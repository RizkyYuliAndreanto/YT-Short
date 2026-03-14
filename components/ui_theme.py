"""
UI Theme and Design System for CONTEN CREATOR AGENT
Modern SaaS palette with bright triadic colors and optional dark mode.
"""

import tkinter as tk
import customtkinter as ctk


_UI_MODE = "light"


def _palette_light():
    return {
        "BG_PRIMARY": "#EAF1FB",
        "BG_SECONDARY": "#F3F7FD",
        "BG_TERTIARY": "#E4EDF9",
        "ACCENT_PRIMARY": "#1976D2",  # Blue
        "ACCENT_SECONDARY": "#F57C00",  # Orange
        "ACCENT_GRADIENT_START": "#1976D2",
        "ACCENT_GRADIENT_END": "#43A047",  # Green
        "SUCCESS": "#43A047",
        "WARNING": "#F9A825",
        "ERROR": "#E53935",
        "INFO": "#00ACC1",
        "TEXT_PRIMARY": "#1A2A3A",
        "TEXT_SECONDARY": "#4E6278",
        "TEXT_MUTED": "#6E8297",
        "TEXT_HIGHLIGHT": "#1976D2",
        "BORDER": "#AFC4DD",
        "BORDER_HOVER": "#1976D2",
        "CARD_BG": "#F7FAFF",
        "CARD_HOVER": "#EAF3FF",
        "BTN_PRIMARY": "#1976D2",
        "BTN_PRIMARY_HOVER": "#1565C0",
        "BTN_SECONDARY": "#43A047",
        "BTN_SECONDARY_HOVER": "#2E7D32",
        "BTN_DANGER": "#E53935",
        "BTN_DANGER_HOVER": "#C62828",
        "BTN_SUCCESS": "#F57C00",
        "BTN_SUCCESS_HOVER": "#EF6C00",
    }


def _palette_dark():
    return {
        "BG_PRIMARY": "#0E1726",
        "BG_SECONDARY": "#111E32",
        "BG_TERTIARY": "#1A2A3D",
        "ACCENT_PRIMARY": "#4EA3FF",
        "ACCENT_SECONDARY": "#FFB74D",
        "ACCENT_GRADIENT_START": "#4EA3FF",
        "ACCENT_GRADIENT_END": "#66BB6A",
        "SUCCESS": "#66BB6A",
        "WARNING": "#FFCA28",
        "ERROR": "#EF5350",
        "INFO": "#4DD0E1",
        "TEXT_PRIMARY": "#F5F9FF",
        "TEXT_SECONDARY": "#C6D5E6",
        "TEXT_MUTED": "#9CB2CA",
        "TEXT_HIGHLIGHT": "#8BC3FF",
        "BORDER": "#2D4662",
        "BORDER_HOVER": "#4EA3FF",
        "CARD_BG": "#13243A",
        "CARD_HOVER": "#1B3453",
        "BTN_PRIMARY": "#2C7EDB",
        "BTN_PRIMARY_HOVER": "#206DBF",
        "BTN_SECONDARY": "#2E7D32",
        "BTN_SECONDARY_HOVER": "#25692A",
        "BTN_DANGER": "#D64545",
        "BTN_DANGER_HOVER": "#BE3A3A",
        "BTN_SUCCESS": "#FF9800",
        "BTN_SUCCESS_HOVER": "#F57C00",
    }


def apply_theme_mode(mode: str = "light"):
    """Apply light/dark palette by mutating Colors class constants."""
    global _UI_MODE
    _UI_MODE = "dark" if str(mode).lower().startswith("dark") else "light"
    palette = _palette_dark() if _UI_MODE == "dark" else _palette_light()
    for key, value in palette.items():
        setattr(Colors, key, value)


def get_theme_mode() -> str:
    return _UI_MODE


