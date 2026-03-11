"""
In-app video preview player using OpenCV + CTkImage.
Lightweight frame-by-frame player rendered directly in CustomTkinter.
"""

import os
import threading
import time
import cv2
from pathlib import Path
from PIL import Image
from typing import Optional, Callable

# Force FFmpeg inside OpenCV to use single thread — prevents
# "Assertion fctx->async_lock failed" crash on short clips
os.environ["OPENCV_FFMPEG_THREADS"] = "1"

import customtkinter as ctk
from components.ui_theme import Colors, Fonts, Spacing, BorderRadius, create_styled_button


class VideoPreviewPlayer(ctk.CTkFrame):
    """
    Compact in-app video player.
    Uses OpenCV to read frames and renders them in a CTkLabel.
    Supports play/pause/stop, seek bar, and close callback.
    """
    
    def __init__(self, parent, video_path: str, 
                 width: int = 360, height: int = 640,
                 on_close: Optional[Callable] = None,
                 autoplay: bool = True):
        super().__init__(parent, fg_color=Colors.BG_PRIMARY, 
                         corner_radius=BorderRadius.LG,
                         border_width=2, border_color=Colors.ACCENT_PRIMARY)
        
        self.video_path = video_path
        self.display_w = width
        self.display_h = height
        self.on_close = on_close
        
        # Playback state
        self._playing = False
        self._stop_flag = False
        self._destroyed = False
        self._cap: Optional[cv2.VideoCapture] = None
        self._cap_lock = threading.Lock()
        self._fps = 30.0
        self._total_frames = 0
        self._current_frame = 0
        self._duration = 0.0
        self._ctk_image = None  # Keep reference to prevent GC
        
        self._build_ui()
        self._load_video()
        
        if autoplay:
            self.after(200, self.play)
    
    def _build_ui(self):
        # Top bar with close button
        top_bar = ctk.CTkFrame(self, fg_color="transparent", height=28)
        top_bar.pack(fill="x", padx=4, pady=(4, 0))
        top_bar.pack_propagate(False)
        
        ctk.CTkLabel(top_bar, text="▶ Preview", font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=Colors.TEXT_MUTED).pack(side="left", padx=4)
        
        close_btn = ctk.CTkButton(top_bar, text="✕", width=24, height=24,
            fg_color="transparent", hover_color=Colors.ERROR,
            text_color=Colors.TEXT_MUTED, font=ctk.CTkFont(size=12),
            command=self._close)
        close_btn.pack(side="right")
        
        # Video display
        self.video_label = ctk.CTkLabel(self, text="", 
            width=self.display_w, height=self.display_h,
            fg_color="#000000", corner_radius=4)
        self.video_label.pack(padx=4, pady=2)
        
        # Controls bar
        ctrl = ctk.CTkFrame(self, fg_color="transparent", height=36)
        ctrl.pack(fill="x", padx=4, pady=(2, 4))
        ctrl.pack_propagate(False)
        
        self.play_btn = ctk.CTkButton(ctrl, text="⏸", width=32, height=28,
            fg_color=Colors.ACCENT_PRIMARY, hover_color=Colors.BTN_PRIMARY_HOVER,
            font=ctk.CTkFont(size=14), command=self._toggle_play)
        self.play_btn.pack(side="left", padx=(0, 4))
        
        # Seek slider
        self.seek_var = ctk.DoubleVar(value=0)
        self.seek_slider = ctk.CTkSlider(ctrl, from_=0, to=1, variable=self.seek_var,
            height=12, fg_color=Colors.BG_SECONDARY,
            progress_color=Colors.ACCENT_PRIMARY, button_color=Colors.TEXT_PRIMARY,
            button_length=8, command=self._on_seek)
        self.seek_slider.pack(side="left", fill="x", expand=True, padx=4)
        
        self.time_label = ctk.CTkLabel(ctrl, text="0:00 / 0:00", 
            font=ctk.CTkFont(size=9), text_color=Colors.TEXT_MUTED, width=70)
        self.time_label.pack(side="right")
    
    def _load_video(self):
        """Open video and read metadata with single-thread decoding."""
        try:
            cap = cv2.VideoCapture(self.video_path, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                return
            
            # Force single-thread decoding to prevent async_lock crash
            cap.set(cv2.CAP_PROP_N_THREADS, 1)
            
            with self._cap_lock:
                self._cap = cap
            
            self._fps = self._cap.get(cv2.CAP_PROP_FPS) or 30.0
            self._total_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self._duration = self._total_frames / self._fps if self._fps > 0 else 0
            
            # Show first frame
            ret, frame = self._cap.read()
            if ret:
                self._show_frame(frame)
                self._current_frame = 1
        except Exception:
            pass
    
    def _show_frame(self, frame):
        """Convert OpenCV frame to CTkImage and display."""
        if self._destroyed:
            return
        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil = Image.fromarray(rgb)
            
            # Fit within display size maintaining aspect ratio
            orig_w, orig_h = pil.size
            ratio = min(self.display_w / orig_w, self.display_h / orig_h)
            new_w = max(1, int(orig_w * ratio))
            new_h = max(1, int(orig_h * ratio))
            pil = pil.resize((new_w, new_h), Image.Resampling.LANCZOS)
            
            self._ctk_image = ctk.CTkImage(light_image=pil, dark_image=pil, size=(new_w, new_h))
            self.video_label.configure(image=self._ctk_image, width=self.display_w, height=self.display_h)
        except Exception:
            pass
    
    def play(self):
        """Start playback."""
        if self._playing or self._destroyed:
            return
        with self._cap_lock:
            if not self._cap:
                return
        self._playing = True
        self._stop_flag = False
        try:
            self.play_btn.configure(text="⏸")
        except Exception:
            return
        threading.Thread(target=self._playback_loop, daemon=True).start()
    
    def pause(self):
        """Pause playback."""
        self._playing = False
        self.play_btn.configure(text="▶")
    
    def _toggle_play(self):
        if self._playing:
            self.pause()
        else:
            self.play()
    
    def _playback_loop(self):
        """Background thread: read frames at target FPS."""
        target_delay = 1.0 / min(self._fps, 30)  # Cap at 30fps for UI smoothness
        
        while self._playing and not self._stop_flag and not self._destroyed:
            t0 = time.perf_counter()
            
            with self._cap_lock:
                cap = self._cap
            if not cap or not cap.isOpened():
                break
            
            try:
                ret, frame = cap.read()
            except Exception:
                break
            
            if not ret:
                # Loop back to start
                try:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    self._current_frame = 0
                    ret, frame = cap.read()
                except Exception:
                    break
                if not ret:
                    break
            
            try:
                self._current_frame = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
            except Exception:
                break
            
            # Update UI from main thread — guard against destroyed widget
            if self._destroyed or self._stop_flag:
                break
            try:
                self.after(0, lambda f=frame: self._show_frame(f))
                self.after(0, self._update_time_display)
            except (RuntimeError, Exception):
                break
            
            # Maintain target FPS
            elapsed = time.perf_counter() - t0
            sleep_time = target_delay - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
        
        self._playing = False
        if not self._destroyed:
            try:
                self.after(0, lambda: self.play_btn.configure(text="▶") if not self._destroyed else None)
            except Exception:
                pass
    
    def _update_time_display(self):
        """Update seek bar and time label."""
        if self._destroyed:
            return
        try:
            if self._total_frames > 0:
                pos = self._current_frame / self._total_frames
                self.seek_var.set(pos)
            
            cur_sec = self._current_frame / self._fps if self._fps > 0 else 0
            self.time_label.configure(
                text=f"{self._fmt_time(cur_sec)} / {self._fmt_time(self._duration)}")
        except Exception:
            pass
    
    def _on_seek(self, value):
        """Handle seek slider drag."""
        with self._cap_lock:
            cap = self._cap
        if not cap:
            return
        try:
            target_frame = int(value * self._total_frames)
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            self._current_frame = target_frame
            
            if not self._playing:
                ret, frame = cap.read()
                if ret:
                    self._show_frame(frame)
                    self._update_time_display()
        except Exception:
            pass
    
    def _fmt_time(self, seconds: float) -> str:
        m = int(seconds) // 60
        s = int(seconds) % 60
        return f"{m}:{s:02d}"
    
    def _close(self):
        """Stop and cleanup."""
        self._destroyed = True
        self._stop_flag = True
        self._playing = False
        # Give playback thread time to exit
        time.sleep(0.05)
        with self._cap_lock:
            if self._cap:
                try:
                    self._cap.release()
                except Exception:
                    pass
                self._cap = None
        cb = self.on_close
        try:
            super().destroy()
        except Exception:
            pass
        if cb:
            try:
                cb()
            except Exception:
                pass
    
    def destroy(self):
        if self._destroyed:
            try:
                super().destroy()
            except Exception:
                pass
            return
        self._destroyed = True
        self._stop_flag = True
        self._playing = False
        # Give playback thread time to exit
        time.sleep(0.05)
        with self._cap_lock:
            if self._cap:
                try:
                    self._cap.release()
                except Exception:
                    pass
                self._cap = None
        try:
            super().destroy()
        except Exception:
            pass


def extract_thumbnail(video_path: str, time_offset: float = 0.5,
                      size: tuple = (160, 90)) -> Optional[ctk.CTkImage]:
    """
    Extract a single thumbnail frame from a video at the given time offset (0-1 ratio).
    Returns a CTkImage or None.
    """
    try:
        cap = cv2.VideoCapture(video_path, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            return None
        
        cap.set(cv2.CAP_PROP_N_THREADS, 1)
        
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        target = int(total * time_offset)
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(1, target))
        
        ret, frame = cap.read()
        cap.release()
        
        if not ret:
            return None
        
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)
        pil.thumbnail(size, Image.Resampling.LANCZOS)
        
        return ctk.CTkImage(light_image=pil, dark_image=pil, size=pil.size)
    except Exception:
        return None
