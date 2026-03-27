"""
Caption Generator - Auto Caption feature for video subtitles
Fixed: Karaoke highlighting, smooth transitions, hook effects
"""

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Callable
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import io


# Available fonts for caption
AVAILABLE_FONTS = [
    "Montserrat",
    "Arial Black",
    "Arial",
    "Impact",
    "Verdana",
    "Tahoma",
    "Roboto",
    "Open Sans",
    "Bebas Neue",
]

# Caption display modes
CAPTION_MODES = {
    "sentence": "Full Sentence (default)",
    "word_by_word": "Word-by-Word (TikTok style)",
    "word_highlight": "Karaoke Highlight",
    "chunk": "2-3 Word Chunks",
}

# Transition effects
TRANSITION_EFFECTS = {
    "none": "No transition",
    "fade": "Fade In/Out",
    "slide_up": "Slide Up",
    "slide_down": "Slide Down",
    "pop": "Pop/Scale",
}


@dataclass
class CaptionStyle:
    """Caption styling configuration"""
    font_name: str = "Montserrat"
    font_size: int = 65
    primary_color: str = "&H00FFFFFF"  # White in BGR
    outline_color: str = "&H00000000"  # Black
    highlight_color: str = "&H0000FFFF"  # Yellow for highlight
    outline_width: int = 4
    shadow: int = 2
    bold: bool = True
    italic: bool = False
    alignment: int = 2  # 2=bottom-center, 5=middle-center, 8=top-center
    margin_v: int = 50
    margin_h: int = 50
    transition_in: str = "fade"
    transition_out: str = "fade"
    transition_duration: float = 0.15
    caption_mode: str = "sentence"
    timing_offset: float = 0.0
    words_per_chunk: int = 3
    enable_hook_effect: bool = True  # Special effect for first sentence


@dataclass
class WordTiming:
    """Single word with precise timing"""
    text: str
    start: float
    end: float


@dataclass
class CaptionSegment:
    """A single caption segment with timing"""
    text: str
    start: float
    end: float
    words: Optional[List[Dict]] = None
    is_hook: bool = False  # Mark as hook/opening sentence


