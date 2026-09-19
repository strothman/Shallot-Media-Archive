"""
Shared TrackTable Component for Shallot Media Archive.
Standardizes scrollable track lists, selection tracking, and status badge updates
across Spotify to Plexamp, YouTube to Plexamp, and Local to Plexamp.
Supports both instance-based container encapsulation and static list operations.
"""

from typing import Any, Callable, Dict, List, Optional
import customtkinter as ctk


class TrackTable:
    """
    Component managing track list rows, selection toggles, and status badge updates.
    Can be used as a standalone helper or as an encapsulated table instance.
    """

    def __init__(self, container: Optional[Any] = None, track_items: Optional[List[Dict[str, Any]]] = None):
        self.container = container
        self.track_items = track_items if track_items is not None else []

    def count_selected(self) -> int:
        """Returns number of checked items in this table's track_items."""
        return sum(1 for item in self.track_items if item.get("var") and item["var"].get() == 1)

    def update_status_badge(self, index: int, text: str, color: Optional[str] = None) -> None:
        """Updates text and color of the status badge at the given index."""
        if 0 <= index < len(self.track_items):
            badge = self.track_items[index].get("status_badge")
            if badge:
                if color:
                    badge.configure(text=text, text_color=color)
                else:
                    badge.configure(text=text)

    def clear_completed(self) -> List[Dict[str, Any]]:
        """Removes rows marked done (indicated by ✓ checkmark), destroys their widgets, returns remaining."""
        remaining = []
        for item in self.track_items:
            badge = item.get("status_badge")
            text = badge.cget("text") if badge else ""
            if "✓" in text or "Complete" in text:
                if "row_frame" in item and hasattr(item["row_frame"], "destroy"):
                    item["row_frame"].destroy()
            else:
                remaining.append(item)
        self.track_items = remaining
        return remaining

    # --- Static helper methods for direct list manipulation ---

    @staticmethod
    def select_all_items(track_items: List[Dict[str, Any]], select: bool = True) -> None:
        """Sets the checkbox state for all items in the list."""
        val = 1 if select else 0
        for item in track_items:
            if "var" in item:
                item["var"].set(val)

    def select_all(self, select: bool = True) -> None:
        """Sets the checkbox state for all items in this instance."""
        TrackTable.select_all_items(self.track_items, select)

    @staticmethod
    def count_selected_items(track_items: List[Dict[str, Any]]) -> int:
        """Static: Returns the number of checked items."""
        return sum(1 for item in track_items if item.get("var") and item["var"].get() == 1)

    @staticmethod
    def clear_completed_items(track_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Static: Filters out rows that have been marked completed."""
        remaining = []
        for item in track_items:
            badge = item.get("status_badge")
            text = badge.cget("text") if badge else ""
            if "✓" in text or "Complete" in text:
                if "row_frame" in item and hasattr(item["row_frame"], "destroy"):
                    item["row_frame"].destroy()
            else:
                remaining.append(item)
        return remaining

    @staticmethod
    def update_badge(track_items: List[Dict[str, Any]], index: int, text: str, color: Optional[str] = None) -> None:
        """Static: Updates badge text and color at index."""
        if 0 <= index < len(track_items):
            badge = track_items[index].get("status_badge")
            if badge:
                if color:
                    badge.configure(text=text, text_color=color)
                else:
                    badge.configure(text=text)
