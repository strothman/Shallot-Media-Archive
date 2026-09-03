"""
CD Mixtape / 700MB CD Burn Engine for Shallot Media Archive (SMArchive)
Handles:
1. Spotify / Last.fm / iTunes Top Tracks & Related Artist "Vibe" recommendations.
2. Local music library recursive indexing and fuzzy track matching.
3. Knapsack / Greedy capacity bin-packing to maximize 700MB Data CD (or 80-min Audio CD) capacity.
4. Non-destructive file copying and optional on-the-fly transcoding via FFmpeg.
5. Sequential track numbering and M3U playlist generation for CD burning software.
"""

import os
import re
import json
import ssl
import shutil
import base64
import time
import random
import html
import urllib.request
import urllib.parse
import subprocess
import threading
from typing import Dict, List, Optional, Tuple, Callable

import mutagen
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TRCK, TPOS
from mutagen.flac import FLAC
from mutagen.mp4 import MP4

BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
CREATION_FLAGS_BACKGROUND = (
    (subprocess.CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS)
    if os.name == 'nt' else 0
)

SUPPORTED_AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".m4a", ".aac", ".wav", ".ogg", ".opus", ".wma", ".aiff", ".alac"
}
LOSSLESS_EXTENSIONS = {".flac", ".wav", ".aiff", ".alac"}

LASTFM_API_KEY = "b25b959554ed76058ac220b7b2e0a026"

# Safe standard capacities
CAPACITY_PRESETS = {
    "700MB_DATA_CD": {
        "name": "700 MB Data CD (MP3 / M4A)",
        "type": "bytes",
        # Use ~695 MB safe boundary (728,760,320 bytes) to prevent CD-R disc overburn errors
        "target_value": int(695 * 1024 * 1024),
        "display_limit": "695 MB / 700 MB"
    },
    "650MB_DATA_CD": {
        "name": "650 MB Data CD",
        "type": "bytes",
        "target_value": int(645 * 1024 * 1024),
        "display_limit": "645 MB / 650 MB"
    },
    "800MB_DATA_CD": {
        "name": "800 MB Data CD (90 Min CD-R)",
        "type": "bytes",
        "target_value": int(792 * 1024 * 1024),
        "display_limit": "792 MB / 800 MB"
    },
    "80MIN_AUDIO_CD": {
        "name": "80-Minute Standard Audio CD (Red Book)",
        "type": "duration",
        # 79 mins 45 secs safe limit
        "target_value": int(79.75 * 60),
        "display_limit": "79m 45s / 80m"
    },
    "74MIN_AUDIO_CD": {
        "name": "74-Minute Standard Audio CD",
        "type": "duration",
        "target_value": int(73.75 * 60),
        "display_limit": "73m 45s / 74m"
    }
}


def normalize_string(text: str) -> str:
    """Normalizes string for fuzzy title/artist matching."""
    if not text:
        return ""
    text = text.lower()
    # Remove bracketed/parenthetical clutter: (feat. ...), (remastered ...), [official video]
    text = re.sub(r'[\(\[\{].*?[\)\]\}]', '', text)
    # Remove common featuring patterns
    text = re.sub(r'\b(feat|ft|featuring|with|prod|produced by)\b.*', '', text)
    # Remove punctuation
    text = re.sub(r'[^\w\s]', '', text)
    # Collapse multiple spaces
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def sanitize_filename(name: str, max_len: int = 80) -> str:
    """Cleans names for Windows filenames."""
    sanitized = re.sub(r'[\\/*?:"<>|]', '', name).strip()
    sanitized = re.sub(r'\s+', ' ', sanitized)
    return sanitized[:max_len].strip() or "Track"


CLEAN_NOISE_REGEX = re.compile(
    r'[\(\[\{]\s*(?:official\s*(?:music\s*)?video|official\s*audio|official\s*hd|lyric\s*video|music\s*video|audio\s*only|full\s*audio|visualizer|hd|hq|1080p|4k|remaster(?:ed)?(?:\s*\d{4})?|video|lyrics?|audio|official|original\s*mix)\s*[\)\]\}]',
    re.IGNORECASE
)


def clean_display_title(raw_title: str) -> str:
    """
    Cleans YouTube clutter, bracketed bloat, and track numbering prefixes from song titles
    so car stereos (e.g. Ford SYNC) display clean, legible song titles immediately.
    """
    if not raw_title:
        return "Unknown Track"
    t = raw_title.strip()
    # Remove leading track number patterns like "01. ", "01 - ", "1 "
    t = re.sub(r'^\d+\s*[-_.]\s*', '', t)
    # Remove noise patterns: (Official Audio), [1080p], etc.
    t = CLEAN_NOISE_REGEX.sub('', t)
    # Remove empty leftover brackets
    t = re.sub(r'[\(\[\{]\s*[\)\]\}]', '', t)
    t = re.sub(r'\s+', ' ', t).strip(' -_.,;:')
    return t or raw_title.strip()


def clean_display_artist(raw_artist: str) -> str:
    """Cleans artist names for clean automotive display."""
    if not raw_artist:
        return "Unknown Artist"
    a = raw_artist.strip()
    a = CLEAN_NOISE_REGEX.sub('', a)
    a = re.sub(r'[\(\[\{]\s*[\)\]\}]', '', a)
    a = re.sub(r'\s+', ' ', a).strip(' -_.,;:')
    return a or raw_artist.strip()


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

        elif ext in (".m4a", ".mp4", ".aac", ".alac"):
            try:
                mp4 = MP4(file_path)
                mp4["\xa9nam"] = [clean_tit]
                mp4["\xa9ART"] = [clean_art]
                mp4["\xa9alb"] = [clean_alb]
                mp4["trkn"] = [(track_num, total_tracks)]
                mp4["disk"] = [(1, 1)]
                mp4.save()
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
        print(f"[CDMixtapeExporter] Tagging error for '{file_path}': {e}")

    return False


