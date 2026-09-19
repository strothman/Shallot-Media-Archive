"""
Core System & String Utilities for Shallot Media Archive (SMArchive).
Provides standardized cross-platform process flags, filename sanitization,
safe file manipulation with retry semantics, and fuzzy/censorship string matching.
"""

import os
import re
import shutil
import time
import subprocess
from typing import Set

# Windows Process Scheduling Flags (run subprocesses in background without popping windows or hogging CPU)
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
CREATION_FLAGS_BACKGROUND = (
    (subprocess.CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS)
    if os.name == 'nt' else 0
)

# Standard supported audio extensions
SUPPORTED_AUDIO_EXTENSIONS: Set[str] = {
    ".mp3", ".flac", ".m4a", ".aac", ".wav", ".ogg", ".opus", ".wma", ".aiff", ".alac"
}
LOSSLESS_EXTENSIONS: Set[str] = {".flac", ".wav", ".aiff", ".alac"}


def sanitize_filename(name: str, max_len: int = 80) -> str:
    """
    Removes invalid filesystem characters and limits length to prevent Windows MAX_PATH errors.
    """
    if not name:
        return "Unknown"
    # Strip invalid chars: < > : " / \ | ? * and control chars
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name).strip()
    clean = re.sub(r'\s+', ' ', clean)
    clean = clean.rstrip('. ')
    if not clean:
        clean = "Unknown"
    return clean[:max_len]


def safe_move_file(src: str, dst: str, max_retries: int = 4, delay: float = 0.35) -> bool:
    """
    Moves a file safely on Windows, retrying on transient locks (e.g. Defender, Indexer).
    """
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    for attempt in range(max_retries):
        try:
            if os.path.exists(dst) and os.path.abspath(src) != os.path.abspath(dst):
                try:
                    os.remove(dst)
                except Exception:
                    pass
            shutil.move(src, dst)
            return True
        except (PermissionError, OSError) as e:
            if attempt < max_retries - 1:
                time.sleep(delay * (attempt + 1))
            else:
                raise e
    return False


def safe_save_tags(audio_obj, *args, **kwargs) -> bool:
    """
    Saves Mutagen tags with automatic retry for Windows file locks.
    """
    for attempt in range(4):
        try:
            audio_obj.save(*args, **kwargs)
            return True
        except (PermissionError, OSError) as e:
            if attempt < 3:
                time.sleep(0.35 * (attempt + 1))
            else:
                raise e
    return False


def normalize_string(text: str) -> str:
    """
    Normalizes string for fuzzy title/artist matching.
    Removes bracketed/parenthetical clutter, featuring tags, and punctuation.
    """
    if not text:
        return ""
    text = text.lower()
    # Remove bracketed/parenthetical clutter: (feat. ...), (remastered ...), [official video]
    text = re.sub(r'[\(\[\{].*?[\)\]\}]', '', text)
    # Remove common featuring patterns
    text = re.sub(r'\b(feat|ft|featuring|with|prod|produced by)\b.*', '', text)
    # Remove punctuation
    text = re.sub(r'[^\w\s]', '', text)
    # Collapse multiple spaces
    text = re.sub(r'\s+', ' ', text).strip()
    return text


import unicodedata

