"""
Shallot Media Archive (SMArchive) Core Framework Package.
Exposes standardized media tagging, audio analysis, lyrics extraction,
and system/string utilities across all application modules.
"""

from core.utils import (
    BELOW_NORMAL_PRIORITY_CLASS,
    CREATION_FLAGS_BACKGROUND,
    SUPPORTED_AUDIO_EXTENSIONS,
    LOSSLESS_EXTENSIONS,
    sanitize_filename,
    safe_move_file,
    safe_save_tags,
    normalize_string,
    normalize_text,
    is_censored_match,
    string_similarity,
    clean_display_title,
    clean_display_artist,
)
from core.audio import (
    ReplayGainCalculator,
    slice_audio_segment,
    get_track_bitrate_kbps,
    should_transcode_track,
)
from core.lyrics import (
    LyricsFetcher,
)
from core.tagger import (
    PlexampTagger,
    write_car_optimized_tags,
)
from core.cache import (
    VerifierDatabase,
)

__all__ = [
    "BELOW_NORMAL_PRIORITY_CLASS",
    "CREATION_FLAGS_BACKGROUND",
    "SUPPORTED_AUDIO_EXTENSIONS",
    "LOSSLESS_EXTENSIONS",
    "sanitize_filename",
    "safe_move_file",
    "safe_save_tags",
    "normalize_string",
    "normalize_text",
    "is_censored_match",
    "string_similarity",
    "clean_display_title",
    "clean_display_artist",
    "ReplayGainCalculator",
    "slice_audio_segment",
    "get_track_bitrate_kbps",
    "should_transcode_track",
    "LyricsFetcher",
    "PlexampTagger",
    "write_car_optimized_tags",
    "VerifierDatabase",
]