class SpotifyRecommender:
    """Fetches artist top tracks, related vibe artists, and genre info from Spotify / Last.fm / iTunes."""

    def __init__(self, client_id: str = "", client_secret: str = "", refresh_token: str = ""):
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.refresh_token = refresh_token.strip()
        self._api_token: Optional[str] = None
        self._token_expiry: float = 0
        self._ssl_ctx = ssl.create_default_context()
        self._ssl_ctx.check_hostname = False
        self._ssl_ctx.verify_mode = ssl.CERT_NONE

    def _get_token(self) -> Optional[str]:
        """Gets API token via user credentials if configured."""
        now = time.time()
        if self._api_token and now < self._token_expiry:
            return self._api_token

        if self.client_id and self.client_secret:
            try:
                auth_str = f"{self.client_id}:{self.client_secret}"
                b64_auth = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
                if self.refresh_token:
                    payload = {"grant_type": "refresh_token", "refresh_token": self.refresh_token}
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
                with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=8) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    self._api_token = data.get("access_token")
                    expires_in = data.get("expires_in", 3600)
                    self._token_expiry = now + expires_in - 60
                    return self._api_token
            except Exception as e:
                print(f"[SpotifyRecommender] Spotify API token acquisition failed: {e}")

        return None

    def search_artist(self, artist_name: str) -> Dict:
        """Searches for an artist and returns {id, name, genres, popularity}."""
        token = self._get_token()
        if token:
            try:
                q = urllib.parse.quote(artist_name.strip())
                url = f"https://api.spotify.com/v1/search?q={q}&type=artist&limit=5"
                req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
                with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=8) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    items = data.get("artists", {}).get("items", [])
                    if items:
                        norm_target = normalize_string(artist_name)
                        for item in items:
                            if normalize_string(item.get("name", "")) == norm_target:
                                return {
                                    "id": item.get("id", ""),
                                    "name": item.get("name", artist_name),
                                    "genres": item.get("genres", []),
                                    "popularity": item.get("popularity", 60)
                                }
                        return {
                            "id": items[0].get("id", ""),
                            "name": items[0].get("name", artist_name),
                            "genres": items[0].get("genres", []),
                            "popularity": items[0].get("popularity", 60)
                        }
            except Exception as e:
                print(f"[SpotifyRecommender] Spotify search_artist error: {e}")

        # Fallback to iTunes / Last.fm
        return self._search_artist_itunes(artist_name)

    def get_artist_top_tracks(self, artist_id: str, artist_name: str = "", market: str = "US") -> List[Dict]:
        """Fetches top tracks for an artist via Spotify API with iTunes / Last.fm fallbacks."""
        token = self._get_token()
        if token and artist_id:
            try:
                url = f"https://api.spotify.com/v1/artists/{artist_id}/top-tracks?market={market}"
                req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
                with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=8) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    tracks = data.get("tracks", [])
                    if tracks:
                        return [
                            {
                                "title": t.get("name", ""),
                                "artist": t.get("artists", [{}])[0].get("name", artist_name),
                                "album": t.get("album", {}).get("name", ""),
                                "popularity": t.get("popularity", 50),
                                "duration_ms": t.get("duration_ms", 0),
                                "spotify_id": t.get("id", ""),
                                "release_date": t.get("album", {}).get("release_date", "")
                            }
                            for t in tracks
                        ]
            except Exception as e:
                print(f"[SpotifyRecommender] Spotify get_artist_top_tracks error: {e}")

        # Fallback 1: iTunes Top Tracks
        itunes_tracks = self.get_itunes_top_tracks(artist_name or artist_id, limit=30)
        if itunes_tracks:
            return itunes_tracks

        # Fallback 2: Last.fm Top Tracks
        return self.get_lastfm_top_tracks(artist_name or artist_id, limit=30)

    def get_related_artists(self, artist_id: str, artist_name: str = "") -> List[Dict]:
        """Fetches related vibe artists via Spotify API or Last.fm similar artists."""
        token = self._get_token()
        if token and artist_id:
            try:
                url = f"https://api.spotify.com/v1/artists/{artist_id}/related-artists"
                req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
                with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=8) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    artists = data.get("artists", [])
                    if artists:
                        return [
                            {
                                "id": a.get("id", ""),
                                "name": a.get("name", ""),
                                "popularity": a.get("popularity", 50),
                                "genres": a.get("genres", [])
                            }
                            for a in artists
                        ]
            except Exception as e:
                print(f"[SpotifyRecommender] Spotify get_related_artists error: {e}")

        # Fallback: Last.fm Similar Artists API
        target_name = artist_name or artist_id
        return self.get_lastfm_similar_artists(target_name, limit=50)

    def get_lastfm_similar_artists(self, artist_name: str, limit: int = 50) -> List[Dict]:
        """Fetches similar vibe artists via Last.fm API."""
        try:
            q = urllib.parse.quote(artist_name.strip())
            url = f"https://ws.audioscrobbler.com/2.0/?method=artist.getsimilar&artist={q}&api_key={LASTFM_API_KEY}&format=json&limit={limit}"
            req = urllib.request.Request(url, headers={"User-Agent": "SMArchive/1.1.0"})
            with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=7) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                artists = data.get("similarartists", {}).get("artist", [])
                results = []
                for a in artists:
                    try:
                        match_score = float(a.get("match", 0.5))
                    except Exception:
                        match_score = 0.5
                    pop = int(match_score * 100)
                    results.append({
                        "id": a.get("mbid", ""),
                        "name": a.get("name", ""),
                        "popularity": pop,
                        "genres": []
                    })
                return results
        except Exception as e:
            print(f"[SpotifyRecommender] Last.fm similar artists error: {e}")
            return []

    def get_lastfm_top_tracks(self, artist_name: str, limit: int = 30) -> List[Dict]:
        """Fetches top tracks via Last.fm API."""
        try:
            q = urllib.parse.quote(artist_name.strip())
            url = f"https://ws.audioscrobbler.com/2.0/?method=artist.gettoptracks&artist={q}&api_key={LASTFM_API_KEY}&format=json&limit={limit}"
            req = urllib.request.Request(url, headers={"User-Agent": "SMArchive/1.1.0"})
            with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=7) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                tracks = data.get("toptracks", {}).get("track", [])
                results = []
                for idx, t in enumerate(tracks):
                    pop = max(10, 95 - idx * 2)
                    dur_s = int(t.get("duration", 0))
                    results.append({
                        "title": t.get("name", ""),
                        "artist": t.get("artist", {}).get("name", artist_name),
                        "album": "",
                        "popularity": pop,
                        "duration_ms": dur_s * 1000 if dur_s else 0,
                        "spotify_id": t.get("mbid", ""),
                        "release_date": ""
                    })
                return results
        except Exception as e:
            print(f"[SpotifyRecommender] Last.fm top tracks error: {e}")
            return []

    def _search_artist_itunes(self, artist_name: str) -> Dict:
        """Fallback artist info via iTunes Search API."""
        try:
            q = urllib.parse.quote(artist_name.strip())
            url = f"https://itunes.apple.com/search?term={q}&entity=musicArtist&limit=3"
            req = urllib.request.Request(url, headers={"User-Agent": "SMArchive/1.1.0"})
            with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=6) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                results = data.get("results", [])
                if results:
                    r = results[0]
                    return {
                        "id": str(r.get("artistId", "")),
                        "name": r.get("artistName", artist_name),
                        "genres": [r.get("primaryGenreName", "")] if r.get("primaryGenreName") else [],
                        "popularity": 70
                    }
        except Exception as e:
            print(f"[SpotifyRecommender] iTunes fallback error: {e}")
        return {"id": "", "name": artist_name, "genres": [], "popularity": 50}

    def get_itunes_top_tracks(self, artist_name: str, limit: int = 30) -> List[Dict]:
        """Fetches top tracks for an artist via iTunes Search API."""
        try:
            q = urllib.parse.quote(artist_name.strip())
            url = f"https://itunes.apple.com/search?term={q}&entity=song&limit={limit}"
            req = urllib.request.Request(url, headers={"User-Agent": "SMArchive/1.1.0"})
            with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=6) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                results = data.get("results", [])
                tracks = []
                seen_titles = set()
                for idx, r in enumerate(results):
                    t_name = r.get("trackName", "")
                    norm = normalize_string(t_name)
                    if not norm or norm in seen_titles:
                        continue
                    seen_titles.add(norm)
                    pop = max(10, 95 - idx * 2)
                    tracks.append({
                        "title": t_name,
                        "artist": r.get("artistName", artist_name),
                        "album": r.get("collectionName", ""),
                        "popularity": pop,
                        "duration_ms": r.get("trackTimeMillis", 0),
                        "spotify_id": str(r.get("trackId", "")),
                        "release_date": r.get("releaseDate", "")[:10]
                    })
                return tracks
        except Exception as e:
            print(f"[SpotifyRecommender] iTunes top tracks fallback error: {e}")
            return []