class CaptionGenerator:
    """Caption generation with word-level precision and hook effects"""

    POSITION_MAP = {"bottom": 2, "middle": 5, "top": 8}
    _processing_lock = False

    def __init__(self, style: Optional[CaptionStyle] = None):
        self.style = style or CaptionStyle()
        self.ffmpeg_path = self._get_ffmpeg_path()
        self.ffprobe_path = self._get_ffprobe_path()

    def _get_ffmpeg_path(self) -> str:
        try:
            from utils.helpers import get_ffmpeg_path
            return get_ffmpeg_path()
        except:
            return "ffmpeg"

    def _get_ffprobe_path(self) -> str:
        try:
            from utils.helpers import get_ffprobe_path
            return get_ffprobe_path()
        except:
            return "ffprobe"

    # ===== Timestamp Formatting =====

    @staticmethod
    def format_timestamp(seconds: float) -> str:
        """Format seconds to MM:SS format"""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes:02d}:{secs:02d}"

    @staticmethod
    def parse_timestamp(timestamp: str) -> float:
        """Parse MM:SS or MM:SS.ms format to seconds"""
        parts = timestamp.strip().replace(",", ".").split(":")
        if len(parts) == 2:
            mins, secs = parts
            return int(mins) * 60 + float(secs)
        elif len(parts) == 3:
            hours, mins, secs = parts
            return int(hours) * 3600 + int(mins) * 60 + float(secs)
        return 0

    # ===== Timed Script Format =====

    def format_timed_script(self, segments: List[CaptionSegment]) -> str:
        """Format segments into editable timed script [MM:SS - MM:SS] text"""
        lines = []
        for i, seg in enumerate(segments):
            start_str = self.format_timestamp(seg.start)
            end_str = self.format_timestamp(seg.end)
            text = seg.text.strip()
            if text:
                prefix = "[HOOK] " if i == 0 else ""
                lines.append(f"[{start_str} - {end_str}] {prefix}{text}")
        return "\n".join(lines)

    def parse_timed_script(self, script_text: str) -> List[CaptionSegment]:
        """Parse timed script back into segments"""
        segments = []
        pattern_new = re.compile(r"\[(\d+:\d+(?:\.\d+)?)\s*-\s*(\d+:\d+(?:\.\d+)?)\]\s*(?:\[HOOK\]\s*)?(.+)", re.IGNORECASE)
        pattern_legacy = re.compile(r"detik\s+(\d+)\s*-\s*(\d+)\s*:\s*(.+)", re.IGNORECASE)

        for idx, line in enumerate(script_text.strip().split("\n")):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            match = pattern_new.match(line)
            if match:
                start = self.parse_timestamp(match.group(1))
                end = self.parse_timestamp(match.group(2))
                text = match.group(3).strip()
                if text:
                    segments.append(CaptionSegment(
                        text=text, start=float(start), end=float(end),
                        is_hook=(idx == 0)
                    ))
                continue

            match = pattern_legacy.match(line)
            if match:
                start = int(match.group(1))
                end = int(match.group(2))
                text = match.group(3).strip()
                if text:
                    segments.append(CaptionSegment(
                        text=text, start=float(start), end=float(end),
                        is_hook=(len(segments) == 0)
                    ))

        return segments

    # ===== Word-Level Processing =====

    def expand_to_word_segments(
        self,
        segments: List[CaptionSegment],
        mode: str = "word_by_word"
    ) -> List[CaptionSegment]:
        """Expand sentence segments to word-level segments"""
        expanded = []

        for seg_idx, seg in enumerate(segments):
            is_first_segment = (seg_idx == 0)

            if seg.words and len(seg.words) > 0:
                if mode == "word_by_word":
                    expanded.extend(self._expand_word_by_word(seg, is_first_segment))
                elif mode == "chunk":
                    expanded.extend(self._expand_chunks(seg, is_first_segment))
                elif mode == "word_highlight":
                    expanded.extend(self._expand_karaoke(seg, is_first_segment))
                else:
                    seg.is_hook = is_first_segment
                    expanded.append(seg)
            else:
                estimated_seg = self._estimate_word_timings(seg)
                if mode == "word_by_word":
                    expanded.extend(self._expand_word_by_word(estimated_seg, is_first_segment))
                elif mode == "chunk":
                    expanded.extend(self._expand_chunks(estimated_seg, is_first_segment))
                elif mode == "word_highlight":
                    expanded.extend(self._expand_karaoke(estimated_seg, is_first_segment))
                else:
                    seg.is_hook = is_first_segment
                    expanded.append(seg)

        return expanded

    def _expand_word_by_word(self, seg: CaptionSegment, is_hook: bool = False) -> List[CaptionSegment]:
        """Expand segment to show one word at a time"""
        if not seg.words:
            return [seg]

        result = []
        for idx, w in enumerate(seg.words):
            word_text = w.get('text', '').strip()
            if word_text:
                result.append(CaptionSegment(
                    text=word_text.upper(),
                    start=w.get('start', 0),
                    end=w.get('end', 0),
                    words=None,
                    is_hook=(is_hook and idx == 0)
                ))
        return result

    def _expand_chunks(self, seg: CaptionSegment, is_hook: bool = False) -> List[CaptionSegment]:
        """Expand segment to show N words at a time"""
        if not seg.words:
            return [seg]

        result = []
        words_per_chunk = self.style.words_per_chunk

        for i in range(0, len(seg.words), words_per_chunk):
            chunk_words = seg.words[i:i + words_per_chunk]
            if chunk_words:
                chunk_text = " ".join(w.get('text', '').strip() for w in chunk_words)
                result.append(CaptionSegment(
                    text=chunk_text.upper(),
                    start=chunk_words[0].get('start', 0),
                    end=chunk_words[-1].get('end', 0),
                    words=chunk_words,
                    is_hook=(is_hook and i == 0)
                ))
        return result

    def _expand_karaoke(self, seg: CaptionSegment, is_hook: bool = False) -> List[CaptionSegment]:
        """
        Create smooth karaoke using ASS \\kf tags - NO FLICKER!

        Uses built-in ASS karaoke feature:
        - Single subtitle event per sentence (no multiple overlapping events)
        - \\kf<centiseconds> = smooth fill effect for each word
        - Words highlight progressively from left to right

        IMPORTANT: Duration is calculated as time until NEXT word starts (not word end)
        This ensures total karaoke time matches segment duration exactly.
        """
        if not seg.words:
            return [seg]

        # Filter out empty words first
        valid_words = []
        for w in seg.words:
            word = w.get('text', '').strip()
            if word:
                valid_words.append(w)

        if not valid_words:
            return [seg]

        # Build karaoke text with \kf tags
        # FIXED: Duration = time until next word (or segment end for last word)
        # This ensures proper sync and no missing words
        karaoke_parts = []
        num_words = len(valid_words)

        for i, w in enumerate(valid_words):
            word = w.get('text', '').strip().upper()
            word_start = w.get('start', 0)

            if i < num_words - 1:
                # For non-last words: duration = next_word_start - current_word_start
                next_word_start = valid_words[i + 1].get('start', word_start)
                duration_sec = next_word_start - word_start
            else:
                # For LAST word: duration = segment_end - last_word_start
                # This ensures the last word fills until segment ends
                duration_sec = seg.end - word_start

            # Convert to centiseconds with minimum duration
            duration_cs = max(int(duration_sec * 100), 15)  # Minimum 0.15 second

            karaoke_parts.append(f"{{\\kf{duration_cs}}}{word}")

        if not karaoke_parts:
            return [seg]

        # Join with spaces - single text for entire sentence
        karaoke_text = " ".join(karaoke_parts)

        # Return SINGLE segment spanning entire sentence duration
        return [CaptionSegment(
            text=karaoke_text,
            start=seg.start,
            end=seg.end,
            words=None,
            is_hook=is_hook
        )]

    def _estimate_word_timings(self, seg: CaptionSegment) -> CaptionSegment:
        """Estimate word timings for segments without word-level data"""
        words = seg.text.split()
        if not words:
            return seg

        total_chars = sum(len(w) for w in words)
        if total_chars == 0:
            return seg

        duration = seg.end - seg.start
        current_time = seg.start

        estimated_words = []
        for word in words:
            word_duration = (len(word) / total_chars) * duration
            word_duration = max(word_duration, 0.12)  # Minimum duration

            estimated_words.append({
                'text': word,
                'start': round(current_time, 3),
                'end': round(min(current_time + word_duration, seg.end), 3)
            })
            current_time += word_duration

        return CaptionSegment(
            text=seg.text, start=seg.start, end=seg.end,
            words=estimated_words, is_hook=seg.is_hook
        )

    # ===== ASS Subtitle Generation =====

    def generate_ass_subtitle(
        self,
        segments: List[CaptionSegment],
        output_path: str,
        video_width: int = 1080,
        video_height: int = 1920,
        enable_word_mode: bool = False
    ) -> str:
        """Generate ASS subtitle file with custom styling and hook effects"""
        s = self.style

        # Apply word-level expansion if enabled
        if enable_word_mode and s.caption_mode != "sentence":
            segments = self.expand_to_word_segments(segments, s.caption_mode)

        # ASS file header with multiple styles
        # Note: For karaoke (\kf tags), the fill goes FROM SecondaryColour TO PrimaryColour
        header = f"""[Script Info]
Title: Auto Caption
ScriptType: v4.00+
WrapStyle: 0
PlayResX: {video_width}
PlayResY: {video_height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{s.font_name},{s.font_size},{s.primary_color},&H000000FF,{s.outline_color},&H80000000,{-1 if s.bold else 0},{-1 if s.italic else 0},0,0,100,100,0,0,1,{s.outline_width},{s.shadow},{s.alignment},{s.margin_h},{s.margin_h},{s.margin_v},1
Style: Hook,{s.font_name},{int(s.font_size * 1.2)},{s.highlight_color},&H000000FF,{s.outline_color},&H80000000,-1,0,0,0,100,100,0,0,1,{s.outline_width + 2},{s.shadow + 1},{s.alignment},{s.margin_h},{s.margin_h},{s.margin_v},1
Style: Highlight,{s.font_name},{s.font_size},{s.highlight_color},&H000000FF,{s.outline_color},&H80000000,{-1 if s.bold else 0},{-1 if s.italic else 0},0,0,100,100,0,0,1,{s.outline_width},{s.shadow},{s.alignment},{s.margin_h},{s.margin_h},{s.margin_v},1
Style: Karaoke,{s.font_name},{s.font_size},{s.highlight_color},{s.primary_color},{s.outline_color},&H80000000,{-1 if s.bold else 0},{-1 if s.italic else 0},0,0,100,100,0,0,1,{s.outline_width},{s.shadow},{s.alignment},{s.margin_h},{s.margin_h},{s.margin_v},1
Style: KaraokeHook,{s.font_name},{int(s.font_size * 1.2)},{s.highlight_color},{s.primary_color},{s.outline_color},&H80000000,-1,0,0,0,100,100,0,0,1,{s.outline_width + 2},{s.shadow + 1},{s.alignment},{s.margin_h},{s.margin_h},{s.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        events = []
        trans_ms = int(s.transition_duration * 1000)
        offset = s.timing_offset

        for idx, seg in enumerate(segments):
            adj_start = max(0, seg.start + offset)
            adj_end = seg.end + offset

            start_time = self._format_ass_time(adj_start)
            end_time = self._format_ass_time(adj_end)

            # Text processing
            text = seg.text
            if not text.startswith("{\\"):
                text = text.upper()

            # Check if this is karaoke mode (text contains \kf tags)
            is_karaoke = "\\kf" in text

            # Determine style based on mode and hook status
            if is_karaoke:
                # Use Karaoke styles for proper \kf color handling
                # Karaoke style: PrimaryColour=highlight, SecondaryColour=base
                if seg.is_hook and s.enable_hook_effect:
                    style_name = "KaraokeHook"
                else:
                    style_name = "Karaoke"
            else:
                # Regular styles
                if seg.is_hook and s.enable_hook_effect:
                    style_name = "Hook"
                else:
                    style_name = "Default"

            # Apply effects based on style
            effects = ""

            if seg.is_hook and s.enable_hook_effect:
                # HOOK EFFECT - dramatic entrance for first caption
                # Scale up + bounce effect + glow
                effects = (
                    f"{{\\fad({trans_ms * 2},{trans_ms})}}"  # Longer fade in
                    f"{{\\t(0,{trans_ms * 2},\\fscx110\\fscy110)}}"  # Scale up
                    f"{{\\t({trans_ms * 2},{trans_ms * 3},\\fscx100\\fscy100)}}"  # Bounce back
                    f"{{\\blur2\\t({trans_ms},0,\\blur0)}}"  # Blur to sharp
                )
            elif s.transition_in == "fade":
                effects = f"{{\\fad({trans_ms},{trans_ms})}}"
            elif s.transition_in == "pop":
                effects = f"{{\\fscx80\\fscy80\\t(0,{trans_ms},\\fscx100\\fscy100)}}"
            elif s.transition_in == "slide_up":
                margin_offset = s.margin_v + 50
                effects = f"{{\\move(0,{margin_offset},0,0,0,{trans_ms})}}"

            # Combine effects with text
            if effects:
                # For karaoke mode, don't double-wrap
                if text.startswith("{\\"):
                    text = effects + text
                else:
                    text = f"{effects}{text}"

            event_line = f"Dialogue: 0,{start_time},{end_time},{style_name},,0,0,0,,{text}"
            events.append(event_line)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(header)
            f.write("\n".join(events))

        return output_path

    def _format_ass_time(self, seconds: float) -> str:
        """Convert seconds to ASS time format (H:MM:SS.cc)"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centisecs = int((seconds % 1) * 100)
        return f"{hours}:{minutes:02d}:{secs:02d}.{centisecs:02d}"

    # ===== Thumbnail Preview =====

    def extract_video_frame(
        self,
        video_path: str,
        timestamp: float = 1.0,
        output_path: Optional[str] = None
    ) -> str:
        """Extract a single frame from video as thumbnail"""
        if output_path is None:
            output_path = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name

        cmd = [
            self.ffmpeg_path,
            "-ss", str(timestamp),
            "-i", video_path,
            "-frames:v", "1",
            "-q:v", "2",
            "-y",
            output_path
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
        except AttributeError:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0 or not os.path.exists(output_path):
            raise Exception(f"Failed to extract frame: {result.stderr[:200] if result.stderr else 'Unknown error'}")

        return output_path

    def generate_preview_thumbnail(
        self,
        video_path: str,
        caption_text: str,
        timestamp: float = 1.0,
        is_hook: bool = False
    ) -> Image.Image:
        """Generate preview thumbnail with caption overlay (FAST)"""
        frame_path = None
        try:
            frame_path = self.extract_video_frame(video_path, timestamp)
            img = Image.open(frame_path)
            img = img.convert("RGB")  # Ensure RGB mode
            img_with_caption = self._draw_caption_on_image(img, caption_text, is_hook)
            return img_with_caption
        except Exception as e:
            # Create fallback image if extraction fails
            img = Image.new("RGB", (1080, 1920), color=(30, 30, 30))
            draw = ImageDraw.Draw(img)
            draw.text((540, 960), "Preview Error", fill=(255, 255, 255), anchor="mm")
            return img
        finally:
            if frame_path and os.path.exists(frame_path):
                try:
                    os.remove(frame_path)
                except:
                    pass

    def _draw_caption_on_image(self, img: Image.Image, text: str, is_hook: bool = False) -> Image.Image:
        """Draw caption text on image using PIL"""
        draw = ImageDraw.Draw(img)
        s = self.style

        width, height = img.size

        # Larger font for hook
        font_size = int(s.font_size * 1.2) if is_hook else s.font_size
        font = self._get_pil_font(s.font_name, font_size)
        text = text.upper()

        # Calculate text position
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
        except:
            text_width = len(text) * font_size // 2
            text_height = font_size

        x = (width - text_width) // 2

        if s.alignment == 2:  # bottom
            y = height - s.margin_v - text_height
        elif s.alignment == 8:  # top
            y = s.margin_v
        else:  # middle
            y = (height - text_height) // 2

        # Use highlight color for hook
        if is_hook:
            text_color = self._ass_to_rgb(s.highlight_color)
        else:
            text_color = self._ass_to_rgb(s.primary_color)
        outline_color = self._ass_to_rgb(s.outline_color)

        # Draw outline
        outline_width = s.outline_width + (2 if is_hook else 0)
        for dx in range(-outline_width, outline_width + 1):
            for dy in range(-outline_width, outline_width + 1):
                if dx != 0 or dy != 0:
                    draw.text((x + dx, y + dy), text, font=font, fill=outline_color)

        draw.text((x, y), text, font=font, fill=text_color)

        return img

    def _get_pil_font(self, font_name: str, font_size: int):
        """Get PIL font with fallback"""
        try:
            return ImageFont.truetype(font_name, font_size)
        except:
            pass

        font_paths = [
            f"C:/Windows/Fonts/{font_name}.ttf",
            f"C:/Windows/Fonts/{font_name.lower()}.ttf",
            f"C:/Windows/Fonts/{font_name.replace(' ', '')}.ttf",
            f"C:/Windows/Fonts/{font_name.lower().replace(' ', '')}.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
        ]

        for path in font_paths:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, font_size)
                except:
                    continue

        try:
            return ImageFont.load_default()
        except:
            return None

    def _ass_to_rgb(self, ass_color: str) -> Tuple[int, int, int]:
        """Convert ASS BGR format to RGB tuple"""
        ass_color = ass_color.replace("&H", "").replace("&", "").upper()
        if len(ass_color) < 6:
            return (255, 255, 255)

        bgr = ass_color[-6:]
        try:
            b = int(bgr[0:2], 16)
            g = int(bgr[2:4], 16)
            r = int(bgr[4:6], 16)
            return (r, g, b)
        except:
            return (255, 255, 255)

    # ===== Video Export =====

    def burn_captions_to_video(
        self,
        video_path: str,
        ass_path: str,
        output_path: str,
        progress_callback: Optional[Callable] = None
    ) -> str:
        """Burn captions into video with process lock"""
        if CaptionGenerator._processing_lock:
            raise Exception("Another caption process is running. Please wait.")

        CaptionGenerator._processing_lock = True

        try:
            if progress_callback:
                progress_callback("Burning captions into video...")

            ass_escaped = ass_path.replace("\\", "/").replace(":", "\\:")

            cmd = [
                self.ffmpeg_path,
                "-i", video_path,
                "-vf", f"ass='{ass_escaped}'",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-c:a", "copy",
                "-movflags", "+faststart",
                "-y",
                output_path
            ]

            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=600,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
            except AttributeError:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

            if result.returncode != 0:
                error_msg = result.stderr[:500] if result.stderr else "Unknown error"
                raise Exception(f"FFmpeg error: {error_msg}")

            return output_path

        finally:
            CaptionGenerator._processing_lock = False

    @classmethod
    def is_processing(cls) -> bool:
        return cls._processing_lock

    @classmethod
    def cancel_processing(cls):
        cls._processing_lock = False

    # ===== Color Helpers =====

    @staticmethod
    def hex_to_ass_color(hex_color: str) -> str:
        """Convert hex (#RRGGBB) to ASS BGR (&H00BBGGRR)"""
        hex_color = hex_color.lstrip("#").upper()
        if len(hex_color) != 6:
            return "&H00FFFFFF"
        r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6]
        return f"&H00{b}{g}{r}"

    @staticmethod
    def ass_to_hex_color(ass_color: str) -> str:
        """Convert ASS BGR to hex"""
        ass_color = ass_color.replace("&H", "").replace("&", "").upper()
        if len(ass_color) < 6:
            return "#FFFFFF"
        bgr = ass_color[-6:]
        return f"#{bgr[4:6]}{bgr[2:4]}{bgr[0:2]}"


