import customtkinter as ctk
import pystray
from PIL import Image
import threading
import sys
import os

class TestApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Test Tray App")
        self.geometry("300x200")
        
        self.label = ctk.CTkLabel(self, text="Minimize me to test tray!")
        self.label.pack(pady=40)
        
        # Setup tray icon
        self.tray_icon = None
        self.setup_tray()
        
        # Bind minimize event
        self.bind("<Unmap>", self.on_minimize)
        
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def setup_tray(self):
        # Create a simple red image if icon doesn't exist
        image = Image.new('RGB', (64, 64), color='red')
        
        menu = pystray.Menu(
            pystray.MenuItem("Show Window", self.show_window, default=True),
            pystray.MenuItem("Exit", self.exit_app)
        )
        
        self.tray_icon = pystray.Icon("TestTray", image, "Test Tray App", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def on_minimize(self, event):
        # We only withdraw if the window state is iconic (minimized)
        if self.state() == "iconic":
            self.withdraw()

    def show_window(self, icon=None, item=None):
        self.deiconify()
        self.state("normal")
        self.focus_force()

    def exit_app(self, icon=None, item=None):
        if self.tray_icon:
            self.tray_icon.stop()
        self.destroy()
        sys.exit(0)

    def on_close(self):
        self.exit_app()

if __name__ == "__main__":
    app = TestApp()
    app.mainloop()
