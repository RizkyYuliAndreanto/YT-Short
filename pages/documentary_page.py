"""
Documentary Studio Page — Feature 07
Standalone wizard for long-form YouTube documentary videos (16:9).
"""

import copy
import os
import threading
import time
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from components.ui_theme import (
    Colors, Fonts, Spacing, BorderRadius, ToolTip,
    create_styled_button, create_styled_label,
)
from utils.helpers import get_app_dir


class DocumentaryPage(ctk.CTkFrame):
    """Documentary Studio UI."""

    def __init__(self, parent, app, config):
        super().__init__(parent, fg_color=Colors.BG_PRIMARY)
        self.app = app
        self.config = config
        self.engine = None
        self.session_id = ""
        self.processing = False
        self.cancel_flag = False
        self._processing_started_at = 0.0
        self._build_vars()
        self.create_ui()
        self._refresh_stock_status()

    # ------------------------------------------------------------------ setup
    def _build_vars(self):
        doc = (self.config.config.get("documentary", {}) if hasattr(self.config, "config") else {}) or {}
        brief_defaults = {
            "topic": "",
            "target_duration_seconds": str(doc.get("default_duration_seconds", 300)),
            "style": doc.get("style", "documentary"),
            "language": doc.get("language", "id"),
            "source_mode": doc.get("source_mode", "mixed"),
        }
        self.topic_var = ctk.StringVar(value=brief_defaults["topic"])
        self.duration_var = ctk.StringVar(value=brief_defaults["target_duration_seconds"])
        self.style_var = ctk.StringVar(value=brief_defaults["style"])
        self.language_var = ctk.StringVar(value=brief_defaults["language"])
        self.source_mode_var = ctk.StringVar(value=brief_defaults["source_mode"])
        self.resource_mode_var = ctk.StringVar(value=doc.get("resource_mode", "economy"))
        self.session_var = ctk.StringVar(value="")
        stock = doc.get("stock_footage", {}) or {}
        providers = stock.get("providers", {}) or {}
        pexels_cfg = providers.get("pexels", {}) or {}
        pixabay_cfg = providers.get("pixabay", {}) or {}
        self.pexels_enabled_var = ctk.BooleanVar(value=bool(pexels_cfg.get("enabled", True)))
        self.pixabay_enabled_var = ctk.BooleanVar(value=bool(pixabay_cfg.get("enabled", True)))
        self.pexels_base_var = ctk.StringVar(value=pexels_cfg.get("base_url") or "https://api.pexels.com")
        self.pixabay_base_var = ctk.StringVar(value=pixabay_cfg.get("base_url") or "https://pixabay.com/api")
        self.voice_var = ctk.StringVar(value=(doc.get("edge_tts", {}) or {}).get("voice", "id-ID-ArdiNeural"))
        self.subtitle_var = ctk.BooleanVar(value=(doc.get("subtitle", {}) or {}).get("enabled", True))
        self.bgm_var = ctk.BooleanVar(value=(doc.get("bgm", {}) or {}).get("enabled", False))
        self.bgm_source_var = ctk.StringVar(value=(doc.get("bgm", {}) or {}).get("source", ""))

        llm_override = doc.get("llm_override") or {}
        ai = {}
        if hasattr(self.config, "config"):
            ai = (self.config.config.get("ai_providers") or {})
        elif isinstance(self.config, dict):
            ai = (self.config.get("ai_providers") or {})
        sg = ai.get("script_generator") or {}
        hf = ai.get("highlight_finder") or {}
        default_llm_base = llm_override.get("base_url") or sg.get("base_url") or hf.get("base_url") or "http://localhost:20128/v1"

        endpoint_labels = {}
        def add_llm_endpoint(base_url, label):
            base_url = (base_url or "").strip()
            if base_url and base_url not in endpoint_labels:
                endpoint_labels[base_url] = label
        add_llm_endpoint(llm_override.get("base_url"), "saved/override")
        for key in ["documentary_writer", "script_generator", "highlight_finder", "youtube_title_maker"]:
            cfg = ai.get(key) or {}
            if isinstance(cfg, dict):
                add_llm_endpoint(cfg.get("base_url"), key)
        for key, cfg in ai.items():
            if key in {"caption_maker", "hook_maker"} or not isinstance(cfg, dict):
                continue
            add_llm_endpoint(cfg.get("base_url"), key)
        add_llm_endpoint(default_llm_base, "current")

        self._llm_endpoint_labels = endpoint_labels
        self._llm_endpoint_values = list(endpoint_labels.keys()) or [default_llm_base]
        self.llm_endpoint_var = ctk.StringVar(value=llm_override.get("base_url") or default_llm_base)
        self.llm_override_var = ctk.BooleanVar(value=bool(llm_override.get("enabled")))
        self.llm_base_var = ctk.StringVar(value=self.llm_endpoint_var.get())
        self.llm_model_var = ctk.StringVar(value=llm_override.get("model") or sg.get("model") or hf.get("model") or "")
        self.llm_model_choice_var = ctk.StringVar(value="")
        self.llm_status_var = ctk.StringVar(value="Pilih endpoint, lalu Muat Model")
        self._llm_model_ids = []
        self._llm_test_results = []

    def _doc_config(self) -> dict:
        if hasattr(self.config, "config"):
            return copy.deepcopy(self.config.config.get("documentary", {}) or {})
        if isinstance(self.config, dict):
            return copy.deepcopy(self.config.get("documentary", {}) or {})
        return {}

    def _get_engine_config(self) -> dict:
        if hasattr(self.config, "config"):
            engine_config = copy.deepcopy(self.config.config)
            engine_config["ai_providers"] = self.config.get_resolved_ai_providers()
        elif isinstance(self.config, dict):
            engine_config = copy.deepcopy(self.config)
        else:
            engine_config = {}

        doc = engine_config.setdefault("documentary", {})
        doc["source_mode"] = self.source_mode_var.get()
        doc["resource_mode"] = self.resource_mode_var.get()
        doc["language"] = self.language_var.get()
        doc.setdefault("edge_tts", {})["voice"] = self.voice_var.get()
        doc.setdefault("subtitle", {})["enabled"] = self.subtitle_var.get()
        doc.setdefault("bgm", {})["enabled"] = self.bgm_var.get()
        doc["bgm"]["source"] = self.bgm_source_var.get().strip()

        stock = doc.setdefault("stock_footage", {})
        providers = stock.setdefault("providers", {})
        providers.setdefault("pexels", {})["enabled"] = self.pexels_enabled_var.get()
        providers["pexels"]["base_url"] = self.pexels_base_var.get().strip() or "https://api.pexels.com"
        providers.setdefault("pixabay", {})["enabled"] = self.pixabay_enabled_var.get()
        providers["pixabay"]["base_url"] = self.pixabay_base_var.get().strip() or "https://pixabay.com/api"

        existing_llm = doc.get("llm_override") or {}
        doc["llm_override"] = {
            "enabled": self.llm_override_var.get(),
            "base_url": self.llm_base_var.get().strip(),
            "model": (self.llm_model_choice_var.get() or self.llm_model_var.get()).strip(),
            "api_key_env": existing_llm.get("api_key_env") or "",
        }
        return engine_config

    def _new_engine(self, engine_config=None):
        from documentary_engine import DocumentaryEngine
        engine_config = engine_config or getattr(self, "_worker_engine_config", None) or self._get_engine_config()
        output_dir = engine_config.get("output_dir") or str(get_app_dir() / "output")
        self.engine = DocumentaryEngine(
            config=engine_config,
            output_dir=output_dir,
            cookies_path=str(get_app_dir() / "cookies.txt"),
            log_callback=self._log,
            progress_callback=self._set_status,
            step_callback=self._set_step,
            cancel_check=lambda: self.cancel_flag,
        )
        return self.engine

    def _brief_from_ui(self) -> dict:
        try:
            duration = float(self.duration_var.get() or 300)
        except Exception:
            duration = 300.0
        return {
            "topic": self.topic_var.get().strip(),
            "target_duration_seconds": duration,
            "style": self.style_var.get(),
            "language": self.language_var.get(),
            "source_mode": self.source_mode_var.get(),
        }

    def _parse_urls(self):
        raw = self.urls_box.get("1.0", "end-1c")
        urls = []
        for line in raw.replace(",", "\n").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
        return urls

    # ------------------------------------------------------------------ UI
    def create_ui(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.LG, pady=(Spacing.MD, Spacing.SM))

        left = ctk.CTkFrame(header, fg_color="transparent")
        left.pack(side="left")
        back_btn = create_styled_button(left, "←", command=self.go_back, style="ghost", width=40, height=36, tooltip="Kembali ke menu utama")
        back_btn.pack(side="left")
        title_col = ctk.CTkFrame(left, fg_color="transparent")
        title_col.pack(side="left", padx=(Spacing.SM, 0))
        create_styled_label(title_col, "Documentary Studio", style="heading_lg").pack(anchor="w")
        create_styled_label(title_col, "Alur: Konteks → Generate Script → Footage Plan → Preview → Approve → Render", style="muted").pack(anchor="w")

        right = ctk.CTkFrame(header, fg_color="transparent")
        right.pack(side="right")
        create_styled_button(right, "Settings", command=lambda: self.app.show_page("settings"), style="secondary", width=90, height=32, tooltip="Buka pengaturan aplikasi").pack(side="left")

        self.main_scroll = ctk.CTkScrollableFrame(self, fg_color="transparent", scrollbar_button_color=Colors.BORDER, scrollbar_button_hover_color=Colors.ACCENT_PRIMARY)
        self.main_scroll.pack(fill="both", expand=True, padx=Spacing.LG, pady=(0, Spacing.MD))

        self._create_llm_section()
        self._create_brief_section()
        self._create_script_section()
        self._create_sources_section()
        self._create_pipeline_section()
        self._create_review_section()

    def _section_frame(self, title, subtitle, accent=Colors.ACCENT_PRIMARY):
        frame = ctk.CTkFrame(self.main_scroll, fg_color=Colors.CARD_BG, corner_radius=BorderRadius.LG, border_width=1, border_color=Colors.BORDER)
        frame.pack(fill="x", pady=(0, Spacing.MD))
        head = ctk.CTkFrame(frame, fg_color="transparent")
        head.pack(fill="x", padx=Spacing.MD, pady=(Spacing.MD, Spacing.SM))
        icon = ctk.CTkFrame(head, width=34, height=34, fg_color=accent, corner_radius=BorderRadius.SM)
        icon.pack(side="left")
        icon.pack_propagate(False)
        ctk.CTkLabel(icon, text="", font=ctk.CTkFont(size=16)).place(relx=0.5, rely=0.5, anchor="center")
        col = ctk.CTkFrame(head, fg_color="transparent")
        col.pack(side="left", padx=(Spacing.SM, 0))
        create_styled_label(col, title, style="heading_sm").pack(anchor="w")
        if subtitle:
            create_styled_label(col, subtitle, style="muted").pack(anchor="w")
        return frame

    def _create_brief_section(self):
        sec = self._section_frame("1. Konteks Documentary", "Isi topik, durasi target, gaya bahasa, dan suara narasi — lalu generate script", Colors.ACCENT_PRIMARY)
        grid = ctk.CTkFrame(sec, fg_color="transparent")
        grid.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.SM))

        def field(parent, label, var, width=220, tooltip=""):
            col = ctk.CTkFrame(parent, fg_color="transparent")
            col.pack(side="left", padx=(0, Spacing.MD), pady=Spacing.XS)
            create_styled_label(col, label, style="caption").pack(anchor="w")
            entry = ctk.CTkEntry(col, textvariable=var, width=width, fg_color=Colors.BG_SECONDARY, border_color=Colors.BORDER, text_color=Colors.TEXT_PRIMARY, font=Fonts.body(), corner_radius=BorderRadius.SM, height=36)
            entry.pack(anchor="w")
            if tooltip:
                ToolTip(entry, tooltip)
            return entry

        field(grid, "Topik / Brief", self.topic_var, width=420, tooltip="Contoh: Perbandingan kereta cepat Indonesia vs Jepang")
        field(grid, "Target durasi (detik)", self.duration_var, width=110, tooltip="Target YouTube 10-30 menit: isi 600-1800 detik")

        row2 = ctk.CTkFrame(sec, fg_color="transparent")
        row2.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        col = ctk.CTkFrame(row2, fg_color="transparent")
        col.pack(side="left", padx=(0, Spacing.MD))
        create_styled_label(col, "Gaya", style="caption").pack(anchor="w")
        ctk.CTkOptionMenu(col, variable=self.style_var, values=["documentary", "storytelling", "edukatif", "investigatif"], fg_color=Colors.BG_SECONDARY, button_color=Colors.ACCENT_PRIMARY, button_hover_color=Colors.BTN_PRIMARY_HOVER, dropdown_fg_color=Colors.CARD_BG, text_color=Colors.TEXT_PRIMARY, font=Fonts.body(), width=150, height=36).pack(anchor="w")

        col = ctk.CTkFrame(row2, fg_color="transparent")
        col.pack(side="left", padx=(0, Spacing.MD))
        create_styled_label(col, "Bahasa", style="caption").pack(anchor="w")
        ctk.CTkOptionMenu(col, variable=self.language_var, values=["id", "en"], fg_color=Colors.BG_SECONDARY, button_color=Colors.ACCENT_PRIMARY, button_hover_color=Colors.BTN_PRIMARY_HOVER, dropdown_fg_color=Colors.CARD_BG, text_color=Colors.TEXT_PRIMARY, font=Fonts.body(), width=90, height=36).pack(anchor="w")

        col = ctk.CTkFrame(row2, fg_color="transparent")
        col.pack(side="left", padx=(0, Spacing.MD))
        create_styled_label(col, "Mode Sumber", style="caption").pack(anchor="w")
        ctk.CTkOptionMenu(col, variable=self.source_mode_var, values=["mixed", "manual_urls", "stock_footage"], fg_color=Colors.BG_SECONDARY, button_color=Colors.ACCENT_PRIMARY, button_hover_color=Colors.BTN_PRIMARY_HOVER, dropdown_fg_color=Colors.CARD_BG, text_color=Colors.TEXT_PRIMARY, font=Fonts.body(), width=150, height=36).pack(anchor="w")

        col = ctk.CTkFrame(row2, fg_color="transparent")
        col.pack(side="left", padx=(0, Spacing.MD))
        create_styled_label(col, "Resource", style="caption").pack(anchor="w")
        ctk.CTkOptionMenu(col, variable=self.resource_mode_var, values=["economy", "balanced", "quality"], fg_color=Colors.BG_SECONDARY, button_color=Colors.ACCENT_PRIMARY, button_hover_color=Colors.BTN_PRIMARY_HOVER, dropdown_fg_color=Colors.CARD_BG, text_color=Colors.TEXT_PRIMARY, font=Fonts.body(), width=120, height=36).pack(anchor="w")

        col = ctk.CTkFrame(row2, fg_color="transparent")
        col.pack(side="left")
        create_styled_label(col, "Voice TTS", style="caption").pack(anchor="w")
        ctk.CTkOptionMenu(col, variable=self.voice_var, values=["id-ID-ArdiNeural", "id-ID-GadisNeural"], fg_color=Colors.BG_SECONDARY, button_color=Colors.ACCENT_PRIMARY, button_hover_color=Colors.BTN_PRIMARY_HOVER, dropdown_fg_color=Colors.CARD_BG, text_color=Colors.TEXT_PRIMARY, font=Fonts.body(), width=170, height=36).pack(anchor="w")

        action = ctk.CTkFrame(sec, fg_color="transparent")
        action.pack(fill="x", padx=Spacing.MD, pady=(Spacing.XS, Spacing.MD))
        self.generate_script_btn = create_styled_button(action, "Generate Script", command=self.generate_script, style="primary", width=170, height=38, tooltip="Buat script plan per segmen dari topik+durasi, tanpa mencari footage dulu")
        self.generate_script_btn.pack(side="left")
        create_styled_label(action, "Setelah script jadi, edit narasi di Script Editor, lalu lanjut ke Footage Plan.", style="caption", color=Colors.TEXT_MUTED).pack(side="left", padx=Spacing.SM)

    def _create_sources_section(self):
        sec = self._section_frame("3. Footage & Source Search", "Build footage plan per slot, preview thumbnail kandidat, lalu pilih yang dipakai", Colors.INFO)

        url_frame = ctk.CTkFrame(sec, fg_color="transparent")
        url_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.SM))
        create_styled_label(url_frame, "URL Video (satu per baris)", style="caption").pack(anchor="w")
        self.urls_box = ctk.CTkTextbox(url_frame, height=90, fg_color=Colors.BG_SECONDARY, border_color=Colors.BORDER, text_color=Colors.TEXT_PRIMARY, font=Fonts.body(), corner_radius=BorderRadius.SM)
        self.urls_box.pack(fill="x", pady=(Spacing.XS, 0))
        self.urls_box.insert("1.0", "")
        ToolTip(self.urls_box, "Mode stock footage memakai API Pexels/Pixabay. URL manual hanya dipakai jika mode manual_urls atau mixed dipilih.")

        discover_row = ctk.CTkFrame(sec, fg_color="transparent")
        discover_row.pack(fill="x", padx=Spacing.MD, pady=(Spacing.XS, 0))
        self.discover_btn = create_styled_button(discover_row, "Cari Stock dengan AI", command=self.discover_sources, style="secondary", width=160, height=34, tooltip="LLM membuat query visual lalu mencari footage melalui API Pexels/Pixabay")
        self.discover_btn.pack(side="left")
        create_styled_label(discover_row, "Hasil mengisi daftar URL; review/edit sebelum Prepare Sources.", style="caption", color=Colors.TEXT_MUTED).pack(side="left", padx=Spacing.SM)

        stock = ctk.CTkFrame(sec, fg_color=Colors.BG_TERTIARY, corner_radius=BorderRadius.MD)
        stock.pack(fill="x", padx=Spacing.MD, pady=(Spacing.XS, Spacing.SM))
        create_styled_label(stock, "Stock Footage Providers", style="caption").pack(anchor="w", padx=Spacing.SM, pady=(Spacing.SM, 0))

        row = ctk.CTkFrame(stock, fg_color="transparent")
        row.pack(fill="x", padx=Spacing.SM, pady=Spacing.SM)

        pex = ctk.CTkFrame(row, fg_color="transparent")
        pex.pack(side="left", fill="x", expand=True, padx=(0, Spacing.SM))
        ctk.CTkCheckBox(pex, text="Pexels", variable=self.pexels_enabled_var, fg_color=Colors.ACCENT_PRIMARY, hover_color=Colors.BTN_PRIMARY_HOVER, text_color=Colors.TEXT_PRIMARY, font=Fonts.body()).pack(anchor="w")
        self.pexels_base_entry = ctk.CTkEntry(pex, textvariable=self.pexels_base_var, fg_color=Colors.BG_SECONDARY, border_color=Colors.BORDER, text_color=Colors.TEXT_PRIMARY, font=Fonts.body_sm(), corner_radius=BorderRadius.SM, height=30)
        self.pexels_base_entry.pack(fill="x", pady=(Spacing.XS, 0))
        self.pexels_status = create_styled_label(pex, "status: ...", style="caption")
        self.pexels_status.pack(anchor="w")

        pix = ctk.CTkFrame(row, fg_color="transparent")
        pix.pack(side="left", fill="x", expand=True)
        ctk.CTkCheckBox(pix, text="Pixabay", variable=self.pixabay_enabled_var, fg_color=Colors.ACCENT_PRIMARY, hover_color=Colors.BTN_PRIMARY_HOVER, text_color=Colors.TEXT_PRIMARY, font=Fonts.body()).pack(anchor="w")
        self.pixabay_base_entry = ctk.CTkEntry(pix, textvariable=self.pixabay_base_var, fg_color=Colors.BG_SECONDARY, border_color=Colors.BORDER, text_color=Colors.TEXT_PRIMARY, font=Fonts.body_sm(), corner_radius=BorderRadius.SM, height=30)
        self.pixabay_base_entry.pack(fill="x", pady=(Spacing.XS, 0))
        self.pixabay_status = create_styled_label(pix, "status: ...", style="caption")
        self.pixabay_status.pack(anchor="w")

        note = ctk.CTkFrame(sec, fg_color="transparent")
        note.pack(fill="x", padx=Spacing.MD, pady=(Spacing.XS, 0))
        create_styled_label(note, "API key dibaca dari env: PEXELS_API_KEY dan PIXABAY_API_KEY. Base URL default endpoint resmi; ubah hanya untuk proxy/mirror.", style="caption", color=Colors.TEXT_MUTED).pack(anchor="w")

        plan_row = ctk.CTkFrame(sec, fg_color="transparent")
        plan_row.pack(fill="x", padx=Spacing.MD, pady=(Spacing.SM, Spacing.XS))
        self.build_footage_btn = create_styled_button(plan_row, "Build Footage Plan", command=self.build_footage, style="primary", width=160, height=34, tooltip="Cari kandidat footage untuk setiap slot di script plan")
        self.build_footage_btn.pack(side="left", padx=(0, Spacing.XS))
        self.preview_refresh_btn = create_styled_button(plan_row, "Refresh Preview", command=self.refresh_footage_preview, style="secondary", width=120, height=34, tooltip="Muat ulang preview thumbnail kandidat footage")
        self.preview_refresh_btn.pack(side="left", padx=Spacing.XS)
        create_styled_label(plan_row, "Urutan: pilih 1 kandidat/slot → Setujui Pilihan → Render Final.", style="caption", color=Colors.TEXT_MUTED).pack(side="left", padx=Spacing.SM)

        create_styled_label(sec, "Footage Preview", style="caption").pack(anchor="w", padx=Spacing.MD, pady=(Spacing.XS, 0))
        self.footage_preview_scroll = ctk.CTkScrollableFrame(sec, fg_color=Colors.BG_TERTIARY, corner_radius=BorderRadius.MD, height=320, scrollbar_button_color=Colors.BORDER, scrollbar_button_hover_color=Colors.ACCENT_PRIMARY)
        self.footage_preview_scroll.pack(fill="both", expand=True, padx=Spacing.MD, pady=(Spacing.XS, Spacing.MD))
        self.footage_preview_widgets = []
        create_styled_label(self.footage_preview_scroll, "Belum ada footage plan. Generate Script dulu, lalu Build Footage Plan.", style="muted").pack(anchor="w", padx=Spacing.SM, pady=Spacing.SM)

    def _create_llm_section(self):
        sec = self._section_frame("0. AI / LLM Provider", "Setup endpoint/model dulu; Generate Script memakai provider ini", Colors.ACCENT_PRIMARY)

        row = ctk.CTkFrame(sec, fg_color="transparent")
        row.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.SM))
        ctk.CTkCheckBox(row, text="Override LLM", variable=self.llm_override_var, fg_color=Colors.ACCENT_PRIMARY, hover_color=Colors.BTN_PRIMARY_HOVER, text_color=Colors.TEXT_PRIMARY, font=Fonts.body()).pack(side="left", padx=(0, Spacing.MD))

        col = ctk.CTkFrame(row, fg_color="transparent")
        col.pack(side="left", padx=(0, Spacing.SM))
        create_styled_label(col, "Endpoint", style="caption").pack(anchor="w")
        self.llm_endpoint_menu = ctk.CTkOptionMenu(col, variable=self.llm_endpoint_var, values=self._llm_endpoint_values, command=self._on_llm_endpoint_selected, fg_color=Colors.BG_SECONDARY, button_color=Colors.ACCENT_PRIMARY, button_hover_color=Colors.BTN_PRIMARY_HOVER, dropdown_fg_color=Colors.CARD_BG, text_color=Colors.TEXT_PRIMARY, font=Fonts.body(), width=330, height=34)
        self.llm_endpoint_menu.pack(anchor="w")

        col = ctk.CTkFrame(row, fg_color="transparent")
        col.pack(side="left", padx=(0, Spacing.SM))
        create_styled_label(col, "Model", style="caption").pack(anchor="w")
        ctk.CTkEntry(col, textvariable=self.llm_model_var, width=230, fg_color=Colors.BG_SECONDARY, border_color=Colors.BORDER, text_color=Colors.TEXT_PRIMARY, font=Fonts.body(), corner_radius=BorderRadius.SM, height=34).pack(anchor="w")

        col = ctk.CTkFrame(row, fg_color="transparent")
        col.pack(side="left")
        create_styled_label(col, "Model terpilih", style="caption").pack(anchor="w")
        self.llm_model_menu = ctk.CTkOptionMenu(col, variable=self.llm_model_choice_var, values=["-"], command=self._on_llm_model_selected, fg_color=Colors.BG_SECONDARY, button_color=Colors.ACCENT_PRIMARY, button_hover_color=Colors.BTN_PRIMARY_HOVER, dropdown_fg_color=Colors.CARD_BG, text_color=Colors.TEXT_PRIMARY, font=Fonts.body(), width=230, height=34)
        self.llm_model_menu.pack(anchor="w")

        btn_row = ctk.CTkFrame(sec, fg_color="transparent")
        btn_row.pack(fill="x", padx=Spacing.MD, pady=(Spacing.XS, 0))
        create_styled_button(btn_row, "Muat Model", command=self.fetch_llm_models, style="primary", width=120, height=34, tooltip="Ambil daftar model dari endpoint terpilih").pack(side="left", padx=(0, Spacing.XS))
        create_styled_button(btn_row, "Test Pilihan", command=lambda: self.test_llm_models(False), style="secondary", width=110, height=34, tooltip="Test model yang dipilih di dropdown").pack(side="left", padx=Spacing.XS)
        create_styled_button(btn_row, "Test Semua", command=lambda: self.test_llm_models(True), style="secondary", width=100, height=34, tooltip="Test model yang sudah diambil (maks 12), bisa lama untuk provider gratis").pack(side="left", padx=Spacing.XS)
        create_styled_button(btn_row, "Pakai Model Ini", command=self.save_llm_override, style="success", width=130, height=34, tooltip="Simpan endpoint+model pilihan untuk Documentary Studio").pack(side="left", padx=Spacing.XS)
        create_styled_button(btn_row, "Reset", command=self.reset_llm_override, style="ghost", width=80, height=34, tooltip="Matikan override LLM Documentary Studio").pack(side="left", padx=Spacing.XS)
        ctk.CTkLabel(btn_row, textvariable=self.llm_status_var, font=Fonts.caption(), text_color=Colors.TEXT_MUTED).pack(side="left", padx=Spacing.MD)

        self.llm_models_box = ctk.CTkTextbox(sec, height=120, fg_color=Colors.BG_SECONDARY, border_color=Colors.BORDER, text_color=Colors.TEXT_PRIMARY, font=Fonts.body_sm(), corner_radius=BorderRadius.SM)
        self.llm_models_box.pack(fill="x", padx=Spacing.MD, pady=(Spacing.SM, Spacing.MD))
        self.llm_models_box.insert("1.0", "Pilih endpoint, klik 'Muat Model', lalu pilih model dari dropdown.")
        self.llm_models_box.configure(state="disabled")

    def _create_pipeline_section(self):
        sec = self._section_frame("4. Approve & Render", "Preview footage → approve asset → render per segmen → concat final", Colors.ACCENT_SECONDARY)
        wrap = ctk.CTkFrame(sec, fg_color="transparent")
        wrap.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.SM))

        self.prepare_btn = create_styled_button(wrap, "1. Analisis URL", command=self.prepare_sources, style="secondary", width=140, height=36, tooltip="Cek metadata URL sumber tanpa download")
        self.prepare_btn.pack(side="left", padx=(0, Spacing.XS))
        self.download_btn = create_styled_button(wrap, "2. Download + Transcribe", command=self.download_transcribe, style="secondary", width=190, height=36, tooltip="Download video sumber lalu transcribe untuk konteks AI")
        self.download_btn.pack(side="left", padx=Spacing.XS)
        self.plan_btn = create_styled_button(wrap, "3. Build Footage Plan", command=self.build_footage, style="secondary", width=170, height=36, tooltip="Cari kandidat footage untuk setiap slot di script plan")
        self.plan_btn.pack(side="left", padx=Spacing.XS)
        self.approve_btn = create_styled_button(wrap, "3b. Setujui Pilihan", command=self.approve_footage, style="secondary", width=150, height=36, tooltip="Setujui setelah satu kandidat dipilih di setiap slot")
        self.approve_btn.pack(side="left", padx=Spacing.XS)
        self.render_btn = create_styled_button(wrap, "4. Render Video Final", command=self.render_final, style="primary", width=160, height=36, tooltip="Render voiceover, subtitle, footage, dan video final")
        self.render_btn.pack(side="left", padx=Spacing.XS)
        self.run_all_btn = create_styled_button(wrap, "Jalankan Semua", command=self.run_full, style="success", width=140, height=36, tooltip="Jalankan semua tahap otomatis dari sumber sampai final.mp4")
        self.run_all_btn.pack(side="left", padx=Spacing.XS)

        row2 = ctk.CTkFrame(sec, fg_color="transparent")
        row2.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.SM))
        create_styled_label(row2, "Session ID (opsional untuk resume):", style="caption").pack(side="left")
        ctk.CTkEntry(row2, textvariable=self.session_var, width=260, fg_color=Colors.BG_SECONDARY, border_color=Colors.BORDER, text_color=Colors.TEXT_PRIMARY, font=Fonts.body(), corner_radius=BorderRadius.SM, height=32).pack(side="left", padx=(Spacing.SM, Spacing.XS))
        create_styled_button(row2, "Load", command=self.load_session, style="ghost", width=70, height=32, tooltip="Muat session sebelumnya").pack(side="left", padx=Spacing.XS)
        create_styled_button(row2, "Open Output", command=self.open_output, style="ghost", width=110, height=32, tooltip="Buka folder session/output").pack(side="left", padx=Spacing.XS)

        opt = ctk.CTkFrame(sec, fg_color="transparent")
        opt.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))
        ctk.CTkCheckBox(opt, text="Subtitle", variable=self.subtitle_var, fg_color=Colors.ACCENT_PRIMARY, hover_color=Colors.BTN_PRIMARY_HOVER, text_color=Colors.TEXT_PRIMARY, font=Fonts.body()).pack(side="left", padx=(0, Spacing.MD))
        ctk.CTkCheckBox(opt, text="BGM", variable=self.bgm_var, fg_color=Colors.ACCENT_PRIMARY, hover_color=Colors.BTN_PRIMARY_HOVER, text_color=Colors.TEXT_PRIMARY, font=Fonts.body()).pack(side="left", padx=(0, Spacing.MD))
        ctk.CTkEntry(opt, textvariable=self.bgm_source_var, width=360, fg_color=Colors.BG_SECONDARY, border_color=Colors.BORDER, text_color=Colors.TEXT_PRIMARY, font=Fonts.body(), corner_radius=BorderRadius.SM, height=32, placeholder_text="BGM file path atau URL (opsional)").pack(side="left", fill="x", expand=True)

        self.progress = ctk.CTkProgressBar(sec, fg_color=Colors.BG_TERTIARY, progress_color=Colors.ACCENT_PRIMARY, height=10, corner_radius=BorderRadius.SM)
        self.progress.pack(fill="x", padx=Spacing.MD, pady=(Spacing.SM, Spacing.XS))
        self.progress.set(0)

        status_row = ctk.CTkFrame(sec, fg_color="transparent")
        status_row.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.SM))
        self.status_label = create_styled_label(status_row, "Siap", style="body")
        self.status_label.pack(side="left")
        self.step_label = create_styled_label(status_row, "", style="caption", color=Colors.TEXT_MUTED)
        self.step_label.pack(side="right")
        self.cancel_btn = create_styled_button(status_row, "Cancel", command=self.cancel, style="danger", width=80, height=30)
        self.cancel_btn.pack(side="right", padx=(Spacing.SM, 0))

    def _create_script_section(self):
        sec = self._section_frame("2. Script Editor", "Edit judul dan narasi per segmen sebelum Footage Plan / Render", Colors.ACCENT_PRIMARY)
        bar = ctk.CTkFrame(sec, fg_color="transparent")
        bar.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.SM))
        self.script_refresh_btn = create_styled_button(bar, "Muat Script", command=self.refresh_script_editor, style="secondary", width=110, height=32, tooltip="Muat script plan dari engine/session")
        self.script_refresh_btn.pack(side="left", padx=(0, Spacing.XS))
        self.script_save_btn = create_styled_button(bar, "Simpan Script", command=self.save_script, style="success", width=120, height=32, tooltip="Simpan edit narasi ke script_plan/session")
        self.script_save_btn.pack(side="left", padx=Spacing.XS)
        self.script_rebuild_btn = create_styled_button(bar, "Rebuild Footage Plan", command=self.rebuild_footage_plan, style="secondary", width=160, height=32, tooltip="Simpan edit lalu cari ulang footage per slot")
        self.script_rebuild_btn.pack(side="left", padx=Spacing.XS)
        self.script_status_var = ctk.StringVar(value="Belum ada script plan")
        ctk.CTkLabel(bar, textvariable=self.script_status_var, font=Fonts.caption(), text_color=Colors.TEXT_MUTED).pack(side="left", padx=Spacing.MD)

        self.script_scroll = ctk.CTkScrollableFrame(sec, fg_color=Colors.BG_TERTIARY, corner_radius=BorderRadius.MD, height=320, scrollbar_button_color=Colors.BORDER, scrollbar_button_hover_color=Colors.ACCENT_PRIMARY)
        self.script_scroll.pack(fill="both", expand=True, padx=Spacing.MD, pady=(0, Spacing.MD))
        self.script_widgets = []
        create_styled_label(self.script_scroll, "Belum ada script plan. Jalankan '3. Script + Footage Plan' atau Load session.", style="muted").pack(anchor="w", padx=Spacing.SM, pady=Spacing.SM)

    def _render_script_editor(self):
        try:
            for child in self.script_scroll.winfo_children():
                child.destroy()
        except Exception:
            pass
        self.script_widgets = []
        segments = []
        if self.engine:
            segments = self.engine.segments or ((self.engine.session_data.get("script_plan") or {}).get("segments") or []) or []
        if not segments:
            create_styled_label(self.script_scroll, "Belum ada script plan. Jalankan '3. Script + Footage Plan' atau Load session.", style="muted").pack(anchor="w", padx=Spacing.SM, pady=Spacing.SM)
            self.script_status_var.set("Belum ada script plan")
            return
        script_plan = self.engine.session_data.get("script_plan", {}) if self.engine else {}
        source = script_plan.get("script_source") or "unknown"
        self.script_status_var.set(f"{len(segments)} segmen — sumber: {source} — edit lalu Simpan Script")
        for idx, seg in enumerate(segments, start=1):
            card = ctk.CTkFrame(self.script_scroll, fg_color=Colors.BG_SECONDARY, corner_radius=BorderRadius.SM, border_width=1, border_color=Colors.BORDER)
            card.pack(fill="x", pady=(0, Spacing.SM))
            head = ctk.CTkFrame(card, fg_color="transparent")
            head.pack(fill="x", padx=Spacing.SM, pady=(Spacing.SM, 0))
            title_txt = f"{seg.get('segment_id') or idx}. {seg.get('title') or 'Segmen'}"
            create_styled_label(head, title_txt, style="caption").pack(side="left")
            meta = f"durasi tayang {float(seg.get('target_duration') or 0):.0f}s • {len(seg.get('footage_slots') or [])} slot"
            create_styled_label(head, meta, style="caption", color=Colors.TEXT_MUTED).pack(side="right")

            body = ctk.CTkFrame(card, fg_color="transparent")
            body.pack(fill="x", padx=Spacing.SM, pady=Spacing.SM)
            create_styled_label(body, "Judul segmen", style="caption").pack(anchor="w")
            title_entry = ctk.CTkEntry(body, fg_color=Colors.BG_TERTIARY, border_color=Colors.BORDER, text_color=Colors.TEXT_PRIMARY, font=Fonts.body(), corner_radius=BorderRadius.SM, height=30)
            title_entry.insert("0", seg.get("title") or "")
            title_entry.pack(fill="x", pady=(Spacing.XS, Spacing.SM))

            create_styled_label(body, "Narasi / script untuk TTS", style="caption").pack(anchor="w")
            box = ctk.CTkTextbox(body, height=96, fg_color=Colors.BG_TERTIARY, border_color=Colors.BORDER, text_color=Colors.TEXT_PRIMARY, font=Fonts.body_sm(), corner_radius=BorderRadius.SM)
            box.insert("1.0", seg.get("narration_text") or "")
            box.pack(fill="x", pady=(Spacing.XS, 0))
            self.script_widgets.append({
                "segment_id": seg.get("segment_id"),
                "order": seg.get("order") or idx,
                "title_entry": title_entry,
                "narration_box": box,
            })

    def _create_review_section(self):
        sec = self._section_frame("5. Review & Log", "Ringkasan sources, outline, segmen, dan log proses", Colors.SUCCESS)
        cols = ctk.CTkFrame(sec, fg_color="transparent")
        cols.pack(fill="both", expand=True, padx=Spacing.MD, pady=(0, Spacing.MD))

        left = ctk.CTkFrame(cols, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=(0, Spacing.SM))
        create_styled_label(left, "Review", style="caption").pack(anchor="w")
        self.review_box = ctk.CTkTextbox(left, height=260, fg_color=Colors.BG_SECONDARY, border_color=Colors.BORDER, text_color=Colors.TEXT_PRIMARY, font=Fonts.body_sm(), corner_radius=BorderRadius.SM)
        self.review_box.pack(fill="both", expand=True, pady=(Spacing.XS, 0))
        self.review_box.insert("1.0", "Belum ada data. Jalankan Prepare Sources terlebih dahulu.")
        self.review_box.configure(state="disabled")

        right = ctk.CTkFrame(cols, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True, padx=(Spacing.SM, 0))
        create_styled_label(right, "Log", style="caption").pack(anchor="w")
        self.log_box = ctk.CTkTextbox(right, height=260, fg_color=Colors.BG_SECONDARY, border_color=Colors.BORDER, text_color=Colors.TEXT_PRIMARY, font=Fonts.body_sm(), corner_radius=BorderRadius.SM)
        self.log_box.pack(fill="both", expand=True, pady=(Spacing.XS, 0))
        self.log_box.configure(state="disabled")

    # ------------------------------------------------------------------ callbacks
    def _set_status(self, status, progress=0.0):
        elapsed = max(0.0, time.monotonic() - self._processing_started_at) if self._processing_started_at else 0.0
        percent = int(round(max(0.0, min(1.0, float(progress))) * 100))
        display_status = f"{status} — {percent}% ({elapsed:.1f}s)"
        def _apply():
            try:
                self.status_label.configure(text=display_status)
                if any(token in str(status).lower() for token in ("script", "llm", "api")):
                    self.script_status_var.set(display_status)
                if progress is not None:
                    self.progress.set(max(0.0, min(1.0, float(progress))))
            except Exception:
                pass
        self.after(0, _apply)

    def _set_step(self, step_num, step_name, detail=""):
        def _apply():
            try:
                self.step_label.configure(text=f"Step {step_num}: {step_name} {detail}".strip())
            except Exception:
                pass
        self.after(0, _apply)

    def _log(self, msg):
        def _apply():
            try:
                self.log_box.configure(state="normal")
                self.log_box.insert("end", str(msg) + "\n")
                self.log_box.see("end")
                self.log_box.configure(state="disabled")
            except Exception:
                pass
        self.after(0, _apply)

    def _refresh_review(self):
        data = self.engine.get_review_data() if self.engine else {}
        lines = []
        lines.append(f"Session: {data.get('session_id') or self.session_id or '-'}")
        lines.append(f"Status: {data.get('status') or '-'}")
        lines.append(f"Output: {data.get('session_dir') or '-'}")
        lines.append("")
        lines.append("LLM / API HEALTH")
        script_plan = data.get("script_plan") or {}
        lines.append(f"SCRIPT SOURCE: {script_plan.get('script_source') or '-'}")
        llm_health = data.get("llm_health", []) or []
        if llm_health:
            for health in llm_health:
                error_class = health.get("last_error_class") or "-"
                lines.append(
                    f"- {health.get('provider') or '-'} / {health.get('model') or '-'}: "
                    f"{health.get('status') or '-'} ({error_class})"
                )
        else:
            lines.append("- Belum ada request API pada session ini")
        lines.append("")
        lines.append("STOCK STATUS")
        for st in data.get("stock_status", []) or []:
            lines.append(f"- {st.get('provider')}: {'OK' if st.get('available') else 'NO KEY/disabled'} base={st.get('base_url')}")
        lines.append("")
        lines.append("SOURCES")
        for s in data.get("sources", []) or []:
            pol = s.get("source_policy") or {}
            lines.append(f"- {s.get('source_id')} [{s.get('provider')}] {s.get('title')} dur={s.get('duration', 0):.0f}s status={s.get('status')} policy={pol.get('intended_use', '-')}/{pol.get('status', '-')}")
        outline = data.get("outline") or {}
        if outline:
            lines.append("")
            lines.append(f"OUTLINE: {outline.get('title')}")
            lines.append(str(outline.get("logline") or ""))
        lines.append("")
        lines.append("SEGMENTS")
        for seg in data.get("segments", []) or []:
            clips = seg.get("selected_clips") or []
            clip_txt = ", ".join(f"{c.get('kind')}:{c.get('source_id')}{'!' if c.get('policy_status') in ('warning', 'rejected') else ''}" for c in clips) or "-"
            lines.append(f"- {seg.get('segment_id')} {seg.get('title')} target={seg.get('target_duration')}s clips={clip_txt}")
            lines.append(f"  SCRIPT: {seg.get('narration_text') or '-'}")
        lines.append("")
        lines.append("POLICY WARNINGS")
        warned = []
        for seg in data.get("segments", []) or []:
            for c in seg.get("selected_clips") or []:
                if c.get("policy_status") in ("warning", "rejected"):
                    warned.append(f"- {seg.get('segment_id')} {c.get('kind')}:{c.get('source_id')} {';'.join(c.get('policy_reasons') or [])}")
        lines.extend(warned or ["- none"])
        lines.append("")
        lines.append("RENDER MANIFEST")
        rm = data.get("render_manifest") or {}
        for sid, info in (rm.get("segments") or {}).items():
            lines.append(f"- {sid}: {info.get('status')}")
        text = "\n".join(lines)
        def _apply():
            try:
                self.review_box.configure(state="normal")
                self.review_box.delete("1.0", "end")
                self.review_box.insert("1.0", text)
                self.review_box.configure(state="disabled")
            except Exception:
                pass
        self.after(0, _apply)
        self.after(0, self._render_script_editor)
        self.after(0, self._render_footage_preview)

    def _refresh_stock_status(self):
        try:
            from documentary_stock import StockFootageService
            cfg = self._get_engine_config()
            service = StockFootageService(cfg)
            status = {s["provider"]: s for s in service.provider_status()}
            p = status.get("pexels", {})
            x = status.get("pixabay", {})
            self.pexels_status.configure(text=f"key={'OK' if p.get('has_api_key') else 'MISSING'} enabled={p.get('enabled')}")
            self.pixabay_status.configure(text=f"key={'OK' if x.get('has_api_key') else 'MISSING'} enabled={x.get('enabled')}")
        except Exception as exc:
            self.pexels_status.configure(text=f"status error: {exc}")
            self.pixabay_status.configure(text="status error")

    def _on_llm_endpoint_selected(self, *args):
        value = (args[0] if args else self.llm_endpoint_var.get() or "").strip()
        if not value:
            return
        self.llm_base_var.set(value)
        self._llm_model_ids = []
        self._llm_test_results = []
        self.llm_model_choice_var.set("")
        try:
            self.llm_model_menu.configure(values=["-"])
        except Exception:
            pass
        label = self._llm_endpoint_labels.get(value, value)
        self.llm_status_var.set(f"Endpoint: {label} — klik Muat Model")

    def _on_llm_model_selected(self, *args):
        value = args[0] if args else self.llm_model_choice_var.get()
        if value and value != "-":
            self.llm_model_var.set(value)
            self.llm_override_var.set(True)
            self.llm_status_var.set("Model dipilih — klik 'Pakai Model Ini' untuk menyimpan")

    def _llm_box_set(self, text):
        def apply():
            self.llm_models_box.configure(state="normal")
            self.llm_models_box.delete("1.0", "end")
            self.llm_models_box.insert("1.0", text)
            self.llm_models_box.configure(state="disabled")
        self.after(0, apply)

    def _llm_box_add(self, text):
        def apply():
            self.llm_models_box.configure(state="normal")
            self.llm_models_box.insert("end", "\n" + text)
            self.llm_models_box.configure(state="disabled")
        self.after(0, apply)

    def _set_llm_models_ui(self, endpoints):
        endpoints = endpoints or []
        lines = []
        model_ids = []
        for ep in endpoints:
            lines.append(f"ENDPOINT {ep.get('label') or ep.get('task') or 'provider'} | {ep.get('base_url')} | model={ep.get('model') or '-'}")
            if ep.get("error"):
                lines.append(f"  ERROR {ep.get('error_class')}: {ep.get('error')}")
                continue
            models = ep.get("models") or []
            lines.append(f"  {len(models)} model tersedia")
            for model in models[:120]:
                lines.append(f"  - {model}")
                if model not in model_ids:
                    model_ids.append(model)
        self._llm_model_ids = model_ids[:300]
        first_model = self._llm_model_ids[0] if self._llm_model_ids else ""
        self.llm_model_choice_var.set(first_model)
        if first_model:
            self.llm_model_var.set(first_model)
        try:
            self.llm_model_menu.configure(values=self._llm_model_ids or ["-"])
        except Exception:
            pass
        ok_count = sum(1 for ep in endpoints if ep.get("ok"))
        suffix = " — model pertama auto dipilih" if first_model else ""
        self.llm_status_var.set(f"{ok_count}/{len(endpoints)} endpoint OK, {len(self._llm_model_ids)} model{suffix}")
        self._llm_box_set("\n".join(lines) if lines else "Tidak ada endpoint LLM yang bisa dihubungi.")

    def _apply_llm_test_results(self, results):
        results = results or []
        ok_models = [r.get("model") for r in results if r.get("ok") and r.get("model")]
        if not ok_models:
            self.llm_status_var.set("Test selesai: tidak ada model OK")
            return
        ok_set = set(ok_models)
        reordered = ok_models + [m for m in self._llm_model_ids if m not in ok_set]
        self._llm_model_ids = reordered[:300]
        try:
            self.llm_model_menu.configure(values=self._llm_model_ids or ["-"])
        except Exception:
            pass
        self.llm_model_choice_var.set(ok_models[0])
        self.llm_model_var.set(ok_models[0])
        self.llm_status_var.set(f"{len(ok_models)}/{len(results)} model OK — {ok_models[0]} auto dipilih")

    def fetch_llm_models(self):
        endpoint = (self.llm_base_var.get() or "").strip()
        self.llm_status_var.set("Menghubungi endpoint...")
        self._llm_box_set(f"Mengecek endpoint: {endpoint or '-'}")
        def task():
            engine = self._new_engine()
            endpoints = engine.list_llm_models(base_url=(self.llm_base_var.get() or "").strip(), max_endpoints=1)
            self.after(0, lambda: self._set_llm_models_ui(endpoints))
            ok_count = sum(1 for ep in endpoints if ep.get("ok"))
            self._set_status(f"LLM models: {ok_count}/{len(endpoints)} endpoint OK", 1.0)
        self._run_thread(task)

    def test_llm_models(self, test_all=False):
        base_url = (self.llm_base_var.get() or "").strip()
        if not base_url:
            messagebox.showwarning("Base URL kosong", "Isi Base URL endpoint OpenAI-compatible dulu.")
            return
        if test_all:
            models = list(self._llm_model_ids)
            if not models:
                messagebox.showwarning("Model belum diambil", "Klik 'Ambil Model' dulu untuk mengambil daftar model.")
                return
            if len(models) > 12:
                messagebox.showinfo("Test Semua", "Dibatasi 12 model pertama untuk menghindari rate limit provider gratis.")
                models = models[:12]
        else:
            model = (self.llm_model_choice_var.get() or self.llm_model_var.get()).strip()
            if not model:
                messagebox.showwarning("Model kosong", "Pilih model dari dropdown atau isi manual.")
                return
            models = [model]

        self.llm_status_var.set(f"Menyiapkan test {len(models)} model...")
        self._llm_box_add(f"TEST {base_url} — {len(models)} model, berjalan di background")

        def task():
            engine = self._new_engine()
            def on_probe(result, index, total):
                if result.get("error_class") == "testing":
                    status = "TEST"
                else:
                    status = "OK" if result.get("ok") else "FAIL"
                line = f"[{index}/{total}] {status} {result.get('model')} | {result.get('error_class')} | {result.get('latency_ms')}ms | {(result.get('error') or '')[:160]}"
                self._llm_box_add(line)
                self.after(0, lambda i=index, t=total, m=result.get("model"): self.llm_status_var.set(f"Test {i}/{t}: {m}"))
            results = engine.check_llm_models(base_url, models, max_models=len(models), progress_callback=on_probe)
            self._llm_test_results = results
            self.after(0, lambda: self._apply_llm_test_results(results))
            ok_count = sum(1 for result in results if result.get("ok"))
            self._llm_box_add(f"SELESAI TEST {base_url}: {ok_count}/{len(results)} OK")
            self._set_status(f"LLM test: {ok_count}/{len(results)} OK", 1.0)
        self._run_thread(task)

    def _persist_llm_override(self, override):
        if hasattr(self.config, "config") and hasattr(self.config, "save"):
            self.config.config.setdefault("documentary", {})["llm_override"] = override
            self.config.save()
        elif isinstance(self.config, dict):
            self.config.setdefault("documentary", {})["llm_override"] = override

    def save_llm_override(self):
        base_url = (self.llm_base_var.get() or "").strip()
        model = (self.llm_model_choice_var.get() or self.llm_model_var.get()).strip()
        if not base_url or not model:
            messagebox.showwarning("Override belum lengkap", "Base URL dan model wajib diisi.")
            return
        existing = (self._doc_config().get("llm_override") or {})
        self.llm_override_var.set(True)
        override = {
            "enabled": True,
            "base_url": base_url,
            "model": model,
            "api_key_env": existing.get("api_key_env") or "",
        }
        self._persist_llm_override(override)
        self.llm_model_var.set(model)
        self.llm_status_var.set("Override LLM tersimpan")
        messagebox.showinfo("LLM Override", f"Documentary Studio akan memakai:\n{base_url}\nmodel: {model}")

    def reset_llm_override(self):
        self.llm_override_var.set(False)
        base_url = (self.llm_base_var.get() or "").strip()
        model = (self.llm_model_choice_var.get() or self.llm_model_var.get()).strip()
        existing = (self._doc_config().get("llm_override") or {})
        self._persist_llm_override({
            "enabled": False,
            "base_url": base_url,
            "model": model,
            "api_key_env": existing.get("api_key_env") or "",
        })
        self.llm_status_var.set("Override LLM dimatikan")

    def _set_buttons_state(self, enabled):
        state = "normal" if enabled else "disabled"
        for btn in [self.discover_btn, self.prepare_btn, self.download_btn, self.plan_btn, getattr(self, "approve_btn", None), self.render_btn, self.run_all_btn, getattr(self, "generate_script_btn", None), getattr(self, "build_footage_btn", None), getattr(self, "preview_refresh_btn", None), getattr(self, "script_refresh_btn", None), getattr(self, "script_save_btn", None), getattr(self, "script_rebuild_btn", None)]:
            try:
                btn.configure(state=state)
            except Exception:
                pass

    # ------------------------------------------------------------------ actions
    def go_back(self):
        if self.processing:
            if not messagebox.askyesno("Batalkan?", "Proses sedang berjalan. Batalkan dan kembali?"):
                return
            self.cancel_flag = True
        self.app.show_page("landing")

    def cancel(self):
        self.cancel_flag = True
        self._log("Cancel diminta...")

    def _run_thread(self, fn):
        if self.processing:
            return
        engine_config = self._get_engine_config()
        self.processing = True
        self.cancel_flag = False
        self._processing_started_at = time.monotonic()
        self._set_buttons_state(False)
        self._set_status("Processing...", 0.0)
        def wrapper():
            self._worker_engine_config = engine_config
            try:
                fn()
            except Exception as exc:
                self._log(f"ERROR: {exc}")
                self._set_status(f"Error: {exc}", 0.0)
                self.after(0, lambda error=str(exc): messagebox.showerror("Documentary Studio", error))
            finally:
                self.processing = False
                self._processing_started_at = 0.0
                self._worker_engine_config = None
                self.after(0, lambda: self._set_buttons_state(True))
                self.after(0, self._refresh_review)
                self.after(0, self._refresh_stock_status)
        threading.Thread(target=wrapper, daemon=True).start()

    def discover_sources(self):
        brief = self._brief_from_ui()
        if not (brief.get("topic") or "").strip():
            messagebox.showwarning("Brief kosong", "Isi topik/brief dulu sebelum mencari sumber.")
            return
        def task():
            engine = self._new_engine()
            if self.source_mode_var.get() == "stock_footage":
                candidates = engine.discover_stock_sources(brief=brief, max_results=8)
                self._log(f"Stock API menemukan {len(candidates)} kandidat dari Pexels/Pixabay.")
                self._set_status("Stock discovery selesai", 1.0)
                return
            candidates = []
            try:
                candidates = engine.discover_sources_browser(brief=brief, max_results=8)
                self._log("Source discovery via agent-browser")
            except Exception as exc:
                self._log(f"Browser discovery tidak tersedia/gagal: {str(exc)[:160]}; fallback ytsearch")
                candidates = engine.discover_sources(brief=brief, max_results=8)
            urls = [c.get("url") for c in candidates if c.get("url")]
            if not urls:
                raise RuntimeError("AI source discovery tidak menemukan kandidat URL. Coba ubah brief atau cek koneksi/yt-dlp.")
            self.after(0, lambda discovered="\n".join(urls): (
                self.urls_box.delete("1.0", "end"),
                self.urls_box.insert("1.0", discovered),
            ))
            titles = "; ".join((c.get("title") or c.get("url"))[:60] for c in candidates[:3])
            self._log(f"AI menemukan {len(urls)} kandidat sumber. Contoh: {titles}")
            self._set_status("Source discovery selesai", 1.0)
        self._run_thread(task)

    def prepare_sources(self):
        urls = self._parse_urls()
        brief = self._brief_from_ui()
        if not urls and self.source_mode_var.get() == "manual_urls":
            messagebox.showwarning("URL kosong", "Mode manual_urls membutuhkan minimal satu URL.")
            return
        if not urls and self.source_mode_var.get() == "mixed":
            # mixed can still proceed with stock only; warn but allow
            pass
        def task():
            engine = self._new_engine()
            self.session_id = engine.create_session(brief)
            session_id = self.session_id
            self.after(0, lambda sid=session_id: self.session_var.set(sid))
            engine.prepare_sources(urls)
            self._set_status("Prepare sources selesai", 1.0)
        self._run_thread(task)

    def download_transcribe(self):
        existing_engine = self.engine
        session_id = self.session_var.get().strip()
        def task():
            engine = existing_engine or self._new_engine()
            if not engine.session_id and session_id:
                engine.load_session(session_id)
                self.session_id = engine.session_id
            if not engine.session_id:
                raise RuntimeError("Belum ada session. Jalankan Prepare Sources dulu.")
            engine.download_sources()
            engine.transcribe_sources()
            self._set_status("Download+transcript selesai", 1.0)
        self._run_thread(task)

    def generate_script(self):
        brief = self._brief_from_ui()
        if not (brief.get("topic") or "").strip():
            messagebox.showwarning("Brief kosong", "Isi topik/brief dulu sebelum generate script.")
            return
        def task():
            engine = self.engine or self._new_engine()
            if engine.session_id:
                engine.session_data["brief"] = brief
                engine._save_session()
            else:
                self.session_id = engine.create_session(brief)
                session_id = self.session_id
                self.after(0, lambda sid=session_id: self.session_var.set(sid))
            engine.generate_script_plan(brief)
            self._set_status("Script plan ready — edit di Script Editor", 1.0)
        self._run_thread(task)

    def build_footage(self):
        def task():
            engine = self._require_script_engine()
            if not engine.segments:
                raise RuntimeError("Script plan belum ada. Generate Script dulu.")
            engine.build_footage_plan()
            self._set_status("Footage plan ready — preview lalu Approve Footage", 1.0)
        self._run_thread(task)

    def refresh_footage_preview(self):
        try:
            if not self.engine and self.session_var.get().strip():
                engine = self._new_engine()
                if engine.load_session(self.session_var.get().strip()):
                    self.engine = engine
                    self.session_id = engine.session_id
            self._render_footage_preview()
        except Exception as exc:
            messagebox.showerror("Footage Preview", str(exc))

    def _apply_candidate_thumb(self, label, ctk_img, pil_img):
        try:
            label._doc_preview = (ctk_img, pil_img)
            label.configure(image=ctk_img, text="")
        except Exception:
            pass

    def _load_candidate_thumb(self, label, url):
        url = (url or "").strip()
        if not url:
            try:
                label.configure(image=None, text="no preview")
            except Exception:
                pass
            return
        cache_dir = None
        path = None
        try:
            import hashlib
            cache_dir = get_app_dir() / "output" / "documentaries" / "_thumb_cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
            path = cache_dir / f"{key}.png"
        except Exception:
            path = None

        def work():
            try:
                from PIL import Image
                import requests
                import io
                if path is not None and path.exists():
                    img = Image.open(path).convert("RGB")
                else:
                    resp = requests.get(url, timeout=12)
                    resp.raise_for_status()
                    img = Image.open(io.BytesIO(resp.content)).convert("RGB")
                    img.thumbnail((320, 180))
                    if path is not None:
                        img.save(path)
                ctk_img = ctk.CTkImage(light_image=img, size=(160, 90))
                self.after(0, lambda: self._apply_candidate_thumb(label, ctk_img, img))
            except Exception:
                self.after(0, lambda: label.configure(image=None, text="preview error"))
        threading.Thread(target=work, daemon=True).start()

    def _select_candidate_for_slot(self, seg, slot, cand):
        try:
            engine = self.engine or self._new_engine()
            if not engine.session_id:
                self._log("Pilih kandidat butuh session/footage plan")
                return
            engine.set_candidate_review(seg.get("segment_id"), slot.get("slot_id"), cand.get("id"), "select")
            engine._save_session()
            self._log(f"Dipilih: {slot.get('slot_id')} -> {cand.get('provider')}:{cand.get('id')}")
            self._set_status("Kandidat dipilih — lanjut Approve Footage", 1.0)
            self._render_footage_preview()
        except Exception as exc:
            self._log(f"Pilih kandidat gagal: {exc}")

    def _reject_candidate_for_slot(self, seg, slot, cand):
        try:
            engine = self.engine or self._new_engine()
            if not engine.session_id:
                self._log("Tolak kandidat butuh session/footage plan")
                return
            engine.set_candidate_review(seg.get("segment_id"), slot.get("slot_id"), cand.get("id"), "reject")
            self._log(f"Ditolak: {slot.get('slot_id')} -> {cand.get('provider')}:{cand.get('id')}")
            self._set_status("Kandidat ditolak dan tidak akan dirender", 1.0)
            self._render_footage_preview()
        except Exception as exc:
            self._log(f"Tolak kandidat gagal: {exc}")

    def _render_footage_preview(self):
        try:
            for child in self.footage_preview_scroll.winfo_children():
                child.destroy()
        except Exception:
            pass
        self.footage_preview_widgets = []
        segments = []
        if self.engine:
            segments = self.engine.segments or ((self.engine.session_data.get("script_plan") or {}).get("segments") or []) or []
        if not segments:
            create_styled_label(self.footage_preview_scroll, "Belum ada footage plan. Generate Script dulu, lalu Build Footage Plan.", style="muted").pack(anchor="w", padx=Spacing.SM, pady=Spacing.SM)
            return
        any_slot = False
        for seg in segments:
            slots = seg.get("footage_slots") or []
            if not slots:
                continue
            any_slot = True
            seg_card = ctk.CTkFrame(self.footage_preview_scroll, fg_color=Colors.BG_SECONDARY, corner_radius=BorderRadius.SM, border_width=1, border_color=Colors.BORDER)
            seg_card.pack(fill="x", pady=(0, Spacing.SM))
            head = ctk.CTkFrame(seg_card, fg_color="transparent")
            head.pack(fill="x", padx=Spacing.SM, pady=(Spacing.SM, 0))
            create_styled_label(head, f"{seg.get('segment_id')} • {seg.get('title') or ''}", style="caption").pack(side="left")
            create_styled_label(head, f"target tayang {float(seg.get('target_duration') or 0):.0f}s • {len(slots)} slot", style="caption", color=Colors.TEXT_MUTED).pack(side="right")
            for slot in slots:
                slot_card = ctk.CTkFrame(seg_card, fg_color=Colors.BG_TERTIARY, corner_radius=BorderRadius.SM)
                slot_card.pack(fill="x", padx=Spacing.SM, pady=(Spacing.XS, Spacing.SM))
                selected_id = slot.get("selected_candidate_id") or (slot.get("selected") or {}).get("source_id")
                head2 = ctk.CTkFrame(slot_card, fg_color="transparent")
                head2.pack(fill="x", padx=Spacing.SM, pady=(Spacing.SM, 0))
                slot_title = f"{slot.get('slot_id')} • {slot.get('idea') or ''}"
                create_styled_label(head2, slot_title, style="caption").pack(side="left")
                selection_label = "SUDAH DIPILIH" if selected_id else "BELUM DIPILIH"
                selection_color = Colors.SUCCESS if selected_id else Colors.WARNING
                create_styled_label(head2, selection_label, style="caption", color=selection_color).pack(side="right")
                create_styled_label(
                    slot_card,
                    f"Durasi tayang slot: {float(slot.get('needed_seconds') or 0):.1f} detik "
                    "(video pendek akan diulang otomatis bila perlu)",
                    style="caption",
                    color=Colors.TEXT_MUTED,
                ).pack(anchor="w", padx=Spacing.SM, pady=(Spacing.XS, 0))
                cands = slot.get("candidates") or []
                if not cands:
                    create_styled_label(slot_card, "Belum ada kandidat — cek stock provider/API key atau query slot.", style="caption", color=Colors.TEXT_MUTED).pack(anchor="w", padx=Spacing.SM, pady=(Spacing.XS, Spacing.SM))
                    continue
                for cand in cands[:3]:
                    row = ctk.CTkFrame(slot_card, fg_color=Colors.BG_SECONDARY, corner_radius=BorderRadius.SM)
                    row.pack(fill="x", padx=Spacing.SM, pady=(Spacing.XS, 0))
                    thumb = ctk.CTkLabel(row, text="", width=160, height=90, fg_color=Colors.BG_TERTIARY)
                    thumb.pack(side="left", padx=(Spacing.SM, Spacing.SM), pady=Spacing.SM)
                    info = ctk.CTkFrame(row, fg_color="transparent")
                    info.pack(side="left", fill="x", expand=True, pady=Spacing.SM)
                    title = (cand.get("title") or "")[:90]
                    meta = f"{cand.get('provider')} • sumber {float(cand.get('duration') or 0):.1f}s • score {float(cand.get('score') or 0):.0f} • {cand.get('license') or ''}"
                    create_styled_label(info, title, style="caption").pack(anchor="w")
                    create_styled_label(info, meta, style="caption", color=Colors.TEXT_MUTED).pack(anchor="w")
                    evidence = (cand.get("evidence") or cand.get("tags") or "")[:140]
                    if evidence:
                        create_styled_label(info, evidence, style="caption", color=Colors.TEXT_MUTED).pack(anchor="w")
                    is_selected = str(cand.get("id")) == str(selected_id)
                    btn = create_styled_button(row, "Dipilih" if is_selected else "Pilih", command=lambda s=seg, sl=slot, c=cand: self._select_candidate_for_slot(s, sl, c), style="success" if is_selected else "secondary", width=80, height=30)
                    btn.pack(side="right", padx=Spacing.SM, pady=Spacing.SM)
                    reject_btn = create_styled_button(row, "Tolak", command=lambda s=seg, sl=slot, c=cand: self._reject_candidate_for_slot(s, sl, c), style="danger", width=70, height=30)
                    reject_btn.pack(side="right", padx=(0, Spacing.XS), pady=Spacing.SM)
                    self._load_candidate_thumb(thumb, cand.get("preview_url") or cand.get("thumbnail") or "")
                    self.footage_preview_widgets.append({"slot": slot, "candidate": cand})
        if not any_slot:
            create_styled_label(self.footage_preview_scroll, "Script plan ada, tapi belum ada footage_slots. Jalankan Build Footage Plan.", style="muted").pack(anchor="w", padx=Spacing.SM, pady=Spacing.SM)

    def create_plan(self):
        existing_engine = self.engine
        session_id = self.session_var.get().strip()
        def task():
            engine = existing_engine or self._new_engine()
            if not engine.session_id and session_id:
                engine.load_session(session_id)
                self.session_id = engine.session_id
            if not engine.session_id:
                raise RuntimeError("Belum ada session. Jalankan Prepare Sources dulu.")
            engine.generate_script_plan()
            engine.build_footage_plan()
            self._set_status("Script + footage plan siap — review lalu Approve Footage", 1.0)
        self._run_thread(task)

    def approve_footage(self):
        existing_engine = self.engine
        session_id = self.session_var.get().strip()
        def task():
            engine = existing_engine or self._new_engine()
            if not engine.session_id and session_id:
                engine.load_session(session_id)
                self.session_id = engine.session_id
            if not engine.session_id:
                raise RuntimeError("Belum ada session. Jalankan Prepare Sources dulu.")
            engine.approve_footage_plan(auto=False)
            self._set_status("Footage plan approved", 1.0)
        self._run_thread(task)

    def render_final(self):
        existing_engine = self.engine
        session_id = self.session_var.get().strip()
        def task():
            engine = existing_engine or self._new_engine()
            if not engine.session_id and session_id:
                engine.load_session(session_id)
                self.session_id = engine.session_id
            if not engine.session_id:
                raise RuntimeError("Belum ada session. Jalankan Prepare Sources dulu.")
            engine.run_render_only()
            self._set_status("Render selesai", 1.0)
            self._log(f"Final: {engine.session_data.get('final_path')}")
        self._run_thread(task)

    def run_full(self):
        urls = self._parse_urls()
        brief = self._brief_from_ui()
        if not urls and self.source_mode_var.get() == "manual_urls":
            messagebox.showwarning("URL kosong", "Mode manual_urls membutuhkan minimal satu URL.")
            return
        def task():
            engine = self._new_engine()
            result = engine.run_full_pipeline(urls, brief)
            self.session_id = engine.session_id
            session_id = self.session_id
            self.after(0, lambda sid=session_id: self.session_var.set(sid))
            if result.get("awaiting_review"):
                self._set_status("Review footage wajib sebelum render", 1.0)
                self._log("Full pipeline berhenti di review gate; pilih kandidat lalu Approve Footage.")
            else:
                self._set_status("Full pipeline selesai", 1.0)
                self._log(f"Final: {result.get('final_path')}")
        self._run_thread(task)

    def _collect_script_edits(self):
        edits = []
        for w in self.script_widgets:
            edits.append({
                "segment_id": w.get("segment_id"),
                "order": w.get("order"),
                "title": w["title_entry"].get().strip(),
                "narration_text": w["narration_box"].get("1.0", "end-1c").strip(),
            })
        return edits

    def _require_script_engine(self, engine=None, session_id=None):
        engine = engine or self.engine or self._new_engine()
        sid = session_id if session_id is not None else self.session_var.get().strip()
        if not engine.session_id and sid:
            if not engine.load_session(sid):
                raise RuntimeError("Session tidak ditemukan")
            self.engine = engine
            self.session_id = engine.session_id
        if not engine.session_id:
            raise RuntimeError("Belum ada session/script plan. Generate Script dulu.")
        return engine

    def _apply_script_edits(self, engine, edits):
        by_id = {str(e.get("segment_id")): e for e in edits if e.get("segment_id") is not None}
        by_order = {int(e.get("order") or 0): e for e in edits if e.get("order") is not None}
        for seg in engine.segments or []:
            edit = by_id.get(str(seg.get("segment_id"))) or by_order.get(int(seg.get("order") or 0))
            if not edit:
                continue
            if edit.get("title"):
                seg["title"] = edit["title"]
            narration = (edit.get("narration_text") or "").strip()
            if not narration:
                raise RuntimeError(f"Narasi kosong untuk {seg.get('segment_id') or seg.get('order')}")
            seg["narration_text"] = narration
        engine.segments = engine.segments or []
        script_plan = engine.session_data.get("script_plan") or {}
        engine.outline = script_plan if isinstance(script_plan, dict) and script_plan else (engine.outline or {})
        if isinstance(engine.outline, dict):
            engine.outline["segments"] = engine.segments
        engine.session_data["outline"] = engine.outline
        engine.session_data["segments"] = engine.segments
        if isinstance(engine.session_data.get("script_plan"), dict):
            engine.session_data["script_plan"]["segments"] = engine.segments
        engine._write_json(engine.plan_dir / "script_plan.json", engine.session_data.get("script_plan") or engine.outline)
        engine._write_json(engine.plan_dir / "segment_plan.json", {"segments": engine.segments})
        engine.session_data["status"] = "script_edited"
        engine._save_session()

    def refresh_script_editor(self):
        try:
            if not self.engine and self.session_var.get().strip():
                engine = self._new_engine()
                if engine.load_session(self.session_var.get().strip()):
                    self.engine = engine
                    self.session_id = engine.session_id
            self._render_script_editor()
        except Exception as exc:
            messagebox.showerror("Script Editor", str(exc))

    def save_script(self):
        edits = self._collect_script_edits()
        if not edits:
            messagebox.showwarning("Script Editor", "Belum ada script plan untuk disimpan.")
            return
        if any(not (e.get("narration_text") or "").strip() for e in edits):
            messagebox.showwarning("Script Editor", "Ada narasi yang kosong. Isi semua narasi sebelum simpan.")
            return
        existing_engine = self.engine
        session_id = self.session_var.get().strip()
        def task():
            engine = self._require_script_engine(existing_engine, session_id)
            self._apply_script_edits(engine, edits)
            self._set_status("Script disimpan — jalankan Rebuild Footage Plan jika perlu", 1.0)
        self._run_thread(task)

    def rebuild_footage_plan(self):
        edits = self._collect_script_edits()
        existing_engine = self.engine
        session_id = self.session_var.get().strip()
        def task():
            engine = self._require_script_engine(existing_engine, session_id)
            if edits:
                self._apply_script_edits(engine, edits)
            engine.build_footage_plan()
            self._set_status("Footage plan rebuilt — review lalu Approve Footage", 1.0)
        self._run_thread(task)

    def load_session(self):
        sid = self.session_var.get().strip()
        if not sid:
            messagebox.showwarning("Session kosong", "Masukkan session ID.")
            return
        try:
            engine = self._new_engine()
            if not engine.load_session(sid):
                raise RuntimeError("Session tidak ditemukan")
            self.engine = engine
            self.session_id = sid
            self._refresh_review()
            self._log(f"Loaded session {sid}")
        except Exception as exc:
            messagebox.showerror("Load session", str(exc))

    def open_output(self):
        path = ""
        if self.engine and getattr(self.engine, "session_dir", None):
            path = str(self.engine.session_dir)
        elif self.session_id:
            path = str(get_app_dir() / "output" / "documentaries" / self.session_id)
        if path and Path(path).exists():
            try:
                if os.name == "nt":
                    os.startfile(path)
                else:
                    os.startfile(path) if hasattr(os, "startfile") else os.system(f'open "{path}"')
            except Exception as exc:
                messagebox.showerror("Open output", str(exc))
        else:
            # fallback output documentaries
            path = str(get_app_dir() / "output" / "documentaries")
            if Path(path).exists():
                try:
                    os.startfile(path)
                except Exception:
                    pass
            else:
                messagebox.showinfo("Output", "Belum ada output.")
