"""
Base class for AI Provider settings pages
"""

import threading
import customtkinter as ctk
from tkinter import messagebox

from config.ai_provider_config import AI_PROVIDERS_CONFIG, get_provider_base_url
from pages.settings.base_dialog import BaseSettingsSubPage
from components.ui_theme import Colors


# Generate provider dropdown options from config
def get_provider_dropdown_options():
    """Get list of provider display names for dropdown"""
    # Priority order - most commonly used first
    priority_order = [
        "9router",
        "ytclip",
        "openai",
        "groq",
        "openrouter",
        "google",
        "anthropic",
        "mistral",
        "together",
        "custom",
    ]

    options = []
    # Add priority providers first
    for key in priority_order:
        if key in AI_PROVIDERS_CONFIG:
            options.append(AI_PROVIDERS_CONFIG[key]["name"])

    # Add remaining providers
    for key in AI_PROVIDERS_CONFIG:
        if key not in priority_order:
            options.append(AI_PROVIDERS_CONFIG[key]["name"])

    return options


def get_provider_key_from_name(display_name: str) -> str:
    """Get provider key from display name"""
    for key, config in AI_PROVIDERS_CONFIG.items():
        if config["name"] == display_name:
            return key
    return "custom"


def get_provider_name_from_key(provider_key: str) -> str:
    """Get display name from provider key"""
    return AI_PROVIDERS_CONFIG.get(provider_key, {}).get("name", "⚙️ Custom/Local")


