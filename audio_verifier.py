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
import io
import json
import os
import re
import shutil
import ssl
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional, Tuple

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

# Ensure local ffmpeg.exe is in PATH
base_dir = os.path.dirname(os.path.abspath(__file__))
if base_dir not in [os.path.abspath(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p]:
    os.environ["PATH"] = base_dir + os.pathsep + os.environ.get("PATH", "")

import mutagen
from mutagen.id3 import ID3, APIC, ID3NoHeaderError, TALB, TCMP, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK, TXXX, USLT
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4, MP4Cover
from PIL import Image

try:
    from shazamio import Shazam
    HAS_SHAZAM = True
except ImportError:
    HAS_SHAZAM = False

from spotify_sync import (
    LyricsFetcher,
    PlexampTagger,
    ReplayGainCalculator,
    safe_move_file,
    safe_save_tags,
    sanitize_filename
)

SUPPORTED_AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".m4a", ".aac", ".wav", ".ogg", ".opus", ".wma", ".aiff", ".alac"
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


def string_similarity(s1: str, s2: str) -> float:
    """Computes token set similarity ratio between two normalized strings."""
    n1 = normalize_text(s1)
    n2 = normalize_text(s2)
    if not n1 and not n2:
        return 1.0
    if not n1 or not n2:
        return 0.0
    if n1 == n2:
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
    async def recognize_audio_async(cls, file_path: str) -> Dict:
        """Runs acoustic waveform recognition via Shazam."""
        if not HAS_SHAZAM:
            return {"error": "shazamio package is not installed"}

        if not os.path.exists(file_path):
            return {"error": f"File not found: {file_path}"}

        try:
            shazam = Shazam()
            out = await shazam.recognize(file_path)
            track = out.get("track", {})
            if not track or not track.get("title"):
                return {
                    "matched": False,
                    "title": "",
                    "artist": "",
                    "album": "",
                    "year": "",
                    "genre": "",
                    "cover_url": "",
                    "raw": out
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
        except Exception as e:
            return {
                "matched": False,
                "error": str(e)
            }

    @classmethod
    def verify_single_file(cls, file_path: str) -> Dict:
        """Synchronously verifies a single file, comparing embedded tags vs audio match."""
        embedded = cls.extract_embedded_metadata(file_path)
        
        # Run recognition
        try:
            rec_result = asyncio.run(cls.recognize_audio_async(file_path))
        except Exception as e:
            rec_result = {"matched": False, "error": str(e)}

        status = "UNRECOGNIZED"
        discrepancy_reason = ""
        artist_sim = 0.0
        title_sim = 0.0

        if rec_result.get("error"):
            status = "ERROR"
            discrepancy_reason = rec_result.get("error", "Unknown error")
        elif rec_result.get("matched"):
            v_artist = rec_result.get("artist", "")
            v_title = rec_result.get("title", "")
            e_artist = embedded.get("artist", "")
            e_title = embedded.get("title", "")

            artist_sim = string_similarity(e_artist, v_artist)
            title_sim = string_similarity(e_title, v_title)

            # Match criteria
            if artist_sim >= 0.70 and title_sim >= 0.65:
                status = "VERIFIED"
                discrepancy_reason = "Audio matches current tags"
            else:
                status = "MISMATCH"
                reasons = []
                if artist_sim < 0.70:
                    reasons.append(f"Artist mismatch: Tag '{e_artist}' vs Audio '{v_artist}'")
                if title_sim < 0.65:
                    reasons.append(f"Title mismatch: Tag '{e_title}' vs Audio '{v_title}'")
                discrepancy_reason = "; ".join(reasons)
        else:
            status = "UNRECOGNIZED"
            discrepancy_reason = "No acoustic fingerprint match found in database"

        return {
            "file_path": file_path,
            "filename": os.path.basename(file_path),
            "status": status,
            "discrepancy_reason": discrepancy_reason,
            "artist_similarity": round(artist_sim, 2),
            "title_similarity": round(title_sim, 2),
            "current": embedded,
            "recognized": rec_result
        }

    @classmethod
    def scan_directory(
        cls,
        root_dir: str,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
        item_cb: Optional[Callable[[Dict], None]] = None,
        cancel_event: Optional[threading.Event] = None,
        max_workers: int = 3
    ) -> List[Dict]:
        """
        Recursively scans directory, verifies all audio files concurrently,
        and yields progress callbacks.
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

        def process_file(file_path: str):
            nonlocal completed_count
            if cancel_event and cancel_event.is_set():
                return None

            res = cls.verify_single_file(file_path)
            with lock:
                completed_count += 1
                curr_c = completed_count
                results.append(res)

            if progress_cb:
                progress_cb(curr_c, total_files, os.path.basename(file_path))

            if item_cb:
                item_cb(res)

            return res

        workers = max(1, min(max_workers, 5))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(process_file, fp) for fp in audio_files]
            for f in futures:
                if cancel_event and cancel_event.is_set():
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                try:
                    f.result()
                except Exception:
                    pass

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
                mismatches = [r for r in results if r.get("status") == "MISMATCH"]
                verified = [r for r in results if r.get("status") == "VERIFIED"]
                unrec = [r for r in results if r.get("status") == "UNRECOGNIZED"]

                f.write(f"Total Files Scanned: {total}\n")
                f.write(f"Verified (Match):    {len(verified)}\n")
                f.write(f"Mismatches (Wrong):  {len(mismatches)}\n")
                f.write(f"Unrecognized:        {len(unrec)}\n\n")

                if mismatches:
                    f.write("MISMATCHED TRACKS (WRONG TAGS DETECTED):\n")
                    f.write("-" * 80 + "\n")
                    for m in mismatches:
                        curr = m.get("current", {})
                        rec = m.get("recognized", {})
                        f.write(f"File: {m.get('file_path')}\n")
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

    print(f"[Fact-Checker] Starting acoustic scan on: {scan_path}")
    
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
    mismatches = [r for r in results if r.get("status") == "MISMATCH"]
    verified = [r for r in results if r.get("status") == "VERIFIED"]
    unrec = [r for r in results if r.get("status") == "UNRECOGNIZED"]

    print("\n" + "=" * 60)
    print(f"Scan Complete! Total: {len(results)} | Verified: {len(verified)} | Mismatches: {len(mismatches)} | Unrecognized: {len(unrec)}")
    print("=" * 60)

    if mismatches:
        print("\nMISMATCHES FOUND:")
        for m in mismatches:
            curr = m.get("current", {})
            rec = m.get("recognized", {})
            print(f"⚠️  {m.get('filename')}")
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
    if args.fix and mismatches:
        print(f"\n[Fact-Checker] Fixing {len(mismatches)} mismatched tracks...")
        dest_root = scan_path if os.path.isdir(scan_path) else os.path.dirname(scan_path)
        for m in mismatches:
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
