"""
Main Download Tab Mixin for Shallot Media Archive.
Manages single URL and playlist downloads, channel avatar scraping,
progress bars, TV season & range slicing, and yt-dlp execution.
"""

import os
import re
import ssl
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
import customtkinter as ctk
from PIL import Image
from core import CToolTip


class DownloadTabMixin:
    """Provides Main Downloader page UI construction and download execution controls."""

    def build_download_page(self, parent):
        """Constructs the Main Media Downloader tab page."""
        self.download_page = ctk.CTkFrame(parent, fg_color="transparent")

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
        self.url_input.bind("<Return>", lambda e: self._on_url_input_return())
        self.theme_entries.append(self.url_input)
        CToolTip(self.url_input, "Paste any YouTube, SoundCloud, or supported web video URL. Also automatically detects Spotify playlists or local folders and routes them!")

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
        CToolTip(self.paste_btn, "Paste URL from clipboard (Intelligently detects and routes Spotify playlists or local folders)")

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
        CToolTip(self.folder_input, "Default download destination directory for media files.")

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
        CToolTip(self.browse_btn, "Browse computer or external drive for download destination.")

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
        CToolTip(self.season_input, "TV season prefix (e.g. S01) applied to episode numbering for automated Plex/Jellyfin naming.")

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
        CToolTip(self.range_input, "Playlist item range filter (e.g. 1:50) to download a specific slice instead of an entire series.")

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
        CToolTip(self.speed_input, "Audio/video download bandwidth throttle in MB/s to prevent saturation.")

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

        return self.download_page

    def _on_url_input_return(self, event=None):
        text = self.url_input.get().strip()
        if not text:
            return
        if self.dispatch_smart_input(text, source_tab="download"):
            return
        threading.Thread(target=self.fetch_and_display_avatar, args=(text,), daemon=True).start()

    def paste_url(self):
        """ Pastes clipboard contents into the URL input and loads avatar """
        try:
            clipboard_text = self.clipboard_get().strip()
            if clipboard_text:
                if self.dispatch_smart_input(clipboard_text, source_tab="download"):
                    return
                self.url_input.delete(0, "end")
                self.url_input.insert(0, clipboard_text)
                threading.Thread(target=self.fetch_and_display_avatar, args=(clipboard_text,), daemon=True).start()
        except Exception as e:
            self.log(f"Clipboard paste error: {e}", is_error=True)

    def browse_folder(self):
        """Opens folder picker dialog to select destination folder."""
        current_val = self.folder_input.get().strip() or r"C:\SMA-downloads"
        init_dir = current_val if os.path.exists(current_val) else r"C:\\"
        selected_dir = ctk.filedialog.askdirectory(initialdir=init_dir, title="Select Destination Folder")
        if selected_dir:
            selected_dir = os.path.normpath(selected_dir)
            self.folder_input.delete(0, "end")
            self.folder_input.insert(0, selected_dir)
            self.save_setting("destination_folder", selected_dir)

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

    def fetch_and_display_avatar(self, url):
        """Scrapes the uploader's channel avatar in the background and saves it to a temp file."""
        try:
            yt_dlp_path = self.get_active_yt_dlp_path()
            cookie_args = self.get_cookie_args()

            # 1. Fetch channel URL using yt-dlp
            if "youtube.com/channel/" in url or "youtube.com/@" in url or "youtube.com/c/" in url:
                channel_url = url
            else:
                cmd = [yt_dlp_path] + cookie_args + ["--no-playlist", "--print", "uploader_url", url]
                res = subprocess.run(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                channel_url = res.stdout.strip()

            if not channel_url or "http" not in channel_url:
                channel_url = url

            # 2. Scrape the avatar URL from channel HTML
            req = urllib.request.Request(channel_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            avatar_url = None
            with urllib.request.urlopen(req, context=ctx, timeout=8) as response:
                html = response.read().decode("utf-8", errors="ignore")
                match = re.search(r'<meta property="og:image" content="([^"]+)"', html)
                if match:
                    avatar_url = match.group(1)
                else:
                    match_fallback = re.search(r'"avatar":{"thumbnails":\[{"url":"([^"]+)"', html)
                    if match_fallback:
                        avatar_url = match_fallback.group(1).replace(r"\u0026", "&")

            if avatar_url:
                exe_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
                temp_avatar_path = os.path.join(exe_dir, "temp_avatar.png")

                img_data = urllib.request.urlopen(avatar_url, context=ctx, timeout=8).read()
                with open(temp_avatar_path, "wb") as f:
                    f.write(img_data)

                self.after(0, self.load_avatar_file)
        except Exception as e:
            print("Avatar load failed:", e)

    def load_avatar_file(self):
        """Loads the temporary avatar file in the main thread and displays it."""
        try:
            exe_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
            temp_avatar_path = os.path.join(exe_dir, "temp_avatar.png")
            if os.path.exists(temp_avatar_path):
                img = Image.open(temp_avatar_path)
                self.avatar_image = ctk.CTkImage(light_image=img, dark_image=img, size=(54, 54))
                self.avatar_label.configure(image=self.avatar_image, text="")
        except Exception as e:
            print("Display avatar error:", e)

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
        """Aborts active download immediately and terminates child processes."""
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

        result = subprocess.run(check_cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

        valid_ids = [line for line in result.stdout.strip().split("\n") if line]

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
                    result = subprocess.run(check_cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                    valid_ids = [line for line in result.stdout.strip().split("\n") if line]
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
            a_fmt = self.audio_format_menu.get().lower() if hasattr(self, "audio_format_menu") else "mp3"
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

            aq_choice = self.audio_quality.get().lower() if hasattr(self, "audio_quality") else "best"
            if "320" in aq_choice or "best" in aq_choice:
                aq = "0"
            elif "192" in aq_choice or "standard" in aq_choice:
                aq = "5"
            else:
                aq = "9"

            command.extend(["-f", "ba", "--extract-audio", "--audio-format", ext, "--audio-quality", aq])
        else:
            # Video Resolution selection
            q = self.video_quality.get().lower() if hasattr(self, "video_quality") else "1080p"
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
            if season is not None:
                command.extend(["-o", "%(artist,album_artist,creator,uploader)s/%(album,playlist_title,uploader)s/%(autonumber)02d - %(title)s.%(ext)s", url])
            else:
                command.extend(["-o", "%(artist,album_artist,creator,uploader)s/%(album,playlist_title,uploader)s/%(playlist_index&{:02d} - |)s%(title)s.%(ext)s", url])
        else:
            use_date = bool(self.date_switch.get())
            if season is not None:
                date_prefix = "%(upload_date>%Y-%m-%d)s - " if use_date else ""
                command.extend(["-o", f"%(playlist_title,uploader)s/{date_prefix}%(autonumber)03d - %(title)s.%(ext)s", url])
            else:
                date_prefix = "[%(upload_date>%Y-%m-%d)s] " if use_date else ""
                command.extend(["-o", f"%(playlist_title,uploader)s/{date_prefix}%(title)s.%(ext)s", url])

        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
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