def refresh_theme_for_widget(widget):
    """Recursively walk *widget* and its descendants, updating colours to
    match the current ``Colors`` palette.

    This is the core mechanism that keeps every already-constructed page in
    sync after ``apply_theme_mode()`` changes the palette.  It inspects
    each widget's **current** configured colour and maps it to the
    corresponding new ``Colors`` value, so it works regardless of which
    palette was active when the widget was originally created.

    Colour mapping is done by role: every colour that appeared in either
    the light or dark palette is mapped to its counterpart in the *current*
    palette.
    """
    # Build old→new maps for both palettes so we can update widgets that
    # were created under *either* mode.
    light = _palette_light()
    dark = _palette_dark()
    current = {k: getattr(Colors, k) for k in light}

    # Map any OLD value (from either palette) → new current value
    _color_map: dict[str, str] = {}
    for key in light:
        _color_map[light[key].lower()] = current[key]
        _color_map[dark[key].lower()] = current[key]

    # Supplementary legacy hex values found hardcoded across the codebase.
    # These aren't in either palette but serve similar roles and should
    # be remapped so the widget walker can update them on theme toggle.
    _legacy_mappings = {
        # Old dark-mode backgrounds → BG_PRIMARY / BG_TERTIARY
        "#1a1a1a": "BG_PRIMARY",
        "#0a0a0a": "BG_PRIMARY",
        "#1a1a2e": "BG_TERTIARY",
        "#2a2a3e": "BG_TERTIARY",
        "#3a3a3a": "BG_TERTIARY",
        "#2a2a2a": "BG_SECONDARY",
    }
    for hex_val, palette_key in _legacy_mappings.items():
        _color_map[hex_val.lower()] = current[palette_key]

    def _map(color_value):
        """Return the updated colour, or *None* if no mapping applies."""
        if not color_value or color_value == "transparent":
            return None
        if isinstance(color_value, (list, tuple)):
            # CTk sometimes returns tuple of (light, dark)
            color_value = (
                color_value[0] if isinstance(color_value, tuple) else color_value
            )
            if isinstance(color_value, (list, tuple)):
                return None
        try:
            return _color_map.get(str(color_value).lower())
        except Exception:
            return None

    def _update(w):
        try:
            # --- CTkFrame / CTkScrollableFrame ---
            if isinstance(w, ctk.CTkFrame):
                cur_fg = w.cget("fg_color")
                mapped = _map(cur_fg) if not isinstance(cur_fg, tuple) else None
                if isinstance(cur_fg, tuple):
                    # Try mapping the first element
                    mapped = _map(cur_fg[0])
                if mapped:
                    w.configure(fg_color=mapped)
                cur_border = w.cget("border_color")
                if isinstance(cur_border, tuple):
                    cur_border = cur_border[0]
                mapped_b = _map(cur_border)
                if mapped_b:
                    w.configure(border_color=mapped_b)

            # --- CTkLabel ---
            if isinstance(w, ctk.CTkLabel):
                cur_tc = w.cget("text_color")
                if isinstance(cur_tc, tuple):
                    cur_tc = cur_tc[0]
                mapped = _map(cur_tc)
                if mapped:
                    w.configure(text_color=mapped)

            # --- CTkButton ---
            if isinstance(w, ctk.CTkButton):
                for prop, cget_key in [
                    ("fg_color", "fg_color"),
                    ("hover_color", "hover_color"),
                    ("text_color", "text_color"),
                    ("border_color", "border_color"),
                ]:
                    try:
                        cur = w.cget(cget_key)
                        if isinstance(cur, tuple):
                            cur = cur[0]
                        mapped = _map(cur)
                        if mapped:
                            w.configure(**{prop: mapped})
                    except Exception:
                        pass

            # --- CTkEntry ---
            if isinstance(w, ctk.CTkEntry):
                for prop in (
                    "fg_color",
                    "text_color",
                    "border_color",
                    "placeholder_text_color",
                ):
                    try:
                        cur = w.cget(prop)
                        if isinstance(cur, tuple):
                            cur = cur[0]
                        mapped = _map(cur)
                        if mapped:
                            w.configure(**{prop: mapped})
                    except Exception:
                        pass

            # --- CTkTextbox ---
            if isinstance(w, ctk.CTkTextbox):
                for prop in ("fg_color", "text_color", "border_color"):
                    try:
                        cur = w.cget(prop)
                        if isinstance(cur, tuple):
                            cur = cur[0]
                        mapped = _map(cur)
                        if mapped:
                            w.configure(**{prop: mapped})
                    except Exception:
                        pass

            # --- CTkScrollableFrame ---
            # CTkScrollableFrame has an internal tkinter.Canvas (_parent_canvas)
            # and an inner tkinter.Frame (self) whose bg colours are set during
            # _set_appearance_mode().  When we update fg_color with a single hex
            # string (instead of a CTk tuple), the internal canvas and frame do
            # NOT automatically pick up the new colour.  We must force-sync them.
            if isinstance(w, ctk.CTkScrollableFrame):
                try:
                    # Determine the effective bg that the canvas should use.
                    # If _parent_frame.fg_color is "transparent" we look at
                    # the *page* bg (BG_PRIMARY) as fallback.
                    pf = getattr(w, "_parent_frame", None)
                    if pf is not None:
                        pf_fg = pf.cget("fg_color")
                        if isinstance(pf_fg, tuple):
                            pf_fg = pf_fg[0]
                        mapped_pf = _map(pf_fg)
                        if mapped_pf:
                            pf.configure(fg_color=mapped_pf)
                        # Resolve effective bg for canvas
                        eff_bg = mapped_pf or pf_fg
                        if eff_bg == "transparent":
                            eff_bg = current["BG_PRIMARY"]
                        # Force-update the internal tkinter Canvas
                        canvas = getattr(w, "_parent_canvas", None)
                        if canvas is not None:
                            canvas.configure(bg=eff_bg)
                        # Force-update the inner tkinter.Frame (the CTkScrollableFrame itself)
                        try:
                            tk.Frame.configure(w, bg=eff_bg)
                        except Exception:
                            pass
                except Exception:
                    pass
                # Also update scrollbar colours
                try:
                    sb = getattr(w, "_scrollbar", None)
                    if sb is not None:
                        for prop in ("button_color", "button_hover_color"):
                            try:
                                cur = sb.cget(prop)
                                if isinstance(cur, tuple):
                                    cur = cur[0]
                                mapped = _map(cur)
                                if mapped:
                                    sb.configure(**{prop: mapped})
                            except Exception:
                                pass
                except Exception:
                    pass
            elif hasattr(w, "_scrollbar") and not isinstance(w, ctk.CTkScrollableFrame):
                # Catch-all for other scrollbar-bearing widgets
                try:
                    for prop in ("button_color", "button_hover_color"):
                        try:
                            cur = w._scrollbar.cget(prop)
                            if isinstance(cur, tuple):
                                cur = cur[0]
                            mapped = _map(cur)
                            if mapped:
                                w._scrollbar.configure(**{prop: mapped})
                        except Exception:
                            pass
                except Exception:
                    pass

            # --- CTkOptionMenu / CTkComboBox ---
            if isinstance(w, (ctk.CTkOptionMenu, ctk.CTkComboBox)):
                for prop in (
                    "fg_color",
                    "button_color",
                    "button_hover_color",
                    "text_color",
                    "dropdown_fg_color",
                    "dropdown_hover_color",
                    "dropdown_text_color",
                ):
                    try:
                        cur = w.cget(prop)
                        if isinstance(cur, tuple):
                            cur = cur[0]
                        mapped = _map(cur)
                        if mapped:
                            w.configure(**{prop: mapped})
                    except Exception:
                        pass

            # --- CTkSwitch / CTkCheckBox / CTkRadioButton ---
            if isinstance(w, (ctk.CTkSwitch, ctk.CTkCheckBox, ctk.CTkRadioButton)):
                for prop in (
                    "fg_color",
                    "text_color",
                    "button_color",
                    "button_hover_color",
                    "progress_color",
                ):
                    try:
                        cur = w.cget(prop)
                        if isinstance(cur, tuple):
                            cur = cur[0]
                        mapped = _map(cur)
                        if mapped:
                            w.configure(**{prop: mapped})
                    except Exception:
                        pass

            # --- CTkProgressBar ---
            if isinstance(w, ctk.CTkProgressBar):
                for prop in ("fg_color", "progress_color", "border_color"):
                    try:
                        cur = w.cget(prop)
                        if isinstance(cur, tuple):
                            cur = cur[0]
                        mapped = _map(cur)
                        if mapped:
                            w.configure(**{prop: mapped})
                    except Exception:
                        pass

            # --- CTkSlider ---
            if isinstance(w, ctk.CTkSlider):
                for prop in (
                    "fg_color",
                    "progress_color",
                    "button_color",
                    "button_hover_color",
                ):
                    try:
                        cur = w.cget(prop)
                        if isinstance(cur, tuple):
                            cur = cur[0]
                        mapped = _map(cur)
                        if mapped:
                            w.configure(**{prop: mapped})
                    except Exception:
                        pass

        except Exception:
            pass

        # --- Plain tkinter widgets (tk.Canvas, tk.Frame, tk.Label, etc.) ---
        # These are NOT CTk widgets; they use raw Tk configure options
        # like "bg" / "background", "fg" / "foreground", "highlightbackground".
        try:
            if not isinstance(w, ctk.CTkBaseClass) and isinstance(w, tk.Widget):
                # Background
                for bg_key in ("bg", "background"):
                    try:
                        cur = w.cget(bg_key)
                        mapped = _map(cur)
                        if mapped:
                            w.configure(**{bg_key: mapped})
                            break  # bg and background are aliases
                    except (tk.TclError, Exception):
                        pass
                # Foreground
                for fg_key in ("fg", "foreground"):
                    try:
                        cur = w.cget(fg_key)
                        mapped = _map(cur)
                        if mapped:
                            w.configure(**{fg_key: mapped})
                            break
                    except (tk.TclError, Exception):
                        pass
                # Highlight border (common on Canvas)
                for hb_key in ("highlightbackground", "highlightcolor"):
                    try:
                        cur = w.cget(hb_key)
                        mapped = _map(cur)
                        if mapped:
                            w.configure(**{hb_key: mapped})
                    except (tk.TclError, Exception):
                        pass
        except Exception:
            pass

        # Recurse into children
        try:
            for child in w.winfo_children():
                _update(child)
        except Exception:
            pass

    _update(widget)


