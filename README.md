# Shallot Media Archive (SMArchive)

[![Version](https://img.shields.io/badge/version-1.1.0-blue.svg)](CHANGELOG.md)
[![Python](https://img.shields.io/badge/python-3.11+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Last Updated](https://img.shields.io/badge/last%20updated-2026--08--26-success.svg)](CHANGELOG.md)

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

### 📥 YouTube & Web Media Downloader
- **Universal Downloader Engine**: Powered by `yt-dlp` and `ffmpeg` for downloading full playlists, video ranges, or standalone media.
- **Quality & Format Selection**: Supports resolutions up to 4K (2160p), 2K, 1080p, 720p, and custom audio bitrate extraction.
- **Multi-Session Archive**: Prevents redundant downloads by skipping already archived videos.
- **Speed & Queue Management**: Built-in bandwidth throttle control and real-time per-item queue progress tracking.

### 🔍 YouTube Search Tab
- Search YouTube directly from inside the app with rich thumbnail cards and one-click import into the download queue.

### 🎨 Modern UI & 6 Vibrant Themes
- CustomTkinter dark-mode interface with dynamic palette switching:
  - **Obsidian** (Violet & Slate)
  - **Vapor** (Neon Pink & Purple)
  - **Arctic** (Cyan & Deep Navy)
  - **Ember** (Rose & Charcoal)
  - **Twilight** (Lavender & Indigo)
  - **Cipher** (Emerald & Forest)

---

## 🚀 Quick Start

### 1. Requirements
- **Windows 10 / 11**
- **Python 3.10+** (Python 3.11 recommended)
- Bundled binaries (`ffmpeg.exe`, `ffprobe.exe`, `yt-dlp.exe`, `deno.exe`) are included in the repository.

### 2. Installation
```powershell
# Clone the repository
git clone https://github.com/strothman/util-SMArchive.git
cd util-SMArchive

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
