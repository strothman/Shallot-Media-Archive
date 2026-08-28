import atexit
from concurrent.futures import ThreadPoolExecutor
import ctypes
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

# Ensure Windows Taskbar displays the dedicated app icon instead of generic python icon
if sys.platform.startswith("win"):
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ShallotMediaArchive.SMArchive.GUI.1.0")
    except Exception:
        pass

import customtkinter as ctk
from PIL import Image
import pystray
from spotify_sync import SpotifyAuthHelper, SpotifyFetcher, SpotifyPlexampPipeline
from youtube_sync import YouTubeFetcher, YouTubePlexampPipeline
from local_sync import LocalAudioScanner, LocalPlexampPipeline
from audio_verifier import AudioFactChecker

# --- Setup System PATH for Bundled JS Runtimes (e.g., deno.exe, ffmpeg.exe) ---
base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
for path in [base_path, exe_dir]:
    if path and os.path.abspath(path) not in [os.path.abspath(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p]:
        os.environ["PATH"] = os.path.abspath(path) + os.pathsep + os.environ.get("PATH", "")

BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
CREATION_FLAGS_BACKGROUND = (
    (subprocess.CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS)
    if os.name == 'nt' else 0
)


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

        # --- YouTube to Plexamp Sync State ---
        self.yt_plexamp_collection = None
        self.yt_plexamp_track_items = []
        self.yt_plexamp_pipeline = None
        self.yt_plexamp_art_image = None

        # --- Local to Plexamp Sync State ---
        self.local_plexamp_collection = None
        self.local_plexamp_track_items = []
        self.local_plexamp_pipeline = None

        # --- Audio Fact-Checker State ---
        self.verifier_scan_results = []
        self.verifier_track_items = []
        self.verifier_is_scanning = False
        self.verifier_cancel_event = threading.Event()
        self.verifier_filter_mode = "all"
        self.verifier_active_workers = {}

        # --- Custom Window & Taskbar Icon ---
        icon_path = self.get_file_path("shallot.ico")
        if not os.path.exists(icon_path):
            icon_path = self.get_file_path("icon.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

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

        self.btn_yt_plexamp = ctk.CTkButton(
            self.sidebar_frame,
            text="▶️  YouTube to Plexamp",
            font=("Segoe UI", 12, "bold"),
            height=38,
            corner_radius=8,
            anchor="w",
            command=lambda: self.select_tab("yt_plexamp")
        )
        self.btn_yt_plexamp.pack(fill="x", padx=15, pady=4)

        self.btn_local_plexamp = ctk.CTkButton(
            self.sidebar_frame,
            text="📁  Local to Plexamp",
            font=("Segoe UI", 12, "bold"),
            height=38,
            corner_radius=8,
            anchor="w",
            command=lambda: self.select_tab("local_plexamp")
        )
        self.btn_local_plexamp.pack(fill="x", padx=15, pady=4)

        self.btn_verifier = ctk.CTkButton(
            self.sidebar_frame,
            text="🔬  Fact-Check Audio",
            font=("Segoe UI", 12, "bold"),
            height=38,
            corner_radius=8,
            anchor="w",
            command=lambda: self.select_tab("verifier")
        )
        self.btn_verifier.pack(fill="x", padx=15, pady=4)

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

        self.btn_spotify_clear_completed = ctk.CTkButton(
            tracks_header,
            text="Clear Completed",
            width=95,
            height=24,
            font=("Segoe UI", 9, "bold"),
            command=self.clear_completed_spotify_tracks
        )
        self.btn_spotify_clear_completed.pack(side="right", padx=(4, 0))
        self.theme_buttons_secondary.append(self.btn_spotify_clear_completed)

        self.btn_spotify_deselect_all = ctk.CTkButton(
            tracks_header,
            text="Deselect All",
            width=75,
            height=24,
            font=("Segoe UI", 9, "bold"),
            command=lambda: self.toggle_all_spotify_tracks(False)
        )
        self.btn_spotify_deselect_all.pack(side="right", padx=(4, 0))
        self.theme_buttons_secondary.append(self.btn_spotify_deselect_all)

        self.btn_spotify_select_all = ctk.CTkButton(
            tracks_header,
            text="Select All",
            width=65,
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
        # --- Page 3.5: YouTube to Plexamp Page ---
        # =========================================================================
        self.yt_plexamp_page = ctk.CTkFrame(self.main_container, fg_color="transparent")

        lbl_yt = ctk.CTkLabel(self.yt_plexamp_page, text="YouTube to Plexamp", font=("Segoe UI", 18, "bold"), anchor="w")
        lbl_yt.pack(fill="x", padx=20, pady=(15, 8))
        self.page_titles.append(lbl_yt)

        # Card 1: Input / Source
        self.yt_plexamp_input_card = ctk.CTkFrame(self.yt_plexamp_page, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.yt_plexamp_input_card.pack(fill="x", padx=20, pady=4)

        card_yt_lbl = ctk.CTkLabel(self.yt_plexamp_input_card, text="YOUTUBE SOURCE", font=("Segoe UI", 11, "bold"), text_color="#00E5FF")
        card_yt_lbl.pack(anchor="w", padx=15, pady=(8, 3))
        self.theme_titles.append(card_yt_lbl)

        self.yt_plexamp_url_frame = ctk.CTkFrame(self.yt_plexamp_input_card, fg_color="transparent")
        self.yt_plexamp_url_frame.pack(fill="x", padx=15, pady=(2, 8))

        self.yt_plexamp_url_input = ctk.CTkEntry(
            self.yt_plexamp_url_frame,
            placeholder_text="Paste YouTube Playlist, Album, or Video URL...",
            height=32,
            fg_color="#070F15",
            border_color="#1F3A4E",
            text_color="#F5F5F7",
            placeholder_text_color="#78909C"
        )
        self.yt_plexamp_url_input.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.yt_plexamp_url_input.bind("<Return>", lambda e: self.fetch_yt_plexamp_playlist())
        self.theme_entries.append(self.yt_plexamp_url_input)

        self.btn_yt_plexamp_paste = ctk.CTkButton(
            self.yt_plexamp_url_frame,
            text="📋 Paste",
            width=70,
            height=32,
            font=("Segoe UI", 10, "bold"),
            command=self.paste_yt_plexamp_url
        )
        self.btn_yt_plexamp_paste.pack(side="left", padx=(0, 6))
        self.theme_buttons_secondary.append(self.btn_yt_plexamp_paste)

        self.btn_yt_plexamp_fetch = ctk.CTkButton(
            self.yt_plexamp_url_frame,
            text="⚡ Fetch Tracks",
            width=100,
            height=32,
            font=("Segoe UI", 10, "bold"),
            command=self.fetch_yt_plexamp_playlist
        )
        self.btn_yt_plexamp_fetch.pack(side="right")
        self.theme_buttons_secondary.append(self.btn_yt_plexamp_fetch)

        # Card 2: Collection Overview & Plexamp Options
        self.yt_plexamp_meta_card = ctk.CTkFrame(self.yt_plexamp_page, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.yt_plexamp_meta_card.pack(fill="x", padx=20, pady=4)

        card_yt_meta_lbl = ctk.CTkLabel(self.yt_plexamp_meta_card, text="COLLECTION & PLEXAMP CONFIGURATION", font=("Segoe UI", 11, "bold"), text_color="#00E5FF")
        card_yt_meta_lbl.pack(anchor="w", padx=15, pady=(8, 4))
        self.theme_titles.append(card_yt_meta_lbl)

        yt_meta_grid = ctk.CTkFrame(self.yt_plexamp_meta_card, fg_color="transparent")
        yt_meta_grid.pack(fill="x", padx=15, pady=(2, 8))
        yt_meta_grid.columnconfigure(0, weight=0)
        yt_meta_grid.columnconfigure(1, weight=1)
        yt_meta_grid.columnconfigure(2, weight=2)

        # Col 0: Artwork preview
        self.yt_plexamp_art_frame = ctk.CTkFrame(yt_meta_grid, width=64, height=64, fg_color="#070F15", corner_radius=8, border_color="#1F3A4E", border_width=1)
        self.yt_plexamp_art_frame.grid(row=0, column=0, rowspan=2, padx=(0, 10), pady=2, sticky="nw")
        self.yt_plexamp_art_frame.pack_propagate(False)

        placeholder_yt_art = Image.new('RGB', (64, 64), color='#1E1A24')
        self.yt_plexamp_art_img = ctk.CTkImage(light_image=placeholder_yt_art, dark_image=placeholder_yt_art, size=(64, 64))
        self.yt_plexamp_art_label = ctk.CTkLabel(self.yt_plexamp_art_frame, image=self.yt_plexamp_art_img, text="")
        self.yt_plexamp_art_label.pack(expand=True, fill="both")

        # Col 1: Collection Info
        yt_info_frame = ctk.CTkFrame(yt_meta_grid, fg_color="transparent")
        yt_info_frame.grid(row=0, column=1, rowspan=2, padx=(0, 10), sticky="nsew")

        self.yt_plexamp_title_lbl = ctk.CTkLabel(yt_info_frame, text="No YouTube Link Loaded", font=("Segoe UI", 12, "bold"), text_color="#F5F5F7", anchor="w")
        self.yt_plexamp_title_lbl.pack(fill="x", pady=(0, 1))

        self.yt_plexamp_author_lbl = ctk.CTkLabel(yt_info_frame, text="Paste a link & click 'Fetch Tracks'", font=("Segoe UI", 10), text_color="#78909C", anchor="w")
        self.yt_plexamp_author_lbl.pack(fill="x", pady=(0, 1))
        self.theme_labels_secondary.append(self.yt_plexamp_author_lbl)

        self.yt_plexamp_stats_lbl = ctk.CTkLabel(yt_info_frame, text="0 tracks found", font=("Segoe UI", 10, "bold"), text_color="#00E5FF", anchor="w")
        self.yt_plexamp_stats_lbl.pack(fill="x")
        self.theme_titles.append(self.yt_plexamp_stats_lbl)

        # Col 2: Destination & Options
        yt_cfg_frame = ctk.CTkFrame(yt_meta_grid, fg_color="transparent")
        yt_cfg_frame.grid(row=0, column=2, rowspan=2, sticky="nsew")

        # Music Folder row
        yt_fld_row = ctk.CTkFrame(yt_cfg_frame, fg_color="transparent")
        yt_fld_row.pack(fill="x", pady=(0, 4))
        lbl_yt_pfld = ctk.CTkLabel(yt_fld_row, text="Music Library:", font=("Segoe UI", 10, "bold"), text_color="#78909C", width=80, anchor="w")
        lbl_yt_pfld.pack(side="left")
        self.theme_labels_secondary.append(lbl_yt_pfld)

        default_plex_dir = self.saved_settings.get("plex_music_folder", r"C:\SMA-downloads\Music")
        self.yt_plexamp_folder_input = ctk.CTkEntry(yt_fld_row, placeholder_text=r"C:\SMA-downloads\Music", height=28, fg_color="#070F15", border_color="#1F3A4E", text_color="#F5F5F7", font=("Segoe UI", 10))
        self.yt_plexamp_folder_input.insert(0, default_plex_dir)
        self.yt_plexamp_folder_input.pack(side="left", fill="x", expand=True, padx=(4, 4))
        self.yt_plexamp_folder_input.bind("<FocusOut>", lambda e: self.save_setting("plex_music_folder", self.yt_plexamp_folder_input.get().strip()))
        self.yt_plexamp_folder_input.bind("<KeyRelease>", lambda e: self.save_setting("plex_music_folder", self.yt_plexamp_folder_input.get().strip()))
        self.theme_entries.append(self.yt_plexamp_folder_input)

        self.btn_yt_plexamp_browse = ctk.CTkButton(yt_fld_row, text="📂", width=32, height=28, font=("Segoe UI", 10, "bold"), command=self.browse_yt_plex_folder)
        self.btn_yt_plexamp_browse.pack(side="right")
        self.theme_buttons_secondary.append(self.btn_yt_plexamp_browse)

        # Row 1: Format + Org + Concurrency
        yt_opts_row1 = ctk.CTkFrame(yt_cfg_frame, fg_color="transparent")
        yt_opts_row1.pack(fill="x", pady=(0, 3))

        self.yt_plexamp_format_menu = ctk.CTkOptionMenu(
            yt_opts_row1,
            values=["MP3 (320 kbps)", "FLAC (Lossless)", "M4A (256 kbps)"],
            height=28,
            font=("Segoe UI", 10),
            dropdown_font=("Segoe UI", 10),
            command=lambda v: self.save_setting("yt_audio_format", v)
        )
        saved_yt_fmt = self.saved_settings.get("yt_audio_format", "MP3 (320 kbps)")
        if saved_yt_fmt in self.yt_plexamp_format_menu._values:
            self.yt_plexamp_format_menu.set(saved_yt_fmt)
        self.yt_plexamp_format_menu.pack(side="left", padx=(0, 4))
        self.theme_option_menus.append(self.yt_plexamp_format_menu)

        self.yt_plexamp_org_menu = ctk.CTkOptionMenu(
            yt_opts_row1,
            values=["Plex Standard (Artist/Album/Track)", "Playlist Folder (Playlists/Track)"],
            height=28,
            font=("Segoe UI", 10),
            dropdown_font=("Segoe UI", 10),
            command=lambda v: self.save_setting("yt_folder_structure", v)
        )
        saved_yt_org = self.saved_settings.get("yt_folder_structure", "Plex Standard (Artist/Album/Track)")
        if saved_yt_org in self.yt_plexamp_org_menu._values:
            self.yt_plexamp_org_menu.set(saved_yt_org)
        self.yt_plexamp_org_menu.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.theme_option_menus.append(self.yt_plexamp_org_menu)

        self.yt_plexamp_concurrency_menu = ctk.CTkOptionMenu(
            yt_opts_row1,
            values=["2 Tracks Concurrent", "3 Tracks Concurrent", "1 Track Safe"],
            height=28,
            width=120,
            font=("Segoe UI", 9),
            dropdown_font=("Segoe UI", 9),
            command=lambda v: self.save_setting("yt_concurrency", v)
        )
        saved_yt_conc = self.saved_settings.get("yt_concurrency", "2 Tracks Concurrent")
        if saved_yt_conc in self.yt_plexamp_concurrency_menu._values:
            self.yt_plexamp_concurrency_menu.set(saved_yt_conc)
        self.yt_plexamp_concurrency_menu.pack(side="left")
        self.theme_option_menus.append(self.yt_plexamp_concurrency_menu)

        # Row 2: Toggles (Artwork, Synced Lyrics, ReplayGain, Auto-Enrich)
        yt_opts_row2 = ctk.CTkFrame(yt_cfg_frame, fg_color="transparent")
        yt_opts_row2.pack(fill="x", pady=(2, 0))

        self.yt_plexamp_embed_art_switch = ctk.CTkSwitch(
            yt_opts_row2,
            text="Artwork",
            font=("Segoe UI", 9),
            width=58,
            height=18,
            command=lambda: self.save_setting("yt_embed_art", bool(self.yt_plexamp_embed_art_switch.get()))
        )
        if self.saved_settings.get("yt_embed_art", True):
            self.yt_plexamp_embed_art_switch.select()
        else:
            self.yt_plexamp_embed_art_switch.deselect()
        self.yt_plexamp_embed_art_switch.pack(side="left", padx=(0, 4))
        self.theme_switches.append(self.yt_plexamp_embed_art_switch)

        self.yt_plexamp_lyrics_switch = ctk.CTkSwitch(
            yt_opts_row2,
            text="Lyrics (.lrc)",
            font=("Segoe UI", 9),
            width=70,
            height=18,
            command=lambda: self.save_setting("yt_fetch_lyrics", bool(self.yt_plexamp_lyrics_switch.get()))
        )
        if self.saved_settings.get("yt_fetch_lyrics", True):
            self.yt_plexamp_lyrics_switch.select()
        else:
            self.yt_plexamp_lyrics_switch.deselect()
        self.yt_plexamp_lyrics_switch.pack(side="left", padx=(0, 4))
        self.theme_switches.append(self.yt_plexamp_lyrics_switch)

        self.yt_plexamp_gain_switch = ctk.CTkSwitch(
            yt_opts_row2,
            text="ReplayGain",
            font=("Segoe UI", 9),
            width=68,
            height=18,
            command=lambda: self.save_setting("yt_calculate_replaygain", bool(self.yt_plexamp_gain_switch.get()))
        )
        if self.saved_settings.get("yt_calculate_replaygain", True):
            self.yt_plexamp_gain_switch.select()
        else:
            self.yt_plexamp_gain_switch.deselect()
        self.yt_plexamp_gain_switch.pack(side="left", padx=(0, 4))
        self.theme_switches.append(self.yt_plexamp_gain_switch)

        self.yt_plexamp_enrich_switch = ctk.CTkSwitch(
            yt_opts_row2,
            text="Smart Tags",
            font=("Segoe UI", 9),
            width=68,
            height=18,
            command=lambda: self.save_setting("yt_auto_enrich", bool(self.yt_plexamp_enrich_switch.get()))
        )
        if self.saved_settings.get("yt_auto_enrich", True):
            self.yt_plexamp_enrich_switch.select()
        else:
            self.yt_plexamp_enrich_switch.deselect()
        self.yt_plexamp_enrich_switch.pack(side="left")
        self.theme_switches.append(self.yt_plexamp_enrich_switch)

        # Card 3: Tracklist Selection
        self.yt_plexamp_tracks_card = ctk.CTkFrame(self.yt_plexamp_page, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.yt_plexamp_tracks_card.pack(fill="both", expand=True, padx=20, pady=4)

        yt_tracks_header = ctk.CTkFrame(self.yt_plexamp_tracks_card, fg_color="transparent")
        yt_tracks_header.pack(fill="x", padx=15, pady=(8, 4))

        card_yt_trk_lbl = ctk.CTkLabel(yt_tracks_header, text="TRACKLIST SELECTION", font=("Segoe UI", 11, "bold"), text_color="#00E5FF")
        card_yt_trk_lbl.pack(side="left")
        self.theme_titles.append(card_yt_trk_lbl)

        self.yt_plexamp_track_count_lbl = ctk.CTkLabel(yt_tracks_header, text="0 / 0 Selected", font=("Segoe UI", 10, "bold"), text_color="#78909C")
        self.yt_plexamp_track_count_lbl.pack(side="left", padx=12)
        self.theme_labels_secondary.append(self.yt_plexamp_track_count_lbl)

        self.btn_yt_plexamp_clear_completed = ctk.CTkButton(
            yt_tracks_header,
            text="Clear Completed",
            width=95,
            height=24,
            font=("Segoe UI", 9, "bold"),
            command=self.clear_completed_yt_plexamp_tracks
        )
        self.btn_yt_plexamp_clear_completed.pack(side="right", padx=(4, 0))
        self.theme_buttons_secondary.append(self.btn_yt_plexamp_clear_completed)

        self.btn_yt_plexamp_deselect_all = ctk.CTkButton(
            yt_tracks_header,
            text="Deselect All",
            width=75,
            height=24,
            font=("Segoe UI", 9, "bold"),
            command=lambda: self.toggle_all_yt_plexamp_tracks(False)
        )
        self.btn_yt_plexamp_deselect_all.pack(side="right", padx=(4, 0))
        self.theme_buttons_secondary.append(self.btn_yt_plexamp_deselect_all)

        self.btn_yt_plexamp_select_all = ctk.CTkButton(
            yt_tracks_header,
            text="Select All",
            width=65,
            height=24,
            font=("Segoe UI", 9, "bold"),
            command=lambda: self.toggle_all_yt_plexamp_tracks(True)
        )
        self.btn_yt_plexamp_select_all.pack(side="right")
        self.theme_buttons_secondary.append(self.btn_yt_plexamp_select_all)

        # Scrollable Tracklist Frame
        self.yt_plexamp_track_scroll = ctk.CTkScrollableFrame(self.yt_plexamp_tracks_card, fg_color="transparent", border_width=0)
        self.yt_plexamp_track_scroll.pack(fill="both", expand=True, padx=12, pady=(0, 6))

        self.yt_plexamp_empty_lbl = ctk.CTkLabel(
            self.yt_plexamp_track_scroll,
            text="No tracks loaded yet. Enter a YouTube playlist or video URL above and click 'Fetch Tracks'.",
            font=("Segoe UI", 11),
            text_color="#78909C"
        )
        self.yt_plexamp_empty_lbl.pack(pady=30)
        self.theme_labels_secondary.append(self.yt_plexamp_empty_lbl)

        # Card 4: Action & Progress Card
        self.yt_plexamp_action_card = ctk.CTkFrame(self.yt_plexamp_page, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.yt_plexamp_action_card.pack(fill="x", padx=20, pady=(4, 10))

        yt_act_top = ctk.CTkFrame(self.yt_plexamp_action_card, fg_color="transparent")
        yt_act_top.pack(fill="x", padx=15, pady=(8, 2))

        self.yt_plexamp_status_lbl = ctk.CTkLabel(yt_act_top, text="Ready to sync", font=("Segoe UI", 10, "bold"), text_color="#78909C", anchor="w")
        self.yt_plexamp_status_lbl.pack(side="left")
        self.theme_labels_secondary.append(self.yt_plexamp_status_lbl)

        self.yt_plexamp_counter_lbl = ctk.CTkLabel(yt_act_top, text="0 / 0", font=("Segoe UI", 10, "bold"), text_color="#F5F5F7", anchor="e")
        self.yt_plexamp_counter_lbl.pack(side="right")

        self.yt_plexamp_progress_bar = ctk.CTkProgressBar(self.yt_plexamp_action_card, height=8, corner_radius=4, progress_color="#00E5FF", fg_color="#070F15")
        self.yt_plexamp_progress_bar.set(0)
        self.yt_plexamp_progress_bar.pack(fill="x", padx=15, pady=(2, 8))

        yt_act_btns = ctk.CTkFrame(self.yt_plexamp_action_card, fg_color="transparent")
        yt_act_btns.pack(fill="x", padx=15, pady=(0, 8))

        self.btn_yt_plexamp_start = ctk.CTkButton(
            yt_act_btns,
            text="🚀  Download & Tag for Plexamp",
            font=("Segoe UI", 12, "bold"),
            height=36,
            corner_radius=8,
            command=self.start_yt_plexamp_sync
        )
        self.btn_yt_plexamp_start.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.btn_yt_plexamp_open_folder = ctk.CTkButton(
            yt_act_btns,
            text="📂 Open Music Folder",
            font=("Segoe UI", 11, "bold"),
            height=36,
            width=140,
            corner_radius=8,
            fg_color="#0E1A24",
            border_color="#00E5FF",
            border_width=1,
            text_color="#00E5FF",
            command=self.open_yt_plexamp_music_folder
        )
        self.btn_yt_plexamp_open_folder.pack(side="left", padx=(0, 6))
        self.theme_buttons_secondary.append(self.btn_yt_plexamp_open_folder)

        self.btn_yt_plexamp_stop = ctk.CTkButton(
            yt_act_btns,
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
            command=self.stop_yt_plexamp_sync
        )
        self.btn_yt_plexamp_stop.pack(side="right")

        # =========================================================================
        # --- Page 3.75: Local to Plexamp Page ---
        # =========================================================================
        self.local_plexamp_page = ctk.CTkFrame(self.main_container, fg_color="transparent")

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

        # =========================================================================
        # --- Page: Audio Fact-Checker & Verifier Page ---
        # =========================================================================
        self.verifier_page = ctk.CTkFrame(self.main_container, fg_color="transparent")

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

        v_input_frame = ctk.CTkFrame(self.verifier_source_card, fg_color="transparent")
        v_input_frame.pack(fill="x", padx=15, pady=(2, 4))

        self.verifier_folder_input = ctk.CTkEntry(
            v_input_frame,
            placeholder_text="e.g. \\\\joandesk\\Music\\Strothman or local music directory...",
            height=32,
            fg_color="#070F15",
            border_color="#1F3A4E",
            text_color="#F5F5F7"
        )
        saved_vdir = self.saved_settings.get("plex_music_folder", "") or self.saved_settings.get("destination_folder", "")
        if saved_vdir:
            self.verifier_folder_input.insert(0, saved_vdir)
        self.verifier_folder_input.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.theme_entries.append(self.verifier_folder_input)

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

        v_stats_inner = ctk.CTkFrame(self.verifier_stats_card, fg_color="transparent")
        v_stats_inner.pack(fill="x", padx=15, pady=6)

        self.verifier_lbl_total = ctk.CTkLabel(v_stats_inner, text="0 Scanned", font=("Segoe UI", 10, "bold"), text_color="#78909C", cursor="hand2")
        self.verifier_lbl_total.pack(side="left", padx=(0, 10))
        self.verifier_lbl_total.bind("<Button-1>", lambda e: self.set_verifier_filter("all"))

        self.verifier_lbl_mismatch = ctk.CTkLabel(v_stats_inner, text="0 ⚠️ Mismatches", font=("Segoe UI", 10, "bold"), text_color="#FB7185", cursor="hand2")
        self.verifier_lbl_mismatch.pack(side="left", padx=(0, 10))
        self.verifier_lbl_mismatch.bind("<Button-1>", lambda e: self.set_verifier_filter("mismatch"))

        self.verifier_lbl_verified = ctk.CTkLabel(v_stats_inner, text="0 ✅ Verified", font=("Segoe UI", 10, "bold"), text_color="#4ADE80", cursor="hand2")
        self.verifier_lbl_verified.pack(side="left", padx=(0, 10))
        self.verifier_lbl_verified.bind("<Button-1>", lambda e: self.set_verifier_filter("verified"))

        self.verifier_lbl_unrec = ctk.CTkLabel(v_stats_inner, text="0 ❓ Unknown", font=("Segoe UI", 10, "bold"), text_color="#94A3B8", cursor="hand2")
        self.verifier_lbl_unrec.pack(side="left", padx=(0, 15))
        self.verifier_lbl_unrec.bind("<Button-1>", lambda e: self.set_verifier_filter("unrec"))

        self.btn_verifier_deselect_all = ctk.CTkButton(
            v_stats_inner,
            text="Deselect All",
            width=75,
            height=24,
            font=("Segoe UI", 9, "bold"),
            command=lambda: self.toggle_all_verifier_items(False)
        )
        self.btn_verifier_deselect_all.pack(side="right", padx=(4, 0))
        self.theme_buttons_secondary.append(self.btn_verifier_deselect_all)

        self.btn_verifier_select_all = ctk.CTkButton(
            v_stats_inner,
            text="Select All",
            width=65,
            height=24,
            font=("Segoe UI", 9, "bold"),
            command=lambda: self.toggle_all_verifier_items(True)
        )
        self.btn_verifier_select_all.pack(side="right", padx=(4, 0))
        self.theme_buttons_secondary.append(self.btn_verifier_select_all)

        self.btn_vfilt_unrec = ctk.CTkButton(
            v_stats_inner,
            text="❓ Unknown",
            width=75,
            height=24,
            font=("Segoe UI", 9, "bold"),
            command=lambda: self.set_verifier_filter("unrec")
        )
        self.btn_vfilt_unrec.pack(side="right", padx=(4, 0))
        self.theme_buttons_secondary.append(self.btn_vfilt_unrec)

        self.btn_vfilt_verified = ctk.CTkButton(
            v_stats_inner,
            text="✅ Verified",
            width=70,
            height=24,
            font=("Segoe UI", 9, "bold"),
            command=lambda: self.set_verifier_filter("verified")
        )
        self.btn_vfilt_verified.pack(side="right", padx=(4, 0))
        self.theme_buttons_secondary.append(self.btn_vfilt_verified)

        self.btn_vfilt_mismatch = ctk.CTkButton(
            v_stats_inner,
            text="⚠️ Mismatches",
            width=88,
            height=24,
            font=("Segoe UI", 9, "bold"),
            command=lambda: self.set_verifier_filter("mismatch")
        )
        self.btn_vfilt_mismatch.pack(side="right", padx=(4, 0))
        self.theme_buttons_secondary.append(self.btn_vfilt_mismatch)

        self.btn_vfilt_all = ctk.CTkButton(
            v_stats_inner,
            text="All",
            width=45,
            height=24,
            font=("Segoe UI", 9, "bold"),
            command=lambda: self.set_verifier_filter("all")
        )
        self.btn_vfilt_all.pack(side="right", padx=(4, 0))
        self.theme_buttons_secondary.append(self.btn_vfilt_all)

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

        self.verifier_status_lbl = ctk.CTkLabel(v_act_top, text="Ready to fact-check audio library", font=("Segoe UI", 10, "bold"), text_color="#78909C", anchor="w")
        self.verifier_status_lbl.pack(side="left")
        self.theme_labels_secondary.append(self.verifier_status_lbl)

        self.verifier_counter_lbl = ctk.CTkLabel(v_act_top, text="0 / 0", font=("Segoe UI", 10, "bold"), text_color="#F5F5F7", anchor="e")
        self.verifier_counter_lbl.pack(side="right")

        self.verifier_progress_bar = ctk.CTkProgressBar(self.verifier_action_card, height=8, corner_radius=4, progress_color="#00E5FF", fg_color="#070F15")
        self.verifier_progress_bar.set(0)
        self.verifier_progress_bar.pack(fill="x", padx=15, pady=(2, 4))

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
            values=["Midnight", "Carbon", "Nordic"],
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
        saved_theme = self.saved_settings.get("theme", "Midnight")
        if saved_theme not in ["Midnight", "Carbon", "Nordic"]:
            saved_theme = "Midnight"
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

        # 1-Click Spotify Authorization Row
        sp_auth_row = ctk.CTkFrame(self.spotify_settings_card, fg_color="transparent")
        sp_auth_row.pack(fill="x", padx=15, pady=(8, 12))

        self.btn_spotify_auth = ctk.CTkButton(
            sp_auth_row,
            text="🔗 Connect Spotify (Unlocks 700+ Songs)",
            height=32,
            font=("Segoe UI", 11, "bold"),
            command=self.authenticate_spotify_account
        )
        self.btn_spotify_auth.pack(side="left", padx=(0, 10))
        self.theme_buttons_secondary.append(self.btn_spotify_auth)

        has_tok = bool(self.saved_settings.get("spotify_refresh_token"))
        self.lbl_spotify_auth_status = ctk.CTkLabel(
            sp_auth_row,
            text="✓ Spotify Connected (All 700+ Songs Unlocked)" if has_tok else "Status: Click to authorize in browser",
            font=("Segoe UI", 10, "bold"),
            text_color="#4ADE80" if has_tok else "#78909C"
        )
        self.lbl_spotify_auth_status.pack(side="left")

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
            "yt_plexamp": (self.btn_yt_plexamp, self.yt_plexamp_page),
            "local_plexamp": (self.btn_local_plexamp, self.local_plexamp_page),
            "verifier": (self.btn_verifier, self.verifier_page),
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

    def authenticate_spotify_account(self):
        """Launches 1-click browser authorization for Spotify Web API to unlock 700+ songs."""
        cid = self.spotify_cid_entry.get().strip() or self.saved_settings.get("spotify_client_id", "")
        csec = self.spotify_csec_entry.get().strip() or self.saved_settings.get("spotify_client_secret", "")
        if not cid or not csec:
            self.lbl_spotify_auth_status.configure(text="Please enter Client ID & Secret first", text_color="#FB7185")
            return

        self.save_setting("spotify_client_id", cid)
        self.save_setting("spotify_client_secret", csec)
        self.btn_spotify_auth.configure(state="disabled", text="Connecting in Browser... ⏳")
        self.lbl_spotify_auth_status.configure(text="Waiting for browser approval...", text_color="#38BDF8")

        def on_done(refresh_tok, error):
            if refresh_tok:
                self.save_setting("spotify_refresh_token", refresh_tok)
                self.after(0, lambda: self.lbl_spotify_auth_status.configure(text="✓ Spotify Connected (All 700+ Songs Unlocked)", text_color="#4ADE80"))
                self.after(0, lambda: self.btn_spotify_auth.configure(state="normal", text="✓ Re-Authorize Account"))
                self.log("SUCCESS: Spotify Account authorized! Unlimited playlist size unlocked.")
                if self.spotify_url_input.get().strip():
                    self.after(500, self.fetch_spotify_playlist)
            else:
                self.after(0, lambda: self.lbl_spotify_auth_status.configure(text=f"Auth Error: {str(error)[:40]}", text_color="#FB7185"))
                self.after(0, lambda: self.btn_spotify_auth.configure(state="normal", text="🔗 Connect Spotify"))
                self.log(f"Spotify auth failed: {error}", is_error=True)

        SpotifyAuthHelper.authorize_in_browser(cid, csec, on_done)

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
            rtok = self.saved_settings.get("spotify_refresh_token", "")
            fetcher = SpotifyFetcher(client_id=cid, client_secret=csec, refresh_token=rtok)

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

        # Populate Tracklist smoothly in non-blocking slices
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

        batch_size = 40

        def render_chunk(start_idx=0):
            end_idx = min(start_idx + batch_size, total_count)
            for idx in range(start_idx + 1, end_idx + 1):
                track = tracks[idx - 1]
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
                try:
                    coll = self.spotify_collection or {}
                    is_in_lib = SpotifyPlexampPipeline.check_existing_track(
                        dest_folder, track, coll, audio_fmt, folder_struct
                    )
                except Exception:
                    is_in_lib = False
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
            if end_idx < total_count:
                self.spotify_status_lbl.configure(text=f"Loading tracklist... ({end_idx}/{total_count})", text_color=getattr(self, 'theme_cfg', {}).get("accent", "#00E5FF"))
                self.after(2, lambda: render_chunk(end_idx))
            else:
                self.spotify_status_lbl.configure(text=f"Loaded {total_count} songs. Select songs and click 'Download & Tag'.", text_color=getattr(self, 'theme_cfg', {}).get("text_primary", "#F5F5F7"))

        render_chunk(0)

    def toggle_all_spotify_tracks(self, select_all: bool):
        for item in self.spotify_track_items:
            item["var"].set(1 if select_all else 0)
        self.update_spotify_selected_count()

    def clear_completed_spotify_tracks(self):
        """ Removes tracks that are already in the Plex library or marked done from the view """
        if not self.spotify_track_items:
            return
        remaining_items = []
        for item in self.spotify_track_items:
            status_text = item["status_badge"].cget("text")
            if "✓" in status_text:
                item["row_frame"].destroy()
            else:
                remaining_items.append(item)
        self.spotify_track_items = remaining_items
        self.update_spotify_selected_count()
        if not self.spotify_track_items:
            empty_lbl = ctk.CTkLabel(
                self.spotify_track_scroll,
                text="✓ All completed tracks cleared. All caught up!",
                font=("Segoe UI", 11, "bold"),
                text_color=getattr(self, 'theme_cfg', {}).get("accent", "#00E5FF")
            )
            empty_lbl.pack(pady=30)
            self.theme_labels_secondary.append(empty_lbl)

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
            if not self.spotify_pipeline:
                return
            self.log(f"Starting Spotify to Plexamp sync ({len(selected_tracks)} songs) to: {dest_folder} (Concurrency: {concurrency})")
            coll = self.spotify_collection or {}
            stats = self.spotify_pipeline.process_playlist(
                collection=coll,
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
    # --- YouTube to Plexamp Controller Methods ---
    # =========================================================================

    def paste_yt_plexamp_url(self):
        """ Pastes clipboard contents into the YouTube URL input and triggers fetch """
        try:
            clipboard_text = self.clipboard_get().strip()
            if clipboard_text:
                self.yt_plexamp_url_input.delete(0, "end")
                self.yt_plexamp_url_input.insert(0, clipboard_text)
                self.fetch_yt_plexamp_playlist()
        except Exception as e:
            self.log(f"YouTube clipboard paste error: {e}", is_error=True)

    def browse_yt_plex_folder(self):
        """ Opens folder picker dialog to select Plex music library folder """
        current_val = self.yt_plexamp_folder_input.get().strip() or r"C:\SMA-downloads\Music"
        init_dir = current_val if os.path.exists(current_val) else r"C:\\"
        selected_dir = ctk.filedialog.askdirectory(initialdir=init_dir, title="Select Plexamp Music Library Folder")
        if selected_dir:
            selected_dir = os.path.normpath(selected_dir)
            self.yt_plexamp_folder_input.delete(0, "end")
            self.yt_plexamp_folder_input.insert(0, selected_dir)
            if hasattr(self, 'spotify_folder_input'):
                self.spotify_folder_input.delete(0, "end")
                self.spotify_folder_input.insert(0, selected_dir)
            self.save_setting("plex_music_folder", selected_dir)

    def fetch_yt_plexamp_playlist(self):
        """ Fetches metadata and tracklist for the entered YouTube link in a worker thread """
        url = self.yt_plexamp_url_input.get().strip()
        if not url:
            self.yt_plexamp_status_lbl.configure(text="Please enter a valid YouTube URL.", text_color="#FB7185")
            return

        self.btn_yt_plexamp_fetch.configure(state="disabled", text="Fetching... ⏳")
        self.yt_plexamp_status_lbl.configure(text="Fetching playlist metadata from YouTube...", text_color=getattr(self, 'theme_cfg', {}).get("accent", "#00E5FF"))

        def run_fetch():
            yt_dlp_path = self.get_active_yt_dlp_path()
            cookie_args = self.get_cookie_args()

            try:
                collection = YouTubeFetcher.fetch_entity(url, yt_dlp_path, cookie_args)
                self.yt_plexamp_collection = collection
                self.after(0, lambda: self.display_yt_plexamp_collection(collection))
            except Exception as e:
                err_msg = str(e)
                self.log(f"YouTube fetch error: {err_msg}", is_error=True)
                self.after(0, lambda msg=err_msg: self.show_yt_plexamp_fetch_error(msg))
            finally:
                self.after(0, lambda: self.btn_yt_plexamp_fetch.configure(state="normal", text="⚡ Fetch Tracks"))

        threading.Thread(target=run_fetch, daemon=True).start()

    def show_yt_plexamp_fetch_error(self, err_msg):
        self.yt_plexamp_status_lbl.configure(text=f"Error: {err_msg[:60]}", text_color="#FB7185")
        for widget in self.yt_plexamp_track_scroll.winfo_children():
            widget.destroy()
        lbl = ctk.CTkLabel(self.yt_plexamp_track_scroll, text=f"Failed to fetch YouTube link:\n{err_msg}", font=("Segoe UI", 11), text_color="#FB7185")
        lbl.pack(pady=25)

    def display_yt_plexamp_collection(self, collection):
        """ Renders the fetched YouTube collection header, cover art, and interactive tracklist """
        title = collection.get("title", "YouTube Collection")
        author = collection.get("author", "")
        tracks = collection.get("tracks", [])
        total_count = len(tracks)

        self.yt_plexamp_title_lbl.configure(text=title[:38] + ("..." if len(title) > 38 else ""))
        self.yt_plexamp_author_lbl.configure(text=f"By: {author}" if author else "YouTube")
        self.yt_plexamp_stats_lbl.configure(text=f"{total_count} tracks ready to sync")

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
                    raw_img = Image.open(io.BytesIO(img_data)).convert("RGB")
                    w, h = raw_img.size
                    min_dim = min(w, h)
                    left = (w - min_dim) // 2
                    top = (h - min_dim) // 2
                    cropped = raw_img.crop((left, top, left + min_dim, top + min_dim)).resize((64, 64), Image.Resampling.LANCZOS)
                    ctk_img = ctk.CTkImage(light_image=cropped, dark_image=cropped, size=(64, 64))
                    self.after(0, lambda: self.yt_plexamp_art_label.configure(image=ctk_img))
                    self.yt_plexamp_art_image = ctk_img
                except Exception as e:
                    print("YouTube cover art fetch failed:", e)

            threading.Thread(target=load_cover, daemon=True).start()

        # Populate Tracklist smoothly in non-blocking slices
        for widget in self.yt_plexamp_track_scroll.winfo_children():
            widget.destroy()

        self.yt_plexamp_track_items = []
        input_bg = getattr(self, 'theme_cfg', {}).get('input_bg', '#070F15')
        border_col = getattr(self, 'theme_cfg', {}).get('border', '#1F3A4E')
        text_sec = getattr(self, 'theme_cfg', {}).get('text_secondary', '#78909C')

        dest_folder = self.yt_plexamp_folder_input.get().strip() or r"C:\SMA-downloads\Music"
        raw_fmt = self.yt_plexamp_format_menu.get().lower()
        audio_fmt = "flac" if "flac" in raw_fmt else ("m4a" if "m4a" in raw_fmt else "mp3")
        raw_org = self.yt_plexamp_org_menu.get()
        folder_struct = "playlist_folder" if "Playlist Folder" in raw_org else "plex_standard"

        batch_size = 40

        def render_chunk(start_idx=0):
            end_idx = min(start_idx + batch_size, total_count)
            for idx in range(start_idx + 1, end_idx + 1):
                track = tracks[idx - 1]
                row_frame = ctk.CTkFrame(self.yt_plexamp_track_scroll, fg_color=input_bg, border_color=border_col, border_width=1, corner_radius=6, height=36)
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
                    command=self.update_yt_plexamp_selected_count
                )
                chk.pack(side="left", padx=(8, 4), pady=4)

                num_lbl = ctk.CTkLabel(row_frame, text=f"{idx:02d}.", font=("Segoe UI", 10, "bold"), text_color=text_sec, width=24, anchor="e")
                num_lbl.pack(side="left", padx=(0, 6))

                t_title = track.get("title", "Unknown")
                t_artist = track.get("artist", "Unknown")
                t_album = track.get("album", "")

                title_text = f"{t_title} - {t_artist}"
                if t_album and t_album not in ["YouTube Collection", "YouTube Playlist", "YouTube Music"]:
                    title_text += f"   [{t_album}]"

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
                try:
                    coll = self.yt_plexamp_collection or {}
                    is_in_lib = YouTubePlexampPipeline.check_existing_track(
                        dest_folder, track, coll, audio_fmt, folder_struct
                    )
                except Exception:
                    is_in_lib = False
                init_status = "✓ In Library" if is_in_lib else "Ready"
                init_color = "#4ADE80" if is_in_lib else "#78909C"

                status_badge = ctk.CTkLabel(row_frame, text=init_status, font=("Segoe UI", 9, "bold"), text_color=init_color, width=75, anchor="e")
                status_badge.pack(side="right", padx=(0, 10))

                self.yt_plexamp_track_items.append({
                    "track": track,
                    "var": chk_var,
                    "row_frame": row_frame,
                    "status_badge": status_badge,
                    "checkbox": chk
                })

            self.update_yt_plexamp_selected_count()
            if end_idx < total_count:
                self.yt_plexamp_status_lbl.configure(text=f"Loading tracklist... ({end_idx}/{total_count})", text_color=getattr(self, 'theme_cfg', {}).get("accent", "#00E5FF"))
                self.after(2, lambda: render_chunk(end_idx))
            else:
                self.yt_plexamp_status_lbl.configure(text=f"Loaded {total_count} songs. Select songs and click 'Download & Tag'.", text_color=getattr(self, 'theme_cfg', {}).get("text_primary", "#F5F5F7"))

        render_chunk(0)

    def toggle_all_yt_plexamp_tracks(self, select_all: bool):
        for item in self.yt_plexamp_track_items:
            item["var"].set(1 if select_all else 0)
        self.update_yt_plexamp_selected_count()

    def clear_completed_yt_plexamp_tracks(self):
        """ Removes tracks that are already in the Plex library or marked done from the view """
        if not self.yt_plexamp_track_items:
            return
        remaining_items = []
        for item in self.yt_plexamp_track_items:
            status_text = item["status_badge"].cget("text")
            if "✓" in status_text:
                item["row_frame"].destroy()
            else:
                remaining_items.append(item)
        self.yt_plexamp_track_items = remaining_items
        self.update_yt_plexamp_selected_count()
        if not self.yt_plexamp_track_items:
            empty_lbl = ctk.CTkLabel(
                self.yt_plexamp_track_scroll,
                text="✓ All completed tracks cleared. All caught up!",
                font=("Segoe UI", 11, "bold"),
                text_color=getattr(self, 'theme_cfg', {}).get("accent", "#00E5FF")
            )
            empty_lbl.pack(pady=30)
            self.theme_labels_secondary.append(empty_lbl)

    def update_yt_plexamp_selected_count(self):
        selected = sum(1 for item in self.yt_plexamp_track_items if item["var"].get() == 1)
        total = len(self.yt_plexamp_track_items)
        self.yt_plexamp_track_count_lbl.configure(text=f"{selected} / {total} Selected")
        self.yt_plexamp_counter_lbl.configure(text=f"0 / {selected}")

    def open_yt_plexamp_music_folder(self):
        """ Opens the Plex music folder in Windows Explorer """
        folder = self.yt_plexamp_folder_input.get().strip() or r"C:\SMA-downloads\Music"
        os.makedirs(folder, exist_ok=True)
        try:
            os.startfile(folder)
        except Exception as e:
            self.log(f"Failed to open folder '{folder}': {e}", is_error=True)

    def start_yt_plexamp_sync(self):
        """ Runs the YouTube direct audio download and Plexamp tagging pipeline """
        if not self.yt_plexamp_collection:
            self.yt_plexamp_status_lbl.configure(text="Please fetch a YouTube playlist first.", text_color="#FB7185")
            return

        selected_tracks = []
        for idx, item in enumerate(self.yt_plexamp_track_items):
            if item["var"].get() == 1:
                t = dict(item["track"])
                t["_track_index"] = idx
                selected_tracks.append(t)

        if not selected_tracks:
            self.yt_plexamp_status_lbl.configure(text="No tracks selected. Check at least one song.", text_color="#FB7185")
            return

        dest_folder = self.yt_plexamp_folder_input.get().strip() or r"C:\SMA-downloads\Music"
        self.save_setting("plex_music_folder", dest_folder)

        raw_fmt = self.yt_plexamp_format_menu.get().lower()
        audio_fmt = "flac" if "flac" in raw_fmt else ("m4a" if "m4a" in raw_fmt else "mp3")

        raw_org = self.yt_plexamp_org_menu.get()
        folder_struct = "playlist_folder" if "Playlist Folder" in raw_org else "plex_standard"

        embed_art = bool(self.yt_plexamp_embed_art_switch.get())
        fetch_lyrics = bool(self.yt_plexamp_lyrics_switch.get())
        calc_replaygain = bool(self.yt_plexamp_gain_switch.get())
        auto_enrich = bool(self.yt_plexamp_enrich_switch.get())

        raw_conc = self.yt_plexamp_concurrency_menu.get()
        concurrency = 2
        if "3" in raw_conc:
            concurrency = 3
        elif "1" in raw_conc:
            concurrency = 1

        yt_dlp_path = self.get_active_yt_dlp_path()
        cookie_args = self.get_cookie_args()

        self.btn_yt_plexamp_start.configure(state="disabled", text="Syncing to Plexamp... ⏳")
        self.yt_plexamp_progress_bar.set(0)
        self.power_light.configure(text="● SYNCING", text_color=getattr(self, 'theme_cfg', {}).get("accent", "#00E5FF"))

        def log_cb(msg: str, is_error: bool = False):
            self.log(f"[YouTube] {msg}", is_error=is_error)

        def progress_cb(pct: float, status_text: str):
            self.after(0, lambda: self.yt_plexamp_progress_bar.set(pct))
            self.after(0, lambda: self.yt_plexamp_status_lbl.configure(text=status_text))
            self.after(0, lambda: self.update_taskbar_progress(int(pct * 100)))

        def track_status_cb(track_index: int, text: str, color: str):
            if track_index < len(self.yt_plexamp_track_items):
                badge = self.yt_plexamp_track_items[track_index]["status_badge"]
                self.after(0, lambda b=badge, t=text, c=color: b.configure(text=t, text_color=c))

        self.yt_plexamp_pipeline = YouTubePlexampPipeline(
            yt_dlp_path=yt_dlp_path,
            cookie_args=cookie_args,
            log_callback=log_cb,
            progress_callback=progress_cb,
            track_status_callback=track_status_cb
        )

        def run_pipeline():
            if not self.yt_plexamp_pipeline:
                return
            self.log(f"Starting YouTube to Plexamp sync ({len(selected_tracks)} songs) to: {dest_folder} (Concurrency: {concurrency})")
            coll = self.yt_plexamp_collection or {}
            stats = self.yt_plexamp_pipeline.process_playlist(
                collection=coll,
                selected_tracks=selected_tracks,
                base_music_dir=dest_folder,
                audio_format=audio_fmt,
                folder_structure=folder_struct,
                embed_art=embed_art,
                save_cover_file=True,
                fetch_lyrics=fetch_lyrics,
                calculate_replaygain=calc_replaygain,
                auto_enrich=auto_enrich,
                concurrency=concurrency
            )
            self.after(0, lambda: self.finish_yt_plexamp_sync(stats))

        threading.Thread(target=run_pipeline, daemon=True).start()

    def stop_yt_plexamp_sync(self):
        """ Cancels the active YouTube download pipeline """
        if self.yt_plexamp_pipeline:
            self.yt_plexamp_pipeline.cancel()
            self.yt_plexamp_status_lbl.configure(text="Sync cancelled by user.", text_color="#FB7185")
            self.power_light.configure(text="● STOPPED", text_color="#FB7185")
            self.reset_yt_plexamp_sync_button()

    def finish_yt_plexamp_sync(self, stats):
        completed = stats.get("completed", 0)
        failed = stats.get("failed", 0)
        self.log(f"🏁 YouTube Sync finished: {completed} ready in Plex library, {failed} errors.")
        self.send_notification("YouTube Sync Complete", f"{completed} tracks ready for Plexamp!")
        self.yt_plexamp_status_lbl.configure(
            text=f"✓ Complete! {completed} tracks ready for Plexamp. ({failed} errors)",
            text_color=getattr(self, 'theme_cfg', {}).get("accent", "#00E5FF") if failed == 0 else "#FB7185"
        )
        self.reset_yt_plexamp_sync_button()

    def reset_yt_plexamp_sync_button(self):
        self.btn_yt_plexamp_start.configure(state="normal", text="🚀  Download & Tag for Plexamp")
        self.update_taskbar_progress(0)
        self.power_light.configure(
            text=getattr(self, 'theme_cfg', {}).get("status_text", "● READY"),
            text_color=getattr(self, 'theme_cfg', {}).get("status_color", "#38BDF8")
        )

    # =========================================================================
    # --- Local to Plexamp Controller Methods ---
    # =========================================================================

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

    # =========================================================================
    # --- Theme & Style Engine ---
    # =========================================================================

    def apply_theme(self, theme_name):
        themes = {
            "Midnight": {
                "app_bg": "#0B0F17",
                "card_bg": "#151B26",
                "border": "#263042",
                "border_width": 1,
                "accent": "#38BDF8",
                "text_primary": "#F8FAFC",
                "text_secondary": "#94A3B8",
                "btn_bg": "#1E293B",
                "btn_border": "#38BDF8",
                "btn_text": "#38BDF8",
                "btn_hover": "#2C3B52",
                "status_text": "● READY",
                "status_color": "#38BDF8",
                "input_bg": "#0B0F17",
                "input_border": "#263042",
                "option_btn": "#1E293B",
                "option_hover": "#2C3B52",
                "option_bg": "#0B0F17",
                "option_drop": "#151B26"
            },
            "Carbon": {
                "app_bg": "#121214",
                "card_bg": "#18181B",
                "border": "#27272A",
                "border_width": 1,
                "accent": "#10B981",
                "text_primary": "#FAFAFA",
                "text_secondary": "#A1A1AA",
                "btn_bg": "#27272A",
                "btn_border": "#10B981",
                "btn_text": "#10B981",
                "btn_hover": "#3F3F46",
                "status_text": "● READY",
                "status_color": "#10B981",
                "input_bg": "#121214",
                "input_border": "#27272A",
                "option_btn": "#27272A",
                "option_hover": "#3F3F46",
                "option_bg": "#121214",
                "option_drop": "#18181B"
            },
            "Nordic": {
                "app_bg": "#0F172A",
                "card_bg": "#1E293B",
                "border": "#334155",
                "border_width": 1,
                "accent": "#818CF8",
                "text_primary": "#F8FAFC",
                "text_secondary": "#94A3B8",
                "btn_bg": "#312E81",
                "btn_border": "#818CF8",
                "btn_text": "#818CF8",
                "btn_hover": "#3730A3",
                "status_text": "● READY",
                "status_color": "#818CF8",
                "input_bg": "#0F172A",
                "input_border": "#334155",
                "option_btn": "#334155",
                "option_hover": "#475569",
                "option_bg": "#0F172A",
                "option_drop": "#1E293B"
            }
        }
        
        cfg = themes.get(theme_name, themes["Midnight"])
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
            self.spotify_action_card, self.spotify_settings_card,
            self.yt_plexamp_input_card, self.yt_plexamp_meta_card, self.yt_plexamp_tracks_card,
            self.yt_plexamp_action_card,
            self.local_input_card, self.local_meta_card, self.local_tracks_card,
            self.local_action_card
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

        if hasattr(self, 'btn_yt_plexamp_start'):
            self.btn_yt_plexamp_start.configure(
                fg_color=cfg["btn_bg"],
                border_color=cfg["btn_border"],
                text_color=cfg["btn_text"],
                hover_color=cfg["btn_hover"]
            )

        if hasattr(self, 'btn_local_start'):
            self.btn_local_start.configure(
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

        if hasattr(self, 'yt_plexamp_progress_bar'):
            self.yt_plexamp_progress_bar.configure(
                progress_color=cfg["accent"],
                fg_color=cfg["input_bg"]
            )
        if hasattr(self, 'yt_plexamp_counter_lbl'):
            self.yt_plexamp_counter_lbl.configure(text_color=cfg["text_primary"])
        if hasattr(self, 'yt_plexamp_art_frame'):
            self.yt_plexamp_art_frame.configure(fg_color=cfg["input_bg"], border_color=cfg["border"])
        for item in getattr(self, 'yt_plexamp_track_items', []):
            item["row_frame"].configure(fg_color=cfg["input_bg"], border_color=cfg["border"])
            item["checkbox"].configure(
                fg_color=cfg["option_btn"],
                hover_color=cfg["option_hover"],
                checkmark_color=cfg["input_bg"]
            )

        if hasattr(self, 'local_progress_bar'):
            self.local_progress_bar.configure(
                progress_color=cfg["accent"],
                fg_color=cfg["input_bg"]
            )
        if hasattr(self, 'local_counter_lbl'):
            self.local_counter_lbl.configure(text_color=cfg["text_primary"])
        if hasattr(self, 'local_folder_icon_frame'):
            self.local_folder_icon_frame.configure(fg_color=cfg["input_bg"], border_color=cfg["border"])
        for item in getattr(self, 'local_plexamp_track_items', []):
            item["row_frame"].configure(fg_color=cfg["input_bg"], border_color=cfg["border"])
            item["checkbox"].configure(
                fg_color=cfg["option_btn"],
                hover_color=cfg["option_hover"],
                checkmark_color=cfg["input_bg"]
            )

        if hasattr(self, 'verifier_progress_bar'):
            self.verifier_progress_bar.configure(
                progress_color=cfg["accent"],
                fg_color=cfg["input_bg"]
            )
        if hasattr(self, 'verifier_counter_lbl'):
            self.verifier_counter_lbl.configure(text_color=cfg["text_primary"])
        for item in getattr(self, 'verifier_track_items', []):
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
            icon_path = self.get_file_path("shallot.ico")
            if not os.path.exists(icon_path):
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

        # Clear scrollable list
        for child in self.verifier_scroll.winfo_children():
            child.destroy()

        self.verifier_progress_bar.set(0)
        self.btn_verifier_start_scan.configure(state="disabled", text="Scanning Library... ⏳")
        self.btn_verifier_fix_selected.configure(state="disabled")
        self.btn_verifier_export.configure(state="disabled")
        self.verifier_status_lbl.configure(text="Discovering audio files...", text_color="#78909C")
        self.verifier_workers_lbl.configure(text="⚡ Active: Initializing worker threads...", text_color="#38BDF8")
        self.power_light.configure(text="● SCANNING", text_color=getattr(self, 'theme_cfg', {}).get("accent", "#00E5FF"))

        self.verifier_lbl_total.configure(text="0 Scanned")
        self.verifier_lbl_mismatch.configure(text="0 ⚠️ Mismatches")
        self.verifier_lbl_verified.configure(text="0 ✅ Verified")
        self.verifier_lbl_unrec.configure(text="0 ❓ Unknown")

        def log_cb(msg: str, is_error: bool = False):
            self.log(f"[Fact-Checker] {msg}", is_error=is_error)

        def active_worker_cb(workers: dict):
            self.verifier_active_workers = workers
            self.after(0, update_workers_display)

        def update_workers_display():
            if not self.verifier_is_scanning:
                self.verifier_workers_lbl.configure(text="")
                return
            if not self.verifier_active_workers:
                self.verifier_workers_lbl.configure(text="⚡ Active: Dispatching next tracks...", text_color="#78909C")
                return

            worker_strs = []
            now = time.time()
            for idx, info in enumerate(self.verifier_active_workers.values(), start=1):
                fn = info.get("filename", "")
                if len(fn) > 28:
                    fn = fn[:25] + "..."
                elapsed = int(now - info.get("start_time", now))
                warn = " ⚠️" if elapsed >= 15 else ""
                worker_strs.append(f"W{idx}: {fn} ({elapsed}s{warn})")

            disp_text = "⚡ Active: " + "  |  ".join(worker_strs)
            self.verifier_workers_lbl.configure(text=disp_text, text_color="#38BDF8")

        def heartbeat_loop():
            if self.verifier_is_scanning:
                update_workers_display()
                self.after(500, heartbeat_loop)

        def progress_cb(curr: int, total: int, filename: str):
            pct = curr / max(1, total)
            self.after(0, lambda: self.verifier_progress_bar.set(pct))
            self.after(0, lambda: self.verifier_counter_lbl.configure(text=f"{curr} / {total}"))
            self.after(0, lambda: self.verifier_status_lbl.configure(text=f"Acoustic Check ({curr}/{total}): {filename[:40]}"))
            self.after(0, lambda: self.update_taskbar_progress(int(pct * 100)))

        def item_cb(res: dict):
            self.verifier_scan_results.append(res)
            # Update stats
            tot = len(self.verifier_scan_results)
            mis = sum(1 for r in self.verifier_scan_results if r.get("status") == "MISMATCH")
            ver = sum(1 for r in self.verifier_scan_results if r.get("status") == "VERIFIED")
            unr = sum(1 for r in self.verifier_scan_results if r.get("status") in ("UNRECOGNIZED", "TIMEOUT", "ERROR"))
            self.after(0, lambda: self.verifier_lbl_total.configure(text=f"{tot} Scanned"))
            self.after(0, lambda: self.verifier_lbl_mismatch.configure(text=f"{mis} ⚠️ Mismatches"))
            self.after(0, lambda: self.verifier_lbl_verified.configure(text=f"{ver} ✅ Verified"))
            self.after(0, lambda: self.verifier_lbl_unrec.configure(text=f"{unr} ❓ Unknown"))

        def run_scan():
            self.log(f"Starting acoustic library fact-check on: {folder}")
            use_cache = bool(self.verifier_cache_switch.get()) if hasattr(self, 'verifier_cache_switch') else True
            try:
                AudioFactChecker.scan_directory(
                    root_dir=folder,
                    progress_cb=progress_cb,
                    item_cb=item_cb,
                    active_worker_cb=active_worker_cb,
                    log_cb=log_cb,
                    cancel_event=self.verifier_cancel_event,
                    per_file_timeout=20.0,
                    use_cache=use_cache
                )
            except Exception as e:
                self.log(f"Scan error: {e}", is_error=True)
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
        self.btn_verifier_export.configure(state="normal")
        self.update_taskbar_progress(0)
        self.power_light.configure(
            text=getattr(self, 'theme_cfg', {}).get("status_text", "● READY"),
            text_color=getattr(self, 'theme_cfg', {}).get("status_color", "#38BDF8")
        )

        tot = len(self.verifier_scan_results)
        mis = sum(1 for r in self.verifier_scan_results if r.get("status") == "MISMATCH")
        ver = sum(1 for r in self.verifier_scan_results if r.get("status") == "VERIFIED")
        unr = sum(1 for r in self.verifier_scan_results if r.get("status") in ("UNRECOGNIZED", "TIMEOUT", "ERROR"))

        # If mismatches are detected, automatically default the view to Mismatches so the user immediately sees tracks to fix
        if mis > 0:
            self.verifier_filter_mode = "mismatch"
        self.update_verifier_filter_buttons()

        self.verifier_status_lbl.configure(
            text=f"✓ Scan Complete: {tot} files scanned | {mis} mismatches found | {ver} verified",
            text_color="#FB7185" if mis > 0 else "#4ADE80"
        )
        self.log(f"Scan finished: {tot} total files, {mis} tag mismatches detected, {ver} verified, {unr} unrecognized/timeouts.")

        self.render_verifier_results()

    def set_verifier_filter(self, mode: str):
        self.verifier_filter_mode = mode
        self.update_verifier_filter_buttons()
        self.render_verifier_results()

    def update_verifier_filter_buttons(self):
        cfg = getattr(self, 'theme_cfg', {})
        active_bg = cfg.get("option_btn", "#028090")
        inactive_bg = cfg.get("input_bg", "#070F15")
        border = cfg.get("btn_border", "#1F3A4E")

        mode = self.verifier_filter_mode
        if hasattr(self, 'btn_vfilt_all'):
            self.btn_vfilt_all.configure(fg_color=active_bg if mode == "all" else inactive_bg, border_color=cfg.get("accent", "#00E5FF") if mode == "all" else border)
            self.btn_vfilt_mismatch.configure(fg_color="#881337" if mode == "mismatch" else inactive_bg, border_color="#FB7185" if mode == "mismatch" else border)
            self.btn_vfilt_verified.configure(fg_color="#064E3B" if mode == "verified" else inactive_bg, border_color="#34D399" if mode == "verified" else border)
            self.btn_vfilt_unrec.configure(fg_color="#334155" if mode == "unrec" else inactive_bg, border_color="#94A3B8" if mode == "unrec" else border)

    def clear_verifier_cache(self):
        """ Clears persistent verification cache on disk """
        AudioFactChecker.clear_cache()
        self.verifier_scan_results = []
        self.verifier_lbl_total.configure(text="0 Scanned")
        self.verifier_lbl_mismatch.configure(text="0 ⚠️ Mismatches")
        self.verifier_lbl_verified.configure(text="0 ✅ Verified")
        self.verifier_lbl_unrec.configure(text="0 ❓ Unknown")
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
            "MISMATCH": 0,
            "TIMEOUT": 1,
            "ERROR": 2,
            "UNRECOGNIZED": 3,
            "VERIFIED": 4
        }

        filtered = []
        for idx, res in enumerate(self.verifier_scan_results):
            st = res.get("status", "")
            if self.verifier_filter_mode == "mismatch" and st != "MISMATCH":
                continue
            if self.verifier_filter_mode == "verified" and st != "VERIFIED":
                continue
            if self.verifier_filter_mode == "unrec" and st not in ("UNRECOGNIZED", "TIMEOUT", "ERROR"):
                continue
            filtered.append((idx, res))

        # Always sort with Mismatches first, then Unknown/Errors, then Verified
        filtered.sort(key=lambda x: (status_priority.get(x[1].get("status", ""), 99), x[1].get("filename", "").lower()))

        if not filtered:
            msg = "No files match the selected filter." if self.verifier_scan_results else "No scan performed yet. Select your music folder and click 'Scan & Fact-Check'."
            empty_lbl = ctk.CTkLabel(self.verifier_scroll, text=msg, font=("Segoe UI", 11), text_color="#78909C")
            empty_lbl.pack(pady=30)
            return

        for original_idx, res in filtered:
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
            var = ctk.IntVar(value=1 if st == "MISMATCH" else 0)
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
            if st == "MISMATCH":
                badge_text = "⚠️ WRONG TAG"
                badge_color = "#FB7185"
            elif st == "VERIFIED":
                badge_text = "✅ VERIFIED"
                badge_color = "#4ADE80"
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
                width=85,
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
                text_color="#FB7185" if st == "MISMATCH" else "#94A3B8",
                anchor="w"
            )
            detail_lbl.pack(fill="x")

            # Action Button per row
            btn_fix = None
            btn_keep = None
            if st == "MISMATCH":
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

            self.verifier_track_items.append({
                "original_index": original_idx,
                "result": res,
                "var": var,
                "row_frame": row_frame,
                "checkbox": cb,
                "badge_lbl": badge_lbl,
                "detail_lbl": detail_lbl,
                "btn_fix": btn_fix,
                "btn_keep": btn_keep
            })

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
        mis = sum(1 for r in self.verifier_scan_results if r.get("status") == "MISMATCH")
        ver = sum(1 for r in self.verifier_scan_results if r.get("status") == "VERIFIED")
        unr = sum(1 for r in self.verifier_scan_results if r.get("status") in ("UNRECOGNIZED", "TIMEOUT", "ERROR"))
        self.verifier_lbl_total.configure(text=f"{tot} Scanned")
        self.verifier_lbl_mismatch.configure(text=f"{mis} ⚠️ Mismatches")
        self.verifier_lbl_verified.configure(text=f"{ver} ✅ Verified")
        self.verifier_lbl_unrec.configure(text=f"{unr} ❓ Unknown")
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
        mis = sum(1 for r in self.verifier_scan_results if r.get("status") == "MISMATCH")
        ver = sum(1 for r in self.verifier_scan_results if r.get("status") == "VERIFIED")
        unr = sum(1 for r in self.verifier_scan_results if r.get("status") in ("UNRECOGNIZED", "TIMEOUT", "ERROR"))
        self.verifier_lbl_total.configure(text=f"{tot} Scanned")
        self.verifier_lbl_mismatch.configure(text=f"{mis} ⚠️ Mismatches")
        self.verifier_lbl_verified.configure(text=f"{ver} ✅ Verified")
        self.verifier_lbl_unrec.configure(text=f"{unr} ❓ Unknown")
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

            self.after(0, lambda: self.btn_verifier_fix_selected.configure(state="normal", text="🛠  Fix & Re-tag Selected Mismatches"))
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

    def persist_current_state(self):
        """Saves dynamic UI inputs so previous selections are remembered on next launch."""
        try:
            if hasattr(self, 'folder_input'):
                val = self.folder_input.get().strip()
                if val:
                    self.save_setting("destination_folder", val)
            if hasattr(self, 'spotify_folder_input'):
                val = self.spotify_folder_input.get().strip()
                if val:
                    self.save_setting("plex_music_folder", val)
        except Exception:
            pass

    def on_close_window(self):
        """Intercepts window close event (X button), saves current selection, and minimizes to tray."""
        self.persist_current_state()
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
        """Cleanly halts all background tasks, saves previous selections, and terminates."""
        self.persist_current_state()
        if hasattr(self, 'spotify_pipeline') and self.spotify_pipeline:
            self.spotify_pipeline.cancel()
        if self.active_process:
            self.emergency_process_cleanup()
        self.destroy()
        os._exit(0)


if __name__ == "__main__":
    app = DownloaderApp()
    app.mainloop()