# =============================================================================
# COLOR PALETTE - Midnight Professional Theme
# =============================================================================


class Colors:
    """Color constants for the application"""

    # Primary Background Gradient
    BG_PRIMARY = "#EAF1FB"
    BG_SECONDARY = "#F3F7FD"
    BG_TERTIARY = "#E4EDF9"

    # Accent Colors
    ACCENT_PRIMARY = "#1976D2"
    ACCENT_SECONDARY = "#F57C00"
    ACCENT_GRADIENT_START = "#1976D2"
    ACCENT_GRADIENT_END = "#43A047"

    # Status Colors
    SUCCESS = "#43A047"
    WARNING = "#F9A825"
    ERROR = "#E53935"
    INFO = "#00ACC1"

    # Text Colors
    TEXT_PRIMARY = "#1A2A3A"
    TEXT_SECONDARY = "#4E6278"
    TEXT_MUTED = "#6E8297"
    TEXT_HIGHLIGHT = "#1976D2"

    # Border/Divider
    BORDER = "#AFC4DD"
    BORDER_HOVER = "#1976D2"

    # Card Colors
    CARD_BG = "#F7FAFF"
    CARD_HOVER = "#EAF3FF"

    # Button States
    BTN_PRIMARY = "#1976D2"
    BTN_PRIMARY_HOVER = "#1565C0"
    BTN_SECONDARY = "#43A047"
    BTN_SECONDARY_HOVER = "#2E7D32"
    BTN_DANGER = "#E53935"
    BTN_DANGER_HOVER = "#C62828"
    BTN_SUCCESS = "#F57C00"
    BTN_SUCCESS_HOVER = "#EF6C00"


