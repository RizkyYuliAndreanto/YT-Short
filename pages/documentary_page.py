"""
Documentary Studio Page — Feature 07
Standalone wizard for long-form YouTube documentary videos (16:9).
"""

import copy
import os
import threading
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
        return engine_config

    def _new_engine(self):
        from documentary_engine import DocumentaryEngine
        engine_config = self._get_engine_config()
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
        create_styled_label(title_col, "Video dokumenter YouTube 16:9 dari brief, URL, dan stock footage", style="muted").pack(anchor="w")

        right = ctk.CTkFrame(header, fg_color="transparent")
        right.pack(side="right")
        create_styled_button(right, "Settings", command=lambda: self.app.show_page("settings"), style="secondary", width=90, height=32, tooltip="Buka pengaturan aplikasi").pack(side="left")

        self.main_scroll = ctk.CTkScrollableFrame(self, fg_color="transparent", scrollbar_button_color=Colors.BORDER, scrollbar_button_hover_color=Colors.ACCENT_PRIMARY)
        self.main_scroll.pack(fill="both", expand=True, padx=Spacing.LG, pady=(0, Spacing.MD))

        self._create_brief_section()
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
        sec = self._section_frame("1. Brief Documentary", "Topik, durasi target, gaya bahasa, dan format output", Colors.ACCENT_PRIMARY)
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
        field(grid, "Target durasi (detik)", self.duration_var, width=110, tooltip="Misal 300 untuk 5 menit")

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
        col.pack(side="left")
        create_styled_label(col, "Voice TTS", style="caption").pack(anchor="w")
        ctk.CTkOptionMenu(col, variable=self.voice_var, values=["id-ID-ArdiNeural", "id-ID-GadisNeural"], fg_color=Colors.BG_SECONDARY, button_color=Colors.ACCENT_PRIMARY, button_hover_color=Colors.BTN_PRIMARY_HOVER, dropdown_fg_color=Colors.CARD_BG, text_color=Colors.TEXT_PRIMARY, font=Fonts.body(), width=170, height=36).pack(anchor="w")

    def _create_sources_section(self):
        sec = self._section_frame("2. Sources & Stock Footage", "URL video manual dan/atau B-roll dari Pexels/Pixabay", Colors.INFO)

        url_frame = ctk.CTkFrame(sec, fg_color="transparent")
        url_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.SM))
        create_styled_label(url_frame, "URL Video (satu per baris)", style="caption").pack(anchor="w")
        self.urls_box = ctk.CTkTextbox(url_frame, height=90, fg_color=Colors.BG_SECONDARY, border_color=Colors.BORDER, text_color=Colors.TEXT_PRIMARY, font=Fonts.body(), corner_radius=BorderRadius.SM)
        self.urls_box.pack(fill="x", pady=(Spacing.XS, 0))
        self.urls_box.insert("1.0", "")
        ToolTip(self.urls_box, "Tempel URL YouTube/TikTok/Instagram/Facebook. Untuk stock footage, cukup aktifkan provider di bawah.")

        discover_row = ctk.CTkFrame(sec, fg_color="transparent")
        discover_row.pack(fill="x", padx=Spacing.MD, pady=(Spacing.XS, 0))
        self.discover_btn = create_styled_button(discover_row, "Cari Link dengan AI", command=self.discover_sources, style="secondary", width=160, height=34, tooltip="LLM membuat query pencarian lalu yt-dlp ytsearch mengambil kandidat URL YouTube")
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
        note.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))
        create_styled_label(note, "API key dibaca dari env: PEXELS_API_KEY dan PIXABAY_API_KEY. Base URL default endpoint resmi; ubah hanya untuk proxy/mirror.", style="caption", color=Colors.TEXT_MUTED).pack(anchor="w")

    def _create_pipeline_section(self):
        sec = self._section_frame("3. Pipeline", "Jalankan bertahap atau full pipeline", Colors.ACCENT_SECONDARY)
        wrap = ctk.CTkFrame(sec, fg_color="transparent")
        wrap.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.SM))

        self.prepare_btn = create_styled_button(wrap, "1. Prepare Sources", command=self.prepare_sources, style="secondary", width=150, height=36, tooltip="Analisis URL sumber")
        self.prepare_btn.pack(side="left", padx=(0, Spacing.XS))
        self.download_btn = create_styled_button(wrap, "2. Download+Transcript", command=self.download_transcribe, style="secondary", width=170, height=36, tooltip="Download video dan transcribe")
        self.download_btn.pack(side="left", padx=Spacing.XS)
        self.plan_btn = create_styled_button(wrap, "3. Outline+Plan", command=self.create_plan, style="secondary", width=150, height=36, tooltip="Generate outline, stock candidates, dan pilih clips")
        self.plan_btn.pack(side="left", padx=Spacing.XS)
        self.render_btn = create_styled_button(wrap, "4. Render Final", command=self.render_final, style="primary", width=140, height=36, tooltip="Voiceover, subtitle, render per segmen, concat")
        self.render_btn.pack(side="left", padx=Spacing.XS)
        self.run_all_btn = create_styled_button(wrap, "Run Full Pipeline", command=self.run_full, style="success", width=150, height=36, tooltip="Jalankan semua tahap otomatis")
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

    def _create_review_section(self):
        sec = self._section_frame("4. Review & Log", "Ringkasan sources, outline, segmen, dan log proses", Colors.SUCCESS)
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
        def _apply():
            try:
                self.status_label.configure(text=str(status))
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
        lines.append("STOCK STATUS")
        for st in data.get("stock_status", []) or []:
            lines.append(f"- {st.get('provider')}: {'OK' if st.get('available') else 'NO KEY/disabled'} base={st.get('base_url')}")
        lines.append("")
        lines.append("SOURCES")
        for s in data.get("sources", []) or []:
            lines.append(f"- {s.get('source_id')} [{s.get('provider')}] {s.get('title')} dur={s.get('duration', 0):.0f}s status={s.get('status')}")
        outline = data.get("outline") or {}
        if outline:
            lines.append("")
            lines.append(f"OUTLINE: {outline.get('title')}")
            lines.append(str(outline.get("logline") or ""))
        lines.append("")
        lines.append("SEGMENTS")
        for seg in data.get("segments", []) or []:
            clips = seg.get("selected_clips") or []
            clip_txt = ", ".join(f"{c.get('kind')}:{c.get('source_id')}" for c in clips) or "-"
            lines.append(f"- {seg.get('segment_id')} {seg.get('title')} target={seg.get('target_duration')}s clips={clip_txt}")
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

    def _set_buttons_state(self, enabled):
        state = "normal" if enabled else "disabled"
        for btn in [self.discover_btn, self.prepare_btn, self.download_btn, self.plan_btn, self.render_btn, self.run_all_btn]:
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
        self.processing = True
        self.cancel_flag = False
        self._set_buttons_state(False)
        self._set_status("Processing...", 0.0)
        def wrapper():
            try:
                fn()
            except Exception as exc:
                self._log(f"ERROR: {exc}")
                self._set_status(f"Error: {exc}", 0.0)
                messagebox.showerror("Documentary Studio", str(exc))
            finally:
                self.processing = False
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
            candidates = engine.discover_sources(brief=brief, max_results=8)
            urls = [c.get("url") for c in candidates if c.get("url")]
            if not urls:
                raise RuntimeError("AI source discovery tidak menemukan kandidat URL. Coba ubah brief atau cek koneksi/yt-dlp.")
            self.urls_box.delete("1.0", "end")
            self.urls_box.insert("1.0", "\n".join(urls))
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
            self.session_var.set(self.session_id)
            engine.prepare_sources(urls)
            self._set_status("Prepare sources selesai", 1.0)
        self._run_thread(task)

    def download_transcribe(self):
        def task():
            engine = self.engine or self._new_engine()
            if not engine.session_id and self.session_var.get().strip():
                engine.load_session(self.session_var.get().strip())
                self.session_id = engine.session_id
            if not engine.session_id:
                raise RuntimeError("Belum ada session. Jalankan Prepare Sources dulu.")
            engine.download_sources()
            engine.transcribe_sources()
            self._set_status("Download+transcript selesai", 1.0)
        self._run_thread(task)

    def create_plan(self):
        def task():
            engine = self.engine or self._new_engine()
            if not engine.session_id and self.session_var.get().strip():
                engine.load_session(self.session_var.get().strip())
                self.session_id = engine.session_id
            if not engine.session_id:
                raise RuntimeError("Belum ada session. Jalankan Prepare Sources dulu.")
            engine.generate_outline()
            engine.find_stock_candidates()
            engine.select_clips()
            self._set_status("Outline+plan selesai", 1.0)
        self._run_thread(task)

    def render_final(self):
        def task():
            engine = self.engine or self._new_engine()
            if not engine.session_id and self.session_var.get().strip():
                engine.load_session(self.session_var.get().strip())
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
            self.session_var.set(self.session_id)
            self._set_status("Full pipeline selesai", 1.0)
            self._log(f"Final: {result.get('final_path')}")
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
