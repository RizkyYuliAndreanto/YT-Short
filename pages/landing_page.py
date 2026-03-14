"""
Landing Page - Card-based mode selection
Shows 4 main modes: YouTube Clipper, AI Dubbing Studio, Multi-Clip Compiler, Shopping Video Creator
"""

import customtkinter as ctk
from PIL import Image
from pathlib import Path
from components.ui_theme import Colors


class LandingPage(ctk.CTkFrame):
    """Landing page with 4 mode cards"""
    
    def __init__(self, parent, app, config):
        super().__init__(parent)
        self.app = app
        self.config = config
        
        self.create_ui()
    
    def create_ui(self):
        """Create the landing page UI"""
        self.configure(fg_color=Colors.BG_PRIMARY)
        
        # Header
        self.create_header()
        
        # Main content - centered cards
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=40, pady=20)
        
        # Center container
        center_container = ctk.CTkFrame(main_frame, fg_color="transparent")
        center_container.place(relx=0.5, rely=0.45, anchor="center")
        
        # Tagline
        ctk.CTkLabel(center_container, text="What would you like to create today?",
            font=ctk.CTkFont(size=18), text_color="gray").pack(pady=(0, 30))
        
        # Cards grid (2x2)
        cards_frame = ctk.CTkFrame(center_container, fg_color="transparent")
        cards_frame.pack()
        
        # Row 1
        row1 = ctk.CTkFrame(cards_frame, fg_color="transparent")
        row1.pack(pady=(0, 15))
        
        # Card 1: YouTube Clipper
        self.create_mode_card(row1, 
            icon="🎬",
            title="YouTube Clipper",
            description="Turn long YouTube videos into viral shorts.\nAI finds the best highlights automatically.",
            color=("#e74c3c", "#c0392b"),
            command=lambda: self.app.show_page("home"),
            side="left"
        )
        
        # Card 2: AI Dubbing Studio
        self.create_mode_card(row1,
            icon="🎤",
            title="AI Dubbing Studio",
            description="Upload any video → AI generates script →\nEdge TTS creates natural voiceover.",
            color=("#3498db", "#2980b9"),
            command=lambda: self.app.show_page("dubbing_studio"),
            side="left",
            badge="NEW"
        )
        
        # Row 2
        row2 = ctk.CTkFrame(cards_frame, fg_color="transparent")
        row2.pack()
        
        # Card 3: Multi-Clip Compiler
        self.create_mode_card(row2,
            icon="🎞️",
            title="Multi-Clip Compiler",
            description="Combine 1-10 clips into one video.\nAI creates unified voiceover script.",
            color=("#9b59b6", "#8e44ad"),
            command=lambda: self.show_coming_soon("Multi-Clip Compiler"),
            side="left",
            badge="SOON"
        )
        
        # Card 4: Shopping Video Creator
        self.create_mode_card(row2,
            icon="🛒",
            title="Shopping Video",
            description="Create selling videos for TikTok Shop.\nAI writes persuasive sales script.",
            color=("#e67e22", "#d35400"),
            command=lambda: self.show_coming_soon("Shopping Video Creator"),
            side="left",
            badge="SOON"
        )
        
        # Footer
        self.create_footer()
    
    def create_header(self):
        """Create header with logo"""
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=40, pady=(30, 10))
        
        # Logo and title
        left_header = ctk.CTkFrame(header, fg_color="transparent")
        left_header.pack(side="left")
        
        # Try to load icon
        try:
            from utils.helpers import get_bundle_dir
            BUNDLE_DIR = get_bundle_dir()
            ASSETS_DIR = BUNDLE_DIR / "assets"
            ICON_PATH = ASSETS_DIR / "icon.png"
            
            if ICON_PATH.exists():
                icon_img = Image.open(ICON_PATH)
                icon_img.thumbnail((48, 48), Image.Resampling.LANCZOS)
                header_icon = ctk.CTkImage(light_image=icon_img, dark_image=icon_img, size=(48, 48))
                ctk.CTkLabel(left_header, image=header_icon, text="").pack(side="left", padx=(0, 15))
                self._header_icon = header_icon
        except:
            # Fallback emoji
            ctk.CTkLabel(left_header, text="🎬", font=ctk.CTkFont(size=36)).pack(side="left", padx=(0, 15))
        
        title_frame = ctk.CTkFrame(left_header, fg_color="transparent")
        title_frame.pack(side="left")
        
        ctk.CTkLabel(title_frame, text="CONTEN CREATOR AGENT", 
            font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(title_frame, text="AI-Powered Content Operating System",
            font=ctk.CTkFont(size=12), text_color="gray").pack(anchor="w")
        
        # Right side - Settings button
        right_header = ctk.CTkFrame(header, fg_color="transparent")
        right_header.pack(side="right")
        
        ctk.CTkButton(right_header, text="⚙️ Settings", width=100, height=36,
            fg_color=("gray70", "gray30"), hover_color=("gray60", "gray25"),
            command=lambda: self.app.show_page("settings")).pack(side="right")
        
        ctk.CTkButton(right_header, text="📊 API Status", width=100, height=36,
            fg_color=("gray70", "gray30"), hover_color=("gray60", "gray25"),
            command=lambda: self.app.show_page("api_status")).pack(side="right", padx=(0, 10))
    
    def create_mode_card(self, parent, icon, title, description, color, command, side="left", badge=None):
        """Create a mode selection card"""
        # Card container
        card = ctk.CTkFrame(parent, width=280, height=180, 
            fg_color=("gray85", "gray20"), corner_radius=15, cursor="hand2")
        card.pack(side=side, padx=10)
        card.pack_propagate(False)
        
        # Hover effects
        def on_enter(e):
            card.configure(fg_color=color)
        
        def on_leave(e):
            card.configure(fg_color=("gray85", "gray20"))
        
        card.bind("<Enter>", on_enter)
        card.bind("<Leave>", on_leave)
        card.bind("<Button-1>", lambda e: command())
        
        # Content
        content = ctk.CTkFrame(card, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=20, pady=15)
        content.bind("<Button-1>", lambda e: command())
        
        # Header row: icon + badge
        header_row = ctk.CTkFrame(content, fg_color="transparent")
        header_row.pack(fill="x")
        header_row.bind("<Button-1>", lambda e: command())
        
        # Icon
        icon_label = ctk.CTkLabel(header_row, text=icon, font=ctk.CTkFont(size=32))
        icon_label.pack(side="left")
        icon_label.bind("<Button-1>", lambda e: command())
        
        # Badge
        if badge:
            badge_color = "#27ae60" if badge == "NEW" else "#7f8c8d"
            badge_label = ctk.CTkLabel(header_row, text=badge, 
                font=ctk.CTkFont(size=9, weight="bold"),
                fg_color=badge_color, corner_radius=4,
                width=40, height=18)
            badge_label.pack(side="right")
            badge_label.bind("<Button-1>", lambda e: command())
        
        # Title
        title_label = ctk.CTkLabel(content, text=title, 
            font=ctk.CTkFont(size=16, weight="bold"), anchor="w")
        title_label.pack(fill="x", pady=(10, 5))
        title_label.bind("<Button-1>", lambda e: command())
        
        # Description
        desc_label = ctk.CTkLabel(content, text=description,
            font=ctk.CTkFont(size=11), text_color="gray",
            anchor="w", justify="left")
        desc_label.pack(fill="x")
        desc_label.bind("<Button-1>", lambda e: command())
    
    def create_footer(self):
        """Create footer"""
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=40, pady=(10, 20), side="bottom")
        
        # Links
        links_frame = ctk.CTkFrame(footer, fg_color="transparent")
        links_frame.pack()
        
        # Browse Videos
        browse_btn = ctk.CTkButton(links_frame, text="📂 Browse Videos", width=110, height=28,
            fg_color="transparent", hover_color=("gray75", "gray25"),
            font=ctk.CTkFont(size=11), command=lambda: self.app.show_page("browse"))
        browse_btn.pack(side="left", padx=5)

        if hasattr(self.app, "toggle_theme_mode"):
            mode_text = "Dark Mode" if str(getattr(self.app, "get_theme_mode", lambda: "light")()).lower().startswith("light") else "Light Mode"
            mode_btn = ctk.CTkButton(links_frame, text=f"🌓 {mode_text}", width=120, height=28,
                fg_color="transparent", hover_color=("gray75", "gray25"),
                font=ctk.CTkFont(size=11), command=self.app.toggle_theme_mode)
            mode_btn.pack(side="left", padx=5)
        
        # Version
        try:
            from version import __version__
            version_text = f"v{__version__}"
        except:
            version_text = "v0.0.1"
        
        ctk.CTkLabel(footer, text=version_text, font=ctk.CTkFont(size=10), 
            text_color="gray").pack(pady=(10, 0))
    
    def show_coming_soon(self, feature_name):
        """Show coming soon message"""
        from tkinter import messagebox
        messagebox.showinfo("Coming Soon", 
            f"🚧 {feature_name} is coming soon!\n\n"
            f"This feature is currently under development.\n"
            f"Stay tuned for updates!")
    
    def open_discord(self):
        """Open Discord"""
        import webbrowser
        webbrowser.open("https://s.id/ytsdiscord")
    
    def open_github(self):
        """Open GitHub"""
        import webbrowser
        webbrowser.open("https://github.com/jipraks/yt-short-clipper")
