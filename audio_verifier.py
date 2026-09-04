"""
Audio Fact-Checker & Acoustic Verifier Module
Recursively scans music libraries, runs acoustic waveform recognition via Shazam,
compares recognized audio against embedded ID3/FLAC/MP4 tags, detects discrepancies/mismatches,
and provides 1-click re-tagging, cover art downloading, .lrc lyrics generation,
and folder re-organization for Plexamp.
"""

import argparse
import asyncio
import csv
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import subprocess
import ssl
import urllib.parse
import urllib.request

# Ensure local ffmpeg.exe is in PATH
base_dir = os.path.dirname(os.path.abspath(__file__))
if base_dir not in [os.path.abspath(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p]:
    os.environ["PATH"] = base_dir + os.pathsep + os.environ.get("PATH", "")

CREATION_FLAGS_BACKGROUND = (
    (subprocess.CREATE_NO_WINDOW | 0x00004000)
    if os.name == 'nt' else 0
)

import mutagen  # noqa: E402
from spotify_sync import (  # noqa: E402
    LyricsFetcher,
    PlexampTagger,
    ReplayGainCalculator,
    safe_move_file,
    sanitize_filename
)

try:
    from shazamio import Shazam  # noqa: E402
    HAS_SHAZAM = True
except ImportError:
    HAS_SHAZAM = False

SUPPORTED_AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".m4a", ".aac", ".wav", ".ogg", ".opus", ".wma", ".aiff", ".alac"
}

VALID_CACHE_STATUSES = {
    "VERIFIED", "MISMATCH", "COVER_DETECTED", "WRONG_TRACK", "METADATA_TYPO", "DURATION_MISMATCH", "UNRECOGNIZED"
}


def normalize_text(text: str) -> str:
    """Normalizes string for fuzzy comparison by removing noise, feats, remasters, punctuation."""
    if not text:
        return ""
    s = text.lower().strip()
    # Remove featuring blocks
    s = re.sub(r'[\(\[\{]\s*(feat\.?|ft\.?|featuring)[^\)\]\}]*[\)\]\}]', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\s+(feat\.?|ft\.?|featuring)\s+.*$', '', s, flags=re.IGNORECASE)
    # Remove common tags
    s = re.sub(r'[\(\[\{]\s*(remaster(ed)?|live|official|audio|video|explicit|clean|deluxe|bonus|version|mix|edit|mono|stereo)[^\)\]\}]*[\)\]\}]', '', s, flags=re.IGNORECASE)
    # Remove track numbers at start
    s = re.sub(r'^\d+[\s\.\-_]+', '', s)
    # Replace punctuation and symbols with single space
    s = re.sub(r'[^a-z0-9\s]', ' ', s)
    # Collapse whitespace
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def is_censored_match(s1: str, s2: str) -> bool:
    """Checks if s2 is an asterisk/bullet censored version of s1 (e.g. Dickhead vs D******d)."""
    if not s1 or not s2:
        return False
    w1 = s1.lower().strip()
    w2 = s2.lower().strip()
    if w1 == w2:
        return True
    if '*' in w2 or '•' in w2:
        p = re.escape(w2).replace(r'\*', '.').replace(r'\•', '.')
        try:
            if re.fullmatch(p, w1):
                return True
        except Exception:
            pass
    if '*' in w1 or '•' in w1:
        p = re.escape(w1).replace(r'\*', '.').replace(r'\•', '.')
        try:
            if re.fullmatch(p, w2):
                return True
        except Exception:
            pass
    return False


def string_similarity(s1: str, s2: str) -> float:
    """Computes token set similarity ratio between two normalized strings with censorship handling."""
    if is_censored_match(s1, s2):
        return 1.0

    n1 = normalize_text(s1)
    n2 = normalize_text(s2)
    if not n1 and not n2:
        return 1.0
    if not n1 or not n2:
        return 0.0
    if n1 == n2 or is_censored_match(n1, n2):
        return 1.0
    if n1 in n2 or n2 in n1:
        return 0.90

    tokens1 = set(n1.split())
    tokens2 = set(n2.split())
    if not tokens1 or not tokens2:
        return 0.0

    intersection = tokens1.intersection(tokens2)
    union = tokens1.union(tokens2)
    return len(intersection) / len(union)


def fetch_reference_metadata(artist: str, title: str) -> Optional[Dict]:
    """Queries iTunes Catalog API for canonical studio track info and duration in ms."""
    if not artist or not title:
        return None
    try:
        clean_t = re.sub(r'\s*-\s*(Remastered|Remaster|Live|Single Version).*$', '', title, flags=re.IGNORECASE).strip()
        query = f"{artist} {clean_t}"
        url = f"https://itunes.apple.com/search?term={urllib.parse.quote(query)}&entity=song&limit=3"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, context=ctx, timeout=4) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            results = data.get("results", [])
            if results:
                top = results[0]
                return {
                    "artist": top.get("artistName", ""),
                    "title": top.get("trackName", ""),
                    "album": top.get("collectionName", ""),
                    "duration_ms": int(top.get("trackTimeMillis", 0)),
                    "release_date": top.get("releaseDate", "")[:10],
                    "cover_url": (top.get("artworkUrl100") or "").replace("100x100bb", "640x640bb")
                }
    except Exception:
        pass
    return None


def slice_audio_segment(file_path: str, offset_seconds: float = 30.0, duration_seconds: float = 12.0) -> Optional[bytes]:
    """Extracts a slice from file_path as MP3 bytes using bundled ffmpeg for fast acoustic scanning."""
    norm_path = os.path.normpath(file_path)
    if not os.path.exists(norm_path):
        return None
    try:
        ffmpeg_bin = os.path.join(base_dir, "ffmpeg.exe") if os.path.exists(os.path.join(base_dir, "ffmpeg.exe")) else "ffmpeg"
        cmd = [
            ffmpeg_bin,
            "-threads", "2",
            "-nostats",
            "-loglevel", "error",
            "-ss", f"{max(0.0, offset_seconds):.2f}",
            "-t", f"{duration_seconds:.2f}",
            "-i", norm_path,
            "-f", "mp3",
            "-ac", "2",
            "-ar", "44100",
            "pipe:1"
        ]
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        proc = subprocess.run(cmd, capture_output=True, creationflags=flags, timeout=12)
        if proc.returncode == 0 and len(proc.stdout) > 1000:
            return proc.stdout
    except Exception:
        pass
    return None


