# Changelog

All notable changes to the **Shallot Media Archive (SMArchive)** project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Fixed
- enforce strict duplicate immunity in CD mixtape planner (514c587)

### Fixed
- import typing definitions in app.py for clean silent startup (5d3de51)

### Added
- add 700MB CD Mixtape and burn prep utility (f0890af)

### Changed
- chore: rename repository references to Shallot-Media-Archive (e6c7a0f)

### Changed
- chore(security): sanitize UI placeholder, untrack verifier cache, and add PROJECT_STATE.md (d0295fe)

### Added
- add manual verification and censorship-aware string matching to audio verifier (38d809e)

### Changed
- chore: add shallot icon and update verifier cache with new track metadata (b1bd3c4)

### Added
- implement persistent audio verification cache to optimize status lookups (5bd5a13)

### Added
- implement acoustic fingerprinting and metadata verification module for audio library integrity (a9babbb)

### Changed
- refactor: remove obsolete backup files and temporary assets from project directory (cbc0b9f)

### Added
- implement YouTube sync module with automatic title cleaning and metadata enrichment (9900a08)

### Changed
- Merge branch 'main' of https://github.com/strothman/util-SMArchive and resolve CHANGELOG.md (79b8ad5)
- Merge branch 'main' of https://github.com/strothman/util-SMArchive (79dcbd9)

### Added
- **Local to Plexamp Organizer & Tagger**:
  - Full-featured section for scanning, cleaning, tagging, and organizing local audio files (`.mp3`, `.flac`, `.m4a`, `.wav`, `.aac`, `.ogg`, `.opus`, `.wma`) directly into Plexamp.
  - Recursive directory traversal with embedded tag extraction and smart filename parsing.
  - Automatic master catalog enrichment via iTunes Search API and LRCLIB for studio albums, release dates, track numbers, and 1400×1400 artwork.
  - Lossless direct copy or high-quality conversion via `ffmpeg`, with ID3v2.4/FLAC/MP4 tags, `.lrc` lyrics, ReplayGain normalization, and Plex standard folder hierarchy.

- **YouTube to Plexamp Engine & UI Section**:
  - Full-featured section for downloading YouTube / YouTube Music playlists, albums, and videos directly into Plexamp.
  - Smart title and artist cleaner stripping video clutter (`Official Video`, `[4K]`, `Lyric Video`).
  - Automatic metadata enrichment using iTunes Search API & LRCLIB for studio albums, release dates, and 1400×1400 square artwork.
  - Center-square 1:1 auto-cropping for 16:9 YouTube thumbnails.
  - Mutagen tagging (`ID3v2.4`, `FLAC`, `MP4`), synchronized `.lrc` lyrics sidecars, ReplayGain normalization, and Plex standard folder hierarchy.

- **Performance & Reliability Optimizations**:
  - Added Windows file-lock retry mechanism (`safe_move_file` and `safe_save_tags`) with exponential backoff to eliminate `[WinError 32]` collisions with Windows Defender and Plex Indexer.
  - Implemented in-memory iTunes metadata caching to eliminate redundant HTTP requests across album/playlist sync operations.
  - Added segment length capping (max 80 chars per segment) in `sanitize_filename` to prevent Windows `MAX_PATH` overflow.
  - Added native multi-disc album organization (`Disc 01 / Disc 02` subfolders and `1-01` numbering) across Spotify, YouTube, and Local Plexamp engines.
  - Added safe-move validation in Local to Plexamp ensuring source files are only removed if destination is verified $> 100\text{ KB}$.

- **Streamlined 3 Professional Visual Themes**:
  - Reduced theme options to **Midnight** (Studio Slate & Electric Azure), **Carbon** (Minimalist Matte & Emerald), and **Nordic** (Deep Navy & Indigo) for maximum readability and high contrast.

- add licensing, implement process throttling, improve tracklist rendering performance, and add clear completed functionality (8b5de11)

### Fixed
- support Spotify 2026 /items endpoint for unlimited playlist track pagination (bfafde7)

### Fixed
- position SpotifyFetcher fetch_entity method properly (d6d2a73)

### Added
- add 1-click Spotify OAuth connect to unlock full 700+ song playlists (ebfaec0)

### Added
- remember previous folder selection on app close or exit (5d114ef)

### Changed
- chore: stop tracking local settings.json (0520b18)

### Fixed
- eliminate duplicate tray icon initialization (002af06)

### Added
- auto-save target directories to settings.json on typing, paste, browse, or focus loss (fce31d8)

### Changed
- chore: add settings.json to gitignore (46b649a)

### Fixed
- launch run.bat silently with pythonw and auto-close console prompt (c0e6a47)

### Added
- apply Plexamp Artist/Album/XX-Title naming hierarchy to Universal Downloader audio mode (1e4fc10)

### Added
- add minimize to system tray on window close with right-click exit menu (8aa9f64)

### Added
- add synced lyrics, ReplayGain, concurrent downloading, duplicate detection, Inno installer, and release CI (3c20202)
- embed original album track numbers and display original track index in UI (818dd1b)
- resolve true original studio albums and high-res artwork for all tracks (c1c90f9)
- add real-time track status badges, update yt-dlp downloader configuration, and include launcher scripts (6491579)
- implement per-track status badges, add automated batch execution scripts, and update configuration settings. (4354f53)
- implement Spotify metadata fetcher with support for playlist, album, and track parsing (da9c4de)
- initialize util-SMArchive standalone repository (5f6c813)

### Fixed
- make batch and vbs launchers robust with absolute pathing (6b551a1)

### Changed
- chore: rename application to Shallot Media Archive (b3c45bc)
- docs: add comprehensive README, CHANGELOG, and automated daily docs workflow (93ae246)

---

## [1.2.0] - 2026-08-26

### Changed
- refactor: resolve all linter warnings and fix exception closure variable (e1b9fd7)

### Added
- **Synced Karaoke Lyrics (`.lrc`) Engine**: Automatically queries LRCLIB for synchronized timestamps and drops sidecar `.lrc` files for Plexamp animated lyrics display, while embedding `USLT` ID3 tags.
- **ReplayGain & Volume Normalization Tagging**: Implemented `ffmpeg ebur128` audio loudness analyzer to write `REPLAYGAIN_TRACK_GAIN`, `REPLAYGAIN_TRACK_PEAK`, and `RVA2` volume metadata.
- **Concurrent Multi-Worker Downloads**: Downloads 2–3 songs simultaneously for 3× faster playlist syncing.
- **Smart Library Duplicate Detection**: Pre-checks destination directory and tags already downloaded songs with `✓ In Library`.
- **Post-Download "Open Folder" Action**: 1-click button to open the music directory directly in Windows Explorer.
- **Inno Setup Windows Installer**: Added `installer/ShallotMediaArchive.iss` for professional Windows desktop installer compilation.
- **Automated GitHub Release CI/CD**: Added `.github/workflows/release.yml` for automated binary builds on git tag push.
- **True Original Studio Albums & Track Indexing**: Automatically resolves actual studio album releases, release years, and original album track numbers for playlist songs.

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
