"""
YouTube to Plexamp Integration Engine
Handles YouTube / YouTube Music playlist, album, and video extraction,
smart metadata cleaning, iTunes/MusicBrainz enrichment, thumbnail square-cropping,
audio download via yt-dlp, and rich Plexamp-compatible metadata tagging (ID3v2 / FLAC / MP4).
"""

import os
import re
import ssl
import json
import shutil
import urllib.request
import urllib.parse
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple, Callable
from PIL import Image

from spotify_sync import (
    PlexampTagger,
    ReplayGainCalculator,
    LyricsFetcher,
    sanitize_filename,
    safe_move_file
)

BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
CREATION_FLAGS_BACKGROUND = (
    (subprocess.CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS)
    if os.name == 'nt' else 0
)


class YouTubeTitleCleaner:
    """Intelligently cleans noisy YouTube video titles and extracts clean Artist and Song Title."""

    NOISE_PATTERNS = [
        r'\((?:official\s+)?(?:music\s+)?video\)',
        r'\[(?:official\s+)?(?:music\s+)?video\]',
        r'\((?:official\s+)?audio\)',
        r'\[(?:official\s+)?audio\]',
        r'\((?:official\s+)?lyric(?:s)?(?:\s+video)?\)',
        r'\[(?:official\s+)?lyric(?:s)?(?:\s+video)?\]',
        r'\(visualizer\)',
        r'\[visualizer\]',
        r'\(audio\s+visualizer\)',
        r'\[audio\s+visualizer\]',
        r'\[(?:hd|4k|hq|1080p|720p|uhd)\]',
        r'\((?:hd|4k|hq|1080p|720p|uhd)\)',
        r'\(remastered(?:\s+\d{4})?\)',
        r'\[remastered(?:\s+\d{4})?\]',
        r'\((?:explicit|clean|radio\s+edit|extended\s+mix)\)',
        r'\[(?:explicit|clean|radio\s+edit|extended\s+mix)\]',
        r'\[mv\]',
        r'\(mv\)',
        r'\(live(?:\s+at\s+[^)]+)?\)',
        r'\[live(?:\s+at\s+[^\]]+)?\]',
        r'\|\s*official\s*music\s*video.*$',
        r'\|\s*official\s*video.*$',
        r'\|\s*lyrics.*$',
        r'[\(\[]\s*\d+\s*kbps\s*[\)\]]',
        r'[\(\[]\s*(?:flac|mp3|m4a|aac|wav|lossless|cd\s*rip)\s*[\)\]]',
    ]

    @classmethod
    def clean_title_noise(cls, text: str) -> str:
        """Strips common video junk strings."""
        if not text:
            return ""
        cleaned = text
        for pat in cls.NOISE_PATTERNS:
            cleaned = re.sub(pat, '', cleaned, flags=re.IGNORECASE)
        # Clean extra quotes, multiple spaces
        cleaned = re.sub(r'["\u201c\u201d]', '', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        # Clean trailing hyphens or pipes
        cleaned = re.sub(r'[\s\-–—|]+$', '', cleaned).strip()
        return cleaned

    @classmethod
    def parse_artist_and_title(cls, raw_title: str, uploader: str = "") -> Tuple[str, str]:
        """
        Parses a YouTube video title into (artist, title).
        Handles formats like:
        - "Artist - Song Title"
        - "Artist: Song Title"
        - "Artist 'Song Title'"
        - "Song Title" (falls back to uploader as artist)
        """
        raw_cleaned = cls.clean_title_noise(raw_title)

        # Clean uploader name (strip "- Topic", "VEVO", "Official", etc.)
        clean_uploader = re.sub(r'\s*-\s*Topic$', '', uploader, flags=re.IGNORECASE).strip()
        clean_uploader = re.sub(r'VEVO$', '', clean_uploader, flags=re.IGNORECASE).strip()
        clean_uploader = re.sub(r'\s+Official(?:\s+Channel)?$', '', clean_uploader, flags=re.IGNORECASE).strip()

        # Check standard separators " - ", " – ", " — ", " : "
        for sep in [" - ", " – ", " — ", " : "]:
            if sep in raw_cleaned:
                parts = raw_cleaned.split(sep, 1)
                candidate_artist = re.sub(r'^\d+[\s\.\-_]+', '', parts[0]).strip()
                candidate_title = parts[1].strip()
                if candidate_artist and candidate_title:
                    return candidate_artist, candidate_title

        # Check if uploader is present and valid
        if clean_uploader:
            return clean_uploader, raw_cleaned

        return "Unknown Artist", raw_cleaned or raw_title


_ITUNES_METADATA_CACHE: Dict[str, Dict] = {}


class YouTubeMetadataEnricher:
    """Enriches YouTube track info using iTunes Search API and LRCLIB to obtain official album names, years, and square artwork."""

    @staticmethod
    def query_itunes(artist: str, title: str) -> Optional[Dict]:
        """
        Queries the free, public, high-speed iTunes Search API for official song metadata.
        Returns dict with album, album_artist, year, release_date, track_number, total_tracks, cover_url (1400x1400).
        """
        if not artist or not title or artist == "Unknown Artist":
            return None

        cache_key = f"{artist.lower().strip()}|||{title.lower().strip()}"
        if cache_key in _ITUNES_METADATA_CACHE:
            return dict(_ITUNES_METADATA_CACHE[cache_key])

        # Clean title for search (remove 'feat. ...')
        search_title = re.sub(r'\s*\(?(?:feat\.?|ft\.?)\s+[^)]+\)?', '', title, flags=re.IGNORECASE).strip()
        query = f"{artist} {search_title}"
        url = f"https://itunes.apple.com/search?term={urllib.parse.quote(query)}&entity=song&limit=5"

        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(url, headers={"User-Agent": "ShallotMediaArchive/1.1"})
            with urllib.request.urlopen(req, context=ctx, timeout=4) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                results = data.get("results", [])
                if not results:
                    return None

                # Find closest match
                target_title_clean = re.sub(r'[^a-zA-Z0-9]', '', title).lower()
                for item in results:
                    res_title = item.get("trackName", "")
                    res_title_clean = re.sub(r'[^a-zA-Z0-9]', '', res_title).lower()

                    if target_title_clean in res_title_clean or res_title_clean in target_title_clean:
                        # Got a match!
                        artwork = item.get("artworkUrl100", "")
                        # Upgrade resolution from 100x100 to 1400x1400
                        if artwork:
                            artwork_hq = re.sub(r'\d+x\d+bb', '1400x1400bb', artwork)
                        else:
                            artwork_hq = ""

                        rel_date = item.get("releaseDate", "")
                        year = rel_date[:4] if rel_date and len(rel_date) >= 4 else ""

                        res_dict = {
                            "title": item.get("trackName", title),
                            "artist": item.get("artistName", artist),
                            "album_artist": item.get("artistName", artist),
                            "album": item.get("collectionName", f"{title} - Single"),
                            "track_number": item.get("trackNumber", 1),
                            "total_tracks": item.get("trackCount", 1),
                            "disc_number": item.get("discNumber", 1),
                            "release_date": rel_date[:10] if rel_date else year,
                            "year": year,
                            "cover_url": artwork_hq
                        }
                        _ITUNES_METADATA_CACHE[cache_key] = res_dict
                        return dict(res_dict)

                # Fallback to first result if close enough
                first = results[0]
                artwork = first.get("artworkUrl100", "")
                artwork_hq = re.sub(r'\d+x\d+bb', '1400x1400bb', artwork) if artwork else ""
                rel_date = first.get("releaseDate", "")
                year = rel_date[:4] if rel_date and len(rel_date) >= 4 else ""

                res_dict = {
                    "title": first.get("trackName", title),
                    "artist": first.get("artistName", artist),
                    "album_artist": first.get("artistName", artist),
                    "album": first.get("collectionName", f"{title} - Single"),
                    "track_number": first.get("trackNumber", 1),
                    "total_tracks": first.get("trackCount", 1),
                    "disc_number": first.get("discNumber", 1),
                    "release_date": rel_date[:10] if rel_date else year,
                    "year": year,
                    "cover_url": artwork_hq
                }
                _ITUNES_METADATA_CACHE[cache_key] = res_dict
                return dict(res_dict)
        except Exception:
            return None

    @staticmethod
    def crop_square_thumbnail(src_path: str, dst_path: str, target_size: int = 640) -> bool:
        """Crops a 16:9 YouTube thumbnail into a centered 1:1 square for Plexamp."""
        if not os.path.exists(src_path):
            return False
        try:
            with Image.open(src_path) as img:
                img = img.convert("RGB")
                w, h = img.size
                min_dim = min(w, h)
                left = (w - min_dim) // 2
                top = (h - min_dim) // 2
                right = left + min_dim
                bottom = top + min_dim
                cropped = img.crop((left, top, right, bottom))
                cropped = cropped.resize((target_size, target_size), Image.Resampling.LANCZOS)
                cropped.save(dst_path, "JPEG", quality=92)
            return True
        except Exception as e:
            print(f"[YouTubeMetadataEnricher] Thumbnail crop failed: {e}")
            try:
                shutil.copy(src_path, dst_path)
                return True
            except Exception:
                return False


class YouTubeFetcher:
    """Extracts metadata from YouTube/YouTube Music playlists, albums, or videos via yt-dlp."""

    @staticmethod
    def parse_youtube_url(url: str) -> Tuple[str, str]:
        """
        Classifies YouTube URL.
        Returns (url_type, entity_id) where url_type is 'playlist', 'album', or 'video'.
        """
        text = url.strip()
        # Playlist check
        list_match = re.search(r'[?&]list=([a-zA-Z0-9_\-]+)', text)
        if list_match:
            return "playlist", list_match.group(1)

        # Video check (watch?v= or youtu.be/ or shorts/)
        v_match = re.search(r'(?:v=|youtu\.be/|shorts/|embed/)([a-zA-Z0-9_\-]{11})', text)
        if v_match:
            return "video", v_match.group(1)

        return "unknown", ""

    @staticmethod
    def fetch_entity(url: str, yt_dlp_path: str, cookie_args: Optional[List[str]] = None) -> Dict:
        """
        Extracts full playlist/video metadata using yt-dlp in flat-playlist JSON mode.
        Returns a collection dictionary compatible with Plexamp pipeline.
        """
        if not os.path.exists(yt_dlp_path):
            raise FileNotFoundError(f"yt-dlp executable not found at {yt_dlp_path}")

        cmd = [
            yt_dlp_path,
            "--flat-playlist",
            "--dump-single-json",
            "--no-warnings",
            "--no-check-certificates",
            "--ignore-errors"
        ]
        if cookie_args:
            cmd.extend(cookie_args)
        cmd.append(url.strip())

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore',
            creationflags=CREATION_FLAGS_BACKGROUND
        )

        if proc.returncode != 0 and not proc.stdout.strip():
            err_msg = proc.stderr.strip() or "Failed to extract YouTube metadata."
            raise RuntimeError(err_msg)

        try:
            data = json.loads(proc.stdout.strip())
        except Exception as e:
            raise RuntimeError(f"Could not parse YouTube metadata response: {e}")

        # Check if it's a playlist or a single video
        is_playlist = "_type" in data and data["_type"] == "playlist" or "entries" in data
        entries = data.get("entries", []) if is_playlist else [data]

        collection_title = data.get("title") or (data.get("playlist_title") if is_playlist else "YouTube Collection")
        collection_author = data.get("uploader") or data.get("channel") or data.get("playlist_uploader") or "YouTube"
        collection_id = data.get("id") or "yt_collection"

        # Best cover art URL for collection
        collection_thumbnails = data.get("thumbnails", [])
        collection_cover_url = ""
        if collection_thumbnails:
            collection_cover_url = collection_thumbnails[-1].get("url", "")
        elif data.get("thumbnail"):
            collection_cover_url = data.get("thumbnail")

        parsed_tracks = []
        for idx, entry in enumerate(entries, start=1):
            if not entry:
                continue

            raw_title = entry.get("title") or "Unknown Track"
            uploader = entry.get("uploader") or entry.get("channel") or collection_author
            v_id = entry.get("id") or ""
            v_url = entry.get("url") or (f"https://www.youtube.com/watch?v={v_id}" if v_id else "")

            # Check if YouTube Music provided native music tags
            yt_track = entry.get("track")
            yt_artist = entry.get("artist")
            yt_album = entry.get("album")
            yt_year = entry.get("release_year") or (entry.get("upload_date", "")[:4] if entry.get("upload_date") else "")

            if yt_track and yt_artist:
                clean_title = yt_track
                clean_artist = yt_artist
                clean_album = yt_album or collection_title
            else:
                clean_artist, clean_title = YouTubeTitleCleaner.parse_artist_and_title(raw_title, uploader)
                clean_album = yt_album or collection_title

            # Thumbnail
            t_thumbs = entry.get("thumbnails", [])
            t_cover_url = t_thumbs[-1].get("url", "") if t_thumbs else entry.get("thumbnail", "")
            if not t_cover_url and v_id:
                t_cover_url = f"https://i.ytimg.com/vi/{v_id}/maxresdefault.jpg"

            dur_sec = entry.get("duration") or 0
            dur_ms = int(dur_sec * 1000)

            parsed_tracks.append({
                "id": v_id,
                "yt_id": v_id,
                "yt_url": v_url,
                "title": clean_title,
                "artist": clean_artist,
                "album": clean_album,
                "album_artist": clean_artist,
                "track_number": idx,
                "total_tracks": len(entries),
                "duration_ms": dur_ms,
                "year": str(yt_year) if yt_year else "",
                "release_date": str(yt_year) if yt_year else "",
                "cover_url": t_cover_url,
                "uploader": uploader,
                "raw_title": raw_title
            })

        if not parsed_tracks:
            raise RuntimeError("No downloadable tracks found in the provided YouTube link.")

        return {
            "id": collection_id,
            "title": collection_title,
            "author": collection_author,
            "cover_url": collection_cover_url,
            "track_count": len(parsed_tracks),
            "tracks": parsed_tracks,
            "is_playlist": is_playlist
        }