class Fonts:
    """Font configurations"""

    @staticmethod
    def heading_xl():
        return ctk.CTkFont(family="Segoe UI Semibold", size=28, weight="bold")

    @staticmethod
    def heading_lg():
        return ctk.CTkFont(family="Segoe UI Semibold", size=22, weight="bold")

    @staticmethod
    def heading_md():
        return ctk.CTkFont(family="Segoe UI Semibold", size=16, weight="bold")

    @staticmethod
    def heading_sm():
        return ctk.CTkFont(family="Segoe UI Semibold", size=14, weight="bold")

    @staticmethod
    def body():
        return ctk.CTkFont(family="Segoe UI", size=13)

    @staticmethod
    def body_sm():
        return ctk.CTkFont(family="Segoe UI", size=11)

    @staticmethod
    def caption():
        return ctk.CTkFont(family="Segoe UI", size=10)

    @staticmethod
    def mono():
        return ctk.CTkFont(family="Consolas", size=12)


class Spacing:
    """Consistent spacing values"""

    XS = 4
    SM = 8
    MD = 16
    LG = 24
    XL = 32
    XXL = 48


class BorderRadius:
    """Border radius values"""

    SM = 8
    MD = 12
    LG = 18
    XL = 26
    ROUND = 50


# =============================================================================
# TOOLTIP COMPONENT
# =============================================================================


