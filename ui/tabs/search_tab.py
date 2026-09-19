"""
YouTube Search Tab Mixin for Shallot Media Archive.
Manages search input, parallel search execution, thumbnail downloading,
grid rendering, and selection routing to the download tab.
"""

from concurrent.futures import ThreadPoolExecutor
import json
import os
import ssl
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
import customtkinter as ctk
from PIL import Image


class SearchTabMixin:
    """Provides YouTube search UI and controller methods."""

    def build_search_page(self, parent):
        """Constructs the Search YouTube tab page."""
        self.search_page = ctk.CTkFrame(parent, fg_color="transparent")

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
        return self.search_page

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

                res_v = subprocess.run(cmd_videos, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                res_p = subprocess.run(cmd_playlists, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

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

                temp_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))

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
        border_col = getattr(self, "theme_cfg", {}).get("border", "#1F3A4E")
        input_bg = getattr(self, "theme_cfg", {}).get("input_bg", "#070F15")

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
                img = Image.new("RGB", (160, 90), color="#1E1A24")

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
                return lambda e: card.configure(border_color=getattr(self, "theme_cfg", {}).get("accent", "#00E5FF"))

            def make_leave_handler(card=result_card):
                return lambda e: card.configure(
                    border_color=getattr(self, "theme_cfg", {}).get("accent", "#00E5FF")
                    if card == self.selected_search_card
                    else getattr(self, "theme_cfg", {}).get("border", "#1F3A4E")
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
        accent = getattr(self, "theme_cfg", {}).get("accent", "#00E5FF")
        border = getattr(self, "theme_cfg", {}).get("border", "#1F3A4E")

        for card, card_url in self.search_result_widgets:
            if card == selected_card:
                card.configure(border_color=accent, border_width=2)
            else:
                card.configure(border_color=border, border_width=1)

        threading.Thread(target=self.fetch_and_display_avatar, args=(url,), daemon=True).start()
        self.after(300, lambda: self.select_tab("download"))
