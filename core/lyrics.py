"""
Core Lyrics Retrieval Engine for Shallot Media Archive (SMArchive).
Fetches synchronized (.lrc) and unsynchronized plain-text lyrics from the LRCLIB API.
"""

import json
import re
import ssl
import urllib.parse
import urllib.request
from typing import Dict


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

        headers = {"User-Agent": "ShallotMediaArchive/1.1 (https://github.com/strothman/Shallot-Media-Archive)"}

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
