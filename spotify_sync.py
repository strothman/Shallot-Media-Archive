"""
Spotify to Plexamp Integration Engine
Handles Spotify playlist/album/track metadata extraction, YouTube audio matching/download via yt-dlp,
and rich Plexamp-compatible metadata tagging (ID3v2 / FLAC / MP4) with Mutagen.
"""

import os
import re
import sys
import json
import ssl
import shutil
import base64
import urllib.request
import urllib.parse
import subprocess
from typing import Dict, List, Optional, Tuple, Callable

import mutagen
from mutagen.id3 import (
    ID3, TIT2, TPE1, TPE2, TALB, TRCK, TPOS, TDRC, APIC, TCMP, ID3NoHeaderError
)
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4, MP4Cover


def sanitize_filename(name: str, max_len: int = 120) -> str:
    """Removes invalid filesystem characters for Windows/Linux/macOS."""
    if not name:
        return "Unknown"
    # Strip invalid chars: < > : " / \ | ? * and control chars
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name).strip()
    clean = re.sub(r'\s+', ' ', clean)
    clean = clean.rstrip('. ')
    if not clean:
        clean = "Unknown"
    return clean[:max_len]


class SpotifyFetcher:
    """Fetches Spotify metadata via Embed scraping or official Web API."""

    def __init__(self, client_id: str = "", client_secret: str = ""):
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self._api_token: Optional[str] = None
        self._ssl_ctx = ssl.create_default_context()
        self._ssl_ctx.check_hostname = False
        self._ssl_ctx.verify_mode = ssl.CERT_NONE

    @staticmethod
    def parse_spotify_url(url_or_uri: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Parses Spotify URL or URI into (entity_type, entity_id).
        Supports: playlist, album, track.
        """
        text = url_or_uri.strip()
        # URI format: spotify:playlist:37i9dQZF1DXcBWIGoYBM5M
        uri_match = re.match(r'spotify:(playlist|album|track):([a-zA-Z0-9]+)', text)
        if uri_match:
            return uri_match.group(1), uri_match.group(2)

        # URL format: https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?...
        url_match = re.search(r'open\.spotify\.com/(playlist|album|track)/([a-zA-Z0-9]+)', text)
        if url_match:
            return url_match.group(1), url_match.group(2)

        return None, None

    def _get_api_token(self) -> Optional[str]:
        """Obtains an OAuth Bearer token using Client Credentials flow if configured."""
        if not self.client_id or not self.client_secret:
            return None
        if self._api_token:
            return self._api_token

        try:
            auth_str = f"{self.client_id}:{self.client_secret}"
            b64_auth = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
            req = urllib.request.Request(
                "https://accounts.spotify.com/api/token",
                data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode('utf-8'),
                headers={
                    "Authorization": f"Basic {b64_auth}",
                    "Content-Type": "application/x-www-form-urlencoded"
                }
            )
            with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                self._api_token = data.get("access_token")
                return self._api_token
        except Exception as e:
            print(f"[SpotifyFetcher] API Token acquisition failed: {e}")
            return None

    def fetch_entity(self, url_or_uri: str) -> Dict:
        """
        Fetches full metadata for a Spotify playlist, album, or track.
        Returns a dict:
        {
            "type": "playlist"|"album"|"track",
            "id": "...",
            "title": "...",
            "description": "...",
            "author": "...",
            "cover_url": "...",
            "total_tracks": int,
            "tracks": [
                {
                    "title": "...",
                    "artist": "...",
                    "artists": ["..."],
                    "album": "...",
                    "album_artist": "...",
                    "track_number": int,
                    "total_tracks": int,
                    "disc_number": int,
                    "release_date": "YYYY" or "YYYY-MM-DD",
                    "year": "YYYY",
                    "duration_ms": int,
                    "cover_url": "...",
                    "spotify_id": "...",
                    "spotify_url": "..."
                },
                ...
            ]
        }
        """
        entity_type, entity_id = self.parse_spotify_url(url_or_uri)
        if not entity_type or not entity_id:
            raise ValueError("Invalid Spotify URL or URI. Please provide a valid playlist, album, or track link.")

        # 1. Try official API if credentials are provided
        api_token = self._get_api_token()
        if api_token:
            try:
                return self._fetch_via_api(entity_type, entity_id, api_token)
            except Exception as e:
                print(f"[SpotifyFetcher] Official API fetch failed, falling back to embed scraper: {e}")

        # 2. Embed Scraper (0-config fallback)
        return self._fetch_via_embed(entity_type, entity_id)

    def _fetch_via_embed(self, entity_type: str, entity_id: str) -> Dict:
        """Extracts metadata by scraping Spotify's public embed page."""
        embed_url = f"https://open.spotify.com/embed/{entity_type}/{entity_id}"
        req = urllib.request.Request(
            embed_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9"
            }
        )

        with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=12) as resp:
            html = resp.read().decode('utf-8')

        match = re.search(r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>', html, re.DOTALL)
        if not match:
            raise RuntimeError("Could not extract metadata from Spotify. Please check the link or provide Spotify API keys in Settings.")

        data = json.loads(match.group(1))
        props = data.get("props", {}).get("pageProps", {})
        state = props.get("state", {}).get("data", {})
        entity = state.get("entity", {})

        title = entity.get("title") or entity.get("name") or "Spotify Collection"
        subtitle = entity.get("subtitle") or ""
        authors = entity.get("authors", [])
        author_name = authors[0].get("name") if authors else subtitle

        # Cover artwork
        cover_url = ""
        cover_art = entity.get("coverArt", {})
        if cover_art and isinstance(cover_art, dict):
            sources = cover_art.get("sources", [])
            if sources:
                cover_url = sources[-1].get("url") or sources[0].get("url") or ""

        # Visual identity image fallback (640x640)
        if not cover_url:
            vis_images = entity.get("visualIdentity", {}).get("image", [])
            if vis_images:
                cover_url = vis_images[-1].get("url") or ""

        raw_tracks = entity.get("trackList", [])
        tracks: List[Dict] = []

        release_date_obj = entity.get("releaseDate", {})
        default_release_date = ""
        if isinstance(release_date_obj, dict):
            default_release_date = release_date_obj.get("isoString", "")[:10]
        elif isinstance(release_date_obj, str):
            default_release_date = release_date_obj[:10]

        default_year = default_release_date[:4] if len(default_release_date) >= 4 else ""

        if entity_type == "track":
            # Single track entity
            track_artists = [a.get("name") for a in entity.get("artists", []) if a.get("name")]
            primary_artist = track_artists[0] if track_artists else (entity.get("subtitle") or "Unknown Artist")
            track_cover = cover_url
            t_data = {
                "title": entity.get("title") or entity.get("name") or "Unknown Track",
                "artist": primary_artist,
                "artists": track_artists or [primary_artist],
                "album": title if entity_type == "album" else "Singles",
                "album_artist": primary_artist,
                "track_number": 1,
                "total_tracks": 1,
                "disc_number": 1,
                "release_date": default_release_date,
                "year": default_year,
                "duration_ms": entity.get("duration", 0),
                "cover_url": track_cover,
                "spotify_id": entity_id,
                "spotify_url": f"https://open.spotify.com/track/{entity_id}"
            }
            tracks.append(t_data)
        else:
            # Playlist or Album
            total = len(raw_tracks)
            for idx, item in enumerate(raw_tracks, start=1):
                t_title = item.get("title") or "Unknown Track"
                t_artist_raw = item.get("subtitle") or author_name or "Unknown Artist"
                # Split multiple artist names if comma separated
                artists = [a.strip() for a in t_artist_raw.split(",") if a.strip()]
                primary_artist = artists[0] if artists else t_artist_raw
                album_name = title if entity_type == "album" else "Spotify Playlist"
                album_artist = author_name if entity_type == "album" else primary_artist

                t_uri = item.get("uri", "")
                t_id = t_uri.split(":")[-1] if ":" in t_uri else f"track_{idx}"

                tracks.append({
                    "title": t_title,
                    "artist": primary_artist,
                    "artists": artists,
                    "album": album_name,
                    "album_artist": album_artist,
                    "track_number": idx,
                    "total_tracks": total,
                    "disc_number": 1,
                    "release_date": default_release_date,
                    "year": default_year,
                    "duration_ms": item.get("duration", 0),
                    "cover_url": cover_url,
                    "spotify_id": t_id,
                    "spotify_url": f"https://open.spotify.com/track/{t_id}" if t_id else ""
                })

        return {
            "type": entity_type,
            "id": entity_id,
            "title": title,
            "description": entity.get("description", ""),
            "author": author_name,
            "cover_url": cover_url,
            "total_tracks": len(tracks),
            "tracks": tracks
        }

    def _fetch_via_api(self, entity_type: str, entity_id: str, token: str) -> Dict:
        """Fetches metadata using official Spotify Web API endpoints."""
        headers = {"Authorization": f"Bearer {token}"}
        base_api = "https://api.spotify.com/v1"

        if entity_type == "track":
            req = urllib.request.Request(f"{base_api}/tracks/{entity_id}", headers=headers)
            with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=10) as resp:
                item = json.loads(resp.read().decode('utf-8'))
            
            artists = [a.get("name") for a in item.get("artists", [])]
            album_obj = item.get("album", {})
            album_name = album_obj.get("name", "Singles")
            album_artists = [a.get("name") for a in album_obj.get("artists", [])]
            album_artist = album_artists[0] if album_artists else (artists[0] if artists else "Unknown Artist")
            images = album_obj.get("images", [])
            cover_url = images[0].get("url") if images else ""
            rel_date = album_obj.get("release_date", "")

            track_info = {
                "title": item.get("name", "Unknown Track"),
                "artist": artists[0] if artists else "Unknown Artist",
                "artists": artists,
                "album": album_name,
                "album_artist": album_artist,
                "track_number": item.get("track_number", 1),
                "total_tracks": album_obj.get("total_tracks", 1),
                "disc_number": item.get("disc_number", 1),
                "release_date": rel_date,
                "year": rel_date[:4] if len(rel_date) >= 4 else "",
                "duration_ms": item.get("duration_ms", 0),
                "cover_url": cover_url,
                "spotify_id": entity_id,
                "spotify_url": item.get("external_urls", {}).get("spotify", "")
            }
            return {
                "type": "track",
                "id": entity_id,
                "title": item.get("name", "Track"),
                "description": "",
                "author": artists[0] if artists else "",
                "cover_url": cover_url,
                "total_tracks": 1,
                "tracks": [track_info]
            }

        elif entity_type == "album":
            req = urllib.request.Request(f"{base_api}/albums/{entity_id}", headers=headers)
            with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=10) as resp:
                album = json.loads(resp.read().decode('utf-8'))

            album_name = album.get("name", "Album")
            album_artists = [a.get("name") for a in album.get("artists", [])]
            album_artist = album_artists[0] if album_artists else "Unknown Artist"
            images = album.get("images", [])
            cover_url = images[0].get("url") if images else ""
            rel_date = album.get("release_date", "")
            total_tracks = album.get("total_tracks", len(album.get("tracks", {}).get("items", [])))

            tracks = []
            for item in album.get("tracks", {}).get("items", []):
                t_artists = [a.get("name") for a in item.get("artists", [])]
                tracks.append({
                    "title": item.get("name", "Unknown Track"),
                    "artist": t_artists[0] if t_artists else album_artist,
                    "artists": t_artists,
                    "album": album_name,
                    "album_artist": album_artist,
                    "track_number": item.get("track_number", 1),
                    "total_tracks": total_tracks,
                    "disc_number": item.get("disc_number", 1),
                    "release_date": rel_date,
                    "year": rel_date[:4] if len(rel_date) >= 4 else "",
                    "duration_ms": item.get("duration_ms", 0),
                    "cover_url": cover_url,
                    "spotify_id": item.get("id", ""),
                    "spotify_url": item.get("external_urls", {}).get("spotify", "")
                })

            return {
                "type": "album",
                "id": entity_id,
                "title": album_name,
                "description": "",
                "author": album_artist,
                "cover_url": cover_url,
                "total_tracks": len(tracks),
                "tracks": tracks
            }

        elif entity_type == "playlist":
            req = urllib.request.Request(f"{base_api}/playlists/{entity_id}", headers=headers)
            with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=10) as resp:
                plist = json.loads(resp.read().decode('utf-8'))

            plist_title = plist.get("name", "Playlist")
            owner_name = plist.get("owner", {}).get("display_name", "")
            images = plist.get("images", [])
            plist_cover = images[0].get("url") if images else ""

            # Fetch tracks (supports pagination)
            tracks = []
            tracks_url = f"{base_api}/playlists/{entity_id}/tracks?limit=100"
            track_idx = 1

            while tracks_url:
                req_t = urllib.request.Request(tracks_url, headers=headers)
                with urllib.request.urlopen(req_t, context=self._ssl_ctx, timeout=10) as resp_t:
                    t_data = json.loads(resp_t.read().decode('utf-8'))
                
                items = t_data.get("items", [])
                for entry in items:
                    track_item = entry.get("track")
                    if not track_item or not track_item.get("id"):
                        continue

                    t_artists = [a.get("name") for a in track_item.get("artists", [])]
                    album_obj = track_item.get("album", {})
                    album_name = album_obj.get("name", plist_title)
                    album_artists = [a.get("name") for a in album_obj.get("artists", [])]
                    album_artist = album_artists[0] if album_artists else (t_artists[0] if t_artists else "Unknown Artist")
                    t_images = album_obj.get("images", [])
                    t_cover = t_images[0].get("url") if t_images else plist_cover
                    t_reldate = album_obj.get("release_date", "")

                    tracks.append({
                        "title": track_item.get("name", "Unknown Track"),
                        "artist": t_artists[0] if t_artists else "Unknown Artist",
                        "artists": t_artists,
                        "album": album_name,
                        "album_artist": album_artist,
                        "track_number": track_item.get("track_number", track_idx),
                        "total_tracks": album_obj.get("total_tracks", 1),
                        "disc_number": track_item.get("disc_number", 1),
                        "release_date": t_reldate,
                        "year": t_reldate[:4] if len(t_reldate) >= 4 else "",
                        "duration_ms": track_item.get("duration_ms", 0),
                        "cover_url": t_cover,
                        "spotify_id": track_item.get("id", ""),
                        "spotify_url": track_item.get("external_urls", {}).get("spotify", "")
                    })
                    track_idx += 1

                tracks_url = t_data.get("next")

            return {
                "type": "playlist",
                "id": entity_id,
                "title": plist_title,
                "description": plist.get("description", ""),
                "author": owner_name,
                "cover_url": plist_cover,
                "total_tracks": len(tracks),
                "tracks": tracks
            }

        raise ValueError(f"Unsupported entity type: {entity_type}")


