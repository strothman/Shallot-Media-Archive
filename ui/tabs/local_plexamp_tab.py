"""
Local to Plexamp Tab Mixin for Shallot Media Archive.
Handles local directory scanning for audio files, format conversion,
tag enrichment, and seamless ingestion into Plexamp directory structure.
"""

import os
import sys
import threading
import customtkinter as ctk

from local_sync import LocalAudioScanner, LocalPlexampPipeline


class LocalPlexampTabMixin:
    """Mixin containing GUI layout and controller methods for Local to Plexamp tab."""

    def build_local_plexamp_page(self, parent):
        # =========================================================================
        # --- Page 3.75: Local to Plexamp Page ---
        # =========================================================================
        self.local_plexamp_page = ctk.CTkFrame(parent, fg_color="transparent")

        lbl_local = ctk.CTkLabel(self.local_plexamp_page, text="Local to Plexamp", font=("Segoe UI", 18, "bold"), anchor="w")
        lbl_local.pack(fill="x", padx=20, pady=(15, 8))
        self.page_titles.append(lbl_local)

        # Card 1: Local Source Folder
        self.local_input_card = ctk.CTkFrame(self.local_plexamp_page, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.local_input_card.pack(fill="x", padx=20, pady=4)

        card_loc_lbl = ctk.CTkLabel(self.local_input_card, text="LOCAL SOURCE DIRECTORY", font=("Segoe UI", 11, "bold"), text_color="#00E5FF")
        card_loc_lbl.pack(anchor="w", padx=15, pady=(8, 3))
        self.theme_titles.append(card_loc_lbl)

        self.local_src_frame = ctk.CTkFrame(self.local_input_card, fg_color="transparent")
        self.local_src_frame.pack(fill="x", padx=15, pady=(2, 8))

        default_src_folder = self.saved_settings.get("local_source_folder", r"C:\SMA-downloads")
        self.local_source_folder_input = ctk.CTkEntry(
            self.local_src_frame,
            placeholder_text=r"Select folder with audio files (.mp3, .flac, .m4a, .wav)...",
            height=32,
            fg_color="#070F15",
            border_color="#1F3A4E",
            text_color="#F5F5F7",
            placeholder_text_color="#78909C"
        )
        self.local_source_folder_input.insert(0, default_src_folder)
        self.local_source_folder_input.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.local_source_folder_input.bind("<Return>", lambda e: self.scan_local_folder())
        self.theme_entries.append(self.local_source_folder_input)

        self.btn_local_src_browse = ctk.CTkButton(
            self.local_src_frame,
            text="📁 Browse",
            width=75,
            height=32,
            font=("Segoe UI", 10, "bold"),
            command=self.browse_local_source_folder
        )
        self.btn_local_src_browse.pack(side="left", padx=(0, 6))
        self.theme_buttons_secondary.append(self.btn_local_src_browse)

        self.btn_local_scan = ctk.CTkButton(
            self.local_src_frame,
            text="⚡ Scan Folder",
            width=100,
            height=32,
            font=("Segoe UI", 10, "bold"),
            command=self.scan_local_folder
        )
        self.btn_local_scan.pack(side="right")
        self.theme_buttons_secondary.append(self.btn_local_scan)

        # Card 2: Collection Overview & Plexamp Options
        self.local_meta_card = ctk.CTkFrame(self.local_plexamp_page, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.local_meta_card.pack(fill="x", padx=20, pady=4)

        card_loc_meta_lbl = ctk.CTkLabel(self.local_meta_card, text="COLLECTION & PLEXAMP CONFIGURATION", font=("Segoe UI", 11, "bold"), text_color="#00E5FF")
        card_loc_meta_lbl.pack(anchor="w", padx=15, pady=(8, 4))
        self.theme_titles.append(card_loc_meta_lbl)

        loc_meta_grid = ctk.CTkFrame(self.local_meta_card, fg_color="transparent")
        loc_meta_grid.pack(fill="x", padx=15, pady=(2, 8))
        loc_meta_grid.columnconfigure(0, weight=0)
        loc_meta_grid.columnconfigure(1, weight=1)
        loc_meta_grid.columnconfigure(2, weight=2)

        # Col 0: Folder Icon preview
        self.local_folder_icon_frame = ctk.CTkFrame(loc_meta_grid, width=64, height=64, fg_color="#070F15", corner_radius=8, border_color="#1F3A4E", border_width=1)
        self.local_folder_icon_frame.grid(row=0, column=0, rowspan=2, padx=(0, 10), pady=2, sticky="nw")
        self.local_folder_icon_frame.pack_propagate(False)

        self.local_folder_icon_lbl = ctk.CTkLabel(self.local_folder_icon_frame, text="📁", font=("Segoe UI", 26))
        self.local_folder_icon_lbl.pack(expand=True, fill="both")

        # Col 1: Collection Info
        loc_info_frame = ctk.CTkFrame(loc_meta_grid, fg_color="transparent")
        loc_info_frame.grid(row=0, column=1, rowspan=2, padx=(0, 10), sticky="nsew")

        self.local_title_lbl = ctk.CTkLabel(loc_info_frame, text="No Local Folder Scanned", font=("Segoe UI", 12, "bold"), text_color="#F5F5F7", anchor="w")
        self.local_title_lbl.pack(fill="x", pady=(0, 1))

        self.local_author_lbl = ctk.CTkLabel(loc_info_frame, text="Select source folder & click 'Scan Folder'", font=("Segoe UI", 10), text_color="#78909C", anchor="w")
        self.local_author_lbl.pack(fill="x", pady=(0, 1))
        self.theme_labels_secondary.append(self.local_author_lbl)

        self.local_stats_lbl = ctk.CTkLabel(loc_info_frame, text="0 audio files found", font=("Segoe UI", 10, "bold"), text_color="#00E5FF", anchor="w")
        self.local_stats_lbl.pack(fill="x")
        self.theme_titles.append(self.local_stats_lbl)

        # Col 2: Destination & Options
        loc_cfg_frame = ctk.CTkFrame(loc_meta_grid, fg_color="transparent")
        loc_cfg_frame.grid(row=0, column=2, rowspan=2, sticky="nsew")

        # Music Folder row
        loc_fld_row = ctk.CTkFrame(loc_cfg_frame, fg_color="transparent")
        loc_fld_row.pack(fill="x", pady=(0, 4))
        lbl_loc_pfld = ctk.CTkLabel(loc_fld_row, text="Music Library:", font=("Segoe UI", 10, "bold"), text_color="#78909C", width=80, anchor="w")
        lbl_loc_pfld.pack(side="left")
        self.theme_labels_secondary.append(lbl_loc_pfld)

        default_plex_dir = self.saved_settings.get("plex_music_folder", r"C:\SMA-downloads\Music")
        self.local_folder_input = ctk.CTkEntry(loc_fld_row, placeholder_text=r"C:\SMA-downloads\Music", height=28, fg_color="#070F15", border_color="#1F3A4E", text_color="#F5F5F7", font=("Segoe UI", 10))
        self.local_folder_input.insert(0, default_plex_dir)
        self.local_folder_input.pack(side="left", fill="x", expand=True, padx=(4, 4))
        self.local_folder_input.bind("<FocusOut>", lambda e: self.save_setting("plex_music_folder", self.local_folder_input.get().strip()))
        self.local_folder_input.bind("<KeyRelease>", lambda e: self.save_setting("plex_music_folder", self.local_folder_input.get().strip()))
        self.theme_entries.append(self.local_folder_input)

        self.btn_local_browse = ctk.CTkButton(loc_fld_row, text="📂", width=32, height=28, font=("Segoe UI", 10, "bold"), command=self.browse_local_plex_folder)
        self.btn_local_browse.pack(side="right")
        self.theme_buttons_secondary.append(self.btn_local_browse)

        # Row 1: Format + Org + Concurrency
        loc_opts_row1 = ctk.CTkFrame(loc_cfg_frame, fg_color="transparent")
        loc_opts_row1.pack(fill="x", pady=(0, 3))

        self.local_format_menu = ctk.CTkOptionMenu(
            loc_opts_row1,
            values=["Keep Original (Copy)", "MP3 (320 kbps)", "FLAC (Lossless)", "M4A (256 kbps)"],
            height=28,
            font=("Segoe UI", 10),
            dropdown_font=("Segoe UI", 10),
            command=lambda v: self.save_setting("local_audio_format", v)
        )
        saved_loc_fmt = self.saved_settings.get("local_audio_format", "Keep Original (Copy)")
        if saved_loc_fmt in self.local_format_menu._values:
            self.local_format_menu.set(saved_loc_fmt)
        self.local_format_menu.pack(side="left", padx=(0, 4))
        self.theme_option_menus.append(self.local_format_menu)

        self.local_org_menu = ctk.CTkOptionMenu(
            loc_opts_row1,
            values=["Plex Standard (Artist/Album/Track)", "Batch Folder (Batch/Track)"],
            height=28,
            font=("Segoe UI", 10),
            dropdown_font=("Segoe UI", 10),
            command=lambda v: self.save_setting("local_folder_structure", v)
        )
        saved_loc_org = self.saved_settings.get("local_folder_structure", "Plex Standard (Artist/Album/Track)")
        if saved_loc_org in self.local_org_menu._values:
            self.local_org_menu.set(saved_loc_org)
        self.local_org_menu.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.theme_option_menus.append(self.local_org_menu)

        self.local_concurrency_menu = ctk.CTkOptionMenu(
            loc_opts_row1,
            values=["4 Files Concurrent", "2 Files Concurrent", "1 File Safe"],
            height=28,
            width=120,
            font=("Segoe UI", 9),
            dropdown_font=("Segoe UI", 9),
            command=lambda v: self.save_setting("local_concurrency", v)
        )
        saved_loc_conc = self.saved_settings.get("local_concurrency", "4 Files Concurrent")
        if saved_loc_conc in self.local_concurrency_menu._values:
            self.local_concurrency_menu.set(saved_loc_conc)
        self.local_concurrency_menu.pack(side="left")
        self.theme_option_menus.append(self.local_concurrency_menu)

        # Row 2: Toggles (Artwork, Synced Lyrics, ReplayGain, Auto-Enrich, Move)
        loc_opts_row2 = ctk.CTkFrame(loc_cfg_frame, fg_color="transparent")
        loc_opts_row2.pack(fill="x", pady=(2, 0))

        self.local_embed_art_switch = ctk.CTkSwitch(
            loc_opts_row2,
            text="Artwork",
            font=("Segoe UI", 9),
            width=58,
            height=18,
            command=lambda: self.save_setting("local_embed_art", bool(self.local_embed_art_switch.get()))
        )
        if self.saved_settings.get("local_embed_art", True):
            self.local_embed_art_switch.select()
        else:
            self.local_embed_art_switch.deselect()
        self.local_embed_art_switch.pack(side="left", padx=(0, 4))
        self.theme_switches.append(self.local_embed_art_switch)

        self.local_lyrics_switch = ctk.CTkSwitch(
            loc_opts_row2,
            text="Lyrics (.lrc)",
            font=("Segoe UI", 9),
            width=70,
            height=18,
            command=lambda: self.save_setting("local_fetch_lyrics", bool(self.local_lyrics_switch.get()))
        )
        if self.saved_settings.get("local_fetch_lyrics", True):
            self.local_lyrics_switch.select()
        else:
            self.local_lyrics_switch.deselect()
        self.local_lyrics_switch.pack(side="left", padx=(0, 4))
        self.theme_switches.append(self.local_lyrics_switch)

        self.local_gain_switch = ctk.CTkSwitch(
            loc_opts_row2,
            text="ReplayGain",
            font=("Segoe UI", 9),
            width=68,
            height=18,
            command=lambda: self.save_setting("local_calculate_replaygain", bool(self.local_gain_switch.get()))
        )
        if self.saved_settings.get("local_calculate_replaygain", True):
            self.local_gain_switch.select()
        else:
            self.local_gain_switch.deselect()
        self.local_gain_switch.pack(side="left", padx=(0, 4))
        self.theme_switches.append(self.local_gain_switch)

        self.local_enrich_switch = ctk.CTkSwitch(
            loc_opts_row2,
            text="Smart Tags",
            font=("Segoe UI", 9),
            width=68,
            height=18,
            command=lambda: self.save_setting("local_auto_enrich", bool(self.local_enrich_switch.get()))
        )
        if self.saved_settings.get("local_auto_enrich", True):
            self.local_enrich_switch.select()
        else:
            self.local_enrich_switch.deselect()
        self.local_enrich_switch.pack(side="left", padx=(0, 4))
        self.theme_switches.append(self.local_enrich_switch)

        self.local_move_switch = ctk.CTkSwitch(
            loc_opts_row2,
            text="Move File",
            font=("Segoe UI", 9),
            width=62,
            height=18,
            command=lambda: self.save_setting("local_move_files", bool(self.local_move_switch.get()))
        )
        if self.saved_settings.get("local_move_files", False):
            self.local_move_switch.select()
        else:
            self.local_move_switch.deselect()
        self.local_move_switch.pack(side="left")
        self.theme_switches.append(self.local_move_switch)

        # Card 3: Tracklist Selection
        self.local_tracks_card = ctk.CTkFrame(self.local_plexamp_page, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.local_tracks_card.pack(fill="both", expand=True, padx=20, pady=4)

        loc_tracks_header = ctk.CTkFrame(self.local_tracks_card, fg_color="transparent")
        loc_tracks_header.pack(fill="x", padx=15, pady=(8, 4))

        card_loc_trk_lbl = ctk.CTkLabel(loc_tracks_header, text="AUDIO FILES FOUND", font=("Segoe UI", 11, "bold"), text_color="#00E5FF")
        card_loc_trk_lbl.pack(side="left")
        self.theme_titles.append(card_loc_trk_lbl)

        self.local_track_count_lbl = ctk.CTkLabel(loc_tracks_header, text="0 / 0 Selected", font=("Segoe UI", 10, "bold"), text_color="#78909C")
        self.local_track_count_lbl.pack(side="left", padx=12)
        self.theme_labels_secondary.append(self.local_track_count_lbl)

        self.btn_local_clear_completed = ctk.CTkButton(
            loc_tracks_header,
            text="Clear Completed",
            width=95,
            height=24,
            font=("Segoe UI", 9, "bold"),
            command=self.clear_completed_local_tracks
        )
        self.btn_local_clear_completed.pack(side="right", padx=(4, 0))
        self.theme_buttons_secondary.append(self.btn_local_clear_completed)

        self.btn_local_deselect_all = ctk.CTkButton(
            loc_tracks_header,
            text="Deselect All",
            width=75,
            height=24,
            font=("Segoe UI", 9, "bold"),
            command=lambda: self.toggle_all_local_tracks(False)
        )
        self.btn_local_deselect_all.pack(side="right", padx=(4, 0))
        self.theme_buttons_secondary.append(self.btn_local_deselect_all)

        self.btn_local_select_all = ctk.CTkButton(
            loc_tracks_header,
            text="Select All",
            width=65,
            height=24,
            font=("Segoe UI", 9, "bold"),
            command=lambda: self.toggle_all_local_tracks(True)
        )
        self.btn_local_select_all.pack(side="right")
        self.theme_buttons_secondary.append(self.btn_local_select_all)

        # Scrollable Tracklist Frame
        self.local_track_scroll = ctk.CTkScrollableFrame(self.local_tracks_card, fg_color="transparent", border_width=0)
        self.local_track_scroll.pack(fill="both", expand=True, padx=12, pady=(0, 6))

        self.local_empty_lbl = ctk.CTkLabel(
            self.local_track_scroll,
            text="No files loaded yet. Select a source folder above and click 'Scan Folder'.",
            font=("Segoe UI", 11),
            text_color="#78909C"
        )
        self.local_empty_lbl.pack(pady=30)
        self.theme_labels_secondary.append(self.local_empty_lbl)

        # Card 4: Action & Progress Card
        self.local_action_card = ctk.CTkFrame(self.local_plexamp_page, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.local_action_card.pack(fill="x", padx=20, pady=(4, 10))

        loc_act_top = ctk.CTkFrame(self.local_action_card, fg_color="transparent")
        loc_act_top.pack(fill="x", padx=15, pady=(8, 2))

        self.local_status_lbl = ctk.CTkLabel(loc_act_top, text="Ready to import", font=("Segoe UI", 10, "bold"), text_color="#78909C", anchor="w")
        self.local_status_lbl.pack(side="left")
        self.theme_labels_secondary.append(self.local_status_lbl)

        self.local_counter_lbl = ctk.CTkLabel(loc_act_top, text="0 / 0", font=("Segoe UI", 10, "bold"), text_color="#F5F5F7", anchor="e")
        self.local_counter_lbl.pack(side="right")

        self.local_progress_bar = ctk.CTkProgressBar(self.local_action_card, height=8, corner_radius=4, progress_color="#00E5FF", fg_color="#070F15")
        self.local_progress_bar.set(0)
        self.local_progress_bar.pack(fill="x", padx=15, pady=(2, 8))

        loc_act_btns = ctk.CTkFrame(self.local_action_card, fg_color="transparent")
        loc_act_btns.pack(fill="x", padx=15, pady=(0, 8))

        self.btn_local_start = ctk.CTkButton(
            loc_act_btns,
            text="🚀  Import & Tag for Plexamp",
            font=("Segoe UI", 12, "bold"),
            height=36,
            corner_radius=8,
            command=self.start_local_sync
        )
        self.btn_local_start.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.btn_local_open_folder = ctk.CTkButton(
            loc_act_btns,
            text="📂 Open Music Folder",
            font=("Segoe UI", 11, "bold"),
            height=36,
            width=140,
            corner_radius=8,
            fg_color="#0E1A24",
            border_color="#00E5FF",
            border_width=1,
            text_color="#00E5FF",
            command=self.open_local_music_folder
        )
        self.btn_local_open_folder.pack(side="left", padx=(0, 6))
        self.theme_buttons_secondary.append(self.btn_local_open_folder)

        self.btn_local_stop = ctk.CTkButton(
            loc_act_btns,
            text="⏹ Cancel",
            font=("Segoe UI", 11, "bold"),
            height=36,
            width=85,
            corner_radius=8,
            fg_color="#3B1214",
            hover_color="#5C1D20",
            border_color="#FB7185",
            border_width=1,
            text_color="#FB7185",
            command=self.stop_local_sync
        )
        self.btn_local_stop.pack(side="right")

    def browse_local_source_folder(self):
        """ Opens folder picker dialog for local audio source directory """
        current_val = self.local_source_folder_input.get().strip() or r"C:\SMA-downloads"
        init_dir = current_val if os.path.exists(current_val) else r"C:\\"
        selected_dir = ctk.filedialog.askdirectory(initialdir=init_dir, title="Select Local Music Source Directory")
        if selected_dir:
            selected_dir = os.path.normpath(selected_dir)
            self.local_source_folder_input.delete(0, "end")
            self.local_source_folder_input.insert(0, selected_dir)
            self.save_setting("local_source_folder", selected_dir)
            self.scan_local_folder()

    def browse_local_plex_folder(self):
        """ Opens folder picker dialog to select Plex music library folder """
        current_val = self.local_folder_input.get().strip() or r"C:\SMA-downloads\Music"
        init_dir = current_val if os.path.exists(current_val) else r"C:\\"
        selected_dir = ctk.filedialog.askdirectory(initialdir=init_dir, title="Select Plexamp Music Library Folder")
        if selected_dir:
            selected_dir = os.path.normpath(selected_dir)
            self.local_folder_input.delete(0, "end")
            self.local_folder_input.insert(0, selected_dir)
            if hasattr(self, 'spotify_folder_input'):
                self.spotify_folder_input.delete(0, "end")
                self.spotify_folder_input.insert(0, selected_dir)
            if hasattr(self, 'yt_plexamp_folder_input'):
                self.yt_plexamp_folder_input.delete(0, "end")
                self.yt_plexamp_folder_input.insert(0, selected_dir)
            self.save_setting("plex_music_folder", selected_dir)

    def scan_local_folder(self):
        """ Scans the selected folder for audio files in a background worker thread """
        folder_path = self.local_source_folder_input.get().strip()
        if not folder_path or not os.path.exists(folder_path):
            self.local_status_lbl.configure(text="Please select a valid source folder.", text_color="#FB7185")
            return

        self.btn_local_scan.configure(state="disabled", text="Scanning... ⏳")
        self.local_status_lbl.configure(text="Scanning audio files in folder...", text_color=getattr(self, 'theme_cfg', {}).get("accent", "#00E5FF"))

        def run_scan():
            try:
                collection = LocalAudioScanner.scan_directory(folder_path)
                self.local_plexamp_collection = collection
                self.after(0, lambda: self.display_local_collection(collection))
            except Exception as e:
                err_msg = str(e)
                self.log(f"Local scan error: {err_msg}", is_error=True)
                self.after(0, lambda msg=err_msg: self.show_local_scan_error(msg))
            finally:
                self.after(0, lambda: self.btn_local_scan.configure(state="normal", text="⚡ Scan Folder"))

        threading.Thread(target=run_scan, daemon=True).start()

    def show_local_scan_error(self, err_msg):
        self.local_status_lbl.configure(text=f"Error: {err_msg[:60]}", text_color="#FB7185")
        for widget in self.local_track_scroll.winfo_children():
            widget.destroy()
        lbl = ctk.CTkLabel(self.local_track_scroll, text=f"Failed to scan folder:\n{err_msg}", font=("Segoe UI", 11), text_color="#FB7185")
        lbl.pack(pady=25)

    def display_local_collection(self, collection):
        """ Renders the scanned local collection header, stats, and interactive file list """
        title = collection.get("title", "Local Files")
        tracks = collection.get("tracks", [])
        total_count = len(tracks)

        self.local_title_lbl.configure(text=title[:38] + ("..." if len(title) > 38 else ""))
        self.local_author_lbl.configure(text=f"Path: {collection.get('source_dir', '')[:40]}")
        self.local_stats_lbl.configure(text=f"{total_count} audio files found")

        # Populate Tracklist smoothly in non-blocking slices
        for widget in self.local_track_scroll.winfo_children():
            widget.destroy()

        self.local_plexamp_track_items = []
        input_bg = getattr(self, 'theme_cfg', {}).get('input_bg', '#070F15')
        border_col = getattr(self, 'theme_cfg', {}).get('border', '#1F3A4E')
        text_sec = getattr(self, 'theme_cfg', {}).get('text_secondary', '#78909C')

        dest_folder = self.local_folder_input.get().strip() or r"C:\SMA-downloads\Music"
        raw_fmt = self.local_format_menu.get().lower()
        if "flac" in raw_fmt:
            target_ext = "flac"
        elif "m4a" in raw_fmt:
            target_ext = "m4a"
        elif "mp3" in raw_fmt:
            target_ext = "mp3"
        else:
            target_ext = "mp3"

        raw_org = self.local_org_menu.get()
        folder_struct = "playlist_folder" if "Batch Folder" in raw_org else "plex_standard"

        batch_size = 40

        def render_chunk(start_idx=0):
            end_idx = min(start_idx + batch_size, total_count)
            for idx in range(start_idx + 1, end_idx + 1):
                track = tracks[idx - 1]
                row_frame = ctk.CTkFrame(self.local_track_scroll, fg_color=input_bg, border_color=border_col, border_width=1, corner_radius=6, height=36)
                row_frame.pack(fill="x", padx=4, pady=2)
                row_frame.pack_propagate(False)

                chk_var = ctk.IntVar(value=1)
                chk = ctk.CTkCheckBox(
                    row_frame,
                    text="",
                    variable=chk_var,
                    width=20,
                    height=20,
                    corner_radius=4,
                    command=self.update_local_selected_count
                )
                chk.pack(side="left", padx=(8, 4), pady=4)

                num_lbl = ctk.CTkLabel(row_frame, text=f"{idx:02d}.", font=("Segoe UI", 10, "bold"), text_color=text_sec, width=24, anchor="e")
                num_lbl.pack(side="left", padx=(0, 6))

                t_title = track.get("title", "Unknown")
                t_artist = track.get("artist", "Unknown")
                t_album = track.get("album", "")
                t_ext = track.get("ext", "").upper()

                title_text = f"{t_title} - {t_artist}"
                if t_album and t_album not in ["Singles", "Local Files"]:
                    title_text += f"   [{t_album}]"
                title_text += f"   ({t_ext})"

                if len(title_text) > 75:
                    title_text = title_text[:72] + "..."

                title_lbl = ctk.CTkLabel(row_frame, text=title_text, font=("Segoe UI", 10), text_color="#F5F5F7", anchor="w")
                title_lbl.pack(side="left", fill="x", expand=True, padx=4)

                dur_ms = track.get("duration_ms", 0)
                mins = int((dur_ms / 1000) // 60)
                secs = int((dur_ms / 1000) % 60)
                dur_str = f"{mins}:{secs:02d}" if dur_ms > 0 else ""
                dur_lbl = ctk.CTkLabel(row_frame, text=dur_str, font=("Segoe UI", 9), text_color=text_sec, width=40, anchor="e")
                dur_lbl.pack(side="left", padx=(0, 8))

                # Pre-check if already in library
                try:
                    coll = self.local_plexamp_collection or {}
                    is_in_lib = LocalPlexampPipeline.check_existing_track(
                        dest_folder, track, coll, target_ext, folder_struct
                    )
                except Exception:
                    is_in_lib = False
                init_status = "✓ In Library" if is_in_lib else "Ready"
                init_color = "#4ADE80" if is_in_lib else "#78909C"

                status_badge = ctk.CTkLabel(row_frame, text=init_status, font=("Segoe UI", 9, "bold"), text_color=init_color, width=75, anchor="e")
                status_badge.pack(side="right", padx=(0, 10))

                self.local_plexamp_track_items.append({
                    "track": track,
                    "var": chk_var,
                    "row_frame": row_frame,
                    "status_badge": status_badge,
                    "checkbox": chk
                })

            self.update_local_selected_count()
            if end_idx < total_count:
                self.local_status_lbl.configure(text=f"Loading files... ({end_idx}/{total_count})", text_color=getattr(self, 'theme_cfg', {}).get("accent", "#00E5FF"))
                self.after(2, lambda: render_chunk(end_idx))
            else:
                self.local_status_lbl.configure(text=f"Loaded {total_count} files. Select files and click 'Import & Tag'.", text_color=getattr(self, 'theme_cfg', {}).get("text_primary", "#F5F5F7"))

        render_chunk(0)

    def toggle_all_local_tracks(self, select_all: bool):
        for item in self.local_plexamp_track_items:
            item["var"].set(1 if select_all else 0)
        self.update_local_selected_count()

    def clear_completed_local_tracks(self):
        """ Removes tracks that are already in the Plex library or marked done from the view """
        if not self.local_plexamp_track_items:
            return
        remaining_items = []
        for item in self.local_plexamp_track_items:
            status_text = item["status_badge"].cget("text")
            if "✓" in status_text:
                item["row_frame"].destroy()
            else:
                remaining_items.append(item)
        self.local_plexamp_track_items = remaining_items
        self.update_local_selected_count()
        if not self.local_plexamp_track_items:
            empty_lbl = ctk.CTkLabel(
                self.local_track_scroll,
                text="✓ All completed files cleared. All caught up!",
                font=("Segoe UI", 11, "bold"),
                text_color=getattr(self, 'theme_cfg', {}).get("accent", "#00E5FF")
            )
            empty_lbl.pack(pady=30)
            self.theme_labels_secondary.append(empty_lbl)

    def update_local_selected_count(self):
        selected = sum(1 for item in self.local_plexamp_track_items if item["var"].get() == 1)
        total = len(self.local_plexamp_track_items)
        self.local_track_count_lbl.configure(text=f"{selected} / {total} Selected")
        self.local_counter_lbl.configure(text=f"0 / {selected}")

    def open_local_music_folder(self):
        """ Opens the Plex music folder in Windows Explorer """
        folder = self.local_folder_input.get().strip() or r"C:\SMA-downloads\Music"
        os.makedirs(folder, exist_ok=True)
        try:
            os.startfile(folder)
        except Exception as e:
            self.log(f"Failed to open folder '{folder}': {e}", is_error=True)

    def start_local_sync(self):
        """ Runs the Local to Plexamp ingestion and tagging pipeline """
        if not self.local_plexamp_collection:
            self.local_status_lbl.configure(text="Please scan a source folder first.", text_color="#FB7185")
            return

        selected_tracks = []
        for idx, item in enumerate(self.local_plexamp_track_items):
            if item["var"].get() == 1:
                t = dict(item["track"])
                t["_track_index"] = idx
                selected_tracks.append(t)

        if not selected_tracks:
            self.local_status_lbl.configure(text="No files selected. Check at least one song.", text_color="#FB7185")
            return

        dest_folder = self.local_folder_input.get().strip() or r"C:\SMA-downloads\Music"
        self.save_setting("plex_music_folder", dest_folder)

        raw_fmt = self.local_format_menu.get()
        raw_org = self.local_org_menu.get()
        folder_struct = "playlist_folder" if "Batch Folder" in raw_org else "plex_standard"

        embed_art = bool(self.local_embed_art_switch.get())
        fetch_lyrics = bool(self.local_lyrics_switch.get())
        calc_replaygain = bool(self.local_gain_switch.get())
        auto_enrich = bool(self.local_enrich_switch.get())
        move_files = bool(self.local_move_switch.get())

        raw_conc = self.local_concurrency_menu.get()
        concurrency = 4
        if "2" in raw_conc:
            concurrency = 2
        elif "1" in raw_conc:
            concurrency = 1

        app_dir = os.path.dirname(self.get_active_yt_dlp_path())
        ffmpeg_exe = os.path.join(app_dir, "ffmpeg.exe")

        self.btn_local_start.configure(state="disabled", text="Importing to Plexamp... ⏳")
        self.local_progress_bar.set(0)
        self.power_light.configure(text="● IMPORTING", text_color=getattr(self, 'theme_cfg', {}).get("accent", "#00E5FF"))

        def log_cb(msg: str, is_error: bool = False):
            self.log(f"[Local] {msg}", is_error=is_error)

        def progress_cb(pct: float, status_text: str):
            self.after(0, lambda: self.local_progress_bar.set(pct))
            self.after(0, lambda: self.local_status_lbl.configure(text=status_text))
            self.after(0, lambda: self.update_taskbar_progress(int(pct * 100)))

        def track_status_cb(track_index: int, text: str, color: str):
            if track_index < len(self.local_plexamp_track_items):
                badge = self.local_plexamp_track_items[track_index]["status_badge"]
                self.after(0, lambda b=badge, t=text, c=color: b.configure(text=t, text_color=c))

        self.local_plexamp_pipeline = LocalPlexampPipeline(
            ffmpeg_exe=ffmpeg_exe,
            log_callback=log_cb,
            progress_callback=progress_cb,
            track_status_callback=track_status_cb
        )

        def run_pipeline():
            if not self.local_plexamp_pipeline:
                return
            self.log(f"Starting Local to Plexamp import ({len(selected_tracks)} files) to: {dest_folder} (Concurrency: {concurrency})")
            coll = self.local_plexamp_collection or {}
            stats = self.local_plexamp_pipeline.process_batch(
                collection=coll,
                selected_tracks=selected_tracks,
                base_music_dir=dest_folder,
                output_format_option=raw_fmt,
                folder_structure=folder_struct,
                move_files=move_files,
                embed_art=embed_art,
                save_cover_file=True,
                fetch_lyrics=fetch_lyrics,
                calculate_replaygain=calc_replaygain,
                auto_enrich=auto_enrich,
                concurrency=concurrency
            )
            self.after(0, lambda: self.finish_local_sync(stats))

        threading.Thread(target=run_pipeline, daemon=True).start()

    def stop_local_sync(self):
        """ Cancels the active Local import pipeline """
        if self.local_plexamp_pipeline:
            self.local_plexamp_pipeline.cancel()
            self.local_status_lbl.configure(text="Import cancelled by user.", text_color="#FB7185")
            self.power_light.configure(text="● STOPPED", text_color="#FB7185")
            self.reset_local_sync_button()

    def finish_local_sync(self, stats):
        completed = stats.get("completed", 0)
        failed = stats.get("failed", 0)
        self.log(f"🏁 Local Import finished: {completed} ready in Plex library, {failed} errors.")
        self.send_notification("Local Import Complete", f"{completed} tracks ready for Plexamp!")
        self.local_status_lbl.configure(
            text=f"✓ Complete! {completed} tracks ready for Plexamp. ({failed} errors)",
            text_color=getattr(self, 'theme_cfg', {}).get("accent", "#00E5FF") if failed == 0 else "#FB7185"
        )
        self.reset_local_sync_button()

    def reset_local_sync_button(self):
        self.btn_local_start.configure(state="normal", text="🚀  Import & Tag for Plexamp")
        self.update_taskbar_progress(0)
        self.power_light.configure(
            text=getattr(self, 'theme_cfg', {}).get("status_text", "● READY"),
            text_color=getattr(self, 'theme_cfg', {}).get("status_color", "#38BDF8")
        )