class BaseProviderSettingsPage(BaseSettingsSubPage):
    """Base class for AI provider settings pages"""

    # Override in child class for fixed model list (None = load from API)
    FIXED_MODELS = None
    # Override in child class to use manual input instead of dropdown
    USE_MANUAL_INPUT = False
    # Default model value when using manual input
    DEFAULT_MODEL = ""

    def __init__(
        self, parent, title, provider_key, config, on_save_callback, on_back_callback
    ):
        self.config = config
        self.provider_key = provider_key
        self.on_save_callback = on_save_callback
        self.models_list = []

        super().__init__(parent, title, on_back_callback)

        self.create_provider_content()
        self.load_config()

    def create_provider_content(self):
        """Create provider settings content"""
        # Provider Type Section
        type_section = self.create_section("Provider Type")

        type_frame = ctk.CTkFrame(type_section, fg_color="transparent")
        type_frame.pack(fill="x", padx=15, pady=(0, 12))

        ctk.CTkLabel(
            type_frame, text="Select API Provider", font=ctk.CTkFont(size=11)
        ).pack(anchor="w")

        self.provider_type_var = ctk.StringVar(value="⭐ YTClip AI")
        self.provider_dropdown = ctk.CTkOptionMenu(
            type_frame,
            values=get_provider_dropdown_options(),
            variable=self.provider_type_var,
            height=36,
            command=self._on_provider_type_changed,
        )
        self.provider_dropdown.pack(fill="x", pady=(5, 0))

        # System Message Section (optional, can be overridden by child)
        self.system_message_textbox = None

        # URL Section (only visible for custom)
        self.url_section = self.create_section("Base URL")
        self.url_section.pack_forget()  # Hidden by default

        url_frame = ctk.CTkFrame(self.url_section, fg_color="transparent")
        url_frame.pack(fill="x", padx=15, pady=(0, 12))

        ctk.CTkLabel(url_frame, text="API Base URL", font=ctk.CTkFont(size=11)).pack(
            anchor="w"
        )
        self.url_entry = ctk.CTkEntry(
            url_frame, placeholder_text="https://api.openai.com/v1", height=36
        )
        self.url_entry.pack(fill="x", pady=(5, 0))

        # API Key Section
        key_section = self.create_section("API Key")

        key_frame = ctk.CTkFrame(key_section, fg_color="transparent")
        key_frame.pack(fill="x", padx=15, pady=(0, 12))

        ctk.CTkLabel(key_frame, text="API Key", font=ctk.CTkFont(size=11)).pack(
            anchor="w"
        )
        self.key_entry = ctk.CTkEntry(
            key_frame, placeholder_text="sk-...", show="•", height=36
        )
        self.key_entry.pack(fill="x", pady=(5, 0))

        # Model Section
        self.model_section = self.create_section("Model")

        model_frame = ctk.CTkFrame(self.model_section, fg_color="transparent")
        model_frame.pack(fill="x", padx=15, pady=(0, 12))

        ctk.CTkLabel(model_frame, text="Model Name", font=ctk.CTkFont(size=11)).pack(
            anchor="w"
        )

        model_row = ctk.CTkFrame(model_frame, fg_color="transparent")
        model_row.pack(fill="x", pady=(5, 0))

        # Check if using manual input mode
        if self.USE_MANUAL_INPUT:
            # Manual input mode - use CTkEntry
            self.model_entry = ctk.CTkEntry(
                model_row, placeholder_text=f"e.g., {self.DEFAULT_MODEL}", height=36
            )
            self.model_entry.pack(fill="x")
            self.model_dropdown = None
            self.model_var = None
            self.load_btn = None
        else:
            # Dropdown mode
            self.model_var = ctk.StringVar(value="")
            self.model_entry = None

            # Check if using fixed models or load from API
            if self.FIXED_MODELS:
                # Fixed dropdown - no load button needed
                self.model_dropdown = ctk.CTkOptionMenu(
                    model_row,
                    values=self.FIXED_MODELS,
                    variable=self.model_var,
                    height=36,
                )
                self.model_dropdown.pack(fill="x")
                self.load_btn = None
            else:
                # Dynamic dropdown with load button
                self.model_dropdown = ctk.CTkOptionMenu(
                    model_row,
                    values=["-- Click Load to fetch models --"],
                    variable=self.model_var,
                    height=36,
                    width=200,
                )
                self.model_dropdown.pack(
                    side="left", fill="x", expand=True, padx=(0, 5)
                )

                self.load_btn = ctk.CTkButton(
                    model_row,
                    text="🔄 Load",
                    width=80,
                    height=36,
                    command=self.load_models,
                )
                self.load_btn.pack(side="right")

        # Actions
        actions_frame = ctk.CTkFrame(self.content, fg_color="transparent")
        actions_frame.pack(fill="x", pady=(10, 0))

        ctk.CTkButton(
            actions_frame,
            text="🔍 Validate Configuration",
            height=40,
            fg_color=Colors.BTN_PRIMARY,
            hover_color=Colors.BTN_PRIMARY_HOVER,
            command=self.validate_config,
        ).pack(fill="x", pady=(0, 10))

        # Save button
        self.create_save_button(self.save_settings)

    def _on_provider_type_changed(self, value):
        """Handle provider type dropdown change"""
        provider_key = get_provider_key_from_name(value)

        # Show URL section only for custom provider
        if provider_key == "custom":
            self.url_section.pack(
                fill="x", pady=(0, 10), after=self.content.winfo_children()[1]
            )
        else:
            self.url_section.pack_forget()

        # Pre-fill URL with provider's default base URL
        base_url = get_provider_base_url(provider_key)
        if base_url:
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, base_url)

    def _get_provider_type_key(self):
        """Get provider type key from dropdown value"""
        return get_provider_key_from_name(self.provider_type_var.get())

    def get_base_url(self):
        """Get base URL based on provider type"""
        ptype = self._get_provider_type_key()

        # For custom provider, use user-entered URL
        if ptype == "custom":
            return self.url_entry.get().strip() or "http://localhost:8000/v1"

        # For known providers, use config URL
        return get_provider_base_url(ptype) or self.url_entry.get().strip()

    def load_models(self):
        """Load available models from API"""
        if self.FIXED_MODELS:
            return  # No need to load for fixed models

        api_key = self.key_entry.get().strip()

        if not api_key:
            messagebox.showerror("Error", "Please enter API Key first")
            return

        url = self.get_base_url()
        self.load_btn.configure(state="disabled", text="Loading...")

        def do_load():
            try:
                from openai import OpenAI

                client = OpenAI(api_key=api_key, base_url=url)
                models_response = client.models.list()
                models = [m.id for m in models_response.data]
                models.sort()

                self.after(0, lambda: self._on_models_loaded(models))
            except Exception as e:
                self.after(0, lambda: self._on_models_error(str(e)))

        threading.Thread(target=do_load, daemon=True).start()

    def _on_models_loaded(self, models):
        """Handle models loaded"""
        self.load_btn.configure(state="normal", text="🔄 Load")
        self.models_list = models

        if models:
            # Update dropdown with loaded models
            self.model_dropdown.configure(values=models)
            # Keep current selection if valid, otherwise select first
            current = self.model_var.get()
            if current not in models:
                self.model_var.set(models[0])
            messagebox.showinfo("Success", f"Loaded {len(models)} models")
        else:
            messagebox.showwarning("Warning", "No models found")

    def _on_models_error(self, error):
        """Handle models load error"""
        self.load_btn.configure(state="normal", text="🔄 Load")
        messagebox.showerror("Error", f"Failed to load models:\n{error}")

    def validate_config(self):
        """Validate provider configuration"""
        api_key = self.key_entry.get().strip()
        model = self.model_var.get().strip()
        url = self.get_base_url()

        if not api_key:
            messagebox.showerror("Error", "API Key is required")
            return

        if not model or model.startswith("--"):
            messagebox.showerror("Error", "Please select a model")
            return

        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key, base_url=url)
            client.models.list()
            messagebox.showinfo(
                "Success", f"✓ Configuration valid!\n\nModel: {model}\nURL: {url}"
            )
        except Exception as e:
            messagebox.showerror("Error", f"Validation failed:\n{str(e)}")

    def load_config(self):
        """Load config into UI"""
        # Handle both ConfigManager and dict
        if hasattr(self.config, "config"):
            config_dict = self.config.config
        else:
            config_dict = self.config

        ai_providers = config_dict.get("ai_providers", {})
        provider = ai_providers.get(self.provider_key, {})

        # Determine provider type from URL
        base_url = provider.get("base_url", "")

        # Find matching provider from URL
        matched_provider = None
        for key, pconfig in AI_PROVIDERS_CONFIG.items():
            if pconfig["base_url"] and pconfig["base_url"] in base_url:
                matched_provider = key
                break

        if matched_provider:
            self.provider_type_var.set(get_provider_name_from_key(matched_provider))
            self.url_section.pack_forget()
        else:
            self.provider_type_var.set("⚙️ Custom/Local")
            self.url_section.pack(
                fill="x", pady=(0, 10), after=self.content.winfo_children()[1]
            )

        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, base_url)

        self.key_entry.delete(0, "end")
        self.key_entry.insert(0, provider.get("api_key", ""))

        saved_model = provider.get("model", "")

        # Load model based on input type
        if self.USE_MANUAL_INPUT:
            # Manual input mode
            self.model_entry.delete(0, "end")
            if saved_model:
                self.model_entry.insert(0, saved_model)
            else:
                self.model_entry.insert(0, self.DEFAULT_MODEL)
        else:
            # Dropdown mode
            if saved_model:
                if self.FIXED_MODELS:
                    # For fixed models, just set the value
                    if saved_model in self.FIXED_MODELS:
                        self.model_var.set(saved_model)
                    else:
                        self.model_var.set(self.FIXED_MODELS[0])
                else:
                    # For dynamic models, add to dropdown if not empty
                    self.model_var.set(saved_model)
                    current_values = list(self.model_dropdown.cget("values"))
                    if saved_model not in current_values:
                        self.model_dropdown.configure(
                            values=[saved_model] + current_values
                        )

        # Load system message if textbox exists
        if self.system_message_textbox:
            # Try provider-specific system_message first, fallback to root system_prompt
            system_message = provider.get("system_message", "")
            if not system_message:
                system_message = config_dict.get("system_prompt", "")
            self.system_message_textbox.delete("1.0", "end")
            self.system_message_textbox.insert("1.0", system_message)

    def save_settings(self):
        """Save settings"""
        api_key = self.key_entry.get().strip()

        # Get model from entry or dropdown
        if self.USE_MANUAL_INPUT:
            model = self.model_entry.get().strip()
            if not model:
                model = self.DEFAULT_MODEL
        else:
            model = self.model_var.get().strip()

        url = self.get_base_url()

        if not api_key:
            messagebox.showerror("Error", "API Key is required")
            return

        if not model or model.startswith("--"):
            messagebox.showerror("Error", "Please select a model")
            return

        # Handle both ConfigManager and dict
        if hasattr(self.config, "config"):
            config_dict = self.config.config
        else:
            config_dict = self.config

        # Update config
        if "ai_providers" not in config_dict:
            config_dict["ai_providers"] = {}

        provider_config = {"base_url": url, "api_key": api_key, "model": model}

        # Save system message if textbox exists
        if self.system_message_textbox:
            system_message = self.system_message_textbox.get("1.0", "end").strip()
            if system_message:
                provider_config["system_message"] = system_message

        config_dict["ai_providers"][self.provider_key] = provider_config

        # Call save callback with the full config dict (not just ai_providers)
        if self.on_save_callback:
            self.on_save_callback(config_dict)

        messagebox.showinfo("Success", f"{self.title} settings saved!")
        self.on_back()
