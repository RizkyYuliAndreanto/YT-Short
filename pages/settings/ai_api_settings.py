"""
AI API Settings Sub-Page - Gateway routing & card-based navigation to individual providers
"""

import threading
import customtkinter as ctk
from tkinter import messagebox

from pages.settings.base_dialog import BaseSettingsSubPage
from config.ai_provider_config import (
    AI_PROVIDERS_CONFIG,
    get_provider_name,
)
from config.ai_router import (
    apply_active_router_to_config,
    auto_detect_and_select_router,
    get_default_gateway_config,
    resolve_task_provider,
)


class AIAPISettingsSubPage(BaseSettingsSubPage):
    """Sub-page for AI API settings with gateway controls and card navigation"""

    def __init__(self, parent, config, on_save_callback, on_back_callback):
        self.config = config
        self.on_save_callback = on_save_callback
        self.main_back = on_back_callback
        self.container = parent

        super().__init__(parent, "AI API Settings", on_back_callback)

        self.create_content()

    def create_content(self):
        """Create page content with gateway settings and provider cards"""
        # 1. Quick Provider Switch Section
        quick_section = self.create_section("Quick Provider Switch")

        quick_frame = ctk.CTkFrame(quick_section, fg_color="transparent")
        quick_frame.pack(fill="x", padx=10, pady=(0, 10))

        ctk.CTkLabel(
            quick_frame,
            text="Apply provider to all AI services:",
            font=ctk.CTkFont(size=11),
        ).pack(anchor="w", padx=(0, 10), pady=(0, 6))

        # Provider buttons
        btn_frame = ctk.CTkFrame(quick_frame, fg_color="transparent")
        btn_frame.pack(fill="x")

        ctk.CTkButton(
            btn_frame,
            text="🔀 9router (Local)",
            width=130,
            fg_color="#8b5cf6",
            hover_color="#7c3aed",
            command=lambda: self._apply_provider("9router"),
        ).pack(side="left", padx=2, pady=2)

        ctk.CTkButton(
            btn_frame,
            text="🌐 Omnirouter",
            width=120,
            fg_color="#0ea5e9",
            hover_color="#0284c7",
            command=lambda: self._apply_provider("omnirouter"),
        ).pack(side="left", padx=2, pady=2)

        ctk.CTkButton(
            btn_frame,
            text="🚀 GROQ (Free)",
            width=120,
            fg_color="#f55036",
            hover_color="#d44030",
            command=lambda: self._apply_provider("groq"),
        ).pack(side="left", padx=2, pady=2)

        ctk.CTkButton(
            btn_frame,
            text="🌐 OpenRouter",
            width=120,
            fg_color="#6366f1",
            hover_color="#4f46e5",
            command=lambda: self._apply_provider("openrouter"),
        ).pack(side="left", padx=2, pady=2)

        ctk.CTkButton(
            btn_frame,
            text="🤖 OpenAI",
            width=110,
            fg_color="#10a37f",
            hover_color="#0d8a6a",
            command=lambda: self._apply_provider("openai"),
        ).pack(side="left", padx=2, pady=2)

        # 2. Gateway & Fallback Section
        gw_section = self.create_section("Gateway & Fallback Routing")
        gw_frame = ctk.CTkFrame(gw_section, fg_color="transparent")
        gw_frame.pack(fill="x", padx=10, pady=(0, 10))

        # Fallback Toggle
        gw_config = self.config.get("ai_gateway", get_default_gateway_config())
        fallback_enabled = gw_config.get("fallback_enabled", True)

        toggle_frame = ctk.CTkFrame(gw_frame, fg_color="transparent")
        toggle_frame.pack(fill="x", pady=(0, 6))

        self.fallback_switch = ctk.CTkSwitch(
            toggle_frame,
            text="Enable Automatic Fallback Chain",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_fallback_toggled,
        )
        if fallback_enabled:
            self.fallback_switch.select()
        else:
            self.fallback_switch.deselect()
        self.fallback_switch.pack(side="left")

        # Fallback chain info
        fb_providers = gw_config.get(
            "fallback_providers", ["9router", "openrouter", "groq"]
        )
        chain_names = [get_provider_name(p) for p in fb_providers]
        self.chain_label = ctk.CTkLabel(
            gw_frame,
            text=f"Fallback Chain Order: {' ➔ '.join(chain_names)}",
            font=ctk.CTkFont(size=10),
            text_color="gray",
        )
        self.chain_label.pack(anchor="w", pady=(2, 0))

        # Auto-detect Router button
        self.auto_router_btn = ctk.CTkButton(
            gw_frame,
            text="⚡ Cek & Gunakan Router Aktif (9router / Omnirouter)",
            height=34,
            fg_color="#8b5cf6",
            hover_color="#7c3aed",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._on_auto_detect_router,
        )
        self.auto_router_btn.pack(fill="x", pady=(8, 2))

        # 3. AI Providers Section
        providers_section = self.create_section("AI Services & Model Selection")

        cards_frame = ctk.CTkFrame(providers_section, fg_color="transparent")
        cards_frame.pack(fill="x", padx=10, pady=(0, 12))
        cards_frame.grid_columnconfigure((0, 1), weight=1, uniform="provider")

        # Row 1
        self._create_provider_card(
            cards_frame,
            0,
            0,
            "Highlight Finder",
            "Find viral moments from transcript",
            "highlight_finder",
        )
        self._create_provider_card(
            cards_frame,
            0,
            1,
            "Caption Maker",
            "Generate captions (Whisper)",
            "caption_maker",
        )

        # Row 2
        self._create_provider_card(
            cards_frame,
            1,
            0,
            "Hook Maker",
            "Create audio/text TTS hooks",
            "hook_maker",
        )
        self._create_provider_card(
            cards_frame,
            1,
            1,
            "Title Generator",
            "Generate titles & descriptions",
            "youtube_title_maker",
        )

    def _on_fallback_toggled(self):
        """Handle fallback switch toggle"""
        is_on = bool(self.fallback_switch.get())
        gw = self.config.get("ai_gateway", get_default_gateway_config())
        gw["fallback_enabled"] = is_on
        self.config.set("ai_gateway", gw)
        if self.on_save_callback:
            self.on_save_callback({"ai_gateway": gw})

    def _on_auto_detect_router(self):
        """Auto detect which router (9router or Omnirouter) is reachable and working"""
        self.auto_router_btn.configure(
            state="disabled", text="⏳ Sedang Mengecek 9router & Omnirouter..."
        )

        def run_check():
            try:
                cfg_dict = (
                    self.config.config
                    if hasattr(self.config, "config")
                    else self.config
                )
                result = auto_detect_and_select_router(cfg_dict, timeout=4.0)

                working_probe = result.get("working_probe")
                if working_probe and working_probe.get("ok"):
                    updated_cfg = apply_active_router_to_config(
                        cfg_dict, working_probe
                    )
                    if hasattr(self.config, "save_config"):
                        self.config.save_config(updated_cfg)
                    elif hasattr(self.config, "save"):
                        self.config.save()
                    if self.on_save_callback:
                        self.on_save_callback(updated_cfg)

                    self.after(0, lambda: self._on_auto_detect_success(result))
                else:
                    self.after(0, lambda: self._on_auto_detect_failed(result))
            except Exception as e:
                self.after(0, lambda: self._on_auto_detect_error(str(e)))

        threading.Thread(target=run_check, daemon=True).start()

    def _on_auto_detect_success(self, result):
        self.auto_router_btn.configure(
            state="normal",
            text="⚡ Cek & Gunakan Router Aktif (9router / Omnirouter)",
        )
        self._update_all_statuses()
        working = result.get("working_probe", {})
        prov_name = working.get("provider", "").upper()
        url = working.get("base_url", "")
        models_cnt = len(working.get("models", []))
        messagebox.showinfo(
            "Router Aktif Ditemukan",
            f"✓ Berhasil terhubung ke {prov_name}!\n\n"
            f"URL: {url}\n"
            f"Model: {models_cnt} model tersedia.\n\n"
            f"Semua AI services (Highlight Finder, Hook, Title) telah dialihkan ke {prov_name} secara otomatis.",
        )

    def _on_auto_detect_failed(self, result):
        self.auto_router_btn.configure(
            state="normal",
            text="⚡ Cek & Gunakan Router Aktif (9router / Omnirouter)",
        )
        p9 = result.get("probes", {}).get("9router", {})
        pomni = result.get("probes", {}).get("omnirouter", {})
        msg = (
            f"Tidak ada router lokal yang berhasil terhubung:\n\n"
            f"• 9router ({p9.get('base_url', 'http://localhost:20128/v1')}):\n"
            f"  Status: {p9.get('status')} - {p9.get('error')[:80]}\n\n"
            f"• Omnirouter:\n"
            f"  Status: {pomni.get('status')} - {pomni.get('error')[:80]}\n\n"
            f"💡 Saran: Pastikan aplikasi 9router atau Omnirouter sudah menyala, atau gunakan GROQ / OpenRouter.",
        )
        messagebox.showwarning("Router Belum Terhubung", msg)

    def _on_auto_detect_error(self, err):
        self.auto_router_btn.configure(
            state="normal",
            text="⚡ Cek & Gunakan Router Aktif (9router / Omnirouter)",
        )
        messagebox.showerror("Error", f"Gagal mengecek router: {err}")

    def _apply_provider(self, provider_key: str):
        """Apply selected provider to all AI services"""
        provider_config = AI_PROVIDERS_CONFIG.get(provider_key)
        if not provider_config:
            messagebox.showerror("Error", f"Unknown provider: {provider_key}")
            return

        # Provider-specific default models
        provider_defaults = {
            "9router": {
                "highlight_finder": "ag/gemini-3.8-flash-high",
                "caption_maker": "whisper-large-v3-turbo",  # Groq Whisper fallback
                "hook_maker": "tts-1",
                "youtube_title_maker": "ag/gemini-3.8-flash-high",
            },
            "omnirouter": {
                "highlight_finder": "antigravity/gemini-3.8-flash-high",
                "caption_maker": "whisper-large-v3-turbo",
                "hook_maker": "tts-1",
                "youtube_title_maker": "antigravity/gemini-3.8-flash-high",
            },
            "groq": {
                "highlight_finder": "llama-3.3-70b-versatile",
                "caption_maker": "whisper-large-v3",
                "hook_maker": "tts-1",  # GROQ doesn't have TTS, keep placeholder
                "youtube_title_maker": "llama-3.3-70b-versatile",
            },
            "openrouter": {
                "highlight_finder": "meta-llama/llama-3.3-70b-instruct",
                "caption_maker": "openai/whisper-large-v3",
                "hook_maker": "openai/tts-1",
                "youtube_title_maker": "meta-llama/llama-3.3-70b-instruct",
            },
            "openai": {
                "highlight_finder": "gpt-4.1",
                "caption_maker": "whisper-1",
                "hook_maker": "tts-1",
                "youtube_title_maker": "gpt-4.1",
            },
        }

        defaults = provider_defaults.get(provider_key, {})
        base_url = provider_config.get("base_url", "https://api.openai.com/v1")

        # Update all providers
        ai_providers = self.config.get("ai_providers", {})

        for service_key in [
            "highlight_finder",
            "caption_maker",
            "hook_maker",
            "youtube_title_maker",
        ]:
            if service_key not in ai_providers:
                ai_providers[service_key] = {}

            if service_key == "caption_maker" and provider_key in ("9router", "omnirouter"):
                # 9router and Omnirouter are chat LLM gateways; use Groq Whisper for speech-to-text
                ai_providers[service_key]["provider"] = "groq"
                ai_providers[service_key]["base_url"] = "https://api.groq.com/openai/v1"
                ai_providers[service_key]["model"] = "whisper-large-v3-turbo"
            elif service_key == "hook_maker" and provider_key in ("9router", "omnirouter", "groq"):
                # LLM gateways do not provide TTS speech synthesis; use OpenAI / Edge-TTS
                ai_providers[service_key]["provider"] = "openai"
                ai_providers[service_key]["base_url"] = "https://api.openai.com/v1"
                ai_providers[service_key]["model"] = "tts-1"
            else:
                ai_providers[service_key]["provider"] = provider_key
                ai_providers[service_key]["base_url"] = base_url
                ai_providers[service_key]["model"] = defaults.get(service_key, "")

        # Update preferred provider in gateway
        gw = self.config.get("ai_gateway", get_default_gateway_config())
        gw["preferred_provider"] = provider_key
        self.config.set("ai_gateway", gw)

        # Save config
        self.config.set("ai_providers", ai_providers)
        self.on_save_callback({"ai_providers": ai_providers, "ai_gateway": gw})

        # Refresh UI
        self._update_all_statuses()

        provider_name = provider_config.get("name", provider_key.upper())
        env_var = provider_config.get(
            "api_key_env", f"{provider_key.upper()}_API_KEY"
        )
        messagebox.showinfo(
            "Provider Applied",
            f"All AI services now use {provider_name}.\n\n"
            f"Ensure your API key is set in .env file:\n"
            f"  {env_var}=your_key_here",
        )

    def _update_all_statuses(self):
        """Update all provider card statuses cleanly without rebuilding widgets"""
        for key in [
            "highlight_finder",
            "caption_maker",
            "hook_maker",
            "youtube_title_maker",
        ]:
            self._update_status(key)

    def _create_provider_card(self, parent, row, col, title, desc, key):
        """Create a clickable provider card"""
        card = ctk.CTkFrame(
            parent, fg_color=("gray85", "gray20"), corner_radius=8, cursor="hand2"
        )
        card.grid(row=row, column=col, padx=5, pady=5, sticky="nsew")
        card.bind("<Button-1>", lambda e, k=key: self.navigate_to_provider(k))

        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(12, 4))
        header.bind("<Button-1>", lambda e, k=key: self.navigate_to_provider(k))

        ctk.CTkLabel(
            header, text=title, font=ctk.CTkFont(size=12, weight="bold")
        ).pack(side="left")

        status = ctk.CTkLabel(header, text="", font=ctk.CTkFont(size=10))
        status.pack(side="right")
        setattr(self, f"{key}_status", status)

        d = ctk.CTkLabel(card, text=desc, font=ctk.CTkFont(size=9), text_color="gray")
        d.pack(anchor="w", padx=12, pady=(0, 4))
        d.bind("<Button-1>", lambda e, k=key: self.navigate_to_provider(k))

        m = ctk.CTkLabel(card, text="", font=ctk.CTkFont(size=9), text_color="gray")
        m.pack(anchor="w", padx=12, pady=(0, 10))
        m.bind("<Button-1>", lambda e, k=key: self.navigate_to_provider(k))
        setattr(self, f"{key}_model", m)

        card.bind("<Enter>", lambda e: card.configure(fg_color=("gray75", "gray25")))
        card.bind("<Leave>", lambda e: card.configure(fg_color=("gray85", "gray20")))

        self._update_status(key)

    def _update_status(self, key):
        """Update provider card status using resolved routing"""
        cfg_dict = (
            self.config.config
            if hasattr(self.config, "config")
            else self.config
        )
        resolved = resolve_task_provider(cfg_dict, key)

        provider_name = resolved.get("name") or resolved.get("provider") or "Unknown"
        model = resolved.get("model", "")
        has_key = resolved.get("has_key", False)

        s = getattr(self, f"{key}_status", None)
        m = getattr(self, f"{key}_model", None)

        if s:
            if has_key and model:
                s.configure(text="Configured", text_color="green")
            elif has_key:
                s.configure(text="No model", text_color="orange")
            elif model:
                s.configure(text="No API key", text_color="orange")
            else:
                s.configure(text="Not set", text_color="gray")

        if m:
            model_display = model if model else "Not set"
            m.configure(text=f"[{provider_name}] {model_display}")

    def navigate_to_provider(self, key):
        """Navigate to provider settings page"""
        for w in self.container.winfo_children():
            w.destroy()

        if key == "highlight_finder":
            from pages.settings.ai_providers.highlight_finder import (
                HighlightFinderSettingsPage,
            )

            HighlightFinderSettingsPage(
                self.container, self.config, self.on_save_callback, self._back
            )
        elif key == "caption_maker":
            from pages.settings.ai_providers.caption_maker import (
                CaptionMakerSettingsPage,
            )

            CaptionMakerSettingsPage(
                self.container, self.config, self.on_save_callback, self._back
            )
        elif key == "hook_maker":
            from pages.settings.ai_providers.hook_maker import HookMakerSettingsPage

            HookMakerSettingsPage(
                self.container, self.config, self.on_save_callback, self._back
            )
        elif key == "youtube_title_maker":
            from pages.settings.ai_providers.title_generator import (
                TitleGeneratorSettingsPage,
            )

            TitleGeneratorSettingsPage(
                self.container, self.config, self.on_save_callback, self._back
            )

    def _back(self):
        """Navigate back to AI API settings"""
        for w in self.container.winfo_children():
            w.destroy()
        AIAPISettingsSubPage(
            self.container, self.config, self.on_save_callback, self.main_back
        )
