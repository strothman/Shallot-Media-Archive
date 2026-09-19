"""
Shallot Media Archive (SMArchive) UI Framework Package.
Provides modular tab mixins, reusable UI components, and theme styling.
"""

from ui.components import TrackTable
from ui.tabs import (
    DownloadTabMixin,
    SearchTabMixin,
    SpotifyTabMixin,
    YtPlexampTabMixin,
    LocalPlexampTabMixin,
    VerifierTabMixin,
    CDMixtapeTabMixin,
    SettingsTabMixin,
    LogsTabMixin,
)

__all__ = [
    "TrackTable",
    "DownloadTabMixin",
    "SearchTabMixin",
    "SpotifyTabMixin",
    "YtPlexampTabMixin",
    "LocalPlexampTabMixin",
    "VerifierTabMixin",
    "CDMixtapeTabMixin",
    "SettingsTabMixin",
    "LogsTabMixin",
]
