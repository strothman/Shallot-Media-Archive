import atexit
from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import threading
import urllib.parse
import urllib.request

import customtkinter as ctk
from PIL import Image
import pystray
from spotify_sync import SpotifyFetcher, SpotifyPlexampPipeline

# --- Setup System PATH for Bundled JS Runtimes (e.g., deno.exe, ffmpeg.exe) ---
base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
for path in [base_path, exe_dir]:
    if path and os.path.abspath(path) not in [os.path.abspath(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p]:
        os.environ["PATH"] = os.path.abspath(path) + os.pathsep + os.environ.get("PATH", "")


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class DownloaderApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Shallot Media Archive")
        
        # --- Process & Lifecycle Management ---
        self.active_process = None
        self.is_cancelled = False
        atexit.register(self.emergency_process_cleanup)

        # --- Spotify Sync State ---
        self.spotify_collection = None
        self.spotify_track_items = []
        self.spotify_pipeline = None
        self.spotify_art_image = None

        # --- Custom Window Icon ---
        icon_path = self.get_file_path("icon.ico")
        if os.path.exists(icon_path):
            self.iconbitmap(icon_path)

        # --- System Tray & Close Behavior ---
        self.tray_icon = None
        self.protocol("WM_DELETE_WINDOW", self.on_close_window)
        self.init_system_tray()

        width, height = 960, 640
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.configure(fg_color="#070F15")
        self.minsize(900, 600)

        # --- Load Saved Preferences ---
        self.saved_settings = self.load_saved_settings()

        # --- Theme Widget Registry ---
        self.theme_titles = []
        self.theme_labels_secondary = []
        self.theme_entries = []
        self.theme_switches = []
        self.theme_option_menus = []
        self.theme_buttons_secondary = []
        self.page_titles = []

        # --- Left Sidebar ---
        self.sidebar_frame = ctk.CTkFrame(self, corner_radius=0, width=210)
        self.sidebar_frame.pack(side="left", fill="y")
        self.sidebar_frame.pack_propagate(False)

        self.logo_label = ctk.CTkLabel(
            self.sidebar_frame, 
            text="SMArchive", 
            font=("Segoe UI", 22, "bold"), 
            text_color="#00E5FF",
            anchor="w"
        )
        self.logo_label.pack(padx=25, pady=(24, 2), anchor="w")

        self.power_light = ctk.CTkLabel(
            self.sidebar_frame,
            text="● READY",
            font=("Segoe UI", 11, "bold"),
            text_color="#00F2FE",
            anchor="w"
        )
        self.power_light.pack(padx=25, pady=(0, 24), anchor="w")

        # Sidebar Buttons
        self.btn_download = ctk.CTkButton(
            self.sidebar_frame,
            text="📥  Download Media",
            font=("Segoe UI", 12, "bold"),
            height=38,
            corner_radius=8,
            anchor="w",
            command=lambda: self.select_tab("download")
        )
        self.btn_download.pack(fill="x", padx=15, pady=4)

        self.btn_search = ctk.CTkButton(
            self.sidebar_frame,
            text="🔍  Search YouTube",
            font=("Segoe UI", 12, "bold"),
            height=38,
            corner_radius=8,
            anchor="w",
            command=lambda: self.select_tab("search")
        )
        self.btn_search.pack(fill="x", padx=15, pady=4)

        self.btn_spotify = ctk.CTkButton(
            self.sidebar_frame,
            text="🎵  Spotify to Plexamp",
            font=("Segoe UI", 12, "bold"),
            height=38,
            corner_radius=8,
            anchor="w",
            command=lambda: self.select_tab("spotify")
        )
        self.btn_spotify.pack(fill="x", padx=15, pady=4)

        self.btn_settings = ctk.CTkButton(
            self.sidebar_frame,
            text="⚙️  Settings & Tools",
            font=("Segoe UI", 12, "bold"),
            height=38,
            corner_radius=8,
            anchor="w",
            command=lambda: self.select_tab("settings")
        )
        self.btn_settings.pack(fill="x", padx=15, pady=4)

        self.btn_logs = ctk.CTkButton(
            self.sidebar_frame,
            text="📜  Console Logs",
            font=("Segoe UI", 12, "bold"),
            height=38,
            corner_radius=8,
            anchor="w",
            command=lambda: self.select_tab("logs")
        )
        self.btn_logs.pack(fill="x", padx=15, pady=4)

        # --- Main Frame ---
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.pack(side="right", fill="both", expand=True)

        # =========================================================================
        # --- Page 1: Download Page ---
        # =========================================================================
        self.download_page = ctk.CTkFrame(self.main_container, fg_color="transparent")
        
        lbl_p1 = ctk.CTkLabel(self.download_page, text="Download Media", font=("Segoe UI", 18, "bold"), anchor="w")
        lbl_p1.pack(fill="x", padx=20, pady=(15, 10))
        self.page_titles.append(lbl_p1)

        # Card 1: Input / Source
        self.input_card = ctk.CTkFrame(self.download_page, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.input_card.pack(fill="x", padx=20, pady=6)
        
        card1_lbl = ctk.CTkLabel(self.input_card, text="INPUT / SOURCE", font=("Segoe UI", 11, "bold"), text_color="#00E5FF")
        card1_lbl.pack(anchor="w", padx=15, pady=(8, 3))
        self.theme_titles.append(card1_lbl)

        # Source URL with Paste Button
        lbl_src = ctk.CTkLabel(self.input_card, text="SOURCE URL", font=("Segoe UI", 10, "bold"), text_color="#78909C")
        lbl_src.pack(anchor="w", padx=15, pady=(4, 0))
        self.theme_labels_secondary.append(lbl_src)
        
        self.url_frame = ctk.CTkFrame(self.input_card, fg_color="transparent")
        self.url_frame.pack(fill="x", padx=15, pady=(2, 4))

        self.url_input = ctk.CTkEntry(
            self.url_frame, 
            placeholder_text="Paste YouTube Link...", 
            height=32, 
            fg_color="#070F15", 
            border_color="#1F3A4E", 
            text_color="#F5F5F7", 
            placeholder_text_color="#78909C"
        )
        self.url_input.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.theme_entries.append(self.url_input)

        self.paste_btn = ctk.CTkButton(
            self.url_frame,
            text="📋 Paste",
            width=70,
            height=32,
            font=("Segoe UI", 10, "bold"),
            command=self.paste_url
        )
        self.paste_btn.pack(side="right")
        self.theme_buttons_secondary.append(self.paste_btn)
        
        # Destination Folder with Browse Button
        lbl_dst = ctk.CTkLabel(self.input_card, text="DESTINATION FOLDER", font=("Segoe UI", 10, "bold"), text_color="#78909C")
        lbl_dst.pack(anchor="w", padx=15, pady=(4, 0))
        self.theme_labels_secondary.append(lbl_dst)
        
        self.folder_frame = ctk.CTkFrame(self.input_card, fg_color="transparent")
        self.folder_frame.pack(fill="x", padx=15, pady=(2, 10))

        default_folder = self.saved_settings.get("destination_folder", r"C:\SMA-downloads")
        self.folder_input = ctk.CTkEntry(
            self.folder_frame, 
            placeholder_text=r"C:\SMA-downloads", 
            height=32, 
            fg_color="#070F15", 
            border_color="#1F3A4E", 
            text_color="#F5F5F7", 
            placeholder_text_color="#78909C"
        )
        self.folder_input.insert(0, default_folder)
        self.folder_input.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.folder_input.bind("<FocusOut>", lambda e: self.save_setting("destination_folder", self.folder_input.get().strip()))
        self.folder_input.bind("<KeyRelease>", lambda e: self.save_setting("destination_folder", self.folder_input.get().strip()))
        self.theme_entries.append(self.folder_input)

        self.browse_btn = ctk.CTkButton(
            self.folder_frame,
            text="📁 Browse",
            width=70,
            height=32,
            font=("Segoe UI", 10, "bold"),
            command=self.browse_folder
        )
        self.browse_btn.pack(side="right")
        self.theme_buttons_secondary.append(self.browse_btn)

        # Options Card (Switches / Avatar)
        self.options_card = ctk.CTkFrame(self.download_page, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.options_card.pack(fill="x", padx=20, pady=6)
        
        card3_lbl = ctk.CTkLabel(self.options_card, text="DOWNLOAD OPTIONS", font=("Segoe UI", 11, "bold"), text_color="#00E5FF")
        card3_lbl.pack(anchor="w", padx=15, pady=(6, 2))
        self.theme_titles.append(card3_lbl)
        
        self.switches_container = ctk.CTkFrame(self.options_card, fg_color="transparent")
        self.switches_container.pack(fill="x", padx=15, pady=(2, 8))
        
        self.avatar_label = ctk.CTkLabel(self.switches_container, text="", width=54, height=54, fg_color="#070F15", corner_radius=8)
        self.avatar_label.pack(side="left", padx=(0, 15))
        self.avatar_image = None
        
        self.switches_subframe = ctk.CTkFrame(self.switches_container, fg_color="transparent")
        self.switches_subframe.pack(side="left", fill="both", expand=True)
        self.switches_subframe.columnconfigure(0, weight=1)
        self.switches_subframe.columnconfigure(1, weight=1)
        self.switches_subframe.columnconfigure(2, weight=1)
        
        # Row 0
        self.audio_switch = ctk.CTkSwitch(self.switches_subframe, text="Audio Only", progress_color="#00E5FF", text_color="#F5F5F7", font=("Segoe UI", 10))
        self.audio_switch.grid(row=0, column=0, padx=2, pady=1, sticky="w")
        self.theme_switches.append(self.audio_switch)
        
        self.subtitles_switch = ctk.CTkSwitch(self.switches_subframe, text="Subtitles", progress_color="#00E5FF", text_color="#F5F5F7", font=("Segoe UI", 10))
        self.subtitles_switch.grid(row=0, column=1, padx=2, pady=1, sticky="w")
        self.theme_switches.append(self.subtitles_switch)

        self.date_switch = ctk.CTkSwitch(self.switches_subframe, text="Upload Date", progress_color="#00E5FF", text_color="#F5F5F7", font=("Segoe UI", 10))
        self.date_switch.select()
        self.date_switch.grid(row=0, column=2, padx=2, pady=1, sticky="w")
        self.theme_switches.append(self.date_switch)
        
        # Row 1
        self.metadata_switch = ctk.CTkSwitch(self.switches_subframe, text="Metadata", progress_color="#00E5FF", text_color="#F5F5F7", font=("Segoe UI", 10))
        self.metadata_switch.grid(row=1, column=0, padx=2, pady=1, sticky="w")
        self.theme_switches.append(self.metadata_switch)
        
        self.open_folder_switch = ctk.CTkSwitch(self.switches_subframe, text="Auto Open", progress_color="#00E5FF", text_color="#F5F5F7", font=("Segoe UI", 10))
        self.open_folder_switch.select()
        self.open_folder_switch.grid(row=1, column=1, padx=2, pady=1, sticky="w")
        self.theme_switches.append(self.open_folder_switch)

        self.archive_switch = ctk.CTkSwitch(self.switches_subframe, text="Resume Archive", progress_color="#00E5FF", text_color="#F5F5F7", font=("Segoe UI", 10))
        self.archive_switch.select()
        self.archive_switch.grid(row=1, column=2, padx=2, pady=1, sticky="w")
        self.theme_switches.append(self.archive_switch)

        # Action Card (Download Start / Cancel / Season / Range / Speed)
        self.action_card = ctk.CTkFrame(self.download_page, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.action_card.pack(fill="x", padx=20, pady=6)
        
        self.action_frame = ctk.CTkFrame(self.action_card, fg_color="transparent")
        self.action_frame.pack(fill="x", padx=15, pady=(10, 10))
        
        # Col 0: Season Number
        self.season_frame = ctk.CTkFrame(self.action_frame, fg_color="transparent")
        self.season_frame.grid(row=0, column=0, padx=(0, 4), sticky="ew")
        
        self.season_checkbox = ctk.CTkCheckBox(
            self.season_frame, 
            text="Season", 
            font=("Segoe UI", 10),
            width=16,
            height=16,
            checkbox_width=14,
            checkbox_height=14,
            fg_color="#028090",
            hover_color="#00A896",
            checkmark_color="#070F15",
            text_color="#78909C",
            command=self.toggle_season_input
        )
        self.season_checkbox.pack(side="left", padx=(0, 4), anchor="center")
        self.season_input = ctk.CTkEntry(self.season_frame, width=45, height=26, fg_color="#070F15", border_color="#1F3A4E", text_color="#F5F5F7", justify="center")
        self.season_input.insert(0, "1")
        self.season_input.configure(state="disabled")
        self.season_input.pack(side="left", anchor="center")
        self.season_checkbox.deselect()
        self.theme_entries.append(self.season_input)

        # Col 1: Items Range
        self.range_frame = ctk.CTkFrame(self.action_frame, fg_color="transparent")
        self.range_frame.grid(row=0, column=1, padx=4, sticky="ew")
        
        self.range_checkbox = ctk.CTkCheckBox(
            self.range_frame, 
            text="Items", 
            font=("Segoe UI", 10),
            width=16,
            height=16,
            checkbox_width=14,
            checkbox_height=14,
            fg_color="#028090",
            hover_color="#00A896",
            checkmark_color="#070F15",
            text_color="#78909C",
            command=self.toggle_range_input
        )
        self.range_checkbox.pack(side="left", padx=(0, 4), anchor="center")
        self.range_input = ctk.CTkEntry(self.range_frame, placeholder_text="1:50", width=60, height=26, fg_color="#070F15", border_color="#1F3A4E", text_color="#F5F5F7", justify="center")
        self.range_input.configure(state="disabled")
        self.range_input.pack(side="left", anchor="center")
        self.range_checkbox.deselect()
        self.theme_entries.append(self.range_input)

        # Col 2: Start Button / Progress / Cancel Container
        self.btn_container = ctk.CTkFrame(self.action_frame, width=170, height=42, fg_color="transparent")
        self.btn_container.grid(row=0, column=2, padx=4, sticky="nsew")
        self.btn_container.pack_propagate(False)
        self.btn_container.grid_propagate(False)
        
        self.download_button = ctk.CTkButton(
            self.btn_container, 
            text="START DOWNLOAD", 
            fg_color="#082A36", 
            border_color="#00E5FF",
            border_width=2,
            hover_color="#0D3F52", 
            text_color="#00E5FF",
            font=("Segoe UI", 11, "bold"),
            width=170,
            height=42,
            corner_radius=8,
            command=self.start_download
        )
        self.download_button.place(x=0, y=0)
 
        self.progress_frame = ctk.CTkFrame(self.btn_container, fg_color="transparent", width=170, height=42)

        self.progress = ctk.CTkProgressBar(
            self.progress_frame,
            width=105,
            height=8,
            corner_radius=4,
            progress_color="#00E5FF",
            fg_color="#070F15"
        )
        self.progress.set(0)
        self.progress.place(relx=0.35, rely=0.35, anchor="center")
 
        self.progress_label = ctk.CTkLabel(
            self.progress_frame,
            text="0%",
            font=("Segoe UI", 10, "bold"),
            text_color="#F5F5F7",
            fg_color="transparent"
        )
        self.progress_label.place(relx=0.35, rely=0.75, anchor="center")

        self.cancel_button = ctk.CTkButton(
            self.progress_frame,
            text="⏹ Stop",
            width=48,
            height=28,
            corner_radius=6,
            fg_color="#3B1214",
            hover_color="#5C1D20",
            border_color="#FB7185",
            border_width=1,
            text_color="#FB7185",
            font=("Segoe UI", 10, "bold"),
            command=self.stop_download
        )
        self.cancel_button.place(relx=0.83, rely=0.5, anchor="center")
        
        # Col 3: Speed Limiter
        self.speed_frame = ctk.CTkFrame(self.action_frame, fg_color="transparent")
        self.speed_frame.grid(row=0, column=3, padx=(4, 0), sticky="ew")
        self.speed_lbl = ctk.CTkLabel(self.speed_frame, text="Speed (MB/s):", font=("Segoe UI", 10), text_color="#78909C")
        self.speed_lbl.pack(side="left", padx=(0, 4), anchor="center")
        self.theme_labels_secondary.append(self.speed_lbl)
        
        self.speed_input = ctk.CTkEntry(self.speed_frame, width=50, height=26, fg_color="#070F15", border_color="#1F3A4E", text_color="#F5F5F7", justify="center")
        self.speed_input.insert(0, "33")
        self.speed_input.pack(side="left", anchor="center")
        self.theme_entries.append(self.speed_input)
        
        # Grid configs
        self.action_frame.columnconfigure(0, weight=1)
        self.action_frame.columnconfigure(1, weight=1)
        self.action_frame.columnconfigure(2, weight=2)
        self.action_frame.columnconfigure(3, weight=1)

        # Queue Progress Card (hidden until download starts)
        self.queue_card = ctk.CTkFrame(self.download_page, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)

        queue_header_frame = ctk.CTkFrame(self.queue_card, fg_color="transparent")
        queue_header_frame.pack(fill="x", padx=15, pady=(8, 2))

        self.queue_title_lbl = ctk.CTkLabel(queue_header_frame, text="QUEUE PROGRESS", font=("Segoe UI", 11, "bold"), text_color="#00E5FF")
        self.queue_title_lbl.pack(side="left")
        self.theme_titles.append(self.queue_title_lbl)

        self.queue_counter_lbl = ctk.CTkLabel(queue_header_frame, text="0 / 0", font=("Segoe UI", 11, "bold"), text_color="#F5F5F7", anchor="e")
        self.queue_counter_lbl.pack(side="right")

        self.queue_item_lbl = ctk.CTkLabel(self.queue_card, text="Waiting...", font=("Segoe UI", 10), text_color="#78909C", anchor="w")
        self.queue_item_lbl.pack(fill="x", padx=15, pady=(2, 4))
        self.theme_labels_secondary.append(self.queue_item_lbl)

        self.queue_progress = ctk.CTkProgressBar(
            self.queue_card,
            height=8,
            corner_radius=4,
            progress_color="#00E5FF",
            fg_color="#070F15"
        )
        self.queue_progress.set(0)
        self.queue_progress.pack(fill="x", padx=15, pady=(0, 10))

        # =========================================================================
        # --- Page 2: Search Page ---
        # =========================================================================
        self.search_page = ctk.CTkFrame(self.main_container, fg_color="transparent")
        
        lbl_p2 = ctk.CTkLabel(self.search_page, text="Search YouTube", font=("Segoe UI", 18, "bold"), anchor="w")
        lbl_p2.pack(fill="x", padx=20, pady=(15, 10))
        self.page_titles.append(lbl_p2)

        # YouTube Search Frame
        self.search_frame = ctk.CTkFrame(self.search_page, fg_color="transparent")
        self.search_frame.pack(fill="x", padx=20, pady=4)
        
        self.search_input = ctk.CTkEntry(
            self.search_frame, 
            placeholder_text="Search YouTube...", 
            height=32, 
            fg_color="#070F15", 
            border_color="#1F3A4E", 
            text_color="#F5F5F7", 
            placeholder_text_color="#78909C"
        )
        self.search_input.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.search_input.bind("<Return>", lambda e: self.search_youtube())
        self.theme_entries.append(self.search_input)
        
        self.search_button = ctk.CTkButton(
            self.search_frame, 
            text="🔍 Search", 
            width=80, 
            height=32, 
            fg_color="#0E1A24", 
            border_color="#00E5FF", 
            border_width=1, 
            hover_color="#1F3A4E", 
            text_color="#00E5FF",
            font=("Segoe UI", 11, "bold"),
            command=self.search_youtube
        )
        self.search_button.pack(side="right")
        self.theme_buttons_secondary.append(self.search_button)

        # Scrollable results container
        self.results_frame = ctk.CTkScrollableFrame(
            self.search_page,
            fg_color="transparent",
            border_width=0
        )
        self.results_frame.pack(fill="both", expand=True, padx=20, pady=10)
        self.search_result_widgets = []

        # =========================================================================
        # --- Page 3: Spotify to Plexamp Page ---
        # =========================================================================
        self.spotify_page = ctk.CTkFrame(self.main_container, fg_color="transparent")

        lbl_spotify = ctk.CTkLabel(self.spotify_page, text="Spotify to Plexamp", font=("Segoe UI", 18, "bold"), anchor="w")
        lbl_spotify.pack(fill="x", padx=20, pady=(15, 8))
        self.page_titles.append(lbl_spotify)

        # Card 1: Input / Source
        self.spotify_input_card = ctk.CTkFrame(self.spotify_page, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.spotify_input_card.pack(fill="x", padx=20, pady=4)

        card_sp_lbl = ctk.CTkLabel(self.spotify_input_card, text="SPOTIFY SOURCE", font=("Segoe UI", 11, "bold"), text_color="#00E5FF")
        card_sp_lbl.pack(anchor="w", padx=15, pady=(8, 3))
        self.theme_titles.append(card_sp_lbl)

        self.spotify_url_frame = ctk.CTkFrame(self.spotify_input_card, fg_color="transparent")
        self.spotify_url_frame.pack(fill="x", padx=15, pady=(2, 8))

        self.spotify_url_input = ctk.CTkEntry(
            self.spotify_url_frame,
            placeholder_text="Paste Spotify Playlist, Album, or Track URL...",
            height=32,
            fg_color="#070F15",
            border_color="#1F3A4E",
            text_color="#F5F5F7",
            placeholder_text_color="#78909C"
        )
        self.spotify_url_input.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.spotify_url_input.bind("<Return>", lambda e: self.fetch_spotify_playlist())
        self.theme_entries.append(self.spotify_url_input)

        self.btn_spotify_paste = ctk.CTkButton(
            self.spotify_url_frame,
            text="📋 Paste",
            width=70,
            height=32,
            font=("Segoe UI", 10, "bold"),
            command=self.paste_spotify_url
        )
        self.btn_spotify_paste.pack(side="left", padx=(0, 6))
        self.theme_buttons_secondary.append(self.btn_spotify_paste)

        self.btn_spotify_fetch = ctk.CTkButton(
            self.spotify_url_frame,
            text="⚡ Fetch Tracks",
            width=100,
            height=32,
            font=("Segoe UI", 10, "bold"),
            command=self.fetch_spotify_playlist
        )
        self.btn_spotify_fetch.pack(side="right")
        self.theme_buttons_secondary.append(self.btn_spotify_fetch)

        # Card 2: Collection Overview & Plexamp Options
        self.spotify_meta_card = ctk.CTkFrame(self.spotify_page, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.spotify_meta_card.pack(fill="x", padx=20, pady=4)

        card_meta_lbl = ctk.CTkLabel(self.spotify_meta_card, text="COLLECTION & PLEXAMP CONFIGURATION", font=("Segoe UI", 11, "bold"), text_color="#00E5FF")
        card_meta_lbl.pack(anchor="w", padx=15, pady=(8, 4))
        self.theme_titles.append(card_meta_lbl)

        meta_grid = ctk.CTkFrame(self.spotify_meta_card, fg_color="transparent")
        meta_grid.pack(fill="x", padx=15, pady=(2, 8))
        meta_grid.columnconfigure(0, weight=0)
        meta_grid.columnconfigure(1, weight=1)
        meta_grid.columnconfigure(2, weight=2)

        # Col 0: Artwork preview
        self.spotify_art_frame = ctk.CTkFrame(meta_grid, width=64, height=64, fg_color="#070F15", corner_radius=8, border_color="#1F3A4E", border_width=1)
        self.spotify_art_frame.grid(row=0, column=0, rowspan=2, padx=(0, 10), pady=2, sticky="nw")
        self.spotify_art_frame.pack_propagate(False)

        placeholder_art = Image.new('RGB', (64, 64), color='#1E1A24')
        self.spotify_art_img = ctk.CTkImage(light_image=placeholder_art, dark_image=placeholder_art, size=(64, 64))
        self.spotify_art_label = ctk.CTkLabel(self.spotify_art_frame, image=self.spotify_art_img, text="")
        self.spotify_art_label.pack(expand=True, fill="both")

        # Col 1: Collection Info
        info_frame = ctk.CTkFrame(meta_grid, fg_color="transparent")
        info_frame.grid(row=0, column=1, rowspan=2, padx=(0, 10), sticky="nsew")

        self.spotify_title_lbl = ctk.CTkLabel(info_frame, text="No Spotify Link Loaded", font=("Segoe UI", 12, "bold"), text_color="#F5F5F7", anchor="w")
        self.spotify_title_lbl.pack(fill="x", pady=(0, 1))

        self.spotify_author_lbl = ctk.CTkLabel(info_frame, text="Paste a link & click 'Fetch Tracks'", font=("Segoe UI", 10), text_color="#78909C", anchor="w")
        self.spotify_author_lbl.pack(fill="x", pady=(0, 1))
        self.theme_labels_secondary.append(self.spotify_author_lbl)

        self.spotify_stats_lbl = ctk.CTkLabel(info_frame, text="0 tracks found", font=("Segoe UI", 10, "bold"), text_color="#00E5FF", anchor="w")
        self.spotify_stats_lbl.pack(fill="x")
        self.theme_titles.append(self.spotify_stats_lbl)

        # Col 2: Destination & Options
        cfg_frame = ctk.CTkFrame(meta_grid, fg_color="transparent")
        cfg_frame.grid(row=0, column=2, rowspan=2, sticky="nsew")

        # Music Folder row
        fld_row = ctk.CTkFrame(cfg_frame, fg_color="transparent")
        fld_row.pack(fill="x", pady=(0, 4))
        lbl_pfld = ctk.CTkLabel(fld_row, text="Music Library:", font=("Segoe UI", 10, "bold"), text_color="#78909C", width=80, anchor="w")
        lbl_pfld.pack(side="left")
        self.theme_labels_secondary.append(lbl_pfld)

        default_plex_dir = self.saved_settings.get("plex_music_folder", r"C:\SMA-downloads\Music")
        self.spotify_folder_input = ctk.CTkEntry(fld_row, placeholder_text=r"C:\SMA-downloads\Music", height=28, fg_color="#070F15", border_color="#1F3A4E", text_color="#F5F5F7", font=("Segoe UI", 10))
        self.spotify_folder_input.insert(0, default_plex_dir)
        self.spotify_folder_input.pack(side="left", fill="x", expand=True, padx=(4, 4))
        self.spotify_folder_input.bind("<FocusOut>", lambda e: self.save_setting("plex_music_folder", self.spotify_folder_input.get().strip()))
        self.spotify_folder_input.bind("<KeyRelease>", lambda e: self.save_setting("plex_music_folder", self.spotify_folder_input.get().strip()))
        self.theme_entries.append(self.spotify_folder_input)

        self.btn_spotify_browse = ctk.CTkButton(fld_row, text="📂", width=32, height=28, font=("Segoe UI", 10, "bold"), command=self.browse_plex_folder)
        self.btn_spotify_browse.pack(side="right")
        self.theme_buttons_secondary.append(self.btn_spotify_browse)

        # Row 1: Format + Org + Concurrency
        opts_row1 = ctk.CTkFrame(cfg_frame, fg_color="transparent")
        opts_row1.pack(fill="x", pady=(0, 3))

        self.spotify_format_menu = ctk.CTkOptionMenu(
            opts_row1,
            values=["MP3 (320 kbps)", "FLAC (Lossless)", "M4A (256 kbps)"],
            height=28,
            font=("Segoe UI", 10),
            dropdown_font=("Segoe UI", 10),
            command=lambda v: self.save_setting("spotify_audio_format", v)
        )
        saved_sp_fmt = self.saved_settings.get("spotify_audio_format", "MP3 (320 kbps)")
        if saved_sp_fmt in self.spotify_format_menu._values:
            self.spotify_format_menu.set(saved_sp_fmt)
        self.spotify_format_menu.pack(side="left", padx=(0, 4))
        self.theme_option_menus.append(self.spotify_format_menu)

        self.spotify_org_menu = ctk.CTkOptionMenu(
            opts_row1,
            values=["Plex Standard (Artist/Album/Track)", "Playlist Folder (Playlists/Track)"],
            height=28,
            font=("Segoe UI", 10),
            dropdown_font=("Segoe UI", 10),
            command=lambda v: self.save_setting("spotify_folder_structure", v)
        )
        saved_sp_org = self.saved_settings.get("spotify_folder_structure", "Plex Standard (Artist/Album/Track)")
        if saved_sp_org in self.spotify_org_menu._values:
            self.spotify_org_menu.set(saved_sp_org)
        self.spotify_org_menu.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.theme_option_menus.append(self.spotify_org_menu)

        self.spotify_concurrency_menu = ctk.CTkOptionMenu(
            opts_row1,
            values=["2 Tracks Concurrent", "3 Tracks Concurrent", "1 Track Safe"],
            height=28,
            width=120,
            font=("Segoe UI", 9),
            dropdown_font=("Segoe UI", 9),
            command=lambda v: self.save_setting("spotify_concurrency", v)
        )
        saved_sp_conc = self.saved_settings.get("spotify_concurrency", "2 Tracks Concurrent")
        if saved_sp_conc in self.spotify_concurrency_menu._values:
            self.spotify_concurrency_menu.set(saved_sp_conc)
        self.spotify_concurrency_menu.pack(side="left")
        self.theme_option_menus.append(self.spotify_concurrency_menu)

        # Row 2: Toggles (Artwork, Synced Lyrics, ReplayGain)
        opts_row2 = ctk.CTkFrame(cfg_frame, fg_color="transparent")
        opts_row2.pack(fill="x", pady=(2, 0))

        self.spotify_embed_art_switch = ctk.CTkSwitch(
            opts_row2,
            text="Artwork",
            font=("Segoe UI", 9),
            width=58,
            height=18,
            command=lambda: self.save_setting("spotify_embed_art", bool(self.spotify_embed_art_switch.get()))
        )
        if self.saved_settings.get("spotify_embed_art", True):
            self.spotify_embed_art_switch.select()
        else:
            self.spotify_embed_art_switch.deselect()
        self.spotify_embed_art_switch.pack(side="left", padx=(0, 6))
        self.theme_switches.append(self.spotify_embed_art_switch)

        self.spotify_lyrics_switch = ctk.CTkSwitch(
            opts_row2,
            text="Lyrics (.lrc)",
            font=("Segoe UI", 9),
            width=70,
            height=18,
            command=lambda: self.save_setting("spotify_fetch_lyrics", bool(self.spotify_lyrics_switch.get()))
        )
        if self.saved_settings.get("spotify_fetch_lyrics", True):
            self.spotify_lyrics_switch.select()
        else:
            self.spotify_lyrics_switch.deselect()
        self.spotify_lyrics_switch.pack(side="left", padx=(0, 6))
        self.theme_switches.append(self.spotify_lyrics_switch)

        self.spotify_gain_switch = ctk.CTkSwitch(
            opts_row2,
            text="ReplayGain",
            font=("Segoe UI", 9),
            width=68,
            height=18,
            command=lambda: self.save_setting("spotify_calculate_replaygain", bool(self.spotify_gain_switch.get()))
        )
        if self.saved_settings.get("spotify_calculate_replaygain", True):
            self.spotify_gain_switch.select()
        else:
            self.spotify_gain_switch.deselect()
        self.spotify_gain_switch.pack(side="left")
        self.theme_switches.append(self.spotify_gain_switch)

        # Card 3: Tracklist Selection
        self.spotify_tracks_card = ctk.CTkFrame(self.spotify_page, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.spotify_tracks_card.pack(fill="both", expand=True, padx=20, pady=4)

        tracks_header = ctk.CTkFrame(self.spotify_tracks_card, fg_color="transparent")
        tracks_header.pack(fill="x", padx=15, pady=(8, 4))

        card_trk_lbl = ctk.CTkLabel(tracks_header, text="TRACKLIST SELECTION", font=("Segoe UI", 11, "bold"), text_color="#00E5FF")
        card_trk_lbl.pack(side="left")
        self.theme_titles.append(card_trk_lbl)

        self.spotify_track_count_lbl = ctk.CTkLabel(tracks_header, text="0 / 0 Selected", font=("Segoe UI", 10, "bold"), text_color="#78909C")
        self.spotify_track_count_lbl.pack(side="left", padx=12)
        self.theme_labels_secondary.append(self.spotify_track_count_lbl)

        self.btn_spotify_deselect_all = ctk.CTkButton(
            tracks_header,
            text="Deselect All",
            width=80,
            height=24,
            font=("Segoe UI", 9, "bold"),
            command=lambda: self.toggle_all_spotify_tracks(False)
        )
        self.btn_spotify_deselect_all.pack(side="right", padx=(4, 0))
        self.theme_buttons_secondary.append(self.btn_spotify_deselect_all)

        self.btn_spotify_select_all = ctk.CTkButton(
            tracks_header,
            text="Select All",
            width=70,
            height=24,
            font=("Segoe UI", 9, "bold"),
            command=lambda: self.toggle_all_spotify_tracks(True)
        )
        self.btn_spotify_select_all.pack(side="right")
        self.theme_buttons_secondary.append(self.btn_spotify_select_all)

        # Scrollable Tracklist Frame
        self.spotify_track_scroll = ctk.CTkScrollableFrame(self.spotify_tracks_card, fg_color="transparent", border_width=0)
        self.spotify_track_scroll.pack(fill="both", expand=True, padx=12, pady=(0, 6))

        self.spotify_empty_lbl = ctk.CTkLabel(
            self.spotify_track_scroll,
            text="No tracks loaded yet. Enter a Spotify URL above and click 'Fetch Tracks'.",
            font=("Segoe UI", 11),
            text_color="#78909C"
        )
        self.spotify_empty_lbl.pack(pady=30)
        self.theme_labels_secondary.append(self.spotify_empty_lbl)

        # Card 4: Action & Progress Card
        self.spotify_action_card = ctk.CTkFrame(self.spotify_page, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.spotify_action_card.pack(fill="x", padx=20, pady=(4, 10))

        sp_act_top = ctk.CTkFrame(self.spotify_action_card, fg_color="transparent")
        sp_act_top.pack(fill="x", padx=15, pady=(8, 2))

        self.spotify_status_lbl = ctk.CTkLabel(sp_act_top, text="Ready to sync", font=("Segoe UI", 10, "bold"), text_color="#78909C", anchor="w")
        self.spotify_status_lbl.pack(side="left")
        self.theme_labels_secondary.append(self.spotify_status_lbl)

        self.spotify_counter_lbl = ctk.CTkLabel(sp_act_top, text="0 / 0", font=("Segoe UI", 10, "bold"), text_color="#F5F5F7", anchor="e")
        self.spotify_counter_lbl.pack(side="right")

        self.spotify_progress_bar = ctk.CTkProgressBar(self.spotify_action_card, height=8, corner_radius=4, progress_color="#00E5FF", fg_color="#070F15")
        self.spotify_progress_bar.set(0)
        self.spotify_progress_bar.pack(fill="x", padx=15, pady=(2, 8))

        sp_act_btns = ctk.CTkFrame(self.spotify_action_card, fg_color="transparent")
        sp_act_btns.pack(fill="x", padx=15, pady=(0, 8))

        self.btn_spotify_start = ctk.CTkButton(
            sp_act_btns,
            text="🚀  Download & Tag for Plexamp",
            font=("Segoe UI", 12, "bold"),
            height=36,
            corner_radius=8,
            command=self.start_spotify_sync
        )
        self.btn_spotify_start.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.btn_spotify_open_folder = ctk.CTkButton(
            sp_act_btns,
            text="📂 Open Music Folder",
            font=("Segoe UI", 11, "bold"),
            height=36,
            width=140,
            corner_radius=8,
            fg_color="#0E1A24",
            border_color="#00E5FF",
            border_width=1,
            text_color="#00E5FF",
            command=self.open_spotify_music_folder
        )
        self.btn_spotify_open_folder.pack(side="left", padx=(0, 6))
        self.theme_buttons_secondary.append(self.btn_spotify_open_folder)

        self.btn_spotify_stop = ctk.CTkButton(
            sp_act_btns,
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
            command=self.stop_spotify_sync
        )
        self.btn_spotify_stop.pack(side="right")

        # =========================================================================
        # --- Page 4: Settings Page ---
        # =========================================================================
        self.settings_page = ctk.CTkFrame(self.main_container, fg_color="transparent")
        
        lbl_p3 = ctk.CTkLabel(self.settings_page, text="Settings & Tools", font=("Segoe UI", 18, "bold"), anchor="w")
        lbl_p3.pack(fill="x", padx=20, pady=(15, 10))
        self.page_titles.append(lbl_p3)

        self.quality_card = ctk.CTkFrame(self.settings_page, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.quality_card.pack(fill="x", padx=20, pady=6)
        
        card2_lbl = ctk.CTkLabel(self.quality_card, text="QUALITY & PREFERENCES", font=("Segoe UI", 11, "bold"), text_color="#00E5FF")
        card2_lbl.pack(anchor="w", padx=15, pady=(8, 4))
        self.theme_titles.append(card2_lbl)
        
        self.quality_grid = ctk.CTkFrame(self.quality_card, fg_color="transparent")
        self.quality_grid.pack(fill="x", padx=15, pady=(2, 10))
        self.quality_grid.columnconfigure(0, weight=1)
        self.quality_grid.columnconfigure(1, weight=1)
        self.quality_grid.columnconfigure(2, weight=1)
        
        # Row 0, Col 0: Video Quality
        video_frame = ctk.CTkFrame(self.quality_grid, fg_color="transparent")
        video_frame.grid(row=0, column=0, sticky="ew", padx=(0, 4), pady=(0, 6))
        lbl_vid = ctk.CTkLabel(video_frame, text="Video Quality", font=("Segoe UI", 11), text_color="#78909C")
        lbl_vid.pack(anchor="w")
        self.theme_labels_secondary.append(lbl_vid)
        
        self.video_quality = ctk.CTkOptionMenu(
            video_frame, 
            values=["Best / 4K (2160p)", "1440p (2K)", "1080p (FHD)", "720p (HD)", "480p (SD)"],
            height=32,
            button_color="#028090", 
            button_hover_color="#00A896", 
            fg_color="#070F15", 
            dropdown_fg_color="#0E1A24", 
            text_color="#F5F5F7",
            dropdown_text_color="#F5F5F7",
            dropdown_hover_color="#1F3A4E",
            command=lambda v: self.save_setting("video_quality", v)
        )
        saved_vid = self.saved_settings.get("video_quality", "1080p (FHD)")
        if saved_vid in self.video_quality._values:
            self.video_quality.set(saved_vid)
        else:
            self.video_quality.set("1080p (FHD)")
        self.video_quality.pack(fill="x", pady=(1, 0))
        self.theme_option_menus.append(self.video_quality)
        
        # Row 0, Col 1: Audio Quality / Bitrate
        audio_frame = ctk.CTkFrame(self.quality_grid, fg_color="transparent")
        audio_frame.grid(row=0, column=1, sticky="ew", padx=(4, 4), pady=(0, 6))
        lbl_aud = ctk.CTkLabel(audio_frame, text="Audio Bitrate", font=("Segoe UI", 11), text_color="#78909C")
        lbl_aud.pack(anchor="w")
        self.theme_labels_secondary.append(lbl_aud)
        
        self.audio_quality = ctk.CTkOptionMenu(
            audio_frame, 
            values=["Best (320 kbps)", "Standard (192 kbps)", "Compact (128 kbps)"],
            height=32,
            button_color="#028090", 
            button_hover_color="#00A896", 
            fg_color="#070F15", 
            dropdown_fg_color="#0E1A24", 
            text_color="#F5F5F7",
            dropdown_text_color="#F5F5F7",
            dropdown_hover_color="#1F3A4E",
            command=lambda v: self.save_setting("audio_quality", v)
        )
        saved_aud = self.saved_settings.get("audio_quality", "Best (320 kbps)")
        if saved_aud in self.audio_quality._values:
            self.audio_quality.set(saved_aud)
        else:
            self.audio_quality.set("Best (320 kbps)")
        self.audio_quality.pack(fill="x", pady=(1, 0))
        self.theme_option_menus.append(self.audio_quality)
 
        # Row 0, Col 2: Audio Format
        format_frame = ctk.CTkFrame(self.quality_grid, fg_color="transparent")
        format_frame.grid(row=0, column=2, sticky="ew", padx=(4, 0), pady=(0, 6))
        lbl_fmt = ctk.CTkLabel(format_frame, text="Audio Format", font=("Segoe UI", 11), text_color="#78909C")
        lbl_fmt.pack(anchor="w")
        self.theme_labels_secondary.append(lbl_fmt)

        self.audio_format_menu = ctk.CTkOptionMenu(
            format_frame,
            values=["MP3", "M4A (AAC)", "FLAC (Lossless)", "WAV", "OPUS"],
            height=32,
            button_color="#028090",
            button_hover_color="#00A896",
            fg_color="#070F15",
            dropdown_fg_color="#0E1A24",
            text_color="#F5F5F7",
            dropdown_text_color="#F5F5F7",
            dropdown_hover_color="#1F3A4E",
            command=lambda v: self.save_setting("audio_format", v)
        )
        saved_afmt = self.saved_settings.get("audio_format", "MP3")
        if saved_afmt in self.audio_format_menu._values:
            self.audio_format_menu.set(saved_afmt)
        else:
            self.audio_format_menu.set("MP3")
        self.audio_format_menu.pack(fill="x", pady=(1, 0))
        self.theme_option_menus.append(self.audio_format_menu)

        # Row 1, Col 0: App Theme selector
        theme_frame = ctk.CTkFrame(self.quality_grid, fg_color="transparent")
        theme_frame.grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=(6, 0))
        lbl_thm = ctk.CTkLabel(theme_frame, text="App Theme", font=("Segoe UI", 11), text_color="#78909C")
        lbl_thm.pack(anchor="w")
        self.theme_labels_secondary.append(lbl_thm)
        
        self.theme_menu = ctk.CTkOptionMenu(
            theme_frame,
            values=["Obsidian", "Vapor", "Arctic", "Ember", "Twilight", "Cipher"],
            height=32,
            button_color="#028090",
            button_hover_color="#00A896",
            fg_color="#070F15",
            dropdown_fg_color="#0E1A24",
            text_color="#F5F5F7",
            dropdown_text_color="#F5F5F7",
            dropdown_hover_color="#1F3A4E",
            command=self.apply_theme
        )
        saved_theme = self.saved_settings.get("theme", "Obsidian")
        self.theme_menu.set(saved_theme)
        self.theme_menu.pack(fill="x", pady=(1, 0))
        self.theme_option_menus.append(self.theme_menu)

        # Row 1, Col 1: Cookie Source selector
        cookie_src_frame = ctk.CTkFrame(self.quality_grid, fg_color="transparent")
        cookie_src_frame.grid(row=1, column=1, sticky="ew", padx=(4, 4), pady=(6, 0))
        lbl_csrc = ctk.CTkLabel(cookie_src_frame, text="Cookie Source", font=("Segoe UI", 11), text_color="#78909C")
        lbl_csrc.pack(anchor="w")
        self.theme_labels_secondary.append(lbl_csrc)

        self.cookie_source_menu = ctk.CTkOptionMenu(
            cookie_src_frame,
            values=["cookies.txt (File)", "Chrome", "Edge", "Firefox", "Brave", "Opera", "Vivaldi"],
            height=32,
            button_color="#028090",
            button_hover_color="#00A896",
            fg_color="#070F15",
            dropdown_fg_color="#0E1A24",
            text_color="#F5F5F7",
            dropdown_text_color="#F5F5F7",
            dropdown_hover_color="#1F3A4E",
            command=lambda v: self.save_setting("cookie_source", v)
        )
        saved_csrc = self.saved_settings.get("cookie_source", "cookies.txt (File)")
        if saved_csrc in self.cookie_source_menu._values:
            self.cookie_source_menu.set(saved_csrc)
        else:
            self.cookie_source_menu.set("cookies.txt (File)")
        self.cookie_source_menu.pack(fill="x", pady=(1, 0))
        self.theme_option_menus.append(self.cookie_source_menu)

        # Row 1, Col 2: Notifications Switch
        notif_frame = ctk.CTkFrame(self.quality_grid, fg_color="transparent")
        notif_frame.grid(row=1, column=2, sticky="ew", padx=(4, 0), pady=(6, 0))
        lbl_notif = ctk.CTkLabel(notif_frame, text="Desktop Alerts", font=("Segoe UI", 11), text_color="#78909C")
        lbl_notif.pack(anchor="w")
        self.theme_labels_secondary.append(lbl_notif)

        self.notif_switch = ctk.CTkSwitch(
            notif_frame, 
            text="Notifications", 
            progress_color="#00E5FF", 
            text_color="#F5F5F7", 
            font=("Segoe UI", 10),
            command=lambda: self.save_setting("notifications_enabled", bool(self.notif_switch.get()))
        )
        if self.saved_settings.get("notifications_enabled", True):
            self.notif_switch.select()
        else:
            self.notif_switch.deselect()
        self.notif_switch.pack(anchor="w", pady=(6, 0))
        self.theme_switches.append(self.notif_switch)

        # Spotify & Plexamp Settings Card
        self.spotify_settings_card = ctk.CTkFrame(self.settings_page, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.spotify_settings_card.pack(fill="x", padx=20, pady=6)

        card_sp_set_lbl = ctk.CTkLabel(self.spotify_settings_card, text="SPOTIFY & PLEXAMP PREFERENCES", font=("Segoe UI", 11, "bold"), text_color="#00E5FF")
        card_sp_set_lbl.pack(anchor="w", padx=15, pady=(8, 4))
        self.theme_titles.append(card_sp_set_lbl)

        sp_set_grid = ctk.CTkFrame(self.spotify_settings_card, fg_color="transparent")
        sp_set_grid.pack(fill="x", padx=15, pady=(2, 10))
        sp_set_grid.columnconfigure(0, weight=1)
        sp_set_grid.columnconfigure(1, weight=1)

        # Col 0: Spotify Client ID (Optional)
        cid_frame = ctk.CTkFrame(sp_set_grid, fg_color="transparent")
        cid_frame.grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=(0, 4))
        lbl_cid = ctk.CTkLabel(cid_frame, text="Spotify Client ID (Optional)", font=("Segoe UI", 11), text_color="#78909C")
        lbl_cid.pack(anchor="w")
        self.theme_labels_secondary.append(lbl_cid)

        self.spotify_cid_entry = ctk.CTkEntry(
            cid_frame,
            placeholder_text="Enter Spotify Client ID for high rate limits...",
            height=30,
            fg_color="#070F15",
            border_color="#1F3A4E",
            text_color="#F5F5F7"
        )
        saved_cid = self.saved_settings.get("spotify_client_id", "")
        if saved_cid:
            self.spotify_cid_entry.insert(0, saved_cid)
        self.spotify_cid_entry.pack(fill="x", pady=(1, 0))
        self.spotify_cid_entry.bind("<FocusOut>", lambda e: self.save_setting("spotify_client_id", self.spotify_cid_entry.get().strip()))
        self.theme_entries.append(self.spotify_cid_entry)

        # Col 1: Spotify Client Secret (Optional)
        csec_frame = ctk.CTkFrame(sp_set_grid, fg_color="transparent")
        csec_frame.grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=(0, 4))
        lbl_csec = ctk.CTkLabel(csec_frame, text="Spotify Client Secret (Optional)", font=("Segoe UI", 11), text_color="#78909C")
        lbl_csec.pack(anchor="w")
        self.theme_labels_secondary.append(lbl_csec)

        self.spotify_csec_entry = ctk.CTkEntry(
            csec_frame,
            placeholder_text="Enter Spotify Client Secret...",
            height=30,
            show="•",
            fg_color="#070F15",
            border_color="#1F3A4E",
            text_color="#F5F5F7"
        )
        saved_csec = self.saved_settings.get("spotify_client_secret", "")
        if saved_csec:
            self.spotify_csec_entry.insert(0, saved_csec)
        self.spotify_csec_entry.pack(fill="x", pady=(1, 0))
        self.spotify_csec_entry.bind("<FocusOut>", lambda e: self.save_setting("spotify_client_secret", self.spotify_csec_entry.get().strip()))
        self.theme_entries.append(self.spotify_csec_entry)

        # Tools Card (Upload Cookies, Update Engine, Open Error Log)
        self.tools_card = ctk.CTkFrame(self.settings_page, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.tools_card.pack(fill="x", padx=20, pady=6)

        card_tools_lbl = ctk.CTkLabel(self.tools_card, text="UTILITIES", font=("Segoe UI", 11, "bold"), text_color="#00E5FF")
        card_tools_lbl.pack(anchor="w", padx=15, pady=(8, 4))
        self.theme_titles.append(card_tools_lbl)

        self.tools_frame = ctk.CTkFrame(self.tools_card, fg_color="transparent")
        self.tools_frame.pack(fill="x", padx=15, pady=(2, 10))
        self.tools_frame.columnconfigure(0, weight=1)
        self.tools_frame.columnconfigure(1, weight=1)
        self.tools_frame.columnconfigure(2, weight=1)
        
        self.update_cookies_btn = ctk.CTkButton(
            self.tools_frame,
            text="Upload Cookies",
            height=34,
            border_width=1,
            font=("Segoe UI", 11, "bold"),
            command=self.upload_cookies
        )
        self.update_cookies_btn.grid(row=0, column=0, padx=4, sticky="ew")
        self.theme_buttons_secondary.append(self.update_cookies_btn)

        self.update_ytdlp_btn = ctk.CTkButton(
            self.tools_frame,
            text="Update Engine",
            height=34,
            border_width=1,
            font=("Segoe UI", 11, "bold"),
            command=self.update_ytdlp
        )
        self.update_ytdlp_btn.grid(row=0, column=1, padx=4, sticky="ew")
        self.theme_buttons_secondary.append(self.update_ytdlp_btn)

        self.open_error_log_btn = ctk.CTkButton(
            self.tools_frame,
            text="Open Error Log",
            height=34,
            border_width=1,
            font=("Segoe UI", 11, "bold"),
            command=self.open_error_log
        )
        self.open_error_log_btn.grid(row=0, column=2, padx=4, sticky="ew")
        self.theme_buttons_secondary.append(self.open_error_log_btn)

        # =========================================================================
        # --- Page 4: Console Logs Page ---
        # =========================================================================
        self.logs_page = ctk.CTkFrame(self.main_container, fg_color="transparent")
        
        # Header with Clear and Copy buttons
        logs_header_frame = ctk.CTkFrame(self.logs_page, fg_color="transparent")
        logs_header_frame.pack(fill="x", padx=20, pady=(15, 10))

        lbl_p4 = ctk.CTkLabel(logs_header_frame, text="Console Logs", font=("Segoe UI", 18, "bold"), anchor="w")
        lbl_p4.pack(side="left")
        self.page_titles.append(lbl_p4)

        self.btn_clear_logs = ctk.CTkButton(
            logs_header_frame,
            text="🗑 Clear Logs",
            width=90,
            height=30,
            font=("Segoe UI", 10, "bold"),
            command=self.clear_logs
        )
        self.btn_clear_logs.pack(side="right", padx=(6, 0))
        self.theme_buttons_secondary.append(self.btn_clear_logs)

        self.btn_copy_logs = ctk.CTkButton(
            logs_header_frame,
            text="📋 Copy Logs",
            width=90,
            height=30,
            font=("Segoe UI", 10, "bold"),
            command=self.copy_logs
        )
        self.btn_copy_logs.pack(side="right")
        self.theme_buttons_secondary.append(self.btn_copy_logs)

        # Status box (styled logs text box)
        self.status_box = ctk.CTkTextbox(
            self.logs_page, 
            fg_color="#070F15", 
            border_color="#1F3A4E", 
            border_width=1, 
            text_color="#9E9EAF"
        )
        self.status_box.pack(fill="both", expand=True, padx=20, pady=(2, 20))
        
        self.log_visible = False
        self.search_visible = False
        
        # --- Taskbar Progress & Tray Icon Initialization ---
        self.taskbar = None
        self.selected_search_card = None
        try:
            import comtypes.client as cc
            cc.GetModule("shobjidl.tlb")
            import comtypes.gen.TaskbarLib as tbl  # type: ignore # pylint: disable=import-error,no-name-in-module
            tb = cc.CreateObject("{56FDF344-FD6D-11d0-958A-006097C9A090}", interface=tbl.ITaskbarList3)
            if tb is not None:
                tb.HrInit()
                self.taskbar = tb
        except Exception:
            self.taskbar = None
            
        self.apply_theme(saved_theme)
        self.select_tab("download")
        
        self.after(100, lambda: self.update_taskbar_progress(0))
        
        # Bring window to front
        self.lift()
        self.focus_force()

    # =========================================================================
    # --- Helper & Utility Methods ---
    # =========================================================================

    def emergency_process_cleanup(self):
        """ Guarantees all child processes (yt-dlp, ffmpeg) are terminated when exiting """
        if self.active_process:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(self.active_process.pid)],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            except Exception:
                try:
                    self.active_process.kill()
                except Exception:
                    pass

    def paste_url(self):
        """ Pastes clipboard contents into the URL input and loads avatar """
        try:
            clipboard_text = self.clipboard_get().strip()
            if clipboard_text:
                self.url_input.delete(0, "end")
                self.url_input.insert(0, clipboard_text)
                threading.Thread(target=self.fetch_and_display_avatar, args=(clipboard_text,), daemon=True).start()
        except Exception as e:
            self.log(f"Clipboard paste error: {e}", is_error=True)

    def browse_folder(self):
        """ Opens folder picker dialog to select destination folder """
        current_val = self.folder_input.get().strip() or r"C:\SMA-downloads"
        init_dir = current_val if os.path.exists(current_val) else r"C:\\"
        selected_dir = ctk.filedialog.askdirectory(initialdir=init_dir, title="Select Destination Folder")
        if selected_dir:
            selected_dir = os.path.normpath(selected_dir)
            self.folder_input.delete(0, "end")
            self.folder_input.insert(0, selected_dir)
            self.save_setting("destination_folder", selected_dir)

    def clear_logs(self):
        """ Clears all console logs """
        self.status_box.delete("1.0", "end")

    def copy_logs(self):
        """ Copies all console logs to clipboard """
        try:
            content = self.status_box.get("1.0", "end").strip()
            if content:
                self.clipboard_clear()
                self.clipboard_append(content)
                self.btn_copy_logs.configure(text="Copied! ✓")
                self.after(2000, lambda: self.btn_copy_logs.configure(text="📋 Copy Logs"))
        except Exception as e:
            self.log(f"Copy logs error: {e}", is_error=True)

    def send_notification(self, title, message):
        """ Sends a Windows desktop toast notification if enabled """
        if hasattr(self, 'notif_switch') and not self.notif_switch.get():
            return
        if self.tray_icon:
            try:
                self.tray_icon.notify(message, title)
                return
            except Exception:
                pass
        try:
            ps_cmd = f'[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null; $t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); $n = $t.GetElementsByTagName("text"); $n.Item(0).AppendChild($t.CreateTextNode("{title}")) > $null; $n.Item(1).AppendChild($t.CreateTextNode("{message}")) > $null; [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("SMArchive").Show([Windows.UI.Notifications.ToastNotification]::new($t))'
            subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd], creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception:
            pass

    def get_hwnd(self):
        try:
            return self.winfo_id()
        except Exception:
            return None

    def update_taskbar_progress(self, val, total=100):
        if self.taskbar:
            try:
                hwnd = self.get_hwnd()
                if hwnd:
                    if val <= 0:
                        self.taskbar.SetProgressState(hwnd, 0)
                    else:
                        self.taskbar.SetProgressState(hwnd, 2)
                        self.taskbar.SetProgressValue(hwnd, int(val), int(total))
            except Exception as e:
                print("Failed to set taskbar progress:", e)

    def toggle_season_input(self):
        if self.season_checkbox.get() == 1:
            self.season_input.configure(state="normal")
        else:
            self.season_input.configure(state="disabled")

    def toggle_range_input(self):
        if self.range_checkbox.get() == 1:
            self.range_input.configure(state="normal")
        else:
            self.range_input.configure(state="disabled")

    def get_cookie_args(self):
        """ Returns the appropriate yt-dlp arguments for cookies based on user setting """
        source_val = self.cookie_source_menu.get() if hasattr(self, 'cookie_source_menu') else self.saved_settings.get("cookie_source", "cookies.txt (File)")
        
        if source_val and "cookies.txt" not in source_val:
            browser_map = {
                "Chrome": "chrome",
                "Edge": "edge",
                "Firefox": "firefox",
                "Brave": "brave",
                "Opera": "opera",
                "Vivaldi": "vivaldi",
                "Chromium": "chromium"
            }
            browser_key = browser_map.get(source_val, source_val.lower())
            return ["--cookies-from-browser", browser_key]
        else:
            cookies_path = self.get_active_cookies_path()
            if os.path.exists(cookies_path):
                return ["--cookies", cookies_path]
            return []

    def fetch_and_display_avatar(self, url):
        """ Scrapes the uploader's channel avatar in the background and saves it to a temp file """
        try:
            yt_dlp_path = self.get_active_yt_dlp_path()
            cookie_args = self.get_cookie_args()
            
            # 1. Fetch channel URL using yt-dlp
            if "youtube.com/channel/" in url or "youtube.com/@" in url or "youtube.com/c/" in url:
                channel_url = url
            else:
                cmd = [yt_dlp_path] + cookie_args + ["--no-playlist", "--print", "uploader_url", url]
                res = subprocess.run(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                channel_url = res.stdout.strip()
                
            if not channel_url or "http" not in channel_url:
                channel_url = url
                
            # 2. Scrape the avatar URL from channel HTML
            req = urllib.request.Request(channel_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            
            avatar_url = None
            with urllib.request.urlopen(req, context=ctx, timeout=8) as response:
                html = response.read().decode('utf-8', errors='ignore')
                match = re.search(r'<meta property="og:image" content="([^"]+)"', html)
                if match:
                    avatar_url = match.group(1)
                else:
                    match_fallback = re.search(r'"avatar":{"thumbnails":\[{"url":"([^"]+)"', html)
                    if match_fallback:
                        avatar_url = match_fallback.group(1).replace(r"\u0026", "&")
                        
            if avatar_url:
                exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
                temp_avatar_path = os.path.join(exe_dir, "temp_avatar.png")
                
                img_data = urllib.request.urlopen(avatar_url, context=ctx, timeout=8).read()
                with open(temp_avatar_path, "wb") as f:
                    f.write(img_data)
                    
                self.after(0, self.load_avatar_file)
        except Exception as e:
            print("Avatar load failed:", e)

    def load_avatar_file(self):
        """ Loads the temporary avatar file in the main thread and displays it """
        try:
            exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
            temp_avatar_path = os.path.join(exe_dir, "temp_avatar.png")
            if os.path.exists(temp_avatar_path):
                pil_img = Image.open(temp_avatar_path)
                ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(60, 60))
                self.avatar_label.configure(image=ctk_img)
                self.avatar_image = ctk_img
        except Exception as e:
            print("Failed to render avatar:", e)

    def get_file_path(self, filename):
        """ Universal path finder for dev and bundled PyInstaller EXE """
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_path, filename)

    def get_active_cookies_path(self):
        """ Checks for an updated user cookie file before using the bundled one """
        exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
        updated_cookies = os.path.join(exe_dir, "cookies.txt")
        
        if os.path.exists(updated_cookies):
            return updated_cookies
        return self.get_file_path("cookies.txt")

    def get_active_yt_dlp_path(self):
        """ Checks for an updated yt-dlp.exe in the execution directory first """
        exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
        updated_yt_dlp = os.path.join(exe_dir, "yt-dlp.exe")
        
        if os.path.exists(updated_yt_dlp):
            return updated_yt_dlp
        return self.get_file_path("yt-dlp.exe")

    def upload_cookies(self):
        """ Opens a file dialogue to select and save a new cookies.txt file """
        file_path = ctk.filedialog.askopenfilename(
            title="Select your new cookies.txt file",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
        )
        if file_path:
            try:
                exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
                target_path = os.path.join(exe_dir, "cookies.txt")
                shutil.copy(file_path, target_path)
                
                self.log("SUCCESS: New cookies.txt saved permanently!")
                self.log(f"Location: {target_path}")
            except Exception as e:
                self.log(f"ERROR: Could not save cookies. {e}", is_error=True)

    def update_ytdlp(self):
        """ Runs updates for yt-dlp.exe directly """
        if self.update_ytdlp_btn:
            self.update_ytdlp_btn.configure(state="disabled", text="Updating...")
        
        def run_update():
            self.log("Starting engine update check...")
            exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
            target_path = os.path.join(exe_dir, "yt-dlp.exe")
            
            if not os.path.exists(target_path):
                try:
                    bundled_path = self.get_file_path("yt-dlp.exe")
                    shutil.copy(bundled_path, target_path)
                except Exception as e:
                    self.log(f"ERROR: Could not prepare engine for update: {e}", is_error=True)
                    self.after(0, lambda: self.update_ytdlp_btn.configure(text="Update Failed! ❌") if self.update_ytdlp_btn else None)
                    self.after(4000, self.reset_update_button)
                    return
            
            self.log(f"Running update on: {target_path}")
            cmd = [target_path, "-U"]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                if res.returncode == 0:
                    self.log("SUCCESS: Downloader Engine updated successfully!")
                    self.log(res.stdout.strip())
                    self.after(0, lambda: self.update_ytdlp_btn.configure(text="Update Complete! 🎉") if self.update_ytdlp_btn else None)
                else:
                    self.log(f"ERROR: Update failed: {res.stderr.strip() or res.stdout.strip()}", is_error=True)
                    self.after(0, lambda: self.update_ytdlp_btn.configure(text="Update Failed! ❌") if self.update_ytdlp_btn else None)
            except Exception as e:
                self.log(f"ERROR running update command: {e}", is_error=True)
                self.after(0, lambda: self.update_ytdlp_btn.configure(text="Update Failed! ❌") if self.update_ytdlp_btn else None)
                
            self.after(4000, self.reset_update_button)

        threading.Thread(target=run_update, daemon=True).start()

    def reset_update_button(self):
        if self.update_ytdlp_btn:
            self.update_ytdlp_btn.configure(state="normal", text="Update Engine")

    def select_tab(self, tab_name):
        self.active_tab = tab_name
        cfg = getattr(self, 'theme_cfg', {})
        
        tabs = {
            "download": (self.btn_download, self.download_page),
            "search": (self.btn_search, self.search_page),
            "spotify": (self.btn_spotify, self.spotify_page),
            "settings": (self.btn_settings, self.settings_page),
            "logs": (self.btn_logs, self.logs_page)
        }
        
        for name, (btn, page) in tabs.items():
            if name == tab_name:
                btn.configure(
                    fg_color=cfg.get("accent", "#38BDF8"),
                    text_color="#070F15" if cfg.get("accent") != "#FF6E40" else "#FFFFFF",
                    hover_color=cfg.get("btn_hover", "#1E293B")
                )
                page.pack(fill="both", expand=True)
            else:
                btn.configure(
                    fg_color="transparent",
                    text_color=cfg.get("text_secondary", "#94A3B8"),
                    hover_color=cfg.get("option_hover", "#334155")
                )
                page.pack_forget()

    def open_error_log(self):
        """ Opens the persistent error log file in the default system text editor """
        try:
            exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
            log_file = os.path.join(exe_dir, "downloader_errors.txt")
            if not os.path.exists(log_file):
                with open(log_file, "w", encoding="utf-8") as f:
                    from datetime import datetime
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    f.write(f"[{timestamp}] Shallot Media Archive error log initialized.\n")
            try:
                os.startfile(log_file)
            except Exception:
                subprocess.Popen(["notepad.exe", log_file])
        except Exception as e:
            self.log(f"Could not open error log: {e}", is_error=True)

    def log(self, message, is_error=False):
        # Filter benign routine fallback warnings
        if "web_creator client https formats require a GVS PO Token" in message:
            return

        if "The provided YouTube account cookies are no longer valid" in message:
            if getattr(self, '_cookie_warning_shown', False):
                return
            self._cookie_warning_shown = True
            message = "⚠️ [Notice] Your YouTube cookies have expired or rotated. Age-restricted and members-only videos will be skipped until fresh cookies are provided."

        # RAM optimization: auto-prune oldest log lines when exceeding 1500 lines
        try:
            num_lines = int(self.status_box.index('end-1c').split('.')[0])
            if num_lines > 1500:
                self.status_box.delete('1.0', f'{num_lines - 1200}.0')
        except Exception:
            pass

        self.status_box.insert("end", message + "\n")
        self.status_box.see("end")
        
        # Check for signature solving / JavaScript runtime errors
        if "signature solving failed" in message.lower() or "javascript runtime" in message.lower() or "n challenge solving failed" in message.lower():
            tip_msg = "\n💡 [HELP] YouTube now requires an external JavaScript runtime to download videos.\n" \
                      "👉 To fix this on Windows:\n" \
                      "1. Open PowerShell and run: winget install DenoLand.Deno\n" \
                      "2. OR place 'deno.exe' in the folder next to this app.\n" \
                      "3. Then restart the application."
            current_content = self.status_box.get("1.0", "end")
            if "[HELP] YouTube now requires" not in current_content:
                self.status_box.insert("end", tip_msg + "\n")
                self.status_box.see("end")

        if is_error or "error" in message.lower() or "fatal" in message.lower():
            try:
                from datetime import datetime
                exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
                log_file = os.path.join(exe_dir, "downloader_errors.txt")
                with open(log_file, "a", encoding="utf-8") as f:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    f.write(f"[{timestamp}] {message}\n")
            except Exception:
                pass

    # =========================================================================
    # --- Download & Execution Controls ---
    # =========================================================================

    def start_download(self):
        self.is_cancelled = False
        self._cookie_warning_shown = False
        self.progress.set(0)
        self.progress_label.configure(text="0%")
        
        self.download_button.place_forget()
        self.progress_frame.place(x=0, y=0, relwidth=1, relheight=1)
        self.update_taskbar_progress(0)
        
        self.queue_counter_lbl.configure(text="0 / 0")
        self.queue_item_lbl.configure(text="Initializing...")
        self.queue_progress.set(0)
        self.queue_card.pack(fill="x", padx=20, pady=6, after=self.action_card)
        
        self.power_light.configure(text="● INITIALIZING", text_color=self.theme_cfg.get("accent", "#38BDF8"))
        
        url = self.url_input.get().strip()
        if url:
            threading.Thread(target=self.fetch_and_display_avatar, args=(url,), daemon=True).start()
        threading.Thread(target=self.run_command, daemon=True).start()

    def stop_download(self):
        """ Aborts active download immediately and terminates child processes """
        self.is_cancelled = True
        self.emergency_process_cleanup()
        self.active_process = None
        self.log("⏹ Download stopped by user.")
        self.power_light.configure(text="● STOPPED", text_color="#FB7185")
        self.after(0, self.reset_download_button)

    def reset_download_button(self):
        self.progress_frame.place_forget()
        self.download_button.place(x=0, y=0)
        self.update_taskbar_progress(0)
        if not self.is_cancelled:
            self.power_light.configure(text=self.theme_cfg.get("status_text", "● READY"), text_color=self.theme_cfg.get("status_color", "#38BDF8"))
        self.queue_card.pack_forget()

    def run_command(self):
        url = self.url_input.get().strip()
        folder = self.folder_input.get().strip() or r"C:\SMA-downloads"
        
        if not url:
            self.log("ERROR: Please enter or paste a valid URL.", is_error=True)
            self.after(0, self.reset_download_button)
            return

        if not os.path.exists(folder):
            try:
                os.makedirs(folder, exist_ok=True)
            except Exception as e:
                self.log(f"ERROR: Could not create destination folder: {e}", is_error=True)

        if self.season_checkbox.get() == 1:
            try:
                season = int(self.season_input.get())
            except ValueError:
                season = 1
        else:
            season = None

        range_val = None
        if self.range_checkbox.get() == 1:
            raw_range = self.range_input.get().strip()
            if raw_range:
                if "-" in raw_range and ":" not in raw_range:
                    parts = raw_range.split("-")
                    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                        raw_range = f"{parts[0]}:{parts[1]}"
                range_val = raw_range
            
        speed = self.speed_input.get().strip()
        
        yt_dlp_path = self.get_active_yt_dlp_path()
        cookie_args = self.get_cookie_args()
        
        self.log("Initializing download...")
        
        # --- Pre-check block (Fast flat-playlist extraction) ---
        check_cmd = [yt_dlp_path] + cookie_args + ["-i", "--flat-playlist", "--get-id", url]
        if range_val:
            check_cmd.extend(["--playlist-items", range_val])

        result = subprocess.run(check_cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        
        valid_ids = [line for line in result.stdout.strip().split('\n') if line]
        
        if not valid_ids:
            if self.is_cancelled:
                return
            error_msg = result.stderr.strip() if result.stderr else "No valid videos found in link."
            
            # Smart fallback if browser cookie database was locked by an open browser
            if "cookie database" in error_msg.lower() or "database is locked" in error_msg.lower() or "could not copy" in error_msg.lower():
                self.log("⚠️ Notice: Browser cookie database is locked (browser is currently open).")
                self.log("🔄 Automatically falling back to cookies.txt file...")
                cookies_path = self.get_active_cookies_path()
                if os.path.exists(cookies_path):
                    cookie_args = ["--cookies", cookies_path]
                    check_cmd = [yt_dlp_path] + cookie_args + ["-i", "--flat-playlist", "--get-id", url]
                    if range_val:
                        check_cmd.extend(["--playlist-items", range_val])
                    result = subprocess.run(check_cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    valid_ids = [line for line in result.stdout.strip().split('\n') if line]
                    error_msg = result.stderr.strip() if result.stderr else error_msg
            
            if not valid_ids:
                self.log("--- FATAL ERROR ---")
                self.log(error_msg)
                self.log("------------------------")
                self.log("Download stopped. Could not find any readable videos.")
                self.power_light.configure(text="● ERROR", text_color="#FF5722")
                self.after(0, self.reset_download_button)
                return
            
        total_files = len(valid_ids)
        self.log(f"Found {total_files} valid videos. Skipping dead links...")
        self.queue_counter_lbl.configure(text=f"0 / {total_files}")
        self.queue_item_lbl.configure(text="Starting downloads...")
        
        # --- High-Performance Optimized Command Line ---
        command = [
            yt_dlp_path, 
            "--newline", 
            "--progress", 
            "-i",
            "-P", folder, 
            "--concurrent-fragments", "4",
            "--socket-timeout", "15",
            "--retries", "10",
            "--fragment-retries", "10",
            "--mtime",
            "--sleep-interval", "2",
            "--max-sleep-interval", "5"
        ]
        command.extend(cookie_args)

        # Multi-Session Download Archive
        if self.archive_switch.get():
            archive_file = os.path.join(folder, ".download_archive.txt")
            command.extend(["--download-archive", archive_file])
        
        # Playlist item range
        if range_val:
            command.extend(["--playlist-items", range_val])
            self.log(f"Applying Item Range: {range_val}")

        if season is not None:
            start_num = (season * 100) + 1
            command.extend(["--autonumber-start", str(start_num)])
            
        if speed:
            command.extend(["-r", f"{speed}M"])
        
        # Format Configuration
        if self.audio_switch.get():
            # Dedicated Audio Format & Quality
            a_fmt = self.audio_format_menu.get().lower() if hasattr(self, 'audio_format_menu') else "mp3"
            if "aac" in a_fmt or "m4a" in a_fmt:
                ext = "m4a"
            elif "flac" in a_fmt:
                ext = "flac"
            elif "wav" in a_fmt:
                ext = "wav"
            elif "opus" in a_fmt:
                ext = "opus"
            else:
                ext = "mp3"

            aq_choice = self.audio_quality.get().lower() if hasattr(self, 'audio_quality') else "best"
            if "320" in aq_choice or "best" in aq_choice:
                aq = "0"
            elif "192" in aq_choice or "standard" in aq_choice:
                aq = "5"
            else:
                aq = "9"
                
            command.extend(["-f", "ba", "--extract-audio", "--audio-format", ext, "--audio-quality", aq])
        else:
            # Video Resolution selection
            q = self.video_quality.get().lower() if hasattr(self, 'video_quality') else "1080p"
            if "4k" in q or "2160" in q:
                max_h = 2160
            elif "2k" in q or "1440" in q:
                max_h = 1440
            elif "1080" in q:
                max_h = 1080
            elif "720" in q:
                max_h = 720
            elif "480" in q:
                max_h = 480
            else:
                max_h = 1080
                
            fmt = f"bv*[vcodec^=avc1][height<={max_h}]+ba[acodec^=mp4a]/b[ext=mp4][height<={max_h}]/bv*[height<={max_h}]+ba/b[height<={max_h}]/best"
            command.extend(["-f", fmt, "--merge-output-format", "mp4"])
 
        if self.subtitles_switch.get():
            command.extend(["--write-subs", "--write-auto-subs", "--convert-subs", "srt"])
        if self.metadata_switch.get():
            command.extend(["--embed-metadata", "--embed-thumbnail", "--embed-chapters"])
        
        # Filename & Folder Template
        if self.audio_switch.get():
            # Plexamp Standard Music Hierarchy: Artist / Album / 01 - Title.ext
            if season is not None:
                command.extend(["-o", "%(artist,album_artist,creator,uploader)s/%(album,playlist_title,uploader)s/%(autonumber)02d - %(title)s.%(ext)s", url])
            else:
                command.extend(["-o", "%(artist,album_artist,creator,uploader)s/%(album,playlist_title,uploader)s/%(playlist_index&{:02d} - |)s%(title)s.%(ext)s", url])
        else:
            # Video Hierarchy with optional Upload Date
            use_date = bool(self.date_switch.get())
            if season is not None:
                date_prefix = "%(upload_date>%Y-%m-%d)s - " if use_date else ""
                command.extend(["-o", f"%(playlist_title,uploader)s/{date_prefix}%(autonumber)03d - %(title)s.%(ext)s", url])
            else:
                date_prefix = "[%(upload_date>%Y-%m-%d)s] " if use_date else ""
                command.extend(["-o", f"%(playlist_title,uploader)s/{date_prefix}%(title)s.%(ext)s", url])

        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        self.active_process = process

        current_file = 0
        if process.stdout:
            for line in process.stdout:
                if self.is_cancelled:
                    break
                line_str = line.strip()
                if "[download] Downloading item" in line_str:
                    current_file += 1
                    self.power_light.configure(text=f"● DOWNLOADING: {current_file}/{total_files}", text_color=self.theme_cfg.get("accent", "#38BDF8"))
                    self.queue_counter_lbl.configure(text=f"{current_file} / {total_files}")
                    self.queue_progress.set(0)
                if "[download] Destination:" in line_str:
                    dest_title = line_str.split("Destination:", 1)[-1].strip()
                    dest_title = os.path.basename(dest_title)
                    if len(dest_title) > 70:
                        dest_title = dest_title[:67] + "..."
                    self.queue_item_lbl.configure(text=dest_title)
                if "has already been recorded in the archive" in line_str:
                    item_id = line_str.split("[download]", 1)[-1].split("has already")[0].strip()
                    self.queue_item_lbl.configure(text=f"Skipping (Already in archive): {item_id}")
                match = re.search(r"(\d+\.?\d*)%", line_str)
                if match: 
                    pct = float(match.group(1))
                    overall_pct = ((current_file - 1) * 100 + pct) / total_files if total_files > 0 else pct
                    self.progress.set(overall_pct / 100)
                    self.progress_label.configure(text=f"{int(overall_pct)}%")
                    self.update_taskbar_progress(overall_pct)
                    self.queue_progress.set(pct / 100)
                
                if "error" in line_str.lower() or "warning" in line_str.lower():
                    self.log(line_str)
        
        process.wait()
        self.active_process = None

        if self.is_cancelled:
            self.power_light.configure(text="● STOPPED", text_color="#FB7185")
            self.update_taskbar_progress(0)
            self.after(0, self.reset_download_button)
            return

        if process.returncode != 0:
            self.power_light.configure(text="● ERROR", text_color="#FF5722")
            self.log(f"Download failed with exit code {process.returncode}.", is_error=True)
            self.update_taskbar_progress(0)
        else:
            self.progress.set(1)
            self.progress_label.configure(text="100%")
            self.power_light.configure(text="● FINISHED", text_color="#10B981")
            self.log("All downloads complete!")
            self.send_notification("SMArchive", f"All downloads complete! ({total_files} file{'s' if total_files > 1 else ''})")
            self.update_taskbar_progress(100)
            self.after(2000, lambda: self.update_taskbar_progress(0))
            if self.open_folder_switch.get():
                try:
                    os.startfile(folder)
                except Exception as e:
                    self.log(f"Could not open directory: {e}", is_error=True)
        
        self.after(0, self.reset_download_button)

    # =========================================================================
    # --- YouTube Search Feature (Parallel ThreadPool Optimized) ---
    # =========================================================================

    def search_youtube(self):
        query = self.search_input.get().strip()
        if not query:
            return
            
        self.search_button.configure(state="disabled", text="Searching...")
        
        for widget in self.results_frame.winfo_children():
            widget.destroy()
            
        loading_label = ctk.CTkLabel(self.results_frame, text="🔍 Searching YouTube...", font=("Segoe UI", 12), text_color="#00E5FF")
        loading_label.pack(pady=20)
        
        def run_search():
            try:
                yt_dlp_path = self.get_active_yt_dlp_path()
                cookie_args = self.get_cookie_args()
                
                cmd_videos = [
                    yt_dlp_path
                ] + cookie_args + [
                    "--dump-single-json",
                    "--flat-playlist",
                    "--no-playlist",
                    f"ytsearch6:{query}"
                ]
                
                encoded_query = urllib.parse.quote(query)
                playlist_url = f"https://www.youtube.com/results?search_query={encoded_query}&sp=EgIQAw%3D%3D"
                cmd_playlists = [
                    yt_dlp_path
                ] + cookie_args + [
                    "--dump-single-json",
                    "--flat-playlist",
                    "--playlist-end", "3",
                    playlist_url
                ]
                
                res_v = subprocess.run(cmd_videos, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                res_p = subprocess.run(cmd_playlists, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                
                video_entries = []
                if res_v.returncode == 0:
                    try:
                        data_v = json.loads(res_v.stdout.strip())
                        video_entries = data_v.get("entries", [])[:6]
                    except Exception as e:
                        print("Error parsing video search results:", e)
                else:
                    self.log(f"Video search notice: {res_v.stderr.strip()}", is_error=False)
                
                playlist_entries = []
                if res_p.returncode == 0:
                    try:
                        data_p = json.loads(res_p.stdout.strip())
                        playlist_entries = data_p.get("entries", [])[:3]
                    except Exception as e:
                        print("Error parsing playlist search results:", e)
                else:
                    self.log(f"Playlist search notice: {res_p.stderr.strip()}", is_error=False)
                        
                if not video_entries and not playlist_entries:
                    self.after(0, lambda: self.show_search_error("No results found."))
                    return
                
                combined_entries = []
                for entry in video_entries:
                    combined_entries.append((entry, False))
                for entry in playlist_entries:
                    combined_entries.append((entry, True))
                    
                temp_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
                
                # --- Concurrent Thumbnail Downloader ---
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE

                def fetch_single_thumb(item_tuple):
                    idx, (entry, is_playlist) = item_tuple
                    title = entry.get("title", "No Title")
                    url = entry.get("url", "")
                    thumbnails = entry.get("thumbnails", [])
                    thumb_url = thumbnails[-1].get("url") if thumbnails else None
                    
                    local_thumb_path = None
                    if thumb_url:
                        try:
                            local_thumb_path = os.path.join(temp_dir, f"temp_thumb_{idx}.jpg")
                            img_data = urllib.request.urlopen(thumb_url, context=ctx, timeout=6).read()
                            with open(local_thumb_path, "wb") as f:
                                f.write(img_data)
                        except Exception:
                            local_thumb_path = None
                    
                    return {
                        "title": title,
                        "url": url,
                        "thumb_path": local_thumb_path,
                        "is_playlist": is_playlist
                    }

                indexed_entries = list(enumerate(combined_entries))
                with ThreadPoolExecutor(max_workers=6) as executor:
                    results = list(executor.map(fetch_single_thumb, indexed_entries))
                    
                self.after(0, lambda: self.display_search_results(results))
                
            except Exception as e:
                print("Search error:", e)
                self.after(0, lambda: self.show_search_error("Search error occurred."))
            finally:
                self.after(0, lambda: self.search_button.configure(state="normal", text="🔍 Search"))
                
        threading.Thread(target=run_search, daemon=True).start()

    def show_search_error(self, message):
        for widget in self.results_frame.winfo_children():
            widget.destroy()
        err_label = ctk.CTkLabel(self.results_frame, text=message, font=("Segoe UI", 11), text_color="#FF5722")
        err_label.pack(pady=20)

    def display_search_results(self, results):
        for widget in self.results_frame.winfo_children():
            widget.destroy()
            
        self.results_frame.columnconfigure(0, weight=1)
        self.results_frame.columnconfigure(1, weight=1)
        self.results_frame.columnconfigure(2, weight=1)
        
        self.search_result_widgets = []
        self.selected_search_card = None
        border_col = getattr(self, 'theme_cfg', {}).get('border', '#1F3A4E')
        input_bg = getattr(self, 'theme_cfg', {}).get('input_bg', '#070F15')
        
        for idx, item in enumerate(results):
            result_card = ctk.CTkFrame(
                self.results_frame, 
                fg_color=input_bg, 
                border_color=border_col, 
                border_width=1, 
                corner_radius=8,
                cursor="hand2"
            )
            row_idx = idx // 3
            col_idx = idx % 3
            result_card.grid(row=row_idx, column=col_idx, padx=6, pady=6, sticky="nsew")
            
            img = None
            if item["thumb_path"] and os.path.exists(item["thumb_path"]):
                try:
                    img = Image.open(item["thumb_path"])
                except Exception:
                    pass
            if not img:
                img = Image.new('RGB', (160, 90), color='#1E1A24')
                
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(160, 90))
            
            url = item["url"]
            
            img_label = ctk.CTkLabel(result_card, image=ctk_img, text="")
            img_label.pack(padx=2, pady=(4, 2))
            
            title_text = item["title"]
            if item.get("is_playlist"):
                title_text = "📁 " + title_text
            if len(title_text) > 35:
                title_text = title_text[:32] + "..."
            title_label = ctk.CTkLabel(
                result_card, 
                text=title_text, 
                font=("Segoe UI", 9), 
                text_color="#9E9EAF", 
                wraplength=150,
                justify="center",
                height=32
            )
            title_label.pack(padx=2, pady=(0, 4))
            
            def make_select_handler(selected_url=url, card=result_card):
                return lambda e: self.select_search_video(selected_url, card)
                
            def make_enter_handler(card=result_card):
                return lambda e: card.configure(border_color=getattr(self, 'theme_cfg', {}).get('accent', '#00E5FF'))
                
            def make_leave_handler(card=result_card):
                return lambda e: card.configure(
                    border_color=getattr(self, 'theme_cfg', {}).get('accent', '#00E5FF') if card == self.selected_search_card 
                    else getattr(self, 'theme_cfg', {}).get('border', '#1F3A4E')
                )
            
            select_h = make_select_handler()
            enter_h = make_enter_handler()
            leave_h = make_leave_handler()
            
            for w in [result_card, img_label, title_label]:
                w.bind("<Button-1>", select_h)
                w.bind("<Enter>", enter_h)
                w.bind("<Leave>", leave_h)
            
            self.search_result_widgets.append((result_card, url))

    def select_search_video(self, url, selected_card):
        self.url_input.delete(0, "end")
        self.url_input.insert(0, url)
        
        self.selected_search_card = selected_card
        accent = getattr(self, 'theme_cfg', {}).get('accent', '#00E5FF')
        border = getattr(self, 'theme_cfg', {}).get('border', '#1F3A4E')
        
        for card, card_url in self.search_result_widgets:
            if card == selected_card:
                card.configure(border_color=accent, border_width=2)
            else:
                card.configure(border_color=border, border_width=1)
                
        threading.Thread(target=self.fetch_and_display_avatar, args=(url,), daemon=True).start()
        self.after(300, lambda: self.select_tab("download"))

    # =========================================================================
    # --- Spotify to Plexamp Controller Methods ---
    # =========================================================================

    def paste_spotify_url(self):
        """ Pastes clipboard contents into the Spotify URL input and triggers fetch """
        try:
            clipboard_text = self.clipboard_get().strip()
            if clipboard_text:
                self.spotify_url_input.delete(0, "end")
                self.spotify_url_input.insert(0, clipboard_text)
                self.fetch_spotify_playlist()
        except Exception as e:
            self.log(f"Spotify clipboard paste error: {e}", is_error=True)

    def browse_plex_folder(self):
        """ Opens folder picker dialog to select Plex music library folder """
        current_val = self.spotify_folder_input.get().strip() or r"C:\SMA-downloads\Music"
        init_dir = current_val if os.path.exists(current_val) else r"C:\\"
        selected_dir = ctk.filedialog.askdirectory(initialdir=init_dir, title="Select Plexamp Music Library Folder")
        if selected_dir:
            selected_dir = os.path.normpath(selected_dir)
            self.spotify_folder_input.delete(0, "end")
            self.spotify_folder_input.insert(0, selected_dir)
            self.save_setting("plex_music_folder", selected_dir)

    def fetch_spotify_playlist(self):
        """ Fetches metadata and tracklist for the entered Spotify link in a worker thread """
        url = self.spotify_url_input.get().strip()
        if not url:
            self.spotify_status_lbl.configure(text="Please enter a valid Spotify URL.", text_color="#FB7185")
            return

        self.btn_spotify_fetch.configure(state="disabled", text="Fetching... ⏳")
        self.spotify_status_lbl.configure(text="Fetching metadata from Spotify...", text_color=getattr(self, 'theme_cfg', {}).get("accent", "#00E5FF"))

        def run_fetch():
            cid = self.saved_settings.get("spotify_client_id", "")
            csec = self.saved_settings.get("spotify_client_secret", "")
            fetcher = SpotifyFetcher(client_id=cid, client_secret=csec)

            try:
                collection = fetcher.fetch_entity(url)
                self.spotify_collection = collection
                self.after(0, lambda: self.display_spotify_collection(collection))
            except Exception as e:
                err_msg = str(e)
                self.log(f"Spotify fetch error: {err_msg}", is_error=True)
                self.after(0, lambda msg=err_msg: self.show_spotify_fetch_error(msg))
            finally:
                self.after(0, lambda: self.btn_spotify_fetch.configure(state="normal", text="⚡ Fetch Tracks"))

        threading.Thread(target=run_fetch, daemon=True).start()

    def show_spotify_fetch_error(self, err_msg):
        self.spotify_status_lbl.configure(text=f"Error: {err_msg[:60]}", text_color="#FB7185")
        for widget in self.spotify_track_scroll.winfo_children():
            widget.destroy()
        lbl = ctk.CTkLabel(self.spotify_track_scroll, text=f"Failed to fetch Spotify link:\n{err_msg}", font=("Segoe UI", 11), text_color="#FB7185")
        lbl.pack(pady=25)

    def display_spotify_collection(self, collection):
        """ Renders the fetched collection header, cover art, and interactive tracklist """
        title = collection.get("title", "Spotify Collection")
        author = collection.get("author", "")
        tracks = collection.get("tracks", [])
        total_count = len(tracks)

        self.spotify_title_lbl.configure(text=title[:38] + ("..." if len(title) > 38 else ""))
        self.spotify_author_lbl.configure(text=f"By: {author}" if author else "Spotify")
        self.spotify_stats_lbl.configure(text=f"{total_count} tracks ready to sync")

        # Fetch and display cover image
        cover_url = collection.get("cover_url", "")
        if cover_url:
            def load_cover():
                try:
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    req = urllib.request.Request(cover_url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
                        img_data = resp.read()
                    import io
                    pil_img = Image.open(io.BytesIO(img_data)).resize((64, 64), Image.Resampling.LANCZOS)
                    ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(64, 64))
                    self.after(0, lambda: self.spotify_art_label.configure(image=ctk_img))
                    self.spotify_art_image = ctk_img
                except Exception as e:
                    print("Cover art fetch failed:", e)

            threading.Thread(target=load_cover, daemon=True).start()

        # Populate Tracklist
        for widget in self.spotify_track_scroll.winfo_children():
            widget.destroy()

        self.spotify_track_items = []
        input_bg = getattr(self, 'theme_cfg', {}).get('input_bg', '#070F15')
        border_col = getattr(self, 'theme_cfg', {}).get('border', '#1F3A4E')
        text_sec = getattr(self, 'theme_cfg', {}).get('text_secondary', '#78909C')

        dest_folder = self.spotify_folder_input.get().strip() or r"C:\SMA-downloads\Music"
        raw_fmt = self.spotify_format_menu.get().lower()
        audio_fmt = "flac" if "flac" in raw_fmt else ("m4a" if "m4a" in raw_fmt else "mp3")
        raw_org = self.spotify_org_menu.get()
        folder_struct = "playlist_folder" if "Playlist Folder" in raw_org else "plex_standard"

        for idx, track in enumerate(tracks, start=1):
            row_frame = ctk.CTkFrame(self.spotify_track_scroll, fg_color=input_bg, border_color=border_col, border_width=1, corner_radius=6, height=36)
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
                command=self.update_spotify_selected_count
            )
            chk.pack(side="left", padx=(8, 4), pady=4)

            num_lbl = ctk.CTkLabel(row_frame, text=f"{idx:02d}.", font=("Segoe UI", 10, "bold"), text_color=text_sec, width=24, anchor="e")
            num_lbl.pack(side="left", padx=(0, 6))

            orig_num = int(track.get("track_number", idx))
            t_album = track.get("album", "")
            t_title = track.get("title", "Unknown")
            t_artist = track.get("artist", "Unknown")

            title_text = f"{t_title} - {t_artist}"
            if t_album and t_album not in ["Spotify Playlist", "Spotify Collection"]:
                title_text += f"   [Trk #{orig_num:02d} • {t_album}]"

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

            # Pre-check if already exists in library
            is_in_lib = SpotifyPlexampPipeline.check_existing_track(
                dest_folder, track, self.spotify_collection, audio_fmt, folder_struct
            )
            init_status = "✓ In Library" if is_in_lib else "Ready"
            init_color = "#4ADE80" if is_in_lib else "#78909C"

            status_badge = ctk.CTkLabel(row_frame, text=init_status, font=("Segoe UI", 9, "bold"), text_color=init_color, width=75, anchor="e")
            status_badge.pack(side="right", padx=(0, 10))

            self.spotify_track_items.append({
                "track": track,
                "var": chk_var,
                "row_frame": row_frame,
                "status_badge": status_badge,
                "checkbox": chk
            })

        self.update_spotify_selected_count()
        self.spotify_status_lbl.configure(text=f"Loaded {total_count} songs. Select songs and click 'Download & Tag'.", text_color=getattr(self, 'theme_cfg', {}).get("text_primary", "#F5F5F7"))

    def toggle_all_spotify_tracks(self, select_all: bool):
        for item in self.spotify_track_items:
            item["var"].set(1 if select_all else 0)
        self.update_spotify_selected_count()

    def update_spotify_selected_count(self):
        selected = sum(1 for item in self.spotify_track_items if item["var"].get() == 1)
        total = len(self.spotify_track_items)
        self.spotify_track_count_lbl.configure(text=f"{selected} / {total} Selected")
        self.spotify_counter_lbl.configure(text=f"0 / {selected}")

    def open_spotify_music_folder(self):
        """ Opens the Plex music folder in Windows Explorer """
        folder = self.spotify_folder_input.get().strip() or r"C:\SMA-downloads\Music"
        os.makedirs(folder, exist_ok=True)
        try:
            os.startfile(folder)
        except Exception as e:
            self.log(f"Failed to open folder '{folder}': {e}", is_error=True)

    def start_spotify_sync(self):
        """ Runs the YouTube matching, downloading, and Plexamp tagging pipeline """
        if not self.spotify_collection:
            self.spotify_status_lbl.configure(text="Please fetch a Spotify playlist first.", text_color="#FB7185")
            return

        selected_tracks = []
        for idx, item in enumerate(self.spotify_track_items):
            if item["var"].get() == 1:
                t = dict(item["track"])
                t["_track_index"] = idx
                selected_tracks.append(t)

        if not selected_tracks:
            self.spotify_status_lbl.configure(text="No tracks selected. Check at least one song.", text_color="#FB7185")
            return

        dest_folder = self.spotify_folder_input.get().strip() or r"C:\SMA-downloads\Music"
        self.save_setting("plex_music_folder", dest_folder)

        raw_fmt = self.spotify_format_menu.get().lower()
        audio_fmt = "flac" if "flac" in raw_fmt else ("m4a" if "m4a" in raw_fmt else "mp3")

        raw_org = self.spotify_org_menu.get()
        folder_struct = "playlist_folder" if "Playlist Folder" in raw_org else "plex_standard"

        embed_art = bool(self.spotify_embed_art_switch.get())
        fetch_lyrics = bool(self.spotify_lyrics_switch.get())
        calc_replaygain = bool(self.spotify_gain_switch.get())

        raw_conc = self.spotify_concurrency_menu.get()
        concurrency = 2
        if "3" in raw_conc:
            concurrency = 3
        elif "1" in raw_conc:
            concurrency = 1

        yt_dlp_path = self.get_active_yt_dlp_path()
        cookie_args = self.get_cookie_args()

        self.btn_spotify_start.configure(state="disabled", text="Syncing to Plexamp... ⏳")
        self.spotify_progress_bar.set(0)
        self.power_light.configure(text="● SYNCING", text_color=getattr(self, 'theme_cfg', {}).get("accent", "#00E5FF"))

        def log_cb(msg: str, is_error: bool = False):
            self.log(f"[Spotify] {msg}", is_error=is_error)

        def progress_cb(pct: float, status_text: str):
            self.after(0, lambda: self.spotify_progress_bar.set(pct))
            self.after(0, lambda: self.spotify_status_lbl.configure(text=status_text))
            self.after(0, lambda: self.update_taskbar_progress(int(pct * 100)))

        def track_status_cb(track_index: int, text: str, color: str):
            if track_index < len(self.spotify_track_items):
                badge = self.spotify_track_items[track_index]["status_badge"]
                self.after(0, lambda b=badge, t=text, c=color: b.configure(text=t, text_color=c))

        self.spotify_pipeline = SpotifyPlexampPipeline(
            yt_dlp_path=yt_dlp_path,
            cookie_args=cookie_args,
            log_callback=log_cb,
            progress_callback=progress_cb,
            track_status_callback=track_status_cb
        )

        def run_pipeline():
            self.log(f"Starting Spotify to Plexamp sync ({len(selected_tracks)} songs) to: {dest_folder} (Concurrency: {concurrency})")
            stats = self.spotify_pipeline.process_playlist(
                collection=self.spotify_collection,
                selected_tracks=selected_tracks,
                base_music_dir=dest_folder,
                audio_format=audio_fmt,
                folder_structure=folder_struct,
                embed_art=embed_art,
                save_cover_file=True,
                fetch_lyrics=fetch_lyrics,
                calculate_replaygain=calc_replaygain,
                concurrency=concurrency
            )
            self.after(0, lambda: self.finish_spotify_sync(stats))

        threading.Thread(target=run_pipeline, daemon=True).start()

    def stop_spotify_sync(self):
        """ Cancels the active Spotify download pipeline """
        if self.spotify_pipeline:
            self.spotify_pipeline.cancel()
            self.spotify_status_lbl.configure(text="Sync cancelled by user.", text_color="#FB7185")
            self.power_light.configure(text="● STOPPED", text_color="#FB7185")
            self.reset_spotify_sync_button()

    def finish_spotify_sync(self, stats):
        completed = stats.get("completed", 0)
        failed = stats.get("failed", 0)
        self.log(f"🏁 Sync finished: {completed} ready in Plex library, {failed} errors.")
        self.send_notification("Spotify Sync Complete", f"{completed} tracks ready for Plexamp!")
        self.spotify_status_lbl.configure(
            text=f"✓ Complete! {completed} tracks ready for Plexamp. ({failed} errors)",
            text_color=getattr(self, 'theme_cfg', {}).get("accent", "#00E5FF") if failed == 0 else "#FB7185"
        )
        self.reset_spotify_sync_button()

    def reset_spotify_sync_button(self):
        self.btn_spotify_start.configure(state="normal", text="🚀  Download & Tag for Plexamp")
        self.update_taskbar_progress(0)
        self.power_light.configure(
            text=getattr(self, 'theme_cfg', {}).get("status_text", "● READY"),
            text_color=getattr(self, 'theme_cfg', {}).get("status_color", "#38BDF8")
        )

    # =========================================================================
    # --- Theme & Style Engine ---
    # =========================================================================

    def apply_theme(self, theme_name):
        themes = {
            "Obsidian": {
                "app_bg": "#0D0D12",
                "card_bg": "#17171F",
                "border": "#28283A",
                "border_width": 1,
                "accent": "#A78BFA",
                "text_primary": "#EEEEF2",
                "text_secondary": "#8888A0",
                "btn_bg": "#1E1B2E",
                "btn_border": "#A78BFA",
                "btn_text": "#A78BFA",
                "btn_hover": "#2D2845",
                "status_text": "● READY",
                "status_color": "#A78BFA",
                "input_bg": "#0D0D12",
                "input_border": "#28283A",
                "option_btn": "#1E1E2A",
                "option_hover": "#32324A",
                "option_bg": "#0D0D12",
                "option_drop": "#17171F"
            },
            "Vapor": {
                "app_bg": "#110A14",
                "card_bg": "#1E1224",
                "border": "#3A1F48",
                "border_width": 1,
                "accent": "#F472B6",
                "text_primary": "#FDF2F8",
                "text_secondary": "#B07AA8",
                "btn_bg": "#2A1230",
                "btn_border": "#F472B6",
                "btn_text": "#F472B6",
                "btn_hover": "#3D1E48",
                "status_text": "● LIVE",
                "status_color": "#F472B6",
                "input_bg": "#110A14",
                "input_border": "#3A1F48",
                "option_btn": "#241430",
                "option_hover": "#3A1F48",
                "option_bg": "#110A14",
                "option_drop": "#1E1224"
            },
            "Arctic": {
                "app_bg": "#0A0E14",
                "card_bg": "#131B26",
                "border": "#1F3044",
                "border_width": 1,
                "accent": "#67E8F9",
                "text_primary": "#F0F9FF",
                "text_secondary": "#7CA0B8",
                "btn_bg": "#0C1824",
                "btn_border": "#67E8F9",
                "btn_text": "#67E8F9",
                "btn_hover": "#1A2E42",
                "status_text": "● ONLINE",
                "status_color": "#67E8F9",
                "input_bg": "#0A0E14",
                "input_border": "#1F3044",
                "option_btn": "#152230",
                "option_hover": "#1F3044",
                "option_bg": "#0A0E14",
                "option_drop": "#131B26"
            },
            "Ember": {
                "app_bg": "#120C0C",
                "card_bg": "#1E1414",
                "border": "#3B2424",
                "border_width": 1,
                "accent": "#FB7185",
                "text_primary": "#FFF1F2",
                "text_secondary": "#B0787E",
                "btn_bg": "#2A1418",
                "btn_border": "#FB7185",
                "btn_text": "#FB7185",
                "btn_hover": "#3D2028",
                "status_text": "● ACTIVE",
                "status_color": "#FB7185",
                "input_bg": "#120C0C",
                "input_border": "#3B2424",
                "option_btn": "#241818",
                "option_hover": "#3B2424",
                "option_bg": "#120C0C",
                "option_drop": "#1E1414"
            },
            "Twilight": {
                "app_bg": "#0C0A16",
                "card_bg": "#161228",
                "border": "#2A2250",
                "border_width": 1,
                "accent": "#C4B5FD",
                "text_primary": "#F5F3FF",
                "text_secondary": "#9390B8",
                "btn_bg": "#1C1640",
                "btn_border": "#C4B5FD",
                "btn_text": "#C4B5FD",
                "btn_hover": "#2A2258",
                "status_text": "● DUSK",
                "status_color": "#C4B5FD",
                "input_bg": "#0C0A16",
                "input_border": "#2A2250",
                "option_btn": "#1A1638",
                "option_hover": "#2A2250",
                "option_bg": "#0C0A16",
                "option_drop": "#161228"
            },
            "Cipher": {
                "app_bg": "#0A0E0A",
                "card_bg": "#141E14",
                "border": "#243824",
                "border_width": 1,
                "accent": "#4ADE80",
                "text_primary": "#F0FDF4",
                "text_secondary": "#7AAC8A",
                "btn_bg": "#102210",
                "btn_border": "#4ADE80",
                "btn_text": "#4ADE80",
                "btn_hover": "#1E3A1E",
                "status_text": "● LINKED",
                "status_color": "#4ADE80",
                "input_bg": "#0A0E0A",
                "input_border": "#243824",
                "option_btn": "#162016",
                "option_hover": "#243824",
                "option_bg": "#0A0E0A",
                "option_drop": "#141E14"
            }
        }
        
        cfg = themes.get(theme_name, themes["Obsidian"])
        self.theme_cfg = cfg
        
        self.configure(fg_color=cfg["app_bg"])
        self.sidebar_frame.configure(fg_color=cfg["card_bg"])
        self.logo_label.configure(text_color=cfg["accent"])
        self.power_light.configure(text=cfg["status_text"], text_color=cfg["status_color"])

        for p_title in self.page_titles:
            p_title.configure(text_color=cfg["text_primary"])
        
        cards = [
            self.input_card, self.quality_card, self.options_card, self.action_card,
            self.tools_card, self.queue_card,
            self.spotify_input_card, self.spotify_meta_card, self.spotify_tracks_card,
            self.spotify_action_card, self.spotify_settings_card
        ]
        for card in cards:
            card.configure(
                fg_color=cfg["card_bg"], 
                border_color=cfg["border"], 
                border_width=cfg["border_width"]
            )
            
        for title_lbl in self.theme_titles:
            title_lbl.configure(text_color=cfg["text_primary"])
            
        for sec_lbl in self.theme_labels_secondary:
            sec_lbl.configure(text_color=cfg["text_secondary"])
            
        for entry in self.theme_entries:
            entry.configure(
                fg_color=cfg["input_bg"],
                border_color=cfg["input_border"],
                text_color="#F5F5F7",
                placeholder_text_color=cfg["text_secondary"]
            )
            
        for menu in self.theme_option_menus:
            menu.configure(
                fg_color=cfg["input_bg"],
                button_color=cfg["option_btn"],
                button_hover_color=cfg["option_hover"],
                dropdown_fg_color=cfg["option_drop"],
                text_color="#F5F5F7",
                dropdown_text_color="#F5F5F7",
                dropdown_hover_color=cfg["input_border"]
            )
            
        for sw in self.theme_switches:
            sw.configure(
                progress_color=cfg["accent"],
                text_color="#F5F5F7"
            )
            
        for chk in [self.season_checkbox, self.range_checkbox]:
            chk.configure(
                fg_color=cfg["option_btn"],
                hover_color=cfg["option_hover"],
                checkmark_color=cfg["input_bg"],
                text_color=cfg["text_secondary"]
            )
        
        for btn in self.theme_buttons_secondary:
            btn.configure(
                fg_color=cfg["input_bg"],
                border_color=cfg["btn_border"],
                border_width=1,
                text_color=cfg["btn_text"],
                hover_color=cfg["btn_hover"]
            )
            
        self.download_button.configure(
            fg_color=cfg["btn_bg"],
            border_color=cfg["btn_border"],
            text_color=cfg["btn_text"],
            hover_color=cfg["btn_hover"]
        )

        self.btn_spotify_start.configure(
            fg_color=cfg["btn_bg"],
            border_color=cfg["btn_border"],
            text_color=cfg["btn_text"],
            hover_color=cfg["btn_hover"]
        )
        
        self.progress.configure(
            progress_color=cfg["accent"],
            fg_color=cfg["input_bg"]
        )
        self.queue_progress.configure(
            progress_color=cfg["accent"],
            fg_color=cfg["input_bg"]
        )
        self.queue_counter_lbl.configure(text_color=cfg["text_primary"])

        self.spotify_progress_bar.configure(
            progress_color=cfg["accent"],
            fg_color=cfg["input_bg"]
        )
        self.spotify_counter_lbl.configure(text_color=cfg["text_primary"])
        if hasattr(self, 'spotify_art_frame'):
            self.spotify_art_frame.configure(fg_color=cfg["input_bg"], border_color=cfg["border"])
        for item in getattr(self, 'spotify_track_items', []):
            item["row_frame"].configure(fg_color=cfg["input_bg"], border_color=cfg["border"])
            item["checkbox"].configure(
                fg_color=cfg["option_btn"],
                hover_color=cfg["option_hover"],
                checkmark_color=cfg["input_bg"]
            )
        
        self.status_box.configure(
            fg_color=cfg["input_bg"],
            border_color=cfg["input_border"],
            text_color="#9E9EAF"
        )
        
        for card, card_url in self.search_result_widgets:
            card.configure(fg_color=cfg["input_bg"], border_color=cfg["border"])
            
        self.save_setting("theme", theme_name)
        
        if hasattr(self, 'active_tab'):
            self.select_tab(self.active_tab)


    # =========================================================================
    # --- Persistence Helpers ---
    # =========================================================================

    def load_saved_settings(self):
        try:
            exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
            settings_path = os.path.join(exe_dir, "settings.json")
            if os.path.exists(settings_path):
                with open(settings_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def save_setting(self, key, value):
        try:
            exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
            settings_path = os.path.join(exe_dir, "settings.json")
            current = self.load_saved_settings()
            current[key] = value
            with open(settings_path, "w", encoding="utf-8") as f:
                json.dump(current, f, indent=2)
            self.saved_settings = current
        except Exception as e:
            print(f"Failed to save setting {key}:", e)


    # =========================================================================
    # --- System Tray & Lifecycle Engine ---
    # =========================================================================

    def init_system_tray(self):
        """Initializes the background system tray icon for minimize-to-tray functionality."""
        try:
            icon_path = self.get_file_path("icon.ico")
            if os.path.exists(icon_path):
                img = Image.open(icon_path)
            else:
                img = Image.new('RGB', (64, 64), color='#00E5FF')

            menu = pystray.Menu(
                pystray.MenuItem("Open Shallot Media Archive", lambda icon, item: self.restore_from_tray(), default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Exit Application", lambda icon, item: self.quit_from_tray())
            )

            self.tray_icon = pystray.Icon("ShallotMediaArchive", img, "Shallot Media Archive", menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        except Exception as e:
            print(f"[Tray] System tray init error: {e}")

    def on_close_window(self):
        """Intercepts window close event (X button) and minimizes to taskbar / system tray."""
        self.withdraw()
        self.send_notification("Shallot Media Archive", "Minimized to taskbar tray. Right-click the icon to exit.")

    def restore_from_tray(self):
        """Restores window from system tray back to desktop."""
        self.after(0, self._restore_window_main_thread)

    def _restore_window_main_thread(self):
        self.deiconify()
        self.state("normal")
        self.lift()
        self.focus_force()

    def quit_from_tray(self):
        """Exits the application cleanly from the system tray menu."""
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.after(0, self.quit_application)

    def quit_application(self):
        """Cleanly halts all background tasks and terminates the application."""
        if hasattr(self, 'spotify_pipeline') and self.spotify_pipeline:
            self.spotify_pipeline.cancel()
        if self.active_process:
            self.emergency_process_cleanup()
        self.destroy()
        os._exit(0)


if __name__ == "__main__":
    app = DownloaderApp()
    app.mainloop()