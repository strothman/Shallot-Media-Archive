"""
Settings & Tools Tab Mixin for Shallot Media Archive.
Manages application configuration, theme selector, cookie source/upload,
yt-dlp engine updating, error logs, and Spotify credentials.
"""

import os
import shutil
import subprocess
import sys
import threading
import customtkinter as ctk
from core import CToolTip


class SettingsTabMixin:
    """Provides Settings & Tools UI construction and configuration actions."""

    def build_settings_page(self, parent):
        """Constructs the Settings & Tools tab page."""
        self.settings_page = ctk.CTkFrame(parent, fg_color="transparent")

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
        CToolTip(self.cookie_source_menu, "Direct cookie extraction from your browser or cookies.txt file to unlock age-restricted, premium, and members-only streams without bot checks.")
        CToolTip(lbl_csrc, "Direct cookie extraction from your browser or cookies.txt file to unlock age-restricted, premium, and members-only streams without bot checks.")

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
        CToolTip(self.update_cookies_btn, "Upload a custom Netscape-formatted cookies.txt file to permanently authenticate yt-dlp downloads.")

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
        CToolTip(self.update_ytdlp_btn, "Checks for and downloads the latest yt-dlp binary release.")

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
        CToolTip(self.open_error_log_btn, "Opens the persistent downloader error log file in your system text editor.")

        return self.settings_page

    def upload_cookies(self):
        """Opens a file dialogue to select and save a new cookies.txt file."""
        file_path = ctk.filedialog.askopenfilename(
            title="Select your new cookies.txt file",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
        )
        if file_path:
            try:
                exe_dir = (
                    os.path.dirname(sys.executable)
                    if getattr(sys, "frozen", False)
                    else os.path.dirname(os.path.abspath(__file__))
                )
                target_path = os.path.join(exe_dir, "cookies.txt")
                shutil.copy(file_path, target_path)

                self.log("SUCCESS: New cookies.txt saved permanently!")
                self.log(f"Location: {target_path}")
            except Exception as e:
                self.log(f"ERROR: Could not save cookies. {e}", is_error=True)

    def update_ytdlp(self):
        """Runs updates for yt-dlp.exe directly."""
        if hasattr(self, "update_ytdlp_btn") and self.update_ytdlp_btn:
            self.update_ytdlp_btn.configure(state="disabled", text="Updating...")

        def run_update():
            self.log("Starting engine update check...")
            exe_dir = (
                os.path.dirname(sys.executable)
                if getattr(sys, "frozen", False)
                else os.path.dirname(os.path.abspath(__file__))
            )
            target_path = os.path.join(exe_dir, "yt-dlp.exe")

            if not os.path.exists(target_path):
                try:
                    bundled_path = self.get_file_path("yt-dlp.exe")
                    shutil.copy(bundled_path, target_path)
                except Exception as e:
                    self.log(f"ERROR: Could not prepare engine for update: {e}", is_error=True)
                    self.after(
                        0,
                        lambda: self.update_ytdlp_btn.configure(text="Update Failed! ❌")
                        if self.update_ytdlp_btn
                        else None,
                    )
                    self.after(4000, self.reset_update_button)
                    return

            self.log(f"Running update on: {target_path}")
            cmd = [target_path, "-U"]
            try:
                res = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                if res.returncode == 0:
                    self.log("SUCCESS: Downloader Engine updated successfully!")
                    self.log(res.stdout.strip())
                    self.after(
                        0,
                        lambda: self.update_ytdlp_btn.configure(text="Update Complete! 🎉")
                        if self.update_ytdlp_btn
                        else None,
                    )
                else:
                    self.log(f"ERROR: Update failed: {res.stderr.strip() or res.stdout.strip()}", is_error=True)
                    self.after(
                        0,
                        lambda: self.update_ytdlp_btn.configure(text="Update Failed! ❌")
                        if self.update_ytdlp_btn
                        else None,
                    )
            except Exception as e:
                self.log(f"ERROR running update command: {e}", is_error=True)
                self.after(
                    0,
                    lambda: self.update_ytdlp_btn.configure(text="Update Failed! ❌")
                    if self.update_ytdlp_btn
                    else None,
                )

            self.after(4000, self.reset_update_button)

        threading.Thread(target=run_update, daemon=True).start()

    def reset_update_button(self):
        if hasattr(self, "update_ytdlp_btn") and self.update_ytdlp_btn:
            self.update_ytdlp_btn.configure(state="normal", text="Update Engine")

    def open_error_log(self):
        """Opens the persistent error log file in the default system text editor."""
        try:
            exe_dir = (
                os.path.dirname(sys.executable)
                if getattr(sys, "frozen", False)
                else os.path.dirname(os.path.abspath(__file__))
            )
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
