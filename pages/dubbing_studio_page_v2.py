"""
AI Dubbing Studio Page - Complete Redesign
Modern UI with Midnight Professional theme
Full pipeline: Analyze → Script → TTS → Mix → Export
"""

import customtkinter as ctk
from pathlib import Path
from tkinter import filedialog, messagebox
import threading
import os
import time
import traceback

# Import theme
from components.ui_theme import (
    Colors,
    Fonts,
    Spacing,
    BorderRadius,
    ToolTip,
    create_styled_button,
    create_styled_card,
    create_styled_input,
    create_styled_label,
    create_section_divider,
)


class DubbingStudioPage(ctk.CTkFrame):
    """AI Dubbing Studio - Modern redesign with proper navigation"""

    def __init__(self, parent, app, config):
        super().__init__(parent, fg_color=Colors.BG_PRIMARY)
        self.app = app
        self.config = config

        # State
        self.current_video_path = None
        self.video_info = None  # VideoInfo object
        self.transcript = None  # Full transcript text
        self.transcript_segments = None  # List[TranscriptSegment]
        self.analysis_result = None  # VideoAnalysis object
        self.generated_script = None
        self.word_timings = None
        self.is_processing = False
        self._cancel_flag = False

        self.create_ui()

    def _get_config_dict(self):
        """Convert ConfigManager to dict for backend modules"""
        if hasattr(self.config, "get_resolved_ai_providers"):
            ai_providers = self.config.get_resolved_ai_providers()
        elif hasattr(self.config, "config"):
            ai_providers = self.config.config.get("ai_providers", {})
        else:
            ai_providers = (
                self.config.get("ai_providers", {})
                if isinstance(self.config, dict)
                else {}
            )

        return {
            "ai_providers": ai_providers,
            "stt_provider": {
                "type": "api",
                "model": ai_providers.get("caption_maker", {}).get(
                    "model", "whisper-large-v3-turbo"
                ),
            },
        }

    def go_back(self):
        """Navigate back to landing page"""
        self.app.show_page("landing")

    def refresh_ui(self):
        """Force refresh scrollable frame content.
        Fixes blank page after pack_forget/pack cycle.
        CTkScrollableFrame's internal canvas can lose scroll region.
        """
        try:
            # Force the scrollable frame's canvas to recalculate
            self.main_scroll._parent_canvas.configure(
                scrollregion=self.main_scroll._parent_canvas.bbox("all")
            )
            # Force geometry update
            self.main_scroll.update_idletasks()
        except Exception:
            pass

    def create_ui(self):
        """Create the dubbing studio UI"""

        # Header
        self._create_header()

        # Main content area with scrolling
        self.main_scroll = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color=Colors.BORDER,
            scrollbar_button_hover_color=Colors.ACCENT_PRIMARY,
        )
        self.main_scroll.pack(
            fill="both", expand=True, padx=Spacing.LG, pady=(0, Spacing.MD)
        )

        # Progress indicator
        self._create_progress_indicator()

        # Step sections
        self._create_upload_section()
        self._create_analysis_section()
        self._create_script_section()
        self._create_voice_section()
        self._create_output_section()

        # Action buttons
        self._create_action_buttons()

    def _create_header(self):
        """Create page header with back button"""
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.LG, pady=(Spacing.MD, Spacing.SM))

        # Left: Back button + Title
        left = ctk.CTkFrame(header, fg_color="transparent")
        left.pack(side="left")

        back_btn = create_styled_button(
            left,
            "←",
            command=self.go_back,
            style="ghost",
            width=40,
            height=36,
            tooltip="Return to main menu",
        )
        back_btn.pack(side="left")

        title_frame = ctk.CTkFrame(left, fg_color="transparent")
        title_frame.pack(side="left", padx=(Spacing.SM, 0))

        create_styled_label(title_frame, "AI Dubbing Studio", style="heading_lg").pack(
            anchor="w"
        )
        create_styled_label(
            title_frame, "Create professional voiceovers with Edge TTS", style="muted"
        ).pack(anchor="w")

        # Right: Help button
        right = ctk.CTkFrame(header, fg_color="transparent")
        right.pack(side="right")

        help_btn = create_styled_button(
            right,
            "Help",
            command=self._show_help,
            style="ghost",
            width=80,
            height=32,
            tooltip="View tutorial and usage guide",
            icon="❓",
        )
        help_btn.pack()

    def _create_progress_indicator(self):
        """Create step progress indicator with percentage display"""
        progress_frame = ctk.CTkFrame(
            self.main_scroll, fg_color=Colors.CARD_BG, corner_radius=BorderRadius.MD
        )
        progress_frame.pack(fill="x", pady=(0, Spacing.MD))

        inner = ctk.CTkFrame(progress_frame, fg_color="transparent")
        inner.pack(fill="x", padx=Spacing.MD, pady=Spacing.SM)

        steps = [
            ("1", "Upload", "Upload your video file"),
            ("2", "Analyze", "AI extracts audio & generates transcript"),
            ("3", "Script", "Review & edit the generated script"),
            ("4", "Voice", "Configure TTS voice settings"),
            ("5", "Export", "Generate final video with voiceover"),
        ]

        self.step_indicators = []

        for i, (num, label, tooltip_text) in enumerate(steps):
            step_frame = ctk.CTkFrame(inner, fg_color="transparent")
            step_frame.pack(side="left", expand=True)

            # Circle with number
            circle = ctk.CTkFrame(
                step_frame,
                width=32,
                height=32,
                fg_color=Colors.BORDER if i > 0 else Colors.ACCENT_PRIMARY,
                corner_radius=BorderRadius.ROUND,
            )
            circle.pack()
            circle.pack_propagate(False)

            num_label = ctk.CTkLabel(
                circle, text=num, font=Fonts.body_sm(), text_color=Colors.TEXT_PRIMARY
            )
            num_label.place(relx=0.5, rely=0.5, anchor="center")

            # Step label
            step_label = ctk.CTkLabel(
                step_frame,
                text=label,
                font=Fonts.caption(),
                text_color=Colors.TEXT_SECONDARY,
            )
            step_label.pack(pady=(4, 0))

            ToolTip(step_frame, tooltip_text)
            self.step_indicators.append((circle, num_label))

            # Connector line (except last)
            if i < len(steps) - 1:
                line = ctk.CTkFrame(inner, height=2, width=40, fg_color=Colors.BORDER)
                line.pack(side="left", pady=(0, 16))

        # === GLOBAL PROGRESS BAR (percentage 0-100%) ===
        self.progress_container = ctk.CTkFrame(progress_frame, fg_color="transparent")
        # Don't pack yet - shown during processing

        # Status text + percentage
        status_row = ctk.CTkFrame(self.progress_container, fg_color="transparent")
        status_row.pack(fill="x", padx=Spacing.MD, pady=(Spacing.SM, 2))

        self.progress_status_label = ctk.CTkLabel(
            status_row,
            text="Idle",
            font=Fonts.body_sm(),
            text_color=Colors.TEXT_SECONDARY,
            anchor="w",
        )
        self.progress_status_label.pack(side="left", fill="x", expand=True)

        self.progress_percent_label = ctk.CTkLabel(
            status_row,
            text="0%",
            font=Fonts.body_sm(),
            text_color=Colors.ACCENT_PRIMARY,
            anchor="e",
        )
        self.progress_percent_label.pack(side="right")

        # Progress bar
        self.global_progress_bar = ctk.CTkProgressBar(
            self.progress_container,
            height=8,
            fg_color=Colors.BG_SECONDARY,
            progress_color=Colors.ACCENT_PRIMARY,
            corner_radius=4,
        )
        self.global_progress_bar.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.SM))
        self.global_progress_bar.set(0)

    def _create_upload_section(self):
        """Create video upload section"""
        section = ctk.CTkFrame(
            self.main_scroll,
            fg_color=Colors.CARD_BG,
            corner_radius=BorderRadius.LG,
            border_width=1,
            border_color=Colors.BORDER,
        )
        section.pack(fill="x", pady=(0, Spacing.MD))
        self.upload_section = section

        # Header
        header = ctk.CTkFrame(section, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.MD, pady=(Spacing.MD, Spacing.SM))

        icon_frame = ctk.CTkFrame(
            header,
            width=36,
            height=36,
            fg_color=Colors.ACCENT_PRIMARY,
            corner_radius=BorderRadius.SM,
        )
        icon_frame.pack(side="left")
        icon_frame.pack_propagate(False)
        ctk.CTkLabel(icon_frame, text="📁", font=ctk.CTkFont(size=18)).place(
            relx=0.5, rely=0.5, anchor="center"
        )

        title_col = ctk.CTkFrame(header, fg_color="transparent")
        title_col.pack(side="left", padx=(Spacing.SM, 0))
        create_styled_label(title_col, "Step 1: Upload Video", style="heading_sm").pack(
            anchor="w"
        )
        create_styled_label(
            title_col, "Select a video file to add AI voiceover", style="muted"
        ).pack(anchor="w")

        # Upload area
        upload_area = ctk.CTkFrame(
            section,
            fg_color=Colors.BG_SECONDARY,
            height=120,
            corner_radius=BorderRadius.MD,
            border_width=2,
            border_color=Colors.BORDER,
        )
        upload_area.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))
        upload_area.pack_propagate(False)

        # Upload content
        upload_content = ctk.CTkFrame(upload_area, fg_color="transparent")
        upload_content.place(relx=0.5, rely=0.5, anchor="center")

        create_styled_label(upload_content, "📤", style="heading_xl").pack()
        create_styled_label(
            upload_content, "Click to upload or drag & drop", style="muted"
        ).pack()
        create_styled_label(
            upload_content, "MP4, MKV, AVI, MOV (max 2GB)", style="caption"
        ).pack()

        # Make clickable
        for widget in [upload_area, upload_content]:
            widget.bind("<Button-1>", lambda e: self._browse_video())

        # Hover effect
        def on_enter(e):
            upload_area.configure(border_color=Colors.ACCENT_PRIMARY)

        def on_leave(e):
            upload_area.configure(border_color=Colors.BORDER)

        upload_area.bind("<Enter>", on_enter)
        upload_area.bind("<Leave>", on_leave)

        ToolTip(
            upload_area, "Click to browse for a video file, or drag and drop directly"
        )

        # Selected file display (hidden initially)
        self.selected_file_frame = ctk.CTkFrame(section, fg_color="transparent")
        # Don't pack yet - shown when file selected

    def _create_analysis_section(self):
        """Create video analysis section"""
        section = ctk.CTkFrame(
            self.main_scroll,
            fg_color=Colors.CARD_BG,
            corner_radius=BorderRadius.LG,
            border_width=1,
            border_color=Colors.BORDER,
        )
        section.pack(fill="x", pady=(0, Spacing.MD))
        section.pack_forget()  # Hidden initially
        self.analysis_section = section

        # Header
        header = ctk.CTkFrame(section, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.MD, pady=(Spacing.MD, Spacing.SM))

        icon_frame = ctk.CTkFrame(
            header,
            width=36,
            height=36,
            fg_color=Colors.INFO,
            corner_radius=BorderRadius.SM,
        )
        icon_frame.pack(side="left")
        icon_frame.pack_propagate(False)
        ctk.CTkLabel(icon_frame, text="🔍", font=ctk.CTkFont(size=18)).place(
            relx=0.5, rely=0.5, anchor="center"
        )

        title_col = ctk.CTkFrame(header, fg_color="transparent")
        title_col.pack(side="left", padx=(Spacing.SM, 0))
        create_styled_label(
            title_col, "Step 2: Video Analysis", style="heading_sm"
        ).pack(anchor="w")
        create_styled_label(
            title_col, "AI will extract audio and generate transcript", style="muted"
        ).pack(anchor="w")

        # Video info display
        info_frame = ctk.CTkFrame(
            section, fg_color=Colors.BG_SECONDARY, corner_radius=BorderRadius.SM
        )
        info_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.SM))

        info_inner = ctk.CTkFrame(info_frame, fg_color="transparent")
        info_inner.pack(fill="x", padx=Spacing.SM, pady=Spacing.SM)

        self.video_info_label = create_styled_label(
            info_inner, "No video selected", style="body"
        )
        self.video_info_label.pack(anchor="w")

        # Analyze button
        btn_frame = ctk.CTkFrame(section, fg_color="transparent")
        btn_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        self.analyze_btn = create_styled_button(
            btn_frame,
            "Analyze Video",
            command=self._analyze_video,
            style="primary",
            width=150,
            height=38,
            tooltip="Extract audio and transcribe using AI (GROQ Whisper)",
            icon="🔬",
        )
        self.analyze_btn.pack(side="left")

        # Progress bar (hidden)
        self.analyze_progress = ctk.CTkProgressBar(
            btn_frame,
            fg_color=Colors.BG_SECONDARY,
            progress_color=Colors.ACCENT_PRIMARY,
        )
        # Don't pack - shown during analysis

    def _create_script_section(self):
        """Create script editing section"""
        section = ctk.CTkFrame(
            self.main_scroll,
            fg_color=Colors.CARD_BG,
            corner_radius=BorderRadius.LG,
            border_width=1,
            border_color=Colors.BORDER,
        )
        section.pack(fill="x", pady=(0, Spacing.MD))
        section.pack_forget()  # Hidden initially
        self.script_section = section

        # Header
        header = ctk.CTkFrame(section, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.MD, pady=(Spacing.MD, Spacing.SM))

        icon_frame = ctk.CTkFrame(
            header,
            width=36,
            height=36,
            fg_color=Colors.SUCCESS,
            corner_radius=BorderRadius.SM,
        )
        icon_frame.pack(side="left")
        icon_frame.pack_propagate(False)
        ctk.CTkLabel(icon_frame, text="📝", font=ctk.CTkFont(size=18)).place(
            relx=0.5, rely=0.5, anchor="center"
        )

        title_col = ctk.CTkFrame(header, fg_color="transparent")
        title_col.pack(side="left", padx=(Spacing.SM, 0))
        create_styled_label(title_col, "Step 3: Edit Script", style="heading_sm").pack(
            anchor="w"
        )
        create_styled_label(
            title_col,
            "Review and modify the AI-generated narration script",
            style="muted",
        ).pack(anchor="w")

        # Regenerate button on right
        regen_btn = create_styled_button(
            header,
            "AI Enhance",
            command=self._regenerate_script,
            style="secondary",
            width=120,
            height=32,
            tooltip="Perbaiki wording tiap segment dengan AI (timing tetap dipertahankan)",
            icon="✨",
        )
        regen_btn.pack(side="right")

        # Script text area
        self.script_text = ctk.CTkTextbox(
            section,
            height=200,
            fg_color=Colors.BG_SECONDARY,
            text_color=Colors.TEXT_PRIMARY,
            font=Fonts.body(),
            corner_radius=BorderRadius.SM,
            border_width=1,
            border_color=Colors.BORDER,
        )
        self.script_text.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        ToolTip(
            self.script_text,
            "Edit the narration script. Each paragraph will be spoken as a separate segment.",
        )

    def _create_voice_section(self):
        """Create voice settings section"""
        section = ctk.CTkFrame(
            self.main_scroll,
            fg_color=Colors.CARD_BG,
            corner_radius=BorderRadius.LG,
            border_width=1,
            border_color=Colors.BORDER,
        )
        section.pack(fill="x", pady=(0, Spacing.MD))
        section.pack_forget()  # Hidden initially
        self.voice_section = section

        # Header
        header = ctk.CTkFrame(section, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.MD, pady=(Spacing.MD, Spacing.SM))

        icon_frame = ctk.CTkFrame(
            header,
            width=36,
            height=36,
            fg_color=Colors.ACCENT_SECONDARY,
            corner_radius=BorderRadius.SM,
        )
        icon_frame.pack(side="left")
        icon_frame.pack_propagate(False)
        ctk.CTkLabel(icon_frame, text="🎤", font=ctk.CTkFont(size=18)).place(
            relx=0.5, rely=0.5, anchor="center"
        )

        title_col = ctk.CTkFrame(header, fg_color="transparent")
        title_col.pack(side="left", padx=(Spacing.SM, 0))
        create_styled_label(
            title_col, "Step 4: Voice Settings", style="heading_sm"
        ).pack(anchor="w")
        create_styled_label(
            title_col, "Configure Edge TTS voice and audio settings", style="muted"
        ).pack(anchor="w")

        # Voice selection
        voice_frame = ctk.CTkFrame(section, fg_color="transparent")
        voice_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.SM))

        # Voice dropdown
        voice_col = ctk.CTkFrame(voice_frame, fg_color="transparent")
        voice_col.pack(side="left", fill="x", expand=True, padx=(0, Spacing.MD))

        create_styled_label(voice_col, "Voice:", style="caption").pack(anchor="w")
        self.voice_var = ctk.StringVar(value="id-ID-ArdiNeural (Male)")
        self.voice_dropdown = ctk.CTkComboBox(
            voice_col,
            values=["id-ID-ArdiNeural (Male)", "id-ID-GadisNeural (Female)"],
            variable=self.voice_var,
            fg_color=Colors.BG_SECONDARY,
            border_color=Colors.BORDER,
            button_color=Colors.ACCENT_PRIMARY,
            dropdown_fg_color=Colors.CARD_BG,
            font=Fonts.body(),
            width=200,
        )
        self.voice_dropdown.pack(anchor="w", pady=(4, 0))
        ToolTip(
            self.voice_dropdown,
            "Select Indonesian voice: Ardi (male) or Gadis (female)",
        )

        # Preview button
        preview_btn = create_styled_button(
            voice_col,
            "Preview",
            command=self._preview_voice,
            style="secondary",
            width=90,
            height=32,
            tooltip="Listen to a sample of the selected voice",
            icon="🔊",
        )
        preview_btn.pack(anchor="w", pady=(Spacing.SM, 0))

        # Speed & Pitch sliders
        sliders_frame = ctk.CTkFrame(section, fg_color="transparent")
        sliders_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.SM))

        # Speed
        speed_col = ctk.CTkFrame(sliders_frame, fg_color="transparent")
        speed_col.pack(side="left", fill="x", expand=True, padx=(0, Spacing.MD))

        speed_header = ctk.CTkFrame(speed_col, fg_color="transparent")
        speed_header.pack(fill="x")
        create_styled_label(speed_header, "Speed:", style="caption").pack(side="left")
        self.speed_value_label = create_styled_label(
            speed_header, "+0%", style="caption", color=Colors.ACCENT_PRIMARY
        )
        self.speed_value_label.pack(side="right")

        self.speed_var = ctk.DoubleVar(value=0)
        self.speed_slider = ctk.CTkSlider(
            speed_col,
            from_=-50,
            to=50,
            variable=self.speed_var,
            command=self._on_speed_change,
            fg_color=Colors.BG_SECONDARY,
            progress_color=Colors.ACCENT_PRIMARY,
            button_color=Colors.ACCENT_PRIMARY,
            button_hover_color=Colors.BTN_PRIMARY_HOVER,
        )
        self.speed_slider.pack(fill="x", pady=(4, 0))
        ToolTip(
            self.speed_slider, "Adjust speaking speed: -50% (slower) to +50% (faster)"
        )

        # Pitch
        pitch_col = ctk.CTkFrame(sliders_frame, fg_color="transparent")
        pitch_col.pack(side="left", fill="x", expand=True)

        pitch_header = ctk.CTkFrame(pitch_col, fg_color="transparent")
        pitch_header.pack(fill="x")
        create_styled_label(pitch_header, "Pitch:", style="caption").pack(side="left")
        self.pitch_value_label = create_styled_label(
            pitch_header, "+0Hz", style="caption", color=Colors.ACCENT_PRIMARY
        )
        self.pitch_value_label.pack(side="right")

        self.pitch_var = ctk.DoubleVar(value=0)
        self.pitch_slider = ctk.CTkSlider(
            pitch_col,
            from_=-20,
            to=20,
            variable=self.pitch_var,
            command=self._on_pitch_change,
            fg_color=Colors.BG_SECONDARY,
            progress_color=Colors.ACCENT_PRIMARY,
            button_color=Colors.ACCENT_PRIMARY,
            button_hover_color=Colors.BTN_PRIMARY_HOVER,
        )
        self.pitch_slider.pack(fill="x", pady=(4, 0))
        ToolTip(
            self.pitch_slider, "Adjust voice pitch: -20Hz (lower) to +20Hz (higher)"
        )

        # Audio mix settings
        mix_frame = ctk.CTkFrame(
            section, fg_color=Colors.BG_SECONDARY, corner_radius=BorderRadius.SM
        )
        mix_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        mix_inner = ctk.CTkFrame(mix_frame, fg_color="transparent")
        mix_inner.pack(fill="x", padx=Spacing.SM, pady=Spacing.SM)

        self.keep_audio_var = ctk.BooleanVar(value=True)
        keep_cb = ctk.CTkCheckBox(
            mix_inner,
            text="Keep original audio as background",
            variable=self.keep_audio_var,
            font=Fonts.body_sm(),
            fg_color=Colors.ACCENT_PRIMARY,
            hover_color=Colors.BTN_PRIMARY_HOVER,
            border_color=Colors.BORDER,
        )
        keep_cb.pack(anchor="w")
        ToolTip(
            keep_cb, "Mix original audio with TTS voiceover (reduces original volume)"
        )

        # Background volume
        vol_frame = ctk.CTkFrame(mix_inner, fg_color="transparent")
        vol_frame.pack(fill="x", pady=(Spacing.SM, 0))

        create_styled_label(vol_frame, "Background Volume:", style="caption").pack(
            side="left"
        )
        self.bg_volume_var = ctk.DoubleVar(value=20)
        self.bg_volume_slider = ctk.CTkSlider(
            vol_frame,
            from_=0,
            to=100,
            width=150,
            variable=self.bg_volume_var,
            command=self._on_volume_change,
            fg_color=Colors.BG_PRIMARY,
            progress_color=Colors.ACCENT_SECONDARY,
            button_color=Colors.ACCENT_SECONDARY,
        )
        self.bg_volume_slider.pack(side="left", padx=(Spacing.SM, Spacing.SM))

        self.volume_value_label = create_styled_label(
            vol_frame, "20%", style="caption", color=Colors.ACCENT_SECONDARY
        )
        self.volume_value_label.pack(side="left")
        ToolTip(
            self.bg_volume_slider, "Volume level for original background audio (0-100%)"
        )

        # ---- Background Music (BGM) from TikTok/URL ----
        bgm_frame = ctk.CTkFrame(
            section, fg_color=Colors.BG_SECONDARY, corner_radius=BorderRadius.SM
        )
        bgm_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        bgm_inner = ctk.CTkFrame(bgm_frame, fg_color="transparent")
        bgm_inner.pack(fill="x", padx=Spacing.SM, pady=Spacing.SM)

        bgm_header = ctk.CTkFrame(bgm_inner, fg_color="transparent")
        bgm_header.pack(fill="x")
        create_styled_label(
            bgm_header, "🎵 Background Music (Optional)", style="caption"
        ).pack(side="left")

        # URL input
        url_frame = ctk.CTkFrame(bgm_inner, fg_color="transparent")
        url_frame.pack(fill="x", pady=(Spacing.SM, 0))

        create_styled_label(url_frame, "TikTok / YouTube URL:", style="caption").pack(
            anchor="w"
        )
        self.bgm_url_var = ctk.StringVar(value="")
        self.bgm_url_entry = ctk.CTkEntry(
            url_frame,
            textvariable=self.bgm_url_var,
            fg_color=Colors.BG_PRIMARY,
            border_color=Colors.BORDER,
            font=Fonts.body_sm(),
            placeholder_text="Paste TikTok or YouTube URL to use as BGM...",
            height=32,
        )
        self.bgm_url_entry.pack(fill="x", pady=(4, 0))
        ToolTip(
            self.bgm_url_entry,
            "Paste a TikTok or YouTube link — audio will be extracted as background music",
        )

        # BGM Volume slider
        bgm_vol_frame = ctk.CTkFrame(bgm_inner, fg_color="transparent")
        bgm_vol_frame.pack(fill="x", pady=(Spacing.SM, 0))

        create_styled_label(bgm_vol_frame, "BGM Volume:", style="caption").pack(
            side="left"
        )
        self.bgm_volume_var = ctk.DoubleVar(value=15)
        self.bgm_volume_slider = ctk.CTkSlider(
            bgm_vol_frame,
            from_=0,
            to=100,
            width=150,
            variable=self.bgm_volume_var,
            command=self._on_bgm_volume_change,
            fg_color=Colors.BG_PRIMARY,
            progress_color=Colors.ACCENT_SECONDARY,
            button_color=Colors.ACCENT_SECONDARY,
        )
        self.bgm_volume_slider.pack(side="left", padx=(Spacing.SM, Spacing.SM))

        self.bgm_volume_label = create_styled_label(
            bgm_vol_frame, "15%", style="caption", color=Colors.ACCENT_SECONDARY
        )
        self.bgm_volume_label.pack(side="left")
        ToolTip(self.bgm_volume_slider, "Volume level for background music (0-100%)")

    def _create_output_section(self):
        """Create output settings section"""
        section = ctk.CTkFrame(
            self.main_scroll,
            fg_color=Colors.CARD_BG,
            corner_radius=BorderRadius.LG,
            border_width=1,
            border_color=Colors.BORDER,
        )
        section.pack(fill="x", pady=(0, Spacing.MD))
        section.pack_forget()  # Hidden initially
        self.output_section = section

        # Header
        header = ctk.CTkFrame(section, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.MD, pady=(Spacing.MD, Spacing.SM))

        icon_frame = ctk.CTkFrame(
            header,
            width=36,
            height=36,
            fg_color=Colors.WARNING,
            corner_radius=BorderRadius.SM,
        )
        icon_frame.pack(side="left")
        icon_frame.pack_propagate(False)
        ctk.CTkLabel(icon_frame, text="💾", font=ctk.CTkFont(size=18)).place(
            relx=0.5, rely=0.5, anchor="center"
        )

        title_col = ctk.CTkFrame(header, fg_color="transparent")
        title_col.pack(side="left", padx=(Spacing.SM, 0))
        create_styled_label(
            title_col, "Step 5: Output Settings", style="heading_sm"
        ).pack(anchor="w")
        create_styled_label(
            title_col, "Configure subtitle style and output location", style="muted"
        ).pack(anchor="w")

        # Subtitle settings
        sub_frame = ctk.CTkFrame(section, fg_color="transparent")
        sub_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.SM))

        self.burn_subtitle_var = ctk.BooleanVar(value=True)
        sub_cb = ctk.CTkCheckBox(
            sub_frame,
            text="Burn subtitles into video",
            variable=self.burn_subtitle_var,
            font=Fonts.body_sm(),
            fg_color=Colors.ACCENT_PRIMARY,
            hover_color=Colors.BTN_PRIMARY_HOVER,
            border_color=Colors.BORDER,
        )
        sub_cb.pack(anchor="w")
        ToolTip(
            sub_cb,
            "Embed subtitle text directly into the video (recommended for social media)",
        )

        # Remove hardcoded subtitle settings
        remove_sub_frame = ctk.CTkFrame(
            section, fg_color=Colors.BG_SECONDARY, corner_radius=BorderRadius.SM
        )
        remove_sub_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.SM))

        remove_sub_inner = ctk.CTkFrame(remove_sub_frame, fg_color="transparent")
        remove_sub_inner.pack(fill="x", padx=Spacing.SM, pady=Spacing.SM)

        self.remove_subs_var = ctk.BooleanVar(value=False)
        remove_sub_cb = ctk.CTkCheckBox(
            remove_sub_inner,
            text="🧹 Remove hardcoded subtitles from source",
            variable=self.remove_subs_var,
            font=Fonts.body_sm(),
            fg_color=Colors.WARNING,
            hover_color=Colors.BTN_SUCCESS_HOVER,
            border_color=Colors.BORDER,
            command=self._toggle_sub_removal,
        )
        remove_sub_cb.pack(anchor="w")
        ToolTip(
            remove_sub_cb,
            "Remove burned-in subtitles from the original video before dubbing (blur or black fill)",
        )

        # Sub-options (hidden by default)
        self.sub_removal_options = ctk.CTkFrame(
            remove_sub_inner, fg_color="transparent"
        )

        # Region selector
        region_row = ctk.CTkFrame(self.sub_removal_options, fg_color="transparent")
        region_row.pack(fill="x", pady=(Spacing.XS, 0))

        create_styled_label(region_row, "Region:", style="caption").pack(side="left")
        self.sub_region_var = ctk.StringVar(value="Bottom")
        region_menu = ctk.CTkOptionMenu(
            region_row,
            variable=self.sub_region_var,
            values=["Bottom", "Top", "Both"],
            width=100,
            height=28,
            font=Fonts.body_sm(),
            fg_color=Colors.BG_PRIMARY,
            button_color=Colors.ACCENT_PRIMARY,
            button_hover_color=Colors.BTN_PRIMARY_HOVER,
        )
        region_menu.pack(side="left", padx=(Spacing.SM, Spacing.MD))
        ToolTip(region_menu, "Where are the subtitles located?")

        # Method selector
        create_styled_label(region_row, "Method:", style="caption").pack(side="left")
        self.sub_method_var = ctk.StringVar(value="Delogo")
        method_menu = ctk.CTkOptionMenu(
            region_row,
            variable=self.sub_method_var,
            values=["Delogo", "Blur", "Black"],
            width=90,
            height=28,
            font=Fonts.body_sm(),
            fg_color=Colors.BG_PRIMARY,
            button_color=Colors.ACCENT_PRIMARY,
            button_hover_color=Colors.BTN_PRIMARY_HOVER,
        )
        method_menu.pack(side="left", padx=(Spacing.SM, Spacing.MD))
        ToolTip(
            method_menu,
            "Delogo: interpolate pixels (cleanest) | Blur: gaussian blur | Black: fill black",
        )

        # Coverage slider (height of removal band)
        pct_row = ctk.CTkFrame(self.sub_removal_options, fg_color="transparent")
        pct_row.pack(fill="x", pady=(Spacing.XS, 0))

        create_styled_label(pct_row, "Coverage:", style="caption").pack(side="left")
        self.sub_region_pct_var = ctk.DoubleVar(value=12)
        pct_slider = ctk.CTkSlider(
            pct_row,
            from_=5,
            to=35,
            width=120,
            variable=self.sub_region_pct_var,
            command=self._on_sub_pct_change,
            fg_color=Colors.BG_PRIMARY,
            progress_color=Colors.WARNING,
            button_color=Colors.WARNING,
        )
        pct_slider.pack(side="left", padx=(Spacing.SM, Spacing.SM))
        ToolTip(pct_slider, "Height of removal band (5-35% of frame)")

        self.sub_pct_label = create_styled_label(
            pct_row, "12%", style="caption", color=Colors.WARNING
        )
        self.sub_pct_label.pack(side="left")

        # Offset slider (shift band inward from edge)
        offset_row = ctk.CTkFrame(self.sub_removal_options, fg_color="transparent")
        offset_row.pack(fill="x", pady=(Spacing.XS, 0))

        create_styled_label(offset_row, "Offset:", style="caption").pack(side="left")
        self.sub_offset_var = ctk.DoubleVar(value=0)
        offset_slider = ctk.CTkSlider(
            offset_row,
            from_=0,
            to=40,
            width=120,
            variable=self.sub_offset_var,
            command=self._on_sub_offset_change,
            fg_color=Colors.BG_PRIMARY,
            progress_color=Colors.WARNING,
            button_color=Colors.WARNING,
        )
        offset_slider.pack(side="left", padx=(Spacing.SM, Spacing.SM))
        ToolTip(
            offset_slider,
            "Shift removal band inward from edge (0-40%). Use when subtitle is not at the very edge — e.g. offset 10% moves band up from bottom",
        )

        self.sub_offset_label = create_styled_label(
            offset_row, "0%", style="caption", color=Colors.WARNING
        )
        self.sub_offset_label.pack(side="left")

        # Output folder
        folder_frame = ctk.CTkFrame(section, fg_color="transparent")
        folder_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        create_styled_label(folder_frame, "Output Folder:", style="caption").pack(
            anchor="w"
        )

        folder_row = ctk.CTkFrame(folder_frame, fg_color="transparent")
        folder_row.pack(fill="x", pady=(4, 0))

        output_dir = (
            self.config.get("output_dir", "output")
            if hasattr(self.config, "get")
            else "output"
        )
        display_path = (
            output_dir[:45] + "..." if len(str(output_dir)) > 45 else str(output_dir)
        )

        self.output_path_label = ctk.CTkLabel(
            folder_row,
            text=display_path,
            font=Fonts.mono(),
            text_color=Colors.TEXT_SECONDARY,
            fg_color=Colors.BG_SECONDARY,
            corner_radius=BorderRadius.SM,
            padx=Spacing.SM,
            pady=Spacing.XS,
        )
        self.output_path_label.pack(side="left", fill="x", expand=True)

        browse_btn = create_styled_button(
            folder_row,
            "Browse",
            command=self._browse_output,
            style="secondary",
            width=80,
            height=32,
            tooltip="Choose output folder location",
            icon="📂",
        )
        browse_btn.pack(side="left", padx=(Spacing.SM, 0))

    def _create_action_buttons(self):
        """Create bottom action buttons"""
        action_frame = ctk.CTkFrame(self.main_scroll, fg_color="transparent")
        action_frame.pack(fill="x", pady=Spacing.MD)

        # Center the buttons
        btn_container = ctk.CTkFrame(action_frame, fg_color="transparent")
        btn_container.pack()

        # Generate button
        self.generate_btn = create_styled_button(
            btn_container,
            "Generate Dubbed Video",
            command=self._generate_video,
            style="primary",
            width=220,
            height=44,
            tooltip="Process video with AI voiceover (may take several minutes)",
            icon="🚀",
        )
        self.generate_btn.pack(side="left", padx=Spacing.SM)
        self.generate_btn.configure(state="disabled")  # Disabled until ready

        # Reset button
        reset_btn = create_styled_button(
            btn_container,
            "Reset",
            command=self._reset_all,
            style="ghost",
            width=100,
            height=44,
            tooltip="Clear all settings and start over",
            icon="🗑️",
        )
        reset_btn.pack(side="left", padx=Spacing.SM)

    # ==========================================================================
    # PROGRESS HELPERS
    # ==========================================================================

    def _show_progress(self):
        """Show global progress bar"""
        self.progress_container.pack(fill="x", pady=(0, Spacing.SM))
        self.global_progress_bar.set(0)
        self.progress_percent_label.configure(text="0%")
        self.progress_status_label.configure(text="Starting...")

    def _hide_progress(self):
        """Hide global progress bar"""
        self.progress_container.pack_forget()

    def _update_progress(self, percent: float, status: str = ""):
        """Thread-safe progress update (0-100)"""

        def _do():
            clamped = max(0, min(100, percent))
            self.global_progress_bar.set(clamped / 100.0)
            self.progress_percent_label.configure(text=f"{int(clamped)}%")
            if status:
                self.progress_status_label.configure(text=status)

        self.after(0, _do)

    # ==========================================================================
    # EVENT HANDLERS
    # ==========================================================================

    def _browse_video(self):
        """Open file dialog to select video"""
        filetypes = [
            ("Video files", "*.mp4 *.mkv *.avi *.mov *.webm *.m4v"),
            ("All files", "*.*"),
        ]

        filepath = filedialog.askopenfilename(
            title="Select Video File", filetypes=filetypes
        )

        if filepath:
            self.current_video_path = filepath
            self._show_selected_file(filepath)
            self._update_step(1)
            self.analysis_section.pack(
                fill="x", pady=(0, Spacing.MD), after=self.upload_section
            )

    def _show_selected_file(self, filepath):
        """Display selected file info"""
        filename = os.path.basename(filepath)
        size_mb = os.path.getsize(filepath) / (1024 * 1024)

        self.video_info_label.configure(text=f"📹 {filename}  |  {size_mb:.1f} MB")

    # ==================================================================
    # TIMED SCRIPT FORMAT HELPERS
    # ==================================================================

    def _format_timed_script(self, segments) -> str:
        """Format transcript segments into editable timed script.

        Format:  [MM:SS - MM:SS] Segment text here
        Each line = one segment. User can edit text, timestamps are reference.
        """
        lines = []
        for seg in segments:
            start = seg.start if hasattr(seg, "start") else seg.get("start", 0)
            end = seg.end if hasattr(seg, "end") else seg.get("end", start + 3)
            text = seg.text if hasattr(seg, "text") else seg.get("text", "")
            text = text.strip()
            if not text:
                continue
            s_mm, s_ss = int(start // 60), int(start % 60)
            e_mm, e_ss = int(end // 60), int(end % 60)
            lines.append(f"[{s_mm:02d}:{s_ss:02d} - {e_mm:02d}:{e_ss:02d}] {text}")
        return "\n".join(lines)

    def _parse_timed_script(self, script_text: str) -> list:
        """Parse timed script back into segment dicts.

        Handles both timed format [MM:SS - MM:SS] text
        and plain text (fallback: distribute evenly across video duration).
        """
        import re

        lines = [l.strip() for l in script_text.strip().split("\n") if l.strip()]
        if not lines:
            return []

        segments = []
        timed_pattern = re.compile(
            r"\[(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\]\s*(.+)"
        )

        for line in lines:
            match = timed_pattern.match(line)
            if match:
                s_m, s_s, e_m, e_s, text = match.groups()
                start = int(s_m) * 60 + int(s_s)
                end = int(e_m) * 60 + int(e_s)
                if text.strip():
                    segments.append(
                        {"text": text.strip(), "start": float(start), "end": float(end)}
                    )
            else:
                # Plain text line — no timestamp
                segments.append({"text": line, "start": -1, "end": -1})

        # Handle plain-text-only (no timestamps): distribute evenly
        untimed = [s for s in segments if s["start"] < 0]
        if untimed and self.video_info:
            duration = self.video_info.duration
            slot = duration / max(len(untimed), 1)
            for i, seg in enumerate(untimed):
                seg["start"] = i * slot
                seg["end"] = (i + 1) * slot
        elif untimed:
            # Fallback: 5s per segment
            for i, seg in enumerate(untimed):
                seg["start"] = i * 5.0
                seg["end"] = (i + 1) * 5.0

        return segments

    def _translate_segments(
        self, segments, source_lang, config_dict, progress_callback=None
    ):
        """Translate transcript segments to Indonesian using LLM.

        Preserves timing structure. Handles content-aware translation:
        - Translates each segment's text naturally
        - Proportional word count (short segment = few words)
        - Filters out dead/filler content (e.g. 15s of just 'thank you')
        """
        from openai import OpenAI
        from config.config_manager import get_api_key_from_env, detect_provider_from_url
        import json

        ai_providers = config_dict.get("ai_providers", {})
        llm_config = ai_providers.get(
            "script_generator", ai_providers.get("highlight_finder", {})
        )

        base_url = llm_config.get("base_url", "https://api.groq.com/openai/v1")
        config_key = llm_config.get("api_key", "")
        model = llm_config.get("model", "llama-3.3-70b-versatile")
        provider = detect_provider_from_url(base_url)
        api_key = get_api_key_from_env(provider, config_key)

        if not api_key:
            raise ValueError(f"No API key found for {provider}")

        client = OpenAI(api_key=api_key, base_url=base_url)

        # Build segment list for prompt
        seg_list = []
        for i, seg in enumerate(segments):
            start = seg.start if hasattr(seg, "start") else seg.get("start", 0)
            end = seg.end if hasattr(seg, "end") else seg.get("end", 0)
            text = seg.text if hasattr(seg, "text") else seg.get("text", "")
            text = text.strip()
            if not text:
                continue
            dur = end - start
            seg_list.append(f'{i + 1}. [{start:.1f}s-{end:.1f}s] ({dur:.1f}s) "{text}"')

        if not seg_list:
            return segments

        if progress_callback:
            progress_callback(f"Translating {len(seg_list)} segments to Indonesian...")

        prompt = f"""Kamu adalah dubber/pengisi suara profesional yang menerjemahkan narasi video dari {source_lang} ke Bahasa Indonesia.

TRANSKRIP VIDEO (dengan timing per segment):

{chr(10).join(seg_list)}

ATURAN TRANSLASI DUBBING:
1. Terjemahkan ke Bahasa Indonesia SEHARI-HARI yang enak didengar, BUKAN terjemahan kaku/literal
   - SALAH: "bertabrakan dengan toko minuman keras" (literal dari "crashed into a liquor store")
   - BENAR: "nyemplung masuk ke toko minuman" atau "nyasar masuk ke toko miras"
2. PERTAHANKAN jumlah segment yang sama (jangan gabung/hapus/tambah)
3. Panjang teks hasil HARUS proporsional dengan durasi segment agar sinkron saat di-dubbing:
   - Segment 2-3 detik: 5-12 kata
   - Segment 4-6 detik: 12-22 kata
   - Segment 7-10 detik: 22-35 kata 
4. Gunakan kata-kata UMUM yang dipahami orang awam:
   - "hangover" → "mabuknya" atau "efek mabuknya"
   - "liquor store" → "toko miras" atau "toko minuman keras" 
   - "passed out" → "pingsan" atau "terkapar"
   - "crash into" → "nyasar masuk" atau "menerobos masuk"
5. ALUR CERITA harus NYAMBUNG antar segment:
   - Tiap segment harus melanjutkan kalimat sebelumnya secara logis
   - Jangan ada lompatan cerita yang ganjil
   - Gunakan kata penghubung yang natural: "Terus...", "Nah...", "Sampai akhirnya..."
6. Jika segment terakhir = outro ("thanks for watching", "subscribe"):
   - Terjemahkan singkat: "Terima kasih sudah menonton!"
7. Segment yang TERLALU sedikit kata untuk durasinya (misal 2 kata untuk 10 detik):
   - Tandai [SKIP]
8. Pertahankan TONE asli (lucu, dramatis, seru) — ini untuk dubbing bukan artikel
9. Bayangkan kamu sedang BERCERITA ke teman, pakai gaya bicara narrator YouTube Indonesia

FORMAT OUTPUT — JSON array SAJA, tanpa penjelasan:
[
  {{"id": 1, "text": "Terjemahan segment 1"}},
  {{"id": 2, "text": "Terjemahan segment 2"}}
]"""

        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "Kamu translator dubbing profesional. Output selalu JSON valid.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.5,
            max_tokens=3000,
        )

        result_text = response.choices[0].message.content.strip()

        # Parse JSON
        if "```" in result_text:
            result_text = result_text.split("```")[1]
            if result_text.startswith("json"):
                result_text = result_text[4:]
        result_text = result_text.strip()

        try:
            translated = json.loads(result_text)
        except json.JSONDecodeError:
            print(f"[DUBBING WARN] Translation JSON parse failed, using original")
            return segments

        # Build translated segments
        result_segments = []
        for i, seg in enumerate(segments):
            start = seg.start if hasattr(seg, "start") else seg.get("start", 0)
            end = seg.end if hasattr(seg, "end") else seg.get("end", 0)
            original_text = seg.text if hasattr(seg, "text") else seg.get("text", "")

            # Find matching translation
            new_text = original_text  # fallback
            for t in translated:
                if t.get("id") == i + 1:
                    txt = t.get("text", "").strip()
                    if txt.upper().startswith("[SKIP]"):
                        # Skip this segment (dead air / filler)
                        continue
                    if txt:
                        new_text = txt
                    break
            else:
                # No translation found, still include original
                pass

            result_segments.append(
                {"text": new_text.strip(), "start": start, "end": end}
            )

        return result_segments

    def _detect_language(self, text: str) -> str:
        """Simple language detection based on common words."""
        text_lower = text.lower()
        # Indonesian markers
        id_words = [
            "yang",
            "dan",
            "di",
            "ini",
            "itu",
            "untuk",
            "dengan",
            "dari",
            "adalah",
            "tidak",
            "akan",
            "juga",
            "sudah",
            "ada",
            "bisa",
            "seperti",
            "karena",
            "tapi",
            "atau",
            "saya",
            "mereka",
            "kami",
            "kalau",
            "mau",
            "kita",
            "apa",
            "lagi",
            "udah",
            "gak",
            "gue",
        ]
        # English markers
        en_words = [
            "the",
            "and",
            "was",
            "that",
            "this",
            "with",
            "for",
            "are",
            "but",
            "not",
            "you",
            "all",
            "can",
            "had",
            "her",
            "one",
            "from",
            "they",
            "been",
            "have",
            "its",
            "into",
            "each",
            "which",
            "their",
            "would",
            "there",
            "could",
            "more",
        ]

        words = text_lower.split()
        if not words:
            return "unknown"

        id_count = sum(1 for w in words if w.strip(".,!?;:") in id_words)
        en_count = sum(1 for w in words if w.strip(".,!?;:") in en_words)

        total = len(words)
        id_ratio = id_count / total
        en_ratio = en_count / total

        if id_ratio > 0.08:
            return "id"
        elif en_ratio > 0.08:
            return "en"
        else:
            return "unknown"

    # ==================================================================
    # ANALYSIS FLOW
    # ==================================================================

    def _analyze_video(self):
        """Analyze video: extract audio → transcribe → auto-translate if needed → show timed segments.

        Uses the transcript segments (with timing) as the script base.
        If source language is not Indonesian, automatically translates to ID.
        """
        if not self.current_video_path:
            messagebox.showwarning("No Video", "Please select a video file first.")
            return

        if self.is_processing:
            messagebox.showinfo("Busy", "Processing is already running.")
            return

        self.is_processing = True
        self._cancel_flag = False
        self.analyze_btn.configure(state="disabled", text="⏳ Analyzing...")
        self._show_progress()

        def run_analysis():
            try:
                from video_analyzer import VideoAnalyzer

                config_dict = self._get_config_dict()
                analyzer = VideoAnalyzer(config_dict)

                # Step 1: Video metadata (5%)
                self._update_progress(5, "📊 Extracting video metadata...")
                video_info = analyzer.get_video_info(self.current_video_path)
                self.video_info = video_info

                if self._cancel_flag:
                    return

                duration_str = (
                    f"{int(video_info.duration // 60)}m{int(video_info.duration % 60)}s"
                )
                self.after(
                    0,
                    lambda: self.video_info_label.configure(
                        text=f"📹 {os.path.basename(self.current_video_path)}  |  "
                        f"{video_info.width}x{video_info.height}  |  "
                        f"{duration_str}  |  Audio: {'✓' if video_info.has_audio else '✗'}"
                    ),
                )

                if not video_info.has_audio:
                    self.after(
                        0,
                        lambda: messagebox.showwarning(
                            "No Audio",
                            "Video has no audio track. Transcription will be skipped.",
                        ),
                    )
                    self._update_progress(70, "⚠️ No audio — skipping transcription...")
                    self.transcript = ""
                    self.transcript_segments = []
                else:
                    # Step 2: Extract audio (15%)
                    self._update_progress(15, "🎵 Extracting audio from video...")
                    import tempfile

                    temp_dir = tempfile.mkdtemp()
                    audio_path = os.path.join(temp_dir, "audio.mp3")
                    analyzer.extract_audio(self.current_video_path, audio_path)

                    if self._cancel_flag:
                        return

                    # Step 3: Transcribe — auto-detect language (30-55%)
                    self._update_progress(
                        30, "🎤 Transcribing audio (auto-detect language)..."
                    )

                    def transcribe_progress(msg):
                        self._update_progress(45, f"🎤 {msg}")

                    # Don't force language — let Whisper auto-detect
                    segments, full_text = analyzer.transcribe_audio(
                        audio_path, None, transcribe_progress
                    )

                    self.transcript = full_text
                    self.transcript_segments = segments

                    # Cleanup temp audio
                    try:
                        os.remove(audio_path)
                        os.rmdir(temp_dir)
                    except:
                        pass

                if self._cancel_flag:
                    return

                # Step 4: Detect language & translate if needed (55-85%)
                translated_segments = None

                if self.transcript and self.transcript_segments:
                    detected_lang = self._detect_language(self.transcript)
                    print(f"[DUBBING] Detected language: {detected_lang}")

                    if detected_lang != "id":
                        # Source is NOT Indonesian → translate to ID
                        lang_name = {"en": "English", "unknown": "non-Indonesian"}.get(
                            detected_lang, detected_lang
                        )
                        self._update_progress(
                            60,
                            f"🌐 Detected {lang_name} → Translating to Indonesian...",
                        )

                        translated_segments = self._translate_segments(
                            self.transcript_segments,
                            lang_name,
                            config_dict,
                            progress_callback=lambda msg: self._update_progress(
                                72, f"🌐 {msg}"
                            ),
                        )

                        self._update_progress(
                            83,
                            f"🌐 Translation complete! ({len(translated_segments)} segments)",
                        )
                    else:
                        self._update_progress(
                            83, "🇮🇩 Audio sudah dalam Bahasa Indonesia"
                        )

                # Step 5: Format as timed script (85-95%)
                self._update_progress(87, "📝 Formatting timed script...")

                source_segments = translated_segments or self.transcript_segments

                if source_segments:
                    # Filter out dead/filler segments: if text is too short for duration
                    filtered = []
                    for seg in source_segments:
                        text = (
                            seg.get("text", "")
                            if isinstance(seg, dict)
                            else (seg.text if hasattr(seg, "text") else "")
                        )
                        start = (
                            seg.get("start", 0)
                            if isinstance(seg, dict)
                            else (seg.start if hasattr(seg, "start") else 0)
                        )
                        end = (
                            seg.get("end", 0)
                            if isinstance(seg, dict)
                            else (seg.end if hasattr(seg, "end") else 0)
                        )
                        text = text.strip()
                        dur = end - start

                        if not text:
                            continue

                        # Skip segment if text is way too short for its duration
                        # (e.g., 3 words for 15 seconds = dead air / outro)
                        word_count = len(text.split())
                        if dur > 5 and word_count < 4 and dur / max(word_count, 1) > 3:
                            print(
                                f"[DUBBING] Skipping dead segment [{start:.1f}-{end:.1f}] '{text}' (too sparse)"
                            )
                            continue

                        filtered.append(seg)

                    timed_script = self._format_timed_script(filtered)
                    self.generated_script = timed_script
                    self._update_progress(93, f"📝 {len(filtered)} segments ready")
                else:
                    self.generated_script = (
                        "(No audio detected — please write your script manually)"
                    )

                # Step 6: Complete (100%)
                self._update_progress(
                    100, "✅ Analysis complete! Review the timed script below."
                )

                self.after(500, self._on_analysis_complete)

            except Exception as e:
                error_msg = str(e)
                tb = traceback.format_exc()
                print(f"[DUBBING ERROR] Analysis failed:\n{tb}")
                self.after(
                    0,
                    lambda: self._on_analysis_error(
                        f"{error_msg}\n\nDetail:\n{tb[:500]}"
                    ),
                )
            finally:
                self.is_processing = False

        threading.Thread(target=run_analysis, daemon=True).start()

    def _on_analysis_complete(self):
        """Handle analysis completion"""
        self.analyze_btn.configure(state="normal", text="✅ Analyzed")
        self._update_step(2)

        # Show next sections
        self.script_section.pack(
            fill="x", pady=(0, Spacing.MD), after=self.analysis_section
        )
        self.voice_section.pack(
            fill="x", pady=(0, Spacing.MD), after=self.script_section
        )
        self.output_section.pack(
            fill="x", pady=(0, Spacing.MD), after=self.voice_section
        )

        # Populate script text
        self.script_text.delete("1.0", "end")
        if self.generated_script:
            self.script_text.insert("1.0", self.generated_script)

        # Enable generate button
        self.generate_btn.configure(state="normal")

        # Hide progress after a moment
        self.after(2000, self._hide_progress)

    def _on_analysis_error(self, error):
        """Handle analysis error"""
        self.analyze_btn.configure(state="normal", text="🔬 Analyze Video")
        self.is_processing = False
        self._update_progress(0, f"❌ Error: {error[:80]}")
        self.after(3000, self._hide_progress)
        messagebox.showerror("Analysis Error", f"Failed to analyze video:\n\n{error}")

    def _regenerate_script(self):
        """Regenerate script via AI — cleans up wording while preserving timing.

        Uses LLM to improve each segment's text while keeping the same
        timestamp structure, so voiceover still matches video duration.
        """
        if not self.transcript_segments and not self.transcript:
            messagebox.showwarning("No Data", "Please analyze a video first.")
            return

        if self.is_processing:
            messagebox.showinfo("Busy", "Processing is already running.")
            return

        if not messagebox.askyesno(
            "AI Script Enhancement",
            "AI akan memperbaiki wording tiap segment sambil mempertahankan timing.\n"
            "Script saat ini akan diganti. Lanjutkan?",
        ):
            return

        self.is_processing = True
        self._show_progress()

        def run_regen():
            try:
                from openai import OpenAI
                from config.config_manager import (
                    get_api_key_from_env,
                    detect_provider_from_url,
                )
                import json

                config_dict = self._get_config_dict()
                ai_providers = config_dict.get("ai_providers", {})
                llm_config = ai_providers.get(
                    "script_generator", ai_providers.get("highlight_finder", {})
                )

                base_url = llm_config.get("base_url", "https://api.groq.com/openai/v1")
                config_key = llm_config.get("api_key", "")
                model = llm_config.get("model", "llama-3.3-70b-versatile")
                provider = detect_provider_from_url(base_url)
                api_key = get_api_key_from_env(provider, config_key)

                if not api_key:
                    raise ValueError(f"No API key found for {provider}")

                client = OpenAI(api_key=api_key, base_url=base_url)

                # Parse current script to get segments
                current_text = self.script_text.get("1.0", "end").strip()
                segments = self._parse_timed_script(current_text)

                if not segments:
                    raise ValueError("No segments to enhance")

                self._update_progress(
                    10, f"🔄 Enhancing {len(segments)} segments with AI..."
                )

                # Build prompt with all segments for batch processing
                seg_list = []
                for i, seg in enumerate(segments):
                    seg_list.append(
                        f"{i + 1}. [{seg['start']:.1f}s - {seg['end']:.1f}s] {seg['text']}"
                    )

                prompt = f"""Kamu adalah editor script dubbing profesional Bahasa Indonesia.

Berikut transcript video yang sudah di-segment dengan timing:

{chr(10).join(seg_list)}

TUGAS:
- Perbaiki wording setiap segment agar lebih natural dan enak didengar
- JANGAN mengubah makna/informasi dari tiap segment
- JANGAN menggabung atau menghapus segment
- JANGAN menambah segment baru
- Pertahankan panjang text yang PROPORSIONAL dengan durasi segment
  (segment 3 detik = kata sedikit, segment 10 detik = kata lebih banyak)
- Output HANYA JSON array, tanpa penjelasan

FORMAT OUTPUT (JSON array):
[
  {{"id": 1, "text": "Text segment 1 yang sudah diperbaiki"}},
  {{"id": 2, "text": "Text segment 2 yang sudah diperbaiki"}}
]"""

                self._update_progress(30, "🔄 Waiting for AI response...")

                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": "Kamu editor script dubbing. Output selalu JSON valid.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.5,
                    max_tokens=3000,
                )

                result_text = response.choices[0].message.content.strip()

                # Parse JSON
                if "```" in result_text:
                    result_text = result_text.split("```")[1]
                    if result_text.startswith("json"):
                        result_text = result_text[4:]
                result_text = result_text.strip()

                enhanced = json.loads(result_text)

                # Apply enhanced text to segments while keeping timing
                for item in enhanced:
                    idx = item.get("id", 0) - 1
                    if 0 <= idx < len(segments):
                        segments[idx]["text"] = item["text"].strip()

                # Rebuild timed script
                lines = []
                for seg in segments:
                    s_m, s_s = int(seg["start"] // 60), int(seg["start"] % 60)
                    e_m, e_s = int(seg["end"] // 60), int(seg["end"] % 60)
                    lines.append(
                        f"[{s_m:02d}:{s_s:02d} - {e_m:02d}:{e_s:02d}] {seg['text']}"
                    )

                self.generated_script = "\n".join(lines)
                self._update_progress(100, "✅ Script enhanced!")

                def update_ui():
                    self.script_text.delete("1.0", "end")
                    self.script_text.insert("1.0", self.generated_script)
                    self.after(2000, self._hide_progress)

                self.after(0, update_ui)

            except Exception as e:
                tb = traceback.format_exc()
                print(f"[DUBBING ERROR] Script enhancement failed:\n{tb}")
                self.after(
                    0,
                    lambda: messagebox.showerror(
                        "Enhancement Error", f"Failed to enhance script:\n{e}"
                    ),
                )
                self.after(0, self._hide_progress)
            finally:
                self.is_processing = False

        threading.Thread(target=run_regen, daemon=True).start()

    def _preview_voice(self):
        """Preview selected voice"""

        def run_preview():
            try:
                from edge_tts_engine import EdgeTTSEngine
                import asyncio
                import tempfile
                import subprocess

                engine = EdgeTTSEngine()
                voice = (
                    "id-ID-ArdiNeural"
                    if "Ardi" in self.voice_var.get()
                    else "id-ID-GadisNeural"
                )
                engine.set_voice(voice)

                speed_val = int(self.speed_var.get())
                pitch_val = int(self.pitch_var.get())
                engine.set_rate(f"{'+' if speed_val >= 0 else ''}{speed_val}%")
                engine.set_pitch(f"{'+' if pitch_val >= 0 else ''}{pitch_val}Hz")

                # Generate preview
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                    temp_path = f.name

                async def generate():
                    await engine.generate_audio(
                        "Halo, ini adalah preview suara Edge TTS untuk dubbing video.",
                        temp_path,
                    )

                asyncio.run(generate())

                # Play audio
                if os.path.exists(temp_path):
                    subprocess.Popen(["start", "", temp_path], shell=True)

            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Preview Error", str(e)))

        threading.Thread(target=run_preview, daemon=True).start()

    def _on_speed_change(self, value):
        """Update speed label"""
        val = int(value)
        sign = "+" if val >= 0 else ""
        self.speed_value_label.configure(text=f"{sign}{val}%")

    def _on_pitch_change(self, value):
        """Update pitch label"""
        val = int(value)
        sign = "+" if val >= 0 else ""
        self.pitch_value_label.configure(text=f"{sign}{val}Hz")

    def _on_volume_change(self, value):
        """Update volume label"""
        self.volume_value_label.configure(text=f"{int(value)}%")

    def _on_bgm_volume_change(self, value):
        """Update BGM volume label"""
        self.bgm_volume_label.configure(text=f"{int(value)}%")

    def _toggle_sub_removal(self):
        """Show/hide subtitle removal options"""
        if self.remove_subs_var.get():
            self.sub_removal_options.pack(fill="x", pady=(Spacing.XS, 0))
        else:
            self.sub_removal_options.pack_forget()

    def _on_sub_pct_change(self, value):
        """Update subtitle removal percentage label"""
        self.sub_pct_label.configure(text=f"{int(value)}%")

    def _on_sub_offset_change(self, value):
        """Update subtitle offset label"""
        self.sub_offset_label.configure(text=f"{int(value)}%")

    def _browse_output(self):
        """Browse for output folder"""
        folder = filedialog.askdirectory(title="Select Output Folder")
        if folder:
            display = folder[:45] + "..." if len(folder) > 45 else folder
            self.output_path_label.configure(text=display)
            self._output_folder = folder

    def _generate_video(self):
        """Generate dubbed video using SEGMENT-BASED pipeline.

        Each transcript segment gets its own TTS audio, placed at the
        correct time position on the video timeline. This ensures the
        voiceover naturally covers the full video duration.
        """
        # Validate
        script = self.script_text.get("1.0", "end").strip()
        if not script:
            messagebox.showwarning(
                "No Script", "Please write or generate a script first."
            )
            return

        if not self.current_video_path:
            messagebox.showwarning("No Video", "Please select a video file first.")
            return

        if self.is_processing:
            messagebox.showinfo("Busy", "Processing is already running.")
            return

        self.is_processing = True
        self._cancel_flag = False
        self.generate_btn.configure(state="disabled", text="⏳ Generating...")
        self._show_progress()

        def run_generation():
            try:
                from tts_sync import TTSVideoSync

                # Parse timed segments from script editor
                timed_segments = self._parse_timed_script(script)
                if not timed_segments:
                    raise ValueError(
                        "No segments found in script. Please check the format."
                    )

                # Build TTS config from UI settings
                voice = (
                    "id-ID-ArdiNeural"
                    if "Ardi" in self.voice_var.get()
                    else "id-ID-GadisNeural"
                )
                speed_val = int(self.speed_var.get())
                pitch_val = int(self.pitch_var.get())
                bg_volume = self.bg_volume_var.get() / 100.0
                keep_audio = self.keep_audio_var.get()
                burn_subs = self.burn_subtitle_var.get()
                remove_subs = self.remove_subs_var.get()

                # Background music config
                bgm_url = self.bgm_url_var.get().strip() or None
                bgm_volume = self.bgm_volume_var.get() / 100.0

                # Subtitle removal config
                sub_removal_config = None
                if remove_subs:
                    sub_removal_config = {
                        "region": self.sub_region_var.get().lower(),
                        "region_percent": int(self.sub_region_pct_var.get()),
                        "offset_percent": int(self.sub_offset_var.get()),
                        "method": self.sub_method_var.get().lower(),
                    }

                tts_config = {
                    "edge_tts": {
                        "voice": voice,
                        "rate": f"{'+' if speed_val >= 0 else ''}{speed_val}%",
                        "pitch": f"{'+' if pitch_val >= 0 else ''}{pitch_val}Hz",
                        "volume": "+0%",
                    },
                    "mix_config": {
                        "voice_volume": 1.0,
                        "background_volume": bg_volume,
                        "keep_original_audio": keep_audio,
                    },
                }

                syncer = TTSVideoSync(tts_config)

                # Determine output path
                output_folder = getattr(self, "_output_folder", None)
                if not output_folder:
                    label_text = self.output_path_label.cget("text")
                    output_folder = (
                        label_text if os.path.isdir(label_text) else "output"
                    )

                os.makedirs(output_folder, exist_ok=True)

                base_name = os.path.splitext(os.path.basename(self.current_video_path))[
                    0
                ]
                output_path = os.path.join(output_folder, f"{base_name}_dubbed.mp4")

                # Avoid overwriting
                counter = 1
                while os.path.exists(output_path):
                    output_path = os.path.join(
                        output_folder, f"{base_name}_dubbed_{counter}.mp4"
                    )
                    counter += 1

                video_duration = self.video_info.duration if self.video_info else 60

                self._update_progress(
                    3,
                    f"🎬 Processing {len(timed_segments)} segments for {video_duration:.0f}s video...",
                )

                # Use the new segment-based pipeline
                result = syncer.process_video_with_timed_segments(
                    video_path=self.current_video_path,
                    timed_segments=timed_segments,
                    video_duration=video_duration,
                    output_path=output_path,
                    include_subtitle=burn_subs,
                    remove_original_subs=remove_subs,
                    sub_removal_config=sub_removal_config,
                    bgm_url=bgm_url,
                    bgm_volume=bgm_volume,
                    progress_callback=lambda pct, msg: self._update_progress(pct, msg),
                )

                if not result.get("success"):
                    raise Exception(
                        result.get("error", "Unknown error during generation")
                    )

                # Show stats
                coverage = result.get("coverage_percent", 0)
                tts_dur = result.get("total_tts_duration", 0)
                n_segs = result.get("segments_count", 0)
                self._update_progress(
                    90,
                    f"✅ Dubbing done! {n_segs} segments, TTS={tts_dur:.1f}s/{video_duration:.0f}s ({coverage:.0f}% coverage)",
                )

                self._update_progress(100, "✅ Done!")

                self.after(0, lambda: self._on_generation_complete(output_path))

            except Exception as e:
                error_msg = str(e)
                tb = traceback.format_exc()
                print(f"[DUBBING ERROR] Generation failed:\n{tb}")
                self.after(
                    0,
                    lambda: self._on_generation_error(
                        f"{error_msg}\n\nDetail:\n{tb[:500]}"
                    ),
                )
            finally:
                self.is_processing = False

        threading.Thread(target=run_generation, daemon=True).start()

    def _on_generation_complete(self, output_path):
        """Handle video generation complete"""
        self.generate_btn.configure(state="normal", text="🚀 Generate Dubbed Video")
        self._update_step(4)

        # Keep progress visible showing completion
        self._update_progress(100, f"✅ Video saved: {os.path.basename(output_path)}")

        result = messagebox.askyesno(
            "Generation Complete! 🎉",
            f"Dubbed video berhasil disimpan:\n{output_path}\n\nBuka folder output?",
        )

        if result:
            # Open folder in explorer
            folder = os.path.dirname(output_path)
            os.startfile(folder)

    def _on_generation_error(self, error):
        """Handle generation error"""
        self.generate_btn.configure(state="normal", text="🚀 Generate Dubbed Video")
        self.is_processing = False
        self._update_progress(0, f"❌ Error")
        self.after(3000, self._hide_progress)
        messagebox.showerror(
            "Generation Error", f"Failed to generate dubbed video:\n\n{error}"
        )

    def _reset_all(self):
        """Reset all settings"""
        if self.is_processing:
            if messagebox.askyesno(
                "Cancel?", "Processing is running. Cancel and reset?"
            ):
                self._cancel_flag = True
            else:
                return

        if not self.is_processing and not messagebox.askyesno(
            "Reset", "Clear all settings and start over?"
        ):
            return

        self.current_video_path = None
        self.video_info = None
        self.transcript = None
        self.transcript_segments = None
        self.analysis_result = None
        self.generated_script = None
        self.word_timings = None
        self.is_processing = False
        self._cancel_flag = False

        # Hide sections
        for section in [
            self.analysis_section,
            self.script_section,
            self.voice_section,
            self.output_section,
        ]:
            section.pack_forget()

        # Reset UI
        self.video_info_label.configure(text="No video selected")
        self.script_text.delete("1.0", "end")
        self.generate_btn.configure(state="disabled", text="🚀 Generate Dubbed Video")
        self.analyze_btn.configure(state="normal", text="🔬 Analyze Video")
        self.remove_subs_var.set(False)
        self.sub_removal_options.pack_forget()
        self.sub_offset_var.set(0)
        self.sub_offset_label.configure(text="0%")
        self.burn_subtitle_var.set(True)
        self.speed_var.set(0)
        self.pitch_var.set(0)
        self.bg_volume_var.set(20)
        self.keep_audio_var.set(True)
        self.bgm_url_var.set("")
        self.bgm_volume_var.set(15)
        self.bgm_volume_label.configure(text="15%")
        self._update_step(0)
        self._hide_progress()

        # Force refresh scrollable frame to prevent blank page
        self.after(50, self.refresh_ui)

    def _update_step(self, step):
        """Update progress indicator"""
        for i, (circle, label) in enumerate(self.step_indicators):
            if i <= step:
                circle.configure(fg_color=Colors.ACCENT_PRIMARY)
            else:
                circle.configure(fg_color=Colors.BORDER)

    def _show_help(self):
        """Show help dialog"""
        messagebox.showinfo(
            "AI Dubbing Studio Help",
            "📌 Cara penggunaan:\n\n"
            "1️⃣ Upload: Pilih file video\n"
            "2️⃣ Analyze: AI extract audio & membuat transcript\n"
            "     (Menggunakan GROQ Whisper - gratis)\n"
            "3️⃣ Script: Edit script narasi yang di-generate AI\n"
            "     (Menggunakan GROQ LLM - gratis)\n"
            "4️⃣ Voice: Pilih suara TTS & pengaturan\n"
            "     (Edge TTS - 100% gratis)\n"
            "5️⃣ Export: Generate video final\n\n"
            "💡 Tip: Semua AI service menggunakan GROQ (gratis!)\n"
            "   Edge TTS juga 100% gratis tanpa limit!",
        )

    # Navigation compatibility
    def show_page(self, page_name):
        """Delegate to main app"""
        self.app.show_page(page_name)