class LocalLibraryIndex:
    """Indexes local audio files for quick artist listing and title matching."""

    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.tracks: List[Dict] = []
        self.artists_map: Dict[str, List[Dict]] = {}  # norm_artist -> [track_dicts]
        self.artist_display_names: Dict[str, str] = {}  # norm_artist -> display_name
        self.all_artists: List[str] = []

    def scan(self, progress_callback: Optional[Callable[[int, int, str], None]] = None) -> int:
        """Scans root_dir and extracts audio metadata."""
        if not os.path.exists(self.root_dir) or not os.path.isdir(self.root_dir):
            raise ValueError(f"Directory not found: {self.root_dir}")

        found_paths = []
        for root, _, files in os.walk(self.root_dir):
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in SUPPORTED_AUDIO_EXTENSIONS:
                    found_paths.append(os.path.join(root, file))

        total_files = len(found_paths)
        if total_files == 0:
            return 0

        self.tracks = []
        self.artists_map = {}
        self.artist_display_names = {}

        for idx, file_path in enumerate(found_paths):
            if progress_callback and (idx % 25 == 0 or idx == total_files - 1):
                progress_callback(idx + 1, total_files, os.path.basename(file_path))

            info = self._read_track_info(file_path)
            if info:
                self.tracks.append(info)
                norm_art = normalize_string(info["artist"])
                if norm_art:
                    if norm_art not in self.artists_map:
                        self.artists_map[norm_art] = []
                        self.artist_display_names[norm_art] = info["artist"]
                    self.artists_map[norm_art].append(info)

        display_names = sorted(list(self.artist_display_names.values()), key=lambda s: s.lower())
        self.all_artists = display_names
        return len(self.tracks)

    def _read_track_info(self, file_path: str) -> Optional[Dict]:
        """Reads tags and file metrics using Mutagen."""
        try:
            stat = os.stat(file_path)
            size_bytes = stat.st_size
            ext = os.path.splitext(file_path)[1].lower()
            filename_no_ext = os.path.splitext(os.path.basename(file_path))[0]

            artist = ""
            title = ""
            album = ""
            duration_s = 0.0

            audio = mutagen.File(file_path, easy=True)
            if audio is not None:
                if audio.info and hasattr(audio.info, "length"):
                    duration_s = float(audio.info.length)
                
                t_val = audio.get("title")
                if t_val:
                    title = str(t_val[0]) if isinstance(t_val, list) else str(t_val)
                
                a_val = audio.get("artist") or audio.get("albumartist")
                if a_val:
                    artist = str(a_val[0]) if isinstance(a_val, list) else str(a_val)
                
                alb_val = audio.get("album")
                if alb_val:
                    album = str(alb_val[0]) if isinstance(alb_val, list) else str(alb_val)

            # Fallback: Parse from filename if tags are blank
            if not title or not artist:
                if " - " in filename_no_ext:
                    parts = filename_no_ext.split(" - ", 1)
                    if not artist:
                        p0 = re.sub(r'^\d+\s*[-_.]\s*', '', parts[0].strip())
                        artist = p0
                    if not title:
                        title = parts[1].strip()
                else:
                    if not title:
                        title = re.sub(r'^\d+\s*[-_.]\s*', '', filename_no_ext).strip()

            if not artist:
                parent_dir = os.path.basename(os.path.dirname(file_path))
                grandparent_dir = os.path.basename(os.path.dirname(os.path.dirname(file_path)))
                if grandparent_dir and grandparent_dir.lower() not in ("music", "downloads", "audio"):
                    artist = grandparent_dir
                elif parent_dir and parent_dir.lower() not in ("music", "downloads", "audio"):
                    artist = parent_dir
                else:
                    artist = "Unknown Artist"

            if not title:
                title = filename_no_ext

            is_lossless = ext in LOSSLESS_EXTENSIONS

            return {
                "file_path": file_path,
                "filename": os.path.basename(file_path),
                "artist": artist.strip(),
                "title": title.strip(),
                "album": album.strip(),
                "size_bytes": size_bytes,
                "duration_s": duration_s,
                "ext": ext,
                "is_lossless": is_lossless,
                "norm_artist": normalize_string(artist),
                "norm_title": normalize_string(title)
            }
        except Exception:
            return None


def canonical_track_key(artist: str, title: str) -> str:
    """Returns a unique canonical identifier for a song (normalized artist + title)."""
    na = normalize_string(artist)
    nt = normalize_string(title)
    return f"{na}:::{nt}"


BLOAT_TITLE_REGEX = re.compile(
    r'\b(full album|complete album|ost mix|lofi mix|hour mix|compilation|soundtrack mix|non-stop|all songs|entire discography|extended mix|marathon)\b',
    re.IGNORECASE
)


