"""
Fact-Check Audio & Acoustic Verifier Tab Mixin for Shallot Media Archive.
Handles acoustic fingerprinting, discrepancy detection, tag auto-fixing,
cover art enrichment, audio preview playback, and library quarantine sorting.
"""

import os
import sys
import time
import json
import shutil
import threading
import subprocess
import concurrent.futures
from PIL import Image
import customtkinter as ctk

from core import AudioPreviewPlayer, CToolTip
from audio_verifier import AudioFactChecker

base_dir = os.path.dirname(os.path.abspath(__file__))
while not os.path.exists(os.path.join(base_dir, 'app.py')) and os.path.dirname(base_dir) != base_dir:
    base_dir = os.path.dirname(base_dir)


class VerifierTabMixin:
    """Mixin containing GUI layout and controller methods for Acoustic Verifier tab."""

    def build_verifier_page(self, parent):
        # =========================================================================
        # --- Page: Audio Fact-Checker & Verifier Page ---
        # =========================================================================
        self.verifier_page = ctk.CTkFrame(parent, fg_color="transparent")

        lbl_pv = ctk.CTkLabel(self.verifier_page, text="Fact-Check Audio & Acoustic Verifier", font=("Segoe UI", 18, "bold"), anchor="w")
        lbl_pv.pack(fill="x", padx=20, pady=(15, 10))
        self.page_titles.append(lbl_pv)

        # Card 1: Source & Controls Card
        self.verifier_source_card = ctk.CTkFrame(self.verifier_page, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.verifier_source_card.pack(fill="x", padx=20, pady=4)

        card_vsrc_lbl = ctk.CTkLabel(self.verifier_source_card, text="LIBRARY SOURCE & OPTIONS", font=("Segoe UI", 11, "bold"), text_color="#00E5FF")
        card_vsrc_lbl.pack(anchor="w", padx=15, pady=(8, 3))
        self.theme_titles.append(card_vsrc_lbl)

        lbl_vsrc = ctk.CTkLabel(self.verifier_source_card, text="MUSIC FOLDER TO SCAN", font=("Segoe UI", 10, "bold"), text_color="#78909C")
        lbl_vsrc.pack(anchor="w", padx=15, pady=(2, 0))
        self.theme_labels_secondary.append(lbl_vsrc)
        CToolTip(lbl_vsrc, "Fact-checker uses Shazam acoustic neural fingerprinting to scan actual waveforms and identify mislabeled tracks, missing cover art, and metadata discrepancies.")

        v_input_frame = ctk.CTkFrame(self.verifier_source_card, fg_color="transparent")
        v_input_frame.pack(fill="x", padx=15, pady=(2, 4))

        self.verifier_folder_input = ctk.CTkEntry(
            v_input_frame,
            placeholder_text="e.g. D:\\Music or \\\\server\\Music\\Library...",
            height=32,
            fg_color="#070F15",
            border_color="#1F3A4E",
            text_color="#F5F5F7"
        )
        saved_vdir = self.saved_settings.get("plex_music_folder", "") or self.saved_settings.get("destination_folder", "")
        if saved_vdir:
            self.verifier_folder_input.insert(0, saved_vdir)
        self.verifier_folder_input.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.verifier_folder_input.bind("<Return>", lambda e: self._on_verifier_folder_return())
        self.theme_entries.append(self.verifier_folder_input)
        CToolTip(self.verifier_folder_input, "Target music library folder or album path to scan and acoustically fact-check with Shazam.")

        self.btn_verifier_paste = ctk.CTkButton(
            v_input_frame,
            text="📋 Paste",
            width=70,
            height=32,
            font=("Segoe UI", 10, "bold"),
            command=self.paste_verifier_folder
        )
        self.btn_verifier_paste.pack(side="right", padx=(6, 0))
        self.theme_buttons_secondary.append(self.btn_verifier_paste)
        CToolTip(self.btn_verifier_paste, "Paste music folder path from clipboard (Auto-routes pasted URLs)")

        self.btn_verifier_browse = ctk.CTkButton(
            v_input_frame,
            text="📂 Browse",
            width=75,
            height=32,
            font=("Segoe UI", 10, "bold"),
            command=self.browse_verifier_folder
        )
        self.btn_verifier_browse.pack(side="right")
        self.theme_buttons_secondary.append(self.btn_verifier_browse)
        CToolTip(self.btn_verifier_browse, "Browse and select music library folder to scan")

        # Options & Scan Action Row
        v_opts_row = ctk.CTkFrame(self.verifier_source_card, fg_color="transparent")
        v_opts_row.pack(fill="x", padx=15, pady=(2, 8))

        self.verifier_reorg_switch = ctk.CTkSwitch(
            v_opts_row,
            text="Auto-Move to Artist/Album",
            font=("Segoe UI", 9),
            width=165,
            height=18
        )
        self.verifier_reorg_switch.select()
        self.verifier_reorg_switch.pack(side="left", padx=(0, 10))
        self.theme_switches.append(self.verifier_reorg_switch)
        CToolTip(self.verifier_reorg_switch, "Automatically organizes audio files into standard 'Artist/Album/Track - Title' folder hierarchy upon verification.")

        self.verifier_art_switch = ctk.CTkSwitch(
            v_opts_row,
            text="Download Art & Lyrics",
            font=("Segoe UI", 9),
            width=145,
            height=18
        )
        self.verifier_art_switch.select()
        self.verifier_art_switch.pack(side="left", padx=(0, 10))
        self.theme_switches.append(self.verifier_art_switch)
        CToolTip(self.verifier_art_switch, "Automatically downloads and embeds high-resolution cover art and synchronized lyrics for verified tracks.")

        self.verifier_autofix_switch = ctk.CTkSwitch(
            v_opts_row,
            text="Auto-Fix Confirmed Audio",
            font=("Segoe UI", 9, "bold"),
            progress_color="#10B981",
            width=175,
            height=18,
            command=lambda: self.save_setting("verifier_auto_fix", bool(self.verifier_autofix_switch.get()))
        )
        if self.saved_settings.get("verifier_auto_fix", True):
            self.verifier_autofix_switch.select()
        else:
            self.verifier_autofix_switch.deselect()
        self.verifier_autofix_switch.pack(side="left", padx=(0, 10))
        self.theme_switches.append(self.verifier_autofix_switch)
        CToolTip(self.verifier_autofix_switch, "When enabled, automatically retags and applies official album art/lyrics for tracks confirmed by acoustic fingerprinting.")

        self.verifier_cache_switch = ctk.CTkSwitch(
            v_opts_row,
            text="Fast Resume (Cache)",
            font=("Segoe UI", 9),
            width=140,
            height=18,
            command=lambda: self.save_setting("verifier_use_cache", bool(self.verifier_cache_switch.get()))
        )
        if self.saved_settings.get("verifier_use_cache", True):
            self.verifier_cache_switch.select()
        else:
            self.verifier_cache_switch.deselect()
        self.verifier_cache_switch.pack(side="left", padx=(0, 10))
        self.theme_switches.append(self.verifier_cache_switch)

        lbl_workers = ctk.CTkLabel(v_opts_row, text="Threads:", font=("Segoe UI", 9, "bold"), text_color="#78909C")
        lbl_workers.pack(side="left", padx=(5, 2))
        self.verifier_workers_dropdown = ctk.CTkComboBox(
            v_opts_row,
            values=["1 Worker (Safe / Overnight)", "2 Workers"],
            width=180,
            height=26,
            font=("Segoe UI", 9)
        )
        self.verifier_workers_dropdown.set("1 Worker (Safe / Overnight)")
        self.verifier_workers_dropdown.pack(side="left", padx=(0, 10))

        self.btn_verifier_clear_cache = ctk.CTkButton(
            v_opts_row,
            text="🗑 Clear Cache",
            width=90,
            height=30,
            font=("Segoe UI", 10, "bold"),
            fg_color="#1E293B",
            hover_color="#334155",
            border_color="#475569",
            border_width=1,
            text_color="#94A3B8",
            command=self.clear_verifier_cache
        )
        self.btn_verifier_clear_cache.pack(side="right")
        self.theme_buttons_secondary.append(self.btn_verifier_clear_cache)

        self.btn_verifier_stop_scan = ctk.CTkButton(
            v_opts_row,
            text="⏹ Cancel",
            width=80,
            height=30,
            font=("Segoe UI", 10, "bold"),
            fg_color="#3B1214",
            hover_color="#5C1D20",
            border_color="#FB7185",
            border_width=1,
            text_color="#FB7185",
            command=self.stop_fact_check_scan
        )
        self.btn_verifier_stop_scan.pack(side="right", padx=(0, 6))

        self.btn_verifier_start_scan = ctk.CTkButton(
            v_opts_row,
            text="🔍  Scan & Fact-Check",
            height=30,
            font=("Segoe UI", 11, "bold"),
            command=self.start_fact_check_scan
        )
        self.btn_verifier_start_scan.pack(side="right", padx=(0, 6))

        # Card 2: Filter & Stats Bar
        self.verifier_stats_card = ctk.CTkFrame(self.verifier_page, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.verifier_stats_card.pack(fill="x", padx=20, pady=4)

        # Hero Metrics Row
        self.v_hero_grid = ctk.CTkFrame(self.verifier_stats_card, fg_color="transparent")
        self.v_hero_grid.pack(fill="x", padx=12, pady=(10, 8))

        self.theme_metric_cards = []

        def create_metric_tile(parent, number_text, label_text, num_color, filter_mode):
            card = ctk.CTkFrame(
                parent,
                fg_color="#131C2E",
                corner_radius=8,
                border_color="#1F3A4E",
                border_width=1,
                cursor="hand2"
            )
            card.pack(side="left", fill="both", expand=True, padx=4)
            self.theme_metric_cards.append(card)

            num_lbl = ctk.CTkLabel(
                card,
                text=number_text,
                font=("Segoe UI", 16, "bold"),
                text_color=num_color
            )
            num_lbl.pack(pady=(6, 0))

            sub_lbl = ctk.CTkLabel(
                card,
                text=label_text,
                font=("Segoe UI", 9, "bold"),
                text_color="#94A3B8"
            )
            sub_lbl.pack(pady=(0, 6))

            # Clicking anywhere on the tile sets the filter
            card.bind("<Button-1>", lambda e, m=filter_mode: self.set_verifier_filter(m))
            num_lbl.bind("<Button-1>", lambda e, m=filter_mode: self.set_verifier_filter(m))
            sub_lbl.bind("<Button-1>", lambda e, m=filter_mode: self.set_verifier_filter(m))

            return card, num_lbl, sub_lbl

        self.metric_card_total, self.verifier_num_total, self.verifier_lbl_total = create_metric_tile(
            self.v_hero_grid, "0", "TOTAL SCANNED", "#38BDF8", "all"
        )
        self.metric_card_mismatch, self.verifier_num_mismatch, self.verifier_lbl_mismatch = create_metric_tile(
            self.v_hero_grid, "0", "⚠️ DISCREPANCIES", "#FB7185", "mismatch"
        )
        self.metric_card_covers, self.verifier_num_covers, self.verifier_lbl_covers = create_metric_tile(
            self.v_hero_grid, "0", "🎭 COVERS", "#F59E0B", "covers"
        )
        self.metric_card_verified, self.verifier_num_verified, self.verifier_lbl_verified = create_metric_tile(
            self.v_hero_grid, "0", "✅ VERIFIED", "#4ADE80", "verified"
        )
        self.metric_card_unrec, self.verifier_num_unrec, self.verifier_lbl_unrec = create_metric_tile(
            self.v_hero_grid, "0", "❓ UNKNOWN", "#94A3B8", "unrec"
        )

        # Filter & Action Control Row
        v_actions_bar = ctk.CTkFrame(self.verifier_stats_card, fg_color="transparent")
        v_actions_bar.pack(fill="x", padx=16, pady=(0, 10))

        v_actions_left = ctk.CTkFrame(v_actions_bar, fg_color="transparent")
        v_actions_left.pack(side="left", fill="x")

        lbl_filter_prefix = ctk.CTkLabel(
            v_actions_left,
            text="FILTER:",
            font=("Segoe UI", 9, "bold"),
            text_color="#64748B"
        )
        lbl_filter_prefix.pack(side="left", padx=(0, 6))

        self.btn_vfilt_all = ctk.CTkButton(
            v_actions_left,
            text="All",
            width=50,
            height=26,
            corner_radius=6,
            font=("Segoe UI", 9, "bold"),
            command=lambda: self.set_verifier_filter("all")
        )
        self.btn_vfilt_all.pack(side="left", padx=3)

        self.btn_vfilt_mismatch = ctk.CTkButton(
            v_actions_left,
            text="⚠️ Mismatches",
            width=92,
            height=26,
            corner_radius=6,
            font=("Segoe UI", 9, "bold"),
            command=lambda: self.set_verifier_filter("mismatch")
        )
        self.btn_vfilt_mismatch.pack(side="left", padx=3)

        self.btn_vfilt_covers = ctk.CTkButton(
            v_actions_left,
            text="🎭 Covers",
            width=80,
            height=26,
            corner_radius=6,
            font=("Segoe UI", 9, "bold"),
            command=lambda: self.set_verifier_filter("covers")
        )
        self.btn_vfilt_covers.pack(side="left", padx=3)

        self.btn_vfilt_verified = ctk.CTkButton(
            v_actions_left,
            text="✅ Verified",
            width=80,
            height=26,
            corner_radius=6,
            font=("Segoe UI", 9, "bold"),
            command=lambda: self.set_verifier_filter("verified")
        )
        self.btn_vfilt_verified.pack(side="left", padx=3)

        self.btn_vfilt_unrec = ctk.CTkButton(
            v_actions_left,
            text="❓ Unknown",
            width=82,
            height=26,
            corner_radius=6,
            font=("Segoe UI", 9, "bold"),
            command=lambda: self.set_verifier_filter("unrec")
        )
        self.btn_vfilt_unrec.pack(side="left", padx=3)

        v_actions_right = ctk.CTkFrame(v_actions_bar, fg_color="transparent")
        v_actions_right.pack(side="right")

        self.btn_verifier_select_all = ctk.CTkButton(
            v_actions_right,
            text="Select All",
            width=76,
            height=26,
            corner_radius=6,
            font=("Segoe UI", 9, "bold"),
            command=lambda: self.toggle_all_verifier_items(True)
        )
        self.btn_verifier_select_all.pack(side="left", padx=3)
        self.theme_buttons_secondary.append(self.btn_verifier_select_all)

        self.btn_verifier_deselect_all = ctk.CTkButton(
            v_actions_right,
            text="Deselect All",
            width=82,
            height=26,
            corner_radius=6,
            font=("Segoe UI", 9, "bold"),
            command=lambda: self.toggle_all_verifier_items(False)
        )
        self.btn_verifier_deselect_all.pack(side="left", padx=3)
        self.theme_buttons_secondary.append(self.btn_verifier_deselect_all)

        # Card 3: Scrollable Result List
        self.verifier_results_card = ctk.CTkFrame(self.verifier_page, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.verifier_results_card.pack(fill="both", expand=True, padx=20, pady=4)

        self.verifier_scroll = ctk.CTkScrollableFrame(self.verifier_results_card, fg_color="transparent", border_width=0)
        self.verifier_scroll.pack(fill="both", expand=True, padx=12, pady=6)

        self.verifier_empty_lbl = ctk.CTkLabel(
            self.verifier_scroll,
            text="No scan performed yet. Select your Plexamp music folder above and click 'Scan & Fact-Check'.",
            font=("Segoe UI", 11),
            text_color="#78909C"
        )
        self.verifier_empty_lbl.pack(pady=30)
        self.theme_labels_secondary.append(self.verifier_empty_lbl)

        # Card 4: Action & Progress Card
        self.verifier_action_card = ctk.CTkFrame(self.verifier_page, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.verifier_action_card.pack(fill="x", padx=20, pady=(4, 10))

        v_act_top = ctk.CTkFrame(self.verifier_action_card, fg_color="transparent")
        v_act_top.pack(fill="x", padx=15, pady=(8, 2))

        self.verifier_status_lbl = ctk.CTkLabel(v_act_top, text="Ready to fact-check audio library", font=("Segoe UI", 11, "bold"), text_color="#78909C", anchor="w")
        self.verifier_status_lbl.pack(side="left")
        self.theme_labels_secondary.append(self.verifier_status_lbl)

        self.verifier_counter_lbl = ctk.CTkLabel(v_act_top, text="0 / 0  (0.0%)", font=("Segoe UI", 11, "bold"), text_color="#38BDF8", anchor="e")
        self.verifier_counter_lbl.pack(side="right")

        self.verifier_progress_bar = ctk.CTkProgressBar(self.verifier_action_card, height=14, corner_radius=7, progress_color="#00E5FF", fg_color="#1E293B")
        self.verifier_progress_bar.set(0)
        self.verifier_progress_bar.pack(fill="x", padx=15, pady=(4, 6))

        self.verifier_workers_lbl = ctk.CTkLabel(
            self.verifier_action_card,
            text="",
            font=("Segoe UI", 9),
            text_color="#38BDF8",
            anchor="w"
        )
        self.verifier_workers_lbl.pack(fill="x", padx=15, pady=(0, 6))
        v_act_btns = ctk.CTkFrame(self.verifier_action_card, fg_color="transparent")
        v_act_btns.pack(fill="x", padx=15, pady=(0, 8))

        self.btn_verifier_redownload_selected = ctk.CTkButton(
            v_act_btns,
            text="🔄  Re-Download Real Audio",
            font=("Segoe UI", 11, "bold"),
            height=36,
            corner_radius=8,
            fg_color="#028090",
            hover_color="#00A896",
            command=self.redownload_selected_verifier_tracks
        )
        self.btn_verifier_redownload_selected.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.btn_verifier_autofix_all = ctk.CTkButton(
            v_act_btns,
            text="⚡  Auto-Fix All Issues",
            font=("Segoe UI", 11, "bold"),
            height=36,
            corner_radius=8,
            fg_color="#059669",
            hover_color="#10B981",
            command=self.autofix_all_discrepancies
        )
        self.btn_verifier_autofix_all.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.btn_verifier_fix_selected = ctk.CTkButton(
            v_act_btns,
            text="🛠  Fix & Re-tag Selected",
            font=("Segoe UI", 11, "bold"),
            height=36,
            corner_radius=8,
            command=self.fix_selected_verifier_tracks
        )
        self.btn_verifier_fix_selected.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.btn_verifier_keep_selected = ctk.CTkButton(
            v_act_btns,
            text="✅  Keep Selected Tags (Mark Verified)",
            font=("Segoe UI", 11, "bold"),
            height=36,
            corner_radius=8,
            fg_color="#064E3B",
            hover_color="#047857",
            border_color="#34D399",
            border_width=1,
            text_color="#34D399",
            command=self.mark_selected_verifier_tracks_as_verified
        )
        self.btn_verifier_keep_selected.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.btn_verifier_move_to_sort = ctk.CTkButton(
            v_act_btns,
            text="📦 Move to _SORT",
            font=("Segoe UI", 11, "bold"),
            height=36,
            corner_radius=8,
            fg_color="#7C2D12",
            hover_color="#9A3412",
            border_color="#FB923C",
            border_width=1,
            text_color="#FED7AA",
            command=self.move_selected_verifier_tracks_to_sort
        )
        self.btn_verifier_move_to_sort.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.btn_verifier_export = ctk.CTkButton(
            v_act_btns,
            text="📋 Export Report",
            font=("Segoe UI", 11, "bold"),
            height=36,
            width=120,
            corner_radius=8,
            command=self.export_verifier_report
        )
        self.btn_verifier_export.pack(side="left", padx=(0, 6))
        self.theme_buttons_secondary.append(self.btn_verifier_export)

        self.btn_verifier_error_log = ctk.CTkButton(
            v_act_btns,
            text="📑 Error Log",
            font=("Segoe UI", 11, "bold"),
            height=36,
            width=100,
            corner_radius=8,
            command=self.open_fact_checker_error_log
        )
        self.btn_verifier_error_log.pack(side="left", padx=(0, 6))
        self.theme_buttons_secondary.append(self.btn_verifier_error_log)

        self.btn_verifier_open_folder = ctk.CTkButton(
            v_act_btns,
            text="📂 Open Music Folder",
            font=("Segoe UI", 11, "bold"),
            height=36,
            width=140,
            corner_radius=8,
            fg_color="#0E1A24",
            border_color="#00E5FF",
            border_width=1,
            text_color="#00E5FF",
            command=self.open_verifier_music_folder
        )
        self.btn_verifier_open_folder.pack(side="right")
        self.theme_buttons_secondary.append(self.btn_verifier_open_folder)


    def _on_verifier_folder_return(self, event=None):
        text = self.verifier_folder_input.get().strip()
        if not text:
            return
        if self.dispatch_smart_input(text, source_tab="verifier"):
            return
        self.start_fact_check_scan()

    def start_verifier_scan(self):
        return self.start_fact_check_scan()

    def paste_verifier_folder(self):
        """ Pastes clipboard contents into Verifier folder input and checks smart dispatch """
        try:
            clipboard_text = self.clipboard_get().strip().strip('"\'')
            if clipboard_text:
                if self.dispatch_smart_input(clipboard_text, source_tab="verifier"):
                    return
                self.verifier_folder_input.delete(0, "end")
                self.verifier_folder_input.insert(0, clipboard_text)
        except Exception as e:
            self.log(f"Verifier clipboard paste error: {e}", is_error=True)
    # =========================================================================
    # --- Audio Fact-Checker & Verifier Logic ---
    # =========================================================================

    def browse_verifier_folder(self):
        from tkinter import filedialog
        folder = filedialog.askdirectory(title="Select Music Folder to Scan & Fact-Check")
        if folder:
            self.verifier_folder_input.delete(0, "end")
            self.verifier_folder_input.insert(0, folder)
            self.save_setting("plex_music_folder", folder)

    def open_verifier_music_folder(self):
        folder = self.verifier_folder_input.get().strip()
        if folder and os.path.exists(folder):
            try:
                os.startfile(folder)
            except Exception:
                subprocess.Popen(["explorer", folder])
        else:
            self.log("Music folder does not exist or is not specified.", is_error=True)

    def start_fact_check_scan(self):
        """ Scans library and performs acoustic recognition to verify actual song identities """
        folder = self.verifier_folder_input.get().strip()
        if not folder or not os.path.exists(folder):
            self.verifier_status_lbl.configure(text="Invalid folder path. Please select a valid folder.", text_color="#FB7185")
            return

        self.save_setting("plex_music_folder", folder)
        self.verifier_is_scanning = True
        self.verifier_cancel_event.clear()
        self.verifier_scan_results = []
        self.verifier_track_items = []
        self.verifier_active_workers = {}

        # Clear scrollable list and add live progress banner
        for child in self.verifier_scroll.winfo_children():
            child.destroy()

        self.verifier_scan_live_banner = ctk.CTkLabel(
            self.verifier_scroll,
            text="🎧 Acoustic verification started... Tracks will appear live below as waveforms are identified.",
            font=("Segoe UI", 11, "italic"),
            text_color="#38BDF8"
        )
        self.verifier_scan_live_banner.pack(pady=20)

        self.verifier_progress_bar.set(0)
        self.verifier_counter_lbl.configure(text="0 / 0")
        self.btn_verifier_start_scan.configure(state="disabled", text="Scanning Library... ⏳")
        self.btn_verifier_fix_selected.configure(state="disabled")
        self.btn_verifier_export.configure(state="disabled")
        self.verifier_status_lbl.configure(text="Discovering audio files...", text_color="#78909C")
        self.verifier_workers_lbl.configure(text="⚡ Active: Initializing worker threads...", text_color="#38BDF8")
        self.power_light.configure(text="● SCANNING", text_color=getattr(self, 'theme_cfg', {}).get("accent", "#00E5FF"))

        self.update_verifier_stat_counts(0, 0, 0, 0, 0)

        scan_start_time = time.time()

        def log_cb(msg: str, is_error: bool = False):
            self.after(0, lambda m=msg, err=is_error: self.log(f"[Fact-Checker] {m}", is_error=err))

        last_worker_update_time = [0.0]
        def active_worker_cb(workers: dict):
            self.verifier_active_workers = dict(workers)
            now = time.time()
            if now - last_worker_update_time[0] >= 0.3:
                last_worker_update_time[0] = now
                self.after(0, update_workers_display)

        def update_workers_display():
            if not self.verifier_is_scanning:
                self.verifier_workers_lbl.configure(text="")
                return
            if not self.verifier_active_workers:
                self.verifier_workers_lbl.configure(text="⚡ Active: Dispatching next track...", text_color="#78909C")
                return

            worker_strs = []
            now = time.time()
            workers_list = list(self.verifier_active_workers.values())
            for idx, info in enumerate(workers_list, start=1):
                fn = info.get("filename", "")
                if len(fn) > 28:
                    fn = fn[:25] + "..."
                elapsed = int(now - info.get("start_time", now))
                warn = " ⚠️" if elapsed >= 25 else ""
                worker_strs.append(f"W{idx}: {fn} ({elapsed}s{warn})")

            disp_text = "⚡ Active: " + "  |  ".join(worker_strs)
            self.verifier_workers_lbl.configure(text=disp_text, text_color="#38BDF8")

        def heartbeat_loop():
            if self.verifier_is_scanning:
                try:
                    update_workers_display()
                except Exception:
                    pass
                self.after(1000, heartbeat_loop)

        def fmt_time(seconds: int) -> str:
            m, s = divmod(max(0, int(seconds)), 60)
            h, m = divmod(m, 60)
            return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

        last_progress_time = [0.0]
        def progress_cb(curr: int, total: int, filename: str):
            pct = curr / max(1, total)
            now = time.time()
            if curr != 0 and curr != total and (now - last_progress_time[0] < 0.35):
                return
            last_progress_time[0] = now

            self.after(0, lambda: self.verifier_progress_bar.set(pct))
            self.after(0, lambda: self.verifier_counter_lbl.configure(text=f"{curr} / {total}  ({pct*100:.1f}%)"))
            if curr == 0:
                self.after(0, lambda: self.verifier_status_lbl.configure(text=f"Analyzing {total} audio files...", text_color="#38BDF8"))
            else:
                elapsed_s = time.time() - scan_start_time
                avg_track_s = elapsed_s / max(1, curr)
                eta_s = int(avg_track_s * max(0, total - curr))
                time_str = f"⏱️ {fmt_time(elapsed_s)} | ETA: {fmt_time(eta_s)}"
                self.after(0, lambda t=time_str, fn=filename: self.verifier_status_lbl.configure(
                    text=f"Acoustic Check ({curr}/{total}) • {t} • {fn[:35]}",
                    text_color="#E0F2FE"
                ))
            self.after(0, lambda: self.update_taskbar_progress(int(pct * 100)))

        # Incremental stats tracker to avoid expensive sum() recalculations
        stats_counts = {
            "total": len(self.verifier_scan_results),
            "covers": sum(1 for r in self.verifier_scan_results if r.get("status") == "COVER_DETECTED"),
            "issues": sum(1 for r in self.verifier_scan_results if r.get("status") in ("MISMATCH", "COVER_DETECTED", "WRONG_TRACK", "METADATA_TYPO", "DURATION_MISMATCH")),
            "verified": sum(1 for r in self.verifier_scan_results if r.get("status") == "VERIFIED"),
            "unknown": sum(1 for r in self.verifier_scan_results if r.get("status") in ("UNRECOGNIZED", "TIMEOUT", "ERROR", "RATE_LIMITED"))
        }
        last_stat_label_time = [0.0]

        def update_stat_labels_throttled(force: bool = False):
            now = time.time()
            if not force and (now - last_stat_label_time[0] < 0.3):
                return
            last_stat_label_time[0] = now
            self.update_verifier_stat_counts(
                stats_counts['total'],
                stats_counts['issues'],
                stats_counts['covers'],
                stats_counts['verified'],
                stats_counts['unknown']
            )

        def item_cb(res: dict):
            self.verifier_scan_results.append(res)
            original_idx = len(self.verifier_scan_results) - 1

            st = res.get("status", "")
            stats_counts["total"] += 1
            if st == "COVER_DETECTED":
                stats_counts["covers"] += 1
            if st in ("MISMATCH", "COVER_DETECTED", "WRONG_TRACK", "METADATA_TYPO", "DURATION_MISMATCH"):
                stats_counts["issues"] += 1
            elif st == "VERIFIED":
                stats_counts["verified"] += 1
            elif st in ("UNRECOGNIZED", "TIMEOUT", "ERROR", "RATE_LIMITED"):
                stats_counts["unknown"] += 1

            self.after(0, update_stat_labels_throttled)
            self.after(0, lambda r=res, idx=original_idx: self._stream_verifier_row(r, idx))

        def run_scan():
            self.log(f"Starting deep acoustic library fact-check on: {folder}")
            use_cache = bool(self.verifier_cache_switch.get()) if hasattr(self, 'verifier_cache_switch') else True
            auto_fix = bool(self.verifier_autofix_switch.get()) if hasattr(self, 'verifier_autofix_switch') else True
            reorg = bool(self.verifier_reorg_switch.get()) if hasattr(self, 'verifier_reorg_switch') else False
            w_str = self.verifier_workers_dropdown.get() if hasattr(self, 'verifier_workers_dropdown') else "1"
            try:
                num_workers = int(w_str.split()[0])
            except Exception:
                num_workers = 1
            num_workers = max(1, min(num_workers, 2))
            self.log(f"[Fact-Checker] Safe Overnight Mode: {num_workers} worker(s) | Auto-Fix: {'ENABLED' if auto_fix else 'DISABLED'} | Reorganize: {'YES' if reorg else 'NO'}")
            try:
                AudioFactChecker.scan_directory(
                    root_dir=folder,
                    progress_cb=progress_cb,
                    item_cb=item_cb,
                    active_worker_cb=active_worker_cb,
                    log_cb=log_cb,
                    cancel_event=self.verifier_cancel_event,
                    max_workers=num_workers,
                    per_file_timeout=35.0,
                    use_cache=use_cache,
                    auto_fix=auto_fix,
                    destination_root=folder,
                    reorganize=reorg
                )
            except Exception as e:
                self.log(f"Scan error: {e}", is_error=True)
            self.after(0, lambda: update_stat_labels_throttled(force=True))
            self.after(0, self.on_verifier_scan_complete)

        self.after(500, heartbeat_loop)
        threading.Thread(target=run_scan, daemon=True).start()

    def stop_fact_check_scan(self):
        """ Cancels the ongoing acoustic scan """
        if self.verifier_is_scanning:
            self.verifier_cancel_event.set()
            self.verifier_status_lbl.configure(text="Cancelling scan...", text_color="#FB7185")
            self.verifier_workers_lbl.configure(text="⏹ Stopping worker threads...", text_color="#FB7185")
            self.log("Acoustic scan cancellation requested by user.")

    def on_verifier_scan_complete(self):
        self.verifier_is_scanning = False
        self.verifier_active_workers = {}
        self.verifier_workers_lbl.configure(text="")
        self.btn_verifier_start_scan.configure(state="normal", text="🔍  Scan & Fact-Check")
        self.btn_verifier_fix_selected.configure(state="normal")
        if hasattr(self, 'btn_verifier_autofix_all'):
            self.btn_verifier_autofix_all.configure(state="normal")
        if hasattr(self, 'btn_verifier_redownload_selected'):
            self.btn_verifier_redownload_selected.configure(state="normal")
        self.btn_verifier_export.configure(state="normal")
        self.update_taskbar_progress(0)
        self.power_light.configure(
            text=getattr(self, 'theme_cfg', {}).get("status_text", "● READY"),
            text_color=getattr(self, 'theme_cfg', {}).get("status_color", "#38BDF8")
        )

        tot = len(self.verifier_scan_results)
        cov = sum(1 for r in self.verifier_scan_results if r.get("status") == "COVER_DETECTED")
        mis = sum(1 for r in self.verifier_scan_results if r.get("status") in ("MISMATCH", "COVER_DETECTED", "WRONG_TRACK", "METADATA_TYPO", "DURATION_MISMATCH"))
        ver = sum(1 for r in self.verifier_scan_results if r.get("status") == "VERIFIED")
        unr = sum(1 for r in self.verifier_scan_results if r.get("status") in ("UNRECOGNIZED", "TIMEOUT", "ERROR"))

        # If covers or mismatches are detected, automatically default the view
        if cov > 0:
            self.verifier_filter_mode = "covers"
        elif mis > 0:
            self.verifier_filter_mode = "mismatch"
        self.update_verifier_filter_buttons()

        msg = f"✓ Scan Complete: {tot} files | {cov} covers | {mis} issues | {ver} verified"
        self.verifier_status_lbl.configure(
            text=msg,
            text_color="#F59E0B" if cov > 0 else ("#FB7185" if mis > 0 else "#4ADE80")
        )
        self.log(f"Scan finished: {tot} files. {cov} covers, {mis} total issues detected, {ver} verified, {unr} unrecognized/timeouts.")

        self.render_verifier_results()

    def update_verifier_stat_counts(self, tot: int = 0, mis: int = 0, cov: int = 0, ver: int = 0, unr: int = 0):
        """ Updates both the bold numeric hero displays and the label texts """
        if hasattr(self, 'verifier_num_total'):
            self.verifier_num_total.configure(text=f"{tot:,}")
        if hasattr(self, 'verifier_num_mismatch'):
            self.verifier_num_mismatch.configure(text=f"{mis:,}")
        if hasattr(self, 'verifier_num_covers'):
            self.verifier_num_covers.configure(text=f"{cov:,}")
        if hasattr(self, 'verifier_num_verified'):
            self.verifier_num_verified.configure(text=f"{ver:,}")
        if hasattr(self, 'verifier_num_unrec'):
            self.verifier_num_unrec.configure(text=f"{unr:,}")

        if hasattr(self, 'verifier_lbl_total'):
            self.verifier_lbl_total.configure(text="TOTAL SCANNED")
        if hasattr(self, 'verifier_lbl_mismatch'):
            self.verifier_lbl_mismatch.configure(text="⚠️ DISCREPANCIES")
        if hasattr(self, 'verifier_lbl_covers'):
            self.verifier_lbl_covers.configure(text="🎭 COVERS")
        if hasattr(self, 'verifier_lbl_verified'):
            self.verifier_lbl_verified.configure(text="✅ VERIFIED")
        if hasattr(self, 'verifier_lbl_unrec'):
            self.verifier_lbl_unrec.configure(text="❓ UNKNOWN")

    def set_verifier_filter(self, mode: str):
        self.verifier_filter_mode = mode
        self.update_verifier_filter_buttons()
        self.render_verifier_results()

    def update_verifier_filter_buttons(self):
        cfg = getattr(self, 'theme_cfg', {})
        active_bg = cfg.get("option_btn", "#1E293B")
        inactive_bg = cfg.get("input_bg", "#090E17")
        border = cfg.get("border", "#1E293B")
        accent = cfg.get("accent", "#38BDF8")

        mode = self.verifier_filter_mode
        if hasattr(self, 'btn_vfilt_all'):
            self.btn_vfilt_all.configure(
                fg_color=accent if mode == "all" else inactive_bg,
                text_color="#080D14" if mode == "all" else "#F8FAFC",
                border_color=accent if mode == "all" else border,
                border_width=1
            )
            self.btn_vfilt_mismatch.configure(
                fg_color="#4C0519" if mode == "mismatch" else inactive_bg,
                text_color="#FB7185" if mode == "mismatch" else "#94A3B8",
                border_color="#FB7185" if mode == "mismatch" else border,
                border_width=1
            )
            self.btn_vfilt_covers.configure(
                fg_color="#451A03" if mode == "covers" else inactive_bg,
                text_color="#F59E0B" if mode == "covers" else "#94A3B8",
                border_color="#F59E0B" if mode == "covers" else border,
                border_width=1
            )
            self.btn_vfilt_verified.configure(
                fg_color="#064E3B" if mode == "verified" else inactive_bg,
                text_color="#4ADE80" if mode == "verified" else "#94A3B8",
                border_color="#4ADE80" if mode == "verified" else border,
                border_width=1
            )
            self.btn_vfilt_unrec.configure(
                fg_color="#1E293B" if mode == "unrec" else inactive_bg,
                text_color="#CBD5E1" if mode == "unrec" else "#94A3B8",
                border_color="#94A3B8" if mode == "unrec" else border,
                border_width=1
            )

        if hasattr(self, 'metric_card_total'):
            self.metric_card_total.configure(border_color=accent if mode == "all" else border, border_width=2 if mode == "all" else 1)
            self.metric_card_mismatch.configure(border_color="#FB7185" if mode == "mismatch" else border, border_width=2 if mode == "mismatch" else 1)
            self.metric_card_covers.configure(border_color="#F59E0B" if mode == "covers" else border, border_width=2 if mode == "covers" else 1)
            self.metric_card_verified.configure(border_color="#4ADE80" if mode == "verified" else border, border_width=2 if mode == "verified" else 1)
            self.metric_card_unrec.configure(border_color="#94A3B8" if mode == "unrec" else border, border_width=2 if mode == "unrec" else 1)

    def clear_verifier_cache(self):
        """ Clears persistent verification cache on disk """
        AudioFactChecker.clear_cache()
        self.verifier_scan_results = []
        self.update_verifier_stat_counts(0, 0, 0, 0, 0)
        self.verifier_status_lbl.configure(text="✓ Verification cache cleared. Ready for fresh scan.", text_color="#4ADE80")
        self.log("[Fact-Checker] Persistent scan cache has been cleared.")
        self.render_verifier_results()

    def toggle_all_verifier_items(self, state: bool):
        for item in self.verifier_track_items:
            item["var"].set(1 if state else 0)

    def render_verifier_results(self):
        """ Renders the list of scanned tracks with their match details into the scroll frame """
        for child in self.verifier_scroll.winfo_children():
            child.destroy()
        self.verifier_track_items = []

        cfg = getattr(self, 'theme_cfg', {})
        card_bg = cfg.get("input_bg", "#070F15")
        border_col = cfg.get("border", "#1F3A4E")

        status_priority = {
            "COVER_DETECTED": 0,
            "WRONG_TRACK": 1,
            "DURATION_MISMATCH": 2,
            "METADATA_TYPO": 3,
            "MISMATCH": 4,
            "TIMEOUT": 5,
            "ERROR": 6,
            "UNRECOGNIZED": 7,
            "VERIFIED": 8
        }

        filtered = []
        for idx, res in enumerate(self.verifier_scan_results):
            st = res.get("status", "")
            if self.verifier_filter_mode == "covers" and st != "COVER_DETECTED":
                continue
            if self.verifier_filter_mode == "mismatch" and st not in ("MISMATCH", "COVER_DETECTED", "WRONG_TRACK", "METADATA_TYPO", "DURATION_MISMATCH"):
                continue
            if self.verifier_filter_mode == "verified" and st != "VERIFIED":
                continue
            if self.verifier_filter_mode == "unrec" and st not in ("UNRECOGNIZED", "TIMEOUT", "ERROR", "RATE_LIMITED"):
                continue
            filtered.append((idx, res))

        # Always sort with Mismatches first, then Unknown/Errors, then Verified
        filtered.sort(key=lambda x: (status_priority.get(x[1].get("status", ""), 99), x[1].get("filename", "").lower()))

        if not filtered:
            msg = "No files match the selected filter." if self.verifier_scan_results else "No scan performed yet. Select your music folder and click 'Scan & Fact-Check'."
            empty_lbl = ctk.CTkLabel(self.verifier_scroll, text=msg, font=("Segoe UI", 11), text_color="#78909C")
            empty_lbl.pack(pady=30)
            return

        MAX_DISPLAY = 250
        for original_idx, res in filtered[:MAX_DISPLAY]:
            self._create_verifier_row_widget(res, original_idx)

        if len(filtered) > MAX_DISPLAY:
            overflow_lbl = ctk.CTkLabel(
                self.verifier_scroll,
                text=f"Showing first {MAX_DISPLAY} of {len(filtered)} items. Select a category tab (Issues / Covers / Verified / Unknown) or Export Report for full details.",
                font=("Segoe UI", 10, "italic"),
                text_color="#78909C"
            )
            overflow_lbl.pack(pady=15)

    def _stream_verifier_row(self, res: dict, original_idx: int):
        """ Dynamically adds a scanned track row to the active view in real-time as recognition finishes """
        if hasattr(self, 'verifier_scan_live_banner') and self.verifier_scan_live_banner and self.verifier_scan_live_banner.winfo_exists():
            try:
                self.verifier_scan_live_banner.destroy()
            except Exception:
                pass
            self.verifier_scan_live_banner = None

        if len(self.verifier_track_items) >= 250:
            return

        st = res.get("status", "")
        mode = getattr(self, "verifier_filter_mode", "all")
        if mode == "covers" and st != "COVER_DETECTED":
            return
        if mode == "mismatch" and st not in ("MISMATCH", "COVER_DETECTED", "WRONG_TRACK", "METADATA_TYPO", "DURATION_MISMATCH"):
            return
        if mode == "verified" and st != "VERIFIED":
            return
        if mode == "unrec" and st not in ("UNRECOGNIZED", "TIMEOUT", "ERROR", "RATE_LIMITED"):
            return

        self._create_verifier_row_widget(res, original_idx)

    def _create_verifier_row_widget(self, res: dict, original_idx: int):
        """ Builds and packs a single track row widget into the scrollable list """
        cfg = getattr(self, 'theme_cfg', {})
        card_bg = cfg.get("input_bg", "#070F15")
        border_col = cfg.get("border", "#1F3A4E")

        st = res.get("status", "")
        curr = res.get("current", {})
        rec = res.get("recognized", {})

        row_frame = ctk.CTkFrame(
            self.verifier_scroll,
            fg_color=card_bg,
            corner_radius=8,
            border_color="#FB7185" if st == "MISMATCH" else border_col,
            border_width=1
        )
        row_frame.pack(fill="x", pady=3, padx=4)

        # Checkbox
        var = ctk.IntVar(value=1 if st in ("MISMATCH", "COVER_DETECTED", "WRONG_TRACK", "DURATION_MISMATCH", "METADATA_TYPO") else 0)
        cb = ctk.CTkCheckBox(
            row_frame,
            text="",
            variable=var,
            width=24,
            checkbox_width=18,
            checkbox_height=18,
            corner_radius=4,
            fg_color=cfg.get("option_btn", "#028090"),
            hover_color=cfg.get("option_hover", "#00A896")
        )
        cb.pack(side="left", padx=(10, 6), pady=8)

        # Status Badge
        if st == "COVER_DETECTED":
            badge_text = "🎭 COVER"
            badge_color = "#F59E0B"
        elif st == "WRONG_TRACK":
            badge_text = "❌ WRONG AUDIO"
            badge_color = "#FB7185"
        elif st == "DURATION_MISMATCH":
            badge_text = "⏳ SKIT/EDIT"
            badge_color = "#EAB308"
        elif st == "METADATA_TYPO":
            badge_text = "🏷️ TYPO"
            badge_color = "#38BDF8"
        elif st == "MISMATCH":
            badge_text = "⚠️ WRONG TAG"
            badge_color = "#FB7185"
        elif st == "VERIFIED":
            badge_text = "✅ VERIFIED"
            badge_color = "#4ADE80"
        elif st == "QUARANTINED":
            badge_text = "📦 QUARANTINED"
            badge_color = "#FB923C"
        elif st == "RATE_LIMITED":
            badge_text = "🛑 RATE-LIMIT"
            badge_color = "#FB7185"
        elif st == "TIMEOUT":
            badge_text = "⏳ TIMEOUT"
            badge_color = "#F59E0B"
        elif st == "UNRECOGNIZED":
            badge_text = "❓ UNKNOWN"
            badge_color = "#94A3B8"
        else:
            badge_text = "⚠️ ERROR"
            badge_color = "#F87171"

        badge_lbl = ctk.CTkLabel(
            row_frame,
            text=badge_text,
            font=("Segoe UI", 9, "bold"),
            text_color=badge_color,
            width=95,
            anchor="w"
        )
        badge_lbl.pack(side="left", padx=(0, 8))

        # Track Info Container
        info_container = ctk.CTkFrame(row_frame, fg_color="transparent")
        info_container.pack(side="left", fill="x", expand=True, pady=6)

        # Row 1: File name & path
        fn_lbl = ctk.CTkLabel(
            info_container,
            text=res.get("filename", ""),
            font=("Segoe UI", 10, "bold"),
            text_color=cfg.get("text_primary", "#F5F5F7"),
            anchor="w"
        )
        fn_lbl.pack(fill="x")

        # Row 2: Tagged vs Actual
        curr_tag_str = f"Tag: {curr.get('artist', 'Unknown')} - {curr.get('title', 'Unknown')} [{curr.get('album', '')}]"
        if rec.get("matched"):
            rec_str = f"ACTUAL: {rec.get('artist')} - {rec.get('title')} [{rec.get('album')} ({rec.get('year')})]"
            detail_text = f"{curr_tag_str}   ➔   {rec_str}"
        else:
            detail_text = f"{curr_tag_str}   (No audio match found)"

        detail_lbl = ctk.CTkLabel(
            info_container,
            text=detail_text,
            font=("Segoe UI", 9),
            text_color="#F59E0B" if st == "COVER_DETECTED" else ("#FB7185" if st in ("MISMATCH", "WRONG_TRACK") else "#94A3B8"),
            anchor="w"
        )
        detail_lbl.pack(fill="x")

        # Action Button per row
        btn_redl = None
        btn_fix = None
        btn_keep = None
        btn_sort = None
        if st in ("COVER_DETECTED", "WRONG_TRACK", "DURATION_MISMATCH"):
            btn_redl = ctk.CTkButton(
                row_frame,
                text="🔄 Re-Download",
                width=95,
                height=26,
                font=("Segoe UI", 9, "bold"),
                fg_color="#028090",
                hover_color="#00A896",
                command=lambda idx=original_idx: self.redownload_single_verifier_track(idx)
            )
            btn_redl.pack(side="right", padx=(4, 8))

            btn_fix = ctk.CTkButton(
                row_frame,
                text="🏷️ Accept Tags",
                width=85,
                height=26,
                font=("Segoe UI", 9, "bold"),
                command=lambda idx=original_idx: self.fix_single_verifier_track(idx)
            )
            btn_fix.pack(side="right", padx=(2, 2))

            btn_keep = ctk.CTkButton(
                row_frame,
                text="✅ Keep",
                width=60,
                height=26,
                font=("Segoe UI", 9, "bold"),
                fg_color="#1E293B",
                hover_color="#334155",
                border_color="#34D399",
                border_width=1,
                text_color="#34D399",
                command=lambda idx=original_idx: self.mark_verifier_track_as_verified(idx)
            )
            btn_keep.pack(side="right", padx=(0, 2))
        elif st in ("METADATA_TYPO", "MISMATCH"):
            btn_fix = ctk.CTkButton(
                row_frame,
                text="🛠 Fix Track",
                width=75,
                height=26,
                font=("Segoe UI", 9, "bold"),
                command=lambda idx=original_idx: self.fix_single_verifier_track(idx)
            )
            btn_fix.pack(side="right", padx=(4, 10))

            btn_keep = ctk.CTkButton(
                row_frame,
                text="✅ Keep Tags",
                width=80,
                height=26,
                font=("Segoe UI", 9, "bold"),
                fg_color="#1E293B",
                hover_color="#334155",
                border_color="#34D399",
                border_width=1,
                text_color="#34D399",
                command=lambda idx=original_idx: self.mark_verifier_track_as_verified(idx)
            )
            btn_keep.pack(side="right", padx=(0, 2))
        elif st in ("UNRECOGNIZED", "TIMEOUT", "ERROR"):
            btn_sort = ctk.CTkButton(
                row_frame,
                text="📦 Quarantine",
                width=85,
                height=26,
                font=("Segoe UI", 9, "bold"),
                fg_color="#7C2D12",
                hover_color="#9A3412",
                border_color="#FB923C",
                border_width=1,
                text_color="#FED7AA",
                command=lambda idx=original_idx: self.quarantine_single_verifier_track(idx)
            )
            btn_sort.pack(side="right", padx=(4, 10))
        elif st == "QUARANTINED":
            lbl_q = ctk.CTkLabel(
                row_frame,
                text="📦 In _SORT_UNMATCHED",
                font=("Segoe UI", 9, "italic"),
                text_color="#FB923C"
            )
            lbl_q.pack(side="right", padx=(4, 10))

        # Side-by-Side Diff Modal Button
        btn_diff = ctk.CTkButton(
            row_frame,
            text="⚖️ Diff",
            width=54,
            height=26,
            font=("Segoe UI", 9, "bold"),
            fg_color="#1E293B",
            hover_color="#334155",
            border_color="#94A3B8",
            border_width=1,
            text_color="#E2E8F0",
            command=lambda idx=original_idx: self.show_verifier_track_diff(idx)
        )
        btn_diff.pack(side="right", padx=(2, 4))

        # In-App 10s Audio Audition Button
        btn_play = ctk.CTkButton(
            row_frame,
            text="▶ 10s Preview",
            width=88,
            height=26,
            font=("Segoe UI", 9, "bold"),
            fg_color="#1E293B",
            hover_color="#334155",
            border_color="#38BDF8",
            border_width=1,
            text_color="#38BDF8"
        )
        btn_play.configure(command=lambda idx=original_idx, b=btn_play: self.toggle_verifier_track_preview(idx, b))
        btn_play.pack(side="right", padx=(2, 4))

        # Allow double-clicking row or labels to open diff
        row_frame.bind("<Double-Button-1>", lambda e, idx=original_idx: self.show_verifier_track_diff(idx))
        detail_lbl.bind("<Double-Button-1>", lambda e, idx=original_idx: self.show_verifier_track_diff(idx))
        fn_lbl.bind("<Double-Button-1>", lambda e, idx=original_idx: self.show_verifier_track_diff(idx))

        self.verifier_track_items.append({
            "original_index": original_idx,
            "result": res,
            "var": var,
            "row_frame": row_frame,
            "checkbox": cb,
            "badge_lbl": badge_lbl,
            "detail_lbl": detail_lbl,
            "btn_redl": btn_redl,
            "btn_fix": btn_fix,
            "btn_keep": btn_keep,
            "btn_sort": btn_sort,
            "btn_play": btn_play,
            "btn_diff": btn_diff
        })

    def toggle_verifier_track_preview(self, track_index: int, button_widget=None):
        """ Toggles playback of a 10-second snippet of the track for instant auditory inspection """
        if track_index >= len(self.verifier_scan_results):
            return
        res = self.verifier_scan_results[track_index]
        file_path = res.get("file_path")
        if not file_path or not os.path.exists(file_path):
            self.log(f"Cannot preview track: File does not exist ({file_path})", is_error=True)
            return

        is_currently_playing_this = (
            AudioPreviewPlayer.is_playing() and 
            AudioPreviewPlayer.get_playing_file() == os.path.normpath(file_path)
        )

        if is_currently_playing_this:
            AudioPreviewPlayer.stop()
            if button_widget and button_widget.winfo_exists():
                button_widget.configure(text="▶ 10s Preview", fg_color="#1E293B", text_color="#38BDF8")
        else:
            if hasattr(self, '_active_preview_button') and self._active_preview_button:
                try:
                    if self._active_preview_button.winfo_exists():
                        self._active_preview_button.configure(text="▶ 10s Preview", fg_color="#1E293B", text_color="#38BDF8")
                except Exception:
                    pass
            self._active_preview_button = button_widget

            def on_playback_done():
                def _update_ui():
                    if button_widget and button_widget.winfo_exists():
                        button_widget.configure(text="▶ 10s Preview", fg_color="#1E293B", text_color="#38BDF8")
                    if getattr(self, '_active_preview_button', None) == button_widget:
                        self._active_preview_button = None
                self.after(0, _update_ui)

            file_dur = res.get("current", {}).get("duration_s", 0) or 0
            offset = max(8.0, min(file_dur * 0.25, file_dur - 12.0)) if file_dur > 20.0 else 10.0

            started = AudioPreviewPlayer.play(
                file_path,
                offset_seconds=offset,
                duration_seconds=10.0,
                on_stop=on_playback_done
            )
            if started:
                if button_widget and button_widget.winfo_exists():
                    button_widget.configure(text="⏹ Stop", fg_color="#7F1D1D", text_color="#FCA5A5")
                self.log(f"[Audio Audition] Playing 10s preview of '{res.get('filename')}' @ {int(offset)}s...")

    def show_verifier_track_diff(self, track_index: int):
        """ Displays an elevated side-by-side metadata and acoustic fingerprint comparison modal """
        if track_index >= len(self.verifier_scan_results):
            return
        res = self.verifier_scan_results[track_index]
        curr = res.get("current", {})
        rec = res.get("recognized", {})
        st = res.get("status", "")
        file_path = res.get("file_path", "")
        filename = res.get("filename", "")
        reason = res.get("discrepancy_reason", "No reason specified.")
        cfg = getattr(self, 'theme_cfg', {})

        dialog = ctk.CTkToplevel(self)
        dialog.title(f"Acoustic Verification Diff: {filename}")
        dialog.geometry("780x520")
        dialog.minsize(700, 460)
        try:
            dialog.transient(self)
            dialog.after(50, lambda: [dialog.grab_set() if dialog.winfo_exists() else None])
        except Exception:
            pass

        try:
            x = self.winfo_x() + (self.winfo_width() // 2) - 390
            y = self.winfo_y() + (self.winfo_height() // 2) - 260
            dialog.geometry(f"780x520+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

        def _on_dialog_close():
            AudioPreviewPlayer.stop()
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", _on_dialog_close)

        hdr = ctk.CTkFrame(dialog, fg_color=cfg.get("card_bg", "#0F172A"), corner_radius=10, border_color=cfg.get("border", "#1E293B"), border_width=1)
        hdr.pack(fill="x", padx=20, pady=(20, 10))

        hdr_top = ctk.CTkFrame(hdr, fg_color="transparent")
        hdr_top.pack(fill="x", padx=15, pady=(10, 4))

        fn_lbl = ctk.CTkLabel(hdr_top, text=f"🎵  {filename}", font=("Segoe UI", 13, "bold"), text_color=cfg.get("text_primary", "#F8FAFC"), anchor="w")
        fn_lbl.pack(side="left")

        badge_color = "#FB7185" if st in ("MISMATCH", "WRONG_TRACK") else ("#F59E0B" if st == "COVER_DETECTED" else ("#4ADE80" if st == "VERIFIED" else "#94A3B8"))
        st_badge = ctk.CTkLabel(hdr_top, text=f"  {st}  ", font=("Segoe UI", 10, "bold"), text_color=badge_color, fg_color="#1E293B", corner_radius=6)
        st_badge.pack(side="right")

        rsn_lbl = ctk.CTkLabel(hdr, text=f"Diagnosis: {reason}", font=("Segoe UI", 10), text_color="#94A3B8", anchor="w", wraplength=700, justify="left")
        rsn_lbl.pack(fill="x", padx=15, pady=(0, 10))

        grid_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        grid_frame.pack(fill="both", expand=True, padx=20, pady=5)

        left_card = ctk.CTkFrame(grid_frame, fg_color=cfg.get("card_bg", "#0F172A"), corner_radius=10, border_color=cfg.get("border", "#1E293B"), border_width=1)
        left_card.pack(side="left", fill="both", expand=True, padx=(0, 8))

        lbl_l_title = ctk.CTkLabel(left_card, text="📁 CURRENT EMBEDDED TAGS", font=("Segoe UI", 11, "bold"), text_color="#38BDF8")
        lbl_l_title.pack(anchor="w", padx=15, pady=(12, 8))

        def add_field(parent, label, value, text_color=None):
            f_frame = ctk.CTkFrame(parent, fg_color="transparent")
            f_frame.pack(fill="x", padx=15, pady=3)
            ctk.CTkLabel(f_frame, text=f"{label}:", width=70, font=("Segoe UI", 10, "bold"), text_color="#64748B", anchor="w").pack(side="left")
            ctk.CTkLabel(f_frame, text=str(value or "None"), font=("Segoe UI", 10), text_color=text_color or "#E2E8F0", anchor="w", wraplength=230, justify="left").pack(side="left", fill="x", expand=True)

        add_field(left_card, "Artist", curr.get("artist", "Unknown"))
        add_field(left_card, "Title", curr.get("title", "Unknown"))
        add_field(left_card, "Album", curr.get("album", "Unknown"))
        dur_s = curr.get("duration_s", 0) or 0
        dur_str = f"{int(dur_s // 60)}m {int(dur_s % 60):02d}s" if dur_s else "Unknown"
        add_field(left_card, "Duration", dur_str)
        add_field(left_card, "Year", curr.get("release_year") or curr.get("date") or "Unknown")
        add_field(left_card, "Artwork", "✓ Embedded Artwork" if curr.get("has_cover") else "❌ Missing Artwork", "#4ADE80" if curr.get("has_cover") else "#FB7185")

        right_card = ctk.CTkFrame(grid_frame, fg_color=cfg.get("card_bg", "#0F172A"), corner_radius=10, border_color=badge_color if st != "VERIFIED" else cfg.get("border", "#1E293B"), border_width=1)
        right_card.pack(side="right", fill="both", expand=True, padx=(8, 0))

        lbl_r_title = ctk.CTkLabel(right_card, text="🔬 ACOUSTIC MATCH (SHAZAM)", font=("Segoe UI", 11, "bold"), text_color="#4ADE80" if st == "VERIFIED" else badge_color)
        lbl_r_title.pack(anchor="w", padx=15, pady=(12, 8))

        if rec.get("matched"):
            add_field(right_card, "Artist", rec.get("artist", "Unknown"), "#4ADE80" if res.get("artist_similarity", 0) >= 0.70 else "#FB7185")
            add_field(right_card, "Title", rec.get("title", "Unknown"), "#4ADE80" if res.get("title_similarity", 0) >= 0.65 else "#FB7185")
            add_field(right_card, "Album", rec.get("album", "Unknown"))
            r_dur_ms = rec.get("duration_ms", 0) or 0
            r_dur_s = r_dur_ms / 1000.0
            r_dur_str = f"{int(r_dur_s // 60)}m {int(r_dur_s % 60):02d}s" if r_dur_s else "Unknown"
            add_field(right_card, "Duration", r_dur_str)
            add_field(right_card, "Year", rec.get("year", "Unknown"))
            add_field(right_card, "Confidence", f"Artist: {int(res.get('artist_similarity', 0)*100)}%  •  Title: {int(res.get('title_similarity', 0)*100)}%", "#38BDF8")
        else:
            add_field(right_card, "Status", "No acoustic fingerprint match found", "#94A3B8")
            add_field(right_card, "Note", "Audio may be an unreleased mix, live session, or podcast not in Shazam catalog", "#64748B")

        act_card = ctk.CTkFrame(dialog, fg_color=cfg.get("card_bg", "#0F172A"), corner_radius=10, border_color=cfg.get("border", "#1E293B"), border_width=1)
        act_card.pack(fill="x", padx=20, pady=(10, 20))

        act_inner = ctk.CTkFrame(act_card, fg_color="transparent")
        act_inner.pack(fill="x", padx=15, pady=10)

        btn_dlg_play = ctk.CTkButton(
            act_inner,
            text="▶ Audition 10s Audio",
            font=("Segoe UI", 10, "bold"),
            height=32,
            fg_color="#1E293B",
            hover_color="#334155",
            border_color="#38BDF8",
            border_width=1,
            text_color="#38BDF8"
        )
        btn_dlg_play.configure(command=lambda: self.toggle_verifier_track_preview(track_index, btn_dlg_play))
        btn_dlg_play.pack(side="left", padx=(0, 8))

        btn_dlg_close = ctk.CTkButton(
            act_inner,
            text="✕ Close",
            font=("Segoe UI", 10, "bold"),
            height=32,
            width=80,
            fg_color="#1E293B",
            hover_color="#334155",
            command=_on_dialog_close
        )
        btn_dlg_close.pack(side="right")

        if st in ("COVER_DETECTED", "WRONG_TRACK", "DURATION_MISMATCH", "MISMATCH", "METADATA_TYPO"):
            if rec.get("matched"):
                btn_dlg_fix = ctk.CTkButton(
                    act_inner,
                    text="🏷️ Accept & Retag",
                    font=("Segoe UI", 10, "bold"),
                    height=32,
                    fg_color="#059669",
                    hover_color="#10B981",
                    command=lambda: [self.fix_single_verifier_track(track_index), _on_dialog_close()]
                )
                btn_dlg_fix.pack(side="right", padx=6)

            btn_dlg_keep = ctk.CTkButton(
                act_inner,
                text="✅ Keep Current Tags",
                font=("Segoe UI", 10, "bold"),
                height=32,
                fg_color="#1E293B",
                hover_color="#334155",
                border_color="#34D399",
                border_width=1,
                text_color="#34D399",
                command=lambda: [self.mark_verifier_track_as_verified(track_index), _on_dialog_close()]
            )
            btn_dlg_keep.pack(side="right", padx=6)

            if st in ("COVER_DETECTED", "WRONG_TRACK", "DURATION_MISMATCH"):
                btn_dlg_redl = ctk.CTkButton(
                    act_inner,
                    text="🔄 Re-Download",
                    font=("Segoe UI", 10, "bold"),
                    height=32,
                    fg_color="#028090",
                    hover_color="#00A896",
                    command=lambda: [self.redownload_single_verifier_track(track_index), _on_dialog_close()]
                )
                btn_dlg_redl.pack(side="right", padx=6)

    def mark_verifier_track_as_verified(self, track_index: int):
        """ Marks a mismatched track as VERIFIED (false positive / keep current tags) """
        if track_index >= len(self.verifier_scan_results):
            return
        res = self.verifier_scan_results[track_index]
        res["status"] = "VERIFIED"
        res["discrepancy_reason"] = "Kept current tags (False positive match ignored)"

        file_path = res.get("file_path")
        if file_path and os.path.exists(file_path):
            try:
                cache = AudioFactChecker.load_cache()
                st = os.stat(file_path)
                cache[file_path] = {
                    "mtime": st.st_mtime,
                    "size": st.st_size,
                    "result": res
                }
                AudioFactChecker.save_cache(cache)
            except Exception as e:
                print(f"Error saving marked track to cache: {e}")

        tot = len(self.verifier_scan_results)
        cov = sum(1 for r in self.verifier_scan_results if r.get("status") == "COVER_DETECTED")
        mis = sum(1 for r in self.verifier_scan_results if r.get("status") in ("MISMATCH", "COVER_DETECTED", "WRONG_TRACK", "METADATA_TYPO", "DURATION_MISMATCH"))
        ver = sum(1 for r in self.verifier_scan_results if r.get("status") == "VERIFIED")
        unr = sum(1 for r in self.verifier_scan_results if r.get("status") in ("UNRECOGNIZED", "TIMEOUT", "ERROR"))
        self.update_verifier_stat_counts(tot, mis, cov, ver, unr)
        self.verifier_status_lbl.configure(
            text=f"✓ Kept Current Tags: {res.get('filename')}",
            text_color="#4ADE80"
        )
        self.log(f"[Fact-Checker] Kept current tags for: {res.get('filename')} (marked Verified)")
        self.render_verifier_results()

    def mark_selected_verifier_tracks_as_verified(self):
        """ Marks all selected tracks as VERIFIED (keeps current tags and saves to cache) """
        selected = [item for item in self.verifier_track_items if item["var"].get() == 1]
        if not selected:
            self.verifier_status_lbl.configure(text="No tracks selected. Please check at least one box.", text_color="#FB7185")
            return

        cache = AudioFactChecker.load_cache()
        marked_count = 0
        for item in selected:
            res = item["result"]
            res["status"] = "VERIFIED"
            res["discrepancy_reason"] = "Kept current tags (False positive match ignored)"
            file_path = res.get("file_path")
            if file_path and os.path.exists(file_path):
                try:
                    st = os.stat(file_path)
                    cache[file_path] = {
                        "mtime": st.st_mtime,
                        "size": st.st_size,
                        "result": res
                    }
                    marked_count += 1
                except Exception:
                    pass

        AudioFactChecker.save_cache(cache)

        tot = len(self.verifier_scan_results)
        cov = sum(1 for r in self.verifier_scan_results if r.get("status") == "COVER_DETECTED")
        mis = sum(1 for r in self.verifier_scan_results if r.get("status") in ("MISMATCH", "COVER_DETECTED", "WRONG_TRACK", "METADATA_TYPO", "DURATION_MISMATCH"))
        ver = sum(1 for r in self.verifier_scan_results if r.get("status") == "VERIFIED")
        unr = sum(1 for r in self.verifier_scan_results if r.get("status") in ("UNRECOGNIZED", "TIMEOUT", "ERROR"))
        self.update_verifier_stat_counts(tot, mis, cov, ver, unr)
        self.verifier_status_lbl.configure(
            text=f"✓ Marked {marked_count} tracks as Verified (Current tags kept)",
            text_color="#4ADE80"
        )
        self.log(f"[Fact-Checker] Marked {marked_count} tracks as Verified (Kept current tags in cache).")
        self.render_verifier_results()

    def fix_single_verifier_track(self, track_index: int):
        """ Fixes & re-tags a single mismatched track """
        if track_index >= len(self.verifier_scan_results):
            return

        res = self.verifier_scan_results[track_index]
        dest_root = self.verifier_folder_input.get().strip() or os.path.dirname(res.get("file_path"))
        reorg = bool(self.verifier_reorg_switch.get())

        self.verifier_status_lbl.configure(text=f"Fixing: {res.get('filename')}...", text_color="#00E5FF")

        def run_fix():
            out = AudioFactChecker.fix_and_retag(
                file_path=res.get("file_path"),
                verified_info=res,
                destination_root=dest_root,
                reorganize=reorg,
                progress_cb=lambda m: self.log(f"[Fact-Checker] {m}")
            )
            if out.get("success"):
                res["status"] = "VERIFIED"
                res["file_path"] = out.get("new_path", res.get("file_path"))
                res["discrepancy_reason"] = "Re-tagged with verified acoustic match"
                self.after(0, lambda: self.verifier_status_lbl.configure(
                    text=f"✓ Fixed: {out.get('verified_artist')} - {out.get('verified_title')}",
                    text_color="#4ADE80"
                ))
                self.after(0, self.render_verifier_results)
            else:
                self.after(0, lambda: self.verifier_status_lbl.configure(
                    text=f"✗ Fix Failed: {out.get('error')}",
                    text_color="#FB7185"
                ))

        threading.Thread(target=run_fix, daemon=True).start()

    def autofix_all_discrepancies(self):
        """ Automatically fixes and re-tags all tracks with confirmed audio matches and discrepancies in batch """
        candidates = [
            res for res in self.verifier_scan_results
            if res.get("recognized", {}).get("matched") and res.get("status") in ("METADATA_TYPO", "MISMATCH", "COVER_DETECTED")
        ]
        if not candidates:
            self.verifier_status_lbl.configure(
                text="No unverified tracks with confirmed audio found to auto-fix.",
                text_color="#38BDF8"
            )
            return

        dest_root = self.verifier_folder_input.get().strip()
        reorg = bool(self.verifier_reorg_switch.get())

        if hasattr(self, 'btn_verifier_autofix_all'):
            self.btn_verifier_autofix_all.configure(state="disabled", text="Auto-Fixing All... ⏳")
        self.btn_verifier_fix_selected.configure(state="disabled")
        self.verifier_progress_bar.set(0)
        self.power_light.configure(text="● AUTO-FIXING", text_color="#10B981")

        def run_autofix_worker():
            total = len(candidates)
            fixed_count = 0
            for idx, res in enumerate(candidates, start=1):
                pct = idx / total
                self.after(0, lambda p=pct: self.verifier_progress_bar.set(p))
                self.after(0, lambda i=idx, t=total: self.verifier_counter_lbl.configure(text=f"{i} / {t}"))
                self.after(0, lambda r=res, i=idx, t=total: self.verifier_status_lbl.configure(
                    text=f"Auto-Fixing ({i}/{t}): {r.get('filename')[:40]}",
                    text_color="#38BDF8"
                ))

                out = AudioFactChecker.fix_and_retag(
                    file_path=res.get("file_path"),
                    verified_info=res,
                    destination_root=dest_root,
                    reorganize=reorg,
                    progress_cb=lambda m: self.log(f"[Fact-Checker] {m}")
                )
                if out.get("success"):
                    fixed_count += 1
                    res["status"] = "VERIFIED"
                    res["file_path"] = out.get("new_path", res.get("file_path"))
                    res["filename"] = os.path.basename(res["file_path"])
                    res["discrepancy_reason"] = "Auto-corrected from confirmed acoustic match"

            if hasattr(self, 'btn_verifier_autofix_all'):
                self.after(0, lambda: self.btn_verifier_autofix_all.configure(state="normal", text="⚡  Auto-Fix All Issues"))
            self.after(0, lambda: self.btn_verifier_fix_selected.configure(state="normal"))
            self.after(0, lambda: self.verifier_status_lbl.configure(
                text=f"✓ Complete! {fixed_count} / {total} confirmed tracks auto-corrected.",
                text_color="#4ADE80"
            ))
            self.after(0, lambda: self.update_taskbar_progress(0))
            self.after(0, lambda: self.power_light.configure(
                text=getattr(self, 'theme_cfg', {}).get("status_text", "● READY"),
                text_color=getattr(self, 'theme_cfg', {}).get("status_color", "#38BDF8")
            ))
            self.after(0, self.render_verifier_results)
            self.send_notification("Auto-Fix Complete", f"Successfully auto-corrected {fixed_count} tracks based on confirmed audio fingerprints!")

        threading.Thread(target=run_autofix_worker, daemon=True).start()

    def fix_selected_verifier_tracks(self):
        """ Fixes all selected tracks in batch """
        selected = [item for item in self.verifier_track_items if item["var"].get() == 1]
        if not selected:
            self.verifier_status_lbl.configure(text="No tracks selected to fix. Please check at least one box.", text_color="#FB7185")
            return

        dest_root = self.verifier_folder_input.get().strip()
        reorg = bool(self.verifier_reorg_switch.get())

        self.btn_verifier_fix_selected.configure(state="disabled", text="Fixing & Re-tagging... ⏳")
        self.verifier_progress_bar.set(0)
        self.power_light.configure(text="● FIXING", text_color=getattr(self, 'theme_cfg', {}).get("accent", "#00E5FF"))

        def run_batch_fix():
            total = len(selected)
            fixed_count = 0
            for idx, item in enumerate(selected, start=1):
                res = item["result"]
                pct = idx / total
                self.after(0, lambda p=pct: self.verifier_progress_bar.set(p))
                self.after(0, lambda i=idx, t=total: self.verifier_counter_lbl.configure(text=f"{i} / {t}"))
                self.after(0, lambda r=res: self.verifier_status_lbl.configure(text=f"Fixing ({idx}/{total}): {r.get('filename')[:40]}"))

                out = AudioFactChecker.fix_and_retag(
                    file_path=res.get("file_path"),
                    verified_info=res,
                    destination_root=dest_root,
                    reorganize=reorg,
                    progress_cb=lambda m: self.log(f"[Fact-Checker] {m}")
                )
                if out.get("success"):
                    fixed_count += 1
                    res["status"] = "VERIFIED"
                    res["file_path"] = out.get("new_path", res.get("file_path"))
                    res["discrepancy_reason"] = "Re-tagged with verified acoustic match"

            self.after(0, lambda: self.btn_verifier_fix_selected.configure(state="normal", text="🛠  Fix & Re-tag Selected"))
            self.after(0, lambda: self.verifier_status_lbl.configure(
                text=f"✓ Complete! {fixed_count} / {total} mismatched tracks corrected.",
                text_color="#4ADE80"
            ))
            self.after(0, lambda: self.update_taskbar_progress(0))
            self.after(0, lambda: self.power_light.configure(
                text=getattr(self, 'theme_cfg', {}).get("status_text", "● READY"),
                text_color=getattr(self, 'theme_cfg', {}).get("status_color", "#38BDF8")
            ))
            self.after(0, self.render_verifier_results)
            self.send_notification("Fact-Checker Complete", f"{fixed_count} mismatched songs have been corrected in your library!")

        threading.Thread(target=run_batch_fix, daemon=True).start()

    def redownload_single_verifier_track(self, track_index: int):
        """ Re-downloads authentic studio audio for a track detected as cover or wrong song """
        if track_index >= len(self.verifier_scan_results):
            return

        res = self.verifier_scan_results[track_index]
        curr = res.get("current", {})
        intended_artist = curr.get("artist") or res.get("recognized", {}).get("artist", "")
        intended_title = curr.get("title") or res.get("recognized", {}).get("title", "")
        intended_album = curr.get("album", "")
        file_path = res.get("file_path")
        dest_root = self.verifier_folder_input.get().strip() or os.path.dirname(file_path)
        reorg = bool(self.verifier_reorg_switch.get())

        self.verifier_status_lbl.configure(text=f"Re-downloading authentic audio: {intended_artist} - {intended_title}...", text_color="#00E5FF")

        def run_redl():
            out = AudioFactChecker.redownload_track_audio(
                file_path=file_path,
                intended_artist=intended_artist,
                intended_title=intended_title,
                intended_album=intended_album,
                destination_root=dest_root,
                reorganize=reorg,
                progress_cb=lambda m: self.log(f"[Fact-Checker] {m}")
            )
            if out.get("success"):
                res["status"] = "VERIFIED"
                res["file_path"] = out.get("file_path", file_path)
                res["discrepancy_reason"] = "Authentic studio audio re-downloaded and verified"
                # Update persistent cache
                try:
                    cache = AudioFactChecker.load_cache()
                    st = os.stat(res["file_path"])
                    cache[res["file_path"]] = {"mtime": st.st_mtime, "size": st.st_size, "result": res}
                    AudioFactChecker.save_cache(cache)
                except Exception:
                    pass
                self.after(0, lambda: self.verifier_status_lbl.configure(
                    text=f"✓ Authentic Audio Replaced: {intended_artist} - {intended_title}",
                    text_color="#4ADE80"
                ))
                self.after(0, self.render_verifier_results)
            else:
                self.after(0, lambda: self.verifier_status_lbl.configure(
                    text=f"✗ Re-download failed: {out.get('error')}",
                    text_color="#FB7185"
                ))

        threading.Thread(target=run_redl, daemon=True).start()

    def redownload_selected_verifier_tracks(self):
        """ Re-downloads authentic audio for all selected tracks in batch """
        selected = [item for item in self.verifier_track_items if item["var"].get() == 1]
        if not selected:
            self.verifier_status_lbl.configure(text="No tracks selected. Please check at least one box.", text_color="#FB7185")
            return

        dest_root = self.verifier_folder_input.get().strip()
        reorg = bool(self.verifier_reorg_switch.get())

        if hasattr(self, 'btn_verifier_redownload_selected'):
            self.btn_verifier_redownload_selected.configure(state="disabled", text="Re-Downloading... ⏳")
        self.verifier_progress_bar.set(0)
        self.power_light.configure(text="● DOWNLOADING", text_color=getattr(self, 'theme_cfg', {}).get("accent", "#00E5FF"))

        def run_batch_redl():
            total = len(selected)
            fixed_count = 0
            cache = AudioFactChecker.load_cache()
            for idx, item in enumerate(selected, start=1):
                res = item["result"]
                curr = res.get("current", {})
                intended_artist = curr.get("artist") or res.get("recognized", {}).get("artist", "")
                intended_title = curr.get("title") or res.get("recognized", {}).get("title", "")
                intended_album = curr.get("album", "")
                file_path = res.get("file_path")

                pct = idx / total
                self.after(0, lambda p=pct: self.verifier_progress_bar.set(p))
                self.after(0, lambda i=idx, t=total: self.verifier_counter_lbl.configure(text=f"{i} / {t}"))
                self.after(0, lambda: self.verifier_status_lbl.configure(text=f"Authentic Audio ({idx}/{total}): {intended_title[:35]}"))

                out = AudioFactChecker.redownload_track_audio(
                    file_path=file_path,
                    intended_artist=intended_artist,
                    intended_title=intended_title,
                    intended_album=intended_album,
                    destination_root=dest_root,
                    reorganize=reorg,
                    progress_cb=lambda m: self.log(f"[Fact-Checker] {m}")
                )
                if out.get("success"):
                    fixed_count += 1
                    res["status"] = "VERIFIED"
                    res["file_path"] = out.get("file_path", file_path)
                    res["discrepancy_reason"] = "Authentic studio audio re-downloaded and verified"
                    try:
                        st = os.stat(res["file_path"])
                        cache[res["file_path"]] = {"mtime": st.st_mtime, "size": st.st_size, "result": res}
                    except Exception:
                        pass

            AudioFactChecker.save_cache(cache)
            if hasattr(self, 'btn_verifier_redownload_selected'):
                self.after(0, lambda: self.btn_verifier_redownload_selected.configure(state="normal", text="🔄  Re-Download Real Audio"))
            self.after(0, lambda: self.verifier_status_lbl.configure(
                text=f"✓ Complete! {fixed_count} / {total} tracks replaced with authentic studio audio.",
                text_color="#4ADE80"
            ))
            self.after(0, lambda: self.update_taskbar_progress(0))
            self.after(0, lambda: self.power_light.configure(
                text=getattr(self, 'theme_cfg', {}).get("status_text", "● READY"),
                text_color=getattr(self, 'theme_cfg', {}).get("status_color", "#38BDF8")
            ))
            self.after(0, self.render_verifier_results)
            self.send_notification("Fact-Checker Audio Replacement", f"{fixed_count} songs replaced with authentic studio audio!")

    def quarantine_single_verifier_track(self, track_index: int):
        """ Moves a single track to the _SORT_UNMATCHED quarantine folder """
        if track_index >= len(self.verifier_scan_results):
            return

        res = self.verifier_scan_results[track_index]
        old_path = res.get("file_path")
        dest_root = self.verifier_folder_input.get().strip()
        if not dest_root or not os.path.exists(dest_root):
            dest_root = os.path.dirname(old_path) if old_path else ""

        if not dest_root or not old_path or not os.path.exists(old_path):
            self.verifier_status_lbl.configure(text="Track or destination folder not found.", text_color="#FB7185")
            return

        out = AudioFactChecker.quarantine_file_to_sort(
            file_path=old_path,
            destination_root=dest_root,
            progress_cb=lambda m: self.log(f"[Fact-Checker] {m}")
        )
        if out.get("success"):
            new_path = out.get("new_path")
            res["file_path"] = new_path
            res["status"] = "QUARANTINED"
            res["discrepancy_reason"] = "Isolated in _SORT_UNMATCHED folder (.plexignore)"

            # Update cache
            try:
                cache = AudioFactChecker.load_cache()
                if old_path in cache:
                    del cache[old_path]
                if os.path.exists(new_path):
                    st = os.stat(new_path)
                    cache[new_path] = {
                        "mtime": st.st_mtime,
                        "size": st.st_size,
                        "result": res
                    }
                AudioFactChecker.save_cache(cache)
            except Exception as e:
                print(f"Error updating cache after quarantine: {e}")

            tot = len(self.verifier_scan_results)
            cov = sum(1 for r in self.verifier_scan_results if r.get("status") == "COVER_DETECTED")
            mis = sum(1 for r in self.verifier_scan_results if r.get("status") in ("MISMATCH", "COVER_DETECTED", "WRONG_TRACK", "METADATA_TYPO", "DURATION_MISMATCH"))
            ver = sum(1 for r in self.verifier_scan_results if r.get("status") == "VERIFIED")
            unr = sum(1 for r in self.verifier_scan_results if r.get("status") in ("UNRECOGNIZED", "TIMEOUT", "ERROR"))
            self.update_verifier_stat_counts(tot, mis, cov, ver, unr)

            self.verifier_status_lbl.configure(
                text=f"📦 Quarantined: {os.path.basename(new_path)} -> _SORT_UNMATCHED",
                text_color="#FB923C"
            )
            self.log(f"[Fact-Checker] Quarantined {os.path.basename(old_path)} to {out.get('quarantine_dir')}")
            self.render_verifier_results()
        else:
            self.verifier_status_lbl.configure(
                text=f"✗ Quarantine Failed: {out.get('error')}",
                text_color="#FB7185"
            )

    def move_selected_verifier_tracks_to_sort(self):
        """ Moves all selected tracks into _SORT_UNMATCHED quarantine folder """
        selected = [item for item in self.verifier_track_items if item["var"].get() == 1]
        if not selected:
            self.verifier_status_lbl.configure(text="No tracks selected. Please check at least one box.", text_color="#FB7185")
            return

        dest_root = self.verifier_folder_input.get().strip()
        if not dest_root or not os.path.exists(dest_root):
            first_path = selected[0]["result"].get("file_path", "")
            dest_root = os.path.dirname(first_path) if first_path else ""

        if not dest_root:
            self.verifier_status_lbl.configure(text="Invalid destination folder path.", text_color="#FB7185")
            return

        if hasattr(self, 'btn_verifier_move_to_sort'):
            self.btn_verifier_move_to_sort.configure(state="disabled", text="Quarantining... ⏳")
        self.verifier_progress_bar.set(0)

        def run_batch_quarantine():
            total = len(selected)
            moved_count = 0
            cache = AudioFactChecker.load_cache()

            for i, item in enumerate(selected):
                res = item["result"]
                old_path = res.get("file_path")
                if not old_path or not os.path.exists(old_path):
                    continue

                self.after(0, lambda fn=os.path.basename(old_path), idx=i+1, tot=total: self.verifier_status_lbl.configure(
                    text=f"Quarantining [{idx}/{tot}]: {fn}...",
                    text_color="#FB923C"
                ))
                self.after(0, lambda p=(i + 1) / total: self.verifier_progress_bar.set(p))

                out = AudioFactChecker.quarantine_file_to_sort(
                    file_path=old_path,
                    destination_root=dest_root,
                    progress_cb=lambda m: self.log(f"[Fact-Checker] {m}")
                )
                if out.get("success"):
                    moved_count += 1
                    new_path = out.get("new_path")
                    res["file_path"] = new_path
                    res["status"] = "QUARANTINED"
                    res["discrepancy_reason"] = "Isolated in _SORT_UNMATCHED folder (.plexignore)"
                    if old_path in cache:
                        del cache[old_path]
                    if os.path.exists(new_path):
                        try:
                            st = os.stat(new_path)
                            cache[new_path] = {
                                "mtime": st.st_mtime,
                                "size": st.st_size,
                                "result": res
                            }
                        except Exception:
                            pass

            try:
                AudioFactChecker.save_cache(cache)
            except Exception:
                pass

            tot = len(self.verifier_scan_results)
            cov = sum(1 for r in self.verifier_scan_results if r.get("status") == "COVER_DETECTED")
            mis = sum(1 for r in self.verifier_scan_results if r.get("status") in ("MISMATCH", "COVER_DETECTED", "WRONG_TRACK", "METADATA_TYPO", "DURATION_MISMATCH"))
            ver = sum(1 for r in self.verifier_scan_results if r.get("status") == "VERIFIED")
            unr = sum(1 for r in self.verifier_scan_results if r.get("status") in ("UNRECOGNIZED", "TIMEOUT", "ERROR"))

            def on_done():
                if hasattr(self, 'btn_verifier_move_to_sort'):
                    self.btn_verifier_move_to_sort.configure(
                        state="normal",
                        text="📦 Move to _SORT"
                    )
                self.update_verifier_stat_counts(tot, mis, cov, ver, unr)
                self.verifier_progress_bar.set(1.0)
                self.verifier_status_lbl.configure(
                    text=f"✓ Quarantined {moved_count} tracks into _SORT_UNMATCHED folder!",
                    text_color="#4ADE80"
                )
                self.render_verifier_results()
                self.send_notification("Fact-Checker Quarantine", f"{moved_count} tracks quarantined to _SORT_UNMATCHED folder!")

            self.after(0, on_done)

        threading.Thread(target=run_batch_quarantine, daemon=True).start()

    def export_verifier_report(self):
        """ Exports report to desktop or file dialog """
        if not self.verifier_scan_results:
            self.verifier_status_lbl.configure(text="No results to export. Run a scan first.", text_color="#FB7185")
            return

        from tkinter import filedialog
        file_path = filedialog.asksaveasfilename(
            title="Export Fact-Check Report",
            defaultextension=".txt",
            filetypes=[("Text Report", "*.txt"), ("CSV File", "*.csv"), ("JSON File", "*.json")]
        )
        if file_path:
            fmt = "txt"
            if file_path.endswith(".csv"):
                fmt = "csv"
            elif file_path.endswith(".json"):
                fmt = "json"

            AudioFactChecker.export_report(self.verifier_scan_results, file_path, fmt=fmt)
            self.verifier_status_lbl.configure(text=f"Report exported to: {os.path.basename(file_path)}", text_color="#4ADE80")
            self.log(f"Fact-check report exported to: {file_path}")

    def open_fact_checker_error_log(self):
        """ Opens the trackable fact_checker_errors.log file in default text editor """
        log_file = os.path.join(base_dir, "fact_checker_errors.log")
        if not os.path.exists(log_file):
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Fact-Checker error log initialized. No errors recorded yet.\n")
        try:
            os.startfile(log_file)
        except Exception:
            subprocess.Popen(["notepad.exe", log_file])

