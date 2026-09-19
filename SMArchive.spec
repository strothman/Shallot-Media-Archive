# -*- mode: python ; coding: utf-8 -*-

import sys
sys.setrecursionlimit(5000)

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('yt-dlp.exe', '.'), ('cookies.txt', '.'), ('icon.ico', '.'), ('deno.exe', '.'), ('ffmpeg.exe', '.'), ('ffprobe.exe', '.')],
    hiddenimports=[
        'core', 'core.utils', 'core.audio', 'core.lyrics', 'core.tagger', 'core.cache',
        'ui', 'ui.components', 'ui.components.track_table', 'ui.tabs',
        'ui.tabs.download_tab', 'ui.tabs.search_tab', 'ui.tabs.spotify_tab',
        'ui.tabs.yt_plexamp_tab', 'ui.tabs.local_plexamp_tab', 'ui.tabs.verifier_tab',
        'ui.tabs.cd_mixtape_tab', 'ui.tabs.settings_tab', 'ui.tabs.logs_tab',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SMArchive',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
    version='file_version_info.txt',
)
