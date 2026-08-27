"""
Local to Plexamp Integration Engine
Recursively scans local folders for audio files (.mp3, .flac, .m4a, .wav, .aac, .ogg, .opus, .wma),
extracts existing metadata / cleans filenames, enriches metadata via iTunes Search API and LRCLIB,
applies Plexamp-compatible tags (ID3v2.4 / FLAC / MP4), generates .lrc lyrics, calculates ReplayGain,
and organizes into standard Plex music folders (Music / Artist / Album / 01 - Title.ext).
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
import mutagen

from spotify_sync import (
    PlexampTagger,
    ReplayGainCalculator,
    LyricsFetcher,
    sanitize_filename,
    safe_move_file,
    safe_save_tags
)
from youtube_sync import YouTubeTitleCleaner, YouTubeMetadataEnricher

BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
CREATION_FLAGS_BACKGROUND = (
    (subprocess.CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS)
    if os.name == 'nt' else 0
)

SUPPORTED_AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".m4a", ".aac", ".wav", ".ogg", ".opus", ".wma", ".aiff", ".alac"
}


class LocalAudioScanner:
    """Recursively scans folders for audio files and extracts metadata."""

    @classmethod
    def scan_directory(cls, root_dir: str) -> Dict:
        """
        Recursively walks root_dir, extracts existing metadata or filename cues,
        and returns a collection dict compatible with the Plexamp pipeline.
        """
        if not os.path.exists(root_dir) or not os.path.isdir(root_dir):
            raise ValueError(f"Directory not found: {root_dir}")

        found_files: List[str] = []
        for root, _, files in os.walk(root_dir):
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in SUPPORTED_AUDIO_EXTENSIONS:
                    found_files.append(os.path.join(root, file))

        found_files.sort()
        if not found_files:
            raise RuntimeError(f"No supported audio files found in: {root_dir}")

        parsed_tracks = []
        for idx, file_path in enumerate(found_files, start=1):
            info = cls.extract_file_metadata(file_path, root_dir, idx, len(found_files))
            parsed_tracks.append(info)

        folder_name = os.path.basename(os.path.normpath(root_dir)) or "Local Music Collection"

        return {
            "id": f"local_{abs(hash(root_dir))}",
            "title": folder_name,
            "author": "Local Files",
            "source_dir": root_dir,
            "cover_url": "",
            "track_count": len(parsed_tracks),
            "tracks": parsed_tracks,
            "is_playlist": False
        }

    @classmethod
    def extract_file_metadata(cls, file_path: str, root_dir: str, seq_num: int, total_count: int) -> Dict:
        """Extracts embedded tags or falls back to smart filename cleaning."""
        ext = os.path.splitext(file_path)[1].lower()
        filename_no_ext = os.path.splitext(os.path.basename(file_path))[0]
        rel_path = os.path.relpath(file_path, root_dir)

        raw_title = ""
        raw_artist = ""
        raw_album = ""
        raw_track_num = seq_num
        raw_year = ""
        dur_ms = 0

        # 1. Try reading embedded tags via Mutagen
        try:
            audio = mutagen.File(file_path, easy=True)
            if audio is not None:
                if audio.info and hasattr(audio.info, 'length'):
                    dur_ms = int(audio.info.length * 1000)

                raw_title = cls._first_tag(audio.get("title"))
                raw_artist = cls._first_tag(audio.get("artist"))
                raw_album = cls._first_tag(audio.get("album"))
                raw_year = cls._first_tag(audio.get("date")) or cls._first_tag(audio.get("year"))

                trck_tag = cls._first_tag(audio.get("tracknumber"))
                if trck_tag:
                    # Could be "3" or "3/12"
                    m = re.match(r'(\d+)', str(trck_tag))
                    if m:
                        raw_track_num = int(m.group(1))
        except Exception:
            pass

        # 2. Check if embedded tags are valid or if filename should be used
        is_generic_title = not raw_title or raw_title.lower() in [
            "track", "track 1", "audio", "unknown", "untitled", filename_no_ext.lower()
        ]

        if is_generic_title or not raw_artist:
            # Clean filename
            cleaned_stem = re.sub(r'^\d+[\s\.\-_]+', '', filename_no_ext)  # strip leading track numbers e.g. "01. "
            parsed_artist, parsed_title = YouTubeTitleCleaner.parse_artist_and_title(cleaned_stem, uploader="")
            if is_generic_title:
                raw_title = parsed_title or filename_no_ext
            if not raw_artist or raw_artist.lower() in ["unknown", "unknown artist"]:
                raw_artist = parsed_artist or "Unknown Artist"

        if not raw_artist:
            raw_artist = "Unknown Artist"
        if not raw_title:
            raw_title = filename_no_ext

        # Clean year
        if raw_year and len(raw_year) >= 4:
            raw_year = raw_year[:4]
        else:
            raw_year = ""

        return {
            "id": f"loc_{seq_num}",
            "file_path": file_path,
            "rel_path": rel_path,
            "filename": os.path.basename(file_path),
            "ext": ext,
            "title": raw_title,
            "artist": raw_artist,
            "album": raw_album or "Singles",
            "album_artist": raw_artist,
            "track_number": raw_track_num,
            "total_tracks": total_count,
            "year": raw_year,
            "release_date": raw_year,
            "duration_ms": dur_ms,
            "cover_url": "",
            "has_embedded_art": cls.has_embedded_artwork(file_path)
        }

    @staticmethod
    def _first_tag(val) -> str:
        if isinstance(val, list) and len(val) > 0:
            return str(val[0]).strip()
        if isinstance(val, str):
            return val.strip()
        return ""

    @staticmethod
    def has_embedded_artwork(file_path: str) -> bool:
        """Checks if the audio file already has embedded artwork."""
        try:
            ext = os.path.splitext(file_path)[1].lower()
            if ext == ".mp3":
                from mutagen.id3 import ID3
                tags = ID3(file_path)
                return len(tags.getall("APIC")) > 0
            elif ext == ".flac":
                from mutagen.flac import FLAC
                audio = FLAC(file_path)
                return len(audio.pictures) > 0
            elif ext in [".m4a", ".mp4", ".aac"]:
                from mutagen.mp4 import MP4
                audio = MP4(file_path)
                return "covr" in audio and len(audio["covr"]) > 0
        except Exception:
            pass
        return False

    @staticmethod
    def extract_embedded_artwork(file_path: str, output_path: str) -> bool:
        """Extracts existing embedded front artwork to a JPEG file."""
        try:
            ext = os.path.splitext(file_path)[1].lower()
            if ext == ".mp3":
                from mutagen.id3 import ID3
                tags = ID3(file_path)
                pics = tags.getall("APIC")
                if pics:
                    with open(output_path, "wb") as f:
                        f.write(pics[0].data)
                    return True
            elif ext == ".flac":
                from mutagen.flac import FLAC
                audio = FLAC(file_path)
                if audio.pictures:
                    with open(output_path, "wb") as f:
                        f.write(audio.pictures[0].data)
                    return True
            elif ext in [".m4a", ".mp4", ".aac"]:
                from mutagen.mp4 import MP4
                audio = MP4(file_path)
                if "covr" in audio and audio["covr"]:
                    with open(output_path, "wb") as f:
                        f.write(bytes(audio["covr"][0]))
                    return True
        except Exception:
            pass
        return False


class LocalPlexampPipeline:
    """Coordinates local file ingestion, iTunes metadata enrichment, tagging, lyrics, ReplayGain, and Plex folder structure."""

    def __init__(
        self,
        ffmpeg_exe: str,
        log_callback: Callable[[str, bool], None],
        progress_callback: Callable[[float, str], None],
        track_status_callback: Optional[Callable[[int, str, str], None]] = None
    ):
        self.ffmpeg_exe = ffmpeg_exe
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
        target_extension: str = "mp3",
        folder_structure: str = "plex_standard"
    ) -> Tuple[str, str, str]:
        """Returns (dest_dir, dest_filename, final_file_path)."""
        t_artist = track.get("album_artist") or track.get("artist", "Unknown Artist")
        t_album = track.get("album", "Singles")
        t_title = track.get("title", "Unknown Track")
        t_num = int(track.get("track_number", 1))
        disc_num = int(track.get("disc_number", 1))
        total_discs = int(track.get("total_discs", 1))

        clean_artist = sanitize_filename(t_artist)
        clean_album = sanitize_filename(t_album)
        clean_title = sanitize_filename(t_title)
        ext = target_extension.lstrip('.')

        if folder_structure == "plex_standard":
            if disc_num > 1 or total_discs > 1:
                dest_dir = os.path.join(base_music_dir, clean_artist, clean_album, f"Disc {disc_num:02d}")
            else:
                dest_dir = os.path.join(base_music_dir, clean_artist, clean_album)
            dest_filename = f"{t_num:02d} - {clean_title}.{ext}"
        else:
            plist_name = sanitize_filename(collection.get("title", "Imported Music"))
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
        target_extension: str = "mp3",
        folder_structure: str = "plex_standard"
    ) -> bool:
        """Checks if a track already exists in the destination library."""
        _, _, final_path = cls.get_destination_path(base_music_dir, track, collection, target_extension, folder_structure)
        return os.path.exists(final_path) and os.path.getsize(final_path) > 100000

    def process_batch(
        self,
        collection: Dict,
        selected_tracks: List[Dict],
        base_music_dir: str,
        output_format_option: str = "Keep Original (Copy)",
        folder_structure: str = "plex_standard",
        move_files: bool = False,
        embed_art: bool = True,
        save_cover_file: bool = True,
        fetch_lyrics: bool = True,
        calculate_replaygain: bool = True,
        auto_enrich: bool = True,
        concurrency: int = 4
    ) -> Dict[str, int]:
        """
        Processes selected local audio files: enriches tags, converts or copies, applies Plexamp tags & artwork,
        downloads .lrc lyrics, calculates ReplayGain, and writes to Plex hierarchy.
        Returns {"completed": int, "skipped": int, "failed": int}
        """
        self.is_cancelled = False
        stats = {"completed": 0, "skipped": 0, "failed": 0}
        total_selected = len(selected_tracks)
        if total_selected == 0:
            self.log("No files selected for import.", is_error=True)
            return stats

        os.makedirs(base_music_dir, exist_ok=True)
        temp_dir = os.path.join(base_music_dir, ".temp_sma_local_sync")
        os.makedirs(temp_dir, exist_ok=True)

        completed_count = [0]

        def process_single_track(item_tuple):
            if self.is_cancelled:
                return

            seq_idx, track = item_tuple
            src_path = track.get("file_path", "")
            src_ext = track.get("ext", "").lower()
            t_title = track.get("title", "Unknown Track")
            t_artist = track.get("artist", "Unknown Artist")
            t_album = track.get("album", "")
            t_num = track.get("track_number", seq_idx)
            track_index = track.get("_track_index", seq_idx)

            if not os.path.exists(src_path):
                with self._lock:
                    self.log(f"✗ Source file missing: {src_path}", is_error=True)
                    stats["failed"] += 1
                    completed_count[0] += 1
                    pct = completed_count[0] / total_selected
                    self.progress_cb(pct, f"[{completed_count[0]}/{total_selected}] Missing: {t_title}")
                    if self.track_status_cb:
                        self.track_status_cb(track_index, "✗ Missing", "#FB7185")
                return

            # Determine Target Format & Extension
            if "flac" in output_format_option.lower():
                target_ext = ".flac"
            elif "m4a" in output_format_option.lower():
                target_ext = ".m4a"
            elif "mp3" in output_format_option.lower():
                target_ext = ".mp3"
            else:
                # "Keep Original"
                if src_ext in [".mp3", ".flac", ".m4a"]:
                    target_ext = src_ext
                else:
                    # Non-standard source format (wav, ogg, wma, aiff) defaults to MP3
                    target_ext = ".mp3"

            # Metadata Enrichment via iTunes & LRCLIB
            if auto_enrich and t_artist != "Unknown Artist":
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
                track["album"] = f"{t_title} - Single" if folder_structure == "plex_standard" else collection.get("title", "Imported Music")

            dest_dir, dest_filename, final_file_path = self.get_destination_path(
                base_music_dir, track, collection, target_ext, folder_structure
            )
            os.makedirs(dest_dir, exist_ok=True)

            # Pre-check if already in library
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
                self.track_status_cb(track_index, "Processing...", "#38BDF8")

            temp_work_file = os.path.join(temp_dir, f"proc_{seq_idx}_{sanitize_filename(t_title)}{target_ext}")

            # Transcode or Direct Copy
            needs_transcode = (src_ext != target_ext)
            if needs_transcode:
                if not os.path.exists(self.ffmpeg_exe):
                    with self._lock:
                        self.log(f"✗ ffmpeg.exe required to transcode {src_ext} to {target_ext}", is_error=True)
                        stats["failed"] += 1
                        completed_count[0] += 1
                        if self.track_status_cb:
                            self.track_status_cb(track_index, "✗ No FFmpeg", "#FB7185")
                    return

                # Convert using FFmpeg
                cmd = [self.ffmpeg_exe, "-y", "-i", src_path]
                if target_ext == ".mp3":
                    cmd.extend(["-c:a", "libmp3lame", "-b:a", "320k"])
                elif target_ext == ".flac":
                    cmd.extend(["-c:a", "flac"])
                elif target_ext == ".m4a":
                    cmd.extend(["-c:a", "aac", "-b:a", "256k"])

                cmd.append(temp_work_file)

                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=CREATION_FLAGS_BACKGROUND
                )
                with self._lock:
                    self.active_procs.append(proc)
                proc.communicate()
                with self._lock:
                    if proc in self.active_procs:
                        self.active_procs.remove(proc)
            else:
                # Lossless copy to temp work file
                try:
                    shutil.copy2(src_path, temp_work_file)
                except Exception as e:
                    with self._lock:
                        self.log(f"✗ Copy failed for {src_path}: {e}", is_error=True)
                        stats["failed"] += 1
                        completed_count[0] += 1
                        if self.track_status_cb:
                            self.track_status_cb(track_index, "✗ Copy Error", "#FB7185")
                    return

            if self.is_cancelled:
                return

            if not os.path.exists(temp_work_file):
                with self._lock:
                    self.log(f"✗ Failed to create target file for {t_title}", is_error=True)
                    stats["failed"] += 1
                    completed_count[0] += 1
                    if self.track_status_cb:
                        self.track_status_cb(track_index, "✗ Error", "#FB7185")
                return

            if self.track_status_cb:
                self.track_status_cb(track_index, "Tagging...", "#FBBF24")

            # Cover Art Handling (iTunes 1400x1400 -> Embedded Artwork)
            track_cover_path = None
            if embed_art or save_cover_file:
                t_cover_url = track.get("cover_url")
                raw_cover_path = os.path.join(temp_dir, f"cover_{seq_idx}.jpg")

                if t_cover_url and PlexampTagger.download_cover_art(t_cover_url, raw_cover_path):
                    track_cover_path = raw_cover_path
                elif LocalAudioScanner.has_embedded_artwork(src_path):
                    if LocalAudioScanner.extract_embedded_artwork(src_path, raw_cover_path):
                        track_cover_path = raw_cover_path

            # Lyrics fetching from LRCLIB
            plain_lyrics = ""
            if fetch_lyrics and t_artist != "Unknown Artist":
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
                    self.log(f"Lyrics notice for {t_title}: {e}")

            # ReplayGain calculation
            replaygain = None
            if calculate_replaygain and os.path.exists(self.ffmpeg_exe):
                try:
                    replaygain = ReplayGainCalculator.calculate_replaygain(temp_work_file, self.ffmpeg_exe)
                except Exception as e:
                    self.log(f"ReplayGain notice for {t_title}: {e}")

            # Apply ID3/FLAC/MP4 tags
            PlexampTagger.apply_metadata(
                file_path=temp_work_file,
                track_info=track,
                cover_image_path=track_cover_path if embed_art else None,
                plain_lyrics=plain_lyrics,
                replaygain=replaygain
            )

            # Move tagged audio to final destination safely
            try:
                safe_move_file(temp_work_file, final_file_path)
                if save_cover_file and track_cover_path and os.path.exists(track_cover_path):
                    album_cover_path = os.path.join(dest_dir, "cover.jpg")
                    if not os.path.exists(album_cover_path):
                        try:
                            shutil.copy2(track_cover_path, album_cover_path)
                        except Exception:
                            pass

                # Delete original source file only if move_files is True and final path is valid (>100KB)
                if move_files and os.path.exists(final_file_path) and os.path.getsize(final_file_path) > 100000:
                    if os.path.abspath(src_path) != os.path.abspath(final_file_path):
                        try:
                            os.remove(src_path)
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
                    self.log(f"✗ Failed to organize {dest_filename}: {e}", is_error=True)
                    stats["failed"] += 1
                    completed_count[0] += 1
                    pct = completed_count[0] / total_selected
                    self.progress_cb(pct, f"[{completed_count[0]}/{total_selected}] Save Error: {t_title}")
                    if self.track_status_cb:
                        self.track_status_cb(track_index, "✗ Save Error", "#FB7185")

        # Execute with thread pool concurrency
        indexed_items = [(idx + 1, trk) for idx, trk in enumerate(selected_tracks)]
        workers = max(1, min(concurrency, 6))

        with ThreadPoolExecutor(max_workers=workers) as executor:
            list(executor.map(process_single_track, indexed_items))

        # Cleanup temp directory
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

        return stats
