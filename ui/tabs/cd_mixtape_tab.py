"""
CD Mixtape Builder Tab Mixin for Shallot Media Archive.
Handles 700MB/80min knapsack packing algorithms, track flow optimization,
capacity visualizers, volume leveling, and burning-ready audio exports.
"""

import os
import sys
import time
import json
import shutil
import threading
import subprocess
from typing import List, Dict, Optional
from PIL import Image
import customtkinter as ctk

from core import CToolTip
from cd_mixtape import CDMixtapePlanner, CDMixtapeExporter, LocalLibraryIndex, SpotifyRecommender, CAPACITY_PRESETS


class CDMixtapeTabMixin:
    """Mixin containing GUI layout and controller methods for CD Mixtape Builder tab."""

    def build_cd_mixtape_page(self, parent):
        # =========================================================================
        # --- Page: CD Mixtape Builder ---
        # =========================================================================
        self.cd_mixtape_page = ctk.CTkFrame(parent, fg_color="transparent")

        lbl_p_cd = ctk.CTkLabel(self.cd_mixtape_page, text="💿 CD Mixtape & 700MB Burn Prep", font=("Segoe UI", 18, "bold"), anchor="w")
        lbl_p_cd.pack(fill="x", padx=20, pady=(15, 6))
        self.page_titles.append(lbl_p_cd)

        # Card 1: Source Library & Seed Artist Card
        self.cd_source_card = ctk.CTkFrame(self.cd_mixtape_page, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.cd_source_card.pack(fill="x", padx=20, pady=3)

        cd_card1_lbl = ctk.CTkLabel(self.cd_source_card, text="LIBRARY SOURCE & SEED ARTIST", font=("Segoe UI", 11, "bold"), text_color="#00E5FF")
        cd_card1_lbl.pack(anchor="w", padx=15, pady=(8, 2))
        self.theme_titles.append(cd_card1_lbl)

        # Row 1: Source Music Folder
        lbl_cd_src = ctk.CTkLabel(self.cd_source_card, text="MUSIC LIBRARY FOLDER (SCAN SOURCE)", font=("Segoe UI", 9, "bold"), text_color="#78909C")
        lbl_cd_src.pack(anchor="w", padx=15, pady=(1, 0))
        self.theme_labels_secondary.append(lbl_cd_src)

        cd_src_frame = ctk.CTkFrame(self.cd_source_card, fg_color="transparent")
        cd_src_frame.pack(fill="x", padx=15, pady=(1, 3))

        self.cd_library_folder_input = ctk.CTkEntry(
            cd_src_frame,
            placeholder_text="e.g. D:\\Music or C:\\SMA-downloads\\Music...",
            height=30,
            fg_color="#070F15",
            border_color="#1F3A4E",
            text_color="#F5F5F7"
        )
        saved_cd_lib = self.saved_settings.get("plex_music_folder", "") or self.saved_settings.get("destination_folder", "") or r"C:\SMA-downloads\Music"
        self.cd_library_folder_input.insert(0, saved_cd_lib)
        self.cd_library_folder_input.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.cd_library_folder_input.bind("<Return>", lambda e: self._on_cd_library_return())
        self.theme_entries.append(self.cd_library_folder_input)
        CToolTip(self.cd_library_folder_input, "Source music folder containing MP3/FLAC tracks to draw from for mixtape creation.")

        self.btn_cd_browse_lib = ctk.CTkButton(
            cd_src_frame,
            text="📂 Browse",
            width=75,
            height=30,
            font=("Segoe UI", 10, "bold"),
            command=self.browse_cd_library_folder
        )
        self.btn_cd_browse_lib.pack(side="left", padx=(0, 6))
        self.theme_buttons_secondary.append(self.btn_cd_browse_lib)

        self.btn_cd_scan_lib = ctk.CTkButton(
            cd_src_frame,
            text="⚡ Scan Library",
            width=95,
            height=30,
            font=("Segoe UI", 10, "bold"),
            command=self.scan_cd_library_artists
        )
        self.btn_cd_scan_lib.pack(side="right")
        self.theme_buttons_secondary.append(self.btn_cd_scan_lib)

        # Row 2: Seed Artist Selection & Stats
        cd_seed_row = ctk.CTkFrame(self.cd_source_card, fg_color="transparent")
        cd_seed_row.pack(fill="x", padx=15, pady=(1, 3))

        cd_seed_left = ctk.CTkFrame(cd_seed_row, fg_color="transparent")
        cd_seed_left.pack(side="left", fill="x", expand=True, padx=(0, 6))

        lbl_cd_seed = ctk.CTkLabel(cd_seed_left, text="SEED ARTIST (OR SELECT FULL LIBRARY CHAOS)", font=("Segoe UI", 9, "bold"), text_color="#78909C")
        lbl_cd_seed.pack(anchor="w", pady=(0, 1))
        self.theme_labels_secondary.append(lbl_cd_seed)

        cd_seed_input_box = ctk.CTkFrame(cd_seed_left, fg_color="transparent")
        cd_seed_input_box.pack(fill="x")

        self.cd_seed_artist_cb = ctk.CTkComboBox(
            cd_seed_input_box,
            values=["🎲 Full Library Chaos (Random Gamble)", "Glass Animals", "Select or Type Artist..."],
            height=30,
            font=("Segoe UI", 11),
            fg_color="#070F15",
            border_color="#1F3A4E",
            text_color="#F5F5F7",
            dropdown_fg_color="#151B26"
        )
        self.cd_seed_artist_cb.set("🎲 Full Library Chaos (Random Gamble)")
        self.cd_seed_artist_cb.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.theme_option_menus.append(self.cd_seed_artist_cb)

        self.btn_cd_roll_artist = ctk.CTkButton(
            cd_seed_input_box,
            text="🎲 Roll Artist",
            width=90,
            height=30,
            font=("Segoe UI", 10, "bold"),
            command=self.roll_random_cd_artist
        )
        self.btn_cd_roll_artist.pack(side="right")
        self.theme_buttons_secondary.append(self.btn_cd_roll_artist)

        cd_seed_right = ctk.CTkFrame(cd_seed_row, fg_color="transparent")
        cd_seed_right.pack(side="right", fill="x", expand=True)

        lbl_cd_out = ctk.CTkLabel(cd_seed_right, text="CD BURN DESTINATION DIRECTORY", font=("Segoe UI", 9, "bold"), text_color="#78909C")
        lbl_cd_out.pack(anchor="w", pady=(0, 1))
        self.theme_labels_secondary.append(lbl_cd_out)

        cd_out_box = ctk.CTkFrame(cd_seed_right, fg_color="transparent")
        cd_out_box.pack(fill="x")

        self.cd_output_folder_input = ctk.CTkEntry(
            cd_out_box,
            placeholder_text=r"C:\SMA-downloads\CD_Mixtapes",
            height=30,
            fg_color="#070F15",
            border_color="#1F3A4E",
            text_color="#F5F5F7"
        )
        saved_cd_out = self.saved_settings.get("cd_output_folder", "") or r"C:\SMA-downloads\CD_Mixtapes"
        self.cd_output_folder_input.insert(0, saved_cd_out)
        self.cd_output_folder_input.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.theme_entries.append(self.cd_output_folder_input)

        self.btn_cd_browse_out = ctk.CTkButton(
            cd_out_box,
            text="📂 Browse",
            width=75,
            height=30,
            font=("Segoe UI", 10, "bold"),
            command=self.browse_cd_output_folder
        )
        self.btn_cd_browse_out.pack(side="right")
        self.theme_buttons_secondary.append(self.btn_cd_browse_out)

        self.cd_library_stats_lbl = ctk.CTkLabel(
            self.cd_source_card,
            text="Click 'Scan Library' to index available artists from your music folder.",
            font=("Segoe UI", 9),
            text_color="#94A3B8",
            anchor="w"
        )
        self.cd_library_stats_lbl.pack(fill="x", padx=15, pady=(1, 6))

        # Card 2: Packing Options & Capacity Configuration
        self.cd_settings_card = ctk.CTkFrame(self.cd_mixtape_page, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.cd_settings_card.pack(fill="x", padx=20, pady=3)

        cd_card2_lbl = ctk.CTkLabel(self.cd_settings_card, text="CAPACITY & VIBE PACKING OPTIONS", font=("Segoe UI", 11, "bold"), text_color="#00E5FF")
        cd_card2_lbl.pack(anchor="w", padx=15, pady=(8, 2))
        self.theme_titles.append(cd_card2_lbl)

        cd_grid = ctk.CTkFrame(self.cd_settings_card, fg_color="transparent")
        cd_grid.pack(fill="x", padx=15, pady=(1, 6))
        cd_grid.columnconfigure(0, weight=1)
        cd_grid.columnconfigure(1, weight=1)
        cd_grid.columnconfigure(2, weight=1)
        cd_grid.columnconfigure(3, weight=1)

        # Row 0, Col 0: Disc Preset
        f_cap = ctk.CTkFrame(cd_grid, fg_color="transparent")
        f_cap.grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=(0, 4))
        lbl_cap = ctk.CTkLabel(f_cap, text="Target Disc Media", font=("Segoe UI", 9, "bold"), text_color="#78909C")
        lbl_cap.pack(anchor="w")
        self.theme_labels_secondary.append(lbl_cap)
        self.cd_preset_menu = ctk.CTkOptionMenu(
            f_cap,
            values=[
                "700 MB Data CD (MP3 / M4A)",
                "650 MB Data CD",
                "800 MB Data CD",
                "80-Minute Standard Audio CD (Red Book)",
                "74-Minute Audio CD"
            ],
            height=28,
            font=("Segoe UI", 10)
        )
        self.cd_preset_menu.pack(fill="x", pady=(1, 0))
        self.theme_option_menus.append(self.cd_preset_menu)
        CToolTip(self.cd_preset_menu, "Target media preset. Uses knapsack optimization to fill standard 700MB Data CDs or 80-minute Red Book Audio CDs to maximum capacity.")
        CToolTip(lbl_cap, "Target media preset. Uses knapsack optimization to fill standard 700MB Data CDs or 80-minute Red Book Audio CDs to maximum capacity.")

        # Row 0, Col 1: Seed Track Count
        f_seed_cnt = ctk.CTkFrame(cd_grid, fg_color="transparent")
        f_seed_cnt.grid(row=0, column=1, sticky="ew", padx=(0, 6), pady=(0, 4))
        lbl_scnt = ctk.CTkLabel(f_seed_cnt, text="Seed Artist Hits (Max)", font=("Segoe UI", 9, "bold"), text_color="#78909C")
        lbl_scnt.pack(anchor="w")
        self.theme_labels_secondary.append(lbl_scnt)
        self.cd_seed_count_menu = ctk.CTkOptionMenu(
            f_seed_cnt,
            values=[
                "Top 20 Hits (Max)",
                "Top 15 Hits (Max)",
                "Top 10 Hits (Max)",
                "Top 25 Hits (Max)",
                "Top 30 Hits (Max)",
                "All Available Hits"
            ],
            height=28,
            font=("Segoe UI", 10)
        )
        self.cd_seed_count_menu.pack(fill="x", pady=(1, 0))
        self.theme_option_menus.append(self.cd_seed_count_menu)

        # Row 0, Col 2: Max Tracks Per Vibe Artist
        f_vibe_max = ctk.CTkFrame(cd_grid, fg_color="transparent")
        f_vibe_max.grid(row=0, column=2, sticky="ew", padx=(0, 6), pady=(0, 4))
        lbl_vmax = ctk.CTkLabel(f_vibe_max, text="Max Per Vibe Artist", font=("Segoe UI", 9, "bold"), text_color="#78909C")
        lbl_vmax.pack(anchor="w")
        self.theme_labels_secondary.append(lbl_vmax)
        self.cd_max_vibe_menu = ctk.CTkOptionMenu(
            f_vibe_max,
            values=[
                "3 Tracks (Default)",
                "1 Track (Max Variety)",
                "2 Tracks",
                "4 Tracks",
                "5 Tracks",
                "No Limit"
            ],
            height=28,
            font=("Segoe UI", 10)
        )
        self.cd_max_vibe_menu.pack(fill="x", pady=(1, 0))
        self.theme_option_menus.append(self.cd_max_vibe_menu)
        CToolTip(self.cd_max_vibe_menu, "Limits maximum tracks selected per related recommendation artist to guarantee diverse, non-repetitive mixtapes.")
        CToolTip(lbl_vmax, "Limits maximum tracks selected per related recommendation artist to guarantee diverse, non-repetitive mixtapes.")

        # Row 0, Col 3: Max Track Duration (Anti-Bloat Filter)
        f_dur_max = ctk.CTkFrame(cd_grid, fg_color="transparent")
        f_dur_max.grid(row=0, column=3, sticky="ew", pady=(0, 4))
        lbl_dmax = ctk.CTkLabel(f_dur_max, text="Max Song Length", font=("Segoe UI", 9, "bold"), text_color="#78909C")
        lbl_dmax.pack(anchor="w")
        self.theme_labels_secondary.append(lbl_dmax)
        self.cd_max_dur_menu = ctk.CTkOptionMenu(
            f_dur_max,
            values=[
                "4:30 (Max Single - No Bloat)",
                "4:00 (Radio Fast)",
                "5:00 (Standard)",
                "6:00 (Extended)",
                "No Limit"
            ],
            height=28,
            font=("Segoe UI", 10)
        )
        self.cd_max_dur_menu.pack(fill="x", pady=(1, 0))
        self.theme_option_menus.append(self.cd_max_dur_menu)
        CToolTip(self.cd_max_dur_menu, "Filters out lengthy mixes, podcasts, or live jams longer than this threshold to preserve disc capacity.")
        CToolTip(lbl_dmax, "Filters out lengthy mixes, podcasts, or live jams longer than this threshold to preserve disc capacity.")

        # Row 1, Col 0: Compression / Squeeze Mode
        f_squeeze = ctk.CTkFrame(cd_grid, fg_color="transparent")
        f_squeeze.grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=(3, 0))
        lbl_sqz = ctk.CTkLabel(f_squeeze, text="Compression / Squeeze Mode", font=("Segoe UI", 9, "bold"), text_color="#78909C")
        lbl_sqz.pack(anchor="w")
        self.theme_labels_secondary.append(lbl_sqz)
        self.cd_squeeze_mode_menu = ctk.CTkOptionMenu(
            f_squeeze,
            values=[
                "Squeeze All Tracks (Fit Max Songs on Disc)",
                "Only Squeeze FLAC / Lossless to MP3",
                "Original Files (No Compression)"
            ],
            height=28,
            font=("Segoe UI", 10)
        )
        self.cd_squeeze_mode_menu.pack(fill="x", pady=(1, 0))
        self.theme_option_menus.append(self.cd_squeeze_mode_menu)
        CToolTip(self.cd_squeeze_mode_menu, "Lossless Squeeze intelligently encodes FLAC/lossless files to high-efficiency MP3 while leaving standard MP3s untouched, optimizing disc space without unnecessary re-encoding.")
        CToolTip(lbl_sqz, "Lossless Squeeze intelligently encodes FLAC/lossless files to high-efficiency MP3 while leaving standard MP3s untouched, optimizing disc space without unnecessary re-encoding.")

        # Row 1, Col 1: Target MP3 Bitrate
        f_trans = ctk.CTkFrame(cd_grid, fg_color="transparent")
        f_trans.grid(row=1, column=1, sticky="ew", padx=(0, 6), pady=(3, 0))
        lbl_trans = ctk.CTkLabel(f_trans, text="Target MP3 Bitrate", font=("Segoe UI", 9, "bold"), text_color="#78909C")
        lbl_trans.pack(anchor="w")
        self.theme_labels_secondary.append(lbl_trans)
        self.cd_bitrate_menu = ctk.CTkOptionMenu(
            f_trans,
            values=[
                "256 kbps (Car Stereo - ~105 Songs)",
                "192 kbps (High Squeeze - ~140 Songs)",
                "160 kbps (Super Squeeze - ~165 Songs)",
                "128 kbps (Max Squeeze - ~200+ Songs)",
                "320 kbps (High Quality - ~80 Songs)"
            ],
            height=28,
            font=("Segoe UI", 10)
        )
        self.cd_bitrate_menu.pack(fill="x", pady=(1, 0))
        self.theme_option_menus.append(self.cd_bitrate_menu)
        CToolTip(self.cd_bitrate_menu, "Target MP3 Bitrate: 256 kbps is the sweet spot for car stereos; 192 kbps allows fitting up to 140 songs on a 700MB CD with high perceptual quality.")
        CToolTip(lbl_trans, "Target MP3 Bitrate: 256 kbps is the sweet spot for car stereos; 192 kbps allows fitting up to 140 songs on a 700MB CD with high perceptual quality.")

        # Row 1, Col 2: Audio Normalization
        f_norm = ctk.CTkFrame(cd_grid, fg_color="transparent")
        f_norm.grid(row=1, column=2, sticky="ew", padx=(0, 6), pady=(3, 0))
        lbl_norm = ctk.CTkLabel(f_norm, text="Audio Normalization", font=("Segoe UI", 9, "bold"), text_color="#78909C")
        lbl_norm.pack(anchor="w")
        self.theme_labels_secondary.append(lbl_norm)
        self.cd_normalization_menu = ctk.CTkOptionMenu(
            f_norm,
            values=[
                "EBU R128 (-14 LUFS - Balanced)",
                "Car HiFi (-16 LUFS - Dynamic)",
                "Off (Original File Volumes)"
            ],
            height=28,
            font=("Segoe UI", 10),
            command=lambda v: self.save_setting("cd_audio_normalization", v)
        )
        CToolTip(self.cd_normalization_menu, "EBU R128 loudness leveling analyzes full acoustic dynamic range and balances volume across varied sources to avoid sudden volume jumps.")
        CToolTip(lbl_norm, "EBU R128 loudness leveling analyzes full acoustic dynamic range and balances volume across varied sources to avoid sudden volume jumps.")
        saved_norm = self.saved_settings.get("cd_audio_normalization", "EBU R128 (-14 LUFS - Balanced)")
        if saved_norm in self.cd_normalization_menu._values:
            self.cd_normalization_menu.set(saved_norm)
        else:
            self.cd_normalization_menu.set("EBU R128 (-14 LUFS - Balanced)")
        self.cd_normalization_menu.pack(fill="x", pady=(1, 0))
        self.theme_option_menus.append(self.cd_normalization_menu)

        # Row 1, Col 3: Track Ordering & Mix Flow
        f_style = ctk.CTkFrame(cd_grid, fg_color="transparent")
        f_style.grid(row=1, column=3, sticky="ew", pady=(3, 0))
        lbl_style = ctk.CTkLabel(f_style, text="Mixtape Flow & Sequencing", font=("Segoe UI", 9, "bold"), text_color="#78909C")
        lbl_style.pack(anchor="w")
        self.theme_labels_secondary.append(lbl_style)
        self.cd_mix_style_menu = ctk.CTkOptionMenu(
            f_style,
            values=[
                "🎲 Chaos Shuffle (Radio Mix)",
                "🌱 Seed Intro + Shuffled Vibes",
                "📁 Grouped by Artist & Role"
            ],
            height=28,
            font=("Segoe UI", 10)
        )
        self.cd_mix_style_menu.pack(fill="x", pady=(1, 0))
        self.theme_option_menus.append(self.cd_mix_style_menu)

        # Row 2: Generate Button
        f_btn_box = ctk.CTkFrame(cd_grid, fg_color="transparent")
        f_btn_box.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8, 2))

        self.btn_cd_generate = ctk.CTkButton(
            f_btn_box,
            text="⚡ Generate & Pack Mixtape",
            font=("Segoe UI", 11, "bold"),
            height=30,
            corner_radius=6,
            command=self.start_cd_mixtape_generation
        )
        self.btn_cd_generate.pack(fill="x")

        # Card 3: Capacity Visualizer & Statistics Card
        self.cd_stats_card = ctk.CTkFrame(self.cd_mixtape_page, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.cd_stats_card.pack(fill="x", padx=20, pady=3)

        cd_stats_header = ctk.CTkFrame(self.cd_stats_card, fg_color="transparent")
        cd_stats_header.pack(fill="x", padx=15, pady=(8, 4))

        self.cd_capacity_lbl = ctk.CTkLabel(
            cd_stats_header,
            text="💿 Audio CD Capacity: 0.0 MB / 700.0 MB (0.0% Full)",
            font=("Segoe UI", 11, "bold"),
            text_color="#38BDF8",
            anchor="w"
        )
        self.cd_capacity_lbl.pack(side="left")
        self.theme_titles.append(self.cd_capacity_lbl)

        self.cd_track_count_lbl = ctk.CTkLabel(
            cd_stats_header,
            text="0 Tracks  •  0m 00s Total Playback",
            font=("Segoe UI", 10, "bold"),
            text_color="#F5F5F7",
            anchor="e"
        )
        self.cd_track_count_lbl.pack(side="right")

        self.cd_capacity_bar = ctk.CTkProgressBar(
            self.cd_stats_card,
            height=12,
            corner_radius=6,
            progress_color="#38BDF8",
            fg_color="#090E17"
        )
        self.cd_capacity_bar.set(0)
        self.cd_capacity_bar.pack(fill="x", padx=15, pady=(4, 6))

        self.cd_breakdown_lbl = ctk.CTkLabel(
            self.cd_stats_card,
            text="Seed: 0 tracks  •  Vibe: 0 tracks  •  Filler: 0 tracks",
            font=("Segoe UI", 10),
            text_color="#94A3B8",
            anchor="w"
        )
        self.cd_breakdown_lbl.pack(fill="x", padx=15, pady=(0, 8))

        # Card 4: Mixtape Track Preview List
        self.cd_tracks_card = ctk.CTkFrame(self.cd_mixtape_page, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.cd_tracks_card.pack(fill="both", expand=True, padx=20, pady=3)

        cd_t_hdr = ctk.CTkFrame(self.cd_tracks_card, fg_color="transparent")
        cd_t_hdr.pack(fill="x", padx=15, pady=(6, 2))

        cd_t_title = ctk.CTkLabel(cd_t_hdr, text="MIXTAPE TRACKLIST PREVIEW", font=("Segoe UI", 11, "bold"), text_color="#00E5FF")
        cd_t_title.pack(side="left")
        self.theme_titles.append(cd_t_title)

        self.cd_tracks_scroll = ctk.CTkScrollableFrame(self.cd_tracks_card, fg_color="transparent", corner_radius=8)
        self.cd_tracks_scroll.pack(fill="both", expand=True, padx=10, pady=(2, 6))

        # Card 5: Export & Action Card
        self.cd_action_card = ctk.CTkFrame(self.cd_mixtape_page, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.cd_action_card.pack(fill="x", padx=20, pady=(3, 10))

        cd_act_top = ctk.CTkFrame(self.cd_action_card, fg_color="transparent")
        cd_act_top.pack(fill="x", padx=15, pady=(6, 2))

        self.cd_export_status_lbl = ctk.CTkLabel(
            cd_act_top,
            text="Ready. Select an artist and click 'Generate & Pack Mixtape'.",
            font=("Segoe UI", 10),
            text_color="#94A3B8",
            anchor="w"
        )
        self.cd_export_status_lbl.pack(side="left")
        self.theme_labels_secondary.append(self.cd_export_status_lbl)

        self.cd_export_counter_lbl = ctk.CTkLabel(
            cd_act_top,
            text="0 / 0",
            font=("Segoe UI", 10, "bold"),
            text_color="#F5F5F7",
            anchor="e"
        )
        self.cd_export_counter_lbl.pack(side="right")

        self.cd_export_progress_bar = ctk.CTkProgressBar(
            self.cd_action_card,
            height=6,
            corner_radius=3,
            progress_color="#00E5FF",
            fg_color="#070F15"
        )
        self.cd_export_progress_bar.set(0)
        self.cd_export_progress_bar.pack(fill="x", padx=15, pady=(2, 4))

        cd_act_btns = ctk.CTkFrame(self.cd_action_card, fg_color="transparent")
        cd_act_btns.pack(fill="x", padx=15, pady=(2, 8))

        self.btn_cd_export = ctk.CTkButton(
            cd_act_btns,
            text="🚀  Copy & Export CD Burn Folder",
            font=("Segoe UI", 11, "bold"),
            height=34,
            corner_radius=8,
            command=self.start_cd_export
        )
        self.btn_cd_export.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.btn_cd_cancel = ctk.CTkButton(
            cd_act_btns,
            text="⏹ Cancel",
            width=85,
            height=34,
            font=("Segoe UI", 10, "bold"),
            fg_color="#3B1214",
            hover_color="#5C1D20",
            border_color="#F43F5E",
            border_width=1,
            text_color="#F43F5E",
            command=self.cancel_cd_operation
        )
        self.btn_cd_cancel.pack(side="left", padx=(0, 6))

        self.btn_cd_open_folder = ctk.CTkButton(
            cd_act_btns,
            text="📂 Open CD Folder",
            font=("Segoe UI", 11, "bold"),
            height=34,
            width=140,
            corner_radius=8,
            fg_color="#0E1A24",
            border_color="#00E5FF",
            border_width=1,
            text_color="#00E5FF",
            command=self.open_cd_output_folder
        )
        self.btn_cd_open_folder.pack(side="right")
        self.theme_buttons_secondary.append(self.btn_cd_open_folder)


    def _on_cd_library_return(self, event=None):
        text = self.cd_library_folder_input.get().strip()
        if not text:
            return
        if self.dispatch_smart_input(text, source_tab="cd_mixtape"):
            return
        self.scan_cd_library_artists()

    def scan_cd_library(self):
        return self.scan_cd_library_artists()
    # --- CD Mixtape Builder Logic & Workers ---
    # =========================================================================

    def browse_cd_library_folder(self):
        from tkinter import filedialog
        folder = filedialog.askdirectory(title="Select Local Music Library Folder")
        if folder:
            self.cd_library_folder_input.delete(0, "end")
            self.cd_library_folder_input.insert(0, folder)
            self.save_setting("plex_music_folder", folder)

    def browse_cd_output_folder(self):
        from tkinter import filedialog
        folder = filedialog.askdirectory(title="Select Destination Folder for CD Burn Mixtapes")
        if folder:
            self.cd_output_folder_input.delete(0, "end")
            self.cd_output_folder_input.insert(0, folder)
            self.save_setting("cd_output_folder", folder)

    def open_cd_output_folder(self):
        folder = self.cd_output_folder_input.get().strip() or r"C:\SMA-downloads\CD_Mixtapes"
        if not os.path.exists(folder):
            try:
                os.makedirs(folder, exist_ok=True)
            except Exception:
                pass
        try:
            os.startfile(folder)
        except Exception:
            subprocess.Popen(["explorer", folder])

    def scan_cd_library_artists(self):
        """Scans the music folder in background and extracts all artists for quick selection."""
        folder = self.cd_library_folder_input.get().strip()
        if not folder or not os.path.exists(folder):
            self.cd_library_stats_lbl.configure(text="Invalid folder path. Please select a valid folder.", text_color="#FB7185")
            return

        self.btn_cd_scan_lib.configure(state="disabled", text="Scanning...")
        self.cd_library_stats_lbl.configure(text="Scanning music library for audio files and tags...", text_color="#38BDF8")

        def run_scan():
            try:
                idx = LocalLibraryIndex(folder)
                count = idx.scan(
                    progress_callback=lambda cur, tot, name: self.after(
                        0, lambda c=cur, t=tot: self.cd_library_stats_lbl.configure(text=f"Scanning audio files: {c} / {t}...")
                    )
                )
                self.cd_library_index = idx
                artists = idx.all_artists
                self.after(0, lambda: self._on_cd_library_scanned_success(count, artists))
            except Exception as e:
                self.after(0, lambda err=str(e): self._on_cd_library_scanned_error(err))

        threading.Thread(target=run_scan, daemon=True).start()

    def roll_random_cd_artist(self):
        """Picks a random artist from the indexed library for instant chaos/gamble fun."""
        import random
        if hasattr(self, 'cd_library_index') and self.cd_library_index and self.cd_library_index.all_artists:
            rand_art = random.choice(self.cd_library_index.all_artists)
            self.cd_seed_artist_cb.set(rand_art)
            self.cd_export_status_lbl.configure(text=f"🎲 Rolled surprise artist: {rand_art}", text_color="#38BDF8")
        else:
            self.cd_seed_artist_cb.set("🎲 Full Library Chaos (Random Gamble)")
            self.cd_export_status_lbl.configure(text="🎲 Set to Full Library Chaos Mode. Click 'Scan Library' to index specific artists.", text_color="#38BDF8")

    def _on_cd_library_scanned_success(self, count: int, artists: List[str]):
        self.btn_cd_scan_lib.configure(state="normal", text="⚡ Scan Library")
        artist_cnt = len(artists)
        self.cd_library_stats_lbl.configure(
            text=f"✓ Indexed {count:,} tracks across {artist_cnt:,} artists in local library.",
            text_color="#4ADE80"
        )
        if artists:
            artist_options = ["🎲 Full Library Chaos (Random Gamble)"] + artists
            self.cd_seed_artist_cb.configure(values=artist_options)
            curr = self.cd_seed_artist_cb.get().strip()
            if not curr or curr == "Select or Type Artist..." or curr == "Glass Animals":
                self.cd_seed_artist_cb.set("🎲 Full Library Chaos (Random Gamble)")

    def _on_cd_library_scanned_error(self, err_msg: str):
        self.btn_cd_scan_lib.configure(state="normal", text="⚡ Scan Library")
        self.cd_library_stats_lbl.configure(text=f"Scan error: {err_msg}", text_color="#FB7185")

    def start_cd_mixtape_generation(self):
        """Builds optimal mixtape plan up to 700MB."""
        folder = self.cd_library_folder_input.get().strip()
        seed_artist = self.cd_seed_artist_cb.get().strip()

        if not folder or not os.path.exists(folder):
            self.cd_export_status_lbl.configure(text="Please choose a valid library folder.", text_color="#FB7185")
            return

        if not seed_artist or seed_artist == "Select or Type Artist...":
            seed_artist = "🎲 Full Library Chaos (Random Gamble)"

        # Parse seed count
        raw_seed_cnt = self.cd_seed_count_menu.get()
        m_scnt = re.search(r'\d+', raw_seed_cnt)
        seed_cnt = int(m_scnt.group()) if m_scnt else 20

        # Parse preset
        raw_preset = self.cd_preset_menu.get()
        preset_key = "700MB_DATA_CD"
        for k, v in CAPACITY_PRESETS.items():
            if v["name"] == raw_preset:
                preset_key = k
                break

        # Parse max vibe tracks per artist
        raw_max_vibe = self.cd_max_vibe_menu.get()
        if "no limit" in raw_max_vibe.lower() or "unlimited" in raw_max_vibe.lower():
            max_vibe_cnt = 999
        else:
            m_vibe = re.search(r'\d+', raw_max_vibe)
            max_vibe_cnt = int(m_vibe.group()) if m_vibe else 3

        # Parse max song duration (anti-bloat filter)
        raw_dur = self.cd_max_dur_menu.get()
        if "no limit" in raw_dur.lower() or "unlimited" in raw_dur.lower():
            max_dur_s = 0
        elif ":" in raw_dur:
            m_time = re.search(r'(\d+):(\d+)', raw_dur)
            if m_time:
                max_dur_s = int(m_time.group(1)) * 60 + int(m_time.group(2))
            else:
                max_dur_s = 270
        else:
            max_dur_s = 270

        # Parse squeeze mode & bitrate
        raw_sqz = self.cd_squeeze_mode_menu.get().lower()
        if "all" in raw_sqz:
            squeeze_mode = "all"
        elif "lossless" in raw_sqz or "flac" in raw_sqz:
            squeeze_mode = "lossless_only"
        else:
            squeeze_mode = "none"

        raw_br = self.cd_bitrate_menu.get()
        m_br = re.search(r'\d+', raw_br)
        bitrate_kbps = int(m_br.group()) if m_br else 256

        # Parse track flow / mix style
        raw_style = self.cd_mix_style_menu.get().lower() if hasattr(self, 'cd_mix_style_menu') else "chaos"
        if "grouped" in raw_style or "artist" in raw_style:
            mix_style = "grouped"
        elif "seed intro" in raw_style or "intro" in raw_style:
            mix_style = "seed_intro"
        else:
            mix_style = "chaos_shuffle"

        raw_norm = self.cd_normalization_menu.get().lower() if hasattr(self, 'cd_normalization_menu') else "ebu"
        if "off" in raw_norm or "none" in raw_norm:
            norm_mode = "off"
        elif "hifi" in raw_norm or "16" in raw_norm:
            norm_mode = "car_hifi"
        else:
            norm_mode = "ebu_r128"

        self.btn_cd_generate.configure(state="disabled", text="Generating...")
        self.btn_cd_export.configure(state="disabled")
        self.cd_export_status_lbl.configure(text="🎲 Rolling library & packing optimal mixtape capacity...", text_color="#38BDF8")

        def run_generation():
            try:
                # Ensure index exists
                if not self.cd_library_index or self.cd_library_index.root_dir != folder:
                    self.after(0, lambda: self.cd_export_status_lbl.configure(text="Indexing local music files..."))
                    idx = LocalLibraryIndex(folder)
                    idx.scan()
                    self.cd_library_index = idx

                # Credentials if available in settings
                sp_cid = self.saved_settings.get("spotify_client_id", "")
                sp_sec = self.saved_settings.get("spotify_client_secret", "")
                sp_ref = self.saved_settings.get("spotify_refresh_token", "")
                recommender = SpotifyRecommender(sp_cid, sp_sec, sp_ref)

                planner = CDMixtapePlanner(recommender, self.cd_library_index)
                plan = planner.plan_mixtape(
                    seed_artist_name=seed_artist,
                    seed_track_count=seed_cnt,
                    preset_key=preset_key,
                    transcode_lossless_to_mp3=(squeeze_mode != "none"),
                    target_mp3_kbps=bitrate_kbps,
                    max_vibe_tracks_per_artist=max_vibe_cnt,
                    max_song_duration_s=max_dur_s,
                    squeeze_mode=squeeze_mode,
                    mix_style=mix_style,
                    normalize_audio=norm_mode,
                    progress_callback=lambda msg: self.after(0, lambda m=msg: self.cd_export_status_lbl.configure(text=m, text_color="#38BDF8"))
                )
                self.cd_mixtape_plan = plan
                self.after(0, lambda: self._on_cd_plan_success(plan))
            except Exception as e:
                self.after(0, lambda err=str(e): self._on_cd_plan_error(err))

        threading.Thread(target=run_generation, daemon=True).start()

    def _on_cd_plan_success(self, plan: Dict):
        self.btn_cd_generate.configure(state="normal", text="⚡ Generate & Pack Mixtape")
        self.btn_cd_export.configure(state="normal")
        self.display_cd_mixtape_plan(plan)

    def _on_cd_plan_error(self, err_msg: str):
        self.btn_cd_generate.configure(state="normal", text="⚡ Generate & Pack Mixtape")
        self.btn_cd_export.configure(state="normal")
        self.cd_export_status_lbl.configure(text=f"Generation failed: {err_msg}", text_color="#FB7185")

    def display_cd_mixtape_plan(self, plan: Dict):
        """Renders the capacity visualizer, metrics badges, and tracklist."""
        summary = plan.get("summary", {})
        tracks = plan.get("selected_tracks", [])

        total_mb = summary.get("total_mb", 0.0)
        util_pct = summary.get("utilization_pct", 0.0)
        disp_limit = summary.get("display_limit", "700 MB")
        dur_str = summary.get("duration_str", "0m 00s")
        seed_cnt = summary.get("seed_count", 0)
        vibe_cnt = summary.get("vibe_count", 0)
        filler_cnt = summary.get("filler_count", 0)

        # Update Capacity Bar & Labels
        frac = min(1.0, util_pct / 100.0)
        self.cd_capacity_bar.set(frac)
        
        # Dynamic color coding: Emerald green if nicely filled (>= 90%)
        bar_col = "#10B981" if util_pct >= 90 else "#38BDF8"
        self.cd_capacity_bar.configure(progress_color=bar_col)

        self.cd_capacity_lbl.configure(
            text=f"Capacity: {total_mb:.1f} MB / {disp_limit} ({util_pct:.1f}% Full)",
            text_color=bar_col
        )
        self.cd_track_count_lbl.configure(
            text=f"{len(tracks)} Tracks  •  {dur_str} Total Playback"
        )
        self.cd_breakdown_lbl.configure(
            text=f"🌱 Seed Artist: {seed_cnt} tracks  •  🎵 Vibe Related: {vibe_cnt} tracks  •  🧩 Gap Fit: {filler_cnt} tracks"
        )
        self.cd_export_status_lbl.configure(
            text=f"✓ Mixtape packed successfully! {len(tracks)} tracks ready to burn ({total_mb:.1f} MB).",
            text_color="#4ADE80"
        )

        # Clear and populate tracklist
        for child in self.cd_tracks_scroll.winfo_children():
            child.destroy()

        input_bg = getattr(self, 'theme_cfg', {}).get('input_bg', '#070F15')
        border_col = getattr(self, 'theme_cfg', {}).get('border', '#1F3A4E')
        text_sec = getattr(self, 'theme_cfg', {}).get('text_secondary', '#94A3B8')

        for idx, trk in enumerate(tracks, start=1):
            row = ctk.CTkFrame(self.cd_tracks_scroll, fg_color=input_bg, border_color=border_col, border_width=1, corner_radius=6, height=32)
            row.pack(fill="x", padx=2, pady=1)
            row.pack_propagate(False)

            num_lbl = ctk.CTkLabel(row, text=f"{idx:03d}.", font=("Segoe UI", 9, "bold"), text_color=text_sec, width=28, anchor="e")
            num_lbl.pack(side="left", padx=(6, 4))

            # Role badge color
            role = trk.get("role", "vibe")
            if role == "seed":
                badge_text = "🌱 SEED"
                badge_bg = "#064E3B"
                badge_fg = "#34D399"
            elif role == "vibe":
                badge_text = "🎵 VIBE"
                badge_bg = "#1E1B4B"
                badge_fg = "#818CF8"
            else:
                badge_text = "🧩 GAP"
                badge_bg = "#312E81"
                badge_fg = "#A5B4FC"

            badge_lbl = ctk.CTkLabel(
                row,
                text=badge_text,
                font=("Segoe UI", 8, "bold"),
                fg_color=badge_bg,
                text_color=badge_fg,
                corner_radius=4,
                width=48,
                height=18
            )
            badge_lbl.pack(side="left", padx=(2, 6))

            t_art = trk.get("artist", "Unknown")
            t_tit = trk.get("title", "Unknown")
            t_alb = trk.get("album", "")

            disp_str = f"{t_art} - {t_tit}"
            if t_alb:
                disp_str += f"   [{t_alb}]"
            if len(disp_str) > 65:
                disp_str = disp_str[:62] + "..."

            title_lbl = ctk.CTkLabel(row, text=disp_str, font=("Segoe UI", 9), text_color="#F5F5F7", anchor="w")
            title_lbl.pack(side="left", fill="x", expand=True, padx=4)

            # Transcode badge / file size
            eff_mb = trk.get("effective_bytes", trk.get("size_bytes", 0)) / (1024 * 1024)
            size_str = f"{eff_mb:.1f} MB"
            if trk.get("will_transcode"):
                size_str += " ⚡MP3"

            size_lbl = ctk.CTkLabel(row, text=size_str, font=("Segoe UI", 9, "bold"), text_color="#38BDF8", width=75, anchor="e")
            size_lbl.pack(side="right", padx=(4, 8))

            dur_s = trk.get("duration_s", 0)
            m = int(dur_s // 60)
            s = int(dur_s % 60)
            dur_lbl = ctk.CTkLabel(row, text=f"{m}:{s:02d}", font=("Segoe UI", 9), text_color=text_sec, width=40, anchor="e")
            dur_lbl.pack(side="right", padx=(0, 4))

    def start_cd_export(self):
        """Executes non-destructive copying and transcoding into burn folder."""
        if not self.cd_mixtape_plan or not self.cd_mixtape_plan.get("selected_tracks"):
            self.cd_export_status_lbl.configure(text="No mixtape planned. Click 'Generate & Pack Mixtape' first.", text_color="#FB7185")
            return

        dest_dir = self.cd_output_folder_input.get().strip() or r"C:\SMA-downloads\CD_Mixtapes"
        self.save_setting("cd_output_folder", dest_dir)

        raw_br = self.cd_bitrate_menu.get()
        m_br = re.search(r'\d+', raw_br)
        bitrate_kbps = int(m_br.group()) if m_br else 256

        raw_norm = self.cd_normalization_menu.get().lower() if hasattr(self, 'cd_normalization_menu') else "ebu"
        if "off" in raw_norm or "none" in raw_norm:
            norm_mode = "off"
        elif "hifi" in raw_norm or "16" in raw_norm:
            norm_mode = "car_hifi"
        else:
            norm_mode = "ebu_r128"

        self.btn_cd_export.configure(state="disabled", text="Exporting...")
        self.btn_cd_generate.configure(state="disabled")
        self.cd_is_exporting = True
        self.cd_export_progress_bar.set(0)

        def on_export_progress(cur: int, tot: int, name: str, status: str):
            self.after(0, lambda c=cur, t=tot, n=name, s=status: self._update_cd_export_progress(c, t, n, s))

        def run_export():
            try:
                ffmpeg_bin = self.get_file_path("ffmpeg.exe")
                exporter = CDMixtapeExporter(ffmpeg_bin)
                self.cd_exporter = exporter

                res = exporter.export(
                    mixtape_plan=self.cd_mixtape_plan,
                    destination_dir=dest_dir,
                    mp3_bitrate_kbps=bitrate_kbps,
                    normalize_audio=norm_mode,
                    progress_callback=on_export_progress
                )
                self.after(0, lambda: self._on_cd_export_complete(res))
            except Exception as e:
                self.after(0, lambda err=str(e): self._on_cd_export_error(err))

        threading.Thread(target=run_export, daemon=True).start()

    def _update_cd_export_progress(self, current: int, total: int, track_name: str, status: str):
        frac = current / total if total > 0 else 0
        self.cd_export_progress_bar.set(frac)
        self.cd_export_counter_lbl.configure(text=f"{current} / {total}")
        self.cd_export_status_lbl.configure(
            text=f"[{current}/{total}] {status} {track_name}",
            text_color="#38BDF8"
        )

    def _on_cd_export_complete(self, res: Dict):
        self.cd_is_exporting = False
        self.btn_cd_export.configure(state="normal", text="🚀 Copy & Export CD Burn Folder")
        self.btn_cd_generate.configure(state="normal")
        self.cd_export_progress_bar.set(1.0)

        if res.get("cancelled"):
            self.cd_export_status_lbl.configure(text="Export cancelled by user.", text_color="#FB7185")
        else:
            folder = res.get("target_folder", "")
            copied = res.get("copied_count", 0)
            transcoded = res.get("transcoded_count", 0)
            self.cd_export_status_lbl.configure(
                text=f"✓ CD Mixtape ready! ({copied} copied, {transcoded} normalized/transcoded). M3U playlist generated.",
                text_color="#4ADE80"
            )
            self.log(f"CD Burn folder ready at: {folder}")
            # Automatically reveal the burn folder
            try:
                os.startfile(folder)
            except Exception:
                subprocess.Popen(["explorer", folder])

    def _on_cd_export_error(self, err_msg: str):
        self.cd_is_exporting = False
        self.btn_cd_export.configure(state="normal", text="🚀 Copy & Export CD Burn Folder")
        self.btn_cd_generate.configure(state="normal")
        self.cd_export_status_lbl.configure(text=f"Export failed: {err_msg}", text_color="#FB7185")

    def cancel_cd_operation(self):
        if self.cd_exporter:
            self.cd_exporter.cancel()
        self.cd_export_status_lbl.configure(text="Cancelling...", text_color="#FB7185")

