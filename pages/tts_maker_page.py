"""
TTS Maker Page - Text-to-Speech Maker
Generate high-quality Indonesian voice audio from text.
Designed for content dubbing (YouTube Shorts, TikTok, Reels).

Features:
- Text input with word/char counter
- Voice selection (Ardi/Gadis)
- Speed, pitch, volume controls
- Real-time duration estimation
- Audio preview and download (in-app player)
- Enhancement options for natural voice
"""

import os
import sys
import threading
import tempfile
import subprocess
import customtkinter as ctk
from tkinter import messagebox, filedialog
from pathlib import Path
from typing import Optional

from components.ui_theme import (
    Colors, Fonts, Spacing, BorderRadius,
    ToolTip, create_styled_button, create_styled_label
)
from components.page_layout import PageHeader, PageFooter

# Windows subprocess flags
SUBPROCESS_FLAGS = 0
if sys.platform == "win32":
    SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW


class InAppAudioPlayer:
    """
    In-app audio player using ffplay (from ffmpeg).
    Plays audio without opening external media player.
    Falls back to system default player if ffplay is not available.
    """

    def __init__(self, ffmpeg_path: str = "ffmpeg"):
        self.ffmpeg_path = ffmpeg_path
        self._process: Optional[subprocess.Popen] = None
        self._is_playing = False
        self._ffplay_path: Optional[str] = None
        self._ffplay_available: Optional[bool] = None

    def _get_ffplay_path(self) -> Optional[str]:
        """Get ffplay path from ffmpeg path, with validation"""
        if self._ffplay_path is not None:
            return self._ffplay_path

        # Try to find ffplay based on ffmpeg path
        if self.ffmpeg_path and self.ffmpeg_path != "ffmpeg":
            ffmpeg_dir = os.path.dirname(self.ffmpeg_path)
            ffplay = os.path.join(ffmpeg_dir, "ffplay.exe" if os.name == "nt" else "ffplay")
            if os.path.exists(ffplay):
                self._ffplay_path = ffplay
                return ffplay

        # Try system PATH
        try:
            # Check if ffplay is in PATH
            result = subprocess.run(
                ["ffplay", "-version"],
                capture_output=True,
                creationflags=SUBPROCESS_FLAGS,
                timeout=5
            )
            if result.returncode == 0:
                self._ffplay_path = "ffplay"
                return "ffplay"
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            pass

        # ffplay not found
        self._ffplay_path = None
        return None

    def is_ffplay_available(self) -> bool:
        """Check if ffplay is available on the system"""
        if self._ffplay_available is not None:
            return self._ffplay_available

        self._ffplay_available = self._get_ffplay_path() is not None
        return self._ffplay_available

    def play(self, audio_path: str, on_complete: callable = None) -> bool:
        """
        Play audio file using ffplay, with fallback to system player.

        Args:
            audio_path: Path to audio file
            on_complete: Optional callback when playback completes

        Returns:
            True if playback started successfully
        """
        if not os.path.exists(audio_path):
            print(f"Audio file not found: {audio_path}")
            return False

        # Stop any existing playback
        self.stop()

        # Try ffplay first
        ffplay = self._get_ffplay_path()
        if ffplay:
            success = self._play_with_ffplay(audio_path, ffplay, on_complete)
            if success:
                return True

        # Fallback: use system default player (Windows)
        if os.name == "nt":
            return self._play_with_system_player(audio_path, on_complete)

        print("No audio player available")
        return False

    def _play_with_ffplay(self, audio_path: str, ffplay: str, on_complete: callable = None) -> bool:
        """Play using ffplay"""
        try:
            # ffplay command:
            # -nodisp: no video display window
            # -autoexit: exit when done
            # -loglevel warning: show warnings/errors only
            cmd = [
                ffplay,
                "-nodisp",
                "-autoexit",
                "-nostats",
                "-loglevel", "warning",
                audio_path
            ]

            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=SUBPROCESS_FLAGS
            )

            # Quick check if process started successfully
            # Give it a moment to fail if it's going to
            import time
            time.sleep(0.1)

            if self._process.poll() is not None:
                # Process already exited, probably an error
                print("ffplay exited immediately during startup")
                return False

            self._is_playing = True

            # Monitor playback completion in background
            if on_complete:
                def wait_for_complete():
                    if self._process:
                        self._process.wait()
                    self._is_playing = False
                    on_complete()

                threading.Thread(target=wait_for_complete, daemon=True).start()

            return True

        except FileNotFoundError:
            print(f"ffplay not found at: {ffplay}")
            return False
        except Exception as e:
            print(f"ffplay error: {e}")
            self._is_playing = False
            return False

    def _play_with_system_player(self, audio_path: str, on_complete: callable = None) -> bool:
        """Fallback: play using Windows Media Player or system default"""
        try:
            # Use PowerShell to play audio in background on Windows
            # This uses Windows Media Player COM object
            ps_script = f'''
            Add-Type -AssemblyName presentationCore
            $player = New-Object System.Windows.Media.MediaPlayer
            $player.Open("{audio_path.replace(chr(92), chr(92)+chr(92))}")
            $player.Play()
            Start-Sleep -Milliseconds 500
            while ($player.Position -lt $player.NaturalDuration.TimeSpan) {{
                Start-Sleep -Milliseconds 100
            }}
            $player.Close()
            '''

            self._process = subprocess.Popen(
                ["powershell", "-Command", ps_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=SUBPROCESS_FLAGS
            )
            self._is_playing = True

            if on_complete:
                def wait_for_complete():
                    if self._process:
                        self._process.wait()
                    self._is_playing = False
                    on_complete()

                threading.Thread(target=wait_for_complete, daemon=True).start()

            return True

        except Exception as e:
            print(f"System player error: {e}")
            return False

    def stop(self):
        """Stop audio playback"""
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=1)
            except:
                try:
                    self._process.kill()
                except:
                    pass
            self._process = None
        self._is_playing = False

    @property
    def is_playing(self) -> bool:
        """Check if audio is currently playing"""
        if self._process:
            # Check if process is still running
            poll = self._process.poll()
            if poll is not None:
                self._is_playing = False
                self._process = None
        return self._is_playing


