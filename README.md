# Shallot Media Archive (SMArchive)

[![Version](https://img.shields.io/badge/version-1.1.0-blue.svg)](CHANGELOG.md)
[![Python](https://img.shields.io/badge/python-3.11+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Last Updated](https://img.shields.io/badge/last%20updated-2026--09--02-success.svg)](CHANGELOG.md)

**SMArchive** is a high-performance, dark-themed desktop media archiving suite designed for downloading video and audio from online sources, managing YouTube media libraries, and synchronizing Spotify playlists directly into **Plex / Plexamp** with automated ID3/FLAC metadata tagging, high-resolution album artwork embedding, and standard folder organization.

---

## 🌟 Key Features

### 🎵 Spotify to Plexamp Sync
- **Zero-Config Extraction**: Paste any public Spotify playlist, album, or track URL and fetch complete metadata without requiring API credentials.
- **True Original Studio Albums**: Automatically resolves original release dates, studio album titles, and original album track numbers for every song in a playlist.
- **Synced Karaoke Lyrics (`.lrc`) & Embedded Tags**: Automatically fetches synchronized `.lrc` sidecars (for Plexamp's animated lyrics view) and embeds `USLT`/`LYRICS` ID3 tags.
- **ReplayGain & Volume Normalization**: Analyzes audio loudness via `ffmpeg ebur128` and embeds track gain tags to prevent volume jumps across songs.
- **Concurrent Multi-Track Sync**: Downloads 2–3 songs simultaneously for 3× faster playlist synchronization.
- **Smart Duplicate Detection**: Pre-scans your music directory and badges existing songs with `✓ In Library`.
- **Plexamp Metadata Tagger (`mutagen`)**: Embeds Track Title, Artist, Album Artist, Album, Track Numbers, Release Year, and 640×640 front cover art.
- **Plex Standard Folder Structure**: Organizes files into `Music / Artist / Album / 01 - Track Title.ext` and writes `cover.jpg` for instant Plex scanner recognition.
- **Multiple Audio Formats**: Supports MP3 (320 kbps), FLAC (Lossless), and M4A (AAC 256 kbps).

### ▶️ YouTube to Plexamp Sync
- **Direct Audio Extraction**: Download directly from YouTube / YouTube Music playlist, album, or video URLs without requiring search matching.
- **Smart Title & Artist Cleaner**: Strips clutter like `(Official Music Video)`, `[HD 4K]`, `(Lyric Video)`, and splits artist/title into clean tags.
- **Automatic Metadata Enrichment**: Enriches tracks with iTunes Search API / LRCLIB data for studio album names, release dates, and 1400×1400 square cover art.
- **Center-Square Artwork Cropping**: Auto-crops 16:9 widescreen thumbnails to centered 1:1 square artwork for Plexamp compatibility.
- **Synced Lyrics & ReplayGain**: Full parity with Spotify to Plexamp, including `.lrc` sidecars and volume normalization.

### 📁 Local to Plexamp Organizer & Tagger
- **Recursive Multi-Folder Scanning**: Scans any local directory or nested subdirectories for all audio formats (`.mp3`, `.flac`, `.m4a`, `.wav`, `.aac`, `.ogg`, `.opus`, `.wma`).
- **Embedded Tag & Filename Fallback**: Reads existing audio metadata or uses smart regex to clean raw filenames into pristine Artist and Title tags.
- **Master Catalog Enrichment**: Looks up official studio albums, release years, track numbers, and 1400×1400 high-res artwork via iTunes and LRCLIB.
- **Lossless Copy or Transcode**: Direct lossless copy for native MP3/FLAC/M4A or automated high-quality transcode via `ffmpeg`.
- **Automatic Organization**: Sorts files into standard Plexamp structure (`Music / Artist / Album / 01 - Song.ext`), writes `cover.jpg`, and drops `.lrc` lyrics.

### 💿 CD Mixtape & 700MB Burn Prep Utility
- **Smart Seed Artist Top Hits**: Pick any artist from your local library (e.g., *Glass Animals*) and automatically select their top most streamed songs based on Spotify / Last.fm statistics.
- **Spotify Vibe & Similar Artist Discovery**: Discovers related vibe artists and ranks local library tracks by popularity and vibe score.
- **Knapsack 700MB Bin-Packing**: Maximizes 700MB Data CD capacity (or 80-minute Audio CD limits) to 98–99.9% full using puzzle-piece gap fitting.
- **Squeeze & Transcode Options**: Optional on-the-fly transcoding of FLAC/lossless files to high-quality MP3 (320k/256k/192k) to fit 150–200+ songs per CD.
- **Non-Destructive Export**: Never moves or deletes originals; copies to a dedicated folder with numbered tracks (`001 - Title.mp3`) and generates an `.m3u` playlist ready for burning in Windows Media Player, ImgBurn, or CDBurnerXP.

### 📥 YouTube & Web Media Downloader
- **Universal Downloader Engine**: Powered by `yt-dlp` and `ffmpeg` for downloading full playlists, video ranges, or standalone media.
- **Quality & Format Selection**: Supports resolutions up to 4K (2160p), 2K, 1080p, 720p, and custom audio bitrate extraction.
- **Multi-Session Archive**: Prevents redundant downloads by skipping already archived videos.
- **Speed & Queue Management**: Built-in bandwidth throttle control and real-time per-item queue progress tracking.

### 🔍 YouTube Search Tab
- Search YouTube directly from inside the app with rich thumbnail cards and one-click import into the download queue.

### 🎨 Modern UI & 3 Professional High-Readability Themes
- CustomTkinter dark-mode interface with clean typography and high contrast:
  - **Midnight** (Studio Slate & Electric Azure) — Crisp, modern dark theme with maximum readability.
  - **Carbon** (Minimalist Matte & Studio Emerald) — Neutral zinc & charcoal palette with vibrant emerald accents.
  - **Nordic** (Deep Navy & Indigo) — Refined Scandinavian enterprise palette with periwinkle/indigo highlights.

---

## 🚀 Quick Start

### 1. Requirements
- **Windows 10 / 11**
- **Python 3.10+** (Python 3.11 recommended)
- Bundled binaries (`ffmpeg.exe`, `ffprobe.exe`, `yt-dlp.exe`, `deno.exe`) are included in the repository.

### 2. Installation
```powershell
# Clone the repository
git clone https://github.com/strothman/Shallot-Media-Archive.git
cd Shallot-Media-Archive

# Create virtual environment & install dependencies
python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
```

### 3. Running the App
- **Normal Mode (Windowed)**: Double-click **`run.bat`** (or run `.\.venv\Scripts\pythonw.exe app.py`).
- **Debug Mode (Console Logs)**: Double-click **`run_debug.bat`** (or run `.\.venv\Scripts\python.exe app.py`).

---

## 📂 Plexamp Music Library Setup

To sync your Spotify playlists directly into your Plex Music library:
1. In SMArchive, navigate to the **`🎵 Spotify to Plexamp`** tab.
2. In **Music Library**, set your destination folder to your Plex music root folder (e.g. `D:\Music` or `C:\SMA-downloads\Music`).
3. Paste any Spotify playlist or album URL and click **`⚡ Fetch Tracks`**.
4. Select the tracks you want and click **`🚀 Download & Tag for Plexamp`**.
5. Once complete, Plex and Plexamp will automatically recognize the folder structure, display the embedded artwork, and organize albums without track splitting.

---

## ⚙️ Configuration & Settings

Settings are stored locally in `settings.json` and can be adjusted in the **`⚙️ Settings & Tools`** tab:
- **Audio Bitrate / Format**: Default bitrate (320kbps, 192kbps, 128kbps) and format (MP3, FLAC, M4A).
- **Cookie Source**: Direct integration with browser cookies (Chrome, Edge, Firefox, Brave) or `cookies.txt` for age-restricted content.
- **Spotify API Keys** *(Optional)*: Add your custom Spotify Developer Client ID and Secret for unlimited API rate limits.
- **Engine Updates**: One-click in-app update for `yt-dlp`.

---

## 📜 Changelog
All updates and release notes are documented in [CHANGELOG.md](CHANGELOG.md).