# Trackable error logging & Shazam rate-limit pacing
_shazam_rate_lock = threading.Lock()
_last_shazam_request_time = 0.0

def log_fact_checker_error(file_path: str, error_type: str, details: str):
    """Appends error events to a persistent trackable fact_checker_errors.log file."""
    try:
        log_path = os.path.join(base_dir, "fact_checker_errors.log")
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] [{error_type}] {os.path.basename(file_path)}\n")
            f.write(f"    Path: {file_path}\n")
            f.write(f"    Detail: {details}\n\n")
    except Exception:
        pass

def pace_shazam_request(min_interval: float = 0.9):
    """Ensures at least min_interval seconds between consecutive Shazam API queries across all threads."""
    global _last_shazam_request_time
    with _shazam_rate_lock:
        now = time.time()
        elapsed = now - _last_shazam_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        _last_shazam_request_time = time.time()


class AudioFactChecker:
    """Acoustic recognition, library verification, and fact-checking engine."""

    def __init__(self, ffmpeg_path: Optional[str] = None):
        self.ffmpeg_path = ffmpeg_path
        if self.ffmpeg_path and os.path.exists(self.ffmpeg_path):
            os.environ["PATH"] = os.path.dirname(os.path.abspath(self.ffmpeg_path)) + os.pathsep + os.environ.get("PATH", "")

    @staticmethod
    def extract_embedded_metadata(file_path: str) -> Dict:
        """Extracts existing embedded tags using Mutagen."""
        metadata = {
            "title": "",
            "artist": "",
            "album": "",
            "album_artist": "",
            "track_number": 1,
            "total_tracks": 1,
            "disc_number": 1,
            "year": "",
            "genre": "",
            "duration_ms": 0,
            "has_cover": False
        }
        if not os.path.exists(file_path):
            return metadata

        filename_stem = os.path.splitext(os.path.basename(file_path))[0]
        try:
            audio = mutagen.File(file_path, easy=True)
            if audio is not None:
                if audio.info and hasattr(audio.info, "length"):
                    metadata["duration_ms"] = int(audio.info.length * 1000)

                def _first(val):
                    if isinstance(val, (list, tuple)):
                        return str(val[0]).strip() if val else ""
                    return str(val).strip() if val is not None else ""

                metadata["title"] = _first(audio.get("title")) or filename_stem
                metadata["artist"] = _first(audio.get("artist"))
                metadata["album"] = _first(audio.get("album"))
                metadata["album_artist"] = _first(audio.get("albumartist")) or _first(audio.get("album_artist")) or metadata["artist"]
                metadata["genre"] = _first(audio.get("genre"))
                
                year_val = _first(audio.get("date")) or _first(audio.get("year"))
                if year_val and len(year_val) >= 4:
                    metadata["year"] = year_val[:4]

                trck_val = _first(audio.get("tracknumber"))
                if trck_val:
                    m = re.match(r'(\d+)(?:/(\d+))?', trck_val)
                    if m:
                        metadata["track_number"] = int(m.group(1))
                        if m.group(2):
                            metadata["total_tracks"] = int(m.group(2))

            # Raw check for cover image
            raw_audio = mutagen.File(file_path)
            if raw_audio is not None:
                if hasattr(raw_audio, "tags") and raw_audio.tags:
                    if any(k.startswith("APIC") for k in raw_audio.tags.keys()):
                        metadata["has_cover"] = True
                    elif "covr" in raw_audio.tags:
                        metadata["has_cover"] = True
                if hasattr(raw_audio, "pictures") and raw_audio.pictures:
                    metadata["has_cover"] = True

        except Exception as e:
            metadata["title"] = filename_stem
            metadata["error"] = str(e)

        return metadata

    @classmethod
    async def recognize_audio_async(cls, file_path: str, timeout: float = 12.0, deep_scan: bool = True) -> Dict:
        """Runs acoustic waveform recognition via Shazam with pacing, rate-limit protection, and mid-track sweet-spot sampling."""
        if not HAS_SHAZAM:
            return {"matched": False, "error": "shazamio package is not installed"}

        norm_path = os.path.normpath(file_path)
        if not os.path.exists(norm_path):
            log_fact_checker_error(norm_path, "FILE_NOT_FOUND", "Audio file could not be accessed.")
            return {"matched": False, "error": f"File not found: {file_path}"}

        shazam = Shazam()

        # Enforce rate-limit pacing so Apple/Shazam never triggers HTTP 429
        pace_shazam_request(min_interval=0.9)

        # Get file duration to find optimal acoustic sweet-spot
        file_duration_s = 0.0
        try:
            aud = mutagen.File(norm_path)
            if aud and aud.info and hasattr(aud.info, "length"):
                file_duration_s = float(aud.info.length)
        except Exception:
            pass

        track = {}
        # 1. Fast slice recognition (extracts 11s snippet at ~25% or 20s in - finishes in <0.5s)
        first_offset = max(8.0, min(file_duration_s * 0.25, file_duration_s - 15.0)) if file_duration_s > 20.0 else 10.0
        slice_bytes = slice_audio_segment(norm_path, offset_seconds=first_offset, duration_seconds=11.0)
        if slice_bytes:
            try:
                out = await asyncio.wait_for(shazam.recognize(slice_bytes), timeout=6.0)
                track = out.get("track", {})
            except (asyncio.TimeoutError, TimeoutError):
                pass
            except Exception as e:
                err_str = str(e)
                if "429" in err_str:
                    log_fact_checker_error(norm_path, "RATE_LIMIT_429", "Shazam API rate limit reached (HTTP 429). Cooldown required.")
                    return {"matched": False, "error": "Shazam rate limit (HTTP 429). Temporary cooldown required."}
                else:
                    log_fact_checker_error(norm_path, "RECOGNIZE_ERROR", err_str)

        # 2. Deep mid-track sampling if first slice didn't match (sample chorus at 50%)
        if (not track or not track.get("title")) and deep_scan and file_duration_s > 30.0:
            second_offset = max(15.0, min(file_duration_s * 0.50, file_duration_s - 15.0))
            slice_bytes2 = slice_audio_segment(norm_path, offset_seconds=second_offset, duration_seconds=11.0)
            if slice_bytes2:
                try:
                    pace_shazam_request(min_interval=0.9)
                    out2 = await asyncio.wait_for(shazam.recognize(slice_bytes2), timeout=6.0)
                    t2 = out2.get("track", {})
                    if t2 and t2.get("title"):
                        track = t2
                except Exception:
                    pass

        # 3. Fallback to whole-file recognition only if slicing produced no audio bytes
        if (not track or not track.get("title")) and not slice_bytes:
            try:
                out_full = await asyncio.wait_for(shazam.recognize(norm_path), timeout=8.0)
                track = out_full.get("track", {})
            except Exception:
                pass

        if not track or not track.get("title"):
            return {
                "matched": False,
                "title": "",
                "artist": "",
                "album": "",
                "year": "",
                "genre": "",
                "cover_url": "",
                "raw": {}
            }

        title = track.get("title", "")
        artist = track.get("subtitle", "")
        album = ""
        year = ""
        label = ""
        cover_url = track.get("images", {}).get("coverarthq") or track.get("images", {}).get("coverart") or ""

        genres = track.get("genres", {})
        genre = genres.get("primary", "") if isinstance(genres, dict) else ""

        sections = track.get("sections", [])
        for sec in sections:
            if sec.get("type") == "SONG":
                for meta in sec.get("metadata", []):
                    m_title = (meta.get("title") or "").strip().lower()
                    m_text = (meta.get("text") or "").strip()
                    if m_title == "album":
                        album = m_text
                    elif m_title == "released":
                        year = m_text[:4] if len(m_text) >= 4 else m_text
                    elif m_title == "label":
                        label = m_text

        if not album:
            album = title

        return {
            "matched": True,
            "title": title,
            "artist": artist,
            "album": album,
            "year": year,
            "genre": genre,
            "label": label,
            "cover_url": cover_url,
            "shazam_id": track.get("key", ""),
            "raw": track
        }

    @classmethod
    def verify_single_file(
        cls,
        file_path: str,
        timeout: float = 12.0,
        deep_scan: bool = True,
        log_cb: Optional[Callable[[str, bool], None]] = None
    ) -> Dict:
        """Synchronously verifies a single file, comparing embedded tags vs audio match and reference metadata."""
        filename = os.path.basename(file_path)
        norm_path = os.path.normpath(file_path)
        embedded = cls.extract_embedded_metadata(norm_path)
        
        # Run recognition with strict timeout protection
        try:
            rec_result = asyncio.run(
                asyncio.wait_for(
                    cls.recognize_audio_async(norm_path, timeout=timeout, deep_scan=deep_scan),
                    timeout=timeout + 2.0
                )
            )
        except (asyncio.TimeoutError, TimeoutError):
            rec_result = {"matched": False, "error": f"Audio recognition timed out after {int(timeout)}s"}
        except Exception as e:
            rec_result = {"matched": False, "error": str(e)}

        status = "UNRECOGNIZED"
        discrepancy_reason = ""
        artist_sim = 0.0
        title_sim = 0.0
        ref_meta = None

        if rec_result.get("error"):
            err_msg = rec_result.get("error", "Unknown error")
            if "timed out" in err_msg.lower():
                status = "TIMEOUT"
                discrepancy_reason = f"Recognition timed out after {int(timeout)}s (skipped hanging file)"
            else:
                status = "ERROR"
                discrepancy_reason = err_msg
            if log_cb:
                log_cb(f"[{status}] {filename}: {discrepancy_reason}", True)
        elif rec_result.get("matched"):
            v_artist = rec_result.get("artist", "")
            v_title = rec_result.get("title", "")
            e_artist = embedded.get("artist", "")
            e_title = embedded.get("title", "")

            artist_sim = string_similarity(e_artist, v_artist)
            title_sim = string_similarity(e_title, v_title)

            # Check reference metadata from iTunes catalog
            ref_meta = fetch_reference_metadata(e_artist, e_title)
            ref_dur_ms = ref_meta.get("duration_ms", 0) if ref_meta else 0
            file_dur_ms = embedded.get("duration_ms", 0)
            dur_diff_s = abs(file_dur_ms - ref_dur_ms) / 1000.0 if (file_dur_ms > 0 and ref_dur_ms > 0) else 0.0

            # 1. Cover Detection:
            # Song title matches closely, but singing artist differs completely,
            # or recognized title explicitly denotes a cover/tribute
            is_cover = False
            if title_sim >= 0.65 and artist_sim < 0.60:
                is_cover = True
            elif "cover" in v_title.lower() or "tribute" in v_title.lower() or "acoustic version" in v_title.lower():
                if "cover" not in e_title.lower():
                    is_cover = True

            if is_cover:
                status = "COVER_DETECTED"
                discrepancy_reason = f"Cover version detected: Audio performed by '{v_artist}', but tagged as '{e_artist}'"
                if log_cb:
                    log_cb(f"[COVER] {filename} | Tag: '{e_artist} - {e_title}' | Audio Singer: '{v_artist}'", True)
            elif artist_sim < 0.50 and title_sim < 0.50:
                status = "WRONG_TRACK"
                discrepancy_reason = f"Completely wrong audio: Tag '{e_artist} - {e_title}' vs Audio '{v_artist} - {v_title}'"
                if log_cb:
                    log_cb(f"[WRONG AUDIO] {filename} | Tag: '{e_artist} - {e_title}' | Audio: '{v_artist} - {v_title}'", True)
            elif artist_sim >= 0.70 and (0.40 <= title_sim < 0.65):
                status = "METADATA_TYPO"
                discrepancy_reason = f"Tag title variation/typo: Tag '{e_title}' vs Audio '{v_title}'"
                if log_cb:
                    log_cb(f"[TYPO] {filename} | Tag: '{e_title}' vs Audio: '{v_title}'", False)
            elif artist_sim >= 0.70 and title_sim >= 0.65:
                if dur_diff_s >= 25.0:
                    status = "DURATION_MISMATCH"
                    discrepancy_reason = f"Duration mismatch: File is {int(file_dur_ms/1000)}s vs Studio {int(ref_dur_ms/1000)}s (likely music video with skits or live version)"
                    if log_cb:
                        log_cb(f"[DURATION] {filename} | Length diff: {int(dur_diff_s)}s (likely video skit)", True)
                else:
                    status = "VERIFIED"
                    discrepancy_reason = "Audio matches current tags"
                    if log_cb:
                        log_cb(f"[VERIFIED] {filename} -> '{v_artist} - {v_title}'", False)
            else:
                status = "MISMATCH"
                reasons = []
                if artist_sim < 0.70:
                    reasons.append(f"Artist mismatch: Tag '{e_artist}' vs Audio '{v_artist}'")
                if title_sim < 0.65:
                    reasons.append(f"Title mismatch: Tag '{e_title}' vs Audio '{v_title}'")
                discrepancy_reason = "; ".join(reasons)
                if log_cb:
                    log_cb(f"[MISMATCH] {filename} | Tag: '{e_artist} - {e_title}' | Audio: '{v_artist} - {v_title}'", True)
        else:
            status = "UNRECOGNIZED"
            discrepancy_reason = "No acoustic fingerprint match found in database"
            if log_cb:
                log_cb(f"[UNKNOWN] {filename}: No acoustic fingerprint match", False)

        return {
            "file_path": file_path,
            "filename": filename,
            "status": status,
            "discrepancy_reason": discrepancy_reason,
            "artist_similarity": round(artist_sim, 2),
            "title_similarity": round(title_sim, 2),
            "current": embedded,
            "recognized": rec_result,
            "reference": ref_meta
        }

    @classmethod
    def get_cache_path(cls) -> str:
        exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
        return os.path.join(exe_dir, "verifier_cache.json")

    @classmethod
    def load_cache(cls, cache_path: Optional[str] = None) -> Dict:
        path = cache_path or cls.get_cache_path()
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    @classmethod
    def save_cache(cls, cache: Dict, cache_path: Optional[str] = None):
        path = cache_path or cls.get_cache_path()
        try:
            temp_path = path + ".tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=2)
            if os.path.exists(path):
                os.remove(path)
            os.rename(temp_path, path)
        except Exception as e:
            print(f"Error saving verifier cache: {e}")

    @classmethod
    def clear_cache(cls, cache_path: Optional[str] = None):
        path = cache_path or cls.get_cache_path()
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

    @classmethod
    def scan_directory(
        cls,
        root_dir: str,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
        item_cb: Optional[Callable[[Dict], None]] = None,
        active_worker_cb: Optional[Callable[[Dict[int, Dict]], None]] = None,
        log_cb: Optional[Callable[[str, bool], None]] = None,
        cancel_event: Optional[threading.Event] = None,
        max_workers: int = 3,
        per_file_timeout: float = 20.0,
        use_cache: bool = True
    ) -> List[Dict]:
        """
        Recursively scans directory, verifies all audio files concurrently with timeouts,
        automatically resumes from disk cache, and yields progress callbacks.
        """
        if not os.path.exists(root_dir):
            raise ValueError(f"Directory not found: {root_dir}")

        audio_files = []
        for root, _, files in os.walk(root_dir):
            if cancel_event and cancel_event.is_set():
                break
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in SUPPORTED_AUDIO_EXTENSIONS:
                    audio_files.append(os.path.join(root, f))

        total_files = len(audio_files)
        results = []
        completed_count = 0
        lock = threading.Lock()
        active_workers: Dict[int, Dict] = {}

        if log_cb:
            log_cb(f"Discovered {total_files} audio files. Checking fast resume cache...", False)
        if progress_cb:
            progress_cb(0, total_files, f"Discovered {total_files} audio files. Checking cache...")

        # 1. Check persistent cache for fast resume
        cache = cls.load_cache() if use_cache else {}
        unscanned_files = []
        cached_count = 0

        for fp in audio_files:
            if cancel_event and cancel_event.is_set():
                break
            is_cached = False
            if use_cache and fp in cache:
                try:
                    st = os.stat(fp)
                    entry = cache[fp]
                    # Allow 2-second tolerance for SMB network timestamp resolution differences
                    mtime_diff = abs(entry.get("mtime", 0) - st.st_mtime)
                    if mtime_diff <= 2.0 and entry.get("size") == st.st_size:
                        c_res = entry.get("result", {})
                        if c_res.get("status") in VALID_CACHE_STATUSES:
                            results.append(c_res)
                            completed_count += 1
                            cached_count += 1
                            if item_cb:
                                item_cb(c_res)
                            is_cached = True
                except Exception:
                    pass
            if not is_cached:
                unscanned_files.append(fp)

        if cached_count > 0:
            if log_cb:
                log_cb(f"⚡ Fast Resume: Loaded {cached_count}/{total_files} previously verified tracks from cache.", False)
            if progress_cb:
                progress_cb(completed_count, total_files, f"Loaded {cached_count} from cache")

        if not unscanned_files or (cancel_event and cancel_event.is_set()):
            return results

        if log_cb:
            log_cb(f"Scanning remaining {len(unscanned_files)} files in {root_dir} (Timeout per track: {int(per_file_timeout)}s)", False)

        def process_file(file_path: str):
            nonlocal completed_count
            if cancel_event and cancel_event.is_set():
                return None

            tid = threading.get_ident()
            filename = os.path.basename(file_path)
            with lock:
                active_workers[tid] = {
                    "filename": filename,
                    "start_time": time.time(),
                    "status": "Recognizing Audio"
                }
                snapshot = {k: v.copy() for k, v in active_workers.items()}
            
            if active_worker_cb:
                active_worker_cb(snapshot)

            res = None
            try:
                res = cls.verify_single_file(file_path, timeout=per_file_timeout, log_cb=log_cb)
            except Exception as e:
                res = {
                    "file_path": file_path,
                    "filename": filename,
                    "status": "ERROR",
                    "discrepancy_reason": f"Verification error: {e}",
                    "artist_similarity": 0.0,
                    "title_similarity": 0.0,
                    "current": {},
                    "recognized": {"matched": False},
                    "reference": None
                }
                if log_cb:
                    log_cb(f"Error analyzing {filename}: {e}", True)
            finally:
                with lock:
                    active_workers.pop(tid, None)
                    completed_count += 1
                    curr_c = completed_count
                    results.append(res)
                    snapshot = {k: v.copy() for k, v in active_workers.items()}

                    # Store in persistent cache
                    if use_cache and res and res.get("status") in VALID_CACHE_STATUSES:
                        try:
                            st = os.stat(file_path)
                            cache[file_path] = {
                                "mtime": st.st_mtime,
                                "size": st.st_size,
                                "result": res
                            }
                        except Exception:
                            pass

                if progress_cb:
                    progress_cb(curr_c, total_files, filename)

                if item_cb and res:
                    item_cb(res)

                if active_worker_cb:
                    active_worker_cb(snapshot)

                # Periodically flush cache to disk every 2 completed tracks
                if use_cache and curr_c % 2 == 0:
                    with lock:
                        cls.save_cache(cache)

            return res

        workers = max(1, min(max_workers, 5))
        try:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [executor.submit(process_file, fp) for fp in unscanned_files]
                for f in futures:
                    if cancel_event and cancel_event.is_set():
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
                    try:
                        f.result()
                    except Exception as e:
                        if log_cb:
                            log_cb(f"Task error on file: {e}", True)
        finally:
            if use_cache:
                with lock:
                    cls.save_cache(cache)

        return results

    @classmethod
    def fix_and_retag(
        cls,
        file_path: str,
        verified_info: Dict,
        destination_root: Optional[str] = None,
        reorganize: bool = True,
        progress_cb: Optional[Callable[[str], None]] = None
    ) -> Dict:
        """
        Applies verified metadata (Artist, Title, Album, Year, Genre),
        downloads cover art, fetches synchronized .lrc lyrics,
        calculates ReplayGain, and optionally moves into standard Plexamp structure.
        """
        if not os.path.exists(file_path):
            return {"success": False, "error": f"File does not exist: {file_path}"}

        rec = verified_info.get("recognized", {})
        if not rec.get("matched"):
            return {"success": False, "error": "No verified acoustic match available for this track."}

        v_title = rec.get("title") or verified_info.get("current", {}).get("title", "Unknown Track")
        v_artist = rec.get("artist") or verified_info.get("current", {}).get("artist", "Unknown Artist")
        v_album = rec.get("album") or rec.get("title") or "Unknown Album"
        v_year = rec.get("year") or verified_info.get("current", {}).get("year", "")
        v_genre = rec.get("genre") or ""
        v_cover_url = rec.get("cover_url", "")
        track_num = verified_info.get("current", {}).get("track_number", 1)

        if progress_cb:
            progress_cb(f"Re-tagging: {v_artist} - {v_title}")

        temp_cover_path = None
        try:
            # 1. Download cover art if available
            if v_cover_url:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_img:
                    temp_cover_path = tmp_img.name
                if not PlexampTagger.download_cover_art(v_cover_url, temp_cover_path):
                    if os.path.exists(temp_cover_path):
                        os.remove(temp_cover_path)
                    temp_cover_path = None

            # 2. Fetch lyrics from LRCLIB
            lyrics_data = LyricsFetcher.fetch_lyrics(v_artist, v_title, v_album)
            plain_lyrics = lyrics_data.get("plain_lyrics", "")
            synced_lyrics = lyrics_data.get("synced_lyrics", "")

            # 3. Calculate ReplayGain
            replaygain = None
            try:
                gain_val, peak_val = ReplayGainCalculator.calculate_replaygain(file_path)
                if gain_val:
                    replaygain = (gain_val, peak_val)
            except Exception:
                pass

            # 4. Construct track info payload
            track_payload = {
                "title": v_title,
                "artist": v_artist,
                "artists": [v_artist],
                "album": v_album,
                "album_artist": v_artist,
                "track_number": track_num,
                "total_tracks": verified_info.get("current", {}).get("total_tracks", 1),
                "disc_number": verified_info.get("current", {}).get("disc_number", 1),
                "year": v_year,
                "release_date": v_year,
                "genre": v_genre
            }

            # Apply metadata tags
            PlexampTagger.apply_metadata(
                file_path=file_path,
                track_info=track_payload,
                cover_image_path=temp_cover_path,
                plain_lyrics=plain_lyrics,
                replaygain=replaygain
            )

            # Write .lrc file alongside audio file
            lrc_base = os.path.splitext(file_path)[0]
            lrc_path = f"{lrc_base}.lrc"
            if synced_lyrics:
                try:
                    with open(lrc_path, "w", encoding="utf-8") as lf:
                        lf.write(synced_lyrics)
                except Exception as e:
                    print(f"Failed to write .lrc file: {e}")

            # 5. Re-organize / move file to correct folder if requested
            new_file_path = file_path
            new_lrc_path = lrc_path if os.path.exists(lrc_path) else None

            if reorganize and destination_root and os.path.exists(destination_root):
                orig_dir = os.path.dirname(os.path.abspath(file_path))
                ext = os.path.splitext(file_path)[1].lower()
                clean_artist = sanitize_filename(v_artist)
                clean_album = sanitize_filename(v_album)
                clean_title = sanitize_filename(v_title)

                target_dir = os.path.join(destination_root, clean_artist, clean_album)
                os.makedirs(target_dir, exist_ok=True)

                track_prefix = f"{track_num:02d} - " if track_num else ""
                target_filename = f"{track_prefix}{clean_title}{ext}"
                target_file_path = os.path.join(target_dir, target_filename)

                # Move audio file
                if os.path.abspath(file_path) != os.path.abspath(target_file_path):
                    safe_move_file(file_path, target_file_path)
                    new_file_path = target_file_path

                # Move .lrc file
                if new_lrc_path and os.path.exists(new_lrc_path):
                    target_lrc_path = os.path.join(target_dir, f"{track_prefix}{clean_title}.lrc")
                    if os.path.abspath(new_lrc_path) != os.path.abspath(target_lrc_path):
                        safe_move_file(new_lrc_path, target_lrc_path)
                        new_lrc_path = target_lrc_path

                # Save cover.jpg in album folder if not present
                target_cover = os.path.join(target_dir, "cover.jpg")
                if temp_cover_path and os.path.exists(temp_cover_path) and not os.path.exists(target_cover):
                    try:
                        shutil.copy2(temp_cover_path, target_cover)
                    except Exception:
                        pass

                # Clean up old empty directory structure if vacated
                try:
                    cls._cleanup_empty_folders(orig_dir, stop_at=destination_root)
                except Exception:
                    pass

            return {
                "success": True,
                "old_path": file_path,
                "new_path": new_file_path,
                "verified_artist": v_artist,
                "verified_title": v_title,
                "verified_album": v_album
            }

        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            if temp_cover_path and os.path.exists(temp_cover_path):
                try:
                    os.remove(temp_cover_path)
                except Exception:
                    pass

    @classmethod
    def redownload_track_audio(
        cls,
        file_path: str,
        intended_artist: str,
        intended_title: str,
        intended_album: str = "",
        destination_root: Optional[str] = None,
        reorganize: bool = False,
        progress_cb: Optional[Callable[[str], None]] = None
    ) -> Dict:
        """
        Re-downloads authentic studio audio for a track using strict duration matching and official audio query,
        tags with Plexamp metadata, lyrics, and ReplayGain, and atomically replaces the file.
        """
        if not os.path.exists(file_path):
            return {"success": False, "error": f"File does not exist: {file_path}"}

        ext = os.path.splitext(file_path)[1].lstrip('.').lower() or "mp3"
        if progress_cb:
            progress_cb(f"Searching official studio audio: {intended_artist} - {intended_title}...")

        # 1. Fetch reference duration and canonical metadata from iTunes
        ref = fetch_reference_metadata(intended_artist, intended_title)
        target_dur_s = (ref.get("duration_ms", 0) / 1000.0) if ref else 0.0
        ref_album = ref.get("album") if (ref and ref.get("album")) else (intended_album or intended_title)
        ref_year = ref.get("release_date", "")[:4] if ref else ""
        ref_cover = ref.get("cover_url", "") if ref else ""

        yt_dlp_bin = os.path.join(base_dir, "yt-dlp.exe") if os.path.exists(os.path.join(base_dir, "yt-dlp.exe")) else "yt-dlp"
        flags = CREATION_FLAGS_BACKGROUND

        # 2. Search candidates via yt-dlp flat-playlist
        search_query = f'"{intended_artist}" "{intended_title}" official audio'
        chosen_id = None

        try:
            inspect_cmd = [
                yt_dlp_bin,
                "--dump-json",
                "--flat-playlist",
                "--default-search", "ytsearch5",
                search_query
            ]
            res = subprocess.run(inspect_cmd, capture_output=True, text=True, creationflags=flags, timeout=15)
            best_diff = 9999.0
            for line in res.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    c_info = json.loads(line)
                    c_id = c_info.get("id")
                    c_title = (c_info.get("title") or "").lower()
                    c_dur = c_info.get("duration") or 0

                    # Filter out covers, karaoke, reaction
                    if "cover" in c_title and "cover" not in intended_title.lower():
                        continue
                    if "karaoke" in c_title or "reaction" in c_title:
                        continue

                    # If target duration known, select closest
                    if target_dur_s > 0 and c_dur > 0:
                        diff = abs(c_dur - target_dur_s)
                        if diff < best_diff and diff <= 15.0:
                            best_diff = diff
                            chosen_id = c_id
                    elif not chosen_id:
                        chosen_id = c_id
                except Exception:
                    continue
        except Exception:
            pass

        target_url = f"https://www.youtube.com/watch?v={chosen_id}" if chosen_id else f"ytsearch1:{search_query}"

        if progress_cb:
            progress_cb(f"Downloading authentic audio: {intended_artist} - {intended_title}...")

        temp_dir = tempfile.mkdtemp(prefix="sma_redl_")
        temp_out = os.path.join(temp_dir, f"audio.%(ext)s")
        aq = "0" if ext in ("flac", "wav") else "5"

        try:
            dl_cmd = [
                yt_dlp_bin,
                "--newline",
                "--no-playlist",
                "-f", "ba/b",
                "--extract-audio",
                "--audio-format", ext,
                "--audio-quality", aq,
                "-o", temp_out,
                target_url
            ]
            dl_proc = subprocess.run(dl_cmd, capture_output=True, text=True, creationflags=flags, timeout=60)

            downloaded_file = None
            for f in os.listdir(temp_dir):
                if f.endswith(f".{ext}") or f.startswith("audio"):
                    downloaded_file = os.path.join(temp_dir, f)
                    break

            if not downloaded_file or not os.path.exists(downloaded_file):
                err_snippet = dl_proc.stderr[:150] if dl_proc.stderr else "Unknown download error"
                return {"success": False, "error": f"Audio download failed: {err_snippet}"}

            if progress_cb:
                progress_cb(f"Applying authentic tags and cover art: {intended_artist} - {intended_title}...")

            # Cover art
            temp_cover = None
            if ref_cover:
                temp_cover = os.path.join(temp_dir, "cover.jpg")
                if not PlexampTagger.download_cover_art(ref_cover, temp_cover):
                    temp_cover = None

            # Lyrics
            lyrics = LyricsFetcher.fetch_lyrics(intended_artist, intended_title, ref_album)
            plain_l = lyrics.get("plain_lyrics", "")
            synced_l = lyrics.get("synced_lyrics", "")

            # ReplayGain
            gain_val = None
            ffmpeg_exe = os.path.join(base_dir, "ffmpeg.exe") if os.path.exists(os.path.join(base_dir, "ffmpeg.exe")) else "ffmpeg"
            try:
                g, p = ReplayGainCalculator.calculate_replaygain(downloaded_file, ffmpeg_exe)
                if g:
                    gain_val = (g, p)
            except Exception:
                pass

            # Tag
            track_payload = {
                "title": intended_title,
                "artist": intended_artist,
                "artists": [intended_artist],
                "album": ref_album,
                "album_artist": intended_artist,
                "track_number": 1,
                "total_tracks": 1,
                "disc_number": 1,
                "year": ref_year,
                "release_date": ref_year
            }
            PlexampTagger.apply_metadata(
                file_path=downloaded_file,
                track_info=track_payload,
                cover_image_path=temp_cover if (temp_cover and os.path.exists(temp_cover)) else None,
                plain_lyrics=plain_l,
                replaygain=gain_val
            )

            # Move/Replace file
            target_final_path = file_path
            if reorganize and destination_root and os.path.exists(destination_root):
                clean_art = sanitize_filename(intended_artist)
                clean_alb = sanitize_filename(ref_album)
                clean_tit = sanitize_filename(intended_title)
                t_dir = os.path.join(destination_root, clean_art, clean_alb)
                os.makedirs(t_dir, exist_ok=True)
                target_final_path = os.path.join(t_dir, f"{clean_tit}.{ext}")

            safe_move_file(downloaded_file, target_final_path)

            # Write .lrc if synced lyrics found
            if synced_l:
                lrc_path = os.path.splitext(target_final_path)[0] + ".lrc"
                try:
                    with open(lrc_path, "w", encoding="utf-8") as lf:
                        lf.write(synced_l)
                except Exception:
                    pass

            return {
                "success": True,
                "file_path": target_final_path,
                "artist": intended_artist,
                "title": intended_title,
                "album": ref_album,
                "year": ref_year
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

    @classmethod
    def quarantine_file_to_sort(
        cls,
        file_path: str,
        destination_root: str,
        sort_folder_name: str = "_SORT_UNMATCHED",
        progress_cb: Optional[Callable[[str], None]] = None
    ) -> Dict:
        """
        Moves an unrecognized, cover, or mismatched audio file to an isolated quarantine folder
        ('_SORT_UNMATCHED') along with its sidecar .lrc lyrics file, and creates a
        .plexignore file with '*' so Plexamp / Plex will ignore the folder until reviewed.
        """
        try:
            if not file_path or not os.path.exists(file_path):
                return {"success": False, "error": f"File not found: {file_path}"}

            quarantine_dir = os.path.join(destination_root, sort_folder_name)
            os.makedirs(quarantine_dir, exist_ok=True)

            # Ensure .plexignore exists so Plex doesn't index quarantined files
            plexignore_path = os.path.join(quarantine_dir, ".plexignore")
            if not os.path.exists(plexignore_path):
                try:
                    with open(plexignore_path, "w", encoding="utf-8") as f:
                        f.write("*\n# Ignore all unmatched quarantined files from Plex library\n")
                except Exception:
                    pass

            old_folder = os.path.dirname(os.path.abspath(file_path))
            filename = os.path.basename(file_path)
            target_path = os.path.join(quarantine_dir, filename)

            # Handle existing filename collisions
            if os.path.exists(target_path) and os.path.abspath(target_path) != os.path.abspath(file_path):
                base_n, ext_n = os.path.splitext(filename)
                target_path = os.path.join(quarantine_dir, f"{base_n}_{int(time.time())}{ext_n}")

            if progress_cb:
                progress_cb(f"Moving to quarantine: {filename} -> {sort_folder_name}/")

            safe_move_file(file_path, target_path)

            # Also move sidecar .lrc if present
            base_old = os.path.splitext(file_path)[0]
            lrc_old = base_old + ".lrc"
            if os.path.exists(lrc_old):
                base_target = os.path.splitext(target_path)[0]
                lrc_target = base_target + ".lrc"
                try:
                    safe_move_file(lrc_old, lrc_target)
                except Exception:
                    pass

            # Cleanup empty source folders
            try:
                cls._cleanup_empty_folders(old_folder, stop_at=destination_root)
            except Exception:
                pass

            return {
                "success": True,
                "old_path": file_path,
                "new_path": target_path,
                "quarantine_dir": quarantine_dir,
                "filename": filename
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @classmethod
    def _cleanup_empty_folders(cls, folder_path: str, stop_at: str):
        """Recursively cleans up empty directories up to stop_at boundary."""
        curr = os.path.abspath(folder_path)
        stop = os.path.abspath(stop_at)
        
        while curr and curr != stop and curr.startswith(stop):
            if os.path.exists(curr) and os.path.isdir(curr):
                remaining = os.listdir(curr)
                # If only non-essential files remain like cover.jpg or empty dirs, remove
                music_files = [
                    f for f in remaining if os.path.splitext(f)[1].lower() in SUPPORTED_AUDIO_EXTENSIONS
                ]
                if not music_files:
                    # Remove all leftover files (like orphaned cover.jpg or .lrc)
                    for f in remaining:
                        f_path = os.path.join(curr, f)
                        if os.path.isfile(f_path):
                            try:
                                os.remove(f_path)
                            except Exception:
                                pass
                        elif os.path.isdir(f_path):
                            try:
                                shutil.rmtree(f_path)
                            except Exception:
                                pass
                    try:
                        os.rmdir(curr)
                    except Exception:
                        break
                else:
                    break
            curr = os.path.dirname(curr)

    @classmethod
    def export_report(cls, results: List[Dict], output_path: str, fmt: str = "json") -> str:
        """Exports verification results to JSON, CSV, or Text file."""
        if fmt.lower() == "json":
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2)
        elif fmt.lower() == "csv":
            with open(output_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Status", "Discrepancy Reason", "Filename", "Current Artist", "Current Title",
                    "Current Album", "Recognized Artist", "Recognized Title", "Recognized Album",
                    "Recognized Year", "File Path"
                ])
                for r in results:
                    curr = r.get("current", {})
                    rec = r.get("recognized", {})
                    writer.writerow([
                        r.get("status", ""),
                        r.get("discrepancy_reason", ""),
                        r.get("filename", ""),
                        curr.get("artist", ""),
                        curr.get("title", ""),
                        curr.get("album", ""),
                        rec.get("artist", ""),
                        rec.get("title", ""),
                        rec.get("album", ""),
                        rec.get("year", ""),
                        r.get("file_path", "")
                    ])
        else:  # Text summary
            with open(output_path, "w", encoding="utf-8") as f:
                f.write("=" * 80 + "\n")
                f.write("SHALLOT MEDIA ARCHIVE - AUDIO FACT-CHECK & VERIFICATION REPORT\n")
                f.write("=" * 80 + "\n\n")
                total = len(results)
                discrepancies = [r for r in results if r.get("status") in ("MISMATCH", "COVER_DETECTED", "WRONG_TRACK", "METADATA_TYPO", "DURATION_MISMATCH")]
                covers = [r for r in results if r.get("status") == "COVER_DETECTED"]
                verified = [r for r in results if r.get("status") == "VERIFIED"]
                unrec = [r for r in results if r.get("status") in ("UNRECOGNIZED", "TIMEOUT", "ERROR")]

                f.write(f"Total Files Scanned: {total}\n")
                f.write(f"Verified (Match):    {len(verified)}\n")
                f.write(f"Covers Detected:     {len(covers)}\n")
                f.write(f"Total Discrepancies: {len(discrepancies)}\n")
                f.write(f"Unrecognized/Errors: {len(unrec)}\n\n")

                if discrepancies:
                    f.write("DISCREPANCY TRACKS (COVERS & MISMATCHES DETECTED):\n")
                    f.write("-" * 80 + "\n")
                    for m in discrepancies:
                        curr = m.get("current", {})
                        rec = m.get("recognized", {})
                        f.write(f"File: {m.get('file_path')}\n")
                        f.write(f"  Status:          [{m.get('status')}]\n")
                        f.write(f"  Current Tag:     {curr.get('artist')} - {curr.get('title')} [{curr.get('album')}]\n")
                        f.write(f"  ACTUAL AUDIO:    {rec.get('artist')} - {rec.get('title')} [{rec.get('album')} ({rec.get('year')})]\n")
                        f.write(f"  Reason:          {m.get('discrepancy_reason')}\n\n")
        return output_path


