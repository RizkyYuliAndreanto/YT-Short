"""
Clip Cutter Page - Multi-platform video segment downloader
Download clips from YouTube, TikTok, Instagram, Facebook with watermark removal
"""

import customtkinter as ctk
from pathlib import Path
from tkinter import filedialog, messagebox
from PIL import Image
import threading
import urllib.request
import io
import re

# Import theme
from components.ui_theme import (
    Colors, Fonts, Spacing, BorderRadius,
    ToolTip, create_styled_button, create_styled_card,
    create_styled_input, create_styled_label, create_section_divider
)

# Import core
from clip_cutter_core import (
    ClipCutterCore, detect_platform, parse_time_input, format_time,
    YTDLP_MODULE_AVAILABLE
)

# Import helpers
from utils.helpers import get_ffmpeg_path, get_ytdlp_path, get_deno_path, get_app_dir
from utils.gpu_detector import GPUDetector


class ClipCutterPage(ctk.CTkFrame):
    """Clip Cutter - Multi-platform video segment downloader"""

    def __init__(self, parent, app, config):
        super().__init__(parent, fg_color=Colors.BG_PRIMARY)
        self.app = app
        self.config = config

        # State
        self.video_info = None
        self.is_downloading = False
        self.cancel_requested = False
        self.current_platform = None

        # Core processor (initialized on demand)
        self.core = None

        # Thumbnail cache
        self._thumbnail_image = None

        self.create_ui()

    def go_back(self):
        """Navigate back to landing page"""
        if self.is_downloading:
            if not messagebox.askyesno("Cancel Download?",
                    "A download is in progress. Do you want to cancel and go back?"):
                return
            self.cancel_requested = True

        self.app.show_page("landing")

    def create_ui(self):
        """Create the clip cutter UI"""

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

        # Clip Settings Section
        self._create_clip_settings_section()

        # Output Settings Section
        self._create_output_section()

        # Action Buttons
        self._create_action_section()

    def _create_header(self):
        """Create page header with back button"""
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.LG, pady=(Spacing.MD, Spacing.SM))

        # Left: Back button + Title
        left = ctk.CTkFrame(header, fg_color="transparent")
        left.pack(side="left")

        back_btn = create_styled_button(left, "",
            command=self.go_back,
            style="ghost", width=40, height=36,
            tooltip="Return to main menu")
        back_btn.pack(side="left")

        title_frame = ctk.CTkFrame(left, fg_color="transparent")
        title_frame.pack(side="left", padx=(Spacing.SM, 0))

        create_styled_label(title_frame, "Clip Cutter", style="heading_lg").pack(anchor="w")
        create_styled_label(title_frame, "Download clips from YouTube, TikTok, Instagram, Facebook",
            style="muted").pack(anchor="w")

        # Right: Settings button
        right = ctk.CTkFrame(header, fg_color="transparent")
        right.pack(side="right")

        settings_btn = create_styled_button(right, "Settings",
            command=lambda: self.app.show_page("settings"),
            style="secondary", width=90, height=32,
            tooltip="Configure API keys and preferences",
            icon="")
        settings_btn.pack(side="left")

    def _create_url_section(self):
        """Create URL input section with platform detection"""
        section = ctk.CTkFrame(self.main_scroll, fg_color=Colors.CARD_BG,
            corner_radius=BorderRadius.LG, border_width=1, border_color=Colors.BORDER)
        section.pack(fill="x", pady=(0, Spacing.MD))

        # Header
        header = ctk.CTkFrame(section, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.MD, pady=(Spacing.MD, Spacing.SM))

        icon_frame = ctk.CTkFrame(header, width=36, height=36,
            fg_color=Colors.INFO, corner_radius=BorderRadius.SM)
        icon_frame.pack(side="left")
        icon_frame.pack_propagate(False)
        ctk.CTkLabel(icon_frame, text="", font=ctk.CTkFont(size=18)).place(relx=0.5, rely=0.5, anchor="center")

        title_col = ctk.CTkFrame(header, fg_color="transparent")
        title_col.pack(side="left", padx=(Spacing.SM, 0))
        create_styled_label(title_col, "Step 1: Enter Video URL", style="heading_sm").pack(anchor="w")
        create_styled_label(title_col, "Paste a video link from any supported platform", style="muted").pack(anchor="w")

        # URL Input
        input_frame = ctk.CTkFrame(section, fg_color="transparent")
        input_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.SM))

        self.url_var = ctk.StringVar()
        self.url_var.trace_add("write", self._on_url_change)

        self.url_entry = ctk.CTkEntry(input_frame, textvariable=self.url_var,
            placeholder_text="https://youtube.com/watch?v=... or tiktok.com/... or instagram.com/...",
            fg_color=Colors.BG_SECONDARY, border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY, font=Fonts.body(),
            corner_radius=BorderRadius.SM, height=42)
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(0, Spacing.SM))
        ToolTip(self.url_entry, "Enter a video URL from YouTube, TikTok, Instagram, or Facebook")

        paste_btn = create_styled_button(input_frame, "Paste",
            command=self._paste_url,
            style="secondary", width=80, height=42,
            tooltip="Paste URL from clipboard",
            icon="")
        paste_btn.pack(side="left", padx=(0, Spacing.SM))

        self.analyze_btn = create_styled_button(input_frame, "Analyze",
            command=self._analyze_url,
            style="primary", width=100, height=42,
            tooltip="Fetch video information")
        self.analyze_btn.pack(side="left")

        # Platform indicator
        platform_frame = ctk.CTkFrame(section, fg_color="transparent")
        platform_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        self.platform_label = create_styled_label(platform_frame, "Platform: Not detected", style="caption")
        self.platform_label.pack(anchor="w")

    def _create_preview_section(self):
        """Create video preview section"""
        self.preview_section = ctk.CTkFrame(self.main_scroll, fg_color=Colors.CARD_BG,
            corner_radius=BorderRadius.LG, border_width=1, border_color=Colors.BORDER)
        self.preview_section.pack(fill="x", pady=(0, Spacing.MD))

        # Header
        header = ctk.CTkFrame(self.preview_section, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.MD, pady=(Spacing.MD, Spacing.SM))

        icon_frame = ctk.CTkFrame(header, width=36, height=36,
            fg_color=Colors.ACCENT_PRIMARY, corner_radius=BorderRadius.SM)
        icon_frame.pack(side="left")
        icon_frame.pack_propagate(False)
        ctk.CTkLabel(icon_frame, text="", font=ctk.CTkFont(size=18)).place(relx=0.5, rely=0.5, anchor="center")

        title_col = ctk.CTkFrame(header, fg_color="transparent")
        title_col.pack(side="left", padx=(Spacing.SM, 0))
        create_styled_label(title_col, "Video Preview", style="heading_sm").pack(anchor="w")
        create_styled_label(title_col, "Video information and thumbnail", style="muted").pack(anchor="w")

        # Content
        content = ctk.CTkFrame(self.preview_section, fg_color="transparent")
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

        ctk.CTkLabel(self.thumb_placeholder, text="", font=ctk.CTkFont(size=40),
            text_color=Colors.TEXT_MUTED).pack()
        ctk.CTkLabel(self.thumb_placeholder, text="Enter URL to load preview",
            font=Fonts.caption(), text_color=Colors.TEXT_MUTED).pack()

        self.thumb_label = ctk.CTkLabel(thumb_frame, text="")

        # Right: Video info
        info_frame = ctk.CTkFrame(content, fg_color="transparent")
        info_frame.pack(side="left", fill="both", expand=True)

        # Title
        create_styled_label(info_frame, "Title", style="caption").pack(anchor="w")
        self.title_label = create_styled_label(info_frame, "---", style="body")
        self.title_label.pack(anchor="w", pady=(0, Spacing.SM))

        # Duration
        create_styled_label(info_frame, "Duration", style="caption").pack(anchor="w")
        self.duration_label = create_styled_label(info_frame, "---", style="body")
        self.duration_label.pack(anchor="w", pady=(0, Spacing.SM))

        # Platform badge
        create_styled_label(info_frame, "Platform", style="caption").pack(anchor="w")
        self.platform_badge = ctk.CTkFrame(info_frame, fg_color=Colors.BG_TERTIARY,
            corner_radius=BorderRadius.SM, height=28)
        self.platform_badge.pack(anchor="w", pady=(0, Spacing.SM))
        self.platform_badge_label = ctk.CTkLabel(self.platform_badge, text="---",
            font=Fonts.caption(), text_color=Colors.TEXT_SECONDARY)
        self.platform_badge_label.pack(padx=Spacing.SM, pady=4)

    def _create_clip_settings_section(self):
        """Create clip settings section"""
        section = ctk.CTkFrame(self.main_scroll, fg_color=Colors.CARD_BG,
            corner_radius=BorderRadius.LG, border_width=1, border_color=Colors.BORDER)
        section.pack(fill="x", pady=(0, Spacing.MD))

        # Header
        header = ctk.CTkFrame(section, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.MD, pady=(Spacing.MD, Spacing.SM))

        icon_frame = ctk.CTkFrame(header, width=36, height=36,
            fg_color=Colors.WARNING, corner_radius=BorderRadius.SM)
        icon_frame.pack(side="left")
        icon_frame.pack_propagate(False)
        ctk.CTkLabel(icon_frame, text="", font=ctk.CTkFont(size=18)).place(relx=0.5, rely=0.5, anchor="center")

        title_col = ctk.CTkFrame(header, fg_color="transparent")
        title_col.pack(side="left", padx=(Spacing.SM, 0))
        create_styled_label(title_col, "Step 2: Clip Settings", style="heading_sm").pack(anchor="w")
        create_styled_label(title_col, "Set time range and quality options", style="muted").pack(anchor="w")

        # Time range inputs
        time_frame = ctk.CTkFrame(section, fg_color="transparent")
        time_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.SM))

        # Start time
        start_col = ctk.CTkFrame(time_frame, fg_color="transparent")
        start_col.pack(side="left", padx=(0, Spacing.MD))

        create_styled_label(start_col, "Start Time", style="caption").pack(anchor="w")
        self.start_time_var = ctk.StringVar(value="00:00")
        self.start_time_entry = ctk.CTkEntry(start_col, textvariable=self.start_time_var,
            width=100, fg_color=Colors.BG_SECONDARY, border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY, font=Fonts.body(),
            corner_radius=BorderRadius.SM, height=36)
        self.start_time_entry.pack(anchor="w")
        ToolTip(self.start_time_entry, "Format: MM:SS or HH:MM:SS")

        # End time
        end_col = ctk.CTkFrame(time_frame, fg_color="transparent")
        end_col.pack(side="left", padx=(0, Spacing.MD))

        create_styled_label(end_col, "End Time", style="caption").pack(anchor="w")
        self.end_time_var = ctk.StringVar(value="01:00")
        self.end_time_entry = ctk.CTkEntry(end_col, textvariable=self.end_time_var,
            width=100, fg_color=Colors.BG_SECONDARY, border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY, font=Fonts.body(),
            corner_radius=BorderRadius.SM, height=36)
        self.end_time_entry.pack(anchor="w")
        ToolTip(self.end_time_entry, "Format: MM:SS or HH:MM:SS")

        # Duration display
        duration_col = ctk.CTkFrame(time_frame, fg_color="transparent")
        duration_col.pack(side="left", padx=(0, Spacing.MD))

        create_styled_label(duration_col, "Clip Duration", style="caption").pack(anchor="w")
        self.clip_duration_label = create_styled_label(duration_col, "1:00", style="body")
        self.clip_duration_label.pack(anchor="w", pady=(8, 0))

        # Bind time change events
        self.start_time_var.trace_add("write", self._on_time_change)
        self.end_time_var.trace_add("write", self._on_time_change)

        # Options row
        options_frame = ctk.CTkFrame(section, fg_color="transparent")
        options_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.SM))

        # Quality selector
        quality_col = ctk.CTkFrame(options_frame, fg_color="transparent")
        quality_col.pack(side="left", padx=(0, Spacing.LG))

        create_styled_label(quality_col, "Quality", style="caption").pack(anchor="w")
        self.quality_var = ctk.StringVar(value="Best")
        self.quality_dropdown = ctk.CTkOptionMenu(quality_col,
            variable=self.quality_var,
            values=["Best", "1080p", "720p", "480p", "360p"],
            fg_color=Colors.BG_SECONDARY,
            button_color=Colors.ACCENT_PRIMARY,
            button_hover_color=Colors.BTN_PRIMARY_HOVER,
            dropdown_fg_color=Colors.CARD_BG,
            dropdown_hover_color=Colors.CARD_HOVER,
            text_color=Colors.TEXT_PRIMARY,
            font=Fonts.body(),
            width=120, height=36)
        self.quality_dropdown.pack(anchor="w")

        # Checkboxes column
        checkbox_col = ctk.CTkFrame(options_frame, fg_color="transparent")
        checkbox_col.pack(side="left", fill="x", expand=True)

        # Partial download checkbox (YouTube only)
        self.partial_download_var = ctk.BooleanVar(value=True)
        self.partial_download_cb = ctk.CTkCheckBox(checkbox_col,
            text="Use Partial Download (YouTube only - saves bandwidth)",
            variable=self.partial_download_var,
            fg_color=Colors.ACCENT_PRIMARY,
            hover_color=Colors.BTN_PRIMARY_HOVER,
            text_color=Colors.TEXT_PRIMARY,
            font=Fonts.body())
        self.partial_download_cb.pack(anchor="w", pady=(Spacing.XS, 0))
        ToolTip(self.partial_download_cb, "Only download the clip segment instead of full video (efficient)")

        # Remove watermark checkbox
        self.remove_watermark_var = ctk.BooleanVar(value=False)
        self.remove_watermark_cb = ctk.CTkCheckBox(checkbox_col,
            text="Remove Watermark (TikTok/Instagram)",
            variable=self.remove_watermark_var,
            fg_color=Colors.ACCENT_PRIMARY,
            hover_color=Colors.BTN_PRIMARY_HOVER,
            text_color=Colors.TEXT_PRIMARY,
            font=Fonts.body())
        self.remove_watermark_cb.pack(anchor="w", pady=(Spacing.XS, 0))
        ToolTip(self.remove_watermark_cb, "Attempt to remove platform watermarks by cropping")

        # Full video checkbox
        self.full_video_var = ctk.BooleanVar(value=False)
        self.full_video_cb = ctk.CTkCheckBox(checkbox_col,
            text="Download Full Video (ignore time range)",
            variable=self.full_video_var,
            fg_color=Colors.ACCENT_PRIMARY,
            hover_color=Colors.BTN_PRIMARY_HOVER,
            text_color=Colors.TEXT_PRIMARY,
            font=Fonts.body(),
            command=self._on_full_video_toggle)
        self.full_video_cb.pack(anchor="w", pady=(Spacing.XS, Spacing.SM))
        ToolTip(self.full_video_cb, "Download the entire video without cutting")

    def _create_output_section(self):
        """Create output settings section"""
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
        ctk.CTkLabel(icon_frame, text="", font=ctk.CTkFont(size=18)).place(relx=0.5, rely=0.5, anchor="center")

        title_col = ctk.CTkFrame(header, fg_color="transparent")
        title_col.pack(side="left", padx=(Spacing.SM, 0))
        create_styled_label(title_col, "Output Settings", style="heading_sm").pack(anchor="w")
        create_styled_label(title_col, "Configure where to save the clip", style="muted").pack(anchor="w")

        # Output folder
        folder_frame = ctk.CTkFrame(section, fg_color="transparent")
        folder_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.SM))

        create_styled_label(folder_frame, "Output Folder", style="caption").pack(anchor="w")

        folder_input_frame = ctk.CTkFrame(folder_frame, fg_color="transparent")
        folder_input_frame.pack(fill="x", pady=(Spacing.XS, 0))

        default_output = self.config.get("output_dir", str(get_app_dir() / "output" / "clips"))
        self.output_dir_var = ctk.StringVar(value=default_output)

        self.output_dir_entry = ctk.CTkEntry(folder_input_frame,
            textvariable=self.output_dir_var,
            fg_color=Colors.BG_SECONDARY, border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY, font=Fonts.body(),
            corner_radius=BorderRadius.SM, height=36)
        self.output_dir_entry.pack(side="left", fill="x", expand=True, padx=(0, Spacing.SM))

        browse_btn = create_styled_button(folder_input_frame, "Browse",
            command=self._browse_output_folder,
            style="secondary", width=80, height=36,
            tooltip="Select output folder")
        browse_btn.pack(side="left")

        # GPU acceleration
        gpu_frame = ctk.CTkFrame(section, fg_color="transparent")
        gpu_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        self.gpu_var = ctk.BooleanVar(value=self.config.get("gpu_acceleration", {}).get("enabled", False))
        self.gpu_cb = ctk.CTkCheckBox(gpu_frame,
            text="GPU Acceleration",
            variable=self.gpu_var,
            fg_color=Colors.ACCENT_PRIMARY,
            hover_color=Colors.BTN_PRIMARY_HOVER,
            text_color=Colors.TEXT_PRIMARY,
            font=Fonts.body())
        self.gpu_cb.pack(side="left")

        # GPU info
        gpu_info = GPUDetector().get_recommended_encoder()
        if gpu_info.get('available'):
            gpu_label = create_styled_label(gpu_frame,
                f"  ({gpu_info.get('encoder', 'GPU')} detected)",
                style="caption", color=Colors.SUCCESS)
        else:
            gpu_label = create_styled_label(gpu_frame,
                "  (No GPU encoder detected)",
                style="caption", color=Colors.TEXT_MUTED)
        gpu_label.pack(side="left")

    def _create_action_section(self):
        """Create action buttons and progress"""
        section = ctk.CTkFrame(self.main_scroll, fg_color=Colors.CARD_BG,
            corner_radius=BorderRadius.LG, border_width=1, border_color=Colors.BORDER)
        section.pack(fill="x", pady=(0, Spacing.MD))

        # Progress bar
        progress_frame = ctk.CTkFrame(section, fg_color="transparent")
        progress_frame.pack(fill="x", padx=Spacing.MD, pady=(Spacing.MD, Spacing.SM))

        self.progress_bar = ctk.CTkProgressBar(progress_frame,
            fg_color=Colors.BG_SECONDARY,
            progress_color=Colors.ACCENT_PRIMARY,
            height=8, corner_radius=4)
        self.progress_bar.pack(fill="x")
        self.progress_bar.set(0)

        # Status label
        self.status_label = create_styled_label(progress_frame, "Ready", style="caption")
        self.status_label.pack(anchor="w", pady=(Spacing.XS, 0))

        # Buttons
        button_frame = ctk.CTkFrame(section, fg_color="transparent")
        button_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        # Spacer
        ctk.CTkFrame(button_frame, fg_color="transparent").pack(side="left", fill="x", expand=True)

        # Cancel button
        self.cancel_btn = create_styled_button(button_frame, "Cancel",
            command=self._cancel_download,
            style="ghost", width=100, height=42,
            tooltip="Cancel current download")
        self.cancel_btn.pack(side="left", padx=(0, Spacing.SM))
        self.cancel_btn.configure(state="disabled")

        # Download button
        self.download_btn = create_styled_button(button_frame, " Download Clip",
            command=self._start_download,
            style="primary", width=160, height=42,
            tooltip="Start downloading the clip")
        self.download_btn.pack(side="left")

    # ============ Event Handlers ============

    def _on_url_change(self, *args):
        """Handle URL input change"""
        url = self.url_var.get().strip()
        if url:
            platform_info = detect_platform(url)
            platform = platform_info['platform']
            is_short_form = platform_info.get('is_short_form', False)

            # Update platform indicator
            platform_icons = {
                'youtube': ' YouTube',
                'youtube_shorts': ' YouTube Shorts',
                'tiktok': ' TikTok',
                'instagram': ' Instagram',
                'facebook': ' Facebook',
                'unknown': ' Unknown',
            }

            icon_text = platform_icons.get(platform, ' Unknown')
            self.platform_label.configure(text=f"Platform: {icon_text}")

            # Update checkbox states based on platform
            # Partial download ONLY for regular YouTube (not Shorts)
            if platform == 'youtube' and not is_short_form:
                self.partial_download_cb.configure(state="normal")
            else:
                # Disable partial download for short-form content
                self.partial_download_var.set(False)
                self.partial_download_cb.configure(state="disabled")

            if platform in ('tiktok', 'instagram'):
                self.remove_watermark_var.set(True)
                self.remove_watermark_cb.configure(state="normal")
            else:
                self.remove_watermark_var.set(False)
                self.remove_watermark_cb.configure(state="disabled")

            # For short-form content, enable full video download by default
            if is_short_form:
                self.full_video_var.set(True)
                self._on_full_video_toggle()
        else:
            self.platform_label.configure(text="Platform: Not detected")

    def _on_time_change(self, *args):
        """Handle time input change"""
        try:
            start = parse_time_input(self.start_time_var.get())
            end = parse_time_input(self.end_time_var.get())
            duration = max(0, end - start)
            self.clip_duration_label.configure(text=format_time(duration))
        except Exception:
            self.clip_duration_label.configure(text="Invalid")

    def _on_full_video_toggle(self):
        """Handle full video checkbox toggle"""
        if self.full_video_var.get():
            self.start_time_entry.configure(state="disabled")
            self.end_time_entry.configure(state="disabled")
            self.partial_download_cb.configure(state="disabled")
        else:
            self.start_time_entry.configure(state="normal")
            self.end_time_entry.configure(state="normal")
            platform_info = detect_platform(self.url_var.get())
            # Only enable partial download for regular YouTube (not Shorts)
            if platform_info['platform'] == 'youtube' and not platform_info.get('is_short_form', False):
                self.partial_download_cb.configure(state="normal")

    def _paste_url(self):
        """Paste URL from clipboard"""
        try:
            url = self.clipboard_get()
            if url:
                self.url_var.set(url.strip())
        except Exception:
            pass

    def _browse_output_folder(self):
        """Browse for output folder"""
        folder = filedialog.askdirectory(
            title="Select Output Folder",
            initialdir=self.output_dir_var.get()
        )
        if folder:
            self.output_dir_var.set(folder)

    def _analyze_url(self):
        """Analyze URL and fetch video info"""
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("No URL", "Please enter a video URL first.")
            return

        # Disable button during analysis
        self.analyze_btn.configure(state="disabled")
        self.status_label.configure(text="Analyzing...")
        self.progress_bar.set(0.2)

        def analyze_thread():
            try:
                # Initialize core if needed
                self._init_core()

                # Get video info
                info = self.core.get_video_info(url)

                # Update UI in main thread
                self.after(0, lambda: self._update_preview(info))

            except Exception as e:
                self.after(0, lambda: self._show_error(f"Analysis failed: {str(e)}"))
            finally:
                self.after(0, lambda: self.analyze_btn.configure(state="normal"))
                self.after(0, lambda: self.progress_bar.set(0))

        thread = threading.Thread(target=analyze_thread, daemon=True)
        thread.start()

    def _update_preview(self, info: dict):
        """Update preview section with video info"""
        if info.get('error'):
            self.status_label.configure(text=f"Error: {info['error']}")
            return

        self.video_info = info
        self.status_label.configure(text="Ready")

        # Update title
        title = info.get('title', 'Unknown')
        if len(title) > 60:
            title = title[:57] + "..."
        self.title_label.configure(text=title)

        # Update duration
        duration = info.get('duration', 0)
        self.duration_label.configure(text=format_time(duration))

        # Set end time to video duration if it's shorter
        if duration > 0:
            current_end = parse_time_input(self.end_time_var.get())
            if current_end > duration:
                self.end_time_var.set(format_time(duration))

        # Update platform badge
        platform = info.get('platform', 'unknown').upper()
        # Display friendly name for youtube_shorts
        display_platform = platform.replace('_', ' ')
        self.platform_badge_label.configure(text=display_platform)

        # Platform-specific colors
        platform_colors = {
            'YOUTUBE': Colors.ERROR,
            'YOUTUBE_SHORTS': Colors.ERROR,  # Same red as YouTube
            'TIKTOK': Colors.TEXT_PRIMARY,
            'INSTAGRAM': Colors.ACCENT_SECONDARY,
            'FACEBOOK': Colors.ACCENT_PRIMARY,
        }
        self.platform_badge.configure(fg_color=platform_colors.get(platform, Colors.BG_TERTIARY))

        # Load thumbnail
        thumbnail_url = info.get('thumbnail')
        if thumbnail_url:
            self._load_thumbnail(thumbnail_url)

    def _load_thumbnail(self, url: str):
        """Load thumbnail image in background"""
        def load_thread():
            try:
                # Download thumbnail
                with urllib.request.urlopen(url, timeout=10) as response:
                    image_data = response.read()

                # Create image
                image = Image.open(io.BytesIO(image_data))
                image.thumbnail((320, 180), Image.Resampling.LANCZOS)

                # Create CTkImage
                ctk_image = ctk.CTkImage(light_image=image, dark_image=image, size=(320, 180))

                # Update UI in main thread
                self.after(0, lambda: self._set_thumbnail(ctk_image))

            except Exception as e:
                print(f"Thumbnail load error: {e}")

        thread = threading.Thread(target=load_thread, daemon=True)
        thread.start()

    def _set_thumbnail(self, image):
        """Set thumbnail image"""
        self._thumbnail_image = image  # Keep reference
        self.thumb_placeholder.place_forget()
        self.thumb_label.configure(image=image)
        self.thumb_label.place(relx=0.5, rely=0.5, anchor="center")

    def _init_core(self):
        """Initialize ClipCutterCore"""
        if self.core is None:
            ffmpeg_path = get_ffmpeg_path()
            ytdlp_path = get_ytdlp_path()
            deno_path = get_deno_path()

            # Get cookies path
            cookies_path = str(get_app_dir() / "cookies.txt")
            if not Path(cookies_path).exists():
                cookies_path = None

            self.core = ClipCutterCore(
                ffmpeg_path=ffmpeg_path,
                ytdlp_path=ytdlp_path,
                output_dir=self.output_dir_var.get(),
                cookies_path=cookies_path,
                deno_path=deno_path,
                log_callback=self._log,
                progress_callback=self._update_progress,
                cancel_check=lambda: self.cancel_requested
            )

            # Set GPU acceleration
            if self.gpu_var.get():
                gpu_detector = GPUDetector()
                gpu_info = gpu_detector.get_recommended_encoder()
                if gpu_info.get('available'):
                    encoder_args = gpu_detector.get_encoder_args(use_gpu=True)
                    self.core.set_gpu_acceleration(True, encoder_args)

    def _log(self, msg: str):
        """Log callback"""
        print(f"[ClipCutter] {msg}")
        self.after(0, lambda: self.status_label.configure(text=msg))

    def _update_progress(self, progress: float, status: str):
        """Progress callback"""
        self.after(0, lambda: self.progress_bar.set(progress))
        self.after(0, lambda: self.status_label.configure(text=status))

    def _start_download(self):
        """Start download process"""
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("No URL", "Please enter a video URL first.")
            return

        # Validate time range
        if not self.full_video_var.get():
            try:
                start = parse_time_input(self.start_time_var.get())
                end = parse_time_input(self.end_time_var.get())
                if end <= start:
                    messagebox.showwarning("Invalid Time", "End time must be after start time.")
                    return
            except Exception:
                messagebox.showwarning("Invalid Time", "Please enter valid time values.")
                return

        # Disable UI
        self.is_downloading = True
        self.cancel_requested = False
        self.download_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.analyze_btn.configure(state="disabled")

        def download_thread():
            try:
                # Initialize core
                self._init_core()

                # Update output directory
                self.core.output_dir = Path(self.output_dir_var.get())
                self.core.output_dir.mkdir(parents=True, exist_ok=True)

                # Get parameters
                if self.full_video_var.get():
                    start_time = None
                    end_time = None
                else:
                    start_time = parse_time_input(self.start_time_var.get())
                    end_time = parse_time_input(self.end_time_var.get())

                quality_map = {
                    "Best": "best",
                    "1080p": "1080",
                    "720p": "720",
                    "480p": "480",
                    "360p": "360",
                }
                quality = quality_map.get(self.quality_var.get(), "best")

                # Download
                output_path, error = self.core.download_clip(
                    url=url,
                    start_time=start_time,
                    end_time=end_time,
                    quality=quality,
                    use_partial_download=self.partial_download_var.get(),
                    remove_watermark=self.remove_watermark_var.get()
                )

                if error:
                    self.after(0, lambda: self._show_error(error))
                else:
                    self.after(0, lambda: self._show_success(output_path))

            except Exception as e:
                self.after(0, lambda: self._show_error(str(e)))
            finally:
                self.after(0, self._download_finished)

        thread = threading.Thread(target=download_thread, daemon=True)
        thread.start()

    def _cancel_download(self):
        """Cancel download"""
        self.cancel_requested = True
        self.status_label.configure(text="Cancelling...")

    def _download_finished(self):
        """Reset UI after download"""
        self.is_downloading = False
        self.cancel_requested = False
        self.download_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.analyze_btn.configure(state="normal")

        # Cleanup
        if self.core:
            self.core.cleanup()
            self.core = None

    def _show_error(self, message: str):
        """Show error message"""
        self.progress_bar.set(0)
        self.status_label.configure(text=f"Error: {message}")
        messagebox.showerror("Download Error", message)

    def _show_success(self, output_path: str):
        """Show success message"""
        self.progress_bar.set(1.0)
        self.status_label.configure(text="Download complete!")

        result = messagebox.askyesno("Download Complete",
            f"Clip saved to:\n{output_path}\n\nOpen containing folder?")
        if result:
            import subprocess
            folder = str(Path(output_path).parent)
            if sys.platform == "win32":
                subprocess.run(["explorer", folder], creationflags=subprocess.CREATE_NO_WINDOW)
            elif sys.platform == "darwin":
                subprocess.run(["open", folder])
            else:
                subprocess.run(["xdg-open", folder])

    def refresh_ui(self):
        """Called when page is shown"""
        # Reset state if needed
        pass
