"""
Clip+Dub Page - Wizard-style UI for the combined Clip + Dub workflow.

Flow: URL Input → Pattern/Context → Clip Preview (reorder/replace) → Script Editor → Voice → Render
All steps in a single page with step indicator.
Features: In-app video preview, spare clips for replacement, drag reorder.
"""

import customtkinter as ctk
import threading
import json
import os
import re
from tkinter import messagebox, filedialog
from pathlib import Path
from typing import Optional, List, Dict

from components.ui_theme import (
    Colors,
    Fonts,
    Spacing,
    BorderRadius,
    ToolTip,
    create_styled_button,
    create_styled_label,
)


class ClipDubPage(ctk.CTkFrame):
    """Combined Clip+Dub wizard page."""

    STEPS = [
        ("1", "URL & Konteks"),
        ("2", "Review Clips"),
        ("3", "Portrait Studio"),
        ("4", "TTS Studio"),
        ("5", "Render"),
    ]

    def __init__(self, parent, app, config):
        super().__init__(parent, fg_color=Colors.BG_PRIMARY)
        self.app = app
        self.config = config

        # State
        self.current_step = 0
        self.engine = None
        self._cancel_flag = False
        self._processing = False
        self.download_result = None
        self.highlights = None
        self.spare_highlights = None  # Backup clips pool
        self.script_data = None
        self._thumbnail_refs = []  # Keep CTkImage references to prevent GC
        self._active_player = None  # Currently open VideoPreviewPlayer
        self._log_lines = []  # Recent log messages for progress panel
        self._current_engine_step = 0  # Track which engine step is active
        self._reco_result = None  # AI recommendation result
        self._reco_running = False  # Whether recommendation is in progress
        self.tts_preview_data = None  # List of TTS preview segment data
        self._audio_process = None  # Currently playing audio subprocess
        self._tts_segment_widgets = []  # Segment card widget refs
        self.manual_crop_data: Dict[int, Dict] = {}
        self._portrait_editor = None
        self._selected_crop_idx = 0
        self._crop_selector_options: List[str] = []

        self._build_ui()

    def _build_ui(self):
        """Build the full wizard UI."""
        # Header with back button + step indicator
        header = ctk.CTkFrame(self, fg_color=Colors.CARD_BG, height=56)
        header.pack(fill="x")
        header.pack_propagate(False)

        header_inner = ctk.CTkFrame(header, fg_color="transparent")
        header_inner.pack(fill="x", padx=Spacing.MD, pady=Spacing.SM)

        back_btn = create_styled_button(
            header_inner,
            "← Back",
            command=self._go_back,
            style="ghost",
            width=70,
            height=32,
        )
        back_btn.pack(side="left")

        create_styled_label(
            header_inner, "🎬 Clip + Dub Studio", style="heading_sm"
        ).pack(side="left", padx=Spacing.MD)

        # Step indicator (right side)
        self.step_frame = ctk.CTkFrame(header_inner, fg_color="transparent")
        self.step_frame.pack(side="right")
        self._build_step_indicator()

        # Main content area (scrollable)
        self.content_area = ctk.CTkFrame(self, fg_color="transparent")
        self.content_area.pack(
            fill="both", expand=True, padx=Spacing.LG, pady=Spacing.MD
        )

        # Step frames (stacked, show one at a time)
        self.step_frames = {}
        self._build_step1()
        self._build_step2()
        self._build_step3_portrait()
        self._build_step3()
        self._build_step4()

        # Status bar at bottom
        self.status_bar = ctk.CTkFrame(self, fg_color=Colors.CARD_BG, height=36)
        self.status_bar.pack(fill="x", side="bottom")
        self.status_bar.pack_propagate(False)

        self.status_label = create_styled_label(
            self.status_bar, "Ready", style="caption"
        )
        self.status_label.pack(side="left", padx=Spacing.MD)

        self.progress_bar = ctk.CTkProgressBar(
            self.status_bar,
            width=200,
            height=8,
            fg_color=Colors.BG_SECONDARY,
            progress_color=Colors.ACCENT_PRIMARY,
        )
        self.progress_bar.pack(side="right", padx=Spacing.MD, pady=Spacing.SM)
        self.progress_bar.set(0)

        # Progress panel (collapsible, above status bar)
        self._build_progress_panel()

        # Show step 1
        self._show_step(0)

    def _build_step_indicator(self):
        """Build the step indicator dots."""
        for widget in self.step_frame.winfo_children():
            widget.destroy()

        for i, (num, label) in enumerate(self.STEPS):
            if i == self.current_step:
                color = Colors.ACCENT_PRIMARY
                text_color = Colors.TEXT_PRIMARY
            elif i < self.current_step:
                color = Colors.SUCCESS
                text_color = Colors.SUCCESS
            else:
                color = Colors.BORDER
                text_color = Colors.TEXT_MUTED

            step_lbl = ctk.CTkLabel(
                self.step_frame,
                text=f" {num}.{label} ",
                font=ctk.CTkFont(
                    size=11, weight="bold" if i == self.current_step else "normal"
                ),
                text_color=text_color,
                fg_color=color if i == self.current_step else "transparent",
                corner_radius=10,
                padx=6,
                pady=2,
            )
            step_lbl.pack(side="left", padx=2)

            if i < len(self.STEPS) - 1:
                ctk.CTkLabel(
                    self.step_frame,
                    text="→",
                    text_color=Colors.BORDER,
                    font=ctk.CTkFont(size=10),
                ).pack(side="left")

    # ─── STEP 1: URL + Context ────────────────────────────────────────

    def _build_step1(self):
        """URL input + Pattern selection + Context."""
        frame = ctk.CTkScrollableFrame(self.content_area, fg_color="transparent")
        self.step_frames[0] = frame

        # URL Section
        url_card = self._card(frame, "📥 Video Source")

        url_row = ctk.CTkFrame(url_card, fg_color="transparent")
        url_row.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        create_styled_label(url_row, "YouTube URL:", style="caption").pack(anchor="w")

        url_input_row = ctk.CTkFrame(url_row, fg_color="transparent")
        url_input_row.pack(fill="x", pady=(4, 0))

        self.url_var = ctk.StringVar()
        self.url_entry = ctk.CTkEntry(
            url_input_row,
            textvariable=self.url_var,
            height=40,
            fg_color=Colors.BG_SECONDARY,
            border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY,
            font=Fonts.body(),
            placeholder_text="https://youtube.com/watch?v=...",
        )
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(0, Spacing.SM))

        paste_btn = create_styled_button(
            url_input_row,
            "📋 Paste",
            command=self._paste_url,
            style="secondary",
            width=80,
            height=40,
        )
        paste_btn.pack(side="right", padx=(0, Spacing.SM))

        self.analyze_btn = create_styled_button(
            url_input_row,
            "🤖 Analyze",
            command=self._start_ai_recommend,
            style="secondary",
            width=100,
            height=40,
            tooltip="AI analisis video & rekomendasikan pattern + konteks",
        )
        self.analyze_btn.pack(side="right")

        # ── AI Recommendation Card (hidden by default) ──
        self.reco_card = ctk.CTkFrame(
            frame,
            fg_color=Colors.CARD_BG,
            corner_radius=BorderRadius.MD,
            border_width=1,
            border_color=Colors.ACCENT_PRIMARY,
        )
        # Not packed yet — shown after AI analysis

        reco_header = ctk.CTkFrame(self.reco_card, fg_color="transparent")
        reco_header.pack(fill="x", padx=Spacing.MD, pady=(Spacing.SM, 0))

        ctk.CTkLabel(
            reco_header,
            text="🤖 AI Recommendation",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=Colors.ACCENT_PRIMARY,
        ).pack(side="left")

        self.reco_status_label = ctk.CTkLabel(
            reco_header, text="", font=Fonts.body_sm(), text_color=Colors.TEXT_MUTED
        )
        self.reco_status_label.pack(side="right")

        # Pattern recommendation
        reco_pattern_frame = ctk.CTkFrame(
            self.reco_card, fg_color=Colors.BG_SECONDARY, corner_radius=BorderRadius.SM
        )
        reco_pattern_frame.pack(fill="x", padx=Spacing.MD, pady=(Spacing.SM, 0))

        reco_pat_header = ctk.CTkFrame(reco_pattern_frame, fg_color="transparent")
        reco_pat_header.pack(fill="x", padx=Spacing.SM, pady=(Spacing.SM, 0))

        ctk.CTkLabel(
            reco_pat_header,
            text="🎯 Pattern:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=Colors.TEXT_PRIMARY,
        ).pack(side="left")

        self.reco_pattern_apply_btn = create_styled_button(
            reco_pat_header,
            "Gunakan",
            command=self._apply_reco_pattern,
            style="secondary",
            width=70,
            height=26,
        )
        self.reco_pattern_apply_btn.pack(side="right")

        self.reco_pattern_label = ctk.CTkLabel(
            reco_pattern_frame,
            text="...",
            font=Fonts.body(),
            text_color=Colors.TEXT_PRIMARY,
            wraplength=500,
            justify="left",
        )
        self.reco_pattern_label.pack(
            fill="x", padx=Spacing.SM, pady=(2, Spacing.SM), anchor="w"
        )

        # Context recommendations
        reco_ctx_frame = ctk.CTkFrame(
            self.reco_card, fg_color=Colors.BG_SECONDARY, corner_radius=BorderRadius.SM
        )
        reco_ctx_frame.pack(fill="x", padx=Spacing.MD, pady=(Spacing.SM, Spacing.MD))

        ctk.CTkLabel(
            reco_ctx_frame,
            text="✏️ Konteks yang disarankan:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=Colors.TEXT_PRIMARY,
        ).pack(anchor="w", padx=Spacing.SM, pady=(Spacing.SM, 2))

        self.reco_ctx_container = ctk.CTkFrame(reco_ctx_frame, fg_color="transparent")
        self.reco_ctx_container.pack(fill="x", padx=Spacing.SM, pady=(0, Spacing.SM))

        # Clip & Duration recommendation
        reco_clip_frame = ctk.CTkFrame(
            self.reco_card, fg_color=Colors.BG_SECONDARY, corner_radius=BorderRadius.SM
        )
        reco_clip_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        reco_clip_header = ctk.CTkFrame(reco_clip_frame, fg_color="transparent")
        reco_clip_header.pack(fill="x", padx=Spacing.SM, pady=(Spacing.SM, 0))

        ctk.CTkLabel(
            reco_clip_header,
            text="📊 Optimal Clips & Durasi:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=Colors.TEXT_PRIMARY,
        ).pack(side="left")

        self.reco_clip_apply_btn = create_styled_button(
            reco_clip_header,
            "Terapkan",
            command=self._apply_reco_clips,
            style="secondary",
            width=75,
            height=26,
        )
        self.reco_clip_apply_btn.pack(side="right")

        self.reco_clip_summary = ctk.CTkLabel(
            reco_clip_frame,
            text="...",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=Colors.ACCENT_PRIMARY,
            wraplength=500,
            justify="left",
        )
        self.reco_clip_summary.pack(fill="x", padx=Spacing.SM, pady=(4, 0), anchor="w")

        self.reco_clip_detail = ctk.CTkLabel(
            reco_clip_frame,
            text="",
            font=Fonts.body_sm(),
            text_color=Colors.TEXT_SECONDARY,
            wraplength=500,
            justify="left",
        )
        self.reco_clip_detail.pack(
            fill="x", padx=Spacing.SM, pady=(2, Spacing.SM), anchor="w"
        )

        # Pattern Selection
        pattern_card = self._card(frame, "🎯 Pilih Pattern")
        self.pattern_card_ref = pattern_card  # Ref for reco_card insertion

        from clip_dub_engine import PATTERNS

        # Pattern grid (2 columns)
        pattern_grid = ctk.CTkFrame(pattern_card, fg_color="transparent")
        pattern_grid.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        self.pattern_var = ctk.StringVar(value="documentary")

        patterns_list = list(PATTERNS.values())
        for i, p in enumerate(patterns_list):
            row_idx = i // 2
            col_idx = i % 2

            # Ensure row frame exists
            if col_idx == 0:
                row_frame = ctk.CTkFrame(pattern_grid, fg_color="transparent")
                row_frame.pack(fill="x", pady=2)

            radio = ctk.CTkRadioButton(
                row_frame,
                text=f"{p['icon']} {p['name']}",
                variable=self.pattern_var,
                value=p["id"],
                font=Fonts.body_sm(),
                fg_color=Colors.ACCENT_PRIMARY,
                hover_color=Colors.BTN_PRIMARY_HOVER,
                border_color=Colors.BORDER,
                command=self._on_pattern_change,
            )
            radio.pack(side="left", padx=(0, Spacing.LG), pady=2)
            ToolTip(radio, f"{p['description']}\nContoh: {p['example']}")

        # Context input
        context_card = self._card(frame, "✏️ Konteks / Instruksi")

        context_frame = ctk.CTkFrame(context_card, fg_color="transparent")
        context_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        create_styled_label(
            context_frame,
            "Jelaskan apa yang ingin dibuat dari video ini:",
            style="caption",
        ).pack(anchor="w")

        self.context_text = ctk.CTkTextbox(
            context_frame,
            height=100,
            fg_color=Colors.BG_SECONDARY,
            border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY,
            font=Fonts.body(),
            border_width=1,
            corner_radius=BorderRadius.SM,
        )
        self.context_text.pack(fill="x", pady=(4, 0))

        # Insert placeholder/example text
        self._context_placeholder = True
        self.context_text.insert(
            "1.0",
            "Contoh: Ambil bagian yang membahas tips produktivitas dan motivasi, "
            "fokus pada momen yang emosional dan impactful. "
            "Hindari bagian intro/sponsor/outro.",
        )
        self.context_text.configure(text_color=Colors.TEXT_MUTED)
        self.context_text.bind("<FocusIn>", self._on_context_focus_in)
        self.context_text.bind("<FocusOut>", self._on_context_focus_out)

        # Example hint
        self.context_hint = create_styled_label(
            context_frame, "", style="caption", color=Colors.TEXT_MUTED
        )
        self.context_hint.pack(anchor="w", pady=(4, 0))
        self._on_pattern_change()  # Set initial hint

        # Settings row
        settings_card = self._card(frame, "⚙️ Settings")

        settings_row = ctk.CTkFrame(settings_card, fg_color="transparent")
        settings_row.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.SM))

        # Klip Utama
        clip_frame = ctk.CTkFrame(settings_row, fg_color="transparent")
        clip_frame.pack(side="left", padx=(0, Spacing.XL))
        create_styled_label(clip_frame, "Klip Utama:", style="caption").pack(anchor="w")
        self.primary_clips_var = ctk.StringVar(value="7")
        ctk.CTkComboBox(
            clip_frame,
            values=["3", "4", "5", "6", "7", "8", "10", "12", "15"],
            variable=self.primary_clips_var,
            width=70,
            height=32,
            fg_color=Colors.BG_SECONDARY,
            border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY,
            font=Fonts.body_sm(),
            dropdown_fg_color=Colors.CARD_BG,
        ).pack(anchor="w", pady=(4, 0))

        # Klip Cadangan
        spare_frame = ctk.CTkFrame(settings_row, fg_color="transparent")
        spare_frame.pack(side="left", padx=(0, Spacing.XL))
        create_styled_label(spare_frame, "Klip Cadangan:", style="caption").pack(
            anchor="w"
        )
        self.spare_clips_var = ctk.StringVar(value="5")
        ctk.CTkComboBox(
            spare_frame,
            values=["2", "3", "5", "7", "8", "10", "12", "15"],
            variable=self.spare_clips_var,
            width=70,
            height=32,
            fg_color=Colors.BG_SECONDARY,
            border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY,
            font=Fonts.body_sm(),
            dropdown_fg_color=Colors.CARD_BG,
        ).pack(anchor="w", pady=(4, 0))

        # Target duration
        dur_frame = ctk.CTkFrame(settings_row, fg_color="transparent")
        dur_frame.pack(side="left", padx=(0, Spacing.XL))
        create_styled_label(dur_frame, "Target Durasi (detik):", style="caption").pack(
            anchor="w"
        )
        self.target_dur_var = ctk.StringVar(value="90")
        ctk.CTkEntry(
            dur_frame,
            textvariable=self.target_dur_var,
            width=60,
            height=32,
            fg_color=Colors.BG_SECONDARY,
            border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY,
            font=Fonts.body(),
            justify="center",
        ).pack(anchor="w", pady=(4, 0))

        # Subtitle language
        lang_frame = ctk.CTkFrame(settings_row, fg_color="transparent")
        lang_frame.pack(side="left")
        create_styled_label(lang_frame, "Bahasa Subtitle:", style="caption").pack(
            anchor="w"
        )
        self.lang_var = ctk.StringVar(value="id")
        ctk.CTkComboBox(
            lang_frame,
            values=["id", "en", "auto", "ja", "ko", "es"],
            variable=self.lang_var,
            width=100,
            height=32,
            fg_color=Colors.BG_SECONDARY,
            border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY,
            font=Fonts.body_sm(),
            dropdown_fg_color=Colors.CARD_BG,
        ).pack(anchor="w", pady=(4, 0))

        # Row 2: Transisi + Hook
        settings_row2 = ctk.CTkFrame(settings_card, fg_color="transparent")
        settings_row2.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        # Transition
        trans_frame = ctk.CTkFrame(settings_row2, fg_color="transparent")
        trans_frame.pack(side="left", padx=(0, Spacing.XL))
        create_styled_label(trans_frame, "Transisi:", style="caption").pack(anchor="w")
        self.transition_var = ctk.StringVar(value="fade")
        ctk.CTkComboBox(
            trans_frame,
            values=["none", "fade", "dissolve", "wipe_left", "wipe_right", "slide_up"],
            variable=self.transition_var,
            width=120,
            height=32,
            fg_color=Colors.BG_SECONDARY,
            border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY,
            font=Fonts.body_sm(),
            dropdown_fg_color=Colors.CARD_BG,
        ).pack(anchor="w", pady=(4, 0))

        # Hook toggle
        hook_frame = ctk.CTkFrame(settings_row2, fg_color="transparent")
        hook_frame.pack(side="left", padx=(0, Spacing.XL))
        self.hook_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            hook_frame,
            text="🎣 Tambah Hook di awal",
            variable=self.hook_var,
            font=Fonts.body_sm(),
            fg_color=Colors.ACCENT_PRIMARY,
            border_color=Colors.BORDER,
        ).pack(anchor="w", pady=(16, 0))

        # Subtitle status banner (shown after download)
        self.subtitle_status_frame = ctk.CTkFrame(frame, fg_color="transparent")
        self.subtitle_status_frame.pack(fill="x", pady=(0, Spacing.SM))
        # Content is populated dynamically by _show_subtitle_status()

        # Action button
        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=Spacing.MD)

        self.step1_btn = create_styled_button(
            btn_frame,
            "🔍 Download & Find Clips",
            command=self._start_step1,
            style="primary",
            width=250,
            height=44,
            tooltip="Download video dan cari clips yang relevan dengan konteks",
        )
        self.step1_btn.pack()

    # ─── STEP 2: Review Clips (preview, reorder, replace) ───────────

    def _build_step2(self):
        """Review clips with thumbnails, preview, reorder, replace."""
        frame = ctk.CTkFrame(self.content_area, fg_color="transparent")
        self.step_frames[1] = frame

        # Split layout: left = clip list, right = preview player
        self.step2_paned = ctk.CTkFrame(frame, fg_color="transparent")
        self.step2_paned.pack(fill="both", expand=True)

        # Left side: scrollable clip list
        left_wrapper = ctk.CTkFrame(self.step2_paned, fg_color="transparent")
        left_wrapper.pack(side="left", fill="both", expand=True, padx=(0, Spacing.SM))

        # Clip list header
        list_header = ctk.CTkFrame(left_wrapper, fg_color="transparent")
        list_header.pack(fill="x")

        create_styled_label(list_header, "🎬 Clips", style="heading_sm").pack(
            side="left"
        )

        self.spare_badge = ctk.CTkLabel(
            list_header,
            text="",
            font=ctk.CTkFont(size=10),
            text_color=Colors.TEXT_MUTED,
        )
        self.spare_badge.pack(side="right")

        self.clips_scroll = ctk.CTkScrollableFrame(left_wrapper, fg_color="transparent")
        self.clips_scroll.pack(fill="both", expand=True, pady=(Spacing.SM, 0))

        # Right side: preview area (fixed width)
        self.preview_panel = ctk.CTkFrame(
            self.step2_paned,
            fg_color=Colors.CARD_BG,
            width=380,
            corner_radius=BorderRadius.LG,
            border_width=1,
            border_color=Colors.BORDER,
        )
        self.preview_panel.pack(side="right", fill="y", padx=(Spacing.SM, 0))
        self.preview_panel.pack_propagate(False)

        self._preview_placeholder()

        # Bottom buttons
        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(Spacing.MD, 0))

        btn_row = ctk.CTkFrame(btn_frame, fg_color="transparent")
        btn_row.pack()

        create_styled_button(
            btn_row,
            "← URL & Konteks",
            command=lambda: self._show_step(0),
            style="secondary",
            width=140,
            height=40,
        ).pack(side="left", padx=Spacing.SM)

        self.step2_btn = create_styled_button(
            btn_row,
            "🧭 Lanjut ke Portrait Studio →",
            command=self._go_to_portrait_studio,
            style="primary",
            width=280,
            height=40,
        )
        self.step2_btn.pack(side="left", padx=Spacing.SM)

    def _preview_placeholder(self):
        """Show placeholder in preview panel."""
        for w in self.preview_panel.winfo_children():
            w.destroy()

        placeholder = ctk.CTkFrame(self.preview_panel, fg_color="transparent")
        placeholder.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(placeholder, text="🎥", font=ctk.CTkFont(size=40)).pack()
        ctk.CTkLabel(
            placeholder,
            text="Klik ▶ pada clip\nuntuk preview",
            font=Fonts.body_sm(),
            text_color=Colors.TEXT_MUTED,
            justify="center",
        ).pack(pady=(Spacing.SM, 0))

    def _go_to_portrait_studio(self):
        """Navigate from clip review to manual portrait crop studio."""
        if not self.highlights:
            messagebox.showwarning("No Clips", "Tidak ada clips yang dipilih.")
            return
        self._populate_portrait_studio()
        self._show_step(2)

    # ─── STEP 3: Portrait Studio ─────────────────────────────────────

    def _build_step3_portrait(self):
        """Manual portrait crop studio with draggable box and keyframes."""
        frame = ctk.CTkScrollableFrame(self.content_area, fg_color="transparent")
        self.step_frames[2] = frame

        header_card = self._card(frame, "🧭 Portrait Studio (Manual Crop)")
        header_inner = ctk.CTkFrame(header_card, fg_color="transparent")
        header_inner.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        create_styled_label(
            header_inner,
            "Geser kotak crop kiri/kanan untuk pilih area portrait. Aktifkan record keyframe bila objek bergerak.",
            style="caption",
            color=Colors.TEXT_MUTED,
        ).pack(anchor="w")

        selector_row = ctk.CTkFrame(header_inner, fg_color="transparent")
        selector_row.pack(fill="x", pady=(Spacing.SM, 0))

        create_styled_label(selector_row, "Clip aktif:", style="caption").pack(
            side="left"
        )
        self.crop_clip_var = ctk.StringVar(value="")
        self.crop_clip_selector = ctk.CTkComboBox(
            selector_row,
            values=[""],
            variable=self.crop_clip_var,
            width=280,
            height=32,
            command=self._on_select_crop_clip,
            fg_color=Colors.BG_SECONDARY,
            border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY,
            font=Fonts.body_sm(),
            dropdown_fg_color=Colors.CARD_BG,
        )
        self.crop_clip_selector.pack(side="left", padx=(6, 0))

        create_styled_button(
            selector_row,
            "📋 Copy ke semua clip",
            command=self._copy_crop_to_all_clips,
            style="secondary",
            width=140,
            height=32,
        ).pack(side="right")

        create_styled_button(
            selector_row,
            "↺ Reset clip ini",
            command=self._reset_current_crop_clip,
            style="ghost",
            width=120,
            height=32,
        ).pack(side="right", padx=(0, 6))

        editor_card = self._card(frame, "🎞 Preview + Crop")
        self.crop_editor_container = ctk.CTkFrame(editor_card, fg_color="transparent")
        self.crop_editor_container.pack(
            fill="both", expand=True, padx=Spacing.MD, pady=(0, Spacing.MD)
        )

        self.crop_status_label = create_styled_label(
            frame,
            "Belum ada clip untuk diedit.",
            style="caption",
            color=Colors.TEXT_MUTED,
        )
        self.crop_status_label.pack(anchor="w", pady=(0, Spacing.MD))

        nav_frame = ctk.CTkFrame(frame, fg_color="transparent")
        nav_frame.pack(fill="x", pady=Spacing.MD)
        nav_row = ctk.CTkFrame(nav_frame, fg_color="transparent")
        nav_row.pack()

        create_styled_button(
            nav_row,
            "← Review Clips",
            command=lambda: self._show_step(1),
            style="secondary",
            width=120,
            height=40,
        ).pack(side="left", padx=Spacing.SM)

        self.portrait_continue_btn = create_styled_button(
            nav_row,
            "🎬 Assemble & Generate Script →",
            command=self._start_step2,
            style="primary",
            width=260,
            height=40,
        )
        self.portrait_continue_btn.pack(side="left", padx=Spacing.SM)

    def _populate_portrait_studio(self):
        """Initialize manual crop editor and clip selector."""
        clips = self.highlights or []
        self._sync_manual_crop_cache_from_highlights()
        self._clamp_selected_crop_index()
        if not clips:
            self._crop_selector_options = []
            self.crop_clip_selector.configure(values=["(no clips)"])
            self.crop_clip_var.set("(no clips)")
            self.crop_status_label.configure(text="Tidak ada clip yang bisa diedit.")
            return

        options = [
            f"#{i + 1} {h.get('title', 'Untitled')[:45]}" for i, h in enumerate(clips)
        ]
        self._crop_selector_options = options
        self.crop_clip_selector.configure(values=options)

        selected = min(self._selected_crop_idx, len(options) - 1)
        self._selected_crop_idx = selected
        self.crop_clip_var.set(options[selected])

        self._ensure_portrait_editor()
        self._load_crop_editor_for_index(selected)

    def _ensure_portrait_editor(self):
        """Create portrait editor widget if missing."""
        if self._portrait_editor:
            return
        from components.portrait_crop_editor import PortraitCropEditor

        self._portrait_editor = PortraitCropEditor(
            self.crop_editor_container,
            width=700,
            height=400,
            on_change=self._on_portrait_crop_change,
        )
        self._portrait_editor.pack(fill="both", expand=True)

    def _on_select_crop_clip(self, selected_text=None):
        """Switch active clip in portrait studio selector."""
        clips = self.highlights or []
        if not clips:
            return

        # Some CustomTkinter versions call combo command with empty/non-string
        # payload. Always fall back to the bound variable so selection stays
        # reliable across environments.
        if not isinstance(selected_text, str) or not selected_text.strip():
            selected_text = self.crop_clip_var.get()

        idx = self._parse_crop_selector_index(selected_text, len(clips))
        self._selected_crop_idx = idx
        self._load_crop_editor_for_index(idx)

    def _parse_crop_selector_index(self, selected_text: str, clip_count: int) -> int:
        """Parse '#N Title' combo label into a stable clip index."""
        if clip_count <= 0:
            return 0

        m = re.match(r"\s*#(\d+)\b", selected_text or "")
        if m:
            idx = int(m.group(1)) - 1
            if 0 <= idx < clip_count:
                return idx

        if selected_text in self._crop_selector_options:
            idx = self._crop_selector_options.index(selected_text)
            if 0 <= idx < clip_count:
                return idx

        return min(max(self._selected_crop_idx, 0), clip_count - 1)

    def _load_crop_editor_for_index(self, idx: int):
        """Load selected clip into portrait editor with saved manual crop."""
        clips = self.highlights or []
        if idx < 0 or idx >= len(clips) or not self._portrait_editor:
            return

        clip = clips[idx]
        clip_path = clip.get("clip_path", "")
        if not clip_path or not os.path.exists(clip_path):
            self.crop_status_label.configure(
                text=f"Clip #{idx + 1}: file tidak ditemukan"
            )
            return

        saved = clip.get("manual_crop") or self.manual_crop_data.get(idx)
        self._portrait_editor.load_clip(clip_path, saved)
        self.crop_status_label.configure(
            text=f"Clip #{idx + 1}: atur posisi crop. Geser box langsung di preview untuk presisi."
        )

    def _on_portrait_crop_change(self, crop_data: Dict):
        """Persist crop setting whenever user adjusts editor."""
        idx = self._selected_crop_idx
        clips = self.highlights or []
        if idx < 0 or idx >= len(clips):
            return
        self.manual_crop_data[idx] = crop_data
        clips[idx]["manual_crop"] = dict(crop_data)
        if self.engine:
            self.engine.highlights = clips

    def _sync_manual_crop_cache_from_highlights(self):
        """Rebuild index cache from current highlights order."""
        cache: Dict[int, Dict] = {}
        for i, h in enumerate(self.highlights or []):
            mc = h.get("manual_crop")
            if isinstance(mc, dict):
                cache[i] = dict(mc)
        self.manual_crop_data = cache

    def _clamp_selected_crop_index(self):
        """Keep selected crop index inside valid highlight range."""
        total = len(self.highlights or [])
        if total <= 0:
            self._selected_crop_idx = 0
            return
        self._selected_crop_idx = min(max(self._selected_crop_idx, 0), total - 1)

    def _copy_crop_to_all_clips(self):
        """Duplicate current clip crop setup into all clips."""
        if not self._portrait_editor or not self.highlights:
            return
        source = self._portrait_editor.get_crop_data()
        for i in range(len(self.highlights)):
            self.manual_crop_data[i] = dict(source)
            self.highlights[i]["manual_crop"] = dict(source)
        self.crop_status_label.configure(text="✓ Setting crop disalin ke semua clip")

    def _reset_current_crop_clip(self):
        """Reset manual crop for active clip."""
        idx = self._selected_crop_idx
        if not self.highlights or idx < 0 or idx >= len(self.highlights):
            return
        self.manual_crop_data[idx] = {
            "enabled": True,
            "base_center_x": 0.5,
            "keyframes": [],
        }
        self.highlights[idx]["manual_crop"] = dict(self.manual_crop_data[idx])
        if self._portrait_editor:
            self._portrait_editor.reset_crop()
        self.crop_status_label.configure(text=f"✓ Clip #{idx + 1} di-reset ke center")

    # ─── STEP 4: TTS Studio ─────────────────────────────────────────

    def _build_step3(self):
        """TTS Studio - CapCut-like editor for script + TTS preview + timeline."""
        import tkinter as tk

        frame = ctk.CTkScrollableFrame(self.content_area, fg_color="transparent")
        self.step_frames[3] = frame

        # ── Voice Config Card ──
        voice_card = self._card(frame, "🎙️ TTS Studio")
        voice_inner = ctk.CTkFrame(voice_card, fg_color="transparent")
        voice_inner.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        config_row = ctk.CTkFrame(voice_inner, fg_color="transparent")
        config_row.pack(fill="x", pady=(0, Spacing.SM))

        # Voice
        vf = ctk.CTkFrame(config_row, fg_color="transparent")
        vf.pack(side="left", padx=(0, Spacing.XL))
        create_styled_label(vf, "Voice:", style="caption").pack(anchor="w")
        self.voice_var = ctk.StringVar(value="id-ID-ArdiNeural")
        ctk.CTkComboBox(
            vf,
            values=[
                "id-ID-ArdiNeural",
                "id-ID-GadisNeural",
                "en-US-GuyNeural",
                "en-US-JennyNeural",
            ],
            variable=self.voice_var,
            width=180,
            height=32,
            fg_color=Colors.BG_SECONDARY,
            border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY,
            font=Fonts.body_sm(),
            dropdown_fg_color=Colors.CARD_BG,
        ).pack(anchor="w", pady=(4, 0))

        # Speed
        sf = ctk.CTkFrame(config_row, fg_color="transparent")
        sf.pack(side="left", padx=(0, Spacing.XL))
        create_styled_label(sf, "Speed:", style="caption").pack(anchor="w")
        self.speed_var = ctk.StringVar(value="+0%")
        ctk.CTkComboBox(
            sf,
            values=["-20%", "-10%", "+0%", "+10%", "+20%"],
            variable=self.speed_var,
            width=100,
            height=32,
            fg_color=Colors.BG_SECONDARY,
            border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY,
            font=Fonts.body_sm(),
            dropdown_fg_color=Colors.CARD_BG,
        ).pack(anchor="w", pady=(4, 0))

        # Action buttons
        action_row = ctk.CTkFrame(voice_inner, fg_color="transparent")
        action_row.pack(fill="x", pady=(Spacing.SM, 0))

        self.gen_all_tts_btn = create_styled_button(
            action_row,
            "🔊 Generate Semua TTS",
            command=self._generate_all_tts,
            style="primary",
            width=200,
            height=36,
        )
        self.gen_all_tts_btn.pack(side="left", padx=(0, Spacing.SM))

        self.stop_audio_btn = create_styled_button(
            action_row,
            "⏹ Stop",
            command=self._stop_audio,
            style="ghost",
            width=70,
            height=36,
        )
        self.stop_audio_btn.pack(side="left")

        self.tts_status_label = create_styled_label(
            voice_inner, "", style="caption", color=Colors.TEXT_MUTED
        )
        self.tts_status_label.pack(anchor="w", pady=(4, 0))

        # ── Timeline Card ──
        timeline_card = self._card(frame, "🎬 Timeline")
        timeline_inner = ctk.CTkFrame(timeline_card, fg_color="transparent")
        timeline_inner.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        self.timeline_canvas = tk.Canvas(
            timeline_inner, height=60, bg=Colors.BG_TERTIARY, highlightthickness=0, bd=0
        )
        self.timeline_canvas.pack(fill="x")
        self.timeline_canvas.bind("<Configure>", lambda e: self._draw_timeline())

        # ── Segments List Card ──
        segments_card = self._card(frame, "📝 Segments")
        self.tts_segments_container = ctk.CTkFrame(
            segments_card, fg_color="transparent"
        )
        self.tts_segments_container.pack(
            fill="x", padx=Spacing.MD, pady=(0, Spacing.MD)
        )

        # Placeholder
        self.tts_seg_placeholder = create_styled_label(
            self.tts_segments_container,
            "Generate script dulu di step sebelumnya...",
            style="caption",
            color=Colors.TEXT_MUTED,
        )
        self.tts_seg_placeholder.pack(pady=Spacing.MD)

        # ── AI Revision Card ──
        revision_card = self._card(frame, "🔄 Revisi Script dengan AI")
        revision_inner = ctk.CTkFrame(revision_card, fg_color="transparent")
        revision_inner.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        create_styled_label(
            revision_inner,
            "Jelaskan apa yang perlu diubah (akan regenerate script + hapus TTS lama):",
            style="caption",
        ).pack(anchor="w")

        self.revision_text = ctk.CTkTextbox(
            revision_inner,
            height=60,
            fg_color=Colors.BG_SECONDARY,
            border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY,
            font=Fonts.body_sm(),
            border_width=1,
            corner_radius=BorderRadius.SM,
        )
        self.revision_text.pack(fill="x", pady=(4, 0))
        self.revision_text.insert(
            "1.0",
            "Contoh: Hapus info yang tidak relevan, buat transisi lebih smooth...",
        )

        revision_btn_row = ctk.CTkFrame(revision_inner, fg_color="transparent")
        revision_btn_row.pack(fill="x", pady=(Spacing.SM, 0))

        self.revise_btn = create_styled_button(
            revision_btn_row,
            "🔄 Revisi Script",
            command=self._revise_script,
            style="secondary",
            width=140,
            height=36,
        )
        self.revise_btn.pack(side="left")

        self.regen_btn = create_styled_button(
            revision_btn_row,
            "🔁 Regenerate Semua",
            command=self._regenerate_script,
            style="ghost",
            width=160,
            height=36,
            tooltip="Generate ulang script dari awal dengan konteks yang sama",
        )
        self.regen_btn.pack(side="left", padx=Spacing.SM)

        # ── Navigation ──
        nav_frame = ctk.CTkFrame(frame, fg_color="transparent")
        nav_frame.pack(fill="x", pady=Spacing.MD)

        nav_row = ctk.CTkFrame(nav_frame, fg_color="transparent")
        nav_row.pack()

        create_styled_button(
            nav_row,
            "← Back",
            command=lambda: self._show_step(2),
            style="secondary",
            width=100,
            height=40,
        ).pack(side="left", padx=Spacing.SM)

        self.step4_btn = create_styled_button(
            nav_row,
            "🚀 Continue to Render →",
            command=lambda: self._show_step(4),
            style="primary",
            width=220,
            height=40,
        )
        self.step4_btn.pack(side="left", padx=Spacing.SM)

    # ─── STEP 4: Render ──────────────────────────────────────────────

    def _build_step4(self):
        """Simplified render config - subtitle + BGM + render."""
        frame = ctk.CTkScrollableFrame(self.content_area, fg_color="transparent")
        self.step_frames[4] = frame

        # Subtitle toggle
        sub_card = self._card(frame, "🔤 Subtitle")
        sub_inner = ctk.CTkFrame(sub_card, fg_color="transparent")
        sub_inner.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        self.subtitle_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            sub_inner,
            text="🔤 Burn subtitle ke video",
            variable=self.subtitle_var,
            font=Fonts.body_sm(),
            fg_color=Colors.ACCENT_PRIMARY,
            border_color=Colors.BORDER,
        ).pack(anchor="w")

        # TTS Summary
        self.tts_summary_label = create_styled_label(
            sub_inner, "", style="caption", color=Colors.TEXT_MUTED
        )
        self.tts_summary_label.pack(anchor="w", pady=(Spacing.SM, 0))

        # BGM
        bgm_card = self._card(frame, "🎵 Background Music (Opsional)")
        bgm_inner = ctk.CTkFrame(bgm_card, fg_color="transparent")
        bgm_inner.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        create_styled_label(
            bgm_inner, "BGM URL (TikTok/YouTube):", style="caption"
        ).pack(anchor="w")
        self.bgm_var = ctk.StringVar()
        ctk.CTkEntry(
            bgm_inner,
            textvariable=self.bgm_var,
            height=32,
            fg_color=Colors.BG_SECONDARY,
            border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY,
            font=Fonts.body_sm(),
            placeholder_text="Kosongkan jika tidak ingin BGM",
        ).pack(fill="x", pady=(4, 0))

        vol_row = ctk.CTkFrame(bgm_inner, fg_color="transparent")
        vol_row.pack(fill="x", pady=(Spacing.SM, 0))
        create_styled_label(vol_row, "Volume BGM:", style="caption").pack(side="left")
        self.bgm_vol_var = ctk.DoubleVar(value=0.15)
        ctk.CTkSlider(
            vol_row,
            from_=0,
            to=0.5,
            variable=self.bgm_vol_var,
            width=150,
            fg_color=Colors.BG_SECONDARY,
            progress_color=Colors.ACCENT_PRIMARY,
            button_color=Colors.ACCENT_PRIMARY,
        ).pack(side="left", padx=Spacing.SM)
        self.bgm_vol_label = ctk.CTkLabel(
            vol_row, text="15%", font=Fonts.body_sm(), text_color=Colors.TEXT_MUTED
        )
        self.bgm_vol_label.pack(side="left")
        self.bgm_vol_var.trace_add("write", self._update_bgm_label)

        # Render button
        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=Spacing.MD)

        btn_row = ctk.CTkFrame(btn_frame, fg_color="transparent")
        btn_row.pack()

        create_styled_button(
            btn_row,
            "← TTS Studio",
            command=lambda: self._show_step(3),
            style="secondary",
            width=120,
            height=44,
        ).pack(side="left", padx=Spacing.SM)

        self.render_btn = create_styled_button(
            btn_row,
            "🚀 Render Final Video",
            command=self._start_render,
            style="primary",
            width=220,
            height=44,
        )
        self.render_btn.pack(side="left", padx=Spacing.SM)

    # ─── UI Helpers ───────────────────────────────────────────────────

    def _card(self, parent, title: str) -> ctk.CTkFrame:
        """Create a styled card with title."""
        card = ctk.CTkFrame(
            parent,
            fg_color=Colors.CARD_BG,
            corner_radius=BorderRadius.LG,
            border_width=1,
            border_color=Colors.BORDER,
        )
        card.pack(fill="x", pady=(0, Spacing.MD))

        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.MD, pady=(Spacing.MD, Spacing.SM))
        create_styled_label(header, title, style="heading_sm").pack(anchor="w")

        return card

    def _show_step(self, step_idx: int):
        """Show a specific step, hide others."""
        # Close any open preview player when switching steps
        self._close_preview_player()
        self._stop_audio()
        if self._portrait_editor and step_idx != 2:
            try:
                self._portrait_editor.stop()
            except Exception:
                pass

        self.current_step = step_idx

        for idx, f in self.step_frames.items():
            f.pack_forget()

        self.step_frames[step_idx].pack(fill="both", expand=True)
        self._build_step_indicator()

        # Populate Portrait Studio
        if step_idx == 2:
            self._populate_portrait_studio()

        # Populate TTS Studio
        if step_idx == 3 and self.script_data:
            self._populate_tts_segments()

        # Update TTS summary when going to Render step
        if step_idx == 4:
            self._sync_tts_data_from_ui()
            self._update_tts_summary()

    def _paste_url(self):
        try:
            url = self.clipboard_get()
            self.url_var.set(url)
        except Exception:
            pass

    def _on_pattern_change(self):
        """Update context hint when pattern changes."""
        from clip_dub_engine import PATTERNS

        pattern = PATTERNS.get(self.pattern_var.get(), {})
        self.context_hint.configure(text=f"💡 Contoh: {pattern.get('example', '')}")

    def _on_context_focus_in(self, event=None):
        """Clear placeholder text when user clicks the context textbox."""
        if self._context_placeholder:
            self.context_text.delete("1.0", "end")
            self.context_text.configure(text_color=Colors.TEXT_PRIMARY)
            self._context_placeholder = False

    def _on_context_focus_out(self, event=None):
        """Restore placeholder if textbox is empty."""
        content = self.context_text.get("1.0", "end-1c").strip()
        if not content:
            self._context_placeholder = True
            self.context_text.insert(
                "1.0",
                "Contoh: Ambil bagian yang membahas tips produktivitas dan motivasi, "
                "fokus pada momen yang emosional dan impactful. "
                "Hindari bagian intro/sponsor/outro.",
            )
            self.context_text.configure(text_color=Colors.TEXT_MUTED)

    # ─── AI Recommendation ────────────────────────────────────────────

    def _start_ai_recommend(self):
        """Trigger AI recommendation in background thread."""
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("No URL", "Masukkan YouTube URL terlebih dahulu.")
            return
        if self._reco_running:
            return

        self._reco_running = True
        self.analyze_btn.configure(state="disabled", text="⏳ Analyzing...")

        # Show the reco card with loading state
        self.reco_card.pack(
            fill="x", pady=(0, Spacing.SM), before=self.pattern_card_ref
        )
        self.reco_status_label.configure(text="Mengambil info video...")
        self.reco_pattern_label.configure(text="...")
        for w in self.reco_ctx_container.winfo_children():
            w.destroy()

        threading.Thread(
            target=self._run_ai_recommend, args=(url,), daemon=True
        ).start()

    def _run_ai_recommend(self, url: str):
        """Background: fetch video info → AI recommend pattern + context + clips."""
        try:
            from clip_dub_engine import (
                fetch_video_info_light,
                recommend_pattern_and_context,
                recommend_clips_and_duration,
            )

            self.after(
                0,
                lambda: self.reco_status_label.configure(
                    text="📡 Mengambil info video..."
                ),
            )

            # Build config
            engine_config = dict(self.config) if isinstance(self.config, dict) else {}
            if hasattr(self.config, "config"):
                engine_config = dict(self.config.config)
            if hasattr(self.config, "get_resolved_ai_providers"):
                engine_config["ai_providers"] = self.config.get_resolved_ai_providers()

            video_info = fetch_video_info_light(url, engine_config)
            title = video_info.get("title", "?")

            self.after(
                0,
                lambda: self.reco_status_label.configure(
                    text=f"🤖 Analyzing: {title[:50]}..."
                ),
            )

            result = recommend_pattern_and_context(video_info, engine_config)

            # Compute clip/duration recommendation (pure logic, instant)
            clip_reco = recommend_clips_and_duration(video_info.get("duration", 0))
            result["clip_reco"] = clip_reco

            self._reco_result = result

            self.after(0, lambda: self._display_recommendation(result))

        except Exception as e:
            error_msg = str(e)[:120]
            self.after(
                0, lambda: self.reco_status_label.configure(text=f"❌ {error_msg}")
            )
        finally:
            self._reco_running = False
            self.after(
                0, lambda: self.analyze_btn.configure(state="normal", text="🤖 Analyze")
            )

    def _display_recommendation(self, result: dict):
        """Populate recommendation card with AI results."""
        from clip_dub_engine import PATTERNS

        pid = result.get("pattern_id", "documentary")
        pattern = PATTERNS.get(pid, {})
        reason = result.get("pattern_reason", "")

        self.reco_status_label.configure(text="✅ Rekomendasi siap!")
        self.reco_pattern_label.configure(
            text=f"{pattern.get('icon', '')} {pattern.get('name', pid)}  —  {reason}"
        )

        # Build context suggestion buttons
        for w in self.reco_ctx_container.winfo_children():
            w.destroy()

        contexts = result.get("contexts", [])
        for i, ctx_text in enumerate(contexts[:3]):
            ctx_row = ctk.CTkFrame(self.reco_ctx_container, fg_color="transparent")
            ctx_row.pack(fill="x", pady=1)

            ctx_label = ctk.CTkLabel(
                ctx_row,
                text=f"{i + 1}. {ctx_text}",
                font=Fonts.body_sm(),
                text_color=Colors.TEXT_SECONDARY,
                wraplength=450,
                justify="left",
                anchor="w",
            )
            ctx_label.pack(side="left", fill="x", expand=True)

            use_btn = create_styled_button(
                ctx_row,
                "Pakai",
                command=lambda t=ctx_text: self._apply_reco_context(t),
                style="secondary",
                width=55,
                height=24,
            )
            use_btn.pack(side="right", padx=(Spacing.SM, 0))

        # Populate clip/duration recommendation
        clip_reco = result.get("clip_reco", {})
        if clip_reco:
            self.reco_clip_summary.configure(text=clip_reco.get("reason", ""))
            self.reco_clip_detail.configure(text=clip_reco.get("detail", ""))

    def _apply_reco_pattern(self):
        """Apply recommended pattern to the pattern selector."""
        if not self._reco_result:
            return
        pid = self._reco_result.get("pattern_id", "documentary")
        self.pattern_var.set(pid)
        self._on_pattern_change()

    def _apply_reco_context(self, text: str):
        """Apply a recommended context to the context textbox."""
        self._on_context_focus_in()  # Clear placeholder if needed
        self.context_text.delete("1.0", "end")
        self.context_text.insert("1.0", text)
        self.context_text.configure(text_color=Colors.TEXT_PRIMARY)
        self._context_placeholder = False

    def _apply_reco_clips(self):
        """Apply recommended clip counts and duration to settings."""
        if not self._reco_result:
            return
        clip_reco = self._reco_result.get("clip_reco", {})
        if not clip_reco:
            return
        self.primary_clips_var.set(str(clip_reco.get("primary_clips", 7)))
        self.spare_clips_var.set(str(clip_reco.get("spare_clips", 5)))
        self.target_dur_var.set(str(clip_reco.get("target_duration", 90)))

    def _get_context_text(self) -> str:
        """Get actual context text, ignoring placeholder."""
        if self._context_placeholder:
            return ""
        return self.context_text.get("1.0", "end-1c").strip()

    def _show_subtitle_status(self, found: bool, lang: str, srt_path: str = None):
        """Show subtitle detection result in the UI banner."""
        for w in self.subtitle_status_frame.winfo_children():
            w.destroy()

        if found:
            banner = ctk.CTkFrame(
                self.subtitle_status_frame,
                fg_color=Colors.CARD_BG,
                corner_radius=BorderRadius.SM,
                border_width=1,
                border_color=Colors.SUCCESS,
            )
            banner.pack(fill="x")

            inner = ctk.CTkFrame(banner, fg_color="transparent")
            inner.pack(fill="x", padx=Spacing.MD, pady=Spacing.SM)

            ctk.CTkLabel(
                inner,
                text="✅ Subtitle ditemukan!",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#27ae60",
            ).pack(anchor="w")

            srt_name = Path(srt_path).name if srt_path else "?"
            ctk.CTkLabel(
                inner,
                text=f"📄 {srt_name}  •  Bahasa: {lang.upper()}  •  "
                f"AI akan menggunakan subtitle ini untuk menemukan momen terbaik",
                font=ctk.CTkFont(size=10),
                text_color=Colors.TEXT_MUTED,
                anchor="w",
                wraplength=500,
            ).pack(anchor="w", pady=(2, 0))
        else:
            banner = ctk.CTkFrame(
                self.subtitle_status_frame,
                fg_color=Colors.CARD_BG,
                corner_radius=BorderRadius.SM,
                border_width=1,
                border_color=Colors.ERROR,
            )
            banner.pack(fill="x")

            inner = ctk.CTkFrame(banner, fg_color="transparent")
            inner.pack(fill="x", padx=Spacing.MD, pady=Spacing.SM)

            ctk.CTkLabel(
                inner,
                text="❌ Subtitle tidak ditemukan!",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#e74c3c",
            ).pack(anchor="w")

            ctk.CTkLabel(
                inner,
                text=f"Video ini tidak memiliki subtitle bahasa '{lang.upper()}'.\n"
                f"Fitur Clip+Dub memerlukan subtitle agar AI bisa menemukan momen yang relevan.",
                font=ctk.CTkFont(size=10),
                text_color=Colors.TEXT_MUTED,
                anchor="w",
                justify="left",
                wraplength=500,
            ).pack(anchor="w", pady=(2, 0))

            # Suggestions
            sug_frame = ctk.CTkFrame(inner, fg_color="transparent")
            sug_frame.pack(fill="x", pady=(Spacing.SM, 0))

            ctk.CTkLabel(
                sug_frame,
                text="💡 Saran:",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=Colors.WARNING,
            ).pack(anchor="w")

            suggestions = [
                "• Ganti bahasa subtitle → coba 'en' (English) atau 'auto' (otomatis)",
                "• Gunakan video lain yang memiliki subtitle/CC",
                "• Upload subtitle manual (.srt) ke YouTube lalu coba lagi",
            ]
            for s in suggestions:
                ctk.CTkLabel(
                    sug_frame,
                    text=s,
                    font=ctk.CTkFont(size=10),
                    text_color=Colors.TEXT_SECONDARY,
                    anchor="w",
                ).pack(anchor="w", pady=1)

            # Quick action buttons
            action_row = ctk.CTkFrame(inner, fg_color="transparent")
            action_row.pack(fill="x", pady=(Spacing.SM, 0))

            ctk.CTkButton(
                action_row,
                text="🔄 Coba English (en)",
                width=140,
                height=28,
                fg_color=Colors.ACCENT_PRIMARY,
                hover_color=Colors.BTN_PRIMARY_HOVER,
                font=ctk.CTkFont(size=11),
                text_color=Colors.TEXT_PRIMARY,
                command=lambda: self._retry_with_lang("en"),
            ).pack(side="left", padx=(0, 6))

            ctk.CTkButton(
                action_row,
                text="🔄 Coba Auto",
                width=110,
                height=28,
                fg_color=Colors.BG_SECONDARY,
                hover_color=Colors.CARD_HOVER,
                font=ctk.CTkFont(size=11),
                text_color=Colors.TEXT_PRIMARY,
                command=lambda: self._retry_with_lang("auto"),
            ).pack(side="left", padx=(0, 6))

            ctk.CTkButton(
                action_row,
                text="📋 Ganti URL",
                width=100,
                height=28,
                fg_color=Colors.BG_SECONDARY,
                hover_color=Colors.CARD_HOVER,
                font=ctk.CTkFont(size=11),
                text_color=Colors.TEXT_PRIMARY,
                command=lambda: self.url_entry.focus_set(),
            ).pack(side="left")

    def _retry_with_lang(self, lang: str):
        """Set subtitle language and restart step 1."""
        self.lang_var.set(lang)
        self._start_step1()

    def _update_bgm_label(self, *args):
        try:
            val = self.bgm_vol_var.get()
            self.bgm_vol_label.configure(text=f"{val:.0%}")
        except Exception:
            pass

    def _go_back(self):
        """Go back to landing page."""
        if self._processing:
            if not messagebox.askyesno(
                "Confirm", "Processing sedang berjalan. Yakin ingin cancel?"
            ):
                return
            self._cancel_flag = True
        self._close_preview_player()
        self.app.show_page("landing")

    def _set_status(self, msg: str, progress: float = -1):
        """Update status bar (thread-safe)."""

        def _update():
            self.status_label.configure(text=msg)
            if progress >= 0:
                self.progress_bar.set(progress)
                self.panel_progress_bar.set(progress)
                pct_text = f"{int(progress * 100)}%"
                self.panel_pct_label.configure(text=pct_text)

        self.after(0, _update)

    def _set_buttons_state(self, enabled: bool):
        """Enable/disable action buttons."""
        state = "normal" if enabled else "disabled"
        for btn in [
            self.step1_btn,
            self.step2_btn,
            self.portrait_continue_btn,
            self.step4_btn,
            self.render_btn,
            self.revise_btn,
            self.regen_btn,
            self.gen_all_tts_btn,
        ]:
            try:
                btn.configure(state=state)
            except Exception:
                pass

    # ─── Progress Panel ───────────────────────────────────────────────

    ENGINE_STEPS = [
        ("📥", "Download"),
        ("🔍", "Cari Klip"),
        ("🎬", "Assemble"),
        ("✍️", "Script"),
        ("🔄", "Revisi"),
        ("🎤", "Render"),
    ]

    def _build_progress_panel(self):
        """Build the collapsible progress panel above the status bar."""
        self.progress_panel = ctk.CTkFrame(
            self,
            fg_color=Colors.CARD_BG,
            border_width=1,
            border_color=Colors.BORDER,
            corner_radius=0,
        )
        # Initially hidden
        self.progress_panel.pack_forget()

        inner = ctk.CTkFrame(self.progress_panel, fg_color="transparent")
        inner.pack(fill="x", padx=Spacing.MD, pady=Spacing.SM)

        # Row 1: Step tracker (horizontal pipeline indicators)
        steps_row = ctk.CTkFrame(inner, fg_color="transparent")
        steps_row.pack(fill="x", pady=(0, Spacing.SM))

        self._step_indicators = []
        for i, (icon, name) in enumerate(self.ENGINE_STEPS):
            step_frame = ctk.CTkFrame(steps_row, fg_color="transparent")
            step_frame.pack(side="left", expand=True, fill="x")

            # Icon + label combined
            lbl = ctk.CTkLabel(
                step_frame,
                text=f"{icon} {name}",
                font=ctk.CTkFont(size=11),
                text_color=Colors.TEXT_MUTED,
                anchor="center",
            )
            lbl.pack()

            # Small bar under each step
            bar = ctk.CTkFrame(
                step_frame, height=3, fg_color=Colors.BORDER, corner_radius=1
            )
            bar.pack(fill="x", padx=4, pady=(2, 0))

            self._step_indicators.append(
                {"frame": step_frame, "label": lbl, "bar": bar}
            )

        # Row 2: Current activity + percentage
        activity_row = ctk.CTkFrame(inner, fg_color="transparent")
        activity_row.pack(fill="x", pady=(0, 4))

        self.panel_activity_label = ctk.CTkLabel(
            activity_row,
            text="Menunggu...",
            font=ctk.CTkFont(size=12),
            text_color=Colors.TEXT_PRIMARY,
            anchor="w",
        )
        self.panel_activity_label.pack(side="left", fill="x", expand=True)

        self.panel_pct_label = ctk.CTkLabel(
            activity_row,
            text="0%",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=Colors.ACCENT_PRIMARY,
            width=50,
            anchor="e",
        )
        self.panel_pct_label.pack(side="right")

        # Row 3: Full-width progress bar
        self.panel_progress_bar = ctk.CTkProgressBar(
            inner,
            height=6,
            fg_color=Colors.BG_SECONDARY,
            progress_color=Colors.ACCENT_PRIMARY,
        )
        self.panel_progress_bar.set(0)
        self.panel_progress_bar.pack(fill="x", pady=(0, 4))

        # Row 4: Scrollable log area (compact, last N messages)
        log_frame = ctk.CTkFrame(
            inner, fg_color=Colors.BG_SECONDARY, corner_radius=4, height=80
        )
        log_frame.pack(fill="x")
        log_frame.pack_propagate(False)

        self.panel_log_text = ctk.CTkTextbox(
            log_frame,
            height=72,
            fg_color=Colors.BG_SECONDARY,
            text_color=Colors.TEXT_MUTED,
            font=ctk.CTkFont(family="Consolas", size=10),
            activate_scrollbars=True,
            wrap="word",
            state="disabled",
        )
        self.panel_log_text.pack(fill="both", expand=True, padx=4, pady=4)

    def _show_progress_panel(self):
        """Show the progress panel (pack above status bar)."""
        self._log_lines = []
        self._current_engine_step = 0
        # Reset step indicators
        for ind in self._step_indicators:
            ind["label"].configure(text_color=Colors.TEXT_MUTED)
            ind["bar"].configure(fg_color=Colors.BORDER)
        self.panel_progress_bar.set(0)
        self.panel_pct_label.configure(text="0%")
        self.panel_activity_label.configure(text="Memulai...")
        self.panel_log_text.configure(state="normal")
        self.panel_log_text.delete("1.0", "end")
        self.panel_log_text.configure(state="disabled")
        # Pack between content and status bar
        self.progress_panel.pack(fill="x", side="bottom", before=self.status_bar)

    def _hide_progress_panel(self):
        """Hide the progress panel."""
        self.progress_panel.pack_forget()

    def _on_step_update(
        self, step_num: int, total_steps: int, step_name: str, detail: str
    ):
        """Handle structured step update from engine (thread-safe)."""

        def _update():
            self._current_engine_step = step_num
            # Update step indicators
            for i, ind in enumerate(self._step_indicators):
                s = i + 1
                if s < step_num:
                    # Done
                    ind["label"].configure(text_color=Colors.SUCCESS)
                    ind["bar"].configure(fg_color=Colors.SUCCESS)
                elif s == step_num:
                    # Active
                    ind["label"].configure(text_color=Colors.ACCENT_PRIMARY)
                    ind["bar"].configure(fg_color=Colors.ACCENT_PRIMARY)
                else:
                    # Pending
                    ind["label"].configure(text_color=Colors.TEXT_MUTED)
                    ind["bar"].configure(fg_color=Colors.BORDER)
            # Update activity label
            self.panel_activity_label.configure(
                text=f"Step {step_num}/{total_steps}: {step_name} — {detail}"
                if detail
                else f"Step {step_num}/{total_steps}: {step_name}"
            )

        self.after(0, _update)

    def _add_log_line(self, msg: str):
        """Add a line to the progress panel log (thread-safe). Keeps last 50 lines."""

        def _update():
            clean = msg.strip()
            if not clean:
                return
            # Skip separator lines
            if clean.startswith("━"):
                return
            self._log_lines.append(clean)
            if len(self._log_lines) > 50:
                self._log_lines = self._log_lines[-50:]
            self.panel_log_text.configure(state="normal")
            self.panel_log_text.delete("1.0", "end")
            self.panel_log_text.insert("1.0", "\n".join(self._log_lines))
            self.panel_log_text.see("end")
            self.panel_log_text.configure(state="disabled")

        self.after(0, _update)

    # ─── STEP 1: Download & Find Clips ────────────────────────────────

    def _start_step1(self):
        """Start download + context-aware clip finding."""
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("No URL", "Masukkan YouTube URL terlebih dahulu.")
            return

        context = self._get_context_text()
        if not context and self.pattern_var.get() == "custom":
            messagebox.showwarning(
                "No Context", "Masukkan konteks/instruksi untuk Pattern Custom."
            )
            return

        try:
            primary_val = self.primary_clips_var.get().strip()
            primary_clips = int(primary_val)
            if not 1 <= primary_clips <= 20:
                raise ValueError()
            spare_val = self.spare_clips_var.get().strip()
            spare_clips = int(spare_val)
            if not 0 <= spare_clips <= 20:
                raise ValueError()
        except ValueError:
            messagebox.showwarning(
                "Invalid", "Klip utama (1-20) dan cadangan (0-20) harus angka valid."
            )
            return

        self._processing = True
        self._cancel_flag = False
        self._set_buttons_state(False)
        self.after(0, self._show_progress_panel)

        threading.Thread(target=self._run_step1, daemon=True).start()

    def _run_step1(self):
        """Background thread: download + find clips + cut individual clips."""
        try:
            from clip_dub_engine import ClipDubEngine, PATTERNS

            # Build config from app
            engine_config = dict(self.config) if isinstance(self.config, dict) else {}
            if hasattr(self.config, "config"):
                engine_config = dict(self.config.config)

            # Ensure ai_providers are resolved
            if hasattr(self.config, "get_resolved_ai_providers"):
                engine_config["ai_providers"] = self.config.get_resolved_ai_providers()

            engine_config["subtitle_language"] = self.lang_var.get()
            engine_config["output_dir"] = engine_config.get("output_dir", "output")

            self.engine = ClipDubEngine(
                config=engine_config,
                log_callback=lambda msg: (
                    self._set_status(msg),
                    self._add_log_line(msg),
                ),
                progress_callback=lambda s, p: self._set_status(s, p),
                cancel_check=lambda: self._cancel_flag,
                step_callback=lambda sn, st, nm, dt: self._on_step_update(
                    sn, st, nm, dt
                ),
            )

            # Step 1a: Download
            self.download_result = self.engine.download_video(
                self.url_var.get().strip()
            )

            if self._cancel_flag:
                return

            sub_lang = self.lang_var.get()
            srt_path = self.download_result.get("srt_path")
            has_sub = self.download_result.get("has_subtitle", False)

            # Show subtitle status in UI
            self.after(
                0, lambda: self._show_subtitle_status(has_sub, sub_lang, srt_path)
            )

            if not has_sub:
                self.after(
                    0,
                    lambda: self._set_status(
                        f"❌ Subtitle '{sub_lang}' tidak ditemukan — lihat saran di atas",
                        0.15,
                    ),
                )
                self._processing = False
                self.after(0, lambda: self._set_buttons_state(True))
                return

            # Step 1b: Find context-aware clips (with spares)
            self.after(
                0,
                lambda: self._set_status(
                    f"✅ Subtitle ditemukan ({sub_lang.upper()}) — mencari clips...",
                    0.25,
                ),
            )

            context = self._get_context_text()
            pattern_id = self.pattern_var.get()

            pattern = PATTERNS.get(pattern_id, {})
            if not context:
                context = pattern.get("description", "Buat ringkasan video ini")

            num_clips_val = self.primary_clips_var.get().strip()
            primary_clips = int(num_clips_val) if num_clips_val.isdigit() else 7
            spare_val = self.spare_clips_var.get().strip()
            spare_clips = int(spare_val) if spare_val.isdigit() else 5
            target_dur = int(self.target_dur_var.get() or 90)

            self.highlights = self.engine.find_context_clips(
                user_context=context,
                pattern_id=pattern_id,
                primary_clips=primary_clips,
                spare_clips=spare_clips,
                target_duration=target_dur,
            )
            self.spare_highlights = list(self.engine.spare_highlights or [])

            if self._cancel_flag:
                return

            # Step 1c: Cut each clip individually for preview
            self._set_status("✂️ Cutting individual clips for preview...", 0.6)
            self.engine.cut_individual_clips(self.highlights)

            if self._cancel_flag:
                return

            # Populate step 2 and navigate
            self.after(0, self._populate_clips)
            self.after(0, lambda: self._show_step(1))

        except Exception as e:
            error_msg = str(e)
            self.after(0, lambda: messagebox.showerror("Error", error_msg))
            self.after(0, lambda: self._set_status(f"Error: {error_msg[:80]}", 0))
        finally:
            self._processing = False
            self.after(0, lambda: self._set_buttons_state(True))
            self.after(500, self._hide_progress_panel)

    def _populate_clips(self):
        """Build clip cards with thumbnails, preview, reorder, replace buttons."""
        for w in self.clips_scroll.winfo_children():
            w.destroy()
        self._thumbnail_refs = []

        if not self.highlights:
            create_styled_label(
                self.clips_scroll, "No clips found.", style="body"
            ).pack(pady=Spacing.MD)
            return

        spare_count = len(self.spare_highlights or [])
        self.spare_badge.configure(text=f"⚪ {spare_count} cadangan tersedia")

        # Primary clips header
        primary_header = ctk.CTkFrame(self.clips_scroll, fg_color="transparent")
        primary_header.pack(fill="x", pady=(0, Spacing.XS))
        ctk.CTkLabel(
            primary_header,
            text=f"🔵 Klip Utama ({len(self.highlights)})",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=Colors.ACCENT_PRIMARY,
        ).pack(side="left")

        for i, h in enumerate(self.highlights):
            self._create_clip_card(i, h, is_spare=False)

        # Spare clips section
        if self.spare_highlights:
            sep = ctk.CTkFrame(self.clips_scroll, fg_color=Colors.BORDER, height=1)
            sep.pack(fill="x", pady=Spacing.SM)

            spare_header = ctk.CTkFrame(self.clips_scroll, fg_color="transparent")
            spare_header.pack(fill="x", pady=(0, Spacing.XS))
            ctk.CTkLabel(
                spare_header,
                text=f"⚪ Klip Cadangan ({len(self.spare_highlights)})",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=Colors.TEXT_MUTED,
            ).pack(side="left")
            ctk.CTkLabel(
                spare_header,
                text="Klik ↑ Promosikan untuk menambahkan ke klip utama",
                font=ctk.CTkFont(size=10),
                text_color=Colors.TEXT_MUTED,
            ).pack(side="right")

            for j, sh in enumerate(self.spare_highlights):
                self._create_clip_card(j, sh, is_spare=True)

    def _create_clip_card(self, idx: int, h: dict, is_spare: bool = False):
        """Create a single clip card with thumbnail, play, replace, reorder."""
        border_color = Colors.BORDER if not is_spare else Colors.BORDER_HOVER
        card_bg = Colors.CARD_BG if not is_spare else Colors.BG_TERTIARY

        card = ctk.CTkFrame(
            self.clips_scroll,
            fg_color=card_bg,
            corner_radius=BorderRadius.MD,
            border_width=1,
            border_color=border_color,
        )
        card.pack(fill="x", pady=(0, Spacing.SM))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=Spacing.SM, pady=Spacing.SM)

        # Row 1: Thumbnail + Info
        top_row = ctk.CTkFrame(inner, fg_color="transparent")
        top_row.pack(fill="x")

        # Thumbnail (left)
        thumb_frame = ctk.CTkFrame(
            top_row, fg_color=Colors.BG_TERTIARY, width=120, height=68, corner_radius=4
        )
        thumb_frame.pack(side="left", padx=(0, Spacing.SM))
        thumb_frame.pack_propagate(False)

        clip_path = h.get("clip_path", "")
        if clip_path and os.path.exists(clip_path):
            self._load_thumbnail_async(clip_path, thumb_frame)
        else:
            ctk.CTkLabel(
                thumb_frame,
                text="🎬",
                font=ctk.CTkFont(size=20),
                text_color=Colors.TEXT_MUTED,
            ).place(relx=0.5, rely=0.5, anchor="center")

        # Info (right of thumbnail)
        info_frame = ctk.CTkFrame(top_row, fg_color="transparent")
        info_frame.pack(side="left", fill="x", expand=True)

        title_row = ctk.CTkFrame(info_frame, fg_color="transparent")
        title_row.pack(fill="x")

        tag = "⚪" if is_spare else "🔵"
        title = h.get("title", "Untitled")
        ctk.CTkLabel(
            title_row,
            text=f"{tag} #{idx + 1}. {title}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=Colors.TEXT_MUTED if is_spare else Colors.TEXT_PRIMARY,
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

        virality = h.get("virality_score", 0)
        score_color = (
            "#27ae60" if virality >= 7 else "#f39c12" if virality >= 5 else "#e74c3c"
        )
        ctk.CTkLabel(
            title_row,
            text=f"⚡{virality}/10",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=score_color,
        ).pack(side="right")

        hm = h.get("heatmap_score", 0)
        if hm > 0:
            hm_color = "#27ae60" if hm >= 0.7 else "#f39c12" if hm >= 0.4 else "#95a5a6"
            ctk.CTkLabel(
                title_row,
                text=f"📊{hm:.0%}",
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=hm_color,
            ).pack(side="right", padx=(0, 6))

        # Timestamps + description
        start = h.get("start_time", "?").split(",")[0]
        end = h.get("end_time", "?").split(",")[0]
        dur = h.get("duration_seconds", 0)
        desc = h.get("description", "")

        info_text = f"⏱ {start} → {end} ({dur}s)"
        if desc:
            info_text += f"  |  {desc[:60]}"

        ctk.CTkLabel(
            info_frame,
            text=info_text,
            font=ctk.CTkFont(size=10),
            text_color=Colors.TEXT_MUTED,
            anchor="w",
        ).pack(fill="x", pady=(2, 0))

        # Row 2: Action buttons
        btn_row = ctk.CTkFrame(inner, fg_color="transparent")
        btn_row.pack(fill="x", pady=(Spacing.XS, 0))

        # Play preview
        ctk.CTkButton(
            btn_row,
            text="▶ Preview",
            width=90,
            height=28,
            fg_color=Colors.ACCENT_PRIMARY,
            hover_color=Colors.BTN_PRIMARY_HOVER,
            font=ctk.CTkFont(size=11),
            text_color=Colors.TEXT_PRIMARY,
            command=lambda p=clip_path: self._play_clip_preview(p),
        ).pack(side="left", padx=(0, 4))

        if is_spare:
            # Spare clip: promote to primary
            ctk.CTkButton(
                btn_row,
                text="↑ Promosikan",
                width=110,
                height=28,
                fg_color=Colors.BTN_SECONDARY,
                hover_color=Colors.BTN_SECONDARY_HOVER,
                font=ctk.CTkFont(size=11),
                text_color=Colors.TEXT_PRIMARY,
                command=lambda j=idx: self._promote_spare(j),
            ).pack(side="left", padx=(8, 4))
        else:
            # Primary clip: move up
            if idx > 0:
                ctk.CTkButton(
                    btn_row,
                    text="↑",
                    width=28,
                    height=28,
                    fg_color=Colors.BG_SECONDARY,
                    hover_color=Colors.CARD_HOVER,
                    font=ctk.CTkFont(size=14),
                    text_color=Colors.TEXT_PRIMARY,
                    command=lambda i=idx: self._move_clip(i, -1),
                ).pack(side="left", padx=2)

            # Move down
            if idx < len(self.highlights) - 1:
                ctk.CTkButton(
                    btn_row,
                    text="↓",
                    width=28,
                    height=28,
                    fg_color=Colors.BG_SECONDARY,
                    hover_color=Colors.CARD_HOVER,
                    font=ctk.CTkFont(size=14),
                    text_color=Colors.TEXT_PRIMARY,
                    command=lambda i=idx: self._move_clip(i, 1),
                ).pack(side="left", padx=2)

            # Replace with spare
            spare_count = len(self.spare_highlights or [])
            replace_btn = ctk.CTkButton(
                btn_row,
                text="🔄 Ganti",
                width=80,
                height=28,
                fg_color=Colors.BG_SECONDARY,
                hover_color=Colors.BTN_SUCCESS_HOVER,
                font=ctk.CTkFont(size=11),
                text_color=Colors.WARNING,
                command=lambda i=idx: self._replace_clip(i),
            )
            replace_btn.pack(side="left", padx=(8, 4))
            ToolTip(
                replace_btn, f"Ganti clip ini dengan cadangan ({spare_count} tersisa)"
            )

            # Remove clip
            ctk.CTkButton(
                btn_row,
                text="✕",
                width=28,
                height=28,
                fg_color=Colors.BG_SECONDARY,
                hover_color=Colors.ERROR,
                font=ctk.CTkFont(size=12),
                text_color=Colors.ERROR,
                command=lambda i=idx: self._remove_clip(i),
            ).pack(side="right")

    def _load_thumbnail_async(self, clip_path: str, thumb_frame: ctk.CTkFrame):
        """Load thumbnail from clip file in background thread."""

        def _load():
            try:
                from components.video_preview import extract_thumbnail

                img = extract_thumbnail(clip_path, time_offset=0.3, size=(120, 68))
                if img:
                    self._thumbnail_refs.append(img)
                    self.after(0, lambda: self._set_thumbnail(thumb_frame, img))
            except Exception:
                pass

        threading.Thread(target=_load, daemon=True).start()

    def _set_thumbnail(self, thumb_frame: ctk.CTkFrame, img):
        """Set thumbnail image in frame."""
        try:
            for w in thumb_frame.winfo_children():
                w.destroy()
            ctk.CTkLabel(thumb_frame, image=img, text="").place(
                relx=0.5, rely=0.5, anchor="center"
            )
        except Exception:
            pass

    def _play_clip_preview(self, clip_path: str):
        """Open in-app video preview player in the preview panel."""
        if not clip_path or not os.path.exists(clip_path):
            messagebox.showwarning("No Clip", "File clip tidak ditemukan.")
            return

        self._close_preview_player()

        # Clear preview panel
        for w in self.preview_panel.winfo_children():
            w.destroy()

        from components.video_preview import VideoPreviewPlayer

        self._active_player = VideoPreviewPlayer(
            self.preview_panel,
            video_path=clip_path,
            width=350,
            height=540,
            on_close=self._on_player_closed,
            autoplay=True,
        )
        self._active_player.pack(fill="both", expand=True, padx=4, pady=4)

    def _close_preview_player(self):
        """Safely close the active preview player."""
        if self._active_player:
            try:
                self._active_player._destroyed = True
                self._active_player._stop_flag = True
                self._active_player._playing = False
            except Exception:
                pass
            try:
                self._active_player.destroy()
            except Exception:
                pass
            self._active_player = None

    def _on_player_closed(self):
        """Callback when player is closed by user."""
        self._active_player = None
        self._preview_placeholder()

    def _move_clip(self, idx: int, direction: int):
        """Move clip up (-1) or down (+1)."""
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(self.highlights):
            return

        self.highlights[idx], self.highlights[new_idx] = (
            self.highlights[new_idx],
            self.highlights[idx],
        )

        if self._selected_crop_idx == idx:
            self._selected_crop_idx = new_idx
        elif self._selected_crop_idx == new_idx:
            self._selected_crop_idx = idx

        self._sync_manual_crop_cache_from_highlights()
        self._clamp_selected_crop_index()

        # Sync with engine
        if self.engine:
            self.engine.highlights = self.highlights

        self._populate_clips()
        self._set_status(
            f"Clip #{idx + 1} dipindah {'ke atas' if direction < 0 else 'ke bawah'}"
        )

    def _replace_clip(self, idx: int):
        """Replace a clip with the next spare clip."""
        if not self.engine:
            return

        self._processing = True
        self._set_buttons_state(False)
        self._set_status(f"🔄 Mencari pengganti clip #{idx + 1}...", 0.35)

        def _run():
            try:
                replacement = self.engine.find_replacement_clip()

                if replacement:
                    self.highlights[idx] = replacement
                    # New clip starts with neutral manual crop unless it already has one.
                    if not isinstance(self.highlights[idx].get("manual_crop"), dict):
                        self.highlights[idx]["manual_crop"] = {
                            "enabled": True,
                            "base_center_x": 0.5,
                            "keyframes": [],
                        }
                    self._sync_manual_crop_cache_from_highlights()
                    self._clamp_selected_crop_index()
                    self.engine.highlights = self.highlights
                    self.spare_highlights = list(self.engine.spare_highlights or [])

                    self.after(0, self._populate_clips)
                    self.after(
                        0,
                        lambda: self._set_status(
                            f"✓ Clip #{idx + 1} diganti: {replacement.get('title', '?')[:40]}",
                            0.40,
                        ),
                    )
                else:
                    self.after(
                        0,
                        lambda: messagebox.showinfo(
                            "No Spare",
                            "Tidak ada clip cadangan tersisa.\n"
                            "Semua clip sudah digunakan atau AI tidak menemukan yang baru.",
                        ),
                    )
                    self.after(
                        0, lambda: self._set_status("Tidak ada cadangan tersisa")
                    )
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
            finally:
                self._processing = False
                self.after(0, lambda: self._set_buttons_state(True))

        threading.Thread(target=_run, daemon=True).start()

    def _remove_clip(self, idx: int):
        """Remove a clip from the selection."""
        if len(self.highlights) <= 1:
            messagebox.showwarning("Min Clips", "Minimal harus ada 1 clip.")
            return

        removed = self.highlights.pop(idx)
        if self._selected_crop_idx > idx:
            self._selected_crop_idx -= 1
        elif self._selected_crop_idx >= len(self.highlights):
            self._selected_crop_idx = max(0, len(self.highlights) - 1)

        self._sync_manual_crop_cache_from_highlights()
        self._clamp_selected_crop_index()
        if self.engine:
            self.engine.highlights = self.highlights

        self._set_status(f"✕ Clip dihapus: {removed.get('title', '?')[:40]}")
        self._populate_clips()

    def _promote_spare(self, spare_idx: int):
        """Move a spare clip into the primary highlights list."""
        if not self.spare_highlights or spare_idx >= len(self.spare_highlights):
            return

        promoted = self.spare_highlights.pop(spare_idx)
        if not isinstance(promoted.get("manual_crop"), dict):
            promoted["manual_crop"] = {
                "enabled": True,
                "base_center_x": 0.5,
                "keyframes": [],
            }
        self.highlights.append(promoted)

        self._sync_manual_crop_cache_from_highlights()
        self._clamp_selected_crop_index()

        if self.engine:
            self.engine.highlights = self.highlights
            self.engine.spare_highlights = self.spare_highlights

        self._set_status(f"✓ Dipromosikan: {promoted.get('title', '?')[:40]}")
        self._populate_clips()

    # ─── STEP 2 → 3: Assemble + Script ────────────────────────────────

    def _start_step2(self):
        """Assemble selected clips + generate script."""
        if not self.highlights:
            messagebox.showwarning("No Clips", "Tidak ada clips yang dipilih.")
            return

        self._close_preview_player()
        self._processing = True
        self._cancel_flag = False
        self._set_buttons_state(False)
        self.after(0, self._show_progress_panel)

        threading.Thread(target=self._run_step2, daemon=True).start()

    def _run_step2(self):
        """Background: assemble draft from pre-cut clips + generate script."""
        try:
            # Ambil setting transisi + hook dari UI
            transition = (
                self.transition_var.get() if hasattr(self, "transition_var") else "none"
            )
            add_hook = self.hook_var.get() if hasattr(self, "hook_var") else False
            hook_voice = (
                self.voice_var.get()
                if hasattr(self, "voice_var")
                else "id-ID-ArdiNeural"
            )

            # Assemble draft using pre-cut clip files
            self.engine.assemble_draft(
                self.highlights,
                convert_portrait=True,
                transition=transition,
                transition_duration=0.5,
                add_hook=add_hook,
                hook_voice=hook_voice,
            )

            if self._cancel_flag:
                return

            # Generate script
            context = self._get_context_text()
            pattern_id = self.pattern_var.get()

            from clip_dub_engine import PATTERNS

            pattern = PATTERNS.get(pattern_id, {})
            if not context:
                context = pattern.get("description", "Buat ringkasan video ini")

            self.script_data = self.engine.generate_script(
                user_context=context, pattern_id=pattern_id
            )

            if self._cancel_flag:
                return

            # Show script in TTS step
            self.after(0, lambda: self._display_script(self.script_data))
            self.after(0, lambda: self._show_step(3))

        except Exception as e:
            error_msg = str(e)
            self.after(0, lambda: messagebox.showerror("Error", error_msg))
            self.after(0, lambda: self._set_status(f"Error: {error_msg[:80]}", 0))
        finally:
            self._processing = False
            self.after(0, lambda: self._set_buttons_state(True))
            self.after(500, self._hide_progress_panel)

    def _display_script(self, script_data: dict):
        """Called after script generation - stores data and populates TTS segments if visible."""
        self.tts_preview_data = None  # Clear old TTS when script changes
        if self.current_step == 3:
            self._populate_tts_segments()

    # ─── TTS Studio Methods ───────────────────────────────────────────

    def _populate_tts_segments(self):
        """Populate segment cards in TTS Studio from script_data."""
        for w in self.tts_segments_container.winfo_children():
            w.destroy()
        self._tts_segment_widgets = []

        if not self.script_data:
            create_styled_label(
                self.tts_segments_container,
                "Belum ada script. Generate dulu di step sebelumnya.",
                style="caption",
                color=Colors.TEXT_MUTED,
            ).pack(pady=Spacing.MD)
            return

        segments = self.script_data.get("segments", [])
        if not segments:
            create_styled_label(
                self.tts_segments_container,
                "Script kosong. Coba regenerate.",
                style="caption",
                color=Colors.TEXT_MUTED,
            ).pack(pady=Spacing.MD)
            return

        # Info bar
        total_wc = sum(len(s.get("text", "").split()) for s in segments)
        info_text = f"📊 {len(segments)} segments  |  {total_wc} kata"
        if self.tts_preview_data:
            total_tts = sum(t.get("tts_duration", 0) for t in self.tts_preview_data)
            info_text += f"  |  🔊 TTS total: {total_tts:.1f}s"
        self.tts_status_label.configure(text=info_text)

        for i, seg in enumerate(segments):
            card = self._create_tts_segment_card(i, seg)
            card.pack(fill="x", pady=(0, Spacing.SM))
            self._tts_segment_widgets.append(card)

        self._draw_timeline()

    @staticmethod
    def _estimate_tts_duration(text: str) -> float:
        """Estimate TTS duration from text. ~2.5 words/sec for Indonesian Edge TTS."""
        words = text.split()
        if not words:
            return 0.0
        return len(words) * 0.4  # ~0.4s per word average

    def _create_tts_segment_card(self, idx: int, seg: dict) -> ctk.CTkFrame:
        """Create a single segment editor card with live duration estimation."""
        import tkinter as tk

        start = float(seg.get("target_start", 0))
        end = float(seg.get("target_end", start + 5))
        text = seg.get("text", "")
        slot_dur = end - start

        # Check if TTS exists for this segment
        tts_info = None
        if self.tts_preview_data and idx < len(self.tts_preview_data):
            tts_info = self.tts_preview_data[idx]

        has_tts = tts_info is not None and os.path.exists(
            tts_info.get("audio_path", "")
        )

        # Card frame
        border_color = "#27ae60" if has_tts else Colors.BORDER
        card = ctk.CTkFrame(
            self.tts_segments_container,
            fg_color=Colors.BG_SECONDARY,
            corner_radius=BorderRadius.SM,
            border_width=1,
            border_color=border_color,
        )

        # Header row: segment number + timing
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.SM, pady=(Spacing.SM, 4))

        s_mm, s_ss = int(start // 60), int(start % 60)
        e_mm, e_ss = int(end // 60), int(end % 60)

        ctk.CTkLabel(
            header,
            text=f"Segment {idx + 1}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=Colors.ACCENT_PRIMARY,
        ).pack(side="left")

        ctk.CTkLabel(
            header,
            text=f"⏱ {slot_dur:.1f}s",
            font=ctk.CTkFont(size=11),
            text_color=Colors.TEXT_MUTED,
        ).pack(side="left", padx=(Spacing.SM, 0))

        # TTS status badge
        if has_tts:
            tts_dur = tts_info["tts_duration"]
            ratio = tts_dur / slot_dur if slot_dur > 0 else 0
            badge_color = (
                "#27ae60"
                if 0.7 <= ratio <= 1.1
                else "#f39c12"
                if ratio < 0.7
                else "#e74c3c"
            )
            ctk.CTkLabel(
                header,
                text=f"🔊 {tts_dur:.1f}s",
                font=ctk.CTkFont(size=10),
                text_color=badge_color,
            ).pack(side="right")
        else:
            ctk.CTkLabel(
                header,
                text="⏳ No TTS",
                font=ctk.CTkFont(size=10),
                text_color=Colors.TEXT_MUTED,
            ).pack(side="right")

        # Timing inputs row
        timing_row = ctk.CTkFrame(card, fg_color="transparent")
        timing_row.pack(fill="x", padx=Spacing.SM, pady=(0, 4))

        ctk.CTkLabel(
            timing_row,
            text="Start:",
            font=ctk.CTkFont(size=10),
            text_color=Colors.TEXT_MUTED,
        ).pack(side="left")
        start_var = ctk.StringVar(value=f"{s_mm:02d}:{s_ss:02d}")
        start_entry = ctk.CTkEntry(
            timing_row,
            textvariable=start_var,
            width=55,
            height=24,
            fg_color=Colors.CARD_BG,
            border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY,
            font=ctk.CTkFont(size=10),
            justify="center",
        )
        start_entry.pack(side="left", padx=(4, Spacing.SM))

        ctk.CTkLabel(
            timing_row,
            text="End:",
            font=ctk.CTkFont(size=10),
            text_color=Colors.TEXT_MUTED,
        ).pack(side="left")
        end_var = ctk.StringVar(value=f"{e_mm:02d}:{e_ss:02d}")
        end_entry = ctk.CTkEntry(
            timing_row,
            textvariable=end_var,
            width=55,
            height=24,
            fg_color=Colors.CARD_BG,
            border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY,
            font=ctk.CTkFont(size=10),
            justify="center",
        )
        end_entry.pack(side="left", padx=(4, 0))

        # Store refs
        card._start_var = start_var
        card._end_var = end_var
        card._seg_idx = idx
        card._slot_dur = slot_dur

        # Text editor
        text_box = ctk.CTkTextbox(
            card,
            height=60,
            fg_color=Colors.CARD_BG,
            border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY,
            font=Fonts.body_sm(),
            border_width=1,
            corner_radius=4,
        )
        text_box.pack(fill="x", padx=Spacing.SM, pady=(0, 4))
        text_box.insert("1.0", text)
        card._text_box = text_box

        # ── Duration Estimation Bar ──
        est_frame = ctk.CTkFrame(card, fg_color="transparent")
        est_frame.pack(fill="x", padx=Spacing.SM, pady=(0, 4))

        # Progress bar showing estimated fill
        est_bar_bg = tk.Canvas(
            est_frame, height=10, bg=Colors.BG_TERTIARY, highlightthickness=0, bd=0
        )
        est_bar_bg.pack(fill="x", side="top")
        card._est_bar = est_bar_bg

        # Estimation text label
        est_label = ctk.CTkLabel(
            est_frame, text="", font=ctk.CTkFont(size=9), text_color=Colors.TEXT_MUTED
        )
        est_label.pack(anchor="w")
        card._est_label = est_label

        # Set initial estimation
        self._update_segment_estimation(card)

        # Bind text change to update estimation in real-time
        text_box.bind("<KeyRelease>", lambda e, c=card: self._on_segment_text_change(c))

        # Action buttons row
        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=Spacing.SM, pady=(0, Spacing.SM))

        if has_tts:
            play_btn = create_styled_button(
                btn_row,
                "▶ Play",
                command=lambda i=idx: self._play_segment_audio(i),
                style="secondary",
                width=70,
                height=28,
            )
            play_btn.pack(side="left", padx=(0, 4))

        regen_btn = create_styled_button(
            btn_row,
            "🔄 Regen TTS" if has_tts else "🔊 Generate TTS",
            command=lambda i=idx: self._generate_segment_tts(i),
            style="secondary",
            width=120,
            height=28,
        )
        regen_btn.pack(side="left", padx=(0, 4))

        # Word count info
        wc = len(text.split())
        wc_label = ctk.CTkLabel(
            btn_row,
            text=f"{wc} kata",
            font=ctk.CTkFont(size=9),
            text_color=Colors.TEXT_MUTED,
        )
        wc_label.pack(side="right")
        card._wc_label = wc_label

        return card

    def _on_segment_text_change(self, card):
        """Called on each keystroke in a segment textbox. Updates estimation."""
        # Debounce: cancel previous scheduled update
        prev_id = getattr(card, "_est_after_id", None)
        if prev_id:
            try:
                self.after_cancel(prev_id)
            except Exception:
                pass
        card._est_after_id = self.after(
            150, lambda: self._update_segment_estimation(card)
        )

    def _update_segment_estimation(self, card):
        """Update the duration estimation bar and label for a segment card."""
        import tkinter as tk

        text_box = getattr(card, "_text_box", None)
        est_bar = getattr(card, "_est_bar", None)
        est_label = getattr(card, "_est_label", None)
        wc_label = getattr(card, "_wc_label", None)
        slot_dur = getattr(card, "_slot_dur", 10)
        idx = getattr(card, "_seg_idx", 0)

        if not text_box or not est_bar or not est_label:
            return

        try:
            current_text = text_box.get("1.0", "end-1c").strip()
        except Exception:
            return

        wc = len(current_text.split()) if current_text else 0

        # Use actual TTS duration if available, otherwise estimate
        tts_info = None
        if self.tts_preview_data and idx < len(self.tts_preview_data):
            tts_info = self.tts_preview_data[idx]

        has_tts = tts_info is not None and os.path.exists(
            tts_info.get("audio_path", "")
        )

        if has_tts and tts_info.get("text", "").strip() == current_text:
            # Text unchanged from generated TTS — use actual duration
            est_dur = tts_info["tts_duration"]
            source = "actual"
        else:
            # Text changed or no TTS — use estimation
            est_dur = self._estimate_tts_duration(current_text)
            source = "est"

        # Update word count label
        if wc_label:
            try:
                wc_label.configure(text=f"{wc} kata")
            except Exception:
                pass

        # Calculate fill ratio
        ratio = est_dur / slot_dur if slot_dur > 0 else 0
        remaining = max(0, slot_dur - est_dur)

        # Color: green if 70-110%, yellow if under, red if over
        if ratio <= 0.01:
            bar_color = "#555555"
            status_icon = "⬜"
        elif ratio < 0.5:
            bar_color = "#e74c3c"  # Red - too short
            status_icon = "🔴"
        elif ratio < 0.7:
            bar_color = "#f39c12"  # Yellow - getting there
            status_icon = "🟡"
        elif ratio <= 1.1:
            bar_color = "#27ae60"  # Green - good fit
            status_icon = "🟢"
        else:
            bar_color = "#e74c3c"  # Red - too long
            status_icon = "🔴"

        # Draw estimation bar
        try:
            est_bar.delete("all")
            est_bar.update_idletasks()
            w = est_bar.winfo_width()
            if w <= 1:
                w = 300
            h = 10

            # Background slot
            est_bar.create_rectangle(0, 0, w, h, fill=Colors.BG_TERTIARY, outline="")
            # Fill bar
            fill_w = min(ratio, 1.2) / 1.2 * w  # Cap visual at 120%
            est_bar.create_rectangle(0, 0, fill_w, h, fill=bar_color, outline="")
            # Slot boundary marker at 100%
            marker_x = (1.0 / 1.2) * w
            est_bar.create_line(marker_x, 0, marker_x, h, fill="#ffffff", width=1)
        except Exception:
            pass

        # Build estimation text
        if source == "actual":
            est_text = f"{status_icon} TTS: {est_dur:.1f}s / slot: {slot_dur:.1f}s"
        else:
            est_text = f"{status_icon} ~{est_dur:.1f}s / slot: {slot_dur:.1f}s"

        if remaining > 0.5 and ratio < 0.9:
            words_needed = int(remaining / 0.4)  # ~0.4s per word
            est_text += f"  — butuh ~{remaining:.0f}s lagi (~{words_needed} kata)"
        elif ratio > 1.1:
            over = est_dur - slot_dur
            est_text += f"  — kelebihan ~{over:.1f}s"
        elif ratio >= 0.7:
            est_text += "  ✓ pas"

        try:
            est_label.configure(text=est_text)
        except Exception:
            pass

    def _generate_all_tts(self):
        """Generate TTS for all segments in background."""
        if not self.script_data or not self.engine:
            messagebox.showwarning("No Data", "Generate script terlebih dahulu.")
            return

        # Sync text edits from UI first
        self._sync_tts_data_from_ui()

        self._processing = True
        self._set_buttons_state(False)
        self.gen_all_tts_btn.configure(text="⏳ Generating...")

        def _run():
            try:
                voice = self.voice_var.get()
                speed = self.speed_var.get()

                def progress_cb(i, total, msg):
                    self.after(
                        0,
                        lambda: self.tts_status_label.configure(
                            text=f"🔊 Generating {i + 1}/{total}..."
                        ),
                    )

                results = self.engine.generate_tts_previews(
                    self.script_data,
                    voice=voice,
                    speed=speed,
                    progress_callback=progress_cb,
                )

                self.tts_preview_data = results
                self.after(0, self._populate_tts_segments)
                self.after(0, lambda: self._set_status("✅ TTS generated!", 0.65))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("TTS Error", str(e)))
            finally:
                self._processing = False
                self.after(0, lambda: self._set_buttons_state(True))
                self.after(
                    0,
                    lambda: self.gen_all_tts_btn.configure(
                        text="🔊 Generate Semua TTS"
                    ),
                )

        threading.Thread(target=_run, daemon=True).start()

    def _generate_segment_tts(self, idx: int):
        """Generate TTS for a single segment in background."""
        if not self.engine:
            return

        # Get text from the segment's textbox
        self._sync_tts_data_from_ui()
        segments = self.script_data.get("segments", [])
        if idx >= len(segments):
            return

        seg = segments[idx]
        text = seg.get("text", "").strip()
        if not text:
            messagebox.showwarning("Empty", "Segment text kosong.")
            return

        def _run():
            try:
                voice = self.voice_var.get()
                speed = self.speed_var.get()

                result = self.engine.generate_single_tts_preview(
                    text, idx, voice=voice, speed=speed
                )

                # Update tts_preview_data
                if not self.tts_preview_data:
                    self.tts_preview_data = [None] * len(segments)

                # Ensure list is long enough
                while len(self.tts_preview_data) <= idx:
                    self.tts_preview_data.append(None)

                self.tts_preview_data[idx] = {
                    "index": idx,
                    "text": text,
                    "target_start": seg.get("target_start", 0),
                    "target_end": seg.get("target_end", 0),
                    "audio_path": result["audio_path"],
                    "tts_duration": result["tts_duration"],
                    "word_timings": result["word_timings"],
                }

                self.after(0, self._populate_tts_segments)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("TTS Error", str(e)))

        threading.Thread(target=_run, daemon=True).start()

    def _play_segment_audio(self, idx: int):
        """Play TTS audio for a specific segment."""
        if not self.tts_preview_data or idx >= len(self.tts_preview_data):
            return

        tts_info = self.tts_preview_data[idx]
        if not tts_info:
            return

        audio_path = tts_info.get("audio_path", "")
        if not audio_path or not os.path.exists(audio_path):
            messagebox.showwarning("No Audio", "File audio belum di-generate.")
            return

        self._stop_audio()

        # Use Windows MCI for MP3 playback
        try:
            import ctypes

            # Close any previous playback
            ctypes.windll.winmm.mciSendStringW("close tts_preview", None, 0, 0)
            # Open and play
            audio_path_escaped = audio_path.replace("\\", "/")
            ctypes.windll.winmm.mciSendStringW(
                f'open "{audio_path_escaped}" type mpegvideo alias tts_preview',
                None,
                0,
                0,
            )
            ctypes.windll.winmm.mciSendStringW("play tts_preview", None, 0, 0)
        except Exception:
            # Fallback: open with system default
            try:
                os.startfile(audio_path)
            except Exception:
                pass

    def _stop_audio(self):
        """Stop any currently playing audio."""
        try:
            import ctypes

            ctypes.windll.winmm.mciSendStringW("stop tts_preview", None, 0, 0)
            ctypes.windll.winmm.mciSendStringW("close tts_preview", None, 0, 0)
        except Exception:
            pass

    def _sync_tts_data_from_ui(self):
        """Read segment text and timing from UI cards back into script_data."""
        import re

        if not self.script_data or not self._tts_segment_widgets:
            return

        segments = self.script_data.get("segments", [])

        for card in self._tts_segment_widgets:
            idx = getattr(card, "_seg_idx", None)
            if idx is None or idx >= len(segments):
                continue

            # Read text
            text_box = getattr(card, "_text_box", None)
            if text_box:
                try:
                    new_text = text_box.get("1.0", "end-1c").strip()
                    if new_text:
                        segments[idx]["text"] = new_text
                except Exception:
                    pass

            # Read timing
            start_var = getattr(card, "_start_var", None)
            end_var = getattr(card, "_end_var", None)
            if start_var and end_var:
                try:
                    sm = re.match(r"(\d+):(\d+)", start_var.get())
                    em = re.match(r"(\d+):(\d+)", end_var.get())
                    if sm:
                        segments[idx]["target_start"] = int(sm.group(1)) * 60 + int(
                            sm.group(2)
                        )
                    if em:
                        segments[idx]["target_end"] = int(em.group(1)) * 60 + int(
                            em.group(2)
                        )
                except Exception:
                    pass

        # Update full_script and word_count
        self.script_data["full_script"] = " ".join(s["text"] for s in segments)
        self.script_data["word_count"] = len(self.script_data["full_script"].split())

        # Also sync timing changes to tts_preview_data
        if self.tts_preview_data:
            for i, seg in enumerate(segments):
                if i < len(self.tts_preview_data) and self.tts_preview_data[i]:
                    self.tts_preview_data[i]["target_start"] = seg.get(
                        "target_start", 0
                    )
                    self.tts_preview_data[i]["target_end"] = seg.get("target_end", 0)
                    self.tts_preview_data[i]["text"] = seg.get("text", "")

    def _draw_timeline(self):
        """Draw visual timeline on canvas showing segment positions."""
        import tkinter as tk

        canvas = self.timeline_canvas
        canvas.delete("all")

        segments = self.script_data.get("segments", []) if self.script_data else []
        if not segments:
            return

        canvas.update_idletasks()
        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w <= 1:
            w = 600

        # Determine total duration from segments
        total_dur = (
            max(float(s.get("target_end", 0)) for s in segments) if segments else 60
        )
        if total_dur <= 0:
            total_dur = float(self.target_dur_var.get() or 90)

        colors = [
            "#3498db",
            "#2ecc71",
            "#e74c3c",
            "#f39c12",
            "#9b59b6",
            "#1abc9c",
            "#e67e22",
            "#2980b9",
        ]

        bar_top = 4
        bar_bottom = h - 18

        for i, seg in enumerate(segments):
            start = float(seg.get("target_start", 0))
            end = float(seg.get("target_end", start + 5))

            x1 = (start / total_dur) * w
            x2 = (end / total_dur) * w
            color = colors[i % len(colors)]

            # Segment block
            canvas.create_rectangle(
                x1 + 1, bar_top, x2 - 1, bar_bottom, fill=color, outline="#ffffff20"
            )

            # Label
            mid_x = (x1 + x2) / 2
            canvas.create_text(
                mid_x,
                (bar_top + bar_bottom) / 2,
                text=f"{i + 1}",
                fill="white",
                font=("Arial", 9, "bold"),
            )

            # TTS fill indicator (green bar at bottom of segment block)
            if (
                self.tts_preview_data
                and i < len(self.tts_preview_data)
                and self.tts_preview_data[i]
            ):
                tts_dur = self.tts_preview_data[i].get("tts_duration", 0)
                slot_dur = end - start
                if slot_dur > 0 and tts_dur > 0:
                    fill_ratio = min(tts_dur / slot_dur, 1.0)
                    fill_x2 = x1 + (x2 - x1) * fill_ratio
                    canvas.create_rectangle(
                        x1 + 2,
                        bar_bottom - 4,
                        fill_x2 - 2,
                        bar_bottom - 1,
                        fill="#00ff00",
                        outline="",
                    )

        # Time markers
        for frac in [0, 0.25, 0.5, 0.75, 1.0]:
            t = total_dur * frac
            x = max(1, min(frac * w, w - 1))
            mm, ss = int(t // 60), int(t % 60)
            anchor = "w" if frac == 0 else ("e" if frac == 1.0 else "center")
            canvas.create_text(
                x,
                h - 4,
                text=f"{mm}:{ss:02d}",
                fill="#888888",
                font=("Arial", 8),
                anchor=anchor,
            )

    def _update_tts_summary(self):
        """Update the TTS summary label on step 4."""
        if not self.tts_preview_data:
            self.tts_summary_label.configure(
                text="⚠️ TTS belum di-generate. Kembali ke TTS Studio untuk generate."
            )
            return

        valid = [
            t
            for t in self.tts_preview_data
            if t and os.path.exists(t.get("audio_path", ""))
        ]
        total_dur = sum(t.get("tts_duration", 0) for t in valid)
        total_seg = len(self.script_data.get("segments", [])) if self.script_data else 0
        self.tts_summary_label.configure(
            text=f"✅ {len(valid)}/{total_seg} segments TTS ready  |  Total: {total_dur:.1f}s  |  Voice: {self.voice_var.get()}"
        )

    # ─── Script Revision ──────────────────────────────────────────────

    def _revise_script(self):
        """Revise script with AI based on feedback."""
        feedback = self.revision_text.get("1.0", "end-1c").strip()
        if not feedback or feedback.startswith("Contoh:"):
            messagebox.showwarning(
                "No Feedback", "Masukkan feedback revisi terlebih dahulu."
            )
            return

        # Sync current segment edits from UI before revision
        self._sync_tts_data_from_ui()

        self._processing = True
        self._set_buttons_state(False)

        def _run():
            try:
                self.script_data = self.engine.refine_script(feedback)
                self.tts_preview_data = None  # Clear TTS since script changed
                self.after(0, self._populate_tts_segments)
                self.after(
                    0,
                    lambda: self._set_status(
                        f"✓ Script revised: {self.script_data.get('changes_made', 'Updated')}",
                        0.65,
                    ),
                )
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
            finally:
                self._processing = False
                self.after(0, lambda: self._set_buttons_state(True))

        threading.Thread(target=_run, daemon=True).start()

    def _regenerate_script(self):
        """Regenerate script from scratch."""
        if not messagebox.askyesno(
            "Confirm", "Regenerate script dari awal? Script & TTS saat ini akan hilang."
        ):
            return

        self._processing = True
        self._set_buttons_state(False)

        def _run():
            try:
                context = self._get_context_text()
                pattern_id = self.pattern_var.get()
                from clip_dub_engine import PATTERNS

                pattern = PATTERNS.get(pattern_id, {})
                if not context:
                    context = pattern.get("description", "Buat ringkasan video ini")

                self.script_data = self.engine.generate_script(
                    user_context=context, pattern_id=pattern_id
                )

                self.tts_preview_data = None  # Clear TTS since script changed
                self.after(0, self._populate_tts_segments)
                self.after(0, lambda: self._set_status("✓ Script regenerated", 0.60))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
            finally:
                self._processing = False
                self.after(0, lambda: self._set_buttons_state(True))

        threading.Thread(target=_run, daemon=True).start()

    # ─── STEP 4: Render ──────────────────────────────────────────────

    def _start_render(self):
        """Start final render."""
        self._processing = True
        self._cancel_flag = False
        self._set_buttons_state(False)
        self.after(0, self._show_progress_panel)

        # Sync latest segment edits from TTS Studio
        self._sync_tts_data_from_ui()

        threading.Thread(target=self._run_render, daemon=True).start()

    def _run_render(self):
        """Background: TTS + Mix + Render. Uses pre-generated TTS if available."""
        try:
            bgm_url = self.bgm_var.get().strip() or None
            bgm_vol = self.bgm_vol_var.get()

            # Pass pre-generated TTS data if available
            tts_previews = None
            if self.tts_preview_data:
                valid = [
                    t
                    for t in self.tts_preview_data
                    if t and os.path.exists(t.get("audio_path", ""))
                ]
                if valid:
                    tts_previews = valid

            final_path = self.engine.render_final(
                script_data=self.script_data,
                voice=self.voice_var.get(),
                speed=self.speed_var.get(),
                pitch="+0Hz",
                include_subtitle=self.subtitle_var.get(),
                bgm_url=bgm_url,
                bgm_volume=bgm_vol,
                tts_previews=tts_previews,
            )

            self.after(0, lambda: self._on_render_complete(final_path))

        except Exception as e:
            error_msg = str(e)
            self.after(0, lambda: messagebox.showerror("Render Error", error_msg))
            self.after(0, lambda: self._set_status(f"Error: {error_msg[:80]}", 0))
        finally:
            self._processing = False
            self.after(0, lambda: self._set_buttons_state(True))
            self.after(500, self._hide_progress_panel)

    def _on_render_complete(self, final_path: str):
        """Handle render completion."""
        self._set_status(f"✅ Video selesai: {Path(final_path).name}", 1.0)

        result = messagebox.askyesnocancel(
            "Selesai! 🎉",
            f"Video berhasil dibuat!\n\n📁 {final_path}\n\nBuka folder output?",
            icon="info",
        )

        if result is True:
            os.startfile(str(Path(final_path).parent))
        elif result is False:
            # Stay on page
            pass
        else:
            self.app.show_page("landing")

    # ─── Public Methods ───────────────────────────────────────────────

    def refresh_ui(self):
        """Called when page is shown."""
        pass

    def reset(self):
        """Reset the wizard to initial state."""
        self._close_preview_player()
        self.current_step = 0
        self.engine = None
        self._cancel_flag = False
        self._processing = False
        self.download_result = None
        self.highlights = None
        self.spare_highlights = None
        self.script_data = None
        self._thumbnail_refs = []
        self.tts_preview_data = None
        self._tts_segment_widgets = []
        self.manual_crop_data = {}
        self._selected_crop_idx = 0
        self._stop_audio()
        if self._portrait_editor:
            try:
                self._portrait_editor.destroy()
            except Exception:
                pass
            self._portrait_editor = None

        self.url_var.set("")
        # Reset context textbox with placeholder
        self.context_text.delete("1.0", "end")
        self._context_placeholder = True
        self.context_text.insert(
            "1.0",
            "Contoh: Ambil bagian yang membahas tips produktivitas dan motivasi, "
            "fokus pada momen yang emosional dan impactful. "
            "Hindari bagian intro/sponsor/outro.",
        )
        self.context_text.configure(text_color=Colors.TEXT_MUTED)
        # Clear subtitle status banner
        for w in self.subtitle_status_frame.winfo_children():
            w.destroy()
        # Clear TTS segments
        for w in self.tts_segments_container.winfo_children():
            w.destroy()
        for w in self.crop_editor_container.winfo_children():
            w.destroy()
        self.progress_bar.set(0)
        self.status_label.configure(text="Ready")
        self._log_lines = []
        self._current_engine_step = 0
        self._hide_progress_panel()

        self._show_step(0)