class ToolTip:
    """
    Create a tooltip for a given widget.
    Shows description on hover after a short delay.
    Uses a plain tkinter Toplevel to avoid CTkToplevel theme-update
    crashes when the tooltip window is destroyed during appearance mode changes.
    """

    def __init__(self, widget, text, delay=400):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.tooltip_window = None
        self.scheduled_id = None

        widget.bind("<Enter>", self.schedule_show)
        widget.bind("<Leave>", self.hide)
        widget.bind("<Button-1>", self.hide)

    def _widget_exists(self):
        """Check if the parent widget still exists and is valid."""
        try:
            return self.widget.winfo_exists()
        except Exception:
            return False

    def schedule_show(self, event=None):
        """Schedule tooltip to show after delay"""
        if not self._widget_exists():
            return
        self.scheduled_id = self.widget.after(self.delay, self.show)

    def show(self, event=None):
        """Display the tooltip"""
        if self.tooltip_window or not self._widget_exists():
            return

        try:
            # Get widget position
            x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5

            # Use plain tkinter Toplevel instead of CTkToplevel to avoid
            # the internal _revert_withdraw_after_windows_set_titlebar_color
            # callback that crashes when the window is destroyed during
            # appearance mode transitions.
            import tkinter as tk

            self.tooltip_window = tw = tk.Toplevel(self.widget)
            tw.wm_overrideredirect(True)
            tw.wm_geometry(f"+{x}+{y}")
            tw.attributes("-topmost", True)

            # Determine colors based on current theme
            bg_color = Colors.CARD_BG
            border_color = Colors.BORDER
            text_color = Colors.TEXT_SECONDARY

            # Tooltip frame with styling
            frame = ctk.CTkFrame(
                tw,
                fg_color=bg_color,
                corner_radius=8,
                border_width=1,
                border_color=border_color,
            )
            frame.pack()

            # Tooltip text
            label = ctk.CTkLabel(
                frame,
                text=self.text,
                font=Fonts.body_sm(),
                text_color=text_color,
                wraplength=250,
                padx=12,
                pady=8,
                justify="left",
            )
            label.pack()

            # Adjust position if tooltip goes off screen
            tw.update_idletasks()
            screen_width = tw.winfo_screenwidth()
            tooltip_width = tw.winfo_width()
            if x + tooltip_width > screen_width:
                x = screen_width - tooltip_width - 10
                tw.wm_geometry(f"+{x}+{y}")
        except Exception:
            # If anything goes wrong during show, clean up silently
            self.tooltip_window = None

    def hide(self, event=None):
        """Hide the tooltip"""
        try:
            if self.scheduled_id and self._widget_exists():
                self.widget.after_cancel(self.scheduled_id)
        except Exception:
            pass
        self.scheduled_id = None

        if self.tooltip_window:
            try:
                self.tooltip_window.destroy()
            except Exception:
                pass
            self.tooltip_window = None


