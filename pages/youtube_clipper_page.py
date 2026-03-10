"""
YouTube Clipper Page - Redesigned with Midnight Professional Theme
Consistent styling with AI Dubbing Studio
"""

import customtkinter as ctk
from pathlib import Path
from tkinter import filedialog, messagebox
from PIL import Image
import threading
import os
import re

# Import theme
from components.ui_theme import (
    Colors, Fonts, Spacing, BorderRadius,
    ToolTip, create_styled_button, create_styled_card,
    create_styled_input, create_styled_label, create_section_divider
)


class YouTubeClipperPage(ctk.CTkFrame):
    """YouTube Clipper - Redesigned with consistent theme"""
    
    def __init__(self, parent, app, config):
        super().__init__(parent, fg_color=Colors.BG_PRIMARY)
        self.app = app
        self.config = config
        
        # State
        self.current_thumbnail = None
        self.subtitle_loaded = False
        self.available_subtitles = []
        
        self.create_ui()
    
    def go_back(self):
        """Navigate back to landing page"""
        self.app.show_page("landing")
    
    def create_ui(self):
        """Create the clipper UI"""
        
        # Header
        self._create_header()
        
        # Main content area with scrolling
        self.main_scroll = ctk.CTkScrollableFrame(self, fg_color="transparent",
            scrollbar_button_color=Colors.BORDER,
            scrollbar_button_hover_color=Colors.ACCENT_PRIMARY)
        self.main_scroll.pack(fill="both", expand=True, padx=Spacing.LG, pady=(0, Spacing.MD))
        
        # URL Input Section
        self._create_url_section()
        
        # Video Preview Section
        self._create_preview_section()
        
        # Settings Section
        self._create_settings_section()
        
        # Action Buttons
        self._create_action_buttons()
    
    def _create_header(self):
        """Create page header with back button"""
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.LG, pady=(Spacing.MD, Spacing.SM))
        
        # Left: Back button + Title
        left = ctk.CTkFrame(header, fg_color="transparent")
        left.pack(side="left")
        
        back_btn = create_styled_button(left, "←", 
            command=self.go_back,
            style="ghost", width=40, height=36,
            tooltip="Return to main menu")
        back_btn.pack(side="left")
        
        title_frame = ctk.CTkFrame(left, fg_color="transparent")
        title_frame.pack(side="left", padx=(Spacing.SM, 0))
        
        create_styled_label(title_frame, "YouTube Clipper", style="heading_lg").pack(anchor="w")
        create_styled_label(title_frame, "Extract viral highlights from YouTube videos", 
            style="muted").pack(anchor="w")
        
        # Right: Settings & Browse buttons
        right = ctk.CTkFrame(header, fg_color="transparent")
        right.pack(side="right")
        
        browse_btn = create_styled_button(right, "Browse",
            command=lambda: self.app.show_page("browse"),
            style="ghost", width=90, height=32,
            tooltip="Browse previously generated clips",
            icon="📂")
        browse_btn.pack(side="left", padx=(0, Spacing.SM))
        
        settings_btn = create_styled_button(right, "Settings",
            command=lambda: self.app.show_page("settings"),
            style="secondary", width=90, height=32,
            tooltip="Configure API keys and preferences",
            icon="⚙️")
        settings_btn.pack(side="left")
    
    def _create_url_section(self):
        """Create YouTube URL input section"""
        section = ctk.CTkFrame(self.main_scroll, fg_color=Colors.CARD_BG,
            corner_radius=BorderRadius.LG, border_width=1, border_color=Colors.BORDER)
        section.pack(fill="x", pady=(0, Spacing.MD))
        
        # Header
        header = ctk.CTkFrame(section, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.MD, pady=(Spacing.MD, Spacing.SM))
        
        icon_frame = ctk.CTkFrame(header, width=36, height=36,
            fg_color=Colors.ERROR, corner_radius=BorderRadius.SM)
        icon_frame.pack(side="left")
        icon_frame.pack_propagate(False)
        ctk.CTkLabel(icon_frame, text="🔗", font=ctk.CTkFont(size=18)).place(relx=0.5, rely=0.5, anchor="center")
        
        title_col = ctk.CTkFrame(header, fg_color="transparent")
        title_col.pack(side="left", padx=(Spacing.SM, 0))
        create_styled_label(title_col, "Step 1: Enter YouTube URL", style="heading_sm").pack(anchor="w")
        create_styled_label(title_col, "Paste a YouTube video link to extract highlights", style="muted").pack(anchor="w")
        
        # URL Input
        input_frame = ctk.CTkFrame(section, fg_color="transparent")
        input_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))
        
        # Use app-level variable for compatibility with processing methods
        self.url_var = self.app.url_var
        self.url_var.trace_add("write", self._on_url_change)
        
        self.url_entry = ctk.CTkEntry(input_frame, textvariable=self.url_var,
            placeholder_text="https://www.youtube.com/watch?v=...",
            fg_color=Colors.BG_SECONDARY, border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY, font=Fonts.body(),
            corner_radius=BorderRadius.SM, height=42)
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(0, Spacing.SM))
        ToolTip(self.url_entry, "Enter a valid YouTube video URL (youtube.com/watch?v=... or youtu.be/...)")
        
        paste_btn = create_styled_button(input_frame, "Paste",
            command=self._paste_url,
            style="secondary", width=80, height=42,
            tooltip="Paste URL from clipboard",
            icon="📋")
        paste_btn.pack(side="left")
        
        # URL Status indicator
        self.url_status_frame = ctk.CTkFrame(section, fg_color="transparent")
        self.url_status_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.SM))
        
        self.url_status_label = create_styled_label(self.url_status_frame, "", style="caption")
        self.url_status_label.pack(anchor="w")
    
    def _create_preview_section(self):
        """Create video preview and info section"""
        section = ctk.CTkFrame(self.main_scroll, fg_color=Colors.CARD_BG,
            corner_radius=BorderRadius.LG, border_width=1, border_color=Colors.BORDER)
        section.pack(fill="x", pady=(0, Spacing.MD))
        self.preview_section = section
        
        # Header
        header = ctk.CTkFrame(section, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.MD, pady=(Spacing.MD, Spacing.SM))
        
        icon_frame = ctk.CTkFrame(header, width=36, height=36,
            fg_color=Colors.ACCENT_PRIMARY, corner_radius=BorderRadius.SM)
        icon_frame.pack(side="left")
        icon_frame.pack_propagate(False)
        ctk.CTkLabel(icon_frame, text="🎬", font=ctk.CTkFont(size=18)).place(relx=0.5, rely=0.5, anchor="center")
        
        title_col = ctk.CTkFrame(header, fg_color="transparent")
        title_col.pack(side="left", padx=(Spacing.SM, 0))
        create_styled_label(title_col, "Video Preview", style="heading_sm").pack(anchor="w")
        create_styled_label(title_col, "Thumbnail and video information", style="muted").pack(anchor="w")
        
        # Preview content - two columns
        content = ctk.CTkFrame(section, fg_color="transparent")
        content.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))
        
        # Left: Thumbnail
        thumb_frame = ctk.CTkFrame(content, width=320, height=180,
            fg_color=Colors.BG_SECONDARY, corner_radius=BorderRadius.MD)
        thumb_frame.pack(side="left", padx=(0, Spacing.MD))
        thumb_frame.pack_propagate(False)
        self.thumb_frame = thumb_frame
        
        # Placeholder
        self.thumb_placeholder = ctk.CTkFrame(thumb_frame, fg_color="transparent")
        self.thumb_placeholder.place(relx=0.5, rely=0.5, anchor="center")
        
        ctk.CTkLabel(self.thumb_placeholder, text="🎥", font=ctk.CTkFont(size=40),
            text_color=Colors.TEXT_MUTED).pack()
        ctk.CTkLabel(self.thumb_placeholder, text="Enter URL to load preview",
            font=Fonts.caption(), text_color=Colors.TEXT_MUTED).pack()
        
        self.thumb_label = ctk.CTkLabel(thumb_frame, text="")
        
        # Right: Video info
        info_frame = ctk.CTkFrame(content, fg_color="transparent")
        info_frame.pack(side="left", fill="both", expand=True)
        
        self.video_title_label = create_styled_label(info_frame, "No video loaded", style="heading_sm")
        self.video_title_label.pack(anchor="w", pady=(0, Spacing.XS))
        
        self.video_channel_label = create_styled_label(info_frame, "", style="muted")
        self.video_channel_label.pack(anchor="w")
        
        self.video_duration_label = create_styled_label(info_frame, "", style="caption")
        self.video_duration_label.pack(anchor="w", pady=(Spacing.SM, 0))
        
        # Subtitle dropdown
        sub_frame = ctk.CTkFrame(info_frame, fg_color="transparent")
        sub_frame.pack(fill="x", pady=(Spacing.MD, 0))
        
        create_styled_label(sub_frame, "Subtitle Language:", style="caption").pack(anchor="w")
        
        # Use app-level variable for compatibility
        self.subtitle_var = self.app.subtitle_var
        # Clear variable - don't use default that doesn't exist in video
        self.subtitle_var.set("")
        self.subtitle_dropdown = ctk.CTkComboBox(sub_frame, values=["(loading...)"],
            variable=self.subtitle_var, fg_color=Colors.BG_SECONDARY,
            border_color=Colors.BORDER, button_color=Colors.ACCENT_PRIMARY,
            dropdown_fg_color=Colors.CARD_BG, font=Fonts.body_sm(),
            width=200, state="disabled")
        self.subtitle_dropdown.pack(anchor="w", pady=(4, 0))
        ToolTip(self.subtitle_dropdown, "Select subtitle language for transcript extraction")
        
        self.subtitle_status = create_styled_label(sub_frame, "", style="caption", color=Colors.TEXT_MUTED)
        self.subtitle_status.pack(anchor="w", pady=(4, 0))
    
    def _create_settings_section(self):
        """Create clip settings section"""
        section = ctk.CTkFrame(self.main_scroll, fg_color=Colors.CARD_BG,
            corner_radius=BorderRadius.LG, border_width=1, border_color=Colors.BORDER)
        section.pack(fill="x", pady=(0, Spacing.MD))
        
        # Header
        header = ctk.CTkFrame(section, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.MD, pady=(Spacing.MD, Spacing.SM))
        
        icon_frame = ctk.CTkFrame(header, width=36, height=36,
            fg_color=Colors.SUCCESS, corner_radius=BorderRadius.SM)
        icon_frame.pack(side="left")
        icon_frame.pack_propagate(False)
        ctk.CTkLabel(icon_frame, text="⚙️", font=ctk.CTkFont(size=18)).place(relx=0.5, rely=0.5, anchor="center")
        
        title_col = ctk.CTkFrame(header, fg_color="transparent")
        title_col.pack(side="left", padx=(Spacing.SM, 0))
        create_styled_label(title_col, "Step 2: Configure Settings", style="heading_sm").pack(anchor="w")
        create_styled_label(title_col, "Set clip count and processing options", style="muted").pack(anchor="w")
        
        # Settings row
        settings_row = ctk.CTkFrame(section, fg_color="transparent")
        settings_row.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))
        
        # Clip count
        clip_frame = ctk.CTkFrame(settings_row, fg_color="transparent")
        clip_frame.pack(side="left", padx=(0, Spacing.XL))
        
        create_styled_label(clip_frame, "Number of Clips:", style="caption").pack(anchor="w")
        
        clip_input_row = ctk.CTkFrame(clip_frame, fg_color="transparent")
        clip_input_row.pack(anchor="w", pady=(4, 0))
        
        # Use app-level variable for compatibility
        self.clips_var = self.app.clips_var
        self.clips_entry = ctk.CTkEntry(clip_input_row, textvariable=self.clips_var,
            width=60, height=36, fg_color=Colors.BG_SECONDARY,
            border_color=Colors.BORDER, text_color=Colors.TEXT_PRIMARY,
            font=Fonts.body(), justify="center", corner_radius=BorderRadius.SM)
        self.clips_entry.pack(side="left", padx=(0, Spacing.SM))
        ToolTip(self.clips_entry, "Number of highlight clips to extract (1-50, use higher for long live streams)")
        
        create_styled_label(clip_input_row, "(1-50)", style="caption", color=Colors.TEXT_MUTED).pack(side="left")
        
        # Processing mode
        mode_frame = ctk.CTkFrame(settings_row, fg_color="transparent")
        mode_frame.pack(side="left")
        
        create_styled_label(mode_frame, "Processing Mode:", style="caption").pack(anchor="w")
        
        self.mode_var = ctk.StringVar(value="full")
        
        mode_options = ctk.CTkFrame(mode_frame, fg_color="transparent")
        mode_options.pack(anchor="w", pady=(4, 0))
        
        full_radio = ctk.CTkRadioButton(mode_options, text="Full Auto",
            variable=self.mode_var, value="full", font=Fonts.body_sm(),
            fg_color=Colors.ACCENT_PRIMARY, hover_color=Colors.BTN_PRIMARY_HOVER,
            border_color=Colors.BORDER)
        full_radio.pack(side="left", padx=(0, Spacing.MD))
        ToolTip(full_radio, "Automatically process all clips without manual selection")
        
        select_radio = ctk.CTkRadioButton(mode_options, text="Select Highlights",
            variable=self.mode_var, value="select", font=Fonts.body_sm(),
            fg_color=Colors.ACCENT_PRIMARY, hover_color=Colors.BTN_PRIMARY_HOVER,
            border_color=Colors.BORDER)
        select_radio.pack(side="left")
        ToolTip(select_radio, "Review and select which highlights to process")
        
        # Heatmap toggle
        heatmap_frame = ctk.CTkFrame(settings_row, fg_color="transparent")
        heatmap_frame.pack(side="left", padx=(Spacing.XL, 0))
        
        create_styled_label(heatmap_frame, "Heatmap Boost:", style="caption").pack(anchor="w")
        
        self.heatmap_var = ctk.BooleanVar(value=True)
        heatmap_cb = ctk.CTkCheckBox(heatmap_frame, text="📊 Most Replayed",
            variable=self.heatmap_var, font=Fonts.body_sm(),
            fg_color=Colors.ACCENT_PRIMARY, hover_color=Colors.BTN_PRIMARY_HOVER,
            border_color=Colors.BORDER, checkbox_width=20, checkbox_height=20)
        heatmap_cb.pack(anchor="w", pady=(4, 0))
        ToolTip(heatmap_cb, "Use YouTube heatmap data to boost clips from most-replayed segments")
        
        # Cookies status
        cookies_frame = ctk.CTkFrame(section, fg_color=Colors.BG_SECONDARY, 
            corner_radius=BorderRadius.SM)
        cookies_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))
        
        cookies_inner = ctk.CTkFrame(cookies_frame, fg_color="transparent")
        cookies_inner.pack(fill="x", padx=Spacing.SM, pady=Spacing.SM)
        
        self.cookies_status_label = create_styled_label(cookies_inner, 
            "🍪 Cookies: Not configured", style="caption")
        self.cookies_status_label.pack(side="left")
        
        # Right side buttons
        cookies_btn_frame = ctk.CTkFrame(cookies_inner, fg_color="transparent")
        cookies_btn_frame.pack(side="right")
        
        cookies_upload_btn = create_styled_button(cookies_btn_frame, "📁 Upload",
            command=self._upload_cookies,
            style="secondary", width=80, height=24,
            tooltip="Upload cookies.txt file from your browser")
        cookies_upload_btn.pack(side="left", padx=(0, Spacing.XS))
        
        cookies_help_btn = create_styled_button(cookies_btn_frame, "❓ Help",
            command=self._show_cookies_help,
            style="ghost", width=60, height=24,
            tooltip="Learn how to setup cookies.txt for age-restricted videos")
        cookies_help_btn.pack(side="left")
        
        # Check and update cookies status
        self._check_cookies_status()
    
    def _create_action_buttons(self):
        """Create action buttons"""
        action_frame = ctk.CTkFrame(self.main_scroll, fg_color="transparent")
        action_frame.pack(fill="x", pady=Spacing.MD)
        
        # Center buttons
        btn_container = ctk.CTkFrame(action_frame, fg_color="transparent")
        btn_container.pack()
        
        # Start button
        self.start_btn = create_styled_button(btn_container, "Start Processing",
            command=self._start_processing,
            style="primary", width=180, height=44,
            tooltip="Begin extracting highlights from the video",
            icon="🚀")
        self.start_btn.pack(side="left", padx=Spacing.SM)
        
        # API Status button
        api_btn = create_styled_button(btn_container, "API Status",
            command=lambda: self.app.show_page("api_status"),
            style="ghost", width=100, height=44,
            tooltip="Check AI API connection status",
            icon="📊")
        api_btn.pack(side="left", padx=Spacing.SM)
    
    # ==========================================================================
    # EVENT HANDLERS
    # ==========================================================================
    
    def _on_url_change(self, *args):
        """Handle URL input change"""
        url = self.url_var.get().strip()
        
        if not url:
            self.url_status_label.configure(text="", text_color=Colors.TEXT_MUTED)
            self._reset_preview()
            return
        
        # Validate YouTube URL
        video_id = self._extract_video_id(url)
        
        if video_id:
            self.url_status_label.configure(
                text=f"✓ Valid YouTube URL (ID: {video_id})",
                text_color=Colors.SUCCESS
            )
            # Load thumbnail and info
            self._load_video_info(video_id)
        else:
            self.url_status_label.configure(
                text="✗ Invalid YouTube URL",
                text_color=Colors.ERROR
            )
            self._reset_preview()
    
    def _extract_video_id(self, url):
        """Extract video ID from YouTube URL"""
        patterns = [
            r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})',
            r'(?:youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None
    
    def _paste_url(self):
        """Paste URL from clipboard"""
        try:
            clipboard = self.clipboard_get()
            self.url_var.set(clipboard)
        except:
            pass
    
    def _load_video_info(self, video_id):
        """Load video thumbnail and info"""
        def load():
            try:
                import urllib.request
                
                # Try different thumbnail qualities
                thumb_urls = [
                    f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
                    f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
                    f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg",
                ]
                
                for thumb_url in thumb_urls:
                    try:
                        with urllib.request.urlopen(thumb_url, timeout=5) as response:
                            from io import BytesIO
                            data = response.read()
                            img = Image.open(BytesIO(data))
                            
                            # Resize to fit
                            img.thumbnail((320, 180), Image.Resampling.LANCZOS)
                            
                            self.after(0, lambda: self._update_thumbnail(img))
                            break
                    except:
                        continue
                
                # Load subtitles using app's existing method
                url = f"https://youtube.com/watch?v={video_id}"
                self.after(100, lambda: self._load_subtitles_via_app(url))
                
            except Exception as e:
                self.after(0, lambda: self.url_status_label.configure(
                    text=f"⚠ Could not load preview: {str(e)[:30]}",
                    text_color=Colors.WARNING
                ))
        
        threading.Thread(target=load, daemon=True).start()
    
    def _load_subtitles_via_app(self, url):
        """Delegate subtitle loading to the app's proven method"""
        # Use the app's existing subtitle loading implementation
        self.subtitle_status.configure(text="⏳ Loading subtitles...")
        
        def on_subtitles_loaded(subtitles):
            """Callback when subtitles are loaded"""
            subs = []
            for sub in subtitles:
                subs.append(f"{sub['code']} - {sub['name']}")
            self._update_subtitles(subs)
        
        def on_error(error):
            """Callback when subtitle loading fails"""
            self.subtitle_status.configure(
                text=f"⚠ {str(error)[:40]}", text_color=Colors.WARNING)
        
        # Use app's load_subtitles but with our callbacks
        def fetch():
            try:
                from clipper_core import AutoClipperCore
                from utils.helpers import get_app_dir
                
                app_dir = get_app_dir()
                cookies_path = app_dir / "cookies.txt"
                
                ytdlp_path = getattr(self.app, 'ytdlp_path', 'yt_dlp_module')
                cookies_str = str(cookies_path) if cookies_path.exists() else None
                
                result = AutoClipperCore.get_available_subtitles(
                    url, 
                    ytdlp_path, 
                    cookies_path=cookies_str
                )
                
                if result.get("error"):
                    self.after(0, lambda: on_error(result["error"]))
                    return
                
                # Combine manual and auto-generated subtitles
                all_subs = []
                
                for sub in result.get("subtitles", []):
                    all_subs.append({
                        "code": sub["code"],
                        "name": sub["name"]
                    })
                
                for sub in result.get("automatic_captions", []):
                    all_subs.append({
                        "code": sub["code"],
                        "name": f"{sub['name']} (auto)"
                    })
                
                if not all_subs:
                    self.after(0, lambda: on_error("No subtitles available"))
                    return
                
                self.after(0, lambda: on_subtitles_loaded(all_subs))
                
            except Exception as e:
                self.after(0, lambda: on_error(str(e)))
        
        threading.Thread(target=fetch, daemon=True).start()
    
    def _update_thumbnail(self, img):
        """Update thumbnail display"""
        self.thumb_placeholder.place_forget()
        
        self.current_thumbnail = ctk.CTkImage(light_image=img, dark_image=img, size=(320, 180))
        self.thumb_label.configure(image=self.current_thumbnail)
        self.thumb_label.place(relx=0.5, rely=0.5, anchor="center")
        
        self.video_title_label.configure(text="Video loaded")
    
    def _reset_preview(self):
        """Reset preview to placeholder"""
        self.thumb_label.place_forget()
        self.thumb_placeholder.place(relx=0.5, rely=0.5, anchor="center")
        self.video_title_label.configure(text="No video loaded")
        self.video_channel_label.configure(text="")
        self.video_duration_label.configure(text="")
        self.subtitle_dropdown.configure(state="disabled", values=["(loading...)"])
        self.subtitle_var.set("")
        self.subtitle_status.configure(text="")
        self.subtitle_loaded = False
    
    def _update_subtitles(self, subs):
        """Update subtitle dropdown"""
        self.subtitle_dropdown.configure(state="normal", values=subs)
        
        # Try to select Indonesian
        for sub in subs:
            if sub.startswith("id"):
                self.subtitle_var.set(sub)
                break
        
        self.subtitle_status.configure(
            text=f"✓ Found {len(subs)} subtitle(s)",
            text_color=Colors.SUCCESS
        )
        self.subtitle_loaded = True
    
    def _start_processing(self):
        """Start the clipping process"""
        url = self.url_var.get().strip()
        
        if not url:
            messagebox.showwarning("No URL", "Please enter a YouTube URL first.")
            return
        
        video_id = self._extract_video_id(url)
        if not video_id:
            messagebox.showwarning("Invalid URL", "Please enter a valid YouTube URL.")
            return
        
        # Check if subtitles are loaded
        if not self.subtitle_loaded:
            messagebox.showwarning("Loading", "Please wait for subtitles to finish loading.")
            return
        
        # Validate subtitle selection
        subtitle_sel = self.subtitle_var.get().strip()
        if not subtitle_sel or subtitle_sel == "(loading...)" or " - " not in subtitle_sel:
            messagebox.showwarning("No Subtitle", "Please select a valid subtitle language from the dropdown.")
            return
        
        try:
            clips = int(self.clips_var.get())
            if clips < 1 or clips > 50:
                raise ValueError()
        except:
            messagebox.showwarning("Invalid Clips", "Clip count must be between 1 and 50.")
            return
        
        # Variables already on app level, no need to copy
        # self.app.url_var, self.app.clips_var, self.app.subtitle_var are already synced
        
        if self.mode_var.get() == "select":
            # Go to highlight selection
            self.app.use_heatmap = self.heatmap_var.get()
            self.app.start_highlight_detection()
        else:
            # Go directly to processing
            self.app.use_heatmap = self.heatmap_var.get()
            self.app.show_page("processing")
            self.app.start_processing()
    
    def _show_cookies_help(self):
        """Show cookies setup help"""
        messagebox.showinfo("Cookies Setup",
            "🍪 Cookies are needed for:\n"
            "• Age-restricted videos\n"
            "• Member-only content\n"
            "• Region-locked videos\n\n"
            "📝 How to setup:\n"
            "1. Install 'Get cookies.txt' browser extension\n"
            "2. Login to YouTube in your browser\n"
            "3. Export cookies to cookies.txt\n"
            "4. Click 'Upload' button to select the file\n\n"
            "See COOKIES.md for detailed guide.")
    
    def _upload_cookies(self):
        """Upload cookies.txt file"""
        from pathlib import Path
        
        file_path = filedialog.askopenfilename(
            title="Select cookies.txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        
        if file_path:
            try:
                # Get app directory
                from utils.helpers import get_app_dir
                app_dir = get_app_dir()
                dest_path = app_dir / "cookies.txt"
                
                # Copy file
                import shutil
                shutil.copy(file_path, dest_path)
                
                # Update status
                self._check_cookies_status()
                
                messagebox.showinfo("Success", "cookies.txt uploaded successfully!")
                
            except Exception as e:
                messagebox.showerror("Upload Failed", f"Failed to upload cookies.txt:\n{str(e)}")
    
    def _check_cookies_status(self):
        """Check if cookies.txt exists and update UI"""
        from utils.helpers import get_app_dir
        app_dir = get_app_dir()
        cookies_path = app_dir / "cookies.txt"
        
        if cookies_path.exists():
            self.cookies_status_label.configure(
                text="🍪 Cookies: ✓ Configured",
                text_color=Colors.SUCCESS
            )
        else:
            self.cookies_status_label.configure(
                text="🍪 Cookies: Not configured",
                text_color=Colors.TEXT_MUTED
            )
    
    def update_cookies_status(self, has_cookies):
        """Update cookies status display"""
        if has_cookies:
            self.cookies_status_label.configure(
                text="🍪 Cookies: ✓ Configured",
                text_color=Colors.SUCCESS
            )
        else:
            self.cookies_status_label.configure(
                text="🍪 Cookies: Not configured",
                text_color=Colors.TEXT_MUTED
            )
    
    # Navigation compatibility
    def show_page(self, page_name):
        """Delegate to main app"""
        self.app.show_page(page_name)
