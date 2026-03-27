"""
Auto Caption Page - Standalone feature for adding captions to videos
Optimized with real-time thumbnail preview (no full video render)
Extract audio → Transcribe → Edit Script → Style → Preview → Export
"""

import customtkinter as ctk
from PIL import Image, ImageTk
from pathlib import Path
from tkinter import filedialog, messagebox
import threading
import os
import tempfile
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

# Import caption generator
from caption_generator import (
    CaptionGenerator,
    CaptionStyle,
    CaptionSegment,
    AVAILABLE_FONTS,
    TRANSITION_EFFECTS,
    CAPTION_MODES,
)


class AutoCaptionPage(ctk.CTkFrame):
    """Auto Caption - Add subtitles to videos with original audio"""

    def __init__(self, parent, app, config):
        super().__init__(parent, fg_color=Colors.BG_PRIMARY)
        self.app = app
        self.config = config

        # State
        self.current_video_path = None
        self.video_info = None
        self.transcript_segments = None
        self.full_transcript = None
        self.caption_segments_with_words = None  # Segments with word-level timestamps
        self.is_processing = False
        self._cancel_flag = False

        # Preview state
        self.preview_image = None
        self.preview_photo = None  # Keep reference to prevent garbage collection

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

    def create_ui(self):
        """Create the auto caption UI"""

        # Header
        self._create_header()

        # Main content - split into left (controls) and right (preview)
        main_container = ctk.CTkFrame(self, fg_color="transparent")
        main_container.pack(fill="both", expand=True, padx=Spacing.LG, pady=(0, Spacing.MD))

        # Left side: Controls (scrollable)
        left_frame = ctk.CTkFrame(main_container, fg_color="transparent", width=450)
        left_frame.pack(side="left", fill="y", padx=(0, Spacing.MD))
        left_frame.pack_propagate(False)

        self.controls_scroll = ctk.CTkScrollableFrame(
            left_frame,
            fg_color="transparent",
            scrollbar_button_color=Colors.BORDER,
            scrollbar_button_hover_color=Colors.ACCENT_PRIMARY,
        )
        self.controls_scroll.pack(fill="both", expand=True)

        # Right side: Preview panel (fixed)
        self._create_preview_panel(main_container)

        # Create control sections
        self._create_upload_section()
        self._create_transcribe_section()
        self._create_style_section()
        self._create_export_section()
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

        create_styled_label(title_frame, "Auto Caption", style="heading_lg").pack(
            anchor="w"
        )
        create_styled_label(
            title_frame, "Add subtitles to videos - keeps original audio", style="muted"
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
            tooltip="View usage guide",
            icon="?",
        )
        help_btn.pack()

    def _create_preview_panel(self, parent):
        """Create the real-time preview panel (right side)"""
        preview_frame = ctk.CTkFrame(
            parent,
            fg_color=Colors.CARD_BG,
            corner_radius=BorderRadius.LG,
            border_width=1,
            border_color=Colors.BORDER,
        )
        preview_frame.pack(side="right", fill="both", expand=True)

        # Header
        header = ctk.CTkFrame(preview_frame, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.MD, pady=(Spacing.MD, Spacing.SM))

        create_styled_label(header, "Live Preview", style="heading_sm").pack(side="left")

        # Refresh button
        refresh_btn = create_styled_button(
            header,
            "Refresh",
            command=self._update_preview,
            style="ghost",
            width=80,
            height=28,
            icon="🔄",
        )
        refresh_btn.pack(side="right")

        # Preview image container
        preview_container = ctk.CTkFrame(
            preview_frame,
            fg_color=Colors.BG_SECONDARY,
            corner_radius=BorderRadius.MD,
        )
        preview_container.pack(fill="both", expand=True, padx=Spacing.MD, pady=(0, Spacing.MD))

        # Preview label (will show the thumbnail)
        self.preview_label = ctk.CTkLabel(
            preview_container,
            text="Upload video to see preview",
            font=Fonts.body(),
            text_color=Colors.TEXT_SECONDARY,
        )
        self.preview_label.pack(expand=True, fill="both", padx=10, pady=10)

        # Status label
        self.preview_status = create_styled_label(
            preview_frame, "No video loaded", style="caption"
        )
        self.preview_status.pack(pady=(0, Spacing.SM))

    def _create_upload_section(self):
        """Create video upload section"""
        section = ctk.CTkFrame(
            self.controls_scroll,
            fg_color=Colors.CARD_BG,
            corner_radius=BorderRadius.LG,
            border_width=1,
            border_color=Colors.BORDER,
        )
        section.pack(fill="x", pady=(0, Spacing.MD))

        # Header
        header = ctk.CTkFrame(section, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.MD, pady=(Spacing.MD, Spacing.SM))

        icon_frame = ctk.CTkFrame(
            header,
            width=32,
            height=32,
            fg_color=Colors.ACCENT_PRIMARY,
            corner_radius=BorderRadius.SM,
        )
        icon_frame.pack(side="left")
        icon_frame.pack_propagate(False)
        ctk.CTkLabel(icon_frame, text="1", font=ctk.CTkFont(size=14, weight="bold")).place(
            relx=0.5, rely=0.5, anchor="center"
        )

        create_styled_label(header, "Upload Video", style="heading_sm").pack(side="left", padx=(Spacing.SM, 0))

        # Upload button
        content = ctk.CTkFrame(section, fg_color="transparent")
        content.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        upload_btn = create_styled_button(
            content,
            "Select Video File",
            command=self._select_video,
            style="secondary",
            width=180,
            height=36,
            icon="📁",
        )
        upload_btn.pack(side="left")

        # Video info label
        self.video_info_label = create_styled_label(
            content, "No video selected", style="muted"
        )
        self.video_info_label.pack(side="left", padx=(Spacing.SM, 0))

    def _create_transcribe_section(self):
        """Create transcription section"""
        section = ctk.CTkFrame(
            self.controls_scroll,
            fg_color=Colors.CARD_BG,
            corner_radius=BorderRadius.LG,
            border_width=1,
            border_color=Colors.BORDER,
        )
        section.pack(fill="x", pady=(0, Spacing.MD))
        section.pack_forget()  # Hidden initially
        self.transcribe_section = section

        # Header
        header = ctk.CTkFrame(section, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.MD, pady=(Spacing.MD, Spacing.SM))

        icon_frame = ctk.CTkFrame(
            header,
            width=32,
            height=32,
            fg_color=Colors.INFO,
            corner_radius=BorderRadius.SM,
        )
        icon_frame.pack(side="left")
        icon_frame.pack_propagate(False)
        ctk.CTkLabel(icon_frame, text="2", font=ctk.CTkFont(size=14, weight="bold")).place(
            relx=0.5, rely=0.5, anchor="center"
        )

        create_styled_label(header, "Transcribe Audio", style="heading_sm").pack(side="left", padx=(Spacing.SM, 0))

        # Content
        content = ctk.CTkFrame(section, fg_color="transparent")
        content.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        # Language & Transcribe button row
        lang_row = ctk.CTkFrame(content, fg_color="transparent")
        lang_row.pack(fill="x", pady=(0, Spacing.SM))

        create_styled_label(lang_row, "Language:", style="caption").pack(side="left")

        self.language_var = ctk.StringVar(value="id")
        lang_dropdown = ctk.CTkComboBox(
            lang_row,
            values=["id", "en", "auto"],
            variable=self.language_var,
            width=80,
            height=28,
            font=Fonts.body_sm(),
            fg_color=Colors.BG_PRIMARY,
        )
        lang_dropdown.pack(side="left", padx=(Spacing.XS, Spacing.MD))

        self.transcribe_btn = create_styled_button(
            lang_row,
            "Transcribe",
            command=self._transcribe_audio,
            style="secondary",
            width=110,
            height=32,
            icon="🎤",
        )
        self.transcribe_btn.pack(side="left")

        # Script editor
        create_styled_label(
            content, "Caption Script [MM:SS - MM:SS] text:", style="caption"
        ).pack(anchor="w", pady=(Spacing.SM, 0))

        self.caption_text = ctk.CTkTextbox(
            content,
            height=150,
            fg_color=Colors.BG_SECONDARY,
            text_color=Colors.TEXT_PRIMARY,
            font=Fonts.mono(),
            corner_radius=BorderRadius.SM,
            border_width=1,
            border_color=Colors.BORDER,
        )
        self.caption_text.pack(fill="x", pady=(4, 0))

        # Bind text change to update preview
        self.caption_text.bind("<KeyRelease>", lambda e: self._schedule_preview_update())

        ToolTip(
            self.caption_text,
            "Format: [00:00 - 00:05] Text caption\nEdit timing dan text sesuai kebutuhan",
        )

    def _create_style_section(self):
        """Create caption style section"""
        section = ctk.CTkFrame(
            self.controls_scroll,
            fg_color=Colors.CARD_BG,
            corner_radius=BorderRadius.LG,
            border_width=1,
            border_color=Colors.BORDER,
        )
        section.pack(fill="x", pady=(0, Spacing.MD))
        section.pack_forget()  # Hidden initially
        self.style_section = section

        # Header
        header = ctk.CTkFrame(section, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.MD, pady=(Spacing.MD, Spacing.SM))

        icon_frame = ctk.CTkFrame(
            header,
            width=32,
            height=32,
            fg_color=Colors.WARNING,
            corner_radius=BorderRadius.SM,
        )
        icon_frame.pack(side="left")
        icon_frame.pack_propagate(False)
        ctk.CTkLabel(icon_frame, text="3", font=ctk.CTkFont(size=14, weight="bold")).place(
            relx=0.5, rely=0.5, anchor="center"
        )

        create_styled_label(header, "Caption Style", style="heading_sm").pack(side="left", padx=(Spacing.SM, 0))

        # Style controls
        style_content = ctk.CTkFrame(section, fg_color="transparent")
        style_content.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        # Row 1: Font, Size
        row1 = ctk.CTkFrame(style_content, fg_color="transparent")
        row1.pack(fill="x", pady=(0, Spacing.SM))

        create_styled_label(row1, "Font:", style="caption").pack(side="left")
        self.font_var = ctk.StringVar(value="Montserrat")
        font_dropdown = ctk.CTkComboBox(
            row1,
            values=AVAILABLE_FONTS,
            variable=self.font_var,
            width=130,
            height=28,
            font=Fonts.body_sm(),
            fg_color=Colors.BG_PRIMARY,
            command=lambda _: self._update_preview(),
        )
        font_dropdown.pack(side="left", padx=(Spacing.XS, Spacing.MD))

        create_styled_label(row1, "Size:", style="caption").pack(side="left")
        self.size_var = ctk.IntVar(value=65)
        size_slider = ctk.CTkSlider(
            row1,
            from_=30,
            to=120,
            width=80,
            variable=self.size_var,
            command=self._on_size_change,
            fg_color=Colors.BG_PRIMARY,
            progress_color=Colors.INFO,
        )
        size_slider.pack(side="left", padx=(Spacing.XS, Spacing.XS))
        self.size_label = create_styled_label(row1, "65", style="caption")
        self.size_label.pack(side="left")

        # Row 2: Bold, Italic, Position
        row2 = ctk.CTkFrame(style_content, fg_color="transparent")
        row2.pack(fill="x", pady=(0, Spacing.SM))

        self.bold_var = ctk.BooleanVar(value=True)
        bold_cb = ctk.CTkCheckBox(
            row2,
            text="Bold",
            variable=self.bold_var,
            font=Fonts.body_sm(),
            fg_color=Colors.INFO,
            width=60,
            command=self._update_preview,
        )
        bold_cb.pack(side="left")

        self.italic_var = ctk.BooleanVar(value=False)
        italic_cb = ctk.CTkCheckBox(
            row2,
            text="Italic",
            variable=self.italic_var,
            font=Fonts.body_sm(),
            fg_color=Colors.INFO,
            width=60,
            command=self._update_preview,
        )
        italic_cb.pack(side="left", padx=(Spacing.SM, Spacing.MD))

        create_styled_label(row2, "Position:", style="caption").pack(side="left")
        self.position_var = ctk.StringVar(value="bottom")
        position_dropdown = ctk.CTkComboBox(
            row2,
            values=["bottom", "middle", "top"],
            variable=self.position_var,
            width=90,
            height=28,
            font=Fonts.body_sm(),
            fg_color=Colors.BG_PRIMARY,
            command=lambda _: self._update_preview(),
        )
        position_dropdown.pack(side="left", padx=(Spacing.XS, 0))

        # Row 3: Colors
        row3 = ctk.CTkFrame(style_content, fg_color="transparent")
        row3.pack(fill="x", pady=(0, Spacing.SM))

        create_styled_label(row3, "Text:", style="caption").pack(side="left")
        self.text_color_var = ctk.StringVar(value="#FFFFFF")
        color_entry = ctk.CTkEntry(
            row3,
            textvariable=self.text_color_var,
            width=70,
            height=28,
            font=Fonts.mono(),
            fg_color=Colors.BG_PRIMARY,
        )
        color_entry.pack(side="left", padx=(Spacing.XS, Spacing.MD))
        color_entry.bind("<FocusOut>", lambda e: self._update_preview())

        create_styled_label(row3, "Outline:", style="caption").pack(side="left")
        self.outline_color_var = ctk.StringVar(value="#000000")
        outline_entry = ctk.CTkEntry(
            row3,
            textvariable=self.outline_color_var,
            width=70,
            height=28,
            font=Fonts.mono(),
            fg_color=Colors.BG_PRIMARY,
        )
        outline_entry.pack(side="left", padx=(Spacing.XS, 0))
        outline_entry.bind("<FocusOut>", lambda e: self._update_preview())

        # Row 4: Transition effects
        row4 = ctk.CTkFrame(style_content, fg_color="transparent")
        row4.pack(fill="x", pady=(0, 0))

        create_styled_label(row4, "Transition:", style="caption").pack(side="left")
        self.transition_var = ctk.StringVar(value="fade")
        transition_dropdown = ctk.CTkComboBox(
            row4,
            values=list(TRANSITION_EFFECTS.keys()),
            variable=self.transition_var,
            width=100,
            height=28,
            font=Fonts.body_sm(),
            fg_color=Colors.BG_PRIMARY,
        )
        transition_dropdown.pack(side="left", padx=(Spacing.XS, 0))
        ToolTip(transition_dropdown, "Caption animation effect (fade, slide, pop)")

        # Row 5: Caption Mode (NEW - Word-level support)
        row5 = ctk.CTkFrame(style_content, fg_color="transparent")
        row5.pack(fill="x", pady=(Spacing.SM, 0))

        create_styled_label(row5, "Mode:", style="caption").pack(side="left")
        self.caption_mode_var = ctk.StringVar(value="sentence")
        mode_dropdown = ctk.CTkComboBox(
            row5,
            values=["sentence", "word_by_word", "chunk", "word_highlight"],
            variable=self.caption_mode_var,
            width=120,
            height=28,
            font=Fonts.body_sm(),
            fg_color=Colors.BG_PRIMARY,
            command=self._on_mode_change,
        )
        mode_dropdown.pack(side="left", padx=(Spacing.XS, Spacing.MD))
        ToolTip(mode_dropdown, "sentence=full text, word_by_word=TikTok style, chunk=2-3 words, word_highlight=karaoke")

        # Words per chunk (for chunk mode)
        self.chunk_frame = ctk.CTkFrame(row5, fg_color="transparent")

        create_styled_label(self.chunk_frame, "Words:", style="caption").pack(side="left")
        self.chunk_var = ctk.IntVar(value=3)
        chunk_slider = ctk.CTkSlider(
            self.chunk_frame,
            from_=2,
            to=5,
            width=60,
            number_of_steps=3,
            variable=self.chunk_var,
            command=lambda _: self._update_preview(),
            fg_color=Colors.BG_PRIMARY,
            progress_color=Colors.WARNING,
        )
        chunk_slider.pack(side="left", padx=(Spacing.XS, Spacing.XS))
        self.chunk_label = create_styled_label(self.chunk_frame, "3", style="caption")
        self.chunk_label.pack(side="left")

        # Row 6: Timing Offset (NEW - Fix early/late captions)
        row6 = ctk.CTkFrame(style_content, fg_color="transparent")
        row6.pack(fill="x", pady=(Spacing.SM, 0))

        create_styled_label(row6, "Timing Offset:", style="caption").pack(side="left")
        self.offset_var = ctk.DoubleVar(value=0.0)
        offset_slider = ctk.CTkSlider(
            row6,
            from_=-0.5,
            to=0.5,
            width=100,
            variable=self.offset_var,
            command=self._on_offset_change,
            fg_color=Colors.BG_PRIMARY,
            progress_color=Colors.ACCENT_PRIMARY,
        )
        offset_slider.pack(side="left", padx=(Spacing.XS, Spacing.XS))
        self.offset_label = create_styled_label(row6, "0.00s", style="caption")
        self.offset_label.pack(side="left")
        ToolTip(offset_slider, "Adjust caption timing: negative=earlier, positive=later")

        # Row 7: Hook Effect (dramatic entrance for first sentence)
        row7 = ctk.CTkFrame(style_content, fg_color="transparent")
        row7.pack(fill="x", pady=(Spacing.SM, 0))

        self.hook_effect_var = ctk.BooleanVar(value=True)
        hook_cb = ctk.CTkCheckBox(
            row7,
            text="Hook Effect",
            variable=self.hook_effect_var,
            font=Fonts.body_sm(),
            fg_color=Colors.WARNING,
            width=100,
            command=self._update_preview,
        )
        hook_cb.pack(side="left")
        ToolTip(hook_cb, "Dramatic entrance effect for first sentence (scale + bounce + glow)")

    def _on_mode_change(self, value):
        """Handle caption mode change"""
        if value == "chunk":
            self.chunk_frame.pack(side="left")
        else:
            self.chunk_frame.pack_forget()
        self._update_preview()

    def _on_offset_change(self, value):
        """Update offset label"""
        self.offset_label.configure(text=f"{float(value):.2f}s")

    def _create_export_section(self):
        """Create export section"""
        section = ctk.CTkFrame(
            self.controls_scroll,
            fg_color=Colors.CARD_BG,
            corner_radius=BorderRadius.LG,
            border_width=1,
            border_color=Colors.BORDER,
        )
        section.pack(fill="x", pady=(0, Spacing.MD))
        section.pack_forget()  # Hidden initially
        self.export_section = section

        # Header
        header = ctk.CTkFrame(section, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.MD, pady=(Spacing.MD, Spacing.SM))

        icon_frame = ctk.CTkFrame(
            header,
            width=32,
            height=32,
            fg_color=Colors.SUCCESS,
            corner_radius=BorderRadius.SM,
        )
        icon_frame.pack(side="left")
        icon_frame.pack_propagate(False)
        ctk.CTkLabel(icon_frame, text="4", font=ctk.CTkFont(size=14, weight="bold")).place(
            relx=0.5, rely=0.5, anchor="center"
        )

        create_styled_label(header, "Export Video", style="heading_sm").pack(side="left", padx=(Spacing.SM, 0))

        # Content
        content = ctk.CTkFrame(section, fg_color="transparent")
        content.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        # Output folder
        folder_row = ctk.CTkFrame(content, fg_color="transparent")
        folder_row.pack(fill="x")

        self.output_folder_var = ctk.StringVar(value=str(Path.home() / "Videos"))
        folder_entry = ctk.CTkEntry(
            folder_row,
            textvariable=self.output_folder_var,
            height=32,
            font=Fonts.body_sm(),
            fg_color=Colors.BG_SECONDARY,
        )
        folder_entry.pack(side="left", fill="x", expand=True)

        browse_btn = create_styled_button(
            folder_row,
            "Browse",
            command=self._browse_output_folder,
            style="ghost",
            width=70,
            height=32,
        )
        browse_btn.pack(side="left", padx=(Spacing.SM, 0))

    def _create_action_buttons(self):
        """Create main action buttons"""
        action_frame = ctk.CTkFrame(self.controls_scroll, fg_color="transparent")
        action_frame.pack(fill="x", pady=(Spacing.SM, Spacing.MD))

        # Export button
        self.export_btn = create_styled_button(
            action_frame,
            "Export Video",
            command=self._export_video,
            style="primary",
            width=180,
            height=40,
            icon="📹",
        )
        self.export_btn.pack(side="left", padx=(0, Spacing.SM))
        self.export_btn.configure(state="disabled")

        # Reset button
        reset_btn = create_styled_button(
            action_frame,
            "Reset",
            command=self._reset_all,
            style="ghost",
            width=80,
            height=40,
            icon="🗑",
        )
        reset_btn.pack(side="left")

        # Progress
        self.progress_label = create_styled_label(
            action_frame, "", style="caption"
        )
        self.progress_label.pack(side="left", padx=(Spacing.MD, 0))

    # ===== Event Handlers =====

    def _select_video(self):
        """Open file dialog to select video"""
        filetypes = [
            ("Video files", "*.mp4 *.mkv *.avi *.mov *.webm"),
            ("All files", "*.*"),
        ]
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            self._load_video(path)

    def _load_video(self, path: str):
        """Load video and get info"""
        self.current_video_path = path
        filename = os.path.basename(path)

        try:
            from video_analyzer import VideoAnalyzer
            analyzer = VideoAnalyzer(self._get_config_dict())
            self.video_info = analyzer.get_video_info(path)

            # Update UI
            duration_str = f"{self.video_info.duration:.1f}s"
            res_str = f"{self.video_info.width}x{self.video_info.height}"

            self.video_info_label.configure(
                text=f"✅ {filename[:20]}... ({duration_str})"
            )

            # Show sections
            self.transcribe_section.pack(fill="x", pady=(0, Spacing.MD))
            self.style_section.pack(fill="x", pady=(0, Spacing.MD))
            self.export_section.pack(fill="x", pady=(0, Spacing.MD))

            # Generate initial preview
            self._update_preview()

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load video:\n{e}")

    def _schedule_preview_update(self):
        """Schedule preview update with debounce"""
        if hasattr(self, '_preview_update_job'):
            self.after_cancel(self._preview_update_job)
        self._preview_update_job = self.after(500, self._update_preview)

    def _update_preview(self):
        """Update the preview thumbnail (FAST - single frame only)"""
        if not self.current_video_path:
            return

        # Get sample caption text
        script_text = self.caption_text.get("1.0", "end").strip() if hasattr(self, 'caption_text') else ""

        # Get first caption or use sample
        sample_text = "SAMPLE CAPTION TEXT"
        if script_text:
            generator = CaptionGenerator()
            segments = generator.parse_timed_script(script_text)
            if segments:
                sample_text = segments[0].text.upper()

        self.preview_status.configure(text="Generating preview...")

        def generate_preview():
            try:
                style = self._get_caption_style()
                generator = CaptionGenerator(style)

                # Generate thumbnail with caption overlay (FAST - single frame)
                preview_img = generator.generate_preview_thumbnail(
                    self.current_video_path,
                    sample_text,
                    timestamp=1.0
                )

                # Resize for display
                display_width = 350
                aspect_ratio = preview_img.height / preview_img.width
                display_height = int(display_width * aspect_ratio)
                preview_img = preview_img.resize((display_width, display_height), Image.Resampling.LANCZOS)

                # Update UI
                self.after(0, lambda: self._display_preview(preview_img))

            except Exception as e:
                self.after(0, lambda: self.preview_status.configure(text=f"Preview error: {str(e)[:30]}"))

        threading.Thread(target=generate_preview, daemon=True).start()

    def _display_preview(self, img: Image.Image):
        """Display preview image in the preview panel"""
        try:
            # Convert PIL image to CTk image
            self.preview_image = img
            self.preview_photo = ctk.CTkImage(
                light_image=img,
                dark_image=img,
                size=(img.width, img.height)
            )

            # Update label
            self.preview_label.configure(image=self.preview_photo, text="")
            self.preview_status.configure(text="Preview ready (single frame)")

        except Exception as e:
            self.preview_status.configure(text=f"Display error: {str(e)[:30]}")

    def _on_size_change(self, value):
        """Update size label and preview"""
        self.size_label.configure(text=str(int(float(value))))
        self._schedule_preview_update()

    def _get_caption_style(self) -> CaptionStyle:
        """Build CaptionStyle from UI values"""
        position_map = {"bottom": 2, "middle": 5, "top": 8}

        return CaptionStyle(
            font_name=self.font_var.get(),
            font_size=self.size_var.get(),
            primary_color=CaptionGenerator.hex_to_ass_color(self.text_color_var.get()),
            outline_color=CaptionGenerator.hex_to_ass_color(self.outline_color_var.get()),
            bold=self.bold_var.get(),
            italic=self.italic_var.get(),
            alignment=position_map.get(self.position_var.get(), 2),
            transition_in=self.transition_var.get(),
            transition_out=self.transition_var.get(),
            caption_mode=self.caption_mode_var.get(),
            timing_offset=self.offset_var.get(),
            words_per_chunk=self.chunk_var.get(),
            enable_hook_effect=self.hook_effect_var.get(),
        )

    def _transcribe_audio(self):
        """Transcribe video audio using Whisper"""
        if not self.current_video_path:
            messagebox.showwarning("No Video", "Please select a video first.")
            return

        if self.is_processing:
            return

        self.is_processing = True
        self.transcribe_btn.configure(state="disabled", text="Processing...")
        self.progress_label.configure(text="Transcribing audio...")

        def transcribe_task():
            try:
                from video_analyzer import VideoAnalyzer

                analyzer = VideoAnalyzer(self._get_config_dict())

                # Extract audio
                temp_dir = tempfile.mkdtemp()
                audio_path = os.path.join(temp_dir, "audio.mp3")
                analyzer.extract_audio(self.current_video_path, audio_path)

                # Transcribe
                language = self.language_var.get()
                if language == "auto":
                    language = None

                segments, full_text = analyzer.transcribe_audio(audio_path, language)

                self.transcript_segments = segments
                self.full_transcript = full_text

                # Convert to CaptionSegments (preserve word timings!)
                caption_segs = []
                for seg in segments:
                    text = seg.text if hasattr(seg, 'text') else seg.get('text', '')
                    start = seg.start if hasattr(seg, 'start') else seg.get('start', 0)
                    end = seg.end if hasattr(seg, 'end') else seg.get('end', 0)
                    words = seg.words if hasattr(seg, 'words') else seg.get('words', None)
                    if text.strip():
                        caption_segs.append(CaptionSegment(
                            text=text.strip(),
                            start=float(start),
                            end=float(end),
                            words=words  # Keep word-level timestamps!
                        ))

                # Store caption segments with word data
                self.caption_segments_with_words = caption_segs

                # Format as timed script (new professional format)
                generator = CaptionGenerator()
                timed_script = generator.format_timed_script(caption_segs)

                # Update UI
                self.after(0, lambda: self._on_transcribe_complete(timed_script, len(caption_segs)))

                # Cleanup
                try:
                    os.remove(audio_path)
                    os.rmdir(temp_dir)
                except:
                    pass

            except Exception as e:
                self.after(0, lambda: self._on_transcribe_error(str(e)))

        threading.Thread(target=transcribe_task, daemon=True).start()

    def _on_transcribe_complete(self, script: str, segment_count: int):
        """Handle transcription completion"""
        self.caption_text.delete("1.0", "end")
        self.caption_text.insert("1.0", script)

        self.transcribe_btn.configure(state="normal", text="✅ Done")
        self.export_btn.configure(state="normal")
        self.is_processing = False
        self.progress_label.configure(text=f"Transcribed {segment_count} segments")

        # Update preview with actual caption
        self._update_preview()

    def _on_transcribe_error(self, error: str):
        """Handle transcription error"""
        self.transcribe_btn.configure(state="normal", text="🎤 Transcribe")
        self.is_processing = False
        self.progress_label.configure(text="")
        messagebox.showerror("Error", f"Transcription failed:\n{error}")

    def _browse_output_folder(self):
        """Browse for output folder"""
        folder = filedialog.askdirectory()
        if folder:
            self.output_folder_var.set(folder)

    def _export_video(self):
        """Export video with burned captions"""
        if not self.current_video_path:
            messagebox.showwarning("No Video", "Please select a video first.")
            return

        script_text = self.caption_text.get("1.0", "end").strip()
        if not script_text:
            messagebox.showwarning("No Script", "Please add caption script first.")
            return

        # Check if already processing
        if CaptionGenerator.is_processing():
            messagebox.showwarning("Busy", "Another caption process is running. Please wait.")
            return

        if self.is_processing:
            return

        self.is_processing = True
        self.export_btn.configure(state="disabled", text="Exporting...")
        self.progress_label.configure(text="Starting export...")

        def export_task():
            try:
                style = self._get_caption_style()
                generator = CaptionGenerator(style)

                # Prefer segments with word data if available
                if self.caption_segments_with_words and style.caption_mode != "sentence":
                    segments = self.caption_segments_with_words
                else:
                    # Parse from script text
                    segments = generator.parse_timed_script(script_text)

                    if not segments:
                        raise ValueError("No valid caption segments found")

                    # Attach word timings from transcript if available
                    if self.caption_segments_with_words:
                        for i, seg in enumerate(segments):
                            if i < len(self.caption_segments_with_words):
                                seg.words = self.caption_segments_with_words[i].words

                self.after(0, lambda: self.progress_label.configure(text="Generating subtitles..."))

                # Generate ASS with word-level support
                enable_word_mode = style.caption_mode != "sentence"
                temp_ass = tempfile.NamedTemporaryFile(suffix=".ass", delete=False).name
                generator.generate_ass_subtitle(
                    segments, temp_ass,
                    self.video_info.width if self.video_info else 1080,
                    self.video_info.height if self.video_info else 1920,
                    enable_word_mode=enable_word_mode,
                )

                # Output path
                input_name = os.path.splitext(os.path.basename(self.current_video_path))[0]
                output_folder = self.output_folder_var.get()
                output_path = os.path.join(output_folder, f"{input_name}_captioned.mp4")

                # Ensure unique filename
                counter = 1
                while os.path.exists(output_path):
                    output_path = os.path.join(output_folder, f"{input_name}_captioned_{counter}.mp4")
                    counter += 1

                self.after(0, lambda: self.progress_label.configure(text="Burning captions..."))

                generator.burn_captions_to_video(
                    self.current_video_path, temp_ass, output_path,
                    progress_callback=lambda msg: self.after(0, lambda: self.progress_label.configure(text=msg))
                )

                # Cleanup
                os.remove(temp_ass)

                self.after(0, lambda: self._on_export_complete(output_path))

            except Exception as e:
                self.after(0, lambda: self._on_export_error(str(e)))

        threading.Thread(target=export_task, daemon=True).start()

    def _on_export_complete(self, output_path: str):
        """Handle export completion"""
        self.export_btn.configure(state="normal", text="✅ Done")
        self.is_processing = False
        self.progress_label.configure(text="Export complete!")

        result = messagebox.askyesno(
            "Export Complete",
            f"Video saved to:\n{output_path}\n\nOpen output folder?"
        )
        if result:
            os.startfile(os.path.dirname(output_path))

        self.after(3000, lambda: self.export_btn.configure(text="📹 Export Video"))

    def _on_export_error(self, error: str):
        """Handle export error"""
        self.export_btn.configure(state="normal", text="📹 Export Video")
        self.is_processing = False
        self.progress_label.configure(text="")
        messagebox.showerror("Export Error", f"Failed to export:\n{error}")

    def _reset_all(self):
        """Reset all state"""
        if self.is_processing:
            if not messagebox.askyesno("Cancel?", "Processing is running. Cancel?"):
                return
            self._cancel_flag = True
            CaptionGenerator.cancel_processing()

        self.current_video_path = None
        self.video_info = None
        self.transcript_segments = None
        self.full_transcript = None
        self.caption_segments_with_words = None
        self.is_processing = False
        self._cancel_flag = False

        # Hide sections
        self.transcribe_section.pack_forget()
        self.style_section.pack_forget()
        self.export_section.pack_forget()

        # Reset UI
        self.video_info_label.configure(text="No video selected")
        self.caption_text.delete("1.0", "end")
        self.transcribe_btn.configure(state="normal", text="🎤 Transcribe")
        self.export_btn.configure(state="disabled", text="📹 Export Video")
        self.progress_label.configure(text="")

        # Reset preview
        self.preview_label.configure(image=None, text="Upload video to see preview")
        self.preview_status.configure(text="No video loaded")
        self.preview_image = None
        self.preview_photo = None

    def _show_help(self):
        """Show help dialog"""
        messagebox.showinfo(
            "Auto Caption Help",
            "📌 Cara penggunaan:\n\n"
            "1️⃣ Upload: Pilih video\n"
            "2️⃣ Transcribe: AI extract teks + word timestamps\n"
            "3️⃣ Edit: Perbaiki teks caption\n"
            "   Format: [00:00 - 00:05] Text\n"
            "4️⃣ Style: Atur font, warna, posisi, mode\n\n"
            "🎯 Caption Modes:\n"
            "   • sentence: Full text sekaligus\n"
            "   • word_by_word: Kata per kata (TikTok style)\n"
            "   • chunk: 2-3 kata per frame\n"
            "   • word_highlight: Karaoke style\n\n"
            "⏱️ Timing Offset:\n"
            "   Geser slider untuk menyesuaikan timing\n"
            "   Negatif = lebih awal, Positif = lebih lambat\n\n"
            "💡 Preview real-time (hanya 1 frame)",
        )

    def show_page(self, page_name):
        """Delegate to main app"""
        self.app.show_page(page_name)
