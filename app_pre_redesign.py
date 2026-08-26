import os
import re
import shutil
import subprocess
import sys
import threading

import customtkinter as ctk

# --- Setup System PATH for Bundled JS Runtimes (e.g., deno.exe) ---
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
        self.title("Strothman Media Archive")
        
        # --- Custom Window Icon ---
        icon_path = self.get_file_path("icon.ico")
        if os.path.exists(icon_path):
            self.iconbitmap(icon_path)

        width, height = 660, 580
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.configure(fg_color="#070F15")

        # --- Theme Widget Registry ---
        self.theme_titles = []
        self.theme_labels_secondary = []
        self.theme_entries = []
        self.theme_switches = []
        self.theme_option_menus = []
        self.theme_buttons_secondary = []

        # --- Header Frame (Title & Subtitle) ---
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.pack(fill="x", padx=30, pady=(12, 4))
        
        self.title_label = ctk.CTkLabel(
            self.header_frame, 
            text="Strothman Media Archive", 
            font=("Segoe UI", 22, "bold"), 
            text_color="#00E5FF",
            anchor="w"
        )
        self.title_label.pack(side="left", anchor="w")
        
        # Aquatic Modern Status Light
        self.power_light = ctk.CTkLabel(
            self.header_frame,
            text="● ACTIVE",
            font=("Segoe UI", 11, "bold"),
            text_color="#00F2FE"
        )
        self.power_light.pack(side="right", anchor="center", padx=5)
        
        self.subtitle_label = ctk.CTkLabel(
            self.header_frame, 
            text="Archive media, build your library.", 
            font=("Segoe UI", 11), 
            text_color="#78909C",
            anchor="w"
        )
        self.subtitle_label.pack(side="left", anchor="w", padx=(15, 0))

        # --- Main vertical layout container ---
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True, padx=30, pady=4)
        
        # --- Panel 1: Media Destination & Source (Preamp Section) ---
        self.input_card = ctk.CTkFrame(self.main_container, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.input_card.pack(fill="x", pady=4)
        
        card1_lbl = ctk.CTkLabel(self.input_card, text="INPUT / SOURCE", font=("Segoe UI", 12, "bold"), text_color="#00E5FF")
        card1_lbl.pack(anchor="w", padx=15, pady=(8, 3))
        self.theme_titles.append(card1_lbl)
        
        # --- YouTube Search Frame ---
        self.search_frame = ctk.CTkFrame(self.input_card, fg_color="transparent")
        self.search_frame.pack(fill="x", padx=15, pady=(2, 4))
        
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
        
        # --- Search Results Container (Hidden initially to prevent empty scroll/space) ---
        self.results_frame = ctk.CTkFrame(self.input_card, fg_color="transparent")
        self.search_result_widgets = []
        
        lbl_src = ctk.CTkLabel(self.input_card, text="SOURCE URL", font=("Segoe UI", 10, "bold"), text_color="#78909C")
        lbl_src.pack(anchor="w", padx=15, pady=(4, 0))
        self.theme_labels_secondary.append(lbl_src)
        
        self.url_input = ctk.CTkEntry(
            self.input_card, 
            placeholder_text="Paste YouTube Link...", 
            height=32, 
            fg_color="#070F15", 
            border_color="#1F3A4E", 
            text_color="#F5F5F7", 
            placeholder_text_color="#78909C"
        )
        self.url_input.pack(fill="x", padx=15, pady=(2, 4))
        self.theme_entries.append(self.url_input)
        
        lbl_dst = ctk.CTkLabel(self.input_card, text="DESTINATION FOLDER", font=("Segoe UI", 10, "bold"), text_color="#78909C")
        lbl_dst.pack(anchor="w", padx=15, pady=(4, 0))
        self.theme_labels_secondary.append(lbl_dst)
        
        self.folder_input = ctk.CTkEntry(
            self.input_card, 
            placeholder_text=r"C:\SMA-downloads", 
            height=32, 
            fg_color="#070F15", 
            border_color="#1F3A4E", 
            text_color="#F5F5F7", 
            placeholder_text_color="#78909C"
        )
        self.folder_input.insert(0, r"C:\SMA-downloads")
        self.folder_input.pack(fill="x", padx=15, pady=(2, 10))
        self.theme_entries.append(self.folder_input)

        # --- Panel 2: Quality Settings ---
        self.quality_card = ctk.CTkFrame(self.main_container, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.quality_card.pack(fill="x", pady=4)
        
        card2_lbl = ctk.CTkLabel(self.quality_card, text="QUALITY SETTINGS", font=("Segoe UI", 11, "bold"), text_color="#00E5FF")
        card2_lbl.pack(anchor="w", padx=15, pady=(6, 2))
        self.theme_titles.append(card2_lbl)
        
        self.quality_grid = ctk.CTkFrame(self.quality_card, fg_color="transparent")
        self.quality_grid.pack(fill="x", padx=15, pady=(2, 8))
        self.quality_grid.columnconfigure(0, weight=1)
        self.quality_grid.columnconfigure(1, weight=1)
        self.quality_grid.columnconfigure(2, weight=1)
        
        # Video settings
        video_frame = ctk.CTkFrame(self.quality_grid, fg_color="transparent")
        video_frame.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        lbl_vid = ctk.CTkLabel(video_frame, text="Video Quality", font=("Segoe UI", 11), text_color="#78909C")
        lbl_vid.pack(anchor="w")
        self.theme_labels_secondary.append(lbl_vid)
        
        self.video_quality = ctk.CTkOptionMenu(
            video_frame, 
            values=["high (1080p+)", "medium (720p)", "low (480p)"],
            height=32,
            button_color="#028090", 
            button_hover_color="#00A896", 
            fg_color="#070F15", 
            dropdown_fg_color="#0E1A24", 
            text_color="#F5F5F7",
            dropdown_text_color="#F5F5F7",
            dropdown_hover_color="#1F3A4E"
        )
        self.video_quality.pack(fill="x", pady=(1, 0))
        self.theme_option_menus.append(self.video_quality)
        
        # Audio settings
        audio_frame = ctk.CTkFrame(self.quality_grid, fg_color="transparent")
        audio_frame.grid(row=0, column=1, sticky="ew", padx=(4, 4))
        lbl_aud = ctk.CTkLabel(audio_frame, text="Audio Quality", font=("Segoe UI", 11), text_color="#78909C")
        lbl_aud.pack(anchor="w")
        self.theme_labels_secondary.append(lbl_aud)
        
        self.audio_quality = ctk.CTkOptionMenu(
            audio_frame, 
            values=["high (best sound)", "medium (standard)", "low (space-saver)"],
            height=32,
            button_color="#028090", 
            button_hover_color="#00A896", 
            fg_color="#070F15", 
            dropdown_fg_color="#0E1A24", 
            text_color="#F5F5F7",
            dropdown_text_color="#F5F5F7",
            dropdown_hover_color="#1F3A4E"
        )
        self.audio_quality.pack(fill="x", pady=(1, 0))
        self.theme_option_menus.append(self.audio_quality)
 
        # Theme settings selector
        theme_frame = ctk.CTkFrame(self.quality_grid, fg_color="transparent")
        theme_frame.grid(row=0, column=2, sticky="ew", padx=(4, 0))
        lbl_thm = ctk.CTkLabel(theme_frame, text="App Theme", font=("Segoe UI", 11), text_color="#78909C")
        lbl_thm.pack(anchor="w")
        self.theme_labels_secondary.append(lbl_thm)
        
        self.theme_menu = ctk.CTkOptionMenu(
            theme_frame,
            values=["Halloween", "Aquatic", "Nature", "Wood"],
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
        saved_theme = self.load_saved_theme()
        self.theme_menu.set(saved_theme)
        self.theme_menu.pack(fill="x", pady=(1, 0))
        self.theme_option_menus.append(self.theme_menu)

        # --- Panel 3: Options ---
        self.options_card = ctk.CTkFrame(self.main_container, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.options_card.pack(fill="x", pady=4)
        
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
        
        self.audio_switch = ctk.CTkSwitch(self.switches_subframe, text="Audio Only", progress_color="#00E5FF", text_color="#F5F5F7", font=("Segoe UI", 10))
        self.audio_switch.grid(row=0, column=0, padx=2, pady=1, sticky="w")
        self.theme_switches.append(self.audio_switch)
        
        self.subtitles_switch = ctk.CTkSwitch(self.switches_subframe, text="Subtitles", progress_color="#00E5FF", text_color="#F5F5F7", font=("Segoe UI", 10))
        self.subtitles_switch.grid(row=0, column=1, padx=2, pady=1, sticky="w")
        self.theme_switches.append(self.subtitles_switch)
        
        self.metadata_switch = ctk.CTkSwitch(self.switches_subframe, text="Metadata", progress_color="#00E5FF", text_color="#F5F5F7", font=("Segoe UI", 10))
        self.metadata_switch.grid(row=1, column=0, padx=2, pady=1, sticky="w")
        self.theme_switches.append(self.metadata_switch)
        
        self.open_folder_switch = ctk.CTkSwitch(self.switches_subframe, text="Auto Open", progress_color="#00E5FF", text_color="#F5F5F7", font=("Segoe UI", 10))
        self.open_folder_switch.select()
        self.open_folder_switch.grid(row=1, column=1, padx=2, pady=1, sticky="w")
        self.theme_switches.append(self.open_folder_switch)

        # --- Panel 4: Action Control Center ---
        self.action_card = ctk.CTkFrame(self.main_container, fg_color="#0E1A24", corner_radius=12, border_color="#1F3A4E", border_width=1)
        self.action_card.pack(fill="x", pady=4)
        
        self.action_frame = ctk.CTkFrame(self.action_card, fg_color="transparent")
        self.action_frame.pack(fill="x", padx=15, pady=(10, 4))
        self.action_frame.rowconfigure(0, weight=1)
        
        # Left: Season Number
        self.season_frame = ctk.CTkFrame(self.action_frame, fg_color="transparent")
        self.season_frame.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        
        self.season_checkbox = ctk.CTkCheckBox(
            self.season_frame, 
            text="Season #", 
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
        self.season_checkbox.pack(side="left", padx=(0, 6), anchor="center")
        self.season_input = ctk.CTkEntry(self.season_frame, width=65, height=26, fg_color="#070F15", border_color="#1F3A4E", text_color="#F5F5F7", justify="center")
        self.season_input.insert(0, "1")
        self.season_input.configure(state="disabled")
        self.season_input.pack(side="left", anchor="center")
        self.season_checkbox.deselect()
        self.theme_entries.append(self.season_input)

        # Center: Start Button / Progress Container
        self.btn_container = ctk.CTkFrame(self.action_frame, width=170, height=42, fg_color="transparent")
        self.btn_container.grid(row=0, column=1, padx=4, sticky="nsew")
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
 
        self.progress = ctk.CTkProgressBar(
            self.btn_container,
            width=160,
            height=10,
            corner_radius=5,
            progress_color="#00E5FF",
            fg_color="#070F15"
        )
        self.progress.set(0)
 
        self.progress_label = ctk.CTkLabel(
            self.btn_container,
            text="0%",
            font=("Segoe UI", 11, "bold"),
            text_color="#F5F5F7",
            fg_color="transparent"
        )
        
        # Right: Speed Limiter
        self.speed_frame = ctk.CTkFrame(self.action_frame, fg_color="transparent")
        self.speed_frame.grid(row=0, column=2, padx=(6, 0), sticky="ew")
        self.speed_lbl = ctk.CTkLabel(self.speed_frame, text="Speed (MBps):", font=("Segoe UI", 10), text_color="#78909C")
        self.speed_lbl.pack(side="left", padx=(0, 6), anchor="center")
        self.theme_labels_secondary.append(self.speed_lbl)
        
        self.speed_input = ctk.CTkEntry(self.speed_frame, width=65, height=26, fg_color="#070F15", border_color="#1F3A4E", text_color="#F5F5F7", justify="center")
        self.speed_input.insert(0, "33")
        self.speed_input.pack(side="left", anchor="center")
        self.theme_entries.append(self.speed_input)
        
        # Grid configs
        self.action_frame.columnconfigure(0, weight=1)
        self.action_frame.columnconfigure(1, weight=2)
        self.action_frame.columnconfigure(2, weight=1)

        # Tools grid under the download section
        self.tools_frame = ctk.CTkFrame(self.action_card, fg_color="transparent")
        self.tools_frame.pack(fill="x", padx=15, pady=(2, 10))
        self.tools_frame.columnconfigure(0, weight=1)
        self.tools_frame.columnconfigure(1, weight=1)
        self.tools_frame.columnconfigure(2, weight=1)
        self.tools_frame.columnconfigure(3, weight=1)
        
        self.update_cookies_btn = ctk.CTkButton(
            self.tools_frame,
            text="Upload Cookies",
            height=30,
            border_width=1,
            font=("Segoe UI", 10, "bold"),
            command=self.upload_cookies
        )
        self.update_cookies_btn.grid(row=0, column=0, padx=4, sticky="ew")
        self.theme_buttons_secondary.append(self.update_cookies_btn)

        self.update_ytdlp_btn = ctk.CTkButton(
            self.tools_frame,
            text="Update Engine",
            height=30,
            border_width=1,
            font=("Segoe UI", 10, "bold"),
            command=self.update_ytdlp
        )
        self.update_ytdlp_btn.grid(row=0, column=1, padx=4, sticky="ew")
        self.theme_buttons_secondary.append(self.update_ytdlp_btn)

        self.toggle_log_btn = ctk.CTkButton(
            self.tools_frame,
            text="Show Log",
            height=30,
            border_width=1,
            font=("Segoe UI", 10, "bold"),
            command=self.toggle_log
        )
        self.toggle_log_btn.grid(row=0, column=2, padx=4, sticky="ew")
        self.theme_buttons_secondary.append(self.toggle_log_btn)

        self.open_error_log_btn = ctk.CTkButton(
            self.tools_frame,
            text="Open Error Log",
            height=30,
            border_width=1,
            font=("Segoe UI", 10, "bold"),
            command=self.open_error_log
        )
        self.open_error_log_btn.grid(row=0, column=3, padx=4, sticky="ew")
        self.theme_buttons_secondary.append(self.open_error_log_btn)

        # Status box (styled, hidden initially)
        self.status_box = ctk.CTkTextbox(
            self, 
            width=800, 
            height=140, 
            fg_color="#070F15", 
            border_color="#1F3A4E", 
            border_width=1, 
            text_color="#9E9EAF"
        )
        self.log_visible = False
        self.search_visible = False
        
        # --- Taskbar Progress & Tray Icon Initialization ---
        self.taskbar = None
        self.selected_search_card = None
        try:
            import comtypes.client as cc
            cc.GetModule("shobjidl.tlb")
            import comtypes.gen.TaskbarLib as tbl  # type: ignore # pylint: disable=import-error,no-name-in-module # pyright: ignore[reportMissingImports, reportGeneralTypeIssues]
            tb = cc.CreateObject("{56FDF344-FD6D-11d0-958A-006097C9A090}", interface=tbl.ITaskbarList3)
            if tb is not None:
                tb.HrInit()
                self.taskbar = tb
        except Exception as e:
            print("Taskbar progress init failed:", e)
            
        self.tray_icon = None
        self.setup_tray()
        
        self.apply_theme(saved_theme)
        
        self.after(100, lambda: self.update_taskbar_progress(0))
        
        self.bind("<Unmap>", self.on_minimize)
        self.protocol("WM_DELETE_WINDOW", self.close_to_tray)

    def on_minimize(self, event):
        if self.state() == "iconic":
            self.withdraw()

    def setup_tray(self):
        try:
            import pystray
            from PIL import Image
            
            icon_path = self.get_file_path("icon.ico")
            if os.path.exists(icon_path):
                icon_image = Image.open(icon_path)
            else:
                icon_image = Image.new('RGB', (64, 64), color='#FF5722')
                
            menu = pystray.Menu(
                pystray.MenuItem("Show Window", self.show_window_from_tray, default=True),
                pystray.MenuItem("Exit", self.exit_app_from_tray)
            )
            
            self.tray_icon = pystray.Icon(
                "SMArchive",
                icon_image,
                "Strothman Media Archive",
                menu
            )
            
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        except Exception as e:
            print("Failed to initialize tray icon:", e)

    def show_window_from_tray(self, icon=None, item=None):
        self.deiconify()
        self.state("normal")
        self.focus_force()

    def exit_app_from_tray(self, icon=None, item=None):
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.destroy()
        sys.exit(0)

    def close_to_tray(self):
        # If download is active (Start button is hidden), withdraw to tray. Otherwise close.
        if hasattr(self, 'download_button') and not self.download_button.winfo_ismapped():
            self.withdraw()
            self.log("Downloader running in background. Double-click tray icon to restore.")
        else:
            self.exit_app_from_tray()

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
                        self.taskbar.SetProgressState(hwnd, 0) # TBPF_NOPROGRESS
                    else:
                        self.taskbar.SetProgressState(hwnd, 2) # TBPF_NORMAL
                        self.taskbar.SetProgressValue(hwnd, int(val), int(total))
            except Exception as e:
                print("Failed to set taskbar progress:", e)

    def toggle_season_input(self):
        if self.season_checkbox.get() == 1:
            self.season_input.configure(state="normal")
        else:
            self.season_input.configure(state="disabled")

    def fetch_and_display_avatar(self, url):
        """ Scrapes the uploader's channel avatar in the background and saves it to a temp file """
        try:
            yt_dlp_path = self.get_active_yt_dlp_path()
            cookies_path = self.get_active_cookies_path()
            
            # 1. Fetch channel URL using yt-dlp
            if "youtube.com/channel/" in url or "youtube.com/@" in url or "youtube.com/c/" in url:
                channel_url = url
            else:
                cmd = [yt_dlp_path, "--cookies", cookies_path, "--print", "uploader_url", url]
                res = subprocess.run(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                channel_url = res.stdout.strip()
                
            if not channel_url or "http" not in channel_url:
                channel_url = url
                
            # 2. Scrape the avatar URL from channel HTML
            import urllib.request
            import ssl
            req = urllib.request.Request(channel_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            
            avatar_url = None
            with urllib.request.urlopen(req, context=ctx) as response:
                html = response.read().decode('utf-8', errors='ignore')
                match = re.search(r'<meta property="og:image" content="([^"]+)"', html)
                if match:
                    avatar_url = match.group(1)
                else:
                    match_fallback = re.search(r'"avatar":{"thumbnails":\[{"url":"([^"]+)"', html)
                    if match_fallback:
                        avatar_url = match_fallback.group(1).replace(r"\u0026", "&")
                        
            if avatar_url:
                # Download to temp directory
                exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
                temp_avatar_path = os.path.join(exe_dir, "temp_avatar.png")
                
                # Fetch image bytes
                img_data = urllib.request.urlopen(avatar_url, context=ctx).read()
                with open(temp_avatar_path, "wb") as f:
                    f.write(img_data)
                    
                # Load and display in main thread
                self.after(0, self.load_avatar_file)
        except Exception as e:
            print("Avatar load failed:", e)

    def load_avatar_file(self):
        """ Loads the temporary avatar file in the main thread and displays it """
        try:
            exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
            temp_avatar_path = os.path.join(exe_dir, "temp_avatar.png")
            if os.path.exists(temp_avatar_path):
                from PIL import Image
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
                self.log(f"ERROR: Could not save cookies. {e}")

    def update_ytdlp(self):
        """ Runs updates for yt-dlp.exe directly """
        if self.update_ytdlp_btn:
            self.update_ytdlp_btn.configure(state="disabled", text="Updating...")
        
        def run_update():
            self.log("Starting engine update check...")
            exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
            target_path = os.path.join(exe_dir, "yt-dlp.exe")
            
            # If the updated file doesn't exist in the exe directory yet, copy the bundled one there
            if not os.path.exists(target_path):
                try:
                    bundled_path = self.get_file_path("yt-dlp.exe")
                    shutil.copy(bundled_path, target_path)
                except Exception as e:
                    self.log(f"ERROR: Could not prepare engine for update: {e}", is_error=True)
                    self.after(0, lambda: self.update_ytdlp_btn.configure(text="Update Failed! ❌") if self.update_ytdlp_btn else None)
                    self.after(4000, self.reset_update_button)
                    return
            
            # Run the update command on the executable in the execution directory
            self.log(f"Running update on: {target_path}")
            cmd = [target_path, "-U"]
            try:
                # We use creationflags to run invisibly
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

    def toggle_log(self):
        if self.log_visible:
            self.hide_log()
        else:
            self.show_log()

    def adjust_window_size(self):
        if self.log_visible:
            target_height = 950 if self.search_visible else 750
        else:
            target_height = 780 if self.search_visible else 580
        geom = self.geometry()
        if geom:
            match = re.match(r"\d+x\d+\+(\d+)\+(\d+)", geom)
            if match:
                self.geometry(f"660x{target_height}+{match.group(1)}+{match.group(2)}")
            else:
                self.geometry(f"660x{target_height}")
        else:
            self.geometry(f"660x{target_height}")

    def show_log(self):
        if not self.log_visible:
            self.status_box.pack(fill="x", padx=30, pady=5)
            if self.toggle_log_btn:
                self.toggle_log_btn.configure(text="Hide Log")
            self.log_visible = True
            self.adjust_window_size()
  
    def hide_log(self):
        if self.log_visible:
            self.status_box.pack_forget()
            if self.toggle_log_btn:
                self.toggle_log_btn.configure(text="Show Log")
            self.log_visible = False
            self.adjust_window_size()

    def open_error_log(self):
        """ Opens the persistent error log file in the default system text editor """
        try:
            exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
            log_file = os.path.join(exe_dir, "downloader_errors.txt")
            if not os.path.exists(log_file):
                with open(log_file, "w", encoding="utf-8") as f:
                    from datetime import datetime
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    f.write(f"[{timestamp}] Strothman Media Archive error log initialized.\n")
            try:
                os.startfile(log_file)
            except Exception:
                subprocess.Popen(["notepad.exe", log_file])
        except Exception as e:
            self.log(f"Could not open error log: {e}", is_error=True)

    def log(self, message, is_error=False):
        self.status_box.insert("end", message + "\n")
        self.status_box.see("end")
        
        # Check for signature solving / JavaScript runtime errors to offer helpful tips
        if "signature solving failed" in message.lower() or "javascript runtime" in message.lower() or "n challenge solving failed" in message.lower():
            tip_msg = "\n💡 [HELP] YouTube now requires an external JavaScript runtime to download videos.\n" \
                      "👉 To fix this on Windows:\n" \
                      "1. Open PowerShell and run: winget install DenoLand.Deno\n" \
                      "2. OR download 'deno.exe' and place it in the folder next to this app.\n" \
                      "3. Then restart the application."
            current_content = self.status_box.get("1.0", "end")
            if "[HELP] YouTube now requires" not in current_content:
                self.status_box.insert("end", tip_msg + "\n")
                self.status_box.see("end")
                self.after(0, self.show_js_runtime_alert)

        if is_error or "error" in message.lower() or "fatal" in message.lower():
            self.show_log()
            
            # Write to persistent error log file next to the executable
            try:
                from datetime import datetime
                exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
                log_file = os.path.join(exe_dir, "downloader_errors.txt")
                with open(log_file, "a", encoding="utf-8") as f:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    f.write(f"[{timestamp}] {message}\n")
            except Exception:
                pass

    def show_js_runtime_alert(self):
        from tkinter import messagebox
        messagebox.showwarning(
            "JavaScript Runtime Required",
            "YouTube has updated their security. This application now requires a JavaScript runtime (like Deno) to solve video signatures.\n\n"
            "To fix this:\n"
            "1. Open PowerShell and run:\n"
            "   winget install DenoLand.Deno\n\n"
            "2. Or download 'deno.exe' and place it in the same directory as this app.\n\n"
            "Please restart the app after installation."
        )

    def start_download(self):
        self.progress.set(0)
        self.progress_label.configure(text="0%")
        self.download_button.place_forget()
        self.progress.place(relx=0.5, rely=0.35, anchor="center")
        self.progress_label.place(relx=0.5, rely=0.75, anchor="center")
        self.update_taskbar_progress(0)
        # Auto-hide search results and collapse window height
        self.results_frame.pack_forget()
        self.search_visible = False
        self.adjust_window_size()
        
        # Set status light to active initializing
        self.power_light.configure(text="● INITIALIZING", text_color=self.theme_cfg.get("accent", "#38BDF8"))
        
        url = self.url_input.get()
        if url:
            threading.Thread(target=self.fetch_and_display_avatar, args=(url,), daemon=True).start()
        threading.Thread(target=self.run_command, daemon=True).start()

    def reset_download_button(self):
        self.progress.place_forget()
        self.progress_label.place_forget()
        self.download_button.place(x=0, y=0)
        self.update_taskbar_progress(0)
        # Reset the status light to theme default
        self.power_light.configure(text=self.theme_cfg.get("status_text", "● ONLINE"), text_color=self.theme_cfg.get("status_color", "#38BDF8"))

    def run_command(self):
        url = self.url_input.get()
        folder = self.folder_input.get()
        
        # Get season if enabled
        if self.season_checkbox.get() == 1:
            try:
                season = int(self.season_input.get())
            except ValueError:
                season = 1
        else:
            season = None
            
        speed = self.speed_input.get()
        
        yt_dlp_path = self.get_active_yt_dlp_path()
        cookies_path = self.get_active_cookies_path() # Uses the smart pathing logic
        
        self.log("Initializing download...")
        
        # --- SMARTER PRE-CHECK BLOCK ---
        check_cmd = [yt_dlp_path, "--cookies", cookies_path, "-i", "--get-id", url]
        result = subprocess.run(check_cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        
        valid_ids = [line for line in result.stdout.strip().split('\n') if line]
        
        if not valid_ids:
            error_msg = result.stderr.strip() if result.stderr else "No valid videos found in link."
            self.log("--- FATAL ERROR ---")
            self.log(error_msg)
            self.log("------------------------")
            self.log("Download stopped. Could not find any readable videos.")
            self.power_light.configure(text="● ERROR", text_color="#FF5722")
            self.after(0, self.reset_download_button)
            return
            
        total_files = len(valid_ids)
        self.log(f"Found {total_files} valid videos. Skipping dead links...")
        
        command = [
            yt_dlp_path, 
            "--newline", 
            "--progress", 
            "--cookies", cookies_path, 
            "-i",
            "-P", folder, 
            "--sleep-interval", "3",
            "--max-sleep-interval", "8"
        ]
        
        if season is not None:
            start_num = (season * 100) + 1
            command.extend(["--autonumber-start", str(start_num)])
            
        if speed:
            command.extend(["-r", f"{speed}M"])
        
        if self.audio_switch.get():
            aq = {"low (space-saver)": "9", "medium (standard)": "5"}.get(self.audio_quality.get(), "0")
            command.extend(["-f", "ba", "--extract-audio", "--audio-format", "mp3", "--audio-quality", aq])
        else:
            q = self.video_quality.get()
            fmt = "bv*[vcodec^=avc1][height<=480]+ba[acodec^=mp4a]/b[ext=mp4][height<=480]/bv*[height<=480]+ba/b[height<=480]/best" if "low" in q else \
                  "bv*[vcodec^=avc1][height<=720]+ba[acodec^=mp4a]/b[ext=mp4][height<=720]/bv*[height<=720]+ba/b[height<=720]/best" if "medium" in q else \
                  "bv*[vcodec^=avc1]+ba[acodec^=mp4a]/b[ext=mp4]/bv*+ba/b/best"
            command.extend(["-f", fmt, "--merge-output-format", "mp4"])
 
        if self.subtitles_switch.get():
            command.extend(["--write-subs", "--write-auto-subs", "--convert-subs", "srt"])
        if self.metadata_switch.get():
            command.extend(["--embed-metadata", "--embed-thumbnail", "--embed-chapters"])
        
        if season is not None:
            command.extend(["-o", "%(playlist_title,uploader)s/%(autonumber)03d - %(title)s.%(ext)s", url])
        else:
            command.extend(["-o", "%(playlist_title,uploader)s/%(title)s.%(ext)s", url])

        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        current_file = 0
        if process.stdout:
            for line in process.stdout:
                line_str = line.strip()
                if "[download] Downloading item" in line_str:
                    current_file += 1
                    self.power_light.configure(text=f"● DOWNLOADING: {current_file}/{total_files}", text_color=self.theme_cfg.get("accent", "#38BDF8"))
                match = re.search(r"(\d+\.?\d*)%", line_str)
                if match: 
                    pct = float(match.group(1))
                    overall_pct = ((current_file - 1) * 100 + pct) / total_files if total_files > 0 else pct
                    self.progress.set(overall_pct / 100)
                    self.progress_label.configure(text=f"{int(overall_pct)}%")
                    self.update_taskbar_progress(overall_pct)
                
                # Log any errors or warnings during download
                if "error" in line_str.lower() or "warning" in line_str.lower():
                    self.log(line_str)
        
        process.wait()
        if process.returncode != 0:
            self.power_light.configure(text="● ERROR", text_color="#FF5722")
            self.log(f"Download failed with exit code {process.returncode}.", is_error=True)
            self.update_taskbar_progress(0)
        else:
            self.progress.set(1)
            self.progress_label.configure(text="100%")
            self.power_light.configure(text="● FINISHED", text_color="#10B981")
            self.log("All downloads complete!")
            self.update_taskbar_progress(100)
            self.after(2000, lambda: self.update_taskbar_progress(0))
            if self.open_folder_switch.get():
                try:
                    os.startfile(folder)
                except Exception as e:
                    self.log(f"Could not open directory: {e}", is_error=True)
        
        self.after(0, self.reset_download_button)

    def search_youtube(self):
        query = self.search_input.get().strip()
        if not query:
            return
            
        self.search_button.configure(state="disabled", text="Searching...")
        
        # Clear previous search results and pack the results frame in the correct position
        for widget in self.results_frame.winfo_children():
            widget.destroy()
            
        self.results_frame.pack(fill="x", padx=15, pady=(2, 4), after=self.search_frame)
        loading_label = ctk.CTkLabel(self.results_frame, text="🔍 Searching YouTube...", font=("Segoe UI", 12), text_color="#00E5FF")
        loading_label.pack(pady=10)
        
        self.search_visible = True
        self.adjust_window_size()
        
        def run_search():
            try:
                yt_dlp_path = self.get_active_yt_dlp_path()
                cookies_path = self.get_active_cookies_path()
                
                cmd = [
                    yt_dlp_path,
                    "--cookies", cookies_path,
                    "--dump-single-json",
                    "--flat-playlist",
                    "--no-playlist",
                    f"ytsearch6:{query}"
                ]
                
                res = subprocess.run(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                if res.returncode != 0:
                    self.log(f"Search failed: {res.stderr.strip()}", is_error=True)
                    self.after(0, lambda: self.show_search_error("Search failed."))
                    return
                
                import json
                data = json.loads(res.stdout.strip())
                entries = data.get("entries", [])
                
                if not entries:
                    self.after(0, lambda: self.show_search_error("No videos found."))
                    return
                    
                # Download thumbnails
                temp_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
                results = []
                import urllib.request
                import ssl
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                
                for idx, entry in enumerate(entries[:6]):
                    title = entry.get("title", "No Title")
                    url = entry.get("url", "")
                    thumbnails = entry.get("thumbnails", [])
                    thumb_url = None
                    if thumbnails:
                        thumb_url = thumbnails[-1].get("url")
                    
                    local_thumb_path = None
                    if thumb_url:
                        try:
                            local_thumb_path = os.path.join(temp_dir, f"temp_thumb_{idx}.jpg")
                            img_data = urllib.request.urlopen(thumb_url, context=ctx).read()
                            with open(local_thumb_path, "wb") as f:
                                f.write(img_data)
                        except Exception as e:
                            print(f"Failed to download thumbnail {idx}: {e}")
                            local_thumb_path = None
                            
                    results.append({
                        "title": title,
                        "url": url,
                        "thumb_path": local_thumb_path
                    })
                    
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
        self.results_frame.pack(fill="x", padx=15, pady=(2, 4), after=self.search_frame)
        err_label = ctk.CTkLabel(self.results_frame, text=message, font=("Segoe UI", 11), text_color="#FF5722")
        err_label.pack(pady=10)

    def display_search_results(self, results):
        for widget in self.results_frame.winfo_children():
            widget.destroy()
            
        self.results_frame.pack(fill="x", padx=15, pady=(2, 4), after=self.search_frame)
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
            result_card.grid(row=row_idx, column=col_idx, padx=4, pady=4, sticky="nsew")
            
            from PIL import Image
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
            
            # Click and Hover Handlers
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
            
            # Bind events to card and all its sub-widgets
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

    def apply_theme(self, theme_name):
        themes = {
            "Halloween": {
                "app_bg": "#0F0F11",
                "card_bg": "#18181C",
                "border": "#2B2B30",
                "border_width": 1,
                "accent": "#FF6E40",
                "text_primary": "#F3F4F6",
                "text_secondary": "#9CA3AF",
                "btn_bg": "#231C1A",
                "btn_border": "#FF6E40",
                "btn_text": "#FF6E40",
                "btn_hover": "#3A241F",
                "status_text": "● ACTIVE",
                "status_color": "#FF6E40",
                "input_bg": "#0F0F11",
                "input_border": "#2B2B30",
                "option_btn": "#1E1E24",
                "option_hover": "#2E2E38",
                "option_bg": "#0F0F11",
                "option_drop": "#18181C"
            },
            "Aquatic": {
                "app_bg": "#0B0F19",
                "card_bg": "#1E293B",
                "border": "#334155",
                "border_width": 1,
                "accent": "#38BDF8",
                "text_primary": "#F8FAFC",
                "text_secondary": "#94A3B8",
                "btn_bg": "#0F172A",
                "btn_border": "#38BDF8",
                "btn_text": "#38BDF8",
                "btn_hover": "#1E293B",
                "status_text": "● ONLINE",
                "status_color": "#38BDF8",
                "input_bg": "#0B0F19",
                "input_border": "#334155",
                "option_btn": "#1E293B",
                "option_hover": "#334155",
                "option_bg": "#0B0F19",
                "option_drop": "#1E293B"
            },
            "Nature": {
                "app_bg": "#080F0A",
                "card_bg": "#112217",
                "border": "#1E3F2A",
                "border_width": 1,
                "accent": "#10B981",
                "text_primary": "#ECFDF5",
                "text_secondary": "#A7F3D0",
                "btn_bg": "#064E3B",
                "btn_border": "#10B981",
                "btn_text": "#10B981",
                "btn_hover": "#1E3F2A",
                "status_text": "● ECO MODE",
                "status_color": "#10B981",
                "input_bg": "#080F0A",
                "input_border": "#1E3F2A",
                "option_btn": "#112217",
                "option_hover": "#1E3F2A",
                "option_bg": "#080F0A",
                "option_drop": "#112217"
            },
            "Wood": {
                "app_bg": "#120E0B",
                "card_bg": "#1E1712",
                "border": "#3A2E26",
                "border_width": 1,
                "accent": "#D97706",
                "text_primary": "#FEF3C7",
                "text_secondary": "#F59E0B",
                "btn_bg": "#451A03",
                "btn_border": "#D97706",
                "btn_text": "#D97706",
                "btn_hover": "#3A2E26",
                "status_text": "● WARM",
                "status_color": "#D97706",
                "input_bg": "#120E0B",
                "input_border": "#3A2E26",
                "option_btn": "#1E1712",
                "option_hover": "#3A2E26",
                "option_bg": "#120E0B",
                "option_drop": "#1E1712"
            }
        }
        
        cfg = themes.get(theme_name, themes["Halloween"])
        self.theme_cfg = cfg
        
        # Configure app background
        self.configure(fg_color=cfg["app_bg"])
        
        # Configure cards
        cards = [self.input_card, self.quality_card, self.options_card, self.action_card]
        for card in cards:
            card.configure(
                fg_color=cfg["card_bg"], 
                border_color=cfg["border"], 
                border_width=cfg["border_width"]
            )
            
        # Configure titles
        self.title_label.configure(text_color=cfg["text_primary"])
        self.subtitle_label.configure(text_color=cfg["text_secondary"])
        self.power_light.configure(text=cfg["status_text"], text_color=cfg["status_color"])
        
        for title_lbl in self.theme_titles:
            title_lbl.configure(text_color=cfg["text_primary"])
            
        for sec_lbl in self.theme_labels_secondary:
            sec_lbl.configure(text_color=cfg["text_secondary"])
            
        # Configure entries
        for entry in self.theme_entries:
            entry.configure(
                fg_color=cfg["input_bg"],
                border_color=cfg["input_border"],
                text_color="#F5F5F7",
                placeholder_text_color=cfg["text_secondary"]
            )
            
        # Configure OptionMenus
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
            
        # Configure switches
        for sw in self.theme_switches:
            sw.configure(
                progress_color=cfg["accent"],
                text_color="#F5F5F7"
            )
            
        # Configure season checkbox
        self.season_checkbox.configure(
            fg_color=cfg["option_btn"],
            hover_color=cfg["option_hover"],
            checkmark_color=cfg["input_bg"],
            text_color=cfg["text_secondary"]
        )
        
        # Configure secondary buttons
        for btn in self.theme_buttons_secondary:
            btn.configure(
                fg_color=cfg["input_bg"],
                border_color=cfg["btn_border"],
                border_width=1,
                text_color=cfg["btn_text"],
                hover_color=cfg["btn_hover"]
            )
            
        # Configure primary download button
        self.download_button.configure(
            fg_color=cfg["btn_bg"],
            border_color=cfg["btn_border"],
            text_color=cfg["btn_text"],
            hover_color=cfg["btn_hover"]
        )
        
        # Configure progress bar
        self.progress.configure(
            progress_color=cfg["accent"],
            fg_color=cfg["input_bg"]
        )
        
        # Configure status box
        self.status_box.configure(
            fg_color=cfg["input_bg"],
            border_color=cfg["input_border"],
            text_color="#9E9EAF"
        )
        
        # Recolor search results card if visible
        for card, card_url in self.search_result_widgets:
            card.configure(fg_color=cfg["input_bg"], border_color=cfg["border"])
            
        self.save_theme(theme_name)

    def load_saved_theme(self):
        try:
            exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
            settings_path = os.path.join(exe_dir, "settings.json")
            if os.path.exists(settings_path):
                import json
                with open(settings_path, "r") as f:
                    data = json.load(f)
                    return data.get("theme", "Aquatic")
        except Exception:
            pass
        return "Aquatic"

    def save_theme(self, theme_name):
        try:
            exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
            settings_path = os.path.join(exe_dir, "settings.json")
            import json
            data = {"theme": theme_name}
            with open(settings_path, "w") as f:
                json.dump(data, f)
        except Exception:
            pass

if __name__ == "__main__":
    app = DownloaderApp()
    app.mainloop()