class PlexampTagger:
    """Tags audio files (MP3, FLAC, M4A) with complete Plexamp-compliant metadata & cover art."""

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
        cover_image_path: Optional[str] = None
    ) -> bool:
        """
        Applies rich Plexamp ID3/FLAC/MP4 tags to the downloaded audio file.
        track_info keys: title, artist, artists, album, album_artist, track_number, total_tracks, disc_number, year, release_date
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
                    is_compilation, cover_image_path
                )
            elif ext == ".flac":
                cls._tag_flac(
                    file_path, title, artist, artists, album, album_artist,
                    track_num, total_tracks, disc_num, year, rel_date,
                    is_compilation, cover_image_path
                )
            elif ext in [".m4a", ".aac", ".mp4"]:
                cls._tag_mp4(
                    file_path, title, artist, artists, album, album_artist,
                    track_num, total_tracks, disc_num, year, rel_date,
                    is_compilation, cover_image_path
                )
            return True
        except Exception as e:
            print(f"[PlexampTagger] Tagging failed for {file_path}: {e}")
            return False

    @staticmethod
    def _tag_mp3(
        file_path: str, title: str, artist: str, artists: List[str], album: str,
        album_artist: str, track_num: int, total_tracks: int, disc_num: int,
        year: str, rel_date: str, is_compilation: bool, cover_path: Optional[str]
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

        tags.save(file_path, v2_version=3)

    @staticmethod
    def _tag_flac(
        file_path: str, title: str, artist: str, artists: List[str], album: str,
        album_artist: str, track_num: int, total_tracks: int, disc_num: int,
        year: str, rel_date: str, is_compilation: bool, cover_path: Optional[str]
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

        if cover_path and os.path.exists(cover_path):
            audio.clear_pictures()
            pic = Picture()
            pic.type = 3  # Front Cover
            pic.mime = "image/jpeg" if cover_path.lower().endswith((".jpg", ".jpeg")) else "image/png"
            with open(cover_path, "rb") as f:
                pic.data = f.read()
            audio.add_picture(pic)

        audio.save()

    @staticmethod
    def _tag_mp4(
        file_path: str, title: str, artist: str, artists: List[str], album: str,
        album_artist: str, track_num: int, total_tracks: int, disc_num: int,
        year: str, rel_date: str, is_compilation: bool, cover_path: Optional[str]
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

        if cover_path and os.path.exists(cover_path):
            with open(cover_path, "rb") as f:
                cov_data = f.read()
            cov_fmt = MP4Cover.FORMAT_JPEG if cover_path.lower().endswith((".jpg", ".jpeg")) else MP4Cover.FORMAT_PNG
            audio["covr"] = [MP4Cover(cov_data, imageformat=cov_fmt)]

        audio.save()


class SpotifyPlexampPipeline:
    """Coordinates search on YouTube, download via yt-dlp, tagging, and Plex file structure."""

    def __init__(
        self,
        yt_dlp_path: str,
        cookie_args: List[str],
        log_callback: Callable[[str, bool], None],
        progress_callback: Callable[[float, str], None]
    ):
        self.yt_dlp_path = yt_dlp_path
        self.cookie_args = cookie_args
        self.log = log_callback
        self.progress_cb = progress_callback
        self.is_cancelled = False
        self.active_proc: Optional[subprocess.Popen] = None

    def cancel(self):
        self.is_cancelled = True
        if self.active_proc:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(self.active_proc.pid)],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            except Exception:
                try:
                    self.active_proc.kill()
                except Exception:
                    pass

    def process_playlist(
        self,
        collection: Dict,
        selected_tracks: List[Dict],
        base_music_dir: str,
        audio_format: str = "mp3",
        folder_structure: str = "plex_standard",  # "plex_standard" or "playlist_folder"
        embed_art: bool = True,
        save_cover_file: bool = True
    ) -> Dict[str, int]:
        """
        Downloads each track, tags with Plexamp metadata, and organizes in destination.
        Returns {"completed": int, "skipped": int, "failed": int}
        """
        self.is_cancelled = False
        stats = {"completed": 0, "skipped": 0, "failed": 0}
        total_selected = len(selected_tracks)
        if total_selected == 0:
            self.log("No tracks selected for download.", is_error=True)
            return stats

        os.makedirs(base_music_dir, exist_ok=True)
        temp_dir = os.path.join(base_music_dir, ".temp_sma_sync")
        os.makedirs(temp_dir, exist_ok=True)

        # Download collection cover art if available
        collection_cover_path = None
        if collection.get("cover_url"):
            collection_cover_path = os.path.join(temp_dir, f"collection_cover_{collection.get('id')}.jpg")
            PlexampTagger.download_cover_art(collection.get("cover_url", ""), collection_cover_path)

        for idx, track in enumerate(selected_tracks, start=1):
            if self.is_cancelled:
                self.log("🛑 Download pipeline cancelled by user.")
                break

            t_title = track.get("title", "Unknown Track")
            t_artist = track.get("artist", "Unknown Artist")
            t_album = track.get("album", "Spotify Music")
            t_num = track.get("track_number", idx)

            self.log(f"[{idx}/{total_selected}] Searching & downloading: {t_artist} - {t_title}")
            self.progress_cb(float(idx - 1) / total_selected, f"[{idx}/{total_selected}] {t_artist} - {t_title}")

            # 1. Determine destination paths
            clean_artist = sanitize_filename(t_artist)
            clean_album = sanitize_filename(t_album)
            clean_title = sanitize_filename(t_title)
            ext = "flac" if "flac" in audio_format.lower() else ("m4a" if "m4a" in audio_format.lower() else "mp3")

            if folder_structure == "plex_standard":
                # Music / Artist / Album / 01 - Title.ext
                dest_dir = os.path.join(base_music_dir, clean_artist, clean_album)
                dest_filename = f"{t_num:02d} - {clean_title}.{ext}"
            else:
                # Music / Playlists / Playlist Name / 01 - Artist - Title.ext
                plist_name = sanitize_filename(collection.get("title", "Spotify Playlist"))
                dest_dir = os.path.join(base_music_dir, "Playlists", plist_name)
                dest_filename = f"{t_num:02d} - {clean_artist} - {clean_title}.{ext}"

            os.makedirs(dest_dir, exist_ok=True)
            final_file_path = os.path.join(dest_dir, dest_filename)

            # Check if file already exists
            if os.path.exists(final_file_path) and os.path.getsize(final_file_path) > 100000:
                self.log(f"✓ Already exists in Plex library: {dest_filename}")
                stats["completed"] += 1
                continue

            # 2. Download Cover Art for Track (if track has unique cover or use collection cover)
            track_cover_path = None
            t_cover_url = track.get("cover_url") or collection.get("cover_url")
            if embed_art and t_cover_url:
                track_cover_path = os.path.join(temp_dir, f"track_cover_{track.get('spotify_id', idx)}.jpg")
                if not os.path.exists(track_cover_path):
                    if not PlexampTagger.download_cover_art(t_cover_url, track_cover_path):
                        track_cover_path = collection_cover_path

            # Save cover.jpg in album directory for Plex library scanner
            if save_cover_file and (track_cover_path or collection_cover_path):
                art_source = track_cover_path if track_cover_path and os.path.exists(track_cover_path) else collection_cover_path
                if art_source and os.path.exists(art_source):
                    album_cover_file = os.path.join(dest_dir, "cover.jpg")
                    if not os.path.exists(album_cover_file):
                        try:
                            shutil.copy(art_source, album_cover_file)
                        except Exception:
                            pass

            # 3. Search and Download from YouTube
            # Optimal query: "{artist} - {title} audio" or "{artist} - {title}"
            search_query = f"{t_artist} - {t_title} audio"
            temp_output_template = os.path.join(temp_dir, f"dl_{idx}_%(id)s.%(ext)s")

            aq = "0" if "flac" in audio_format.lower() or "320" in audio_format.lower() else "5"
            cmd = [
                self.yt_dlp_path,
                "--newline",
                "--no-playlist",
                "-f", "ba",
                "--extract-audio",
                "--audio-format", ext,
                "--audio-quality", aq,
                "-o", temp_output_template,
                f"ytsearch1:{search_query}"
            ] + self.cookie_args

            try:
                self.active_proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )

                for line in self.active_proc.stdout:
                    line_clean = line.strip()
                    if "[download]" in line_clean and "%" in line_clean:
                        # Extract percentage e.g. 45.2%
                        p_match = re.search(r'([0-9.]+)%', line_clean)
                        if p_match:
                            try:
                                pct = float(p_match.group(1))
                                overall_pct = ((idx - 1) + (pct / 100.0)) / total_selected
                                self.progress_cb(overall_pct, f"[{idx}/{total_selected}] Downloading {pct:.0f}%: {t_title}")
                            except Exception:
                                pass
                    elif "ERROR:" in line_clean:
                        self.log(f"⚠️ {line_clean}", is_error=True)

                self.active_proc.wait()
                if self.is_cancelled:
                    break

                if self.active_proc.returncode != 0:
                    self.log(f"❌ Failed to download '{t_title}' from YouTube.", is_error=True)
                    stats["failed"] += 1
                    continue

                # Locate downloaded file in temp_dir
                downloaded_file = None
                for fname in os.listdir(temp_dir):
                    if fname.startswith(f"dl_{idx}_") and fname.lower().endswith(f".{ext}"):
                        downloaded_file = os.path.join(temp_dir, fname)
                        break

                if not downloaded_file or not os.path.exists(downloaded_file):
                    self.log(f"❌ Downloaded audio file not found for '{t_title}'.", is_error=True)
                    stats["failed"] += 1
                    continue

                # 4. Move to final destination
                shutil.move(downloaded_file, final_file_path)

                # 5. Tag with Plexamp Metadata & Cover Art
                if embed_art:
                    PlexampTagger.apply_metadata(final_file_path, track, track_cover_path)
                else:
                    PlexampTagger.apply_metadata(final_file_path, track, None)

                self.log(f"✓ Successfully tagged for Plexamp: {dest_filename}")
                stats["completed"] += 1

            except Exception as e:
                self.log(f"❌ Error processing '{t_title}': {e}", is_error=True)
                stats["failed"] += 1

        # Clean up temp folder
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

        self.progress_cb(1.0, f"Sync complete! {stats['completed']} downloaded, {stats['failed']} failed.")
        return stats