def is_valid_mixtape_track(trk: Dict, max_dur_s: int = 270) -> bool:
    """Filters out mega-mixes, full album compilations, podcast episodes, and ultra-short skits."""
    dur = trk.get("duration_s", 0)
    # Check max duration (default 4:30 = 270s) and min duration (40s)
    if dur > 0:
        if max_dur_s > 0 and dur > max_dur_s:
            return False
        if dur < 35:
            return False

    # Check bloat compilation keywords
    title_str = f"{trk.get('title', '')} {trk.get('album', '')} {trk.get('filename', '')}"
    if BLOAT_TITLE_REGEX.search(title_str):
        return False

    # Check extreme standalone filesize for lossy audio (e.g. 300MB mp3 files)
    if not trk.get("is_lossless", False) and trk.get("size_bytes", 0) > 30 * 1024 * 1024:
        return False

    return True


def get_track_bitrate_kbps(trk: Dict) -> int:
    """Estimates average bitrate in kbps of a track."""
    dur = trk.get("duration_s", 0) or 0
    size = trk.get("size_bytes", 0) or 0
    if dur > 5 and size > 1024:
        kbps = int((size * 8) / dur / 1000)
        return max(32, min(320, kbps))
    return 256


def should_transcode_track(trk: Dict, squeeze_mode: str, target_kbps: int) -> bool:
    """Determines whether a track should be transcoded to reduce filesize."""
    if squeeze_mode == "none":
        return False
    if squeeze_mode == "lossless_only":
        return trk.get("is_lossless", False)
    # squeeze_mode == "all" (compress lossless and any file with higher bitrate than target)
    if trk.get("is_lossless", False):
        return True
    dur = trk.get("duration_s", 0) or 210
    if dur > 0:
        est_curr_kbps = int((trk.get("size_bytes", 0) * 8) / dur / 1000)
        if est_curr_kbps > target_kbps + 15:
            return True
    return False


