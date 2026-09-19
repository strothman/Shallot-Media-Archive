"""
Core Audio Tagging Engine for Shallot Media Archive (SMArchive).
Provides standardized Plexamp tagging (ID3v2.4 / FLAC Vorbis / MP4 atoms)
and legacy automotive tagging (ID3v2.3) with atomic lock retries.
"""

import os
import ssl
import urllib.request
from typing import Dict, List, Optional, Tuple

import mutagen
from mutagen.id3 import (
    ID3, TIT2, TPE1, TPE2, TALB, TRCK, TPOS, TDRC, TYER, TCMP, USLT, TXXX, APIC, ID3NoHeaderError
)
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4, MP4Cover

from core.utils import safe_save_tags, clean_display_title, clean_display_artist


class PlexampTagger:
    """Tags audio files (MP3, FLAC, M4A) with complete Plexamp-compliant metadata, lyrics & cover art."""

    @staticmethod
    def download_cover_art(url: str, output_path: str) -> bool:
        """Downloads cover art image file."""
        if not url:
            return False
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
                with open(output_path, "wb") as f:
                    f.write(resp.read())
            return True
        except Exception as e:
            print(f"[PlexampTagger] Failed to download cover art from {url}: {e}")
            return False

    @classmethod
    def apply_metadata(
        cls,
        file_path: str,
        track_info: Dict,
        cover_image_path: Optional[str] = None,
        plain_lyrics: str = "",
        replaygain: Optional[Tuple[str, str]] = None
    ) -> bool:
        """
        Applies rich Plexamp ID3/FLAC/MP4 tags to the audio file.
        """
        if not os.path.exists(file_path):
            return False

        ext = os.path.splitext(file_path)[1].lower()

        title = track_info.get("title", "")
        artist = track_info.get("artist", "")
        artists = track_info.get("artists", [artist]) if track_info.get("artists") else [artist]
        album = track_info.get("album", "")
        album_artist = track_info.get("album_artist") or artist
        track_num = int(track_info.get("track_number", 1))
        total_tracks = int(track_info.get("total_tracks", 1))
        disc_num = int(track_info.get("disc_number", 1))
        year = str(track_info.get("year", ""))
        rel_date = str(track_info.get("release_date", year))

        # Check if multiple artists or compilation
        is_compilation = (album_artist != artist and "Various" in album_artist)

        try:
            if ext == ".mp3":
                cls._tag_mp3(
                    file_path, title, artist, artists, album, album_artist,
                    track_num, total_tracks, disc_num, year, rel_date,
                    is_compilation, cover_image_path, plain_lyrics, replaygain
                )
            elif ext == ".flac":
                cls._tag_flac(
                    file_path, title, artist, artists, album, album_artist,
                    track_num, total_tracks, disc_num, year, rel_date,
                    is_compilation, cover_image_path, plain_lyrics, replaygain
                )
            elif ext in [".m4a", ".aac", ".mp4"]:
                cls._tag_mp4(
                    file_path, title, artist, artists, album, album_artist,
                    track_num, total_tracks, disc_num, year, rel_date,
                    is_compilation, cover_image_path, plain_lyrics, replaygain
                )
            return True
        except Exception as e:
            print(f"[PlexampTagger] Tagging failed for {file_path}: {e}")
            return False

    @staticmethod
    def _tag_mp3(
        file_path: str, title: str, artist: str, artists: List[str], album: str,
        album_artist: str, track_num: int, total_tracks: int, disc_num: int,
        year: str, rel_date: str, is_compilation: bool, cover_path: Optional[str],
        plain_lyrics: str = "", replaygain: Optional[Tuple[str, str]] = None
    ):
        try:
            tags = ID3(file_path)
        except ID3NoHeaderError:
            tags = ID3()

        # Clean existing core tags to avoid duplicates
        tags.delall("TIT2")
        tags.delall("TPE1")
        tags.delall("TPE2")
        tags.delall("TALB")
        tags.delall("TRCK")
        tags.delall("TPOS")
        tags.delall("TDRC")
        tags.delall("TYER")
        tags.delall("TCMP")

        # Standard ID3v2.3/2.4 Frames for Plexamp
        tags.add(TIT2(encoding=3, text=title))
        tags.add(TPE1(encoding=3, text="/".join(artists) if len(artists) > 1 else artist))
        tags.add(TPE2(encoding=3, text=album_artist))
        tags.add(TALB(encoding=3, text=album))
        tags.add(TRCK(encoding=3, text=f"{track_num}/{total_tracks}" if total_tracks > 1 else str(track_num)))
        tags.add(TPOS(encoding=3, text=str(disc_num)))
        if rel_date:
            tags.add(TDRC(encoding=3, text=rel_date))
        elif year:
            tags.add(TDRC(encoding=3, text=year))

        if is_compilation:
            tags.add(TCMP(encoding=3, text="1"))

        if plain_lyrics:
            tags.delall("USLT")
            tags.add(USLT(encoding=3, lang='eng', desc='', text=plain_lyrics))

        if replaygain:
            gain_str, peak_str = replaygain
            tags.add(TXXX(encoding=3, desc='REPLAYGAIN_TRACK_GAIN', text=gain_str))
            tags.add(TXXX(encoding=3, desc='REPLAYGAIN_TRACK_PEAK', text=peak_str))

        if cover_path and os.path.exists(cover_path):
            tags.delall("APIC")
            with open(cover_path, "rb") as img_f:
                img_data = img_f.read()
            mime = "image/jpeg" if cover_path.lower().endswith((".jpg", ".jpeg")) else "image/png"
            tags.add(APIC(
                encoding=3,
                mime=mime,
                type=3,  # Front Cover
                desc="Cover",
                data=img_data
            ))

        safe_save_tags(tags, file_path, v2_version=3)

    @staticmethod
    def _tag_flac(
        file_path: str, title: str, artist: str, artists: List[str], album: str,
        album_artist: str, track_num: int, total_tracks: int, disc_num: int,
        year: str, rel_date: str, is_compilation: bool, cover_path: Optional[str],
        plain_lyrics: str = "", replaygain: Optional[Tuple[str, str]] = None
    ):
        audio = FLAC(file_path)
        audio["TITLE"] = title
        audio["ARTIST"] = artists
        audio["ALBUMARTIST"] = album_artist
        audio["ALBUM"] = album
        audio["TRACKNUMBER"] = str(track_num)
        audio["TRACKTOTAL"] = str(total_tracks)
        audio["DISCNUMBER"] = str(disc_num)
        if rel_date:
            audio["DATE"] = rel_date
        elif year:
            audio["DATE"] = year
        if is_compilation:
            audio["COMPILATION"] = "1"

        if plain_lyrics:
            audio["LYRICS"] = plain_lyrics
            audio["UNSYNCEDLYRICS"] = plain_lyrics

        if replaygain:
            gain_str, peak_str = replaygain
            audio["REPLAYGAIN_TRACK_GAIN"] = gain_str
            audio["REPLAYGAIN_TRACK_PEAK"] = peak_str

        if cover_path and os.path.exists(cover_path):
            audio.clear_pictures()
            pic = Picture()
            pic.type = 3  # Front Cover
            pic.mime = "image/jpeg" if cover_path.lower().endswith((".jpg", ".jpeg")) else "image/png"
            with open(cover_path, "rb") as f:
                pic.data = f.read()
            audio.add_picture(pic)

        safe_save_tags(audio)

    @staticmethod
    def _tag_mp4(
        file_path: str, title: str, artist: str, artists: List[str], album: str,
        album_artist: str, track_num: int, total_tracks: int, disc_num: int,
        year: str, rel_date: str, is_compilation: bool, cover_path: Optional[str],
        plain_lyrics: str = "", replaygain: Optional[Tuple[str, str]] = None
    ):
        audio = MP4(file_path)
        audio["\xa9nam"] = title
        audio["\xa9ART"] = ", ".join(artists) if len(artists) > 1 else artist
        audio["aART"] = album_artist
        audio["\xa9alb"] = album
        audio["trkn"] = [(track_num, total_tracks)]
        audio["disk"] = [(disc_num, 1)]
        if rel_date:
            audio["\xa9day"] = rel_date
        elif year:
            audio["\xa9day"] = year
        if is_compilation:
            audio["cpil"] = True

        if plain_lyrics:
            audio["\xa9lyr"] = plain_lyrics

        if replaygain:
            gain_str, peak_str = replaygain
            audio["----:com.apple.iTunes:REPLAYGAIN_TRACK_GAIN"] = gain_str.encode('utf-8')
            audio["----:com.apple.iTunes:REPLAYGAIN_TRACK_PEAK"] = peak_str.encode('utf-8')

        if cover_path and os.path.exists(cover_path):
            with open(cover_path, "rb") as f:
                cov_data = f.read()
            cov_fmt = MP4Cover.FORMAT_JPEG if cover_path.lower().endswith((".jpg", ".jpeg")) else MP4Cover.FORMAT_PNG
            audio["covr"] = [MP4Cover(cov_data, imageformat=cov_fmt)]

        safe_save_tags(audio)


