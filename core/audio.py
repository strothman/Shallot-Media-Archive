"""
Core Audio Utilities for Shallot Media Archive (SMArchive).
Handles ReplayGain / EBU R128 loudness analysis, audio segment extraction
for acoustic fingerprinting, and bitrate calculation for transcoding.
"""

import os
import re
import shutil
import subprocess
import threading
from typing import Callable, Dict, Optional, Tuple

from core.utils import CREATION_FLAGS_BACKGROUND


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


def slice_audio_segment(
    file_path: str,
    offset_seconds: float = 30.0,
    duration_seconds: float = 12.0,
    ffmpeg_path: Optional[str] = None
) -> Optional[bytes]:
    """
    Extracts a short segment from file_path as MP3 bytes using ffmpeg for acoustic scanning.
    """
    norm_path = os.path.normpath(file_path)
    if not os.path.exists(norm_path):
        return None
    try:
        bin_path = ffmpeg_path
        if not bin_path or not os.path.exists(bin_path):
            # Fall back to root directory or PATH
            candidate = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ffmpeg.exe")
            bin_path = candidate if os.path.exists(candidate) else "ffmpeg"

        cmd = [
            bin_path,
            "-threads", "2",
            "-nostats",
            "-loglevel", "error",
            "-ss", f"{max(0.0, offset_seconds):.2f}",
            "-t", f"{duration_seconds:.2f}",
            "-i", norm_path,
            "-f", "mp3",
            "-ac", "2",
            "-ar", "44100",
            "pipe:1"
        ]
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        proc = subprocess.run(cmd, capture_output=True, creationflags=flags, timeout=12)
        if proc.returncode == 0 and len(proc.stdout) > 1000:
            return proc.stdout
    except Exception:
        pass
    return None


def get_track_bitrate_kbps(trk: Dict) -> int:
    """Estimates average bitrate in kbps of a track dictionary."""
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


class AudioPreviewPlayer:
    """
    Manages non-blocking audio snippet playback for auditioning tracks.
    Supports seek offsets and durations, using ffplay (zero transcoding overhead)
    with a graceful winsound fallback on Windows.
    """
    _current_process: Optional[subprocess.Popen] = None
    _current_file: Optional[str] = None
    _lock = threading.RLock()
    _on_stop_callback: Optional[Callable[[], None]] = None
    _timer: Optional[threading.Timer] = None

    @classmethod
    def is_playing(cls) -> bool:
        with cls._lock:
            if cls._current_process is not None:
                if cls._current_process.poll() is None:
                    return True
                cls._current_process = None
                cls._current_file = None
            return False

    @classmethod
    def get_playing_file(cls) -> Optional[str]:
        with cls._lock:
            return cls._current_file if cls.is_playing() else None

    @classmethod
    def stop(cls):
        with cls._lock:
            if cls._timer:
                cls._timer.cancel()
                cls._timer = None
            if cls._current_process is not None:
                try:
                    cls._current_process.terminate()
                    cls._current_process.wait(timeout=0.5)
                except Exception:
                    try:
                        cls._current_process.kill()
                    except Exception:
                        pass
                cls._current_process = None
            cls._current_file = None

            if os.name == 'nt':
                try:
                    import winsound
                    winsound.PlaySound(None, winsound.SND_PURGE)
                except Exception:
                    pass

            if cls._on_stop_callback:
                cb = cls._on_stop_callback
                cls._on_stop_callback = None
                try:
                    cb()
                except Exception:
                    pass

    @classmethod
    def play(
        cls,
        file_path: str,
        offset_seconds: float = 15.0,
        duration_seconds: float = 10.0,
        on_stop: Optional[Callable[[], None]] = None
    ) -> bool:
        """
        Starts playing a short snippet of the audio file in the background.
        If already playing the same file, stops it (toggle behavior).
        If playing a different file, stops the previous and starts the new one.
        """
        norm_path = os.path.normpath(file_path)
        if not os.path.exists(norm_path):
            return False

        if cls.is_playing() and cls.get_playing_file() == norm_path:
            cls.stop()
            return False

        cls.stop()

        with cls._lock:
            cls._on_stop_callback = on_stop
            cls._current_file = norm_path

            # 1. Try ffplay first (direct seek, supports all formats, no transcoding)
            ffplay_bin = shutil.which("ffplay")
            if not ffplay_bin:
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                candidate = os.path.join(base_dir, "ffplay.exe")
                if os.path.exists(candidate):
                    ffplay_bin = candidate

            if ffplay_bin:
                try:
                    cmd = [
                        ffplay_bin,
                        "-nodisp",
                        "-autoexit",
                        "-ss", f"{max(0.0, offset_seconds):.2f}",
                        "-t", f"{duration_seconds:.2f}",
                        norm_path
                    ]
                    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                    cls._current_process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=flags
                    )

                    def _wait_and_notify():
                        if cls._current_process:
                            try:
                                cls._current_process.wait(timeout=duration_seconds + 2.0)
                            except Exception:
                                pass
                        cls.stop()

                    threading.Thread(target=_wait_and_notify, daemon=True).start()
                    return True
                except Exception:
                    pass

            # 2. Fallback: Extract WAV slice using ffmpeg and play via winsound (Windows)
            if os.name == 'nt':
                try:
                    import winsound
                    ffmpeg_bin = shutil.which("ffmpeg") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ffmpeg.exe")
                    if os.path.exists(ffmpeg_bin) or shutil.which("ffmpeg"):
                        cmd = [
                            ffmpeg_bin if os.path.exists(ffmpeg_bin) else "ffmpeg",
                            "-threads", "2",
                            "-nostats",
                            "-loglevel", "error",
                            "-ss", f"{max(0.0, offset_seconds):.2f}",
                            "-t", f"{duration_seconds:.2f}",
                            "-i", norm_path,
                            "-f", "wav",
                            "-ac", "2",
                            "-ar", "44100",
                            "pipe:1"
                        ]
                        flags = subprocess.CREATE_NO_WINDOW
                        proc = subprocess.run(cmd, capture_output=True, creationflags=flags, timeout=8)
                        if proc.returncode == 0 and len(proc.stdout) > 1000:
                            winsound.PlaySound(proc.stdout, winsound.SND_MEMORY | winsound.SND_ASYNC)

                            cls._timer = threading.Timer(duration_seconds, cls.stop)
                            cls._timer.daemon = True
                            cls._timer.start()
                            return True
                except Exception:
                    pass

        return False
