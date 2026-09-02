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
import urllib.request
import urllib.parse
import subprocess
import threading
from typing import Dict, List, Optional, Tuple, Callable

import mutagen
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TRCK
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
        return self.get_lastfm_similar_artists(target_name, limit=25)

    def get_lastfm_similar_artists(self, artist_name: str, limit: int = 25) -> List[Dict]:
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
        target_mp3_kbps: int = 320,
        custom_capacity_mb: Optional[int] = None,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> Dict:
        """
        Plans the full mixtape to fill capacity cleanly.
        """
        preset = CAPACITY_PRESETS.get(preset_key, CAPACITY_PRESETS["700MB_DATA_CD"])
        cap_type = preset["type"]
        
        if custom_capacity_mb and cap_type == "bytes":
            target_limit = int(custom_capacity_mb * 1024 * 1024 * 0.993)
            display_limit = f"{custom_capacity_mb} MB"
        else:
            target_limit = preset["target_value"]
            display_limit = preset["display_limit"]

        if progress_callback:
            progress_callback(f"Finding top Spotify hits for '{seed_artist_name}'...")

        # 1. Look up Seed Artist
        seed_artist_info = self.recommender.search_artist(seed_artist_name)
        seed_artist_id = seed_artist_info.get("id", "")
        real_seed_name = seed_artist_info.get("name", seed_artist_name)

        # 2. Get Seed Artist Top Tracks
        spotify_seed_tracks = self.recommender.get_artist_top_tracks(seed_artist_id, real_seed_name)

        # 3. Get Related Vibe Artists
        if progress_callback:
            progress_callback(f"Discovering vibe & related artists for '{real_seed_name}'...")

        related_artists = self.recommender.get_related_artists(seed_artist_id, real_seed_name)

        # 4. Helper to calculate effective track size / duration
        def get_track_metric(local_trk: Dict) -> Tuple[int, int]:
            orig_bytes = local_trk["size_bytes"]
            dur_s = local_trk["duration_s"] or 210
            
            if transcode_lossless_to_mp3 and local_trk["is_lossless"]:
                est_bytes = int((dur_s * (target_mp3_kbps * 1000) / 8) + 131072)
            else:
                est_bytes = orig_bytes

            if cap_type == "duration":
                metric = int(dur_s)
            else:
                metric = est_bytes

            return metric, est_bytes

        # 5. Build candidate pools from local library
        if progress_callback:
            progress_callback("Matching local music files with Spotify vibe...")

        norm_seed_artist = normalize_string(seed_artist_name)
        norm_real_seed = normalize_string(real_seed_name)
        
        local_seed_tracks = (
            self.library_index.artists_map.get(norm_seed_artist, []) or
            self.library_index.artists_map.get(norm_real_seed, [])
        )

        selected_tracks: List[Dict] = []
        used_file_paths = set()
        current_metric_total = 0
        current_bytes_total = 0

        # Phase 1: Match Seed Artist Top Tracks
        matched_seed_tracks = []
        for s_trk in spotify_seed_tracks:
            norm_title = normalize_string(s_trk["title"])
            best_match = None
            for loc_trk in local_seed_tracks:
                if loc_trk["file_path"] in used_file_paths:
                    continue
                loc_norm = loc_trk["norm_title"]
                if loc_norm == norm_title or (len(norm_title) > 4 and norm_title in loc_norm) or (len(loc_norm) > 4 and loc_norm in norm_title):
                    best_match = loc_trk
                    break

            if best_match:
                matched_seed_tracks.append((best_match, s_trk.get("popularity", 80), "seed"))
                used_file_paths.add(best_match["file_path"])

        # If library has remaining seed tracks not in the Spotify list, add them up to seed_track_count
        for loc_trk in local_seed_tracks:
            if loc_trk["file_path"] not in used_file_paths and len(matched_seed_tracks) < seed_track_count:
                matched_seed_tracks.append((loc_trk, 50, "seed"))
                used_file_paths.add(loc_trk["file_path"])

        matched_seed_tracks = matched_seed_tracks[:seed_track_count]

        for loc_trk, pop_score, role in matched_seed_tracks:
            m_val, est_b = get_track_metric(loc_trk)
            if current_metric_total + m_val <= target_limit:
                current_metric_total += m_val
                current_bytes_total += est_b
                selected_tracks.append({
                    **loc_trk,
                    "effective_bytes": est_b,
                    "popularity": pop_score,
                    "role": role,
                    "role_desc": f"Seed: {loc_trk['artist']}",
                    "will_transcode": transcode_lossless_to_mp3 and loc_trk["is_lossless"]
                })
            else:
                break

        # Phase 2: Collect Vibe Tracks from Related Artists
        if progress_callback:
            progress_callback("Filling remaining capacity with related vibe artists...")

        candidate_vibe_tracks: List[Tuple[Dict, int, str, str]] = []

        related_norm_map = {}
        for idx, rel in enumerate(related_artists):
            rel_name = rel.get("name", "")
            rel_norm = normalize_string(rel_name)
            if rel_norm and rel_norm not in (norm_seed_artist, norm_real_seed):
                weight = max(25, 95 - idx * 3)
                related_norm_map[rel_norm] = (rel_name, weight)

        # Also search for top tracks of related artists to match against library
        for norm_art, loc_tracks in self.library_index.artists_map.items():
            if norm_art in related_norm_map:
                disp_art, weight = related_norm_map[norm_art]
                for loc_trk in loc_tracks:
                    if loc_trk["file_path"] not in used_file_paths:
                        candidate_vibe_tracks.append((loc_trk, weight, "vibe", f"Vibe: {disp_art}"))

        # Sort candidate vibe tracks by similarity weight descending
        candidate_vibe_tracks.sort(key=lambda x: x[1], reverse=True)

        for loc_trk, pop_score, role, role_desc in candidate_vibe_tracks:
            if loc_trk["file_path"] in used_file_paths:
                continue
            m_val, est_b = get_track_metric(loc_trk)
            if current_metric_total + m_val <= target_limit:
                current_metric_total += m_val
                current_bytes_total += est_b
                used_file_paths.add(loc_trk["file_path"])
                selected_tracks.append({
                    **loc_trk,
                    "effective_bytes": est_b,
                    "popularity": pop_score,
                    "role": role,
                    "role_desc": role_desc,
                    "will_transcode": transcode_lossless_to_mp3 and loc_trk["is_lossless"]
                })

        # Phase 3: Knapsack Gap-Filler (Puzzle-Piece fitting)
        remaining_capacity = target_limit - current_metric_total
        min_slot_size = 500 * 1024 if cap_type == "bytes" else 30
        
        if remaining_capacity > min_slot_size:
            if progress_callback:
                progress_callback("Maximizing disc utilization (fitting gap pieces)...")

            remaining_library_tracks = [
                t for t in self.library_index.tracks
                if t["file_path"] not in used_file_paths
            ]

            while remaining_capacity > min_slot_size and remaining_library_tracks:
                best_fit = None
                best_diff = float("inf")
                best_metric = 0
                best_est_b = 0

                for candidate in remaining_library_tracks:
                    m_val, est_b = get_track_metric(candidate)
                    if m_val <= remaining_capacity:
                        diff = remaining_capacity - m_val
                        if diff < best_diff:
                            best_diff = diff
                            best_fit = candidate
                            best_metric = m_val
                            best_est_b = est_b

                if best_fit:
                    remaining_library_tracks.remove(best_fit)
                    used_file_paths.add(best_fit["file_path"])
                    current_metric_total += best_metric
                    current_bytes_total += best_est_b
                    remaining_capacity -= best_metric
                    selected_tracks.append({
                        **best_fit,
                        "effective_bytes": best_est_b,
                        "popularity": 40,
                        "role": "filler",
                        "role_desc": f"Filler: {best_fit['artist']}",
                        "will_transcode": transcode_lossless_to_mp3 and best_fit["is_lossless"]
                    })
                else:
                    break

        # Assign sequential track numbers
        for idx, trk in enumerate(selected_tracks, start=1):
            trk["track_number"] = idx
            clean_art = sanitize_filename(trk["artist"], 40)
            clean_title = sanitize_filename(trk["title"], 50)
            target_ext = ".mp3" if trk["will_transcode"] else trk["ext"]
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
    Safely copies/transcodes selected mixtape tracks into a dedicated CD burn directory
    and generates an M3U playlist file for CD burning software.
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
        progress_callback: Optional[Callable[[int, int, str, str], None]] = None
    ) -> Dict:
        """
        Executes non-destructive file copying and optional transcoding.
        """
        self._cancel_event.clear()
        tracks = mixtape_plan.get("selected_tracks", [])
        if not tracks:
            raise ValueError("No tracks in mixtape plan to export.")

        if not folder_name:
            seed_name = mixtape_plan.get("seed_artist", {}).get("name") or "Mixtape"
            clean_seed = sanitize_filename(seed_name, 30)
            folder_name = f"CD_Burn_{clean_seed}_Mixtape"

        target_folder = os.path.join(destination_dir, folder_name)
        os.makedirs(target_folder, exist_ok=True)

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

            disp_title = f"{trk['artist']} - {trk['title']}"
            if progress_callback:
                progress_callback(idx, total_tracks, disp_title, "Processing...")

            if not os.path.exists(src_file):
                errors.append(f"Source file missing: {src_file}")
                continue

            try:
                if trk["will_transcode"]:
                    if progress_callback:
                        progress_callback(idx, total_tracks, disp_title, f"Transcoding to MP3 ({mp3_bitrate_kbps}k)...")
                    
                    cmd = [
                        self.ffmpeg_path,
                        "-y",
                        "-i", src_file,
                        "-vn",
                        "-c:a", "libmp3lame",
                        "-b:a", f"{mp3_bitrate_kbps}k",
                        "-map_metadata", "0",
                        "-id3v2_version", "3",
                        dst_file
                    ]
                    
                    res = subprocess.run(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        creationflags=CREATION_FLAGS_BACKGROUND
                    )
                    
                    if res.returncode == 0 and os.path.exists(dst_file):
                        transcoded_count += 1
                        try:
                            audio = ID3(dst_file)
                        except Exception:
                            audio = ID3()
                        audio["TIT2"] = TIT2(encoding=3, text=trk["title"])
                        audio["TPE1"] = TPE1(encoding=3, text=trk["artist"])
                        if trk.get("album"):
                            audio["TALB"] = TALB(encoding=3, text=trk["album"])
                        audio["TRCK"] = TRCK(encoding=3, text=str(idx))
                        audio.save(dst_file, v2_version=3)
                    else:
                        shutil.copy2(src_file, dst_file)
                        copied_count += 1
                else:
                    if progress_callback:
                        progress_callback(idx, total_tracks, disp_title, "Copying...")
                    shutil.copy2(src_file, dst_file)
                    copied_count += 1

                dur_int = int(trk.get("duration_s", 0))
                m3u_lines.append(f"#EXTINF:{dur_int},{trk['artist']} - {trk['title']}\n")
                m3u_lines.append(f"{dst_filename}\n")

            except Exception as e:
                errors.append(f"Error copying '{src_file}': {e}")

        playlist_path = os.path.join(target_folder, "000_Mixtape_Burn_Playlist.m3u")
        try:
            with open(playlist_path, "w", encoding="utf-8") as f:
                f.writelines(m3u_lines)
        except Exception as e:
            print(f"[CDMixtapeExporter] Failed writing playlist: {e}")

        was_cancelled = self._cancel_event.is_set()

        return {
            "target_folder": target_folder,
            "total_tracks": total_tracks,
            "copied_count": copied_count,
            "transcoded_count": transcoded_count,
            "errors": errors,
            "playlist_path": playlist_path,
            "cancelled": was_cancelled
        }