# =============================================================================
# STYLED COMPONENTS
# =============================================================================


def create_styled_button(
    parent,
    text,
    command,
    style="primary",
    width=None,
    height=38,
    tooltip=None,
    icon=None,
):
    """Create a consistently styled button"""

    if style == "primary":
        fg = Colors.BTN_PRIMARY
        hover = Colors.BTN_PRIMARY_HOVER
        text_color = Colors.TEXT_PRIMARY
    elif style == "secondary":
        fg = Colors.BTN_SECONDARY
        hover = Colors.BTN_SECONDARY_HOVER
        text_color = Colors.TEXT_PRIMARY
    elif style == "danger":
        fg = Colors.BTN_DANGER
        hover = Colors.BTN_DANGER_HOVER
        text_color = Colors.TEXT_PRIMARY
    elif style == "success":
        fg = Colors.BTN_SUCCESS
        hover = Colors.BTN_SUCCESS_HOVER
        text_color = Colors.BG_PRIMARY
    elif style == "ghost":
        fg = "transparent"
        hover = Colors.CARD_HOVER
        text_color = Colors.TEXT_SECONDARY
    else:
        fg = Colors.BTN_PRIMARY
        hover = Colors.BTN_PRIMARY_HOVER
        text_color = Colors.TEXT_PRIMARY

    btn_text = f"{icon} {text}" if icon else text

    btn = ctk.CTkButton(
        parent,
        text=btn_text,
        command=command,
        fg_color=fg,
        hover_color=hover,
        text_color=text_color,
        font=Fonts.body(),
        corner_radius=BorderRadius.MD,
        border_width=1,
        border_color=Colors.BORDER,
        height=height,
        width=width,
    )

    if tooltip:
        ToolTip(btn, tooltip)
    else:
        ToolTip(btn, f"Klik untuk {str(text).strip().lower()}")

    return btn


def create_styled_card(parent, title=None, icon=None, description=None):
    """Create a styled card frame"""
    card = ctk.CTkFrame(
        parent,
        fg_color=Colors.CARD_BG,
        corner_radius=BorderRadius.LG,
        border_width=2,
        border_color=Colors.BORDER,
    )

    if title:
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.MD, pady=(Spacing.MD, Spacing.SM))

        title_text = f"{icon}  {title}" if icon else title
        ctk.CTkLabel(
            header,
            text=title_text,
            font=Fonts.heading_sm(),
            text_color=Colors.TEXT_PRIMARY,
        ).pack(anchor="w")

        if description:
            ctk.CTkLabel(
                header,
                text=description,
                font=Fonts.body_sm(),
                text_color=Colors.TEXT_SECONDARY,
            ).pack(anchor="w", pady=(4, 0))

    return card


