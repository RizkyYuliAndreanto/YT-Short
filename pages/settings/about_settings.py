"""
About Settings Sub-Page
"""

import webbrowser
import customtkinter as ctk
from components.ui_theme import Colors, Fonts

from pages.settings.base_dialog import BaseSettingsSubPage
from version import __version__


class AboutSettingsSubPage(BaseSettingsSubPage):
    """Sub-page showing app information and updates"""
    
    def __init__(self, parent, config, check_update_callback, on_back_callback):
        self.config = config
        self.check_update = check_update_callback
        
        super().__init__(parent, "About", on_back_callback)
        
        self.create_content()
    
    def create_content(self):
        """Create page content"""
        # App info section
        info_frame = ctk.CTkFrame(self.content, fg_color="transparent")
        info_frame.pack(fill="x", pady=(0, 15))
        
        ctk.CTkLabel(info_frame, text="CONTEN CREATOR AGENT", 
            font=Fonts.heading_lg(), text_color=Colors.TEXT_PRIMARY).pack()
        ctk.CTkLabel(info_frame, text=f"v{__version__}", 
            font=Fonts.body_sm(), text_color=Colors.TEXT_MUTED).pack(pady=(5, 0))
        
        # Check for updates button
        if self.check_update:
            ctk.CTkButton(info_frame, text="Check for Updates", height=35, width=150,
                fg_color=Colors.BG_TERTIARY, hover_color=Colors.CARD_HOVER,
                border_width=1, border_color=Colors.BORDER,
                command=self.check_update).pack(pady=(10, 0))
        
        # Description
        desc_frame = ctk.CTkFrame(self.content, fg_color=Colors.CARD_BG, corner_radius=10,
                      border_width=1, border_color=Colors.BORDER)
        desc_frame.pack(fill="x", pady=(0, 15))
        
        desc_text = """Automated YouTube to Short-Form Content Pipeline

Transform long-form YouTube videos into engaging 
short-form content for TikTok, Instagram Reels, 
and YouTube Shorts."""
        
        ctk.CTkLabel(desc_frame, text=desc_text, justify="center", 
            font=Fonts.body_sm(), text_color=Colors.TEXT_SECONDARY, wraplength=380).pack(padx=15, pady=15)
        
        # Credits
        credits_frame = ctk.CTkFrame(self.content, fg_color="transparent")
        credits_frame.pack(fill="x", pady=(0, 15))
        
        ctk.CTkLabel(credits_frame, text="Made with coffee by", 
            font=Fonts.body_sm(), text_color=Colors.TEXT_MUTED).pack()
        ctk.CTkLabel(credits_frame, text="Aji Prakoso", 
            font=Fonts.heading_sm(), text_color=Colors.TEXT_PRIMARY).pack(pady=(5, 0))
        
        # Links
        links_frame = ctk.CTkFrame(self.content, fg_color="transparent")
        links_frame.pack(fill="x", pady=(0, 15))
        
        ctk.CTkButton(links_frame, text="@jipraks on Instagram", height=40,
            fg_color=("#E4405F", "#C13584"), hover_color=("#F56040", "#E1306C"),
            command=lambda: webbrowser.open("https://instagram.com/jipraks")).pack(fill="x", pady=2)
        
        ctk.CTkButton(links_frame, text="YouTube Channel", height=40,
            fg_color=("#c4302b", "#FF0000"), hover_color=("#ff0000", "#CC0000"),
            command=lambda: webbrowser.open("https://youtube.com/@jipraks")).pack(fill="x", pady=2)
        
        # Footer
        footer_frame = ctk.CTkFrame(self.content, fg_color="transparent")
        footer_frame.pack(side="bottom", fill="x", pady=(10, 0))
        
        ctk.CTkLabel(footer_frame, text="Licensed under MIT", 
            font=Fonts.caption(), text_color=Colors.TEXT_MUTED).pack()
