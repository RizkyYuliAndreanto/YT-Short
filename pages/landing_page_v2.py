"""
Landing Page - Modern card-based mode selection
Complete redesign with Midnight Professional theme
"""

import customtkinter as ctk
from PIL import Image
from pathlib import Path
import webbrowser

# Import theme
from components.ui_theme import (
    Colors, Fonts, Spacing, BorderRadius, 
    ToolTip, create_styled_button, create_styled_label
)


class LandingPage(ctk.CTkFrame):
    """Landing page with 4 mode cards - Complete redesign"""
    
    def __init__(self, parent, app, config):
        super().__init__(parent, fg_color=Colors.BG_PRIMARY)
        self.app = app
        self.config = config
        
        self.create_ui()
    
    def create_ui(self):
        """Create the landing page UI"""
        
        # Main container with gradient effect
        main_container = ctk.CTkFrame(self, fg_color=Colors.BG_PRIMARY)
        main_container.pack(fill="both", expand=True)
        
        # Header section
        self._create_header(main_container)
        
        # Tagline
        tagline_frame = ctk.CTkFrame(main_container, fg_color="transparent")
        tagline_frame.pack(pady=(0, Spacing.LG))
        
        create_styled_label(tagline_frame, "What would you like to create today?",
            style="heading_md", color=Colors.TEXT_SECONDARY).pack()
        
        # Cards container - centered
        cards_container = ctk.CTkFrame(main_container, fg_color="transparent")
        cards_container.pack(expand=True, fill="both", padx=Spacing.XL)
        
        # Center the cards
        cards_center = ctk.CTkFrame(cards_container, fg_color="transparent")
        cards_center.place(relx=0.5, rely=0.45, anchor="center")
        
        # Cards grid (2x2)
        self._create_cards_grid(cards_center)
        
        # Footer
        self._create_footer(main_container)
    
    def _create_header(self, parent):
        """Create header with logo and settings"""
        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.XL, pady=(Spacing.LG, Spacing.MD))
        
        # Left side: Logo and title
        left = ctk.CTkFrame(header, fg_color="transparent")
        left.pack(side="left")
        
        # Try to load icon
        self._load_logo(left)
        
        title_frame = ctk.CTkFrame(left, fg_color="transparent")
        title_frame.pack(side="left")
        
        create_styled_label(title_frame, "CONTEN CREATOR AGENT", style="heading_lg").pack(anchor="w")
        create_styled_label(title_frame, "AI-Powered Content Operating System", 
            style="muted").pack(anchor="w")
        
        # Right side: Action buttons
        right = ctk.CTkFrame(header, fg_color="transparent")
        right.pack(side="right")
        
        # API Status button
        api_btn = create_styled_button(right, "API Status", 
            command=lambda: self.app.show_page("api_status"),
            style="ghost", width=100, height=32,
            tooltip="Check API connection status for all AI services",
            icon="📊")
        api_btn.pack(side="left", padx=(0, Spacing.SM))
        
        # Settings button
        settings_btn = create_styled_button(right, "Settings",
            command=lambda: self.app.show_page("settings"),
            style="secondary", width=100, height=32,
            tooltip="Configure API keys, output settings, and preferences",
            icon="⚙️")
        settings_btn.pack(side="left")

        if hasattr(self.app, "toggle_theme_mode"):
            mode_text = "Dark" if str(getattr(self.app, "get_theme_mode", lambda: "light")()).lower().startswith("light") else "Light"
            theme_btn = create_styled_button(right, f"{mode_text} Mode",
                command=self.app.toggle_theme_mode,
                style="ghost", width=110, height=32,
                tooltip="Switch between bright and dark interface",
                icon="🌓")
            theme_btn.pack(side="left", padx=(Spacing.SM, 0))
    
    def _load_logo(self, parent):
        """Load and display app logo"""
        try:
            from utils.helpers import get_bundle_dir
            BUNDLE_DIR = get_bundle_dir()
            ICON_PATH = BUNDLE_DIR / "assets" / "icon.png"
            
            if ICON_PATH.exists():
                icon_img = Image.open(ICON_PATH)
                icon_img.thumbnail((52, 52), Image.Resampling.LANCZOS)
                self._logo = ctk.CTkImage(light_image=icon_img, dark_image=icon_img, size=(52, 52))
                ctk.CTkLabel(parent, image=self._logo, text="").pack(side="left", padx=(0, Spacing.MD))
        except Exception:
            # Fallback: emoji logo
            ctk.CTkLabel(parent, text="🎬", font=ctk.CTkFont(size=40)).pack(side="left", padx=(0, Spacing.MD))
    
    def _create_cards_grid(self, parent):
        """Create the 2x3 grid of mode cards"""

        # Row 1
        row1 = ctk.CTkFrame(parent, fg_color="transparent")
        row1.pack(pady=(0, Spacing.MD))

        # Card 1: YouTube Clipper
        self._create_mode_card(row1,
            icon="✂️",
            title="YouTube Clipper",
            description="Extract viral highlights from long YouTube videos.\nAI automatically finds the best moments.",
            accent_color=Colors.ERROR,  # Coral
            command=lambda: self.app.show_page("home"),
            tooltip="Convert long YouTube videos into short-form content (TikTok, Reels, Shorts)",
            badge=None
        )

        # Card 2: AI Dubbing Studio
        self._create_mode_card(row1,
            icon="🎙️",
            title="AI Dubbing Studio",
            description="Upload video → AI generates script →\nEdge TTS creates natural Indonesian voiceover.",
            accent_color=Colors.ACCENT_PRIMARY,  # Electric blue
            command=lambda: self.app.show_page("dubbing_studio"),
            tooltip="Create AI-powered voiceovers using free Edge TTS with Indonesian support",
            badge=None
        )

        # Row 2
        row2 = ctk.CTkFrame(parent, fg_color="transparent")
        row2.pack(pady=(0, Spacing.MD))

        # Card 3: Clip+Dub Studio
        self._create_mode_card(row2,
            icon="🎬",
            title="Clip + Dub Studio",
            description="Clip video panjang → AI script →\nDubbing otomatis jadi Shorts 1-2 menit.",
            accent_color=Colors.ACCENT_SECONDARY,  # Purple
            command=lambda: self.app.show_page("clip_dub"),
            tooltip="Gabungkan clipping + dubbing: input URL → AI pilih momen → script → TTS → Shorts",
            badge=None
        )

        # Card 4: Clip Cutter
        self._create_mode_card(row2,
            icon="",
            title="Clip Cutter",
            description="Download clips from YouTube, TikTok,\nInstagram, Facebook. Remove watermarks.",
            accent_color=Colors.INFO,  # Cyan
            command=lambda: self.app.show_page("clip_cutter"),
            tooltip="Download video segments from multiple platforms with partial download & watermark removal",
            badge=None
        )

        # Row 3
        row3 = ctk.CTkFrame(parent, fg_color="transparent")
        row3.pack()

        # Card 5: TTS Maker
        self._create_mode_card(row3,
            icon="🔊",
            title="Text-to-Speech Maker",
            description="Ubah teks menjadi audio dubbing natural.\nOptimasi suara agar tidak terdeteksi robotik.",
            accent_color=Colors.SUCCESS,  # Green
            command=lambda: self.app.show_page("tts_maker"),
            tooltip="Generate audio dubbing dari teks untuk konten Shorts. Suara natural dengan enhancement.",
            badge=None
        )

        # Card 6: Auto Caption
        self._create_mode_card(row3,
            icon="CC",
            title="Auto Caption",
            description="Tambahkan subtitle ke video yang sudah ada.\nAudio asli tetap, hanya tambah caption.",
            accent_color=Colors.WARNING,  # Orange/Yellow
            command=lambda: self.app.show_page("auto_caption"),
            tooltip="Extract audio → Transcribe dengan Whisper → Edit script → Burn caption ke video",
            badge="NEW"
        )
    
    def _create_mode_card(self, parent, icon, title, description, accent_color, 
                          command, tooltip=None, badge=None):
        """Create a modern mode selection card"""
        
        # Card outer container
        card = ctk.CTkFrame(parent, width=290, height=170, 
            fg_color=Colors.CARD_BG, corner_radius=BorderRadius.LG,
            border_width=2, border_color=Colors.BORDER)
        card.pack(side="left", padx=Spacing.SM)
        card.pack_propagate(False)
        
        # Store original colors for hover
        card._original_border = Colors.BORDER
        card._accent = accent_color
        
        # Hover effects
        def on_enter(e):
            card.configure(border_color=accent_color, fg_color=Colors.CARD_HOVER)
        
        def on_leave(e):
            card.configure(border_color=Colors.BORDER, fg_color=Colors.CARD_BG)
        
        def on_click(e):
            command()
        
        # Bind events to card and all children
        for widget in [card]:
            widget.bind("<Enter>", on_enter)
            widget.bind("<Leave>", on_leave)
            widget.bind("<Button-1>", on_click)
        
        # Card content
        content = ctk.CTkFrame(card, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=Spacing.MD, pady=Spacing.MD)
        content.bind("<Enter>", on_enter)
        content.bind("<Leave>", on_leave)
        content.bind("<Button-1>", on_click)
        
        # Header row: Icon + Badge
        header_row = ctk.CTkFrame(content, fg_color="transparent")
        header_row.pack(fill="x")
        header_row.bind("<Button-1>", on_click)
        
        # Icon with accent background
        icon_frame = ctk.CTkFrame(header_row, width=44, height=44, 
            fg_color=accent_color, corner_radius=BorderRadius.MD)
        icon_frame.pack(side="left")
        icon_frame.pack_propagate(False)
        icon_frame.bind("<Button-1>", on_click)
        
        icon_label = ctk.CTkLabel(icon_frame, text=icon, font=ctk.CTkFont(size=22),
            text_color=Colors.TEXT_PRIMARY)
        icon_label.place(relx=0.5, rely=0.5, anchor="center")
        icon_label.bind("<Button-1>", on_click)
        
        # Badge
        if badge:
            badge_color = Colors.SUCCESS if badge == "NEW" else Colors.TEXT_MUTED
            badge_frame = ctk.CTkFrame(header_row, fg_color=badge_color, 
                corner_radius=BorderRadius.SM, height=22)
            badge_frame.pack(side="right")
            
            badge_label = ctk.CTkLabel(badge_frame, text=badge, 
                font=ctk.CTkFont(size=9, weight="bold"),
                text_color=Colors.BG_PRIMARY if badge == "NEW" else Colors.TEXT_PRIMARY,
                padx=8, pady=2)
            badge_label.pack()
            badge_frame.bind("<Button-1>", on_click)
            badge_label.bind("<Button-1>", on_click)
        
        # Title
        title_label = ctk.CTkLabel(content, text=title, font=Fonts.heading_sm(),
            text_color=Colors.TEXT_PRIMARY, anchor="w")
        title_label.pack(fill="x", pady=(Spacing.SM, Spacing.XS))
        title_label.bind("<Button-1>", on_click)
        
        # Description
        desc_label = ctk.CTkLabel(content, text=description, font=Fonts.body_sm(),
            text_color=Colors.TEXT_SECONDARY, anchor="w", justify="left")
        desc_label.pack(fill="x")
        desc_label.bind("<Button-1>", on_click)
        
        # Tooltip for the whole card
        if tooltip:
            ToolTip(card, tooltip)
        
        return card
    
    def _create_footer(self, parent):
        """Create footer with links and version"""
        footer = ctk.CTkFrame(parent, fg_color="transparent")
        footer.pack(fill="x", side="bottom", padx=Spacing.XL, pady=Spacing.MD)
        
        # Links row
        links_frame = ctk.CTkFrame(footer, fg_color="transparent")
        links_frame.pack()

        if hasattr(self.app, "toggle_theme_mode"):
            mode_text = "Dark" if str(getattr(self.app, "get_theme_mode", lambda: "light")()).lower().startswith("light") else "Light"
            mode_btn = create_styled_button(links_frame, f"{mode_text} Mode",
                command=self.app.toggle_theme_mode,
                style="ghost", width=120, height=28,
                tooltip="Toggle application appearance mode",
                icon="🌓")
            mode_btn.pack(side="left", padx=Spacing.XS)
        
        # Browse Videos
        browse_btn = create_styled_button(links_frame, "Browse Videos",
            command=lambda: self.app.show_page("browse"),
            style="ghost", width=120, height=28,
            tooltip="Browse previously generated clips and sessions",
            icon="📂")
        browse_btn.pack(side="left", padx=Spacing.XS)
        
        # Version
        try:
            from version import __version__
            version_text = f"v{__version__}"
        except:
            version_text = "v0.0.1"
        
        create_styled_label(footer, version_text, style="caption").pack(pady=(Spacing.SM, 0))
    
    def _show_coming_soon(self, feature_name):
        """Show coming soon popup"""
        from tkinter import messagebox
        messagebox.showinfo("Coming Soon 🚀",
            f"{feature_name} is under development!\n\n"
            f"This feature will be available in a future update.\n"
            f"Stay tuned for upcoming releases!")
    
    # Navigation methods for compatibility
    def show_page(self, page_name):
        """Delegate to main app"""
        self.app.show_page(page_name)