def normalize_text(s: str) -> str:
    """
    Deep string normalization for acoustic fact-checking and comparison.
    Standardizes artist separators, strips diacritics, tags, and track numbers.
    """
    if not s:
        return ""
    # Strip accents / diacritics (e.g. Gabor Szabo)
    s = unicodedata.normalize('NFKD', str(s)).encode('ASCII', 'ignore').decode('utf-8')
    s = s.lower().strip()
    # Normalize artist separators / joiners (e.g. '/' or '+' or '&' -> ' and ')
    s = re.sub(r'[\/\\+&]', ' and ', s)
    # Remove featuring blocks
    s = re.sub(r'[\(\[\{]\s*(feat\.?|ft\.?|featuring)[^\)\]\}]*[\)\]\}]', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\s+(feat\.?|ft\.?|featuring)\s+.*$', '', s, flags=re.IGNORECASE)
    # Remove common tags
    s = re.sub(
        r'[\(\[\{]\s*(remaster(ed)?|live|official|audio|video|explicit|clean|deluxe|bonus|version|mix|edit|mono|stereo)[^\)\]\}]*[\)\]\}]',
        '',
        s,
        flags=re.IGNORECASE
    )
    # Remove track numbers at start
    s = re.sub(r'^\d+[\s\.\-_]+', '', s)
    # Replace punctuation and symbols with single space
    s = re.sub(r'[^a-z0-9\s]', ' ', s)
    # Collapse whitespace
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def is_censored_match(s1: str, s2: str) -> bool:
    """
    Checks if s2 is an asterisk/bullet censored version of s1 (e.g. Dickhead vs D******d).
    """
    if not s1 or not s2:
        return False
    w1 = s1.lower().strip()
    w2 = s2.lower().strip()
    if w1 == w2:
        return True
    if '*' in w2 or '•' in w2:
        p = re.escape(w2).replace(r'\*', '.').replace(r'\•', '.')
        try:
            if re.fullmatch(p, w1):
                return True
        except Exception:
            pass
    if '*' in w1 or '•' in w1:
        p = re.escape(w1).replace(r'\*', '.').replace(r'\•', '.')
        try:
            if re.fullmatch(p, w2):
                return True
        except Exception:
            pass
    return False


def string_similarity(s1: str, s2: str) -> float:
    """
    Computes token set similarity ratio between two normalized strings with censorship handling.
    """
    if is_censored_match(s1, s2):
        return 1.0

    n1 = normalize_text(s1)
    n2 = normalize_text(s2)
    if not n1 and not n2:
        return 1.0
    if not n1 or not n2:
        return 0.0
    if n1 == n2 or is_censored_match(n1, n2):
        return 1.0
    if n1 in n2 or n2 in n1:
        return 0.90

    tokens1 = set(n1.split())
    tokens2 = set(n2.split())
    if not tokens1 or not tokens2:
        return 0.0

    intersection = tokens1.intersection(tokens2)
    union = tokens1.union(tokens2)
    return len(intersection) / len(union)


CLEAN_NOISE_REGEX = re.compile(
    r'[\(\[\{]\s*(?:official\s*(?:music\s*)?video|official\s*audio|official\s*hd|lyric\s*video|music\s*video|audio\s*only|full\s*audio|visualizer|hd|hq|1080p|4k|remaster(?:ed)?(?:\s*\d{4})?|video|lyrics?|audio|official|original\s*mix)\s*[\)\]\}]',
    re.IGNORECASE
)


def clean_display_title(raw_title: str) -> str:
    """
    Cleans YouTube clutter, bracketed bloat, and track numbering prefixes from song titles
    so car stereos and media players display clean, legible song titles immediately.
    """
    if not raw_title:
        return "Unknown Track"
    t = raw_title.strip()
    # Remove leading track number patterns like "01. ", "01 - ", "1 "
    t = re.sub(r'^\d+\s*[-_.]\s*', '', t)
    # Remove noise patterns: (Official Audio), [1080p], etc.
    t = CLEAN_NOISE_REGEX.sub('', t)
    # Remove empty leftover brackets
    t = re.sub(r'[\(\[\{]\s*[\)\]\}]', '', t)
    t = re.sub(r'\s+', ' ', t).strip(' -_.,;:')
    return t or raw_title.strip()


def clean_display_artist(raw_artist: str) -> str:
    """Cleans artist names for clean automotive/media player display."""
    if not raw_artist:
        return "Unknown Artist"
    a = raw_artist.strip()
    a = CLEAN_NOISE_REGEX.sub('', a)
    a = re.sub(r'[\(\[\{]\s*[\)\]\}]', '', a)
    a = re.sub(r'\s+', ' ', a).strip(' -_.,;:')
    return a or raw_artist.strip()