class CDMixtapePlanner:
    """
    Coordinates Spotify recommendations, local library matching,
    and knapsack capacity packing to produce an optimal 700MB CD tracklist.
    """

    def __init__(self, recommender: SpotifyRecommender, library_index: LocalLibraryIndex):
        self.recommender = recommender
        self.library_index = library_index

    def plan_mixtape(
        self,
        seed_artist_name: str,
        seed_track_count: int = 20,
        preset_key: str = "700MB_DATA_CD",
        transcode_lossless_to_mp3: bool = True,
        target_mp3_kbps: int = 256,
        custom_capacity_mb: Optional[int] = None,
        max_vibe_tracks_per_artist: int = 3,
        max_song_duration_s: int = 270,
        squeeze_mode: str = "all",
        mix_style: str = "chaos_shuffle",
        normalize_audio: str = "ebu_r128",
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> Dict:
        """
        Plans the full mixtape to fill capacity cleanly with ZERO duplicates,
        strict max song length (<= 4:30), selectable compression, and true
        library-wide randomized artist/song selection (no alphabetical bias).
        """
        if not transcode_lossless_to_mp3:
            squeeze_mode = "none"

        preset = CAPACITY_PRESETS.get(preset_key, CAPACITY_PRESETS["700MB_DATA_CD"])
        cap_type = preset["type"]
        
        if custom_capacity_mb and cap_type == "bytes":
            target_limit = int(custom_capacity_mb * 1024 * 1024 * 0.993)
            display_limit = f"{custom_capacity_mb} MB"
        else:
            target_limit = preset["target_value"]
            display_limit = preset["display_limit"]

        # Check for full library chaos / gamble mode
        clean_seed_input = seed_artist_name.strip()
        is_chaos_seed = (
            not clean_seed_input or
            "chaos" in clean_seed_input.lower() or
            "gamble" in clean_seed_input.lower() or
            "random" in clean_seed_input.lower()
        )

        selected_tracks: List[Dict] = []
        used_file_paths = set()
        used_track_keys = set()
        vibe_artist_counts: Dict[str, int] = {}
        current_metric_total = 0
        current_bytes_total = 0

        is_normalizing = (normalize_audio or "").lower().strip() not in ("off", "none", "")

        # Helper to calculate effective track size / duration with Smart Bitrate Capping
        def get_track_metric(local_trk: Dict) -> Tuple[int, int, bool]:
            orig_bytes = local_trk["size_bytes"]
            dur_s = local_trk["duration_s"] or 210
            is_lossless = local_trk.get("is_lossless", False)

            if is_normalizing and cap_type == "bytes":
                # Smart Bitrate Capping: normalized audio is re-encoded,
                # but we never inflate a lower-bitrate source file.
                if is_lossless:
                    eff_kbps = target_mp3_kbps
                else:
                    src_kbps = get_track_bitrate_kbps(local_trk)
                    eff_kbps = min(src_kbps, target_mp3_kbps)
                est_bytes = int((dur_s * (eff_kbps * 1000) / 8) + 65536)
                will_trans = True
            else:
                will_trans = should_transcode_track(local_trk, squeeze_mode, target_mp3_kbps)
                if will_trans:
                    est_bytes = int((dur_s * (target_mp3_kbps * 1000) / 8) + 65536)
                else:
                    est_bytes = orig_bytes

            if cap_type == "duration":
                metric = int(dur_s)
            else:
                metric = est_bytes

            return metric, est_bytes, will_trans

        if is_chaos_seed:
            if progress_callback:
                progress_callback("🎲 Rolling library-wide Chaos Gamble mix...")
            seed_artist_info = {
                "id": "",
                "name": "🎲 Full Library Chaos",
                "genres": ["Chaos", "Shuffle", "Eclectic Variety"],
                "popularity": 99
            }
            related_artists = []
            norm_seed_artist = ""
            norm_real_seed = ""
        else:
            if progress_callback:
                progress_callback(f"Finding top Spotify hits for '{clean_seed_input}'...")

            # 1. Look up Seed Artist
            seed_artist_info = self.recommender.search_artist(clean_seed_input)
            seed_artist_id = seed_artist_info.get("id", "")
            real_seed_name = seed_artist_info.get("name", clean_seed_input)

            # 2. Get Seed Artist Top Tracks
            spotify_seed_tracks = self.recommender.get_artist_top_tracks(seed_artist_id, real_seed_name)

            # 3. Get Related Vibe Artists
            if progress_callback:
                progress_callback(f"Discovering vibe & related artists for '{real_seed_name}'...")

            related_artists = self.recommender.get_related_artists(seed_artist_id, real_seed_name)

            norm_seed_artist = normalize_string(clean_seed_input)
            norm_real_seed = normalize_string(real_seed_name)
            
            local_seed_tracks = (
                self.library_index.artists_map.get(norm_seed_artist, []) or
                self.library_index.artists_map.get(norm_real_seed, [])
            )

            # Phase 1: Match Seed Artist Top Tracks
            matched_seed_tracks = []
            for s_trk in spotify_seed_tracks:
                norm_title = normalize_string(s_trk["title"])
                best_match = None
                for loc_trk in local_seed_tracks:
                    trk_key = canonical_track_key(loc_trk["artist"], loc_trk["title"])
                    if loc_trk["file_path"] in used_file_paths or trk_key in used_track_keys:
                        continue
                    if not is_valid_mixtape_track(loc_trk, max_dur_s=max_song_duration_s + 60):
                        continue
                    loc_norm = loc_trk["norm_title"]
                    if loc_norm == norm_title or (len(norm_title) > 4 and norm_title in loc_norm) or (len(loc_norm) > 4 and loc_norm in norm_title):
                        best_match = loc_trk
                        break

                if best_match:
                    trk_key = canonical_track_key(best_match["artist"], best_match["title"])
                    matched_seed_tracks.append((best_match, s_trk.get("popularity", 80), "seed"))
                    used_file_paths.add(best_match["file_path"])
                    used_track_keys.add(trk_key)

            # If library has remaining seed tracks not in the Spotify list, randomly pick them up to seed_track_count
            remaining_seed_tracks = [
                loc_trk for loc_trk in local_seed_tracks
                if loc_trk["file_path"] not in used_file_paths and
                canonical_track_key(loc_trk["artist"], loc_trk["title"]) not in used_track_keys and
                is_valid_mixtape_track(loc_trk, max_dur_s=max_song_duration_s + 60)
            ]
            random.shuffle(remaining_seed_tracks)

            for loc_trk in remaining_seed_tracks:
                if len(matched_seed_tracks) >= seed_track_count:
                    break
                trk_key = canonical_track_key(loc_trk["artist"], loc_trk["title"])
                matched_seed_tracks.append((loc_trk, 50, "seed"))
                used_file_paths.add(loc_trk["file_path"])
                used_track_keys.add(trk_key)

            matched_seed_tracks = matched_seed_tracks[:seed_track_count]

            # Reset used sets before staging into selected_tracks
            used_file_paths.clear()
            used_track_keys.clear()

            for loc_trk, pop_score, role in matched_seed_tracks:
                trk_key = canonical_track_key(loc_trk["artist"], loc_trk["title"])
                if loc_trk["file_path"] in used_file_paths or trk_key in used_track_keys:
                    continue

                m_val, est_b, will_tr = get_track_metric(loc_trk)
                if current_metric_total + m_val <= target_limit:
                    current_metric_total += m_val
                    current_bytes_total += est_b
                    used_file_paths.add(loc_trk["file_path"])
                    used_track_keys.add(trk_key)
                    selected_tracks.append({
                        **loc_trk,
                        "effective_bytes": est_b,
                        "popularity": pop_score,
                        "role": role,
                        "role_desc": f"Seed: {loc_trk['artist']}",
                        "will_transcode": will_tr
                    })
                else:
                    break

            # Phase 2: Collect Vibe Tracks from Direct Related Artists
            if progress_callback:
                progress_callback(f"Filling capacity with related vibe artists (max {max_vibe_tracks_per_artist} per artist)...")

            candidate_vibe_tracks: List[Tuple[Dict, int, str, str]] = []

            related_norm_map = {}
            for idx, rel in enumerate(related_artists):
                rel_name = rel.get("name", "")
                rel_norm = normalize_string(rel_name)
                if rel_norm and rel_norm not in (norm_seed_artist, norm_real_seed):
                    weight = max(25, 95 - idx * 2)
                    related_norm_map[rel_norm] = (rel_name, weight)

            seen_candidate_keys = set()
            for norm_art, (disp_art, weight) in related_norm_map.items():
                loc_tracks = self.library_index.artists_map.get(norm_art, [])
                if not loc_tracks:
                    continue
                
                unique_artist_tracks = []
                for loc_trk in loc_tracks:
                    trk_key = canonical_track_key(loc_trk["artist"], loc_trk["title"])
                    if loc_trk["file_path"] not in used_file_paths and trk_key not in used_track_keys and trk_key not in seen_candidate_keys:
                        if is_valid_mixtape_track(loc_trk, max_dur_s=max_song_duration_s):
                            seen_candidate_keys.add(trk_key)
                            unique_artist_tracks.append(loc_trk)

                # Randomize which tracks are sampled from this vibe artist so it's not always alphabetical
                random.shuffle(unique_artist_tracks)

                for loc_trk in unique_artist_tracks[:max_vibe_tracks_per_artist]:
                    candidate_vibe_tracks.append((loc_trk, weight, "vibe", f"Vibe: {disp_art}"))

            # Sort candidate vibe tracks by similarity weight descending, with slight shuffle for equal weights
            candidate_vibe_tracks.sort(key=lambda x: x[1] + random.uniform(0, 0.5), reverse=True)

            for loc_trk, pop_score, role, role_desc in candidate_vibe_tracks:
                trk_key = canonical_track_key(loc_trk["artist"], loc_trk["title"])
                art_key = loc_trk["norm_artist"]

                if loc_trk["file_path"] in used_file_paths or trk_key in used_track_keys:
                    continue

                if vibe_artist_counts.get(art_key, 0) >= max_vibe_tracks_per_artist:
                    continue

                m_val, est_b, will_tr = get_track_metric(loc_trk)
                if current_metric_total + m_val <= target_limit:
                    current_metric_total += m_val
                    current_bytes_total += est_b
                    used_file_paths.add(loc_trk["file_path"])
                    used_track_keys.add(trk_key)
                    vibe_artist_counts[art_key] = vibe_artist_counts.get(art_key, 0) + 1
                    selected_tracks.append({
                        **loc_trk,
                        "effective_bytes": est_b,
                        "popularity": pop_score,
                        "role": role,
                        "role_desc": role_desc,
                        "will_transcode": will_tr
                    })

        # Phase 2.5: Wide Library Vibe & Diversity Expansion (True A-Z Random Sampling)
        remaining_capacity = target_limit - current_metric_total
        min_slot_size = 500 * 1024 if cap_type == "bytes" else 30

        if remaining_capacity > 5 * 1024 * 1024:  # If more than 5 MB remaining
            if progress_callback:
                progress_callback("🎲 Randomly sampling artists across entire library (A-Z chaos)...")

            # Gather all library artists and randomly shuffle them to eliminate A-Z scanning bias
            all_norm_artists = list(self.library_index.artists_map.keys())
            random.shuffle(all_norm_artists)

            expanded_vibe_tracks: List[Tuple[Dict, int, str, str]] = []
            
            # Target 1-2 tracks per artist for maximum library-wide chaos & variety
            per_artist_limit = 1 if is_chaos_seed else min(2, max_vibe_tracks_per_artist)

            for norm_art in all_norm_artists:
                if not is_chaos_seed and (norm_art == norm_seed_artist or norm_art == norm_real_seed):
                    continue
                if vibe_artist_counts.get(norm_art, 0) >= max_vibe_tracks_per_artist:
                    continue

                loc_tracks = list(self.library_index.artists_map.get(norm_art, []))
                # Shuffle tracks within artist so it doesn't always pick track 1 or alphabetical A
                random.shuffle(loc_tracks)

                artist_added = 0
                for loc_trk in loc_tracks:
                    trk_key = canonical_track_key(loc_trk["artist"], loc_trk["title"])
                    if loc_trk["file_path"] not in used_file_paths and trk_key not in used_track_keys:
                        if is_valid_mixtape_track(loc_trk, max_dur_s=max_song_duration_s):
                            disp_art = loc_trk["artist"]
                            role_label = "Chaos" if is_chaos_seed else "Vibe"
                            expanded_vibe_tracks.append((loc_trk, 50, "vibe", f"{role_label}: {disp_art}"))
                            artist_added += 1
                            if artist_added >= per_artist_limit:
                                break

            # Shuffle all expanded candidates across artists
            random.shuffle(expanded_vibe_tracks)

            for loc_trk, pop_score, role, role_desc in expanded_vibe_tracks:
                trk_key = canonical_track_key(loc_trk["artist"], loc_trk["title"])
                art_key = loc_trk["norm_artist"]

                if loc_trk["file_path"] in used_file_paths or trk_key in used_track_keys:
                    continue

                if vibe_artist_counts.get(art_key, 0) >= max_vibe_tracks_per_artist:
                    continue

                m_val, est_b, will_tr = get_track_metric(loc_trk)
                if current_metric_total + m_val <= target_limit:
                    current_metric_total += m_val
                    current_bytes_total += est_b
                    used_file_paths.add(loc_trk["file_path"])
                    used_track_keys.add(trk_key)
                    vibe_artist_counts[art_key] = vibe_artist_counts.get(art_key, 0) + 1
                    selected_tracks.append({
                        **loc_trk,
                        "effective_bytes": est_b,
                        "popularity": pop_score,
                        "role": role,
                        "role_desc": role_desc,
                        "will_transcode": will_tr
                    })
                else:
                    break

        # Phase 3: Knapsack Micro-Gap Filler (Shuffled pool to avoid alphabetical A-bias)
        remaining_capacity = target_limit - current_metric_total
        
        if remaining_capacity > min_slot_size:
            if progress_callback:
                progress_callback("Maximizing disc capacity (final micro-gap fitting)...")

            # Collect remaining unique standard songs and randomize
            remaining_library_tracks = []
            seen_rem_keys = set()
            for t in self.library_index.tracks:
                trk_key = canonical_track_key(t["artist"], t["title"])
                if t["file_path"] not in used_file_paths and trk_key not in used_track_keys and trk_key not in seen_rem_keys:
                    if is_valid_mixtape_track(t, max_dur_s=max_song_duration_s):
                        seen_rem_keys.add(trk_key)
                        remaining_library_tracks.append(t)

            # Randomize candidate pool so knapsack tests songs across the entire library
            random.shuffle(remaining_library_tracks)

            filler_artist_counts: Dict[str, int] = {}

            while remaining_capacity > min_slot_size and remaining_library_tracks:
                best_fit = None
                best_diff = float("inf")
                best_metric = 0
                best_est_b = 0
                best_will_tr = False

                for candidate in remaining_library_tracks:
                    c_art = candidate["norm_artist"]
                    if filler_artist_counts.get(c_art, 0) >= 1 or vibe_artist_counts.get(c_art, 0) >= max_vibe_tracks_per_artist:
                        continue

                    m_val, est_b, will_tr = get_track_metric(candidate)
                    if m_val <= remaining_capacity:
                        diff = remaining_capacity - m_val
                        if diff < best_diff:
                            best_diff = diff
                            best_fit = candidate
                            best_metric = m_val
                            best_est_b = est_b
                            best_will_tr = will_tr

                if best_fit:
                    best_key = canonical_track_key(best_fit["artist"], best_fit["title"])
                    c_art = best_fit["norm_artist"]
                    filler_artist_counts[c_art] = filler_artist_counts.get(c_art, 0) + 1

                    remaining_library_tracks = [
                        t for t in remaining_library_tracks
                        if t["file_path"] != best_fit["file_path"] and canonical_track_key(t["artist"], t["title"]) != best_key
                    ]
                    used_file_paths.add(best_fit["file_path"])
                    used_track_keys.add(best_key)
                    current_metric_total += best_metric
                    current_bytes_total += best_est_b
                    remaining_capacity -= best_metric
                    selected_tracks.append({
                        **best_fit,
                        "effective_bytes": best_est_b,
                        "popularity": 40,
                        "role": "filler",
                        "role_desc": f"Filler: {best_fit['artist']}",
                        "will_transcode": best_will_tr
                    })
                else:
                    break

        # Apply Mixtape Track Flow & Sequencing
        if mix_style == "chaos_shuffle":
            random.shuffle(selected_tracks)
        elif mix_style == "seed_intro":
            seed_tracks = [t for t in selected_tracks if t.get("role") == "seed"]
            if seed_tracks:
                first_track = random.choice(seed_tracks)
                other_tracks = [t for t in selected_tracks if t != first_track]
                random.shuffle(other_tracks)
                selected_tracks = [first_track] + other_tracks
            else:
                random.shuffle(selected_tracks)
        # if mix_style == "grouped", keep structured Seed -> Vibe -> Filler ordering

        # Assign sequential track numbers with car-optimized clean display names
        for idx, trk in enumerate(selected_tracks, start=1):
            trk["track_number"] = idx
            clean_art = sanitize_filename(clean_display_artist(trk["artist"]), 40)
            clean_title = sanitize_filename(clean_display_title(trk["title"]), 50)
            target_ext = ".mp3" if (trk["will_transcode"] or (is_normalizing and cap_type == "bytes")) else trk["ext"]
            trk["target_filename"] = f"{idx:03d} - {clean_art} - {clean_title}{target_ext}"

        total_duration_s = sum(t["duration_s"] for t in selected_tracks)
        seed_count = sum(1 for t in selected_tracks if t["role"] == "seed")
        vibe_count = sum(1 for t in selected_tracks if t["role"] == "vibe")
        filler_count = sum(1 for t in selected_tracks if t["role"] == "filler")
        utilization_pct = (current_metric_total / target_limit * 100) if target_limit > 0 else 0

        mins = int(total_duration_s // 60)
        secs = int(total_duration_s % 60)
        dur_str = f"{mins}m {secs:02d}s"

        total_mb = current_bytes_total / (1024 * 1024)
        target_mb = target_limit / (1024 * 1024) if cap_type == "bytes" else 700.0

        summary = {
            "total_tracks": len(selected_tracks),
            "seed_count": seed_count,
            "vibe_count": vibe_count,
            "filler_count": filler_count,
            "total_bytes": current_bytes_total,
            "total_mb": total_mb,
            "target_mb": target_mb,
            "display_limit": display_limit,
            "total_duration_s": total_duration_s,
            "duration_str": dur_str,
            "utilization_pct": min(100.0, utilization_pct),
            "cap_type": cap_type
        }

        return {
            "selected_tracks": selected_tracks,
            "summary": summary,
            "seed_artist": seed_artist_info,
            "related_artists": related_artists
        }


class CDMixtapeExporter:
    """
    Safely copies/transcodes selected mixtape tracks into a dedicated CD burn directory,
    optimizes ID3v2.3 tags for car stereos (Ford SYNC), and generates an M3U playlist file + printable CD insert.
    """

    def __init__(self, ffmpeg_path: str = "ffmpeg.exe"):
        self.ffmpeg_path = ffmpeg_path
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()

    def export(
        self,
        mixtape_plan: Dict,
        destination_dir: str,
        folder_name: str = "",
        mp3_bitrate_kbps: int = 320,
        normalize_audio: str = "ebu_r128",
        progress_callback: Optional[Callable[[int, int, str, str], None]] = None
    ) -> Dict:
        """
        Executes non-destructive file copying and optional transcoding with 100% automated
        car stereo ID3v2.3 metadata optimization (Ford SYNC compliant) and optional
        EBU R128 / ITU-R BS.1770 audio loudness normalization.
        """
        self._cancel_event.clear()
        tracks = mixtape_plan.get("selected_tracks", [])
        if not tracks:
            raise ValueError("No tracks in mixtape plan to export.")

        seed_name = mixtape_plan.get("seed_artist", {}).get("name") or "Mixtape"
        clean_seed = clean_display_artist(seed_name)
        if not folder_name:
            folder_seed = sanitize_filename(clean_seed, 30)
            folder_name = f"CD_Burn_{folder_seed}_Mixtape"

        mixtape_album_title = f"{clean_seed} Mixtape" if "chaos" not in clean_seed.lower() else "Library Chaos Mixtape"

        target_folder = os.path.join(destination_dir, folder_name)
        os.makedirs(target_folder, exist_ok=True)

        # Determine audio normalization filter
        norm_filter = None
        norm_label = ""
        clean_norm = (normalize_audio or "").lower().strip()
        if "ebu" in clean_norm or "14" in clean_norm or "balanced" in clean_norm:
            norm_filter = "loudnorm=I=-14:TP=-1.0:LRA=11"
            norm_label = "EBU R128 (-14 LUFS)"
        elif "hifi" in clean_norm or "16" in clean_norm or "dynamic" in clean_norm:
            norm_filter = "loudnorm=I=-16:TP=-1.0:LRA=11"
            norm_label = "Car HiFi (-16 LUFS)"

        copied_count = 0
        transcoded_count = 0
        errors = []
        m3u_lines = ["#EXTM3U\n"]

        total_tracks = len(tracks)

        for idx, trk in enumerate(tracks, start=1):
            if self._cancel_event.is_set():
                break

            src_file = trk["file_path"]
            dst_filename = trk["target_filename"]
            dst_file = os.path.join(target_folder, dst_filename)

            clean_art = clean_display_artist(trk.get('artist', ''))
            clean_tit = clean_display_title(trk.get('title', ''))
            disp_title = f"{clean_art} - {clean_tit}"
            if progress_callback:
                progress_callback(idx, total_tracks, disp_title, "Processing...")

            if not os.path.exists(src_file):
                errors.append(f"Source file missing: {src_file}")
                continue

            try:
                transcode_needed = trk.get("will_transcode", False)
                norm_needed = bool(norm_filter)

                if transcode_needed or norm_needed:
                    if transcode_needed and norm_needed:
                        status_desc = f"Normalizing ({norm_label}) & transcoding ({mp3_bitrate_kbps}k)..."
                    elif norm_needed:
                        status_desc = f"Normalizing levels ({norm_label})..."
                    else:
                        status_desc = f"Transcoding ({mp3_bitrate_kbps}k)..."

                    if progress_callback:
                        progress_callback(idx, total_tracks, disp_title, status_desc)

                    cmd = [
                        self.ffmpeg_path,
                        "-y",
                        "-i", src_file,
                        "-vn"
                    ]

                    if norm_filter:
                        cmd.extend(["-af", norm_filter])

                    dst_ext = os.path.splitext(dst_filename)[1].lower()
                    if dst_ext == ".mp3" or transcode_needed:
                        # Smart Bitrate Capping: Never inflate an existing lower-bitrate lossy track
                        if not trk.get("is_lossless", False):
                            src_kbps = get_track_bitrate_kbps(trk)
                            eff_kbps = min(src_kbps, mp3_bitrate_kbps)
                        else:
                            eff_kbps = mp3_bitrate_kbps
                        cmd.extend(["-c:a", "libmp3lame", "-b:a", f"{eff_kbps}k"])
                    elif dst_ext == ".flac":
                        cmd.extend(["-c:a", "flac"])
                    elif dst_ext in (".m4a", ".mp4", ".aac"):
                        cmd.extend(["-c:a", "aac", "-b:a", f"{mp3_bitrate_kbps}k"])
                    elif dst_ext in (".wav", ".aiff"):
                        cmd.extend(["-c:a", "pcm_s16le"])
                    else:
                        if not trk.get("is_lossless", False):
                            src_kbps = get_track_bitrate_kbps(trk)
                            eff_kbps = min(src_kbps, mp3_bitrate_kbps)
                        else:
                            eff_kbps = mp3_bitrate_kbps
                        cmd.extend(["-c:a", "libmp3lame", "-b:a", f"{eff_kbps}k"])

                    cmd.append(dst_file)

                    res = subprocess.run(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        creationflags=CREATION_FLAGS_BACKGROUND
                    )

                    if res.returncode == 0 and os.path.exists(dst_file):
                        transcoded_count += 1
                        # Automatically write car-optimized ID3v2.3 tags
                        write_car_optimized_tags(
                            file_path=dst_file,
                            artist=clean_art,
                            title=clean_tit,
                            album=mixtape_album_title,
                            track_num=idx,
                            total_tracks=total_tracks
                        )
                    else:
                        # Fallback to copy if FFmpeg returned an error
                        shutil.copy2(src_file, dst_file)
                        copied_count += 1
                        write_car_optimized_tags(
                            file_path=dst_file,
                            artist=clean_art,
                            title=clean_tit,
                            album=mixtape_album_title,
                            track_num=idx,
                            total_tracks=total_tracks
                        )
                else:
                    if progress_callback:
                        progress_callback(idx, total_tracks, disp_title, "Copying & optimizing tags...")
                    shutil.copy2(src_file, dst_file)
                    copied_count += 1
                    # Ensure directly copied files also receive car-optimized ID3v2.3 tags and synced track numbers
                    write_car_optimized_tags(
                        file_path=dst_file,
                        artist=clean_art,
                        title=clean_tit,
                        album=mixtape_album_title,
                        track_num=idx,
                        total_tracks=total_tracks
                    )

                dur_int = int(trk.get("duration_s", 0))
                m3u_lines.append(f"#EXTINF:{dur_int},{clean_art} - {clean_tit}\n")
                m3u_lines.append(f"{dst_filename}\n")

            except Exception as e:
                errors.append(f"Error copying '{src_file}': {e}")

        # 1. Write M3U Playlist
        playlist_path = os.path.join(target_folder, "000_Mixtape_Burn_Playlist.m3u")
        try:
            with open(playlist_path, "w", encoding="utf-8") as f:
                f.writelines(m3u_lines)
        except Exception as e:
            print(f"[CDMixtapeExporter] Failed writing playlist: {e}")

        # 2. Write Printable Jewel Case Insert (HTML / CSS print-ready)
        summary = mixtape_plan.get("summary", {})
        dur_str = summary.get("duration_str", "")
        total_mb = summary.get("total_mb", 0.0)
        
        norm_note = f" &bull; {norm_label}" if norm_label else ""
        insert_html_path = os.path.join(target_folder, "CD_Jewel_Case_Insert.html")
        try:
            rows_html = ""
            for t in tracks:
                d_sec = t.get("duration_s", 0)
                m, s = int(d_sec // 60), int(d_sec % 60)
                rows_html += f"""
                <tr>
                    <td class="num">{t['track_number']:02d}</td>
                    <td class="artist">{html.escape(t['artist'])}</td>
                    <td class="title">{html.escape(t['title'])}</td>
                    <td class="time">{m}:{s:02d}</td>
                </tr>
                """

            html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{html.escape(seed_name)} - CD Mixtape Jewel Case Insert</title>
<style>
  @page {{ size: letter; margin: 0.5in; }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; padding: 20px; }}
  .case-insert {{
    width: 4.75in;
    min-height: 4.75in;
    border: 2px dashed #00E5FF;
    padding: 16px;
    background: #090e17;
    box-sizing: border-box;
    margin: 0 auto;
    page-break-inside: avoid;
  }}
  .header {{ border-bottom: 2px solid #00E5FF; padding-bottom: 8px; margin-bottom: 10px; }}
  .title-main {{ font-size: 16pt; font-weight: bold; color: #00E5FF; margin: 0; }}
  .subtitle {{ font-size: 9pt; color: #94A3B8; margin-top: 2px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 7.5pt; }}
  th {{ text-align: left; color: #38BDF8; border-bottom: 1px solid #1E293B; padding: 2px 4px; }}
  td {{ padding: 2px 4px; border-bottom: 1px dotted #1E293B; }}
  .num {{ font-weight: bold; color: #00E5FF; width: 18px; }}
  .artist {{ font-weight: 600; color: #F1F5F9; max-width: 110px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .title {{ color: #CBD5E1; max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .time {{ text-align: right; color: #94A3B8; width: 32px; font-family: monospace; }}
  .footer {{ margin-top: 10px; padding-top: 6px; border-top: 1px solid #1E293B; font-size: 7.5pt; color: #64748B; display: flex; justify-content: space-between; }}
  @media print {{
    body {{ background: white; color: black; padding: 0; }}
    .case-insert {{ background: white; border: 1px dashed #666; color: black; }}
    .title-main {{ color: black; }}
    th {{ color: black; border-bottom: 1px solid black; }}
    td {{ border-bottom: 1px dotted #ccc; }}
    .artist, .title, .num, .time {{ color: black; }}
    .footer {{ color: #444; border-top: 1px solid black; }}
  }}
</style>
</head>
<body>
  <div class="case-insert">
    <div class="header">
      <div class="title-main">{html.escape(seed_name)} &amp; VIBES</div>
      <div class="subtitle">Custom CD Mixtape &bull; {len(tracks)} Tracks &bull; {dur_str} &bull; {total_mb:.1f} MB{norm_note}</div>
    </div>
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>Artist</th>
          <th>Title</th>
          <th style="text-align:right">Dur</th>
        </tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
    <div class="footer">
      <span>Generated with Shallot Media Archive</span>
      <span>Total: {len(tracks)} Tracks ({dur_str})</span>
    </div>
  </div>
</body>
</html>
"""
            with open(insert_html_path, "w", encoding="utf-8") as f:
                f.write(html_content)
        except Exception as e:
            print(f"[CDMixtapeExporter] Failed writing HTML insert: {e}")

        was_cancelled = self._cancel_event.is_set()

        return {
            "target_folder": target_folder,
            "total_tracks": total_tracks,
            "copied_count": copied_count,
            "transcoded_count": transcoded_count,
            "errors": errors,
            "playlist_path": playlist_path,
            "insert_path": insert_html_path,
            "cancelled": was_cancelled
        }