def write_car_optimized_tags(
    file_path: str,
    artist: str,
    title: str,
    album: str,
    track_num: int,
    total_tracks: int
) -> bool:
    """
    Writes clean, automotive-optimized ID3v2.3 (or MP4/FLAC) metadata.
    100% compatible with Ford SYNC (2016 Ford Fusion) and in-dash CD players:
    - Sets ID3v2.3 standard (no ID3v2.4 parse failure)
    - Syncs TRCK frame to match mixtape sequence number (track_num/total_tracks)
    - Sets cohesive TALB album name so car heads group disc as 1 unified album
    - Cleans noise and web junk from song titles and artists
    """
    if not os.path.exists(file_path):
        return False

    ext = os.path.splitext(file_path)[1].lower()
    clean_art = clean_display_artist(artist)
    clean_tit = clean_display_title(title)
    clean_alb = album.strip() or "CD Mixtape"
    trck_str = f"{track_num}/{total_tracks}"

    try:
        if ext == ".mp3":
            try:
                tags = ID3(file_path)
            except Exception:
                tags = ID3()

            tags["TIT2"] = TIT2(encoding=3, text=clean_tit)
            tags["TPE1"] = TPE1(encoding=3, text=clean_art)
            tags["TALB"] = TALB(encoding=3, text=clean_alb)
            tags["TRCK"] = TRCK(encoding=3, text=trck_str)
            tags["TPOS"] = TPOS(encoding=3, text="1/1")
            
            # Save strictly as ID3v2.3 for car stereo compatibility
            tags.save(file_path, v2_version=3)
            return True

        elif ext == ".m4a":
            try:
                m4a = MP4(file_path)
                m4a["\xa9nam"] = clean_tit
                m4a["\xa9ART"] = clean_art
                m4a["\xa9alb"] = clean_alb
                m4a["trkn"] = [(track_num, total_tracks)]
                m4a["disk"] = [(1, 1)]
                m4a.save()
                return True
            except Exception:
                pass

        elif ext == ".flac":
            try:
                flac = FLAC(file_path)
                flac["title"] = clean_tit
                flac["artist"] = clean_art
                flac["album"] = clean_alb
                flac["tracknumber"] = str(track_num)
                flac["totaltracks"] = str(total_tracks)
                flac["discnumber"] = "1"
                flac["totaldiscs"] = "1"
                flac.save()
                return True
            except Exception:
                pass

    except Exception as e:
        print(f"[write_car_optimized_tags] Tagging error for '{file_path}': {e}")

    return False
