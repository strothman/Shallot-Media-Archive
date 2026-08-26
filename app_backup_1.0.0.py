import customtkinter as ctk
import subprocess
import threading
import os
import sys
import re
import shutil

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

        width, height = 550, 580
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

        self.label = ctk.CTkLabel(self, text="Strothman Media Archive", font=("Arial", 18, "bold"))
        self.label.pack(pady=(10, 5))

        self.url_input = ctk.CTkEntry(self, width=450, placeholder_text="Paste YouTube Link...")
        self.url_input.pack(pady=2)
        
        self.folder_input = ctk.CTkEntry(self, width=450, placeholder_text=r"C:\SMA-downloads")
        self.folder_input.insert(0, r"C:\SMA-downloads")
        self.folder_input.pack(pady=2)

        # --- Quality Settings ---
        ctk.CTkLabel(self, text="--- Video Mode Settings ---", font=("Arial", 11, "bold")).pack(pady=(5, 0))
        self.video_quality = ctk.CTkOptionMenu(self, values=["high (1080p+)", "medium (720p)", "low (480p)"])
        self.video_quality.pack(pady=2)

        ctk.CTkLabel(self, text="--- Audio Mode Settings (If Audio Only is ON) ---", font=("Arial", 11, "bold")).pack(pady=(5, 0))
        self.audio_quality = ctk.CTkOptionMenu(self, values=["high (best sound)", "medium (standard)", "low (space-saver)"])
        self.audio_quality.pack(pady=5)

        # --- Divider Line ---
        self.divider = ctk.CTkFrame(self, height=2, width=450, fg_color="#374151")
        self.divider.pack(pady=10)

        # --- Switches Container (Horizontal Row) ---
        self.switches_container = ctk.CTkFrame(self, fg_color="transparent")
        self.switches_container.pack(pady=5)

        # Left side of switches: Avatar image label (hidden initially by text="", width=60)
        self.avatar_label = ctk.CTkLabel(self.switches_container, text="", width=60)
        self.avatar_label.pack(side="left", padx=(0, 20))

        # Right side of switches: Stack of Switches
        self.switches_subframe = ctk.CTkFrame(self.switches_container, fg_color="transparent")
        self.switches_subframe.pack(side="left")

        self.audio_switch = ctk.CTkSwitch(self.switches_subframe, text="Audio Only Mode")
        self.audio_switch.pack(pady=2, anchor="w")
        self.subtitles_switch = ctk.CTkSwitch(self.switches_subframe, text="Download Subtitles")
        self.subtitles_switch.pack(pady=2, anchor="w")
        self.metadata_switch = ctk.CTkSwitch(self.switches_subframe, text="Embed Plex Metadata")
        self.metadata_switch.pack(pady=2, anchor="w")
        self.open_folder_switch = ctk.CTkSwitch(self.switches_subframe, text="Open folder when done")
        self.open_folder_switch.select()
        self.open_folder_switch.pack(pady=5, anchor="w")

        # --- HORIZONTAL ACTION ROW ---
        self.action_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.action_frame.pack(pady=5)

        # Left: Season Number
        self.season_frame = ctk.CTkFrame(self.action_frame, fg_color="transparent")
        self.season_frame.grid(row=0, column=0, padx=10)
        
        self.season_checkbox = ctk.CTkCheckBox(
            self.season_frame, 
            text="Season #", 
            font=("Segoe UI", 11),
            width=18,
            height=18,
            checkbox_width=16,
            checkbox_height=16,
            command=self.toggle_season_input
        )
        self.season_checkbox.pack(pady=(0, 2))
        self.season_input = ctk.CTkEntry(self.season_frame, width=70)
        self.season_input.insert(0, "1")
        self.season_input.configure(state="disabled")
        self.season_input.pack()
        self.season_checkbox.deselect()  # Unchecked/Disabled by default

        # Center: Start Button / Progress Container
        self.btn_container = ctk.CTkFrame(self.action_frame, width=180, height=38, fg_color="transparent")
        self.btn_container.grid(row=0, column=1, padx=20)
        self.btn_container.pack_propagate(False)
        self.btn_container.grid_propagate(False)

        self.download_button = ctk.CTkButton(
            self.btn_container, 
            text="START DOWNLOAD", 
            fg_color="#F97316", 
            hover_color="#EA580C", 
            text_color="#FFFFFF",
            font=("Segoe UI", 13, "bold"),
            width=180,
            height=38,
            corner_radius=8,
            command=self.start_download
        )
        self.download_button.place(x=0, y=0)

        self.progress = ctk.CTkProgressBar(
            self.btn_container,
            width=180,
            height=38,
            corner_radius=8,
            border_width=2,
            border_color="#4B5563",
            progress_color="#F97316",
            fg_color="#1F2937"
        )
        self.progress.set(0)

        self.progress_label = ctk.CTkLabel(
            self.btn_container,
            text="0%",
            font=("Segoe UI", 13, "bold"),
            text_color="#FFFFFF",
            fg_color="transparent"
        )

        # Right: Speed Limiter
        self.speed_frame = ctk.CTkFrame(self.action_frame, fg_color="transparent")
        self.speed_frame.grid(row=0, column=2, padx=10)
        self.speed_lbl = ctk.CTkLabel(self.speed_frame, text="Speed (MBps):")
        self.speed_lbl.pack(pady=(0, 2))
        self.speed_input = ctk.CTkEntry(self.speed_frame, width=70)
        self.speed_input.insert(0, "15")
        self.speed_input.pack()

        self.queue_label = ctk.CTkLabel(self, text="Queue: Ready", font=("Arial", 12))
        self.queue_label.pack(pady=2)



        # --- Update Cookies & Engine Row ---
        self.cookies_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.cookies_frame.pack(pady=(5, 2))

        self.update_cookies_btn = ctk.CTkButton(
            self.cookies_frame, 
            text="Upload cookies.txt", 
            width=150, 
            height=26, 
            fg_color="#374151", 
            hover_color="#4B5563",
            text_color="#F3F4F6",
            font=("Segoe UI", 11, "normal"),
            corner_radius=6,
            command=self.upload_cookies
        )
        self.update_cookies_btn.grid(row=0, column=0, padx=5)

        self.update_ytdlp_btn = ctk.CTkButton(
            self.cookies_frame, 
            text="Update Engine (yt-dlp)", 
            width=175, 
            height=26, 
            fg_color="#374151", 
            hover_color="#4B5563",
            text_color="#F3F4F6",
            font=("Segoe UI", 11, "normal"),
            corner_radius=6,
            command=self.update_ytdlp
        )
        self.update_ytdlp_btn.grid(row=0, column=1, padx=5)

        # Toggle Log Button
        self.toggle_log_btn = ctk.CTkButton(
            self, 
            text="Show Log", 
            width=100, 
            height=22, 
            fg_color="#374151", 
            hover_color="#4B5563", 
            text_color="#F3F4F6",
            font=("Segoe UI", 10), 
            command=self.toggle_log
        )
        self.toggle_log_btn.pack(pady=5)

        # Open Error Log Button (placed in bottom-right)
        self.open_error_log_btn = ctk.CTkButton(
            self,
            text="Open Error Log",
            width=110,
            height=22,
            fg_color="#374151",
            hover_color="#4B5563",
            text_color="#F3F4F6",
            font=("Segoe UI", 10),
            command=self.open_error_log
        )
        self.open_error_log_btn.place(relx=1.0, rely=1.0, anchor="se", x=-15, y=-15)

        # Status box (increased height to 120, hidden initially)
        self.status_box = ctk.CTkTextbox(self, width=450, height=120)
        self.log_visible = False

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
            import urllib.request, re, ssl
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
                self.avatar_label.image = ctk_img
        except Exception as e:
            print("Failed to render avatar:", e)

    def get_file_path(self, filename):
        """ Universal path finder for dev and bundled PyInstaller EXE """
        if hasattr(sys, '_MEIPASS'):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
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
                
                self.log(f"SUCCESS: New cookies.txt saved permanently!")
                self.log(f"Location: {target_path}")
            except Exception as e:
                self.log(f"ERROR: Could not save cookies. {e}")

    def update_ytdlp(self):
        """ Runs updates for yt-dlp.exe directly """
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
                    self.after(0, lambda: self.update_ytdlp_btn.configure(text="Update Failed! ❌"))
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
                    self.after(0, lambda: self.update_ytdlp_btn.configure(text="Update Complete! 🎉"))
                else:
                    self.log(f"ERROR: Update failed: {res.stderr.strip() or res.stdout.strip()}", is_error=True)
                    self.after(0, lambda: self.update_ytdlp_btn.configure(text="Update Failed! ❌"))
            except Exception as e:
                self.log(f"ERROR running update command: {e}", is_error=True)
                self.after(0, lambda: self.update_ytdlp_btn.configure(text="Update Failed! ❌"))
                
            self.after(4000, self.reset_update_button)

        threading.Thread(target=run_update, daemon=True).start()

    def reset_update_button(self):
        self.update_ytdlp_btn.configure(state="normal", text="Update Engine (yt-dlp)")

    def toggle_log(self):
        if self.log_visible:
            self.hide_log()
        else:
            self.show_log()

    def show_log(self):
        if not self.log_visible:
            self.status_box.pack(pady=5)
            self.toggle_log_btn.configure(text="Hide Log")
            # Update window height to 710 while preserving coordinates
            geom = self.geometry()
            match = re.match(r"\d+x\d+\+(\d+)\+(\d+)", geom)
            if match:
                x, y = match.group(1), match.group(2)
                self.geometry(f"550x710+{x}+{y}")
            else:
                self.geometry("550x710")
            self.log_visible = True

    def hide_log(self):
        if self.log_visible:
            self.status_box.pack_forget()
            self.toggle_log_btn.configure(text="Show Log")
            # Update window height to 580 while preserving coordinates
            geom = self.geometry()
            match = re.match(r"\d+x\d+\+(\d+)\+(\d+)", geom)
            if match:
                x, y = match.group(1), match.group(2)
                self.geometry(f"550x580+{x}+{y}")
            else:
                self.geometry("550x580")
            self.log_visible = False

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
            os.startfile(log_file)
        except Exception as e:
            self.log(f"Could not open error log: {e}", is_error=True)

    def log(self, message, is_error=False):
        self.status_box.insert("end", message + "\n")
        self.status_box.see("end")
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

    def start_download(self):
        self.progress.set(0)
        self.progress_label.configure(text="0%")
        self.download_button.place_forget()
        self.progress.place(x=0, y=0)
        self.progress_label.place(relx=0.5, rely=0.5, anchor="center")
        url = self.url_input.get()
        if url:
            threading.Thread(target=self.fetch_and_display_avatar, args=(url,), daemon=True).start()
        threading.Thread(target=self.run_command, daemon=True).start()

    def reset_download_button(self):
        self.progress.place_forget()
        self.progress_label.place_forget()
        self.download_button.place(x=0, y=0)

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
            self.queue_label.configure(text="Queue: Error")
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
            
        if speed: command.extend(["-r", f"{speed}M"])
        
        if self.audio_switch.get():
            aq = {"low (space-saver)": "9", "medium (standard)": "5"}.get(self.audio_quality.get(), "0")
            command.extend(["-f", "ba", "--extract-audio", "--audio-format", "mp3", "--audio-quality", aq])
        else:
            q = self.video_quality.get()
            fmt = "bv*[vcodec^=avc1][height<=480]+ba[acodec^=mp4a]/b[ext=mp4]/b" if "low" in q else \
                  "bv*[vcodec^=avc1][height<=720]+ba[acodec^=mp4a]/b[ext=mp4]/b" if "medium" in q else \
                  "bv*[vcodec^=avc1]+ba[acodec^=mp4a]/b[ext=mp4]/b"
            command.extend(["-f", fmt, "--merge-output-format", "mp4"])
 
        if self.subtitles_switch.get(): command.extend(["--write-subs", "--write-auto-subs", "--convert-subs", "srt"])
        if self.metadata_switch.get(): command.extend(["--embed-metadata", "--embed-thumbnail", "--embed-chapters"])
        
        if season is not None:
            command.extend(["-o", "%(playlist_title,uploader)s/%(autonumber)03d - %(title)s.%(ext)s", url])
        else:
            command.extend(["-o", "%(playlist_title,uploader)s/%(title)s.%(ext)s", url])

        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        current_file = 0
        for line in process.stdout:
            line_str = line.strip()
            if "[download] Downloading item" in line_str:
                current_file += 1
                self.queue_label.configure(text=f"Downloading: {current_file} of {total_files}")
            match = re.search(r"(\d+\.?\d*)%", line_str)
            if match: 
                pct = float(match.group(1))
                self.progress.set(pct / 100)
                self.progress_label.configure(text=f"{int(pct)}%")
            
            # Log any errors or warnings during download
            if "error" in line_str.lower() or "warning" in line_str.lower():
                self.log(line_str)
        
        process.wait()
        if process.returncode != 0:
            self.queue_label.configure(text="Queue: Error")
            self.log(f"Download failed with exit code {process.returncode}.", is_error=True)
        else:
            self.progress.set(1)
            self.progress_label.configure(text="100%")
            self.queue_label.configure(text="Queue: Finished")
            self.log("All downloads complete!")
            if self.open_folder_switch.get():
                try:
                    os.startfile(folder)
                except Exception as e:
                    self.log(f"Could not open directory: {e}", is_error=True)
        
        self.after(0, self.reset_download_button)

if __name__ == "__main__":
    app = DownloaderApp()
    app.mainloop()