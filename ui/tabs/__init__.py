"""
UI Tabs package for Shallot Media Archive.
Exports all modular page mixins that compose DownloaderApp.
"""

from ui.tabs.download_tab import DownloadTabMixin
from ui.tabs.search_tab import SearchTabMixin
from ui.tabs.spotify_tab import SpotifyTabMixin
from ui.tabs.yt_plexamp_tab import YtPlexampTabMixin
from ui.tabs.local_plexamp_tab import LocalPlexampTabMixin
from ui.tabs.verifier_tab import VerifierTabMixin
from ui.tabs.cd_mixtape_tab import CDMixtapeTabMixin
from ui.tabs.settings_tab import SettingsTabMixin
from ui.tabs.logs_tab import LogsTabMixin

__all__ = [
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
