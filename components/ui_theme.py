"""
UI Theme and Design System for YT Short Clipper
Modern, professional color palette with consistent styling
"""

import customtkinter as ctk

# =============================================================================
# COLOR PALETTE - Midnight Professional Theme
# =============================================================================

class Colors:
    """Color constants for the application"""
    
    # Primary Background Gradient
    BG_PRIMARY = "#0f0f1a"      # Deep midnight blue
    BG_SECONDARY = "#1a1a2e"    # Slightly lighter navy
    BG_TERTIARY = "#16213e"     # Card background
    
    # Accent Colors  
    ACCENT_PRIMARY = "#4361ee"   # Electric blue (main accent)
    ACCENT_SECONDARY = "#7209b7" # Royal purple
    ACCENT_GRADIENT_START = "#4361ee"
    ACCENT_GRADIENT_END = "#4cc9f0"
    
    # Status Colors
    SUCCESS = "#06d6a0"          # Mint green
    WARNING = "#ffd166"          # Warm yellow
    ERROR = "#ef476f"            # Soft coral red
    INFO = "#118ab2"             # Ocean blue
    
    # Text Colors
    TEXT_PRIMARY = "#edf2f4"     # Soft white
    TEXT_SECONDARY = "#8d99ae"   # Muted gray-blue
    TEXT_MUTED = "#6c757d"       # Dark gray
    TEXT_HIGHLIGHT = "#4cc9f0"   # Cyan highlight
    
    # Border/Divider
    BORDER = "#2d3142"           # Subtle border
    BORDER_HOVER = "#4361ee"     # Accent on hover
    
    # Card Colors
    CARD_BG = "#1a1a2e"          # Card background
    CARD_HOVER = "#252550"       # Card hover state
    
    # Button States
    BTN_PRIMARY = "#4361ee"      # Primary button
    BTN_PRIMARY_HOVER = "#5a7cf7"
    BTN_SECONDARY = "#2d3142"    # Secondary button
    BTN_SECONDARY_HOVER = "#3d4159"
    BTN_DANGER = "#ef476f"
    BTN_DANGER_HOVER = "#ff6b8a"
    BTN_SUCCESS = "#06d6a0"
    BTN_SUCCESS_HOVER = "#20e8b4"


class Fonts:
    """Font configurations"""
    
    @staticmethod
    def heading_xl():
        return ctk.CTkFont(family="Segoe UI", size=28, weight="bold")
    
    @staticmethod
    def heading_lg():
        return ctk.CTkFont(family="Segoe UI", size=22, weight="bold")
    
    @staticmethod
    def heading_md():
        return ctk.CTkFont(family="Segoe UI", size=16, weight="bold")
    
    @staticmethod
    def heading_sm():
        return ctk.CTkFont(family="Segoe UI", size=14, weight="bold")
    
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
    SM = 6
    MD = 10
    LG = 16
    XL = 24
    ROUND = 50


# =============================================================================
# TOOLTIP COMPONENT
# =============================================================================

class ToolTip:
    """
    Create a tooltip for a given widget.
    Shows description on hover after a short delay.
    """
    
    def __init__(self, widget, text, delay=400):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.tooltip_window = None
        self.scheduled_id = None
        
        widget.bind('<Enter>', self.schedule_show)
        widget.bind('<Leave>', self.hide)
        widget.bind('<Button-1>', self.hide)
    
    def schedule_show(self, event=None):
        """Schedule tooltip to show after delay"""
        self.scheduled_id = self.widget.after(self.delay, self.show)
    
    def show(self, event=None):
        """Display the tooltip"""
        if self.tooltip_window:
            return
        
        # Get widget position
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        
        # Create tooltip window
        self.tooltip_window = tw = ctk.CTkToplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes("-topmost", True)
        
        # Tooltip frame with styling
        frame = ctk.CTkFrame(tw, fg_color=Colors.CARD_BG, corner_radius=8,
            border_width=1, border_color=Colors.BORDER)
        frame.pack()
        
        # Tooltip text
        label = ctk.CTkLabel(frame, text=self.text, font=Fonts.body_sm(),
            text_color=Colors.TEXT_SECONDARY, wraplength=250,
            padx=12, pady=8, justify="left")
        label.pack()
        
        # Adjust position if tooltip goes off screen
        tw.update_idletasks()
        screen_width = tw.winfo_screenwidth()
        tooltip_width = tw.winfo_width()
        if x + tooltip_width > screen_width:
            x = screen_width - tooltip_width - 10
            tw.wm_geometry(f"+{x}+{y}")
    
    def hide(self, event=None):
        """Hide the tooltip"""
        if self.scheduled_id:
            self.widget.after_cancel(self.scheduled_id)
            self.scheduled_id = None
        
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None


# =============================================================================
# STYLED COMPONENTS
# =============================================================================

def create_styled_button(parent, text, command, style="primary", width=None, 
                         height=38, tooltip=None, icon=None):
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
        hover = Colors.BTN_SECONDARY
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
        height=height,
        width=width
    )
    
    if tooltip:
        ToolTip(btn, tooltip)
    
    return btn


def create_styled_card(parent, title=None, icon=None, description=None):
    """Create a styled card frame"""
    card = ctk.CTkFrame(
        parent,
        fg_color=Colors.CARD_BG,
        corner_radius=BorderRadius.LG,
        border_width=1,
        border_color=Colors.BORDER
    )
    
    if title:
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.MD, pady=(Spacing.MD, Spacing.SM))
        
        title_text = f"{icon}  {title}" if icon else title
        ctk.CTkLabel(header, text=title_text, font=Fonts.heading_sm(),
            text_color=Colors.TEXT_PRIMARY).pack(anchor="w")
        
        if description:
            ctk.CTkLabel(header, text=description, font=Fonts.body_sm(),
                text_color=Colors.TEXT_SECONDARY).pack(anchor="w", pady=(4, 0))
    
    return card


def create_styled_input(parent, placeholder="", tooltip=None, width=None):
    """Create a styled input field"""
    entry = ctk.CTkEntry(
        parent,
        placeholder_text=placeholder,
        fg_color=Colors.BG_SECONDARY,
        border_color=Colors.BORDER,
        text_color=Colors.TEXT_PRIMARY,
        font=Fonts.body(),
        corner_radius=BorderRadius.SM,
        height=40,
        width=width
    )
    
    if tooltip:
        ToolTip(entry, tooltip)
    
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
    
    return ctk.CTkLabel(
        parent,
        text=text,
        font=font,
        text_color=color or default_color
    )


def create_section_divider(parent):
    """Create a horizontal divider line"""
    divider = ctk.CTkFrame(parent, fg_color=Colors.BORDER, height=1)
    return divider
