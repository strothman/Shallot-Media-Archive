"""
Spotify to Plexamp Tab Mixin for Shallot Media Archive.
Handles Spotify playlist/album/track metadata fetching, selection,
and synchronous/asynchronous Plexamp library pipeline conversion.
"""

import os
import sys
import threading
import ssl
import urllib.request
import io
from PIL import Image
import customtkinter as ctk

from core import CToolTip
from spotify_sync import SpotifyFetcher, SpotifyAuthHelper, SpotifyPlexampPipeline


class SpotifyTabMixin:
    """Mixin containing GUI layout and controller methods for Spotify to Plexamp tab."""

    def build_spotify_page(self, parent):
        # --- Page 3: Spotify to Plexamp Page ---
        # =========================================================================
        self.spotify_page = ctk.CTkFrame(parent, fg_color="transparent")

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
        self.spotify_url_input.bind("<Return>", lambda e: self._on_spotify_input_return())
        self.theme_entries.append(self.spotify_url_input)
        CToolTip(self.spotify_url_input, "Paste any Spotify track, album, or playlist URL. Auto-syncs and organizes into your Plexamp library.")

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
        CToolTip(self.btn_spotify_paste, "Paste Spotify URL from clipboard (Auto-routes YouTube links to YouTube-to-Plexamp)")

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
        CToolTip(self.spotify_folder_input, "Root directory of your Plexamp/Plex music library (e.g. C:\\SMA-downloads\\Music).")

        self.btn_spotify_browse = ctk.CTkButton(fld_row, text="📂", width=32, height=28, font=("Segoe UI", 10, "bold"), command=self.browse_plex_folder)
        self.btn_spotify_browse.pack(side="right")
        self.theme_buttons_secondary.append(self.btn_spotify_browse)
        CToolTip(self.btn_spotify_browse, "Browse and select Plexamp music library folder")

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

    def _on_spotify_input_return(self):
        text = self.spotify_url_input.get().strip()
        if text:
            if not self.dispatch_smart_input(text, source_tab="spotify"):
                self.fetch_spotify_playlist()

    def paste_spotify_url(self):
        """ Pastes clipboard contents into the Spotify URL input and triggers fetch """
        try:
            clipboard_text = self.clipboard_get().strip()
            if clipboard_text:
                if self.dispatch_smart_input(clipboard_text, source_tab="spotify"):
                    return
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
        cid = getattr(self, "spotify_cid_entry", None)
        csec = getattr(self, "spotify_csec_entry", None)
        cid_val = cid.get().strip() if cid else self.saved_settings.get("spotify_client_id", "")
        csec_val = csec.get().strip() if csec else self.saved_settings.get("spotify_client_secret", "")
        if not cid_val or not csec_val:
            if hasattr(self, "lbl_spotify_auth_status"):
                self.lbl_spotify_auth_status.configure(text="Please enter Client ID & Secret first", text_color="#FB7185")
            return

        self.save_setting("spotify_client_id", cid_val)
        self.save_setting("spotify_client_secret", csec_val)
        if hasattr(self, "btn_spotify_auth"):
            self.btn_spotify_auth.configure(state="disabled", text="Connecting in Browser... ⏳")
        if hasattr(self, "lbl_spotify_auth_status"):
            self.lbl_spotify_auth_status.configure(text="Waiting for browser approval...", text_color="#38BDF8")

        def on_done(refresh_tok, error):
            if refresh_tok:
                self.save_setting("spotify_refresh_token", refresh_tok)
                if hasattr(self, "lbl_spotify_auth_status"):
                    self.after(0, lambda: self.lbl_spotify_auth_status.configure(text="✓ Spotify Connected (All 700+ Songs Unlocked)", text_color="#4ADE80"))
                if hasattr(self, "btn_spotify_auth"):
                    self.after(0, lambda: self.btn_spotify_auth.configure(state="normal", text="✓ Re-Authorize Account"))
                self.log("SUCCESS: Spotify Account authorized! Unlimited playlist size unlocked.")
                if self.spotify_url_input.get().strip():
                    self.after(500, self.fetch_spotify_playlist)
            else:
                if hasattr(self, "lbl_spotify_auth_status"):
                    self.after(0, lambda: self.lbl_spotify_auth_status.configure(text=f"Auth Error: {str(error)[:40]}", text_color="#FB7185"))
                if hasattr(self, "btn_spotify_auth"):
                    self.after(0, lambda: self.btn_spotify_auth.configure(state="normal", text="🔗 Connect Spotify"))
                self.log(f"Spotify auth failed: {error}", is_error=True)

        SpotifyAuthHelper.authorize_in_browser(cid_val, csec_val, on_done)

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
