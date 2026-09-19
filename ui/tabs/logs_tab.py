"""
Console Logs Tab Mixin for Shallot Media Archive.
Manages the application console status box, copy, clear, and persistent error logging.
"""

import os
import sys
import customtkinter as ctk


class LogsTabMixin:
    """Provides console logs UI construction and log management methods."""

    def build_logs_page(self, parent):
        """Constructs the Console Logs tab page."""
        self.logs_page = ctk.CTkFrame(parent, fg_color="transparent")

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
        return self.logs_page

    def clear_logs(self):
        """Clears all console logs."""
        if hasattr(self, "status_box"):
            self.status_box.delete("1.0", "end")

    def copy_logs(self):
        """Copies all console logs to clipboard."""
        try:
            if hasattr(self, "status_box"):
                content = self.status_box.get("1.0", "end").strip()
                if content:
                    self.clipboard_clear()
                    self.clipboard_append(content)
                    self.btn_copy_logs.configure(text="Copied! ✓")
                    self.after(2000, lambda: self.btn_copy_logs.configure(text="📋 Copy Logs"))
        except Exception as e:
            self.log(f"Copy logs error: {e}", is_error=True)

    def log(self, message, is_error=False):
        """Appends a timestamped or formatted message to the UI status box and persistent error log."""
        if not hasattr(self, "status_box"):
            return

        # Filter benign routine fallback warnings
        if "web_creator client https formats require a GVS PO Token" in message:
            return

        if "The provided YouTube account cookies are no longer valid" in message:
            if getattr(self, "_cookie_warning_shown", False):
                return
            self._cookie_warning_shown = True
            message = "⚠️ [Notice] Your YouTube cookies have expired or rotated. Age-restricted and members-only videos will be skipped until fresh cookies are provided."

        # RAM optimization: auto-prune oldest log lines when exceeding 1500 lines
        try:
            num_lines = int(self.status_box.index("end-1c").split(".")[0])
            if num_lines > 1500:
                self.status_box.delete("1.0", f"{num_lines - 1200}.0")
        except Exception:
            pass

        self.status_box.insert("end", message + "\n")
        self.status_box.see("end")

        # Check for signature solving / JavaScript runtime errors
        if (
            "signature solving failed" in message.lower()
            or "javascript runtime" in message.lower()
            or "n challenge solving failed" in message.lower()
        ):
            tip_msg = (
                "\n💡 [HELP] YouTube now requires an external JavaScript runtime to download videos.\n"
                "👉 To fix this on Windows:\n"
                "1. Open PowerShell and run: winget install DenoLand.Deno\n"
                "2. OR place 'deno.exe' in the folder next to this app.\n"
                "3. Then restart the application."
            )
            current_content = self.status_box.get("1.0", "end")
            if "[HELP] YouTube now requires" not in current_content:
                self.status_box.insert("end", tip_msg + "\n")
                self.status_box.see("end")

        if is_error or "error" in message.lower() or "fatal" in message.lower():
            try:
                from datetime import datetime

                exe_dir = (
                    os.path.dirname(sys.executable)
                    if getattr(sys, "frozen", False)
                    else os.path.dirname(os.path.abspath(__file__))
                )
                log_file = os.path.join(exe_dir, "downloader_errors.txt")
                with open(log_file, "a", encoding="utf-8") as f:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    f.write(f"[{timestamp}] {message}\n")
            except Exception:
                pass
