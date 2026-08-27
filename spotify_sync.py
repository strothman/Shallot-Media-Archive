"""
Spotify to Plexamp Integration Engine
Handles Spotify playlist/album/track metadata extraction, YouTube audio matching/download via yt-dlp,
and rich Plexamp-compatible metadata tagging (ID3v2 / FLAC / MP4) with Mutagen.
"""

import os
import re
import json
import ssl
import shutil
import base64
import urllib.request
import urllib.parse
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple, Callable

from mutagen.id3 import (
    ID3, TIT2, TPE1, TPE2, TALB, TRCK, TPOS, TDRC, APIC, TCMP, USLT, TXXX, ID3NoHeaderError
)
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4, MP4Cover

import time

BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
CREATION_FLAGS_BACKGROUND = (
    (subprocess.CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS)
    if os.name == 'nt' else 0
)


def safe_move_file(src: str, dst: str, max_retries: int = 4, delay: float = 0.35) -> bool:
    """Moves a file safely on Windows, retrying on transient locks (e.g. Defender, Indexer)."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    for attempt in range(max_retries):
        try:
            if os.path.exists(dst) and os.path.abspath(src) != os.path.abspath(dst):
                try:
                    os.remove(dst)
                except Exception:
                    pass
            shutil.move(src, dst)
            return True
        except (PermissionError, OSError) as e:
            if attempt < max_retries - 1:
                time.sleep(delay * (attempt + 1))
            else:
                raise e
    return False


def safe_save_tags(audio_obj, *args, **kwargs) -> bool:
    """Saves Mutagen tags with automatic retry for Windows file locks."""
    for attempt in range(4):
        try:
            audio_obj.save(*args, **kwargs)
            return True
        except (PermissionError, OSError) as e:
            if attempt < 3:
                time.sleep(0.35 * (attempt + 1))
            else:
                raise e
    return False


def sanitize_filename(name: str, max_len: int = 80) -> str:
    """Removes invalid filesystem characters and limits length to prevent Windows MAX_PATH errors."""
    if not name:
        return "Unknown"
    # Strip invalid chars: < > : " / \ | ? * and control chars
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name).strip()
    clean = re.sub(r'\s+', ' ', clean)
    clean = clean.rstrip('. ')
    if not clean:
        clean = "Unknown"
    return clean[:max_len]


class SpotifyAuthHelper:
    """Handles 1-click Spotify OAuth authorization server to unlock unlimited playlist sizes."""

    @staticmethod
    def get_auth_url(client_id: str, redirect_uri: str = "http://127.0.0.1:8888/callback") -> str:
        params = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": "playlist-read-private playlist-read-collaborative user-library-read"
        }
        return "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(params)

    @staticmethod
    def authorize_in_browser(client_id: str, client_secret: str, callback_fn):
        """Spawns a local one-shot HTTP server, opens browser for authorization, and calls callback_fn(refresh_token, error)."""
        import http.server
        import webbrowser

        redirect_uri = "http://127.0.0.1:8888/callback"
        auth_code_container = {"code": None, "error": None}

        class CallbackHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                query = urllib.parse.urlparse(self.path).query
                params = urllib.parse.parse_qs(query)
                if "code" in params:
                    auth_code_container["code"] = params["code"][0]
                    self.send_response(200)
                    self.send_header("Content-type", "text/html; charset=utf-8")
                    self.end_headers()
                    html = """<html><head><title>Spotify Connected</title></head>
                    <body style="background:#0D0D12;color:#10B981;font-family:Segoe UI,sans-serif;text-align:center;padding-top:60px;">
                        <h1 style="font-size:28px;">&#10003; Spotify Connected Successfully!</h1>
                        <p style="color:#EEEEF2;font-size:16px;">All 722+ track playlists are now unlocked in Shallot Media Archive.</p>
                        <p style="color:#78909C;font-size:13px;">You can close this browser tab now.</p>
                    </body></html>"""
                    self.wfile.write(html.encode("utf-8"))
                else:
                    auth_code_container["error"] = params.get("error", ["Unknown error"])[0]
                    self.send_response(400)
                    self.end_headers()

            def log_message(self, format, *args):
                pass

        def run_server():
            try:
                server = http.server.HTTPServer(("127.0.0.1", 8888), CallbackHandler)
                server.timeout = 120
                auth_url = SpotifyAuthHelper.get_auth_url(client_id, redirect_uri)
                webbrowser.open(auth_url)
                
                # Handle single request
                server.handle_request()
                server.server_close()

                if auth_code_container["code"]:
                    # Exchange code for tokens
                    auth_str = f"{client_id}:{client_secret}"
                    b64_auth = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
                    data = urllib.parse.urlencode({
                        "grant_type": "authorization_code",
                        "code": auth_code_container["code"],
                        "redirect_uri": redirect_uri
                    }).encode('utf-8')
                    req = urllib.request.Request(
                        "https://accounts.spotify.com/api/token",
                        data=data,
                        headers={
                            "Authorization": f"Basic {b64_auth}",
                            "Content-Type": "application/x-www-form-urlencoded"
                        }
                    )
                    ssl_ctx = ssl.create_default_context()
                    ssl_ctx.check_hostname = False
                    ssl_ctx.verify_mode = ssl.CERT_NONE
                    with urllib.request.urlopen(req, context=ssl_ctx, timeout=10) as resp:
                        tok_data = json.loads(resp.read().decode('utf-8'))
                        refresh_tok = tok_data.get("refresh_token")
                        callback_fn(refresh_tok, None)
                else:
                    callback_fn(None, auth_code_container.get("error") or "Authorization timed out or was cancelled.")
            except Exception as e:
                callback_fn(None, str(e))

        threading.Thread(target=run_server, daemon=True).start()


class SpotifyFetcher:
    """Fetches Spotify metadata via Embed scraping, User Auth, or Web API."""

    def __init__(self, client_id: str = "", client_secret: str = "", refresh_token: str = ""):
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.refresh_token = refresh_token.strip()
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
        """Obtains an OAuth Bearer token using Refresh Token (preferred) or Client Credentials flow."""
        if not self.client_id or not self.client_secret:
            return None
        if self._api_token:
            return self._api_token

        try:
            auth_str = f"{self.client_id}:{self.client_secret}"
            b64_auth = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
            
            if self.refresh_token:
                payload = {
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token
                }
            else:
                payload = {"grant_type": "client_credentials"}

            req = urllib.request.Request(
                "https://accounts.spotify.com/api/token",
                data=urllib.parse.urlencode(payload).encode('utf-8'),
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

    @classmethod
    def resolve_track_album(
        cls,
        artist: str,
        title: str,
        spotify_id: Optional[str] = None,
        fallback_cover: str = "",
        fallback_date: str = ""
    ) -> Dict:
        """
        Resolves the true original studio album, album artist, release year,
        track number, and high-res album cover for a track.
        """
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        # Clean search query (strip remaster / live noise)
        clean_title = re.sub(r'\s*-\s*(Remastered|Remaster|Live|Single Version).*$', '', title, flags=re.IGNORECASE).strip()
        query = f"{artist} {clean_title}"

        # 1. Query iTunes Music Catalog API (Super-fast, accurate for real album titles)
        try:
            url = f"https://itunes.apple.com/search?term={urllib.parse.quote(query)}&entity=song&limit=3"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, context=ctx, timeout=4) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                results = data.get("results", [])
                if results:
                    it = results[0]
                    alb_name = it.get("collectionName")
                    if alb_name:
                        cover = it.get("artworkUrl100", "").replace("100x100bb", "640x640bb") or fallback_cover
                        rel_date = it.get("releaseDate", "")[:10] or fallback_date
                        return {
                            "album": alb_name,
                            "album_artist": it.get("artistName") or artist,
                            "track_number": it.get("trackNumber", 1),
                            "total_tracks": it.get("trackCount", 1),
                            "release_date": rel_date,
                            "year": rel_date[:4] if len(rel_date) >= 4 else "",
                            "cover_url": cover
                        }
        except Exception:
            pass

        # 2. Spotify track embed fallback for original 640x640 artwork and date
        if spotify_id and not str(spotify_id).startswith("track_"):
            try:
                emb_url = f"https://open.spotify.com/embed/track/{spotify_id}"
                req = urllib.request.Request(emb_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, context=ctx, timeout=4) as resp:
                    html = resp.read().decode('utf-8')
                m = re.search(r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>', html, re.DOTALL)
                if m:
                    t_data = json.loads(m.group(1)).get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
                    vis = t_data.get("visualIdentity", {}).get("image", [])
                    cov = vis[-1].get("url") if vis else fallback_cover
                    rd = t_data.get("releaseDate", {}).get("isoString", "")[:10] or fallback_date
                    return {
                        "album": f"{clean_title} - Single",
                        "album_artist": artist,
                        "track_number": 1,
                        "total_tracks": 1,
                        "release_date": rd,
                        "year": rd[:4] if len(rd) >= 4 else "",
                        "cover_url": cov or fallback_cover
                    }
            except Exception:
                pass

        return {
            "album": f"{clean_title} - Single",
            "album_artist": artist,
            "track_number": 1,
            "total_tracks": 1,
            "release_date": fallback_date,
            "year": fallback_date[:4] if len(fallback_date) >= 4 else "",
            "cover_url": fallback_cover
        }

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
            t_title = entity.get("title") or entity.get("name") or "Unknown Track"
            
            # Resolve actual album
            alb_meta = self.resolve_track_album(primary_artist, t_title, entity_id, cover_url, default_release_date)
            
            t_data = {
                "title": t_title,
                "artist": primary_artist,
                "artists": track_artists or [primary_artist],
                "album": alb_meta.get("album", f"{t_title} - Single"),
                "album_artist": alb_meta.get("album_artist", primary_artist),
                "track_number": alb_meta.get("track_number", 1),
                "total_tracks": alb_meta.get("total_tracks", 1),
                "disc_number": 1,
                "release_date": alb_meta.get("release_date") or default_release_date,
                "year": alb_meta.get("year") or default_year,
                "duration_ms": entity.get("duration", 0),
                "cover_url": alb_meta.get("cover_url") or cover_url,
                "spotify_id": entity_id,
                "spotify_url": f"https://open.spotify.com/track/{entity_id}"
            }
            tracks.append(t_data)
        elif entity_type == "album":
            # Album entity - all tracks belong to this album
            total = len(raw_tracks)
            for idx, item in enumerate(raw_tracks, start=1):
                t_title = item.get("title") or "Unknown Track"
                t_artist_raw = item.get("subtitle") or author_name or "Unknown Artist"
                artists = [a.strip() for a in t_artist_raw.split(",") if a.strip()]
                primary_artist = artists[0] if artists else t_artist_raw

                t_uri = item.get("uri", "")
                t_id = t_uri.split(":")[-1] if ":" in t_uri else f"track_{idx}"

                tracks.append({
                    "title": t_title,
                    "artist": primary_artist,
                    "artists": artists,
                    "album": title,
                    "album_artist": author_name or primary_artist,
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
        else:
            # Playlist entity - resolve the true original studio album for each song in parallel
            total = len(raw_tracks)
            
            def enrich_item(args):
                idx, item = args
                t_title = item.get("title") or "Unknown Track"
                t_artist_raw = item.get("subtitle") or author_name or "Unknown Artist"
                artists = [a.strip() for a in t_artist_raw.split(",") if a.strip()]
                primary_artist = artists[0] if artists else t_artist_raw

                t_uri = item.get("uri", "")
                t_id = t_uri.split(":")[-1] if ":" in t_uri else f"track_{idx}"

                # Resolve true original album metadata
                alb_meta = self.resolve_track_album(
                    artist=primary_artist,
                    title=t_title,
                    spotify_id=t_id,
                    fallback_cover=cover_url,
                    fallback_date=default_release_date
                )

                return {
                    "title": t_title,
                    "artist": primary_artist,
                    "artists": artists,
                    "album": alb_meta.get("album", f"{t_title} - Single"),
                    "album_artist": alb_meta.get("album_artist", primary_artist),
                    "track_number": alb_meta.get("track_number", idx),
                    "total_tracks": alb_meta.get("total_tracks", 1),
                    "disc_number": 1,
                    "release_date": alb_meta.get("release_date") or default_release_date,
                    "year": alb_meta.get("year") or default_year,
                    "duration_ms": item.get("duration", 0),
                    "cover_url": alb_meta.get("cover_url") or cover_url,
                    "spotify_id": t_id,
                    "spotify_url": f"https://open.spotify.com/track/{t_id}" if t_id else ""
                }

            with ThreadPoolExecutor(max_workers=8) as executor:
                tracks = list(executor.map(enrich_item, enumerate(raw_tracks, start=1)))

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

            # Fetch tracks (supports pagination using 2026 /items endpoint with /tracks fallback)
            tracks = []
            tracks_url = f"{base_api}/playlists/{entity_id}/items?limit=100"
            track_idx = 1

            while tracks_url:
                req_t = urllib.request.Request(tracks_url, headers=headers)
                try:
                    with urllib.request.urlopen(req_t, context=self._ssl_ctx, timeout=10) as resp_t:
                        t_data = json.loads(resp_t.read().decode('utf-8'))
                except Exception as e:
                    # Fallback to legacy /tracks endpoint if /items is unsupported
                    if "/items" in tracks_url:
                        tracks_url = tracks_url.replace("/items", "/tracks")
                        req_fallback = urllib.request.Request(tracks_url, headers=headers)
                        with urllib.request.urlopen(req_fallback, context=self._ssl_ctx, timeout=10) as resp_t:
                            t_data = json.loads(resp_t.read().decode('utf-8'))
                    else:
                        raise e
                
                items = t_data.get("items", [])
                for entry in items:
                    track_item = entry.get("item") or entry.get("track")
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


class LyricsFetcher:
    """Fetches synchronized (.lrc) and plain text lyrics from LRCLIB."""

    @staticmethod
    def fetch_lyrics(artist: str, title: str, album: str = "", duration_s: int = 0) -> Dict[str, str]:
        """
        Returns dict with "plain_lyrics" (str) and "synced_lyrics" (str in LRC format).
        """
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        clean_title = re.sub(r'\s*-\s*(Remastered|Remaster|Live|Single Version).*$', '', title, flags=re.IGNORECASE).strip()
        params = {"artist_name": artist, "track_name": clean_title}
        if album and album not in ["Spotify Playlist", "Spotify Collection", "Singles"]:
            params["album_name"] = album
        if duration_s > 0:
            params["duration"] = int(duration_s)

        headers = {"User-Agent": "ShallotMediaArchive/1.1 (https://github.com/strothman/util-SMArchive)"}

        # 1. Direct fetch
        try:
            url = f"https://lrclib.net/api/get?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, context=ctx, timeout=4) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                plain = data.get("plainLyrics") or ""
                synced = data.get("syncedLyrics") or ""
                if plain or synced:
                    return {"plain_lyrics": plain, "synced_lyrics": synced}
        except Exception:
            pass

        # 2. Search fallback
        try:
            q = f"{artist} {clean_title}"
            s_url = f"https://lrclib.net/api/search?q={urllib.parse.quote(q)}"
            s_req = urllib.request.Request(s_url, headers=headers)
            with urllib.request.urlopen(s_req, context=ctx, timeout=4) as resp:
                results = json.loads(resp.read().decode('utf-8'))
                if results and isinstance(results, list):
                    item = results[0]
                    return {
                        "plain_lyrics": item.get("plainLyrics") or "",
                        "synced_lyrics": item.get("syncedLyrics") or ""
                    }
        except Exception:
            pass

        return {"plain_lyrics": "", "synced_lyrics": ""}


class ReplayGainCalculator:
    """Calculates ReplayGain / EBU R128 loudness tags using bundled ffmpeg."""

    @staticmethod
    def calculate_replaygain(file_path: str, ffmpeg_path: str) -> Optional[Tuple[str, str]]:
        """
        Returns (gain_db_str, peak_str) e.g. ("-4.20 dB", "0.985412")
        """
        if not os.path.exists(file_path) or not os.path.exists(ffmpeg_path):
            return None

        try:
            cmd = [
                ffmpeg_path,
                "-threads", "2",
                "-nostats",
                "-i", file_path,
                "-filter_complex", "ebur128=peak=true",
                "-f", "null",
                "-"
            ]
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                creationflags=CREATION_FLAGS_BACKGROUND
            )
            out = res.stderr
            i_match = re.search(r'I:\s+([-\d.]+)\s+LUFS', out)
            peak_match = re.search(r'Peak:\s+([-\d.]+)\s+dBFS', out)

            if i_match:
                lufs = float(i_match.group(1))
                gain = -18.0 - lufs
                gain_str = f"{gain:+.2f} dB"
                peak_str = "1.000000"
                if peak_match:
                    try:
                        peak_db = float(peak_match.group(1))
                        peak_val = 10.0 ** (peak_db / 20.0)
                        peak_str = f"{peak_val:.6f}"
                    except Exception:
                        pass
                return gain_str, peak_str
        except Exception:
            pass
        return None


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
        Applies rich Plexamp ID3/FLAC/MP4 tags to the downloaded audio file.
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


class SpotifyPlexampPipeline:
    """Coordinates search on YouTube, download via yt-dlp, tagging, lyrics, ReplayGain, and Plex file structure."""

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
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
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
        """
        Returns (dest_dir, dest_filename, final_file_path).
        """
        t_artist = track.get("album_artist") or track.get("artist", "Unknown Artist")
        t_album = track.get("album", "Singles")
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
            plist_name = sanitize_filename(collection.get("title", "Spotify Playlist"))
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
        concurrency: int = 2
    ) -> Dict[str, int]:
        """
        Downloads tracks with concurrency, tags with Plexamp metadata, lyrics, ReplayGain, and organizes in destination.
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
            track_index = track.get("_track_index", seq_idx)

            # Ensure track has true album metadata
            if not t_album or t_album in ["Spotify Playlist", "Spotify Collection", "Singles"]:
                resolved = SpotifyFetcher.resolve_track_album(
                    artist=t_artist,
                    title=t_title,
                    spotify_id=track.get("spotify_id"),
                    fallback_cover=track.get("cover_url", ""),
                    fallback_date=track.get("release_date", "")
                )
                t_album = resolved.get("album", f"{t_title} - Single")
                track["album"] = t_album
                track["album_artist"] = resolved.get("album_artist", track.get("album_artist", t_artist))
                track["track_number"] = resolved.get("track_number", t_num)
                track["total_tracks"] = resolved.get("total_tracks", track.get("total_tracks", 1))
                track["release_date"] = resolved.get("release_date", track.get("release_date", ""))
                track["year"] = resolved.get("year", track.get("year", ""))
                if resolved.get("cover_url"):
                    track["cover_url"] = resolved.get("cover_url")
                t_num = track["track_number"]

            dest_dir, dest_filename, final_file_path = self.get_destination_path(
                base_music_dir, track, collection, audio_format, folder_structure
            )
            os.makedirs(dest_dir, exist_ok=True)

            # Check if file already exists in library
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

            with self._lock:
                self.log(f"[{seq_idx}/{total_selected}] Downloading: {t_artist} - {t_title}")
                if self.track_status_cb:
                    self.track_status_cb(track_index, "Downloading...", "#38BDF8")

            # 1. Download Cover Art
            track_cover_path = None
            t_cover_url = track.get("cover_url") or collection.get("cover_url")
            if embed_art and t_cover_url:
                track_cover_path = os.path.join(temp_dir, f"track_cover_{track.get('spotify_id', seq_idx)}.jpg")
                if not os.path.exists(track_cover_path):
                    if not PlexampTagger.download_cover_art(t_cover_url, track_cover_path):
                        track_cover_path = collection_cover_path

            # Save cover.jpg in album directory for Plex scanner
            if save_cover_file and (track_cover_path or collection_cover_path):
                art_source = track_cover_path if track_cover_path and os.path.exists(track_cover_path) else collection_cover_path
                if art_source and os.path.exists(art_source):
                    album_cover_file = os.path.join(dest_dir, "cover.jpg")
                    if not os.path.exists(album_cover_file):
                        try:
                            shutil.copy(art_source, album_cover_file)
                        except Exception:
                            pass

            # 2. Search and Download from YouTube
            search_query = f"{t_artist} - {t_title} audio"
            ext = "flac" if "flac" in audio_format.lower() else ("m4a" if "m4a" in audio_format.lower() else "mp3")
            temp_output_template = os.path.join(temp_dir, f"dl_{seq_idx}_%(id)s.%(ext)s")
            aq = "0" if "flac" in audio_format.lower() or "320" in audio_format.lower() else "5"

            cmd = [
                self.yt_dlp_path,
                "--newline",
                "--no-playlist",
                "--ffmpeg-location", app_dir,
                "--postprocessor-args", "ffmpeg:-threads 2",
                "-f", "ba/b",
                "--extract-audio",
                "--audio-format", ext,
                "--audio-quality", aq,
                "-o", temp_output_template,
                f"ytsearch1:{search_query}"
            ] + self.cookie_args

            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    creationflags=CREATION_FLAGS_BACKGROUND
                )
                with self._lock:
                    self.active_procs.append(proc)

                for line in proc.stdout:
                    line_clean = line.strip()
                    if "ERROR:" in line_clean and "HTTP Error 403" not in line_clean:
                        with self._lock:
                            self.log(f"⚠️ {line_clean}", is_error=True)

                proc.wait()
                with self._lock:
                    if proc in self.active_procs:
                        self.active_procs.remove(proc)

                if self.is_cancelled:
                    return

                if proc.returncode != 0:
                    with self._lock:
                        self.log(f"❌ Failed to download '{t_title}' from YouTube.", is_error=True)
                        stats["failed"] += 1
                        completed_count[0] += 1
                        if self.track_status_cb:
                            self.track_status_cb(track_index, "❌ Failed", "#FB7185")
                    return

                # Locate downloaded file in temp_dir
                downloaded_file = None
                for fname in os.listdir(temp_dir):
                    if fname.startswith(f"dl_{seq_idx}_") and fname.lower().endswith(f".{ext}"):
                        downloaded_file = os.path.join(temp_dir, fname)
                        break

                if not downloaded_file or not os.path.exists(downloaded_file):
                    with self._lock:
                        self.log(f"❌ Downloaded audio file not found for '{t_title}'.", is_error=True)
                        stats["failed"] += 1
                        completed_count[0] += 1
                        if self.track_status_cb:
                            self.track_status_cb(track_index, "❌ Missing", "#FB7185")
                    return

                # Move to destination safely
                safe_move_file(downloaded_file, final_file_path)

                if self.track_status_cb:
                    self.track_status_cb(track_index, "Tagging...", "#C084FC")

                # 3. Lyrics Fetching (.lrc & embedded)
                plain_lyrics = ""
                if fetch_lyrics:
                    dur_s = int(track.get("duration_ms", 0) / 1000)
                    lyric_data = LyricsFetcher.fetch_lyrics(t_artist, t_title, t_album, dur_s)
                    plain_lyrics = lyric_data.get("plain_lyrics", "")
                    synced_lyrics = lyric_data.get("synced_lyrics", "")

                    if synced_lyrics:
                        lrc_path = os.path.splitext(final_file_path)[0] + ".lrc"
                        try:
                            with open(lrc_path, "w", encoding="utf-8") as lrc_f:
                                lrc_f.write(synced_lyrics)
                        except Exception:
                            pass

                # 4. Volume Normalization (ReplayGain)
                replaygain = None
                if calculate_replaygain and os.path.exists(ffmpeg_exe):
                    replaygain = ReplayGainCalculator.calculate_replaygain(final_file_path, ffmpeg_exe)

                # 5. Apply Metadata & Cover Art
                PlexampTagger.apply_metadata(
                    final_file_path,
                    track,
                    track_cover_path if embed_art else None,
                    plain_lyrics=plain_lyrics,
                    replaygain=replaygain
                )

                with self._lock:
                    stats["completed"] += 1
                    completed_count[0] += 1
                    pct = completed_count[0] / total_selected
                    self.log(f"✓ Tagged for Plexamp: {dest_filename}")
                    self.progress_cb(pct, f"[{completed_count[0]}/{total_selected}] ✓ {t_title}")
                    if self.track_status_cb:
                        self.track_status_cb(track_index, "✓ Done", "#4ADE80")

                # Polite pacing: prevents CPU bursts, GPU stalls, and YouTube anti-bot rate-limiting
                import time
                import random
                time.sleep(random.uniform(0.6, 1.2))
                if seq_idx % 15 == 0:
                    import gc
                    gc.collect()

            except Exception as e:
                with self._lock:
                    self.log(f"❌ Error processing '{t_title}': {e}", is_error=True)
                    stats["failed"] += 1
                    completed_count[0] += 1
                    if self.track_status_cb:
                        self.track_status_cb(track_index, "❌ Error", "#FB7185")

        # Concurrently execute track downloads
        workers = max(1, min(concurrency, 4))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            list(executor.map(process_single_track, enumerate(selected_tracks, start=1)))

        # Clean up temp folder
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

        self.progress_cb(1.0, f"Sync complete! {stats['completed']} ready in Plex library, {stats['failed']} failed.")
        return stats
