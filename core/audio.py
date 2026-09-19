"""
Core Audio Utilities for Shallot Media Archive (SMArchive).
Handles ReplayGain / EBU R128 loudness analysis, audio segment extraction
for acoustic fingerprinting, and bitrate calculation for transcoding.
"""

import os
import re
import subprocess
from typing import Dict, Optional, Tuple

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