def main():
    parser = argparse.ArgumentParser(description="Scan and fact-check audio library using acoustic waveform recognition.")
    parser.add_argument("--path", "-p", required=True, help="Music folder or file to scan and verify")
    parser.add_argument("--fix", "-f", action="store_true", help="Automatically re-tag and fix mismatched files")
    parser.add_argument("--reorganize", "-r", action="store_true", help="Reorganize fixed files into Plexamp Artist/Album folder structure")
    parser.add_argument("--output", "-o", default="fact_check_report.json", help="Path to save report output (.json, .csv, .txt)")

    args = parser.parse_args()
    scan_path = os.path.abspath(args.path)

    print(f"[Fact-Checker] Starting deep acoustic scan on: {scan_path}")
    
    if os.path.isfile(scan_path):
        res = AudioFactChecker.verify_single_file(scan_path)
        results = [res]
        print(f"Status: {res['status']}")
        print(f"Reason: {res['discrepancy_reason']}")
        if res.get('recognized', {}).get('matched'):
            rec = res['recognized']
            print(f"Actual Audio Match: {rec.get('artist')} - {rec.get('title')} ({rec.get('album')})")
    else:
        def progress(cur, tot, fn):
            print(f"[{cur}/{tot}] Scanning: {fn}")

        results = AudioFactChecker.scan_directory(scan_path, progress_cb=progress)

    # Summary
    discrepancies = [r for r in results if r.get("status") in ("MISMATCH", "COVER_DETECTED", "WRONG_TRACK", "METADATA_TYPO", "DURATION_MISMATCH")]
    covers = [r for r in results if r.get("status") == "COVER_DETECTED"]
    verified = [r for r in results if r.get("status") == "VERIFIED"]
    unrec = [r for r in results if r.get("status") in ("UNRECOGNIZED", "TIMEOUT", "ERROR")]

    print("\n" + "=" * 60)
    print(f"Scan Complete! Total: {len(results)} | Verified: {len(verified)} | Covers: {len(covers)} | Discrepancies: {len(discrepancies)} | Unrecognized: {len(unrec)}")
    print("=" * 60)

    if discrepancies:
        print("\nDISCREPANCIES FOUND:")
        for m in discrepancies:
            curr = m.get("current", {})
            rec = m.get("recognized", {})
            icon = "🎭" if m.get("status") == "COVER_DETECTED" else "⚠️"
            print(f"{icon}  [{m.get('status')}] {m.get('filename')}")
            print(f"   Tagged As: {curr.get('artist')} - {curr.get('title')} [{curr.get('album')}]")
            print(f"   ACTUAL:    {rec.get('artist')} - {rec.get('title')} [{rec.get('album')} ({rec.get('year')})]\n")

    # Export report
    fmt = "json"
    if args.output.endswith(".csv"):
        fmt = "csv"
    elif args.output.endswith(".txt"):
        fmt = "txt"
    AudioFactChecker.export_report(results, args.output, fmt=fmt)
    print(f"Report exported to: {args.output}")

    # Fix if requested
    if args.fix and discrepancies:
        print(f"\n[Fact-Checker] Fixing {len(discrepancies)} mismatched tracks...")
        dest_root = scan_path if os.path.isdir(scan_path) else os.path.dirname(scan_path)
        for m in discrepancies:
            fp = m.get("file_path")
            res_fix = AudioFactChecker.fix_and_retag(
                file_path=fp,
                verified_info=m,
                destination_root=dest_root,
                reorganize=args.reorganize,
                progress_cb=print
            )
            if res_fix.get("success"):
                print(f"✓ Fixed: {res_fix.get('verified_artist')} - {res_fix.get('verified_title')}")
            else:
                print(f"✗ Failed to fix {fp}: {res_fix.get('error')}")


if __name__ == "__main__":
    main()