def create_styled_input(parent, placeholder="", tooltip=None, width=None):
    """Create a styled input field"""
    entry = ctk.CTkEntry(
        parent,
        placeholder_text=placeholder,
        fg_color=Colors.BG_SECONDARY,
        border_color=Colors.BORDER,
        border_width=1,
        text_color=Colors.TEXT_PRIMARY,
        font=Fonts.body(),
        corner_radius=BorderRadius.SM,
        height=40,
        width=width,
    )

    if tooltip:
        ToolTip(entry, tooltip)
    elif placeholder:
        ToolTip(entry, f"Input: {placeholder}")

    return entry


def create_styled_label(parent, text, style="body", color=None):
    """Create a styled label"""
    if style == "heading_xl":
        font = Fonts.heading_xl()
        default_color = Colors.TEXT_PRIMARY
    elif style == "heading_lg":
        font = Fonts.heading_lg()
        default_color = Colors.TEXT_PRIMARY
    elif style == "heading_md":
        font = Fonts.heading_md()
        default_color = Colors.TEXT_PRIMARY
    elif style == "heading_sm":
        font = Fonts.heading_sm()
        default_color = Colors.TEXT_PRIMARY
    elif style == "caption":
        font = Fonts.caption()
        default_color = Colors.TEXT_MUTED
    elif style == "muted":
        font = Fonts.body_sm()
        default_color = Colors.TEXT_SECONDARY
    else:
        font = Fonts.body()
        default_color = Colors.TEXT_PRIMARY

    return ctk.CTkLabel(parent, text=text, font=font, text_color=color or default_color)


def create_section_divider(parent):
    """Create a horizontal divider line"""
    divider = ctk.CTkFrame(parent, fg_color=Colors.BORDER, height=1)
    return divider


def enable_auto_tooltips_for_ctk():
    """Attach automatic tooltips to common interactive CTk widgets.

    This keeps existing feature logic intact while improving UX discoverability.
    """
    if getattr(ctk, "_cca_auto_tooltip_enabled", False):
        return
    ctk._cca_auto_tooltip_enabled = True

    def _bind_default_tooltip(widget, default_text):
        try:
            if getattr(widget, "_cca_has_tooltip", False):
                return
            ToolTip(widget, default_text)
            widget._cca_has_tooltip = True
        except Exception:
            pass

    # Patch CTkButton
    _orig_btn_init = ctk.CTkButton.__init__

    def _btn_init(self, *args, **kwargs):
        text = kwargs.get("text", "Action")
        _orig_btn_init(self, *args, **kwargs)
        _bind_default_tooltip(self, f"Tombol: {text}")

    ctk.CTkButton.__init__ = _btn_init

    # Patch CTkEntry
    _orig_entry_init = ctk.CTkEntry.__init__

    def _entry_init(self, *args, **kwargs):
        placeholder = kwargs.get("placeholder_text", "Masukkan nilai")
        _orig_entry_init(self, *args, **kwargs)
        _bind_default_tooltip(self, f"Input field: {placeholder}")

    ctk.CTkEntry.__init__ = _entry_init

    # Patch CTkComboBox
    _orig_combo_init = ctk.CTkComboBox.__init__

    def _combo_init(self, *args, **kwargs):
        _orig_combo_init(self, *args, **kwargs)
        _bind_default_tooltip(self, "Dropdown: pilih salah satu opsi")

    ctk.CTkComboBox.__init__ = _combo_init

    # Patch CTkSwitch
    _orig_switch_init = ctk.CTkSwitch.__init__

    def _switch_init(self, *args, **kwargs):
        text = kwargs.get("text", "Sakelar")
        _orig_switch_init(self, *args, **kwargs)
        _bind_default_tooltip(self, f"Switch: {text}")

    ctk.CTkSwitch.__init__ = _switch_init

    # Patch CTkRadioButton
    _orig_radio_init = ctk.CTkRadioButton.__init__

    def _radio_init(self, *args, **kwargs):
        text = kwargs.get("text", "Pilihan")
        _orig_radio_init(self, *args, **kwargs)
        _bind_default_tooltip(self, f"Opsi: {text}")

    ctk.CTkRadioButton.__init__ = _radio_init