def create_caption_from_transcript(
    transcript_segments: List,
    style: Optional[CaptionStyle] = None
) -> List[CaptionSegment]:
    """Convert transcript segments to caption segments with word data"""
    caption_segments = []

    for idx, seg in enumerate(transcript_segments):
        text = seg.text if hasattr(seg, 'text') else seg.get('text', '')
        start = seg.start if hasattr(seg, 'start') else seg.get('start', 0)
        end = seg.end if hasattr(seg, 'end') else seg.get('end', 0)
        words = seg.words if hasattr(seg, 'words') else seg.get('words', None)

        if text.strip():
            caption_segments.append(CaptionSegment(
                text=text, start=float(start), end=float(end),
                words=words, is_hook=(idx == 0)
            ))

    return caption_segments


if __name__ == "__main__":
    print("Caption Generator Test (Fixed)")
    print("=" * 50)

    # Test with word timings
    test_seg = CaptionSegment(
        text="Belum ada listrik apalagi lampu LED",
        start=0, end=3,
        words=[
            {"text": "Belum", "start": 0.0, "end": 0.4},
            {"text": "ada", "start": 0.4, "end": 0.7},
            {"text": "listrik", "start": 0.7, "end": 1.2},
            {"text": "apalagi", "start": 1.2, "end": 1.8},
            {"text": "lampu", "start": 1.8, "end": 2.3},
            {"text": "LED", "start": 2.3, "end": 3.0},
        ],
        is_hook=True
    )

    style = CaptionStyle(caption_mode="word_highlight")
    generator = CaptionGenerator(style)

    # Test karaoke expansion
    expanded = generator._expand_karaoke(test_seg, is_hook=True)
    print("Karaoke expansion (first 3):")
    for seg in expanded[:3]:
        print(f"  [{seg.start:.2f}-{seg.end:.2f}] {seg.text[:80]}...")

    print("\nTest completed!")
