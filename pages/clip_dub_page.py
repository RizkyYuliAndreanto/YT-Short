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
from tkinter import messagebox, filedialog
from pathlib import Path
from typing import Optional, List

from components.ui_theme import (
    Colors, Fonts, Spacing, BorderRadius,
    ToolTip, create_styled_button, create_styled_label
)


class ClipDubPage(ctk.CTkFrame):
    """Combined Clip+Dub wizard page."""
    
    STEPS = [
        ("1", "URL & Konteks"),
        ("2", "Review Clips"),
        ("3", "Edit Script"),
        ("4", "Voice & Render"),
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
        self._thumbnail_refs = []    # Keep CTkImage references to prevent GC
        self._active_player = None   # Currently open VideoPreviewPlayer
        self._log_lines = []         # Recent log messages for progress panel
        self._current_engine_step = 0  # Track which engine step is active
        
        self._build_ui()
    
    def _build_ui(self):
        """Build the full wizard UI."""
        # Header with back button + step indicator
        header = ctk.CTkFrame(self, fg_color=Colors.CARD_BG, height=56)
        header.pack(fill="x")
        header.pack_propagate(False)
        
        header_inner = ctk.CTkFrame(header, fg_color="transparent")
        header_inner.pack(fill="x", padx=Spacing.MD, pady=Spacing.SM)
        
        back_btn = create_styled_button(header_inner, "← Back",
            command=self._go_back, style="ghost", width=70, height=32)
        back_btn.pack(side="left")
        
        create_styled_label(header_inner, "🎬 Clip + Dub Studio",
            style="heading_sm").pack(side="left", padx=Spacing.MD)
        
        # Step indicator (right side)
        self.step_frame = ctk.CTkFrame(header_inner, fg_color="transparent")
        self.step_frame.pack(side="right")
        self._build_step_indicator()
        
        # Main content area (scrollable)
        self.content_area = ctk.CTkFrame(self, fg_color="transparent")
        self.content_area.pack(fill="both", expand=True, padx=Spacing.LG, pady=Spacing.MD)
        
        # Step frames (stacked, show one at a time)
        self.step_frames = {}
        self._build_step1()
        self._build_step2()
        self._build_step3()
        self._build_step4()
        
        # Status bar at bottom
        self.status_bar = ctk.CTkFrame(self, fg_color=Colors.CARD_BG, height=36)
        self.status_bar.pack(fill="x", side="bottom")
        self.status_bar.pack_propagate(False)
        
        self.status_label = create_styled_label(self.status_bar, "Ready", style="caption")
        self.status_label.pack(side="left", padx=Spacing.MD)
        
        self.progress_bar = ctk.CTkProgressBar(self.status_bar, width=200, height=8,
            fg_color=Colors.BG_SECONDARY, progress_color=Colors.ACCENT_PRIMARY)
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
            
            step_lbl = ctk.CTkLabel(self.step_frame, 
                text=f" {num}.{label} ",
                font=ctk.CTkFont(size=11, weight="bold" if i == self.current_step else "normal"),
                text_color=text_color, fg_color=color if i == self.current_step else "transparent",
                corner_radius=10, padx=6, pady=2)
            step_lbl.pack(side="left", padx=2)
            
            if i < len(self.STEPS) - 1:
                ctk.CTkLabel(self.step_frame, text="→", text_color=Colors.BORDER,
                    font=ctk.CTkFont(size=10)).pack(side="left")
    
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
        self.url_entry = ctk.CTkEntry(url_input_row, textvariable=self.url_var,
            height=40, fg_color=Colors.BG_SECONDARY, border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY, font=Fonts.body(),
            placeholder_text="https://youtube.com/watch?v=...")
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(0, Spacing.SM))
        
        paste_btn = create_styled_button(url_input_row, "📋 Paste",
            command=self._paste_url, style="secondary", width=80, height=40)
        paste_btn.pack(side="right")
        
        # Pattern Selection
        pattern_card = self._card(frame, "🎯 Pilih Pattern")
        
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
            
            radio = ctk.CTkRadioButton(row_frame, 
                text=f"{p['icon']} {p['name']}",
                variable=self.pattern_var, value=p["id"],
                font=Fonts.body_sm(), fg_color=Colors.ACCENT_PRIMARY,
                hover_color=Colors.BTN_PRIMARY_HOVER, border_color=Colors.BORDER,
                command=self._on_pattern_change)
            radio.pack(side="left", padx=(0, Spacing.LG), pady=2)
            ToolTip(radio, f"{p['description']}\nContoh: {p['example']}")
        
        # Context input
        context_card = self._card(frame, "✏️ Konteks / Instruksi")
        
        context_frame = ctk.CTkFrame(context_card, fg_color="transparent")
        context_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))
        
        create_styled_label(context_frame, 
            "Jelaskan apa yang ingin dibuat dari video ini:", style="caption").pack(anchor="w")
        
        self.context_text = ctk.CTkTextbox(context_frame, height=100,
            fg_color=Colors.BG_SECONDARY, border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY, font=Fonts.body(), border_width=1,
            corner_radius=BorderRadius.SM)
        self.context_text.pack(fill="x", pady=(4, 0))
        
        # Insert placeholder/example text
        self._context_placeholder = True
        self.context_text.insert("1.0",
            "Contoh: Ambil bagian yang membahas tips produktivitas dan motivasi, "
            "fokus pada momen yang emosional dan impactful. "
            "Hindari bagian intro/sponsor/outro.")
        self.context_text.configure(text_color=Colors.TEXT_MUTED)
        self.context_text.bind("<FocusIn>", self._on_context_focus_in)
        self.context_text.bind("<FocusOut>", self._on_context_focus_out)
        
        # Example hint
        self.context_hint = create_styled_label(context_frame, "", 
            style="caption", color=Colors.TEXT_MUTED)
        self.context_hint.pack(anchor="w", pady=(4, 0))
        self._on_pattern_change()  # Set initial hint
        
        # Settings row
        settings_card = self._card(frame, "⚙️ Settings")
        
        settings_row = ctk.CTkFrame(settings_card, fg_color="transparent")
        settings_row.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.SM))
        
        # Num clips (dropdown: Auto, 3, 5, 7, 10, 15)
        clip_frame = ctk.CTkFrame(settings_row, fg_color="transparent")
        clip_frame.pack(side="left", padx=(0, Spacing.XL))
        create_styled_label(clip_frame, "Jumlah Clip:", style="caption").pack(anchor="w")
        self.num_clips_var = ctk.StringVar(value="Auto")
        ctk.CTkComboBox(clip_frame, values=["Auto", "3", "5", "7", "10", "15"],
            variable=self.num_clips_var, width=80, height=32,
            fg_color=Colors.BG_SECONDARY, border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY, font=Fonts.body_sm(),
            dropdown_fg_color=Colors.CARD_BG).pack(anchor="w", pady=(4, 0))
        
        # Target duration
        dur_frame = ctk.CTkFrame(settings_row, fg_color="transparent")
        dur_frame.pack(side="left", padx=(0, Spacing.XL))
        create_styled_label(dur_frame, "Target Durasi (detik):", style="caption").pack(anchor="w")
        self.target_dur_var = ctk.StringVar(value="90")
        ctk.CTkEntry(dur_frame, textvariable=self.target_dur_var, width=60, height=32,
            fg_color=Colors.BG_SECONDARY, border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY, font=Fonts.body(),
            justify="center").pack(anchor="w", pady=(4, 0))
        
        # Subtitle language
        lang_frame = ctk.CTkFrame(settings_row, fg_color="transparent")
        lang_frame.pack(side="left")
        create_styled_label(lang_frame, "Bahasa Subtitle:", style="caption").pack(anchor="w")
        self.lang_var = ctk.StringVar(value="id")
        ctk.CTkComboBox(lang_frame, values=["id", "en", "auto", "ja", "ko", "es"],
            variable=self.lang_var, width=100, height=32,
            fg_color=Colors.BG_SECONDARY, border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY, font=Fonts.body_sm(),
            dropdown_fg_color=Colors.CARD_BG).pack(anchor="w", pady=(4, 0))
        
        # Row 2: Transisi + Hook
        settings_row2 = ctk.CTkFrame(settings_card, fg_color="transparent")
        settings_row2.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))
        
        # Transition
        trans_frame = ctk.CTkFrame(settings_row2, fg_color="transparent")
        trans_frame.pack(side="left", padx=(0, Spacing.XL))
        create_styled_label(trans_frame, "Transisi:", style="caption").pack(anchor="w")
        self.transition_var = ctk.StringVar(value="fade")
        ctk.CTkComboBox(trans_frame, 
            values=["none", "fade", "dissolve", "wipe_left", "wipe_right", "slide_up"],
            variable=self.transition_var, width=120, height=32,
            fg_color=Colors.BG_SECONDARY, border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY, font=Fonts.body_sm(),
            dropdown_fg_color=Colors.CARD_BG).pack(anchor="w", pady=(4, 0))
        
        # Hook toggle
        hook_frame = ctk.CTkFrame(settings_row2, fg_color="transparent")
        hook_frame.pack(side="left", padx=(0, Spacing.XL))
        self.hook_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(hook_frame, text="🎣 Tambah Hook di awal",
            variable=self.hook_var, font=Fonts.body_sm(),
            fg_color=Colors.ACCENT_PRIMARY, border_color=Colors.BORDER
        ).pack(anchor="w", pady=(16, 0))
        
        # Subtitle status banner (shown after download)
        self.subtitle_status_frame = ctk.CTkFrame(frame, fg_color="transparent")
        self.subtitle_status_frame.pack(fill="x", pady=(0, Spacing.SM))
        # Content is populated dynamically by _show_subtitle_status()
        
        # Action button
        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=Spacing.MD)
        
        self.step1_btn = create_styled_button(btn_frame, 
            "🔍 Download & Find Clips",
            command=self._start_step1, style="primary", width=250, height=44,
            tooltip="Download video dan cari clips yang relevan dengan konteks")
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
        
        create_styled_label(list_header, "🎬 Clips", style="heading_sm").pack(side="left")
        
        self.spare_badge = ctk.CTkLabel(list_header, text="",
            font=ctk.CTkFont(size=10), text_color=Colors.TEXT_MUTED)
        self.spare_badge.pack(side="right")
        
        self.clips_scroll = ctk.CTkScrollableFrame(left_wrapper, fg_color="transparent")
        self.clips_scroll.pack(fill="both", expand=True, pady=(Spacing.SM, 0))
        
        # Right side: preview area (fixed width)
        self.preview_panel = ctk.CTkFrame(self.step2_paned, fg_color=Colors.CARD_BG,
            width=380, corner_radius=BorderRadius.LG, border_width=1, border_color=Colors.BORDER)
        self.preview_panel.pack(side="right", fill="y", padx=(Spacing.SM, 0))
        self.preview_panel.pack_propagate(False)
        
        self._preview_placeholder()
        
        # Bottom buttons
        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(Spacing.MD, 0))
        
        btn_row = ctk.CTkFrame(btn_frame, fg_color="transparent")
        btn_row.pack()
        
        create_styled_button(btn_row, "← URL & Konteks",
            command=lambda: self._show_step(0), style="secondary",
            width=140, height=40).pack(side="left", padx=Spacing.SM)
        
        self.step2_btn = create_styled_button(btn_row,
            "🎬 Assemble & Generate Script →",
            command=self._start_step2, style="primary", width=280, height=40)
        self.step2_btn.pack(side="left", padx=Spacing.SM)
    
    def _preview_placeholder(self):
        """Show placeholder in preview panel."""
        for w in self.preview_panel.winfo_children():
            w.destroy()
        
        placeholder = ctk.CTkFrame(self.preview_panel, fg_color="transparent")
        placeholder.place(relx=0.5, rely=0.5, anchor="center")
        
        ctk.CTkLabel(placeholder, text="🎥", font=ctk.CTkFont(size=40)).pack()
        ctk.CTkLabel(placeholder, text="Klik ▶ pada clip\nuntuk preview",
            font=Fonts.body_sm(), text_color=Colors.TEXT_MUTED,
            justify="center").pack(pady=(Spacing.SM, 0))
    
    # ─── STEP 3: Script Editor ────────────────────────────────────────
    
    def _build_step3(self):
        """Interactive script editor with regeneration."""
        frame = ctk.CTkScrollableFrame(self.content_area, fg_color="transparent")
        self.step_frames[2] = frame
        
        # Script display
        script_card = self._card(frame, "✍️ Script Narasi")
        
        script_inner = ctk.CTkFrame(script_card, fg_color="transparent")
        script_inner.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))
        
        create_styled_label(script_inner, 
            "Edit script di bawah. Kamu bisa langsung edit teks atau minta AI merevisi.",
            style="caption", color=Colors.TEXT_MUTED).pack(anchor="w")
        
        self.script_textbox = ctk.CTkTextbox(script_inner, height=250,
            fg_color=Colors.BG_SECONDARY, border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY, font=Fonts.body(), border_width=1,
            corner_radius=BorderRadius.SM)
        self.script_textbox.pack(fill="x", pady=(Spacing.SM, 0))
        
        # Script info
        self.script_info_label = create_styled_label(script_inner, "", style="caption")
        self.script_info_label.pack(anchor="w", pady=(4, 0))
        
        # Revision section
        revision_card = self._card(frame, "🔄 Revisi dengan AI")
        
        revision_inner = ctk.CTkFrame(revision_card, fg_color="transparent")
        revision_inner.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))
        
        create_styled_label(revision_inner,
            "Jelaskan apa yang perlu diubah:",
            style="caption").pack(anchor="w")
        
        self.revision_text = ctk.CTkTextbox(revision_inner, height=80,
            fg_color=Colors.BG_SECONDARY, border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY, font=Fonts.body_sm(), border_width=1,
            corner_radius=BorderRadius.SM)
        self.revision_text.pack(fill="x", pady=(4, 0))
        self.revision_text.insert("1.0", 
            "Contoh: Hapus info yang tidak relevan, buat transisi lebih smooth...")
        
        revision_btn_row = ctk.CTkFrame(revision_inner, fg_color="transparent")
        revision_btn_row.pack(fill="x", pady=(Spacing.SM, 0))
        
        self.revise_btn = create_styled_button(revision_btn_row,
            "🔄 Revisi Script", command=self._revise_script,
            style="secondary", width=140, height=36)
        self.revise_btn.pack(side="left")
        
        self.regen_btn = create_styled_button(revision_btn_row,
            "🔁 Regenerate Semua", command=self._regenerate_script,
            style="ghost", width=160, height=36,
            tooltip="Generate ulang script dari awal dengan konteks yang sama")
        self.regen_btn.pack(side="left", padx=Spacing.SM)
        
        # Action buttons
        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=Spacing.MD)
        
        btn_row = ctk.CTkFrame(btn_frame, fg_color="transparent")
        btn_row.pack()
        
        create_styled_button(btn_row, "← Back",
            command=lambda: self._show_step(1), style="secondary",
            width=100, height=40).pack(side="left", padx=Spacing.SM)
        
        self.step3_btn = create_styled_button(btn_row,
            "🎤 Approve & Continue →",
            command=lambda: self._show_step(3), style="primary", width=220, height=40)
        self.step3_btn.pack(side="left", padx=Spacing.SM)
    
    # ─── STEP 4: Voice Config + Render ────────────────────────────────
    
    def _build_step4(self):
        """Voice configuration and final render."""
        frame = ctk.CTkScrollableFrame(self.content_area, fg_color="transparent")
        self.step_frames[3] = frame
        
        # Voice settings
        voice_card = self._card(frame, "🎤 Voice Settings")
        
        voice_inner = ctk.CTkFrame(voice_card, fg_color="transparent")
        voice_inner.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))
        
        # Voice selection
        voice_row = ctk.CTkFrame(voice_inner, fg_color="transparent")
        voice_row.pack(fill="x", pady=(0, Spacing.SM))
        
        vf = ctk.CTkFrame(voice_row, fg_color="transparent")
        vf.pack(side="left", padx=(0, Spacing.XL))
        create_styled_label(vf, "Voice:", style="caption").pack(anchor="w")
        self.voice_var = ctk.StringVar(value="id-ID-ArdiNeural")
        ctk.CTkComboBox(vf, values=[
            "id-ID-ArdiNeural", "id-ID-GadisNeural",
            "en-US-GuyNeural", "en-US-JennyNeural"
        ], variable=self.voice_var, width=180, height=32,
            fg_color=Colors.BG_SECONDARY, border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY, font=Fonts.body_sm(),
            dropdown_fg_color=Colors.CARD_BG).pack(anchor="w", pady=(4, 0))
        
        # Speed
        sf = ctk.CTkFrame(voice_row, fg_color="transparent")
        sf.pack(side="left", padx=(0, Spacing.XL))
        create_styled_label(sf, "Speed:", style="caption").pack(anchor="w")
        self.speed_var = ctk.StringVar(value="+0%")
        ctk.CTkComboBox(sf, values=["-20%", "-10%", "+0%", "+10%", "+20%"],
            variable=self.speed_var, width=100, height=32,
            fg_color=Colors.BG_SECONDARY, border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY, font=Fonts.body_sm(),
            dropdown_fg_color=Colors.CARD_BG).pack(anchor="w", pady=(4, 0))
        
        # Subtitle toggle
        self.subtitle_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(voice_inner, text="🔤 Burn subtitle ke video",
            variable=self.subtitle_var, font=Fonts.body_sm(),
            fg_color=Colors.ACCENT_PRIMARY, border_color=Colors.BORDER
        ).pack(anchor="w", pady=(Spacing.SM, 0))
        
        # BGM
        bgm_card = self._card(frame, "🎵 Background Music (Opsional)")
        
        bgm_inner = ctk.CTkFrame(bgm_card, fg_color="transparent")
        bgm_inner.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))
        
        create_styled_label(bgm_inner, "BGM URL (TikTok/YouTube):", style="caption").pack(anchor="w")
        self.bgm_var = ctk.StringVar()
        ctk.CTkEntry(bgm_inner, textvariable=self.bgm_var, height=32,
            fg_color=Colors.BG_SECONDARY, border_color=Colors.BORDER,
            text_color=Colors.TEXT_PRIMARY, font=Fonts.body_sm(),
            placeholder_text="Kosongkan jika tidak ingin BGM").pack(fill="x", pady=(4, 0))
        
        vol_row = ctk.CTkFrame(bgm_inner, fg_color="transparent")
        vol_row.pack(fill="x", pady=(Spacing.SM, 0))
        create_styled_label(vol_row, "Volume BGM:", style="caption").pack(side="left")
        self.bgm_vol_var = ctk.DoubleVar(value=0.15)
        ctk.CTkSlider(vol_row, from_=0, to=0.5, variable=self.bgm_vol_var,
            width=150, fg_color=Colors.BG_SECONDARY,
            progress_color=Colors.ACCENT_PRIMARY, button_color=Colors.ACCENT_PRIMARY
        ).pack(side="left", padx=Spacing.SM)
        self.bgm_vol_label = ctk.CTkLabel(vol_row, text="15%", 
            font=Fonts.body_sm(), text_color=Colors.TEXT_MUTED)
        self.bgm_vol_label.pack(side="left")
        self.bgm_vol_var.trace_add("write", self._update_bgm_label)
        
        # Render button
        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=Spacing.MD)
        
        btn_row = ctk.CTkFrame(btn_frame, fg_color="transparent")
        btn_row.pack()
        
        create_styled_button(btn_row, "← Edit Script",
            command=lambda: self._show_step(2), style="secondary",
            width=120, height=44).pack(side="left", padx=Spacing.SM)
        
        self.render_btn = create_styled_button(btn_row,
            "🚀 Render Final Video",
            command=self._start_render, style="primary", width=220, height=44)
        self.render_btn.pack(side="left", padx=Spacing.SM)
    
    # ─── UI Helpers ───────────────────────────────────────────────────
    
    def _card(self, parent, title: str) -> ctk.CTkFrame:
        """Create a styled card with title."""
        card = ctk.CTkFrame(parent, fg_color=Colors.CARD_BG, 
            corner_radius=BorderRadius.LG, border_width=1, border_color=Colors.BORDER)
        card.pack(fill="x", pady=(0, Spacing.MD))
        
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.MD, pady=(Spacing.MD, Spacing.SM))
        create_styled_label(header, title, style="heading_sm").pack(anchor="w")
        
        return card
    
    def _show_step(self, step_idx: int):
        """Show a specific step, hide others."""
        # Close any open preview player when switching steps
        self._close_preview_player()
        
        self.current_step = step_idx
        
        for idx, f in self.step_frames.items():
            f.pack_forget()
        
        self.step_frames[step_idx].pack(fill="both", expand=True)
        self._build_step_indicator()
        
        # Refresh step 3 script display when navigating to it
        if step_idx == 2 and self.script_data:
            self._display_script(self.script_data)
        
        # Update script data from textbox when going to step 4
        if step_idx == 3 and self.script_data:
            edited_text = self.script_textbox.get("1.0", "end-1c").strip()
            if edited_text != self.script_data.get("full_script", ""):
                self.script_data["full_script"] = edited_text
                # Rebuild segments from full script  
                dur = float(self.target_dur_var.get() or 90)
                self.script_data["segments"] = [
                    {"text": edited_text, "target_start": 0, 
                     "target_end": dur, "tone": "narration"}
                ]
                self.script_data["word_count"] = len(edited_text.split())
    
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
            self.context_text.insert("1.0",
                "Contoh: Ambil bagian yang membahas tips produktivitas dan motivasi, "
                "fokus pada momen yang emosional dan impactful. "
                "Hindari bagian intro/sponsor/outro.")
            self.context_text.configure(text_color=Colors.TEXT_MUTED)
    
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
            banner = ctk.CTkFrame(self.subtitle_status_frame, fg_color="#1a3a1a",
                corner_radius=BorderRadius.SM, border_width=1, border_color="#27ae60")
            banner.pack(fill="x")
            
            inner = ctk.CTkFrame(banner, fg_color="transparent")
            inner.pack(fill="x", padx=Spacing.MD, pady=Spacing.SM)
            
            ctk.CTkLabel(inner, text="✅ Subtitle ditemukan!",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#27ae60").pack(anchor="w")
            
            srt_name = Path(srt_path).name if srt_path else "?"
            ctk.CTkLabel(inner,
                text=f"📄 {srt_name}  •  Bahasa: {lang.upper()}  •  "
                     f"AI akan menggunakan subtitle ini untuk menemukan momen terbaik",
                font=ctk.CTkFont(size=10), text_color=Colors.TEXT_MUTED,
                anchor="w", wraplength=500).pack(anchor="w", pady=(2, 0))
        else:
            banner = ctk.CTkFrame(self.subtitle_status_frame, fg_color="#3a1a1a",
                corner_radius=BorderRadius.SM, border_width=1, border_color="#e74c3c")
            banner.pack(fill="x")
            
            inner = ctk.CTkFrame(banner, fg_color="transparent")
            inner.pack(fill="x", padx=Spacing.MD, pady=Spacing.SM)
            
            ctk.CTkLabel(inner, text="❌ Subtitle tidak ditemukan!",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#e74c3c").pack(anchor="w")
            
            ctk.CTkLabel(inner,
                text=f"Video ini tidak memiliki subtitle bahasa '{lang.upper()}'.\n"
                     f"Fitur Clip+Dub memerlukan subtitle agar AI bisa menemukan momen yang relevan.",
                font=ctk.CTkFont(size=10), text_color=Colors.TEXT_MUTED,
                anchor="w", justify="left", wraplength=500).pack(anchor="w", pady=(2, 0))
            
            # Suggestions
            sug_frame = ctk.CTkFrame(inner, fg_color="transparent")
            sug_frame.pack(fill="x", pady=(Spacing.SM, 0))
            
            ctk.CTkLabel(sug_frame, text="💡 Saran:",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=Colors.WARNING).pack(anchor="w")
            
            suggestions = [
                "• Ganti bahasa subtitle → coba 'en' (English) atau 'auto' (otomatis)",
                "• Gunakan video lain yang memiliki subtitle/CC",
                "• Upload subtitle manual (.srt) ke YouTube lalu coba lagi",
            ]
            for s in suggestions:
                ctk.CTkLabel(sug_frame, text=s,
                    font=ctk.CTkFont(size=10), text_color=Colors.TEXT_SECONDARY,
                    anchor="w").pack(anchor="w", pady=1)
            
            # Quick action buttons
            action_row = ctk.CTkFrame(inner, fg_color="transparent")
            action_row.pack(fill="x", pady=(Spacing.SM, 0))
            
            ctk.CTkButton(action_row, text="🔄 Coba English (en)", width=140, height=28,
                fg_color=Colors.ACCENT_PRIMARY, hover_color=Colors.BTN_PRIMARY_HOVER,
                font=ctk.CTkFont(size=11), text_color=Colors.TEXT_PRIMARY,
                command=lambda: self._retry_with_lang("en")).pack(side="left", padx=(0, 6))
            
            ctk.CTkButton(action_row, text="🔄 Coba Auto", width=110, height=28,
                fg_color=Colors.BG_SECONDARY, hover_color=Colors.CARD_HOVER,
                font=ctk.CTkFont(size=11), text_color=Colors.TEXT_PRIMARY,
                command=lambda: self._retry_with_lang("auto")).pack(side="left", padx=(0, 6))
            
            ctk.CTkButton(action_row, text="📋 Ganti URL", width=100, height=28,
                fg_color=Colors.BG_SECONDARY, hover_color=Colors.CARD_HOVER,
                font=ctk.CTkFont(size=11), text_color=Colors.TEXT_PRIMARY,
                command=lambda: self.url_entry.focus_set()).pack(side="left")
    
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
            if not messagebox.askyesno("Confirm", "Processing sedang berjalan. Yakin ingin cancel?"):
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
        for btn in [self.step1_btn, self.step2_btn, self.step3_btn, 
                     self.render_btn, self.revise_btn, self.regen_btn]:
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
        self.progress_panel = ctk.CTkFrame(self, fg_color=Colors.CARD_BG,
            border_width=1, border_color=Colors.BORDER, corner_radius=0)
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
            lbl = ctk.CTkLabel(step_frame, text=f"{icon} {name}",
                font=ctk.CTkFont(size=11), text_color=Colors.TEXT_MUTED,
                anchor="center")
            lbl.pack()
            
            # Small bar under each step
            bar = ctk.CTkFrame(step_frame, height=3, fg_color=Colors.BORDER,
                corner_radius=1)
            bar.pack(fill="x", padx=4, pady=(2, 0))
            
            self._step_indicators.append({
                "frame": step_frame, "label": lbl, "bar": bar
            })
        
        # Row 2: Current activity + percentage
        activity_row = ctk.CTkFrame(inner, fg_color="transparent")
        activity_row.pack(fill="x", pady=(0, 4))
        
        self.panel_activity_label = ctk.CTkLabel(activity_row,
            text="Menunggu...", font=ctk.CTkFont(size=12),
            text_color=Colors.TEXT_PRIMARY, anchor="w")
        self.panel_activity_label.pack(side="left", fill="x", expand=True)
        
        self.panel_pct_label = ctk.CTkLabel(activity_row,
            text="0%", font=ctk.CTkFont(size=12, weight="bold"),
            text_color=Colors.ACCENT_PRIMARY, width=50, anchor="e")
        self.panel_pct_label.pack(side="right")
        
        # Row 3: Full-width progress bar
        self.panel_progress_bar = ctk.CTkProgressBar(inner, height=6,
            fg_color=Colors.BG_SECONDARY, progress_color=Colors.ACCENT_PRIMARY)
        self.panel_progress_bar.set(0)
        self.panel_progress_bar.pack(fill="x", pady=(0, 4))
        
        # Row 4: Scrollable log area (compact, last N messages)
        log_frame = ctk.CTkFrame(inner, fg_color=Colors.BG_SECONDARY,
            corner_radius=4, height=80)
        log_frame.pack(fill="x")
        log_frame.pack_propagate(False)
        
        self.panel_log_text = ctk.CTkTextbox(log_frame, height=72,
            fg_color=Colors.BG_SECONDARY, text_color=Colors.TEXT_MUTED,
            font=ctk.CTkFont(family="Consolas", size=10),
            activate_scrollbars=True, wrap="word", state="disabled")
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
    
    def _on_step_update(self, step_num: int, total_steps: int,
                        step_name: str, detail: str):
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
                text=f"Step {step_num}/{total_steps}: {step_name} — {detail}" if detail else
                     f"Step {step_num}/{total_steps}: {step_name}")
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
            messagebox.showwarning("No Context", "Masukkan konteks/instruksi untuk Pattern Custom.")
            return
        
        try:
            clips_val = self.num_clips_var.get().strip()
            auto_mode = clips_val.lower() == "auto"
            if not auto_mode:
                num_clips = int(clips_val)
                if not 1 <= num_clips <= 20:
                    raise ValueError()
            else:
                num_clips = 0  # akan ditentukan otomatis
        except ValueError:
            messagebox.showwarning("Invalid", "Jumlah clip harus 'Auto' atau angka 1-20.")
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
            if hasattr(self.config, 'config'):
                engine_config = dict(self.config.config)
            
            # Ensure ai_providers are resolved
            if hasattr(self.config, 'get_resolved_ai_providers'):
                engine_config["ai_providers"] = self.config.get_resolved_ai_providers()
            
            engine_config["subtitle_language"] = self.lang_var.get()
            engine_config["output_dir"] = engine_config.get("output_dir", "output")
            
            self.engine = ClipDubEngine(
                config=engine_config,
                log_callback=lambda msg: (self._set_status(msg), self._add_log_line(msg)),
                progress_callback=lambda s, p: self._set_status(s, p),
                cancel_check=lambda: self._cancel_flag,
                step_callback=lambda sn, st, nm, dt: self._on_step_update(sn, st, nm, dt)
            )
            
            # Step 1a: Download
            self.download_result = self.engine.download_video(self.url_var.get().strip())
            
            if self._cancel_flag:
                return
            
            sub_lang = self.lang_var.get()
            srt_path = self.download_result.get("srt_path")
            has_sub = self.download_result.get("has_subtitle", False)
            
            # Show subtitle status in UI
            self.after(0, lambda: self._show_subtitle_status(
                has_sub, sub_lang, srt_path))
            
            if not has_sub:
                self.after(0, lambda: self._set_status(
                    f"❌ Subtitle '{sub_lang}' tidak ditemukan — lihat saran di atas", 0.15))
                self._processing = False
                self.after(0, lambda: self._set_buttons_state(True))
                return
            
            # Step 1b: Find context-aware clips (with spares)
            self.after(0, lambda: self._set_status(
                f"✅ Subtitle ditemukan ({sub_lang.upper()}) — mencari clips...", 0.25))
            
            context = self._get_context_text()
            pattern_id = self.pattern_var.get()
            
            pattern = PATTERNS.get(pattern_id, {})
            if not context:
                context = pattern.get("description", "Buat ringkasan video ini")
            
            num_clips_val = self.num_clips_var.get().strip()
            auto_mode = num_clips_val.lower() == "auto"
            num_clips = 0 if auto_mode else int(num_clips_val)
            target_dur = int(self.target_dur_var.get() or 90)
            
            self.highlights = self.engine.find_context_clips(
                user_context=context,
                pattern_id=pattern_id,
                num_clips=num_clips if not auto_mode else 10,
                target_duration=target_dur,
                auto_mode=auto_mode
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
            create_styled_label(self.clips_scroll, "No clips found.",
                style="body").pack(pady=Spacing.MD)
            return
        
        spare_count = len(self.spare_highlights or [])
        self.spare_badge.configure(text=f"⚪ {spare_count} cadangan tersedia")
        
        for i, h in enumerate(self.highlights):
            self._create_clip_card(i, h)
    
    def _create_clip_card(self, idx: int, h: dict):
        """Create a single clip card with thumbnail, play, replace, reorder."""
        card = ctk.CTkFrame(self.clips_scroll, fg_color=Colors.CARD_BG,
            corner_radius=BorderRadius.MD, border_width=1, border_color=Colors.BORDER)
        card.pack(fill="x", pady=(0, Spacing.SM))
        
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=Spacing.SM, pady=Spacing.SM)
        
        # Row 1: Thumbnail + Info
        top_row = ctk.CTkFrame(inner, fg_color="transparent")
        top_row.pack(fill="x")
        
        # Thumbnail (left)
        thumb_frame = ctk.CTkFrame(top_row, fg_color="#000000", width=120, height=68,
            corner_radius=4)
        thumb_frame.pack(side="left", padx=(0, Spacing.SM))
        thumb_frame.pack_propagate(False)
        
        clip_path = h.get("clip_path", "")
        if clip_path and os.path.exists(clip_path):
            self._load_thumbnail_async(clip_path, thumb_frame)
        else:
            ctk.CTkLabel(thumb_frame, text="🎬", font=ctk.CTkFont(size=20),
                text_color=Colors.TEXT_MUTED).place(relx=0.5, rely=0.5, anchor="center")
        
        # Info (right of thumbnail)
        info_frame = ctk.CTkFrame(top_row, fg_color="transparent")
        info_frame.pack(side="left", fill="x", expand=True)
        
        title_row = ctk.CTkFrame(info_frame, fg_color="transparent")
        title_row.pack(fill="x")
        
        title = h.get("title", "Untitled")
        ctk.CTkLabel(title_row, text=f"#{idx+1}. {title}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=Colors.TEXT_PRIMARY, anchor="w").pack(side="left", fill="x", expand=True)
        
        virality = h.get("virality_score", 0)
        score_color = "#27ae60" if virality >= 7 else "#f39c12" if virality >= 5 else "#e74c3c"
        ctk.CTkLabel(title_row, text=f"⚡{virality}/10",
            font=ctk.CTkFont(size=10, weight="bold"), text_color=score_color).pack(side="right")
        
        hm = h.get("heatmap_score", 0)
        if hm > 0:
            hm_color = "#27ae60" if hm >= 0.7 else "#f39c12" if hm >= 0.4 else "#95a5a6"
            ctk.CTkLabel(title_row, text=f"📊{hm:.0%}",
                font=ctk.CTkFont(size=10, weight="bold"), text_color=hm_color).pack(side="right", padx=(0, 6))
        
        # Timestamps + description
        start = h.get("start_time", "?").split(",")[0]
        end = h.get("end_time", "?").split(",")[0]
        dur = h.get("duration_seconds", 0)
        desc = h.get("description", "")
        
        info_text = f"⏱ {start} → {end} ({dur}s)"
        if desc:
            info_text += f"  |  {desc[:60]}"
        
        ctk.CTkLabel(info_frame, text=info_text,
            font=ctk.CTkFont(size=10), text_color=Colors.TEXT_MUTED,
            anchor="w").pack(fill="x", pady=(2, 0))
        
        # Row 2: Action buttons
        btn_row = ctk.CTkFrame(inner, fg_color="transparent")
        btn_row.pack(fill="x", pady=(Spacing.XS, 0))
        
        # Play preview
        ctk.CTkButton(btn_row, text="▶ Preview", width=90, height=28,
            fg_color=Colors.ACCENT_PRIMARY, hover_color=Colors.BTN_PRIMARY_HOVER,
            font=ctk.CTkFont(size=11), text_color=Colors.TEXT_PRIMARY,
            command=lambda p=clip_path: self._play_clip_preview(p)).pack(side="left", padx=(0, 4))
        
        # Move up
        if idx > 0:
            ctk.CTkButton(btn_row, text="↑", width=28, height=28,
                fg_color=Colors.BG_SECONDARY, hover_color=Colors.CARD_HOVER,
                font=ctk.CTkFont(size=14), text_color=Colors.TEXT_PRIMARY,
                command=lambda i=idx: self._move_clip(i, -1)).pack(side="left", padx=2)
        
        # Move down
        if idx < len(self.highlights) - 1:
            ctk.CTkButton(btn_row, text="↓", width=28, height=28,
                fg_color=Colors.BG_SECONDARY, hover_color=Colors.CARD_HOVER,
                font=ctk.CTkFont(size=14), text_color=Colors.TEXT_PRIMARY,
                command=lambda i=idx: self._move_clip(i, 1)).pack(side="left", padx=2)
        
        # Replace with spare
        spare_count = len(self.spare_highlights or [])
        replace_btn = ctk.CTkButton(btn_row, text="🔄 Ganti", width=80, height=28,
            fg_color=Colors.BG_SECONDARY, hover_color="#8B4513",
            font=ctk.CTkFont(size=11), text_color=Colors.WARNING,
            command=lambda i=idx: self._replace_clip(i))
        replace_btn.pack(side="left", padx=(8, 4))
        ToolTip(replace_btn, f"Ganti clip ini dengan cadangan ({spare_count} tersisa)")
        
        # Remove clip
        ctk.CTkButton(btn_row, text="✕", width=28, height=28,
            fg_color=Colors.BG_SECONDARY, hover_color=Colors.ERROR,
            font=ctk.CTkFont(size=12), text_color=Colors.ERROR,
            command=lambda i=idx: self._remove_clip(i)).pack(side="right")
    
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
                relx=0.5, rely=0.5, anchor="center")
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
            width=350, height=540,
            on_close=self._on_player_closed,
            autoplay=True
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
        
        self.highlights[idx], self.highlights[new_idx] = \
            self.highlights[new_idx], self.highlights[idx]
        
        # Sync with engine
        if self.engine:
            self.engine.highlights = self.highlights
        
        self._populate_clips()
        self._set_status(f"Clip #{idx+1} dipindah {'ke atas' if direction < 0 else 'ke bawah'}")
    
    def _replace_clip(self, idx: int):
        """Replace a clip with the next spare clip."""
        if not self.engine:
            return
        
        self._processing = True
        self._set_buttons_state(False)
        self._set_status(f"🔄 Mencari pengganti clip #{idx+1}...", 0.35)
        
        def _run():
            try:
                replacement = self.engine.find_replacement_clip()
                
                if replacement:
                    self.highlights[idx] = replacement
                    self.engine.highlights = self.highlights
                    self.spare_highlights = list(self.engine.spare_highlights or [])
                    
                    self.after(0, self._populate_clips)
                    self.after(0, lambda: self._set_status(
                        f"✓ Clip #{idx+1} diganti: {replacement.get('title', '?')[:40]}", 0.40))
                else:
                    self.after(0, lambda: messagebox.showinfo("No Spare",
                        "Tidak ada clip cadangan tersisa.\n"
                        "Semua clip sudah digunakan atau AI tidak menemukan yang baru."))
                    self.after(0, lambda: self._set_status("Tidak ada cadangan tersisa"))
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
        if self.engine:
            self.engine.highlights = self.highlights
        
        self._set_status(f"✕ Clip dihapus: {removed.get('title', '?')[:40]}")
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
            transition = self.transition_var.get() if hasattr(self, 'transition_var') else "none"
            add_hook = self.hook_var.get() if hasattr(self, 'hook_var') else False
            hook_voice = self.voice_var.get() if hasattr(self, 'voice_var') else "id-ID-ArdiNeural"
            
            # Assemble draft using pre-cut clip files
            self.engine.assemble_draft(
                self.highlights, 
                convert_portrait=True,
                transition=transition,
                transition_duration=0.5,
                add_hook=add_hook,
                hook_voice=hook_voice
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
                user_context=context,
                pattern_id=pattern_id
            )
            
            if self._cancel_flag:
                return
            
            # Show script in step 3
            self.after(0, lambda: self._display_script(self.script_data))
            self.after(0, lambda: self._show_step(2))
            
        except Exception as e:
            error_msg = str(e)
            self.after(0, lambda: messagebox.showerror("Error", error_msg))
            self.after(0, lambda: self._set_status(f"Error: {error_msg[:80]}", 0))
        finally:
            self._processing = False
            self.after(0, lambda: self._set_buttons_state(True))
            self.after(500, self._hide_progress_panel)
    
    def _display_script(self, script_data: dict):
        """Display script in the editor."""
        self.script_textbox.delete("1.0", "end")
        self.script_textbox.insert("1.0", script_data.get("full_script", ""))
        
        wc = script_data.get("word_count", 0)
        est_dur = script_data.get("estimated_duration", 0)
        num_seg = len(script_data.get("segments", []))
        self.script_info_label.configure(
            text=f"📊 {wc} kata  |  ~{est_dur:.0f}s  |  {num_seg} segments")
    
    # ─── Script Revision ──────────────────────────────────────────────
    
    def _revise_script(self):
        """Revise script with AI based on feedback."""
        feedback = self.revision_text.get("1.0", "end-1c").strip()
        if not feedback or feedback.startswith("Contoh:"):
            messagebox.showwarning("No Feedback", "Masukkan feedback revisi terlebih dahulu.")
            return
        
        # Update script_data with current text edits before revision
        current_text = self.script_textbox.get("1.0", "end-1c").strip()
        if self.script_data:
            self.script_data["full_script"] = current_text
        
        self._processing = True
        self._set_buttons_state(False)
        
        def _run():
            try:
                self.script_data = self.engine.refine_script(feedback)
                self.after(0, lambda: self._display_script(self.script_data))
                self.after(0, lambda: self._set_status(
                    f"✓ Script revised: {self.script_data.get('changes_made', 'Updated')}", 0.65))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
            finally:
                self._processing = False
                self.after(0, lambda: self._set_buttons_state(True))
        
        threading.Thread(target=_run, daemon=True).start()
    
    def _regenerate_script(self):
        """Regenerate script from scratch."""
        if not messagebox.askyesno("Confirm", "Regenerate script dari awal? Script saat ini akan hilang."):
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
                    user_context=context, pattern_id=pattern_id)
                
                self.after(0, lambda: self._display_script(self.script_data))
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
        
        # Sync latest script text
        if self.script_data:
            edited = self.script_textbox.get("1.0", "end-1c").strip()
            if edited:
                self.script_data["full_script"] = edited
                dur = float(self.target_dur_var.get() or 90)
                self.script_data["segments"] = [
                    {"text": edited, "target_start": 0, 
                     "target_end": dur, "tone": "narration"}
                ]
        
        threading.Thread(target=self._run_render, daemon=True).start()
    
    def _run_render(self):
        """Background: TTS + Mix + Render."""
        try:
            bgm_url = self.bgm_var.get().strip() or None
            bgm_vol = self.bgm_vol_var.get()
            
            final_path = self.engine.render_final(
                script_data=self.script_data,
                voice=self.voice_var.get(),
                speed=self.speed_var.get(),
                pitch="+0Hz",
                include_subtitle=self.subtitle_var.get(),
                bgm_url=bgm_url,
                bgm_volume=bgm_vol
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
        
        result = messagebox.askyesnocancel("Selesai! 🎉",
            f"Video berhasil dibuat!\n\n"
            f"📁 {final_path}\n\n"
            f"Buka folder output?",
            icon="info")
        
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
        
        self.url_var.set("")
        # Reset context textbox with placeholder
        self.context_text.delete("1.0", "end")
        self._context_placeholder = True
        self.context_text.insert("1.0",
            "Contoh: Ambil bagian yang membahas tips produktivitas dan motivasi, "
            "fokus pada momen yang emosional dan impactful. "
            "Hindari bagian intro/sponsor/outro.")
        self.context_text.configure(text_color=Colors.TEXT_MUTED)
        # Clear subtitle status banner
        for w in self.subtitle_status_frame.winfo_children():
            w.destroy()
        self.script_textbox.delete("1.0", "end")
        self.progress_bar.set(0)
        self.status_label.configure(text="Ready")
        self._log_lines = []
        self._current_engine_step = 0
        self._hide_progress_panel()
        
        self._show_step(0)
