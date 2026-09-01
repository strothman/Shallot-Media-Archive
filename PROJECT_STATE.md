# Project State: Shallot Media Archive (SMArchive)

**Last Updated:** 2026-09-01  
**Current Version:** `1.1.0`  
**Repository:** `strothman/util-SMArchive`  
**Primary Language / Framework:** Python 3.11+ / CustomTkinter (Dark Mode GUI)

---

## 1. Executive Summary

**Shallot Media Archive (SMArchive)** is a standalone desktop media downloading and library synchronization suite for Windows. It provides zero-config downloading and organization for YouTube, YouTube Music, and Spotify playlists into standardized Plex/Plexamp music libraries with automated ID3/FLAC metadata tagging, high-resolution album art embedding, ReplayGain loudness normalization, and synced `.lrc` lyrics. It also features an acoustic fingerprinting and metadata fact-checking engine (via Shazam API).

---

## 2. Architecture & Core Components

```
util-SMArchive/
├── app.py                      # Main GUI application (CustomTkinter, threading, tabs, UI themes)
├── spotify_sync.py             # Spotify metadata fetcher (Embed scrape, OAuth 1-click server, Web API) & YTM downloader
├── youtube_sync.py             # Direct YouTube playlist/track downloader & metadata enricher (iTunes/LRCLIB)
├── local_sync.py               # Local directory recursive scanner, tagger, and Plex library organizer
├── audio_verifier.py           # Audio fingerprinting & Shazam verification fact-checker with fuzzy matching
├── scripts/
│   └── update_docs.py          # Auto-syncs CHANGELOG.md & README.md badges from git commits
├── installer/
│   └── ShallotMediaArchive.iss # Inno Setup 6 compiler script for Windows installer generation
├── .github/workflows/
│   ├── auto-docs.yml           # Daily/on-push GitHub Action for changelog & documentation synchronization
│   └── release.yml             # Tag-triggered PyInstaller Windows executable build & GitHub Release packager
├── SMArchive.spec              # PyInstaller specification for bundling dependencies & assets
├── file_version_info.txt       # Windows executable version resource info
├── requirements.txt            # Python dependencies (customtkinter, mutagen, yt-dlp, pillow, etc.)
├── .gitignore                  # Git ignore rules for virtual environments, secrets, caches, and binaries
└── README.md / CHANGELOG.md    # Documentation and changelog
```

### Module Breakdown

1. **`app.py` (Main GUI Hub)**:
   - Built on `customtkinter` with multi-tab navigation: *YouTube Downloader*, *YouTube Search*, *Spotify to Plexamp*, *YouTube to Plexamp*, *Local Organizer*, *Audio Verifier*, and *Settings & Tools*.
   - Multi-threaded background tasks for UI responsiveness with real-time log streaming and per-track badge updates.
   - Built-in UI themes: **Cipher**, **Antigravity**, **Midnight**, **Carbon**, and **Nordic**.
   - Persistent configuration via local `settings.json`.

2. **`spotify_sync.py` (Spotify Engine)**:
   - Multi-mode extraction: public embed scraping (zero-config, no API keys needed), 1-click browser OAuth 2.0 PKCE flow, and official Spotify Web API client credentials.
   - Automated search & download matching against YouTube Music / YouTube.
   - Mutagen tagging: title, artist, album artist, album, track number, year, genre, and embedded cover art.
   - Synced lyrics retrieval (`.lrc` sidecars and embedded `USLT`/`LYRICS` tags via LRCLIB).
   - Volume normalization using `ffmpeg` `ebur128` ReplayGain tags.

3. **`youtube_sync.py` (YouTube to Plexamp Engine)**:
   - Direct audio extraction from YouTube/YouTube Music playlists and URLs.
   - Regex cleaning for video titles (removes `[Official Music Video]`, `(HD 4K)`, etc.).
   - Metadata enrichment via iTunes Search API and LRCLIB.
   - Dynamic artwork cropping from 16:9 thumbnails to 1:1 square covers.

4. **`local_sync.py` (Local Library Organizer)**:
   - Recursive scanning of local folders for `.mp3`, `.flac`, `.m4a`, `.wav`, `.ogg`, `.opus`.
   - Metadata extraction from existing tags with filename regex fallback.
   - Automatic restructuring into standard Plex format: `Music / Artist / Album / 01 - Title.ext`.

5. **`audio_verifier.py` (Audio Fact-Checker & Verifier)**:
   - Acoustical fingerprinting and Shazam API matching.
   - Censorship-aware string normalization (e.g. `F**k` vs `Fuck`) and parenthetical subtitle handling.
   - Discrepancy detection between file tags and recognized master records.

---

## 3. Git & Repository Status

- **Branch:** `main`
- **Working Tree:** Clean (all working changes committed)
- **Upstream Sync:** Behind `origin/main` by doc-sync commits (`docs: auto-update changelog & readme [skip ci]`). Fast-forward mergeable via `git pull`.
- **Packaging Pipelines:**
  - Automated Release workflow configured in `.github/workflows/release.yml` triggered on version tags (`v*`).
  - Daily auto-documentation updates via `.github/workflows/auto-docs.yml`.

---

## 4. Security & Privacy Audit Findings

A comprehensive scan across tracked files, past commit histories, `.gitignore` rules, and source code revealed the following security & privacy items:

### ⚠️ Findings & Vulnerabilities

| Priority | Category | Location | Status & Description |
| :--- | :--- | :--- | :--- |
| **High** | **Exposed Cookies in Git History** | Commit `5f6c8134` (`cookies.txt`) | `cookies.txt` containing YouTube session cookies (`LOGIN_INFO`, `SID`, `__Secure-1PSID`, `SAPISID`) was committed in the initial commit and later deleted in commit `4354f533`. Although currently git-ignored, these cookies remain in past git commit history. **Action:** If repository is public or will be made public, purge commit history using `git-filter-repo` or BFG, and rotate YouTube/Google account session credentials. |
| **Medium** | **Private UNC Network Paths in Tracked Files** | `verifier_cache.json` & `fact_check_report.json` | **Resolved:** Untracked from Git (`git rm --cached`) and added to `.gitignore`. Local files are preserved on disk so the app functionality remains 100% intact without exposing local paths. |
| **Low** | **Hardcoded Network Path Placeholder** | `app.py` (Line 1663) | **Resolved:** Replaced network path placeholder with generic directory template (`e.g. D:\Music or \\server\Music\Library...`). |
| **Safe** | **API Keys & Credentials** | `app.py`, `spotify_sync.py`, `settings.json` | No hardcoded Spotify secrets or API keys in source files. Credentials are read at runtime from local `settings.json` (which is correctly listed in `.gitignore`). |
| **Safe** | **Commit Author Metadata** | Git Log History | Commits are authored with `strothman <strothman@users.noreply.github.com>`, protecting personal email addresses. |

---

## 5. Next Steps & Recommended Actions

1. **History Purge (If Public):**
   - If the repository is shared publicly, run `git-filter-repo --invert-paths --path cookies.txt` (or BFG Repo-Cleaner) to strip the historical cookie file from Git objects, and invalidate old browser sessions.
2. **Pull Remote Doc Commits:**
   - Synchronize with GitHub Actions auto-documentation commits (`git pull`).
