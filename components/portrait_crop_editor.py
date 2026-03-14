"""
Manual portrait crop editor for Clip+Dub.
Provides video preview, draggable 9:16 crop box, and keyframe-based tracking.
"""

import os
import threading
import time
from typing import Callable, Dict, List, Optional

import cv2
import customtkinter as ctk
from PIL import Image, ImageTk

from components.ui_theme import Colors, Fonts, Spacing, BorderRadius


class PortraitCropEditor(ctk.CTkFrame):
    """Interactive portrait crop editor with optional keyframe tracking."""

    def __init__(self, parent, width: int = 640, height: int = 360,
                 on_change: Optional[Callable[[Dict], None]] = None):
        super().__init__(parent, fg_color=Colors.CARD_BG,
                         corner_radius=BorderRadius.MD,
                         border_width=1, border_color=Colors.BORDER)

        self.display_w = width
        self.display_h = height
        self.on_change = on_change

        self.video_path: Optional[str] = None
        self._cap: Optional[cv2.VideoCapture] = None
        self._cap_lock = threading.Lock()

        self._fps = 30.0
        self._total_frames = 0
        self._duration = 0.0
        self._frame_idx = 0
        self._playing = False
        self._stop_flag = False

        self.base_center_x = 0.5
        self.keyframes: List[Dict] = []

        self._dragging = False
        self._photo = None
        self._frame_rgb = None
        self._canvas_img_id = None

        self._build_ui()

    def _build_ui(self):
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=Spacing.SM, pady=(Spacing.SM, 0))

        ctk.CTkLabel(top, text="Manual Portrait Crop Studio",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=Colors.TEXT_PRIMARY).pack(side="left")

        self.mode_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(top, text="Record keyframe saat drag",
                        variable=self.mode_var,
                        font=Fonts.body_sm(),
                        fg_color=Colors.ACCENT_PRIMARY,
                        border_color=Colors.BORDER).pack(side="right")

        self.canvas = ctk.CTkCanvas(self, width=self.display_w, height=self.display_h,
                                    bg="#000000", highlightthickness=0, bd=0)
        self.canvas.pack(fill="x", padx=Spacing.SM, pady=(Spacing.SM, 4))

        self.canvas.bind("<ButtonPress-1>", self._on_mouse_down)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)

        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.pack(fill="x", padx=Spacing.SM, pady=(0, Spacing.SM))

        self.play_btn = ctk.CTkButton(controls, text="▶", width=34, height=30,
                                      fg_color=Colors.ACCENT_PRIMARY,
                                      hover_color=Colors.BTN_PRIMARY_HOVER,
                                      command=self.toggle_play)
        self.play_btn.pack(side="left", padx=(0, 6))

        self.seek_var = ctk.DoubleVar(value=0.0)
        self.seek_slider = ctk.CTkSlider(controls, from_=0, to=1, variable=self.seek_var,
                                         command=self._on_seek,
                                         fg_color=Colors.BG_SECONDARY,
                                         progress_color=Colors.ACCENT_PRIMARY,
                                         button_color=Colors.TEXT_PRIMARY,
                                         button_length=10)
        self.seek_slider.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.time_label = ctk.CTkLabel(controls, text="0:00 / 0:00",
                                       font=Fonts.body_sm(),
                                       text_color=Colors.TEXT_MUTED, width=90)
        self.time_label.pack(side="left")

        row2 = ctk.CTkFrame(self, fg_color="transparent")
        row2.pack(fill="x", padx=Spacing.SM, pady=(0, Spacing.SM))

        ctk.CTkLabel(row2, text="Posisi Crop X:",
                     font=Fonts.body_sm(), text_color=Colors.TEXT_MUTED).pack(side="left")

        self.center_var = ctk.DoubleVar(value=0.5)
        self.center_slider = ctk.CTkSlider(row2, from_=0.1, to=0.9,
                                           variable=self.center_var,
                                           command=self._on_center_slider,
                                           fg_color=Colors.BG_SECONDARY,
                                           progress_color=Colors.ACCENT_PRIMARY,
                                           button_color=Colors.ACCENT_PRIMARY,
                                           button_length=10)
        self.center_slider.pack(side="left", fill="x", expand=True, padx=6)

        self.center_label = ctk.CTkLabel(row2, text="x=0.50",
                                         font=Fonts.body_sm(),
                                         text_color=Colors.TEXT_MUTED, width=56)
        self.center_label.pack(side="left")

        row3 = ctk.CTkFrame(self, fg_color="transparent")
        row3.pack(fill="x", padx=Spacing.SM, pady=(0, Spacing.SM))

        self.add_kf_btn = ctk.CTkButton(row3, text="+ Keyframe @ waktu ini",
                                        width=150, height=28,
                                        fg_color=Colors.BG_SECONDARY,
                                        hover_color=Colors.CARD_HOVER,
                                        command=self._add_current_keyframe)
        self.add_kf_btn.pack(side="left", padx=(0, 6))

        self.del_kf_btn = ctk.CTkButton(row3, text="Hapus Keyframe terdekat",
                                        width=150, height=28,
                                        fg_color=Colors.BG_SECONDARY,
                                        hover_color=Colors.CARD_HOVER,
                                        command=self._delete_nearest_keyframe)
        self.del_kf_btn.pack(side="left", padx=(0, 6))

        self.reset_btn = ctk.CTkButton(row3, text="Reset",
                                       width=70, height=28,
                                       fg_color=Colors.BG_SECONDARY,
                                       hover_color=Colors.ERROR,
                                       command=self.reset_crop)
        self.reset_btn.pack(side="left")

        self.kf_label = ctk.CTkLabel(self, text="Keyframes: 0",
                                     font=Fonts.body_sm(), text_color=Colors.TEXT_MUTED)
        self.kf_label.pack(anchor="w", padx=Spacing.SM, pady=(0, Spacing.SM))

    def load_clip(self, video_path: str, crop_data: Optional[Dict] = None):
        self.stop()
        self.video_path = video_path
        self.base_center_x = 0.5
        self.keyframes = []

        if crop_data:
            self.base_center_x = float(crop_data.get("base_center_x", 0.5))
            self.keyframes = list(crop_data.get("keyframes", []))

        self.center_var.set(self.base_center_x)
        self._update_center_label(self.base_center_x)
        self._update_kf_label()

        # Disable libavcodec async-frame threading before opening the file.
        # This prevents the 'fctx->async_lock' assertion crash in libavcodec/pthread_frame.c
        # when the playback thread and the UI thread both access the same VideoCapture.
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "threads;1"
        cap = cv2.VideoCapture(video_path, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_N_THREADS, 1)
        with self._cap_lock:
            if self._cap:
                try:
                    self._cap.release()
                except Exception:
                    pass
            self._cap = cap

        self._fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        self._total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self._duration = (self._total_frames / self._fps) if self._fps > 0 else 0.0
        self._frame_idx = 0

        self._show_current_frame()
        self._emit_change()

    def get_crop_data(self) -> Dict:
        return {
            "enabled": True,
            "base_center_x": float(self.base_center_x),
            "keyframes": sorted(self.keyframes, key=lambda k: k.get("t", 0.0)),
        }

    def reset_crop(self):
        self.base_center_x = 0.5
        self.keyframes = []
        self.center_var.set(0.5)
        self._update_center_label(0.5)
        self._show_current_frame()
        self._update_kf_label()
        self._emit_change()

    def toggle_play(self):
        if self._playing:
            self.stop()
        else:
            self.play()

    def play(self):
        if self._playing:
            return
        with self._cap_lock:
            if not self._cap:
                return
        self._playing = True
        self._stop_flag = False
        self.play_btn.configure(text="⏸")
        threading.Thread(target=self._playback_loop, daemon=True).start()

    def stop(self):
        self._playing = False
        self._stop_flag = True
        try:
            self.play_btn.configure(text="▶")
        except Exception:
            pass

    def _playback_loop(self):
        delay = 1.0 / max(1.0, min(self._fps, 30.0))
        while self._playing and not self._stop_flag:
            t0 = time.perf_counter()
            if not self._read_next_frame():
                self._seek_to_frame(0)
                if not self._read_next_frame():
                    break
            elapsed = time.perf_counter() - t0
            if delay - elapsed > 0:
                time.sleep(delay - elapsed)
        self._playing = False
        try:
            self.after(0, lambda: self.play_btn.configure(text="▶"))
        except Exception:
            pass

    def _read_next_frame(self) -> bool:
        frame = None
        with self._cap_lock:
            if not self._cap:
                return False
            ret, frame = self._cap.read()
            if not ret:
                return False
            self._frame_idx = int(self._cap.get(cv2.CAP_PROP_POS_FRAMES))
        # Color conversion is CPU-only work — safe outside the lock.
        self._frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        self.after(0, self._render_canvas)
        return True

    def _seek_to_frame(self, frame_idx: int):
        frame_idx = max(0, min(frame_idx, max(0, self._total_frames - 1)))
        with self._cap_lock:
            if not self._cap:
                return
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        self._frame_idx = frame_idx

    def _show_current_frame(self):
        frame = None
        with self._cap_lock:
            if not self._cap:
                return
            # seek + read must be atomic under the lock so the playback
            # thread cannot advance the position between the two calls.
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, self._frame_idx)
            ret, frame = self._cap.read()
            if not ret:
                return
        self._frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        self._render_canvas()

    def _render_canvas(self):
        if self._frame_rgb is None:
            return

        frame = self._frame_rgb
        h, w = frame.shape[:2]
        canvas_w = max(1, int(self.canvas.winfo_width() or self.display_w))
        canvas_h = max(1, int(self.canvas.winfo_height() or self.display_h))

        scale = min(canvas_w / w, canvas_h / h)
        draw_w = max(1, int(w * scale))
        draw_h = max(1, int(h * scale))
        off_x = (canvas_w - draw_w) // 2
        off_y = (canvas_h - draw_h) // 2

        img = Image.fromarray(frame).resize((draw_w, draw_h), Image.Resampling.LANCZOS)
        self._photo = ImageTk.PhotoImage(img)

        self.canvas.delete("all")
        self._canvas_img_id = self.canvas.create_image(off_x, off_y, image=self._photo, anchor="nw")

        t_sec = self._current_time()
        cx = self._effective_center_x(t_sec)

        crop_w = min(draw_w, int(draw_h * 9 / 16))
        center_px = off_x + int(cx * draw_w)
        x1 = max(off_x, min(center_px - crop_w // 2, off_x + draw_w - crop_w))
        x2 = x1 + crop_w

        self.canvas.create_rectangle(x1, off_y, x2, off_y + draw_h,
                                     outline="#00e5ff", width=2)
        self.canvas.create_rectangle(0, 0, x1, canvas_h, fill="#000000", stipple="gray50", outline="")
        self.canvas.create_rectangle(x2, 0, canvas_w, canvas_h, fill="#000000", stipple="gray50", outline="")

        self.seek_var.set((self._frame_idx / max(1, self._total_frames - 1)))
        self.time_label.configure(text=f"{self._fmt_time(t_sec)} / {self._fmt_time(self._duration)}")

    def _on_seek(self, val: float):
        # Stop the playback thread before seeking so _frame_idx is not
        # concurrently modified between the set() in _seek_to_frame and the
        # read() in _show_current_frame.  The user can press play again.
        was_playing = self._playing
        if was_playing:
            self.stop()
            # Give the playback thread a moment to exit the cap.read() critical
            # section before we try to seek (the lock in _show_current_frame
            # guarantees safety, but stopping first avoids the brief lock
            # contention that causes visible frame glitches).
            time.sleep(0.04)
        frame_idx = int(float(val) * max(1, self._total_frames - 1))
        self._seek_to_frame(frame_idx)
        self._show_current_frame()

    def _on_center_slider(self, val: float):
        x = max(0.1, min(0.9, float(val)))
        self._update_center_label(x)
        if self.mode_var.get():
            self._upsert_keyframe(self._current_time(), x)
        else:
            self.base_center_x = x
        if self._playing:
            # While playing, avoid seek+decode on every slider movement.
            # Re-render overlay only; playback loop will refresh next frame.
            self._render_canvas()
        else:
            self._show_current_frame()
        self._update_kf_label()
        self._emit_change()

    def _on_mouse_down(self, event):
        self._dragging = True
        self._set_center_from_canvas_x(event.x)

    def _on_mouse_drag(self, event):
        if not self._dragging:
            return
        self._set_center_from_canvas_x(event.x)

    def _on_mouse_up(self, _event):
        self._dragging = False

    def _set_center_from_canvas_x(self, x_px: int):
        if self._frame_rgb is None:
            return
        frame_h, frame_w = self._frame_rgb.shape[:2]
        canvas_w = max(1, int(self.canvas.winfo_width() or self.display_w))
        canvas_h = max(1, int(self.canvas.winfo_height() or self.display_h))

        scale = min(canvas_w / frame_w, canvas_h / frame_h)
        draw_w = max(1, int(frame_w * scale))
        off_x = (canvas_w - draw_w) // 2

        norm = (x_px - off_x) / max(1, draw_w)
        norm = max(0.1, min(0.9, norm))

        self.center_var.set(norm)
        self._update_center_label(norm)

        if self.mode_var.get():
            self._upsert_keyframe(self._current_time(), norm)
        else:
            self.base_center_x = norm

        if self._playing:
            # Dragging during playback should stay responsive; repaint crop box
            # over current frame instead of forcing a fresh decode.
            self._render_canvas()
        else:
            self._show_current_frame()
        self._update_kf_label()
        self._emit_change()

    def _add_current_keyframe(self):
        self._upsert_keyframe(self._current_time(), float(self.center_var.get()))
        self._update_kf_label()
        self._emit_change()

    def _delete_nearest_keyframe(self):
        if not self.keyframes:
            return
        t = self._current_time()
        nearest = min(self.keyframes, key=lambda k: abs(float(k.get("t", 0.0)) - t))
        self.keyframes.remove(nearest)
        self._update_kf_label()
        self._show_current_frame()
        self._emit_change()

    def _upsert_keyframe(self, t: float, x: float):
        t = max(0.0, min(self._duration, float(t)))
        x = max(0.1, min(0.9, float(x)))
        for k in self.keyframes:
            if abs(float(k.get("t", 0.0)) - t) <= 0.15:
                k["x"] = x
                k["t"] = t
                break
        else:
            self.keyframes.append({"t": t, "x": x})
        self.keyframes.sort(key=lambda k: float(k.get("t", 0.0)))

    def _effective_center_x(self, t: float) -> float:
        if not self.keyframes:
            return max(0.1, min(0.9, float(self.base_center_x)))

        kfs = sorted(self.keyframes, key=lambda k: float(k.get("t", 0.0)))
        if t <= float(kfs[0].get("t", 0.0)):
            return max(0.1, min(0.9, float(kfs[0].get("x", self.base_center_x))))
        if t >= float(kfs[-1].get("t", 0.0)):
            return max(0.1, min(0.9, float(kfs[-1].get("x", self.base_center_x))))

        for i in range(len(kfs) - 1):
            t1 = float(kfs[i].get("t", 0.0))
            t2 = float(kfs[i + 1].get("t", 0.0))
            if t1 <= t <= t2 and t2 > t1:
                x1 = float(kfs[i].get("x", self.base_center_x))
                x2 = float(kfs[i + 1].get("x", self.base_center_x))
                alpha = (t - t1) / (t2 - t1)
                return max(0.1, min(0.9, x1 + (x2 - x1) * alpha))

        return max(0.1, min(0.9, float(self.base_center_x)))

    def _current_time(self) -> float:
        return (self._frame_idx / self._fps) if self._fps > 0 else 0.0

    def _update_kf_label(self):
        self.kf_label.configure(text=f"Keyframes: {len(self.keyframes)}")

    def _update_center_label(self, x: float):
        self.center_label.configure(text=f"x={x:.2f}")

    def _emit_change(self):
        if self.on_change:
            try:
                self.on_change(self.get_crop_data())
            except Exception:
                pass

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        m = int(seconds) // 60
        s = int(seconds) % 60
        return f"{m}:{s:02d}"

    def destroy(self):
        self.stop()
        with self._cap_lock:
            if self._cap:
                try:
                    self._cap.release()
                except Exception:
                    pass
                self._cap = None
        super().destroy()