class TTSMakerPage(ctk.CTkFrame):
    """Text-to-Speech Maker Page"""

    def __init__(self, parent, app, config):
        super().__init__(parent, fg_color=Colors.BG_PRIMARY)
        self.app = app
        self.config = config

        # State
        self.is_processing = False
        self.current_audio_path = None
        self.engine = None
        self._audio_process = None
        self._audio_player: Optional[InAppAudioPlayer] = None
        self._download_folder: Optional[str] = None  # Custom download folder

        # Initialize engine
        self._init_engine()

        # Initialize audio player
        self._init_audio_player()

        # Create UI
        self.create_ui()

    def _init_engine(self):
        """Initialize TTS engine"""
        try:
            from tts_maker_core import TTSMakerEngine, TTSConfig
            from utils.helpers import get_ffmpeg_path

            ffmpeg_path = get_ffmpeg_path()
            output_dir = self.config.get("output_dir", "output")
            tts_output_dir = os.path.join(output_dir, "tts_audio")

            self.engine = TTSMakerEngine(
                ffmpeg_path=ffmpeg_path,
                output_dir=tts_output_dir
            )
        except Exception as e:
            print(f"TTS Engine init error: {e}")
            self.engine = None

    def _init_audio_player(self):
        """Initialize the in-app audio player"""
        try:
            from utils.helpers import get_ffmpeg_path
            ffmpeg_path = get_ffmpeg_path()
            self._audio_player = InAppAudioPlayer(ffmpeg_path)
        except Exception as e:
            print(f"Audio player init error: {e}")
            self._audio_player = InAppAudioPlayer()

    def create_ui(self):
        """Create the TTS Maker UI"""
        # Header
        header = PageHeader(
            self, self,
            show_nav_buttons=False,
            show_back_button=True,
            page_title="Text-to-Speech Maker"
        )
        header.pack(fill="x", padx=20, pady=(15, 10))

        # Main content - scrollable
        self.main_content = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.main_content.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        # Title section
        self._create_title_section()

        # Text input section
        self._create_text_section()

        # Voice settings section
        self._create_voice_section()

        # Enhancement section
        self._create_enhancement_section()

        # Action buttons
        self._create_action_section()

        # Result section (hidden initially)
        self._create_result_section()

        # Footer
        footer = PageFooter(self, self)
        footer.pack(fill="x", padx=20, pady=(0, 15))

    def _create_title_section(self):
        """Create title/intro section"""
        title_frame = ctk.CTkFrame(self.main_content, fg_color="transparent")
        title_frame.pack(fill="x", pady=(0, Spacing.MD))

        # Icon and title
        header_row = ctk.CTkFrame(title_frame, fg_color="transparent")
        header_row.pack(fill="x")

        ctk.CTkLabel(
            header_row,
            text="🎙️",
            font=ctk.CTkFont(size=32)
        ).pack(side="left", padx=(0, Spacing.SM))

        title_content = ctk.CTkFrame(header_row, fg_color="transparent")
        title_content.pack(side="left", fill="x", expand=True)

        create_styled_label(
            title_content,
            "Text-to-Speech Maker",
            style="heading_md"
        ).pack(anchor="w")

        create_styled_label(
            title_content,
            "Ubah teks menjadi suara natural untuk dubbing konten Shorts.",
            style="muted"
        ).pack(anchor="w")

    def _create_text_section(self):
        """Create text input section"""
        section = ctk.CTkFrame(
            self.main_content,
            fg_color=Colors.CARD_BG,
            corner_radius=BorderRadius.MD,
            border_width=1,
            border_color=Colors.BORDER
        )
        section.pack(fill="x", pady=(0, Spacing.MD))

        # Header
        header = ctk.CTkFrame(section, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.MD, pady=(Spacing.MD, Spacing.SM))

        create_styled_label(
            header,
            "📝 Script / Naskah",
            style="heading_sm"
        ).pack(side="left")

        # Stats display
        self.stats_label = ctk.CTkLabel(
            header,
            text="0 kata | 0 karakter | ~0 detik",
            font=Fonts.caption(),
            text_color=Colors.TEXT_MUTED
        )
        self.stats_label.pack(side="right")

        # Text input
        self.text_input = ctk.CTkTextbox(
            section,
            height=200,
            fg_color=Colors.BG_SECONDARY,
            border_color=Colors.BORDER,
            border_width=1,
            text_color=Colors.TEXT_PRIMARY,
            font=Fonts.body(),
            corner_radius=BorderRadius.SM,
            wrap="word"
        )
        self.text_input.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.SM))
        self.text_input.bind("<KeyRelease>", self._on_text_change)

        # Placeholder
        placeholder = (
            "Ketik atau paste naskah dubbing di sini...\n\n"
            "Contoh:\n"
            "Halo semuanya! Selamat datang di channel kami. "
            "Hari ini kita akan membahas tips produktivitas yang sangat bermanfaat. "
            "Jangan lupa subscribe dan like video ini ya!"
        )
        self.text_input.insert("1.0", placeholder)
        self.text_input.configure(text_color=Colors.TEXT_MUTED)
        self._placeholder_active = True
        self.text_input.bind("<FocusIn>", self._on_text_focus_in)
        self.text_input.bind("<FocusOut>", self._on_text_focus_out)

        # Duration estimation display
        duration_frame = ctk.CTkFrame(section, fg_color=Colors.BG_SECONDARY, corner_radius=BorderRadius.SM)
        duration_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        duration_inner = ctk.CTkFrame(duration_frame, fg_color="transparent")
        duration_inner.pack(fill="x", padx=Spacing.MD, pady=Spacing.SM)

        ctk.CTkLabel(
            duration_inner,
            text="⏱️ Estimasi Durasi Audio:",
            font=Fonts.body_sm(),
            text_color=Colors.TEXT_SECONDARY
        ).pack(side="left")

        self.duration_label = ctk.CTkLabel(
            duration_inner,
            text="0 detik",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=Colors.ACCENT_PRIMARY
        )
        self.duration_label.pack(side="right")

        # Tips
        tips_frame = ctk.CTkFrame(section, fg_color="transparent")
        tips_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        ctk.CTkLabel(
            tips_frame,
            text="💡 Tips: Target 130-150 kata per menit untuk pace natural. Gunakan tanda baca untuk jeda.",
            font=Fonts.caption(),
            text_color=Colors.TEXT_MUTED,
            wraplength=500,
            justify="left"
        ).pack(anchor="w")

    def _create_voice_section(self):
        """Create voice settings section"""
        section = ctk.CTkFrame(
            self.main_content,
            fg_color=Colors.CARD_BG,
            corner_radius=BorderRadius.MD,
            border_width=1,
            border_color=Colors.BORDER
        )
        section.pack(fill="x", pady=(0, Spacing.MD))

        # Header
        ctk.CTkLabel(
            section,
            text="🎤 Pengaturan Suara",
            font=Fonts.heading_sm(),
            text_color=Colors.TEXT_PRIMARY
        ).pack(anchor="w", padx=Spacing.MD, pady=(Spacing.MD, Spacing.SM))

        # Voice selector row
        voice_row = ctk.CTkFrame(section, fg_color="transparent")
        voice_row.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.SM))

        # Voice selector
        voice_frame = ctk.CTkFrame(voice_row, fg_color="transparent")
        voice_frame.pack(side="left", padx=(0, Spacing.LG))

        ctk.CTkLabel(
            voice_frame,
            text="Suara:",
            font=Fonts.body_sm(),
            text_color=Colors.TEXT_SECONDARY
        ).pack(anchor="w")

        self.voice_var = ctk.StringVar(value="Ardi (Pria)")
        voice_options = ["Ardi (Pria)", "Gadis (Wanita)"]
        self.voice_menu = ctk.CTkOptionMenu(
            voice_frame,
            values=voice_options,
            variable=self.voice_var,
            height=36,
            width=180,
            fg_color=Colors.BG_SECONDARY,
            button_color=Colors.BTN_PRIMARY,
            button_hover_color=Colors.BTN_PRIMARY_HOVER,
            dropdown_fg_color=Colors.CARD_BG,
            dropdown_hover_color=Colors.CARD_HOVER,
            text_color=Colors.TEXT_PRIMARY,
            font=Fonts.body()
        )
        self.voice_menu.pack(anchor="w", pady=(4, 0))

        # Preview button
        preview_frame = ctk.CTkFrame(voice_row, fg_color="transparent")
        preview_frame.pack(side="left")

        ctk.CTkLabel(preview_frame, text=" ", font=Fonts.body_sm()).pack(anchor="w")  # Spacer

        self.preview_btn = create_styled_button(
            preview_frame,
            "🔊 Preview Suara",
            command=self._preview_voice,
            style="secondary",
            width=130,
            height=36,
            tooltip="Dengarkan contoh suara yang dipilih"
        )
        self.preview_btn.pack(anchor="w", pady=(4, 0))

        # Sliders row
        sliders_row = ctk.CTkFrame(section, fg_color="transparent")
        sliders_row.pack(fill="x", padx=Spacing.MD, pady=(Spacing.SM, Spacing.MD))

        # Speed slider
        speed_frame = ctk.CTkFrame(sliders_row, fg_color="transparent")
        speed_frame.pack(side="left", fill="x", expand=True, padx=(0, Spacing.MD))

        speed_header = ctk.CTkFrame(speed_frame, fg_color="transparent")
        speed_header.pack(fill="x")

        ctk.CTkLabel(
            speed_header,
            text="🚀 Kecepatan:",
            font=Fonts.body_sm(),
            text_color=Colors.TEXT_SECONDARY
        ).pack(side="left")

        self.speed_value_label = ctk.CTkLabel(
            speed_header,
            text="+0%",
            font=Fonts.body_sm(),
            text_color=Colors.ACCENT_PRIMARY
        )
        self.speed_value_label.pack(side="right")

        self.speed_var = ctk.DoubleVar(value=0)
        self.speed_slider = ctk.CTkSlider(
            speed_frame,
            from_=-50,
            to=50,
            variable=self.speed_var,
            command=self._on_speed_change,
            fg_color=Colors.BG_SECONDARY,
            progress_color=Colors.ACCENT_PRIMARY,
            button_color=Colors.BTN_PRIMARY,
            button_hover_color=Colors.BTN_PRIMARY_HOVER
        )
        self.speed_slider.pack(fill="x", pady=(4, 0))

        ctk.CTkLabel(
            speed_frame,
            text="Lambat ← Normal → Cepat",
            font=Fonts.caption(),
            text_color=Colors.TEXT_MUTED
        ).pack()

        # Pitch slider
        pitch_frame = ctk.CTkFrame(sliders_row, fg_color="transparent")
        pitch_frame.pack(side="left", fill="x", expand=True, padx=(0, Spacing.MD))

        pitch_header = ctk.CTkFrame(pitch_frame, fg_color="transparent")
        pitch_header.pack(fill="x")

        ctk.CTkLabel(
            pitch_header,
            text="🎵 Pitch:",
            font=Fonts.body_sm(),
            text_color=Colors.TEXT_SECONDARY
        ).pack(side="left")

        self.pitch_value_label = ctk.CTkLabel(
            pitch_header,
            text="+0Hz",
            font=Fonts.body_sm(),
            text_color=Colors.ACCENT_PRIMARY
        )
        self.pitch_value_label.pack(side="right")

        self.pitch_var = ctk.DoubleVar(value=0)
        self.pitch_slider = ctk.CTkSlider(
            pitch_frame,
            from_=-20,
            to=20,
            variable=self.pitch_var,
            command=self._on_pitch_change,
            fg_color=Colors.BG_SECONDARY,
            progress_color=Colors.ACCENT_PRIMARY,
            button_color=Colors.BTN_PRIMARY,
            button_hover_color=Colors.BTN_PRIMARY_HOVER
        )
        self.pitch_slider.pack(fill="x", pady=(4, 0))

        ctk.CTkLabel(
            pitch_frame,
            text="Rendah ← Normal → Tinggi",
            font=Fonts.caption(),
            text_color=Colors.TEXT_MUTED
        ).pack()

        # Volume slider
        volume_frame = ctk.CTkFrame(sliders_row, fg_color="transparent")
        volume_frame.pack(side="left", fill="x", expand=True)

        volume_header = ctk.CTkFrame(volume_frame, fg_color="transparent")
        volume_header.pack(fill="x")

        ctk.CTkLabel(
            volume_header,
            text="🔉 Volume:",
            font=Fonts.body_sm(),
            text_color=Colors.TEXT_SECONDARY
        ).pack(side="left")

        self.volume_value_label = ctk.CTkLabel(
            volume_header,
            text="+0%",
            font=Fonts.body_sm(),
            text_color=Colors.ACCENT_PRIMARY
        )
        self.volume_value_label.pack(side="right")

        self.volume_var = ctk.DoubleVar(value=0)
        self.volume_slider = ctk.CTkSlider(
            volume_frame,
            from_=-50,
            to=50,
            variable=self.volume_var,
            command=self._on_volume_change,
            fg_color=Colors.BG_SECONDARY,
            progress_color=Colors.ACCENT_PRIMARY,
            button_color=Colors.BTN_PRIMARY,
            button_hover_color=Colors.BTN_PRIMARY_HOVER
        )
        self.volume_slider.pack(fill="x", pady=(4, 0))

        ctk.CTkLabel(
            volume_frame,
            text="Pelan ← Normal → Keras",
            font=Fonts.caption(),
            text_color=Colors.TEXT_MUTED
        ).pack()

    def _create_enhancement_section(self):
        """Create audio enhancement section"""
        section = ctk.CTkFrame(
            self.main_content,
            fg_color=Colors.CARD_BG,
            corner_radius=BorderRadius.MD,
            border_width=1,
            border_color=Colors.BORDER
        )
        section.pack(fill="x", pady=(0, Spacing.MD))

        # Header
        ctk.CTkLabel(
            section,
            text="✨ Enhancement (Optimasi Suara)",
            font=Fonts.heading_sm(),
            text_color=Colors.TEXT_PRIMARY
        ).pack(anchor="w", padx=Spacing.MD, pady=(Spacing.MD, Spacing.SM))

        # Description
        ctk.CTkLabel(
            section,
            text="Enhancement membuat suara lebih natural dan mengurangi kesan robotik.",
            font=Fonts.body_sm(),
            text_color=Colors.TEXT_SECONDARY,
            wraplength=500
        ).pack(anchor="w", padx=Spacing.MD, pady=(0, Spacing.SM))

        # Enhancement options
        options_frame = ctk.CTkFrame(section, fg_color="transparent")
        options_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        # Enable enhancement
        self.enhance_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            options_frame,
            text="🎛️ Enable Audio Enhancement",
            variable=self.enhance_var,
            fg_color=Colors.ACCENT_PRIMARY,
            hover_color=Colors.BTN_PRIMARY_HOVER,
            text_color=Colors.TEXT_PRIMARY,
            font=Fonts.body()
        ).pack(anchor="w", pady=(0, Spacing.XS))

        # Sub-options frame
        sub_options = ctk.CTkFrame(options_frame, fg_color="transparent")
        sub_options.pack(fill="x", padx=Spacing.LG)

        self.normalize_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            sub_options,
            text="📊 Normalize Volume (konsisten)",
            variable=self.normalize_var,
            fg_color=Colors.ACCENT_PRIMARY,
            hover_color=Colors.BTN_PRIMARY_HOVER,
            text_color=Colors.TEXT_SECONDARY,
            font=Fonts.body_sm()
        ).pack(anchor="w", pady=(0, 2))

        self.variation_var = ctk.BooleanVar(value=False)  # DISABLED - compand can cause audio loss
        ctk.CTkCheckBox(
            sub_options,
            text="🎭 Add Subtle Variation (lebih manusiawi)",
            variable=self.variation_var,
            fg_color=Colors.ACCENT_PRIMARY,
            hover_color=Colors.BTN_PRIMARY_HOVER,
            text_color=Colors.TEXT_SECONDARY,
            font=Fonts.body_sm()
        ).pack(anchor="w", pady=(0, 2))

        self.eq_var = ctk.BooleanVar(value=False)  # DISABLED - EQ can cause phase issues
        ctk.CTkCheckBox(
            sub_options,
            text="🔊 Voice EQ (kejelasan suara)",
            variable=self.eq_var,
            fg_color=Colors.ACCENT_PRIMARY,
            hover_color=Colors.BTN_PRIMARY_HOVER,
            text_color=Colors.TEXT_SECONDARY,
            font=Fonts.body_sm()
        ).pack(anchor="w", pady=(0, 2))

        # Pause reduction checkbox
        self.reduce_pause_var = ctk.BooleanVar(value=False)  # DISABLED - silenceremove is dangerous
        ctk.CTkCheckBox(
            sub_options,
            text="⏸️ Reduce Long Pauses (kurangi jeda panjang)",
            variable=self.reduce_pause_var,
            fg_color=Colors.ACCENT_PRIMARY,
            hover_color=Colors.BTN_PRIMARY_HOVER,
            text_color=Colors.TEXT_SECONDARY,
            font=Fonts.body_sm()
        ).pack(anchor="w", pady=(0, 2))

        # Pause duration slider
        pause_frame = ctk.CTkFrame(sub_options, fg_color="transparent")
        pause_frame.pack(fill="x", pady=(4, 0))

        pause_header = ctk.CTkFrame(pause_frame, fg_color="transparent")
        pause_header.pack(fill="x")

        ctk.CTkLabel(
            pause_header,
            text="   Max Jeda:",
            font=Fonts.caption(),
            text_color=Colors.TEXT_MUTED
        ).pack(side="left")

        self.pause_value_label = ctk.CTkLabel(
            pause_header,
            text="0.4s",
            font=Fonts.caption(),
            text_color=Colors.ACCENT_PRIMARY
        )
        self.pause_value_label.pack(side="right")

        self.pause_var = ctk.DoubleVar(value=0.4)
        self.pause_slider = ctk.CTkSlider(
            pause_frame,
            from_=0.2,
            to=0.8,
            variable=self.pause_var,
            command=self._on_pause_change,
            fg_color=Colors.BG_SECONDARY,
            progress_color=Colors.ACCENT_PRIMARY,
            button_color=Colors.BTN_PRIMARY,
            button_hover_color=Colors.BTN_PRIMARY_HOVER,
            width=200
        )
        self.pause_slider.pack(anchor="w", padx=(12, 0))

        ctk.CTkLabel(
            pause_frame,
            text="   0.2s (cepat) ← → 0.8s (natural)",
            font=Fonts.caption(),
            text_color=Colors.TEXT_MUTED
        ).pack(anchor="w")

        # Info about anti-detection
        info_frame = ctk.CTkFrame(section, fg_color=Colors.BG_SECONDARY, corner_radius=BorderRadius.SM)
        info_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        ctk.CTkLabel(
            info_frame,
            text="💡 Enhancement membantu audio tidak terdeteksi sebagai konten otomatis oleh platform seperti YouTube/TikTok.",
            font=Fonts.caption(),
            text_color=Colors.TEXT_MUTED,
            wraplength=450,
            justify="left"
        ).pack(padx=Spacing.SM, pady=Spacing.SM)

    def _create_action_section(self):
        """Create action buttons section"""
        section = ctk.CTkFrame(self.main_content, fg_color="transparent")
        section.pack(fill="x", pady=(0, Spacing.MD))

        # Progress bar (hidden initially)
        self.progress_frame = ctk.CTkFrame(section, fg_color="transparent")
        self.progress_frame.pack(fill="x", pady=(0, Spacing.SM))
        self.progress_frame.pack_forget()

        self.progress_bar = ctk.CTkProgressBar(
            self.progress_frame,
            fg_color=Colors.BG_SECONDARY,
            progress_color=Colors.ACCENT_PRIMARY
        )
        self.progress_bar.pack(fill="x")
        self.progress_bar.set(0)

        self.progress_label = ctk.CTkLabel(
            self.progress_frame,
            text="",
            font=Fonts.caption(),
            text_color=Colors.TEXT_MUTED
        )
        self.progress_label.pack(pady=(Spacing.XS, 0))

        # Buttons row
        btn_frame = ctk.CTkFrame(section, fg_color="transparent")
        btn_frame.pack(fill="x")

        self.generate_btn = create_styled_button(
            btn_frame,
            "🎙️ Generate Audio",
            command=self._generate_audio,
            style="primary",
            width=200,
            height=50,
            tooltip="Generate audio dari teks"
        )
        self.generate_btn.pack(side="left", padx=(0, Spacing.SM))

        self.reset_btn = create_styled_button(
            btn_frame,
            "🔄 Reset",
            command=self._reset_all,
            style="ghost",
            width=100,
            height=50,
            tooltip="Reset semua pengaturan"
        )
        self.reset_btn.pack(side="right")

    def _create_result_section(self):
        """Create result/output section"""
        self.result_section = ctk.CTkFrame(
            self.main_content,
            fg_color=Colors.CARD_BG,
            corner_radius=BorderRadius.MD,
            border_width=2,
            border_color=Colors.SUCCESS
        )
        self.result_section.pack(fill="x", pady=(0, Spacing.MD))
        self.result_section.pack_forget()  # Hidden initially

        # Header
        header = ctk.CTkFrame(self.result_section, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.MD, pady=Spacing.MD)

        ctk.CTkLabel(
            header,
            text="✅ Audio Generated!",
            font=Fonts.heading_sm(),
            text_color=Colors.SUCCESS
        ).pack(side="left")

        self.result_duration_label = ctk.CTkLabel(
            header,
            text="Durasi: 0s",
            font=Fonts.body(),
            text_color=Colors.TEXT_SECONDARY
        )
        self.result_duration_label.pack(side="right")

        # Playback buttons row
        playback_row = ctk.CTkFrame(self.result_section, fg_color="transparent")
        playback_row.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.SM))

        self.play_btn = create_styled_button(
            playback_row,
            "▶️ Play Audio",
            command=self._play_audio,
            style="secondary",
            width=140,
            height=38,
            tooltip="Putar audio yang dihasilkan"
        )
        self.play_btn.pack(side="left", padx=(0, Spacing.SM))

        self.stop_btn = create_styled_button(
            playback_row,
            "⏹️ Stop",
            command=self._stop_audio,
            style="ghost",
            width=80,
            height=38,
            tooltip="Hentikan pemutaran"
        )
        self.stop_btn.pack(side="left")

        # Download section
        download_frame = ctk.CTkFrame(self.result_section, fg_color=Colors.BG_SECONDARY, corner_radius=BorderRadius.SM)
        download_frame.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

        # Download header
        download_header = ctk.CTkFrame(download_frame, fg_color="transparent")
        download_header.pack(fill="x", padx=Spacing.SM, pady=(Spacing.SM, Spacing.XS))

        ctk.CTkLabel(
            download_header,
            text="📥 Download Options",
            font=Fonts.body_sm(),
            text_color=Colors.TEXT_PRIMARY
        ).pack(side="left")

        # Download buttons row
        download_btn_row = ctk.CTkFrame(download_frame, fg_color="transparent")
        download_btn_row.pack(fill="x", padx=Spacing.SM, pady=(0, Spacing.SM))

        self.save_as_btn = create_styled_button(
            download_btn_row,
            "💾 Save As...",
            command=self._save_audio_as,
            style="success",
            width=120,
            height=36,
            tooltip="Pilih lokasi dan nama file untuk menyimpan"
        )
        self.save_as_btn.pack(side="left", padx=(0, Spacing.SM))

        self.quick_save_btn = create_styled_button(
            download_btn_row,
            "⚡ Quick Save",
            command=self._quick_save_audio,
            style="primary",
            width=120,
            height=36,
            tooltip="Simpan cepat ke folder terakhir"
        )
        self.quick_save_btn.pack(side="left", padx=(0, Spacing.SM))

        self.set_folder_btn = create_styled_button(
            download_btn_row,
            "📂 Set Folder",
            command=self._set_download_folder,
            style="ghost",
            width=110,
            height=36,
            tooltip="Pilih folder default untuk download"
        )
        self.set_folder_btn.pack(side="left", padx=(0, Spacing.SM))

        self.open_folder_btn = create_styled_button(
            download_btn_row,
            "📂 Open",
            command=self._open_output_folder,
            style="ghost",
            width=80,
            height=36,
            tooltip="Buka folder output"
        )
        self.open_folder_btn.pack(side="right")

        # Current download folder display
        self.download_folder_label = ctk.CTkLabel(
            download_frame,
            text="📁 Folder: (default)",
            font=Fonts.caption(),
            text_color=Colors.TEXT_MUTED,
            anchor="w"
        )
        self.download_folder_label.pack(fill="x", padx=Spacing.SM, pady=(0, Spacing.SM))
        self._update_download_folder_label()

        # File path display
        self.file_path_label = ctk.CTkLabel(
            self.result_section,
            text="",
            font=Fonts.caption(),
            text_color=Colors.TEXT_MUTED,
            wraplength=500
        )
        self.file_path_label.pack(padx=Spacing.MD, pady=(0, Spacing.MD))

    # ============ Event Handlers ============

    def _on_text_focus_in(self, event=None):
        """Handle text input focus in"""
        if self._placeholder_active:
            self.text_input.delete("1.0", "end")
            self.text_input.configure(text_color=Colors.TEXT_PRIMARY)
            self._placeholder_active = False

    def _on_text_focus_out(self, event=None):
        """Handle text input focus out"""
        text = self.text_input.get("1.0", "end-1c").strip()
        if not text:
            self._placeholder_active = True
            self.text_input.configure(text_color=Colors.TEXT_MUTED)
            placeholder = (
                "Ketik atau paste naskah dubbing di sini...\n\n"
                "Contoh:\n"
                "Halo semuanya! Selamat datang di channel kami. "
                "Hari ini kita akan membahas tips produktivitas yang sangat bermanfaat. "
                "Jangan lupa subscribe dan like video ini ya!"
            )
            self.text_input.insert("1.0", placeholder)

    def _on_text_change(self, event=None):
        """Handle text change - update stats"""
        if self._placeholder_active:
            return

        text = self.text_input.get("1.0", "end-1c").strip()
        words = len(text.split()) if text else 0
        chars = len(text)

        # Estimate duration
        rate = self.speed_var.get()
        duration = 0.0
        if self.engine and text:
            duration = self.engine.estimate_duration(text, rate)

        # Update stats
        self.stats_label.configure(
            text=f"{words} kata | {chars} karakter | ~{duration:.0f} detik"
        )
        self.duration_label.configure(text=f"{duration:.1f} detik")

    def _on_speed_change(self, value):
        """Handle speed slider change"""
        val = int(float(value))
        sign = "+" if val >= 0 else ""
        self.speed_value_label.configure(text=f"{sign}{val}%")
        self._on_text_change()  # Update duration estimate

    def _on_pitch_change(self, value):
        """Handle pitch slider change"""
        val = int(float(value))
        sign = "+" if val >= 0 else ""
        self.pitch_value_label.configure(text=f"{sign}{val}Hz")

    def _on_volume_change(self, value):
        """Handle volume slider change"""
        val = int(float(value))
        sign = "+" if val >= 0 else ""
        self.volume_value_label.configure(text=f"{sign}{val}%")

    def _on_pause_change(self, value):
        """Handle pause duration slider change"""
        val = float(value)
        self.pause_value_label.configure(text=f"{val:.1f}s")

    def _get_voice_id(self) -> str:
        """Get voice ID from selection"""
        voice_selection = self.voice_var.get()
        if "Gadis" in voice_selection:
            return "id-ID-GadisNeural"
        return "id-ID-ArdiNeural"

    def _preview_voice(self):
        """Preview selected voice using in-app player"""
        if self.is_processing:
            return

        # Stop any existing playback
        if self._audio_player:
            self._audio_player.stop()

        self.is_processing = True
        self.preview_btn.configure(state="disabled", text="🔊 Playing...")

        def preview():
            try:
                from tts_maker_core import TTSMakerEngine, TTSConfig

                # Create temp engine
                temp_dir = tempfile.gettempdir()
                engine = TTSMakerEngine(output_dir=temp_dir)

                config = TTSConfig(
                    voice_id=self._get_voice_id(),
                    rate=self.speed_var.get(),
                    pitch=self.pitch_var.get(),
                    volume=self.volume_var.get(),
                    enable_enhancement=False  # Quick preview without enhancement
                )

                sample_text = "Halo semuanya! Ini adalah contoh suara yang akan digunakan untuk dubbing."

                self.after(0, lambda: self.preview_btn.configure(text="🔄 Generating..."))

                result = engine.generate_sync(
                    text=sample_text,
                    config=config,
                    output_filename="preview.mp3"
                )

                if result.success:
                    # Play audio using in-app player
                    self.after(0, lambda: self.preview_btn.configure(text="🔊 Playing..."))

                    def on_playback_complete():
                        self.is_processing = False
                        self.after(0, lambda: self.preview_btn.configure(state="normal", text="🔊 Preview Suara"))

                    if self._audio_player:
                        success = self._audio_player.play(result.audio_path, on_complete=on_playback_complete)
                        if not success:
                            self.after(0, lambda: messagebox.showerror("Error", "Gagal memutar audio. Pastikan ffplay tersedia."))
                            on_playback_complete()
                    else:
                        self.after(0, lambda: messagebox.showerror("Error", "Audio player tidak tersedia."))
                        on_playback_complete()
                else:
                    self.after(0, lambda: messagebox.showerror("Error", f"Preview failed: {result.error}"))
                    self.is_processing = False
                    self.after(0, lambda: self.preview_btn.configure(state="normal", text="🔊 Preview Suara"))

            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", f"Preview failed: {e}"))
                self.is_processing = False
                self.after(0, lambda: self.preview_btn.configure(state="normal", text="🔊 Preview Suara"))

        threading.Thread(target=preview, daemon=True).start()

    def _generate_audio(self):
        """Generate TTS audio"""
        # Get text
        if self._placeholder_active:
            messagebox.showwarning("Warning", "Silakan masukkan teks terlebih dahulu!")
            return

        text = self.text_input.get("1.0", "end-1c").strip()
        if not text:
            messagebox.showwarning("Warning", "Teks tidak boleh kosong!")
            return

        if self.is_processing:
            return

        if not self.engine:
            messagebox.showerror("Error", "TTS Engine tidak tersedia!")
            return

        self.is_processing = True
        self.generate_btn.configure(state="disabled", text="🔄 Generating...")
        self.progress_frame.pack(fill="x", pady=(0, Spacing.SM))
        self.result_section.pack_forget()

        def generate():
            try:
                from tts_maker_core import TTSConfig

                config = TTSConfig(
                    voice_id=self._get_voice_id(),
                    rate=self.speed_var.get(),
                    pitch=self.pitch_var.get(),
                    volume=self.volume_var.get(),
                    enable_enhancement=self.enhance_var.get(),
                    normalize_audio=self.normalize_var.get(),
                    add_subtle_variation=self.variation_var.get(),
                    equalize_voice=self.eq_var.get(),
                    reduce_long_pauses=self.reduce_pause_var.get(),
                    max_pause_duration=self.pause_var.get(),
                    normalize_punctuation=True,
                    # Keep ending fix enabled to avoid abrupt EOS cutoff.
                    fix_abrupt_ending=True,
                    add_trailing_silence=0.25,
                    fade_out_duration=0.12
                )

                def progress_callback(msg):
                    self.after(0, lambda: self._update_progress(msg))

                result = self.engine.generate_sync(
                    text=text,
                    config=config,
                    progress_callback=progress_callback
                )

                if result.success:
                    self.current_audio_path = result.audio_path
                    self.after(0, lambda: self._on_generation_complete(result))
                else:
                    self.after(0, lambda: messagebox.showerror("Error", f"Generation failed: {result.error}"))

            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", f"Generation failed: {e}"))
            finally:
                self.is_processing = False
                self.after(0, lambda: self.generate_btn.configure(state="normal", text="🎙️ Generate Audio"))

        threading.Thread(target=generate, daemon=True).start()

    def _update_progress(self, msg: str):
        """Update progress display"""
        self.progress_label.configure(text=msg)
        # Animate progress bar
        current = self.progress_bar.get()
        if current < 0.9:
            self.progress_bar.set(current + 0.1)

    def _on_generation_complete(self, result):
        """Handle generation complete"""
        self.progress_bar.set(1.0)
        self.progress_label.configure(text="✅ Complete!")

        # Update result section
        self.result_duration_label.configure(text=f"Durasi: {result.duration:.1f}s")
        self.file_path_label.configure(text=f"📁 {result.audio_path}")

        # Show result section
        self.result_section.pack(fill="x", pady=(0, Spacing.MD))

        # Hide progress after short delay
        self.after(1000, lambda: self.progress_frame.pack_forget())

    def _play_audio(self):
        """Play generated audio using in-app player"""
        if not self.current_audio_path or not os.path.exists(self.current_audio_path):
            messagebox.showwarning("Warning", "Audio tidak ditemukan!")
            return

        # Stop any existing playback first
        self._stop_audio()

        try:
            if self._audio_player:
                # Update button state
                self.play_btn.configure(state="disabled", text="🔊 Playing...")

                def on_playback_complete():
                    self.after(0, lambda: self.play_btn.configure(state="normal", text="▶️ Play Audio"))

                success = self._audio_player.play(self.current_audio_path, on_complete=on_playback_complete)
                if not success:
                    # Show detailed error
                    if not self._audio_player.is_ffplay_available():
                        messagebox.showerror(
                            "Error",
                            "Audio player tidak tersedia.\n\n"
                            "ffplay tidak ditemukan. Pastikan:\n"
                            "1. FFmpeg sudah terinstall\n"
                            "2. Path FFmpeg sudah benar di pengaturan\n"
                            "3. Folder FFmpeg mengandung ffplay.exe"
                        )
                    else:
                        messagebox.showerror("Error", "Gagal memutar audio. Cek console untuk detail error.")
                    self.play_btn.configure(state="normal", text="▶️ Play Audio")
            else:
                messagebox.showerror("Error", "Audio player tidak tersedia.")
        except Exception as e:
            messagebox.showerror("Error", f"Cannot play audio: {e}")
            self.play_btn.configure(state="normal", text="▶️ Play Audio")

    def _stop_audio(self):
        """Stop playing audio"""
        if self._audio_player:
            self._audio_player.stop()
        # Also stop legacy process if any
        if self._audio_process:
            try:
                self._audio_process.terminate()
            except:
                pass
            self._audio_process = None
        # Reset button state
        try:
            self.play_btn.configure(state="normal", text="▶️ Play Audio")
        except:
            pass

    def _download_audio(self):
        """Download/save audio to custom location (legacy method)"""
        self._save_audio_as()

    def _save_audio_as(self):
        """Save audio to custom location with file dialog"""
        if not self.current_audio_path or not os.path.exists(self.current_audio_path):
            messagebox.showwarning("Warning", "Audio tidak ditemukan!")
            return

        # Use custom folder as initial directory if set
        initial_dir = self._download_folder if self._download_folder else None

        # Ask for save location
        filename = os.path.basename(self.current_audio_path)
        save_path = filedialog.asksaveasfilename(
            defaultextension=".mp3",
            filetypes=[("MP3 Audio", "*.mp3"), ("WAV Audio", "*.wav"), ("All files", "*.*")],
            initialfile=filename,
            initialdir=initial_dir,
            title="Save Audio As"
        )

        if save_path:
            try:
                import shutil
                shutil.copy2(self.current_audio_path, save_path)
                # Update download folder to the selected directory
                self._download_folder = os.path.dirname(save_path)
                self._update_download_folder_label()
                messagebox.showinfo("Success", f"Audio saved to:\n{save_path}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save: {e}")

    def _quick_save_audio(self):
        """Quick save audio to the default/last used folder"""
        if not self.current_audio_path or not os.path.exists(self.current_audio_path):
            messagebox.showwarning("Warning", "Audio tidak ditemukan!")
            return

        # Determine save folder
        if self._download_folder and os.path.isdir(self._download_folder):
            save_folder = self._download_folder
        else:
            # Use default output folder
            save_folder = self.engine.output_dir if self.engine else "output/tts_audio"
            if not os.path.exists(save_folder):
                os.makedirs(save_folder, exist_ok=True)

        try:
            import shutil
            from datetime import datetime

            # Generate unique filename with timestamp
            base_name = os.path.splitext(os.path.basename(self.current_audio_path))[0]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            new_filename = f"{base_name}_{timestamp}.mp3"
            save_path = os.path.join(save_folder, new_filename)

            shutil.copy2(self.current_audio_path, save_path)
            messagebox.showinfo("Success", f"Audio saved to:\n{save_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save: {e}")

    def _set_download_folder(self):
        """Set default download folder"""
        # Use current folder as initial if set
        initial_dir = self._download_folder if self._download_folder else None

        folder = filedialog.askdirectory(
            title="Select Download Folder",
            initialdir=initial_dir
        )

        if folder:
            self._download_folder = folder
            self._update_download_folder_label()
            messagebox.showinfo("Success", f"Download folder set to:\n{folder}")

    def _update_download_folder_label(self):
        """Update download folder label display"""
        try:
            if self._download_folder:
                # Truncate long paths for display
                display_path = self._download_folder
                if len(display_path) > 50:
                    display_path = "..." + display_path[-47:]
                self.download_folder_label.configure(text=f"📁 Folder: {display_path}")
            else:
                default_folder = self.engine.output_dir if self.engine else "output/tts_audio"
                if len(default_folder) > 50:
                    default_folder = "..." + default_folder[-47:]
                self.download_folder_label.configure(text=f"📁 Folder: {default_folder} (default)")
        except Exception:
            pass  # Label might not exist yet during initialization

    def _open_output_folder(self):
        """Open output folder"""
        if self.current_audio_path:
            folder = os.path.dirname(self.current_audio_path)
        else:
            folder = self.engine.output_dir if self.engine else "output/tts_audio"

        try:
            if os.name == "nt":
                os.startfile(folder)
            else:
                import subprocess
                subprocess.run(["xdg-open", folder])
        except Exception as e:
            messagebox.showerror("Error", f"Cannot open folder: {e}")

    def _reset_all(self):
        """Reset all settings to default"""
        # Stop any playing audio
        self._stop_audio()

        # Reset sliders
        self.speed_var.set(0)
        self.pitch_var.set(0)
        self.volume_var.set(0)
        self._on_speed_change(0)
        self._on_pitch_change(0)
        self._on_volume_change(0)

        # Reset voice
        self.voice_var.set("Ardi (Pria)")

        # Reset enhancement
        self.enhance_var.set(True)
        self.normalize_var.set(True)
        self.variation_var.set(False)  # DISABLED by default for safety
        self.eq_var.set(False)  # DISABLED by default for safety
        self.reduce_pause_var.set(False)  # DISABLED by default for safety
        self.pause_var.set(0.4)
        self._on_pause_change(0.4)

        # Clear text
        self.text_input.delete("1.0", "end")
        self._placeholder_active = False
        self._on_text_focus_out()

        # Hide result section
        self.result_section.pack_forget()
        self.progress_frame.pack_forget()

        # Clear current audio
        self.current_audio_path = None

    # ============ Navigation ============

    def show_page(self, page_name):
        """Delegate to parent app"""
        try:
            parent = self.master
            while parent and not hasattr(parent, "show_page"):
                parent = parent.master
            if parent and hasattr(parent, "show_page"):
                parent.show_page(page_name)
        except:
            pass

    def open_discord(self):
        """Open Discord"""
        import webbrowser
        webbrowser.open("https://s.id/ytsdiscord")

    def open_github(self):
        """Open GitHub"""
        import webbrowser
        webbrowser.open("https://github.com/jipraks/yt-short-clipper")