class YouTubePlexampPipeline:
    """Coordinates direct audio download via yt-dlp, iTunes metadata enrichment, tagging, lyrics, ReplayGain, and Plex folder structure."""

    def __init__(
        self,
        yt_dlp_path: str,
        cookie_args: List[str],
        log_callback: Callable[[str, bool], None],
        progress_callback: Callable[[float, str], None],
        track_status_callback: Optional[Callable[[int, str, str], None]] = None
    ):
        self.yt_dlp_path = yt_dlp_path
        self.cookie_args = cookie_args
        self.log = log_callback
        self.progress_cb = progress_callback
        self.track_status_cb = track_status_callback
        self.is_cancelled = False
        self.active_procs: List[subprocess.Popen] = []
        self._lock = threading.Lock()

    def cancel(self):
        self.is_cancelled = True
        with self._lock:
            for proc in self.active_procs:
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        capture_output=True,
                        creationflags=CREATION_FLAGS_BACKGROUND
                    )
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            self.active_procs.clear()

    @staticmethod
    def get_destination_path(
        base_music_dir: str,
        track: Dict,
        collection: Dict,
        audio_format: str = "mp3",
        folder_structure: str = "plex_standard"
    ) -> Tuple[str, str, str]:
        """Returns (dest_dir, dest_filename, final_file_path)."""
        t_artist = track.get("album_artist") or track.get("artist", "Unknown Artist")
        t_album = track.get("album", "YouTube Music")
        t_title = track.get("title", "Unknown Track")
        t_num = int(track.get("track_number", 1))
        disc_num = int(track.get("disc_number", 1))
        total_discs = int(track.get("total_discs", 1))

        clean_artist = sanitize_filename(t_artist)
        clean_album = sanitize_filename(t_album)
        clean_title = sanitize_filename(t_title)
        ext = "flac" if "flac" in audio_format.lower() else ("m4a" if "m4a" in audio_format.lower() else "mp3")

        if folder_structure == "plex_standard":
            if disc_num > 1 or total_discs > 1:
                dest_dir = os.path.join(base_music_dir, clean_artist, clean_album, f"Disc {disc_num:02d}")
            else:
                dest_dir = os.path.join(base_music_dir, clean_artist, clean_album)
            dest_filename = f"{t_num:02d} - {clean_title}.{ext}"
        else:
            plist_name = sanitize_filename(collection.get("title", "YouTube Playlist"))
            dest_dir = os.path.join(base_music_dir, "Playlists", plist_name)
            dest_filename = f"{t_num:02d} - {clean_artist} - {clean_title}.{ext}"

        final_file_path = os.path.join(dest_dir, dest_filename)
        return dest_dir, dest_filename, final_file_path

    @classmethod
    def check_existing_track(
        cls,
        base_music_dir: str,
        track: Dict,
        collection: Dict,
        audio_format: str = "mp3",
        folder_structure: str = "plex_standard"
    ) -> bool:
        """Checks if a track already exists in the destination library."""
        _, _, final_path = cls.get_destination_path(base_music_dir, track, collection, audio_format, folder_structure)
        return os.path.exists(final_path) and os.path.getsize(final_path) > 100000

    def process_playlist(
        self,
        collection: Dict,
        selected_tracks: List[Dict],
        base_music_dir: str,
        audio_format: str = "mp3",
        folder_structure: str = "plex_standard",
        embed_art: bool = True,
        save_cover_file: bool = True,
        fetch_lyrics: bool = True,
        calculate_replaygain: bool = True,
        auto_enrich: bool = True,
        concurrency: int = 2
    ) -> Dict[str, int]:
        """
        Downloads selected YouTube tracks, enriches metadata, applies Plexamp tags, and organizes in destination.
        Returns {"completed": int, "skipped": int, "failed": int}
        """
        self.is_cancelled = False
        stats = {"completed": 0, "skipped": 0, "failed": 0}
        total_selected = len(selected_tracks)
        if total_selected == 0:
            self.log("No tracks selected for download.", is_error=True)
            return stats

        os.makedirs(base_music_dir, exist_ok=True)
        temp_dir = os.path.join(base_music_dir, ".temp_sma_yt_sync")
        os.makedirs(temp_dir, exist_ok=True)

        app_dir = os.path.dirname(self.yt_dlp_path)
        ffmpeg_exe = os.path.join(app_dir, "ffmpeg.exe")

        completed_count = [0]

        def process_single_track(item_tuple):
            if self.is_cancelled:
                return

            seq_idx, track = item_tuple
            t_title = track.get("title", "Unknown Track")
            t_artist = track.get("artist", "Unknown Artist")
            t_album = track.get("album", "")
            t_num = track.get("track_number", seq_idx)
            v_id = track.get("yt_id") or track.get("id", "")
            track_index = track.get("_track_index", seq_idx)

            # Metadata Enrichment via iTunes / LRCLIB
            enriched = None
            if auto_enrich:
                enriched = YouTubeMetadataEnricher.query_itunes(t_artist, t_title)
                if enriched:
                    track["album"] = enriched.get("album", t_album or f"{t_title} - Single")
                    track["album_artist"] = enriched.get("album_artist", t_artist)
                    track["artist"] = enriched.get("artist", t_artist)
                    track["title"] = enriched.get("title", t_title)
                    track["track_number"] = enriched.get("track_number", t_num)
                    track["total_tracks"] = enriched.get("total_tracks", track.get("total_tracks", 1))
                    track["release_date"] = enriched.get("release_date", track.get("release_date", ""))
                    track["year"] = enriched.get("year", track.get("year", ""))
                    if enriched.get("cover_url"):
                        track["cover_url"] = enriched.get("cover_url")
                    t_title = track["title"]
                    t_artist = track["artist"]
                    t_album = track["album"]
                    t_num = track["track_number"]

            if not track.get("album"):
                track["album"] = f"{t_title} - Single" if folder_structure == "plex_standard" else collection.get("title", "YouTube Music")

            dest_dir, dest_filename, final_file_path = self.get_destination_path(
                base_music_dir, track, collection, audio_format, folder_structure
            )
            os.makedirs(dest_dir, exist_ok=True)

            # Pre-check if file already exists in library
            if os.path.exists(final_file_path) and os.path.getsize(final_file_path) > 100000:
                with self._lock:
                    self.log(f"✓ Already in library: {dest_filename}")
                    stats["completed"] += 1
                    completed_count[0] += 1
                    pct = completed_count[0] / total_selected
                    self.progress_cb(pct, f"[{completed_count[0]}/{total_selected}] In library: {t_title}")
                    if self.track_status_cb:
                        self.track_status_cb(track_index, "✓ In Library", "#4ADE80")
                return

            if self.track_status_cb:
                self.track_status_cb(track_index, "Downloading...", "#38BDF8")

            # Direct audio download via yt-dlp
            audio_ext = "flac" if "flac" in audio_format.lower() else ("m4a" if "m4a" in audio_format.lower() else "mp3")
            temp_output_template = os.path.join(temp_dir, f"yt_{v_id}_{seq_idx}.%(ext)s")

            cmd = [
                self.yt_dlp_path,
                "-x",
                "--audio-format", audio_ext,
                "--audio-quality", "0",
                "--no-playlist",
                "--no-warnings",
                "--no-check-certificates",
                "-o", temp_output_template
            ]
            if os.path.exists(ffmpeg_exe):
                cmd.extend(["--ffmpeg-location", app_dir])
            if self.cookie_args:
                cmd.extend(self.cookie_args)

            target_yt_url = track.get("yt_url") or f"https://www.youtube.com/watch?v={v_id}"
            cmd.append(target_yt_url)

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='ignore',
                creationflags=CREATION_FLAGS_BACKGROUND
            )
            with self._lock:
                self.active_procs.append(proc)

            _, stderr = proc.communicate()

            with self._lock:
                if proc in self.active_procs:
                    self.active_procs.remove(proc)

            if self.is_cancelled:
                return

            temp_downloaded_file = os.path.join(temp_dir, f"yt_{v_id}_{seq_idx}.{audio_ext}")
            if not os.path.exists(temp_downloaded_file):
                # Search if yt-dlp saved with slight extension variance
                candidates = [
                    os.path.join(temp_dir, f) for f in os.listdir(temp_dir)
                    if f.startswith(f"yt_{v_id}_{seq_idx}.")
                ]
                if candidates:
                    temp_downloaded_file = candidates[0]
                else:
                    with self._lock:
                        self.log(f"✗ Failed to download '{t_title}' ({target_yt_url}): {stderr[:120]}", is_error=True)
                        stats["failed"] += 1
                        completed_count[0] += 1
                        pct = completed_count[0] / total_selected
                        self.progress_cb(pct, f"[{completed_count[0]}/{total_selected}] Failed: {t_title}")
                        if self.track_status_cb:
                            self.track_status_cb(track_index, "✗ Failed", "#FB7185")
                    return

            if self.track_status_cb:
                self.track_status_cb(track_index, "Tagging...", "#FBBF24")

            # Cover Art handling (iTunes high-res -> YouTube square cropped)
            track_cover_path = None
            if embed_art or save_cover_file:
                t_cover_url = track.get("cover_url")
                raw_cover_path = os.path.join(temp_dir, f"raw_cover_{v_id}.jpg")
                square_cover_path = os.path.join(temp_dir, f"cover_{v_id}.jpg")

                if t_cover_url and PlexampTagger.download_cover_art(t_cover_url, raw_cover_path):
                    # If it came from iTunes, it's already square; if from YouTube, crop to 1:1
                    if "itunes" in t_cover_url or "mzstatic" in t_cover_url:
                        track_cover_path = raw_cover_path
                    else:
                        YouTubeMetadataEnricher.crop_square_thumbnail(raw_cover_path, square_cover_path)
                        track_cover_path = square_cover_path

            # Lyrics fetching from LRCLIB
            plain_lyrics = ""
            if fetch_lyrics:
                try:
                    dur_sec = int(track.get("duration_ms", 0) / 1000)
                    lyric_res = LyricsFetcher.fetch_lyrics(
                        artist=t_artist,
                        title=t_title,
                        album=t_album,
                        duration_s=dur_sec
                    )
                    plain_lyrics = lyric_res.get("plain_lyrics", "")
                    synced_lyrics = lyric_res.get("synced_lyrics", "")

                    if synced_lyrics:
                        lrc_path = os.path.splitext(final_file_path)[0] + ".lrc"
                        with open(lrc_path, "w", encoding="utf-8") as lf:
                            lf.write(synced_lyrics)
                except Exception as e:
                    self.log(f"Lyrics lookup notice for {t_title}: {e}")

            # ReplayGain calculation
            replaygain = None
            if calculate_replaygain and os.path.exists(ffmpeg_exe):
                try:
                    replaygain = ReplayGainCalculator.calculate_replaygain(temp_downloaded_file, ffmpeg_exe)
                except Exception as e:
                    self.log(f"ReplayGain calculation notice for {t_title}: {e}")

            # Apply ID3/FLAC/MP4 tags
            PlexampTagger.apply_metadata(
                file_path=temp_downloaded_file,
                track_info=track,
                cover_image_path=track_cover_path if embed_art else None,
                plain_lyrics=plain_lyrics,
                replaygain=replaygain
            )

            # Move tagged audio to final destination
            try:
                safe_move_file(temp_downloaded_file, final_file_path)
                if save_cover_file and track_cover_path and os.path.exists(track_cover_path):
                    album_cover_path = os.path.join(dest_dir, "cover.jpg")
                    if not os.path.exists(album_cover_path):
                        try:
                            shutil.copy2(track_cover_path, album_cover_path)
                        except Exception:
                            pass

                with self._lock:
                    self.log(f"✓ Tagged for Plexamp: {dest_filename}")
                    stats["completed"] += 1
                    completed_count[0] += 1
                    pct = completed_count[0] / total_selected
                    self.progress_cb(pct, f"[{completed_count[0]}/{total_selected}] Completed: {t_title}")
                    if self.track_status_cb:
                        self.track_status_cb(track_index, "✓ Done", "#4ADE80")
            except Exception as e:
                with self._lock:
                    self.log(f"✗ Failed to save {dest_filename}: {e}", is_error=True)
                    stats["failed"] += 1
                    completed_count[0] += 1
                    pct = completed_count[0] / total_selected
                    self.progress_cb(pct, f"[{completed_count[0]}/{total_selected}] Save Error: {t_title}")
                    if self.track_status_cb:
                        self.track_status_cb(track_index, "✗ Save Error", "#FB7185")

        # Execute with thread pool concurrency
        indexed_items = [(idx + 1, trk) for idx, trk in enumerate(selected_tracks)]
        workers = max(1, min(concurrency, 3))

        with ThreadPoolExecutor(max_workers=workers) as executor:
            list(executor.map(process_single_track, indexed_items))

        # Cleanup temp directory
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

        return stats
