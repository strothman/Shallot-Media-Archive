# Changelog

All notable changes to the **Strothman Media Archive (SMArchive)** project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Changed
- docs: add comprehensive README, CHANGELOG, and automated daily docs workflow (93ae246)

### Added
- add real-time track status badges, update yt-dlp downloader configuration, and include launcher scripts (6491579)
- implement per-track status badges, add automated batch execution scripts, and update configuration settings. (4354f53)
- implement Spotify metadata fetcher with support for playlist, album, and track parsing (da9c4de)
- initialize util-SMArchive standalone repository (5f6c813)

---

## [1.1.0] - 2026-08-26

### Added
- **Spotify to Plexamp Section**:
  - Zero-config Spotify playlist, album, and single track metadata fetcher (`spotify_sync.py`).
  - High-resolution 640×640 album cover artwork extraction.
  - Plexamp-compliant metadata tagging via `mutagen` for MP3 (`ID3v2.3/v2.4`), FLAC (Vorbis Picture blocks), and M4A (`covr` atoms).
  - Standard Plex directory organization: `Music / Artist / Album / 01 - Track Title.ext` with automatic `cover.jpg` creation.
  - Interactive tracklist checklist with "Select All", "Deselect All", and real-time status badges (`Downloading...`, `✓ Done`, `❌ Error`).
  - Optional custom Spotify Developer credentials integration in Settings.
- **Batch Launchers**:
  - `run.bat`: Clean windowed execution without background command prompt.
  - `run_debug.bat`: Live console debugging output launcher.
- **Automated Documentation**:
  - GitHub Actions automated daily documentation and changelog updater workflow (`.github/workflows/auto-docs.yml`).
  - Local documentation generation script (`scripts/update_docs.py`).

### Fixed
- **YouTube 403 Forbidden Bypass**: Updated `yt-dlp` to `2026.08.19` and configured `player_client=mweb,web` client formats to bypass YouTube anti-bot streaming restrictions.
- **Startup Window Focus**: Fixed initial active tab selection and ensured the application window brings itself forward immediately on startup.
- **Taskbar Progress Hook**: Silenced non-fatal Windows COM type library initialization warnings.

---

## [1.0.1] - 2026-08-26

### Added
- Multi-session download archiving (`--download-archive`) to prevent duplicate downloads.
- Custom season numbering and custom playlist item range filters.
- Desktop toast notifications for completed queue jobs.
- Persistent error logging to `downloader_errors.txt`.
- Enhanced YouTube search tab with concurrent thumbnail loading.

---

## [1.0.0] - 2026-06-22

### Added
- Initial standalone release of **Strothman Media Archive**.
- Dark-themed CustomTkinter graphical interface with 6 dynamic themes (*Obsidian*, *Vapor*, *Arctic*, *Ember*, *Twilight*, *Cipher*).
- High-performance video & audio downloading powered by `yt-dlp` and bundled `ffmpeg`.
- Support for video resolutions up to 4K and audio bitrate extraction.
- System tray minimization and background downloading support via `pystray`.
