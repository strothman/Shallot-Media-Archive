"""
Shallot Media Archive (SMArchive)
Universal Media Ingestion, Verification, and Archival Suite.
Modular GUI Architecture powered by CustomTkinter and Tab Mixins.
"""

import os
import sys
import re
import json
import time
import shutil
import atexit
import threading
import subprocess
import pystray
from PIL import Image
import customtkinter as ctk

from core import AudioPreviewPlayer, CToolTip
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

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class DownloaderApp(
    ctk.CTk,
    DownloadTabMixin,
    SearchTabMixin,
    SpotifyTabMixin,
    YtPlexampTabMixin,
    LocalPlexampTabMixin,
    VerifierTabMixin,
    CDMixtapeTabMixin,
    SettingsTabMixin,
    LogsTabMixin,
):
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

        # --- CD Mixtape State ---
        self.cd_library_index = None
        self.cd_mixtape_plan = None
        self.cd_track_items = []
        self.cd_is_scanning_library = False
        self.cd_is_generating = False
        self.cd_is_exporting = False
        self.cd_exporter = None

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

        width, height = 1120, 720
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = max(0, (screen_w // 2) - (width // 2))
        y = max(0, (screen_h // 2) - (height // 2))
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.configure(fg_color="#070F15")
        self.minsize(980, 650)

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
        self.sidebar_frame = ctk.CTkFrame(self, corner_radius=0, width=225)
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

        self.btn_cd_mixtape = ctk.CTkButton(
            self.sidebar_frame,
            text="💿  CD Mixtape Builder",
            font=("Segoe UI", 12, "bold"),
            height=38,
            corner_radius=8,
            anchor="w",
            command=lambda: self.select_tab("cd_mixtape")
        )
        self.btn_cd_mixtape.pack(fill="x", padx=15, pady=4)

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
        # --- Modular Tab Pages Construction ---
        # =========================================================================
        self.build_download_page(self.main_container)
        self.build_search_page(self.main_container)
        self.build_spotify_page(self.main_container)
        self.build_yt_plexamp_page(self.main_container)
        self.build_local_plexamp_page(self.main_container)
        self.build_verifier_page(self.main_container)
        self.build_cd_mixtape_page(self.main_container)
        self.build_settings_page(self.main_container)
        self.build_logs_page(self.main_container)

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

        saved_theme = self.saved_settings.get("theme", "Midnight")
        if saved_theme not in ["Midnight", "Carbon", "Nordic"]:
            saved_theme = "Midnight"
        self.apply_theme(saved_theme)
        self.select_tab("download")

        self.after(100, lambda: self.update_taskbar_progress(0))

        # Bring window to front
        self.lift()
        self.focus_force()

    def emergency_process_cleanup(self):
        """ Guarantees all child processes (yt-dlp, ffmpeg, ffplay) are terminated when exiting """
        try:
            AudioPreviewPlayer.stop()
        except Exception:
            pass
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

    def dispatch_smart_input(self, raw_input: str, source_tab: str = None) -> bool:
        """
        Intelligently inspects an input string (URL, playlist, or folder path).
        If the content belongs to a different workflow or engine than the current tab,
        it smoothly transitions to the appropriate tab, pre-fills the input, triggers
        the corresponding action, and logs a clear status notification.

        Returns:
            bool: True if redirected to another tab, False if caller should proceed locally.
        """
        if not raw_input or not isinstance(raw_input, str):
            return False

        text = raw_input.strip().strip('"\'')
        if not text:
            return False

        # 1. Spotify Link Detection
        is_spotify = bool(
            "spotify.com/" in text.lower() or 
            text.lower().startswith("spotify:")
        )
        if is_spotify and source_tab != "spotify":
            self.select_tab("spotify")
            self.spotify_url_input.delete(0, "end")
            self.spotify_url_input.insert(0, text)
            self.log("🔀 [Smart Dispatch] Detected Spotify URL. Redirected to Spotify-to-Plexamp tab.")
            self.send_notification("Smart Input Routed", "Switched to Spotify-to-Plexamp tab & fetched playlist.")
            self.fetch_spotify_playlist()
            return True

        # 2. YouTube Link Detection
        is_yt = bool(
            "youtube.com" in text.lower() or 
            "youtu.be" in text.lower()
        )
        if is_yt:
            if source_tab == "spotify":
                self.select_tab("yt_plexamp")
                self.yt_plexamp_url_input.delete(0, "end")
                self.yt_plexamp_url_input.insert(0, text)
                self.log("🔀 [Smart Dispatch] Detected YouTube link in Spotify tab. Switched to YouTube-to-Plexamp tab.")
                self.send_notification("Smart Input Routed", "Switched to YouTube-to-Plexamp tab & fetched playlist.")
                self.fetch_yt_plexamp_playlist()
                return True
            elif source_tab in ("verifier", "cd_mixtape", "local_plexamp"):
                is_playlist = "list=" in text or "playlist" in text.lower()
                target_tab = "yt_plexamp" if is_playlist else "download"
                self.select_tab(target_tab)
                if target_tab == "yt_plexamp":
                    self.yt_plexamp_url_input.delete(0, "end")
                    self.yt_plexamp_url_input.insert(0, text)
                    self.fetch_yt_plexamp_playlist()
                else:
                    self.url_input.delete(0, "end")
                    self.url_input.insert(0, text)
                    threading.Thread(target=self.fetch_and_display_avatar, args=(text,), daemon=True).start()
                self.log(f"🔀 [Smart Dispatch] Routed YouTube link to '{target_tab}' tab.")
                return True

        # 3. Local Directory Detection
        is_dir = False
        try:
            if os.path.isdir(text):
                is_dir = True
            elif re.match(r'^[a-zA-Z]:[\\/]', text) or text.startswith('\\\\'):
                is_dir = os.path.exists(text)
        except Exception:
            is_dir = False

        if is_dir:
            if source_tab in ("download", "search"):
                self.select_tab("verifier")
                self.verifier_folder_input.delete(0, "end")
                self.verifier_folder_input.insert(0, text)
                self.log(f"🔀 [Smart Dispatch] Detected local audio directory '{text}'. Routed to Fact-Check Audio tab.")
                self.send_notification("Smart Input Routed", "Switched to Fact-Check Audio tab.")
                return True
            elif source_tab in ("spotify", "yt_plexamp"):
                if hasattr(self, 'spotify_folder_input'):
                    self.spotify_folder_input.delete(0, "end")
                    self.spotify_folder_input.insert(0, text)
                if hasattr(self, 'yt_plexamp_folder_input'):
                    self.yt_plexamp_folder_input.delete(0, "end")
                    self.yt_plexamp_folder_input.insert(0, text)
                self.save_setting("plex_music_folder", text)
                self.log(f"🔀 [Smart Dispatch] Updated Plexamp music library folder to '{text}'.")
                self.send_notification("Library Updated", f"Destination folder set to: {text}")
                return True

        return False


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


    def select_tab(self, tab_name):
        try:
            AudioPreviewPlayer.stop()
        except Exception:
            pass
        self.active_tab = tab_name
        cfg = getattr(self, 'theme_cfg', {})
        
        tabs = {
            "download": (self.btn_download, self.download_page),
            "search": (self.btn_search, self.search_page),
            "spotify": (self.btn_spotify, self.spotify_page),
            "yt_plexamp": (self.btn_yt_plexamp, self.yt_plexamp_page),
            "local_plexamp": (self.btn_local_plexamp, self.local_plexamp_page),
            "verifier": (self.btn_verifier, self.verifier_page),
            "cd_mixtape": (self.btn_cd_mixtape, self.cd_mixtape_page),
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


    def apply_theme(self, theme_name):
        themes = {
            "Midnight": {
                "app_bg": "#080D14",
                "card_bg": "#0F172A",
                "border": "#1E293B",
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
                "input_bg": "#090E17",
                "input_border": "#1E293B",
                "option_btn": "#1E293B",
                "option_hover": "#334155",
                "option_bg": "#090E17",
                "option_drop": "#0F172A",
                "metric_card_bg": "#131C2E"
            },
            "Carbon": {
                "app_bg": "#0C0C0E",
                "card_bg": "#16161A",
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
                "input_bg": "#0E0E11",
                "input_border": "#27272A",
                "option_btn": "#27272A",
                "option_hover": "#3F3F46",
                "option_bg": "#0E0E11",
                "option_drop": "#18181B",
                "metric_card_bg": "#1D1D24"
            },
            "Nordic": {
                "app_bg": "#0B0F1A",
                "card_bg": "#151D2E",
                "border": "#25334A",
                "border_width": 1,
                "accent": "#818CF8",
                "text_primary": "#F8FAFC",
                "text_secondary": "#94A3B8",
                "btn_bg": "#282D54",
                "btn_border": "#818CF8",
                "btn_text": "#818CF8",
                "btn_hover": "#373C70",
                "status_text": "● READY",
                "status_color": "#818CF8",
                "input_bg": "#0E1524",
                "input_border": "#25334A",
                "option_btn": "#25334A",
                "option_hover": "#3A4B6B",
                "option_bg": "#0E1524",
                "option_drop": "#182236",
                "metric_card_bg": "#1B253B"
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
            self.local_action_card,
            self.verifier_source_card, self.verifier_stats_card, self.verifier_results_card,
            self.verifier_action_card,
            self.cd_source_card, self.cd_settings_card, self.cd_stats_card,
            self.cd_tracks_card, self.cd_action_card
        ]
        for card in cards:
            card.configure(
                fg_color=cfg["card_bg"], 
                border_color=cfg["border"], 
                border_width=cfg["border_width"]
            )

        for m_card in getattr(self, 'theme_metric_cards', []):
            m_card.configure(
                fg_color=cfg.get("metric_card_bg", cfg["card_bg"]),
                border_color=cfg["border"],
                border_width=1
            )
        self.update_verifier_filter_buttons()
            
        for title_lbl in self.theme_titles:
            try:
                if title_lbl.winfo_exists():
                    title_lbl.configure(text_color=cfg["text_primary"])
            except Exception:
                pass
            
        for sec_lbl in self.theme_labels_secondary:
            try:
                if sec_lbl.winfo_exists():
                    sec_lbl.configure(text_color=cfg["text_secondary"])
            except Exception:
                pass
            
        for entry in self.theme_entries:
            try:
                if entry.winfo_exists():
                    entry.configure(
                        fg_color=cfg["input_bg"],
                        border_color=cfg["input_border"],
                        text_color="#F5F5F7",
                        placeholder_text_color=cfg["text_secondary"]
                    )
            except Exception:
                pass
            
        for menu in self.theme_option_menus:
            try:
                if menu.winfo_exists():
                    menu.configure(
                        fg_color=cfg["input_bg"],
                        button_color=cfg["option_btn"],
                        button_hover_color=cfg["option_hover"],
                        dropdown_fg_color=cfg["option_drop"],
                        text_color="#F5F5F7",
                        dropdown_text_color="#F5F5F7",
                        dropdown_hover_color=cfg["input_border"]
                    )
            except Exception:
                pass
            
        for sw in self.theme_switches:
            try:
                if sw.winfo_exists():
                    sw.configure(
                        progress_color=cfg["accent"],
                        text_color="#F5F5F7"
                    )
            except Exception:
                pass
            
        for chk in [self.season_checkbox, self.range_checkbox]:
            try:
                if chk.winfo_exists():
                    chk.configure(
                        fg_color=cfg["option_btn"],
                        hover_color=cfg["option_hover"],
                        checkmark_color=cfg["input_bg"],
                        text_color=cfg["text_secondary"]
                    )
            except Exception:
                pass
        
        for btn in self.theme_buttons_secondary:
            try:
                if btn.winfo_exists():
                    btn.configure(
                        fg_color=cfg["input_bg"],
                        border_color=cfg["btn_border"],
                        border_width=1,
                        text_color=cfg["btn_text"],
                        hover_color=cfg["btn_hover"]
                    )
            except Exception:
                pass
            
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
            if "btn_play" in item and item["btn_play"] and hasattr(item["btn_play"], "winfo_exists") and item["btn_play"].winfo_exists():
                item["btn_play"].configure(
                    fg_color=cfg["input_bg"],
                    hover_color=cfg.get("btn_hover", "#334155")
                )
            if "btn_diff" in item and item["btn_diff"] and hasattr(item["btn_diff"], "winfo_exists") and item["btn_diff"].winfo_exists():
                item["btn_diff"].configure(
                    fg_color=cfg["input_bg"],
                    hover_color=cfg.get("btn_hover", "#334155")
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
            if hasattr(self, 'cd_output_folder_input'):
                val = self.cd_output_folder_input.get().strip()
                if val:
                    self.save_setting("cd_output_folder", val)
            if hasattr(self, 'cd_normalization_menu'):
                val = self.cd_normalization_menu.get().strip()
                if val:
                    self.save_setting("cd_audio_normalization", val)
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

    def destroy(self):
        try:
            AudioPreviewPlayer.stop()
        except Exception:
            pass
        if hasattr(self, 'tray_icon') and self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        super().destroy()

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
