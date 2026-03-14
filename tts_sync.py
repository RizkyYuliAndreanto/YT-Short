"""
TTS Sync Module - Synchronize TTS audio with video
Handles timing adjustment, audio mixing, and subtitle generation
"""

import os
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Callable, Tuple
from dataclasses import dataclass
import asyncio

from utils.helpers import get_ffmpeg_path
from edge_tts_engine import EdgeTTSEngine, EdgeTTSManager, TTSSegment


@dataclass
class AudioMixConfig:
    """Configuration for audio mixing"""
    voice_volume: float = 1.0      # TTS voice volume (0.0 - 2.0)
    background_volume: float = 0.2  # Original video audio volume (0.0 - 1.0)
    keep_original_audio: bool = True  # Mix with original or replace
    normalize: bool = True          # Normalize final audio
    crossfade_ms: int = 50          # Crossfade between segments


@dataclass 
class SubtitleStyle:
    """Subtitle styling configuration"""
    font_name: str = "Arial"
    font_size: int = 24
    primary_color: str = "&HFFFFFF"  # White
    outline_color: str = "&H000000"  # Black
    outline_width: int = 2
    shadow: int = 1
    alignment: int = 2  # Bottom center
    margin_v: int = 40  # Vertical margin
    bold: bool = True
    highlight_color: str = "&H00FFFF"  # Yellow for highlight


class TTSVideoSync:
    """
    Synchronize TTS audio with video
    - Generate TTS from script
    - Adjust timing to match video
    - Mix audio (voice + original background)
    - Generate and burn subtitles
    - GPU-accelerated encoding (NVIDIA NVENC / AMD AMF)
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize syncer
        
        Config:
        {
            "edge_tts": {"voice": "...", "rate": "...", "pitch": "..."},
            "mix_config": {"voice_volume": 1.0, "background_volume": 0.2},
            "subtitle_style": {"font_size": 24, ...}
        }
        """
        self.config = config or {}
        self.ffmpeg_path = get_ffmpeg_path()
        
        # Initialize TTS engine
        tts_config = self.config.get("edge_tts", {})
        self.tts_manager = EdgeTTSManager(tts_config)
        
        # Mix config
        mix_cfg = self.config.get("mix_config", {})
        self.mix_config = AudioMixConfig(**mix_cfg)
        
        # Subtitle style
        sub_cfg = self.config.get("subtitle_style", {})
        self.subtitle_style = SubtitleStyle(**sub_cfg)
        
        # GPU acceleration — auto-detect
        self.gpu_encoder_args = []
        self._init_gpu()
    
    def _init_gpu(self):
        """Auto-detect GPU and set encoder args for FFmpeg."""
        try:
            from utils.gpu_detector import GPUDetector
            detector = GPUDetector(self.ffmpeg_path)
            gpu = detector.detect_gpu()
            if gpu['available']:
                args = detector.get_encoder_args(use_gpu=True)
                # Verify it's not the CPU fallback
                if args and args[1] != 'libx264':
                    self.gpu_encoder_args = args
                    print(f"[TTS_SYNC] ⚡ GPU Acceleration: {gpu['name']} → {args[1]}")
                else:
                    print(f"[TTS_SYNC] GPU detected ({gpu['name']}) but no HW encoder available, using CPU")
            else:
                print("[TTS_SYNC] No GPU detected, using CPU encoding")
        except Exception as e:
            print(f"[TTS_SYNC] GPU detection failed: {e}, using CPU")
    
    def _get_video_encoder_args(self) -> list:
        """Get video encoder args — GPU if available, else CPU."""
        if self.gpu_encoder_args:
            return list(self.gpu_encoder_args)
        return ['-c:v', 'libx264', '-preset', 'fast', '-crf', '18']
    
    def generate_tts_audio(self,
                          script: str,
                          output_path: str,
                          progress_callback: Optional[Callable] = None) -> Tuple[str, float, List[Dict]]:
        """
        Generate TTS audio from script
        
        Returns:
            Tuple of (audio_path, duration, word_timings)
        """
        if progress_callback:
            progress_callback("Generating voice audio...")
        
        return self.tts_manager.generate_audio_sync(script, output_path)
    
    def generate_segmented_tts(self,
                              segments: List[Dict],
                              output_dir: str,
                              video_duration: float,
                              progress_callback: Optional[Callable] = None) -> List[TTSSegment]:
        """
        Generate TTS for multiple segments with timing
        
        Args:
            segments: List of {"text": "...", "target_start": 0, "target_end": 10}
            output_dir: Directory for temp files
            video_duration: Total video duration
            progress_callback: Progress callback
            
        Returns:
            List of TTSSegment with actual timing
        """
        if progress_callback:
            progress_callback("Generating voice segments...")
        
        os.makedirs(output_dir, exist_ok=True)
        
        # Adjust segment timing if needed
        adjusted_segments = self._adjust_segment_timing(segments, video_duration)
        
        return self.tts_manager.generate_segments_sync(adjusted_segments, output_dir)
    
    def _adjust_segment_timing(self, 
                               segments: List[Dict], 
                               video_duration: float) -> List[Dict]:
        """Adjust segment timing to fit video duration"""
        if not segments:
            return []
        
        adjusted = []
        current_time = 0.0
        
        for seg in segments:
            target_start = seg.get("target_start", current_time)
            target_end = seg.get("target_end", target_start + 5)
            
            # Ensure within video bounds
            target_start = min(target_start, video_duration - 1)
            target_end = min(target_end, video_duration)
            
            adjusted.append({
                **seg,
                "target_start": target_start,
                "target_end": target_end
            })
            
            current_time = target_end + 0.2  # Small gap
        
        return adjusted
    
    def download_audio_from_url(self, url: str, output_path: str,
                                progress_callback: Optional[Callable] = None) -> str:
        """
        Download audio from a URL (TikTok, YouTube, etc.) using yt-dlp.
        Extracts audio only as mp3.
        
        Args:
            url: Video URL (TikTok, YouTube, etc.)
            output_path: Where to save the audio file (.mp3)
            progress_callback: Optional callback
            
        Returns:
            Path to downloaded audio file
        """
        if progress_callback:
            progress_callback("Downloading background music...")
        
        print(f"[TTS_SYNC] 🎵 Downloading BGM from: {url[:80]}")
        
        from utils.helpers import get_ytdlp_path
        ytdlp_path = get_ytdlp_path()
        
        # Ensure output ends with .mp3
        if not output_path.endswith(".mp3"):
            output_path = output_path.rsplit(".", 1)[0] + ".mp3"
        
        if ytdlp_path == "yt_dlp_module":
            import yt_dlp
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': output_path.rsplit('.', 1)[0],  # without extension
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'ffmpeg_location': os.path.dirname(self.ffmpeg_path) or None,
                'quiet': True,
                'no_warnings': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        else:
            cmd = [
                ytdlp_path,
                "-x", "--audio-format", "mp3",
                "--audio-quality", "192K",
                "-o", output_path.rsplit('.', 1)[0] + ".%(ext)s",
                "--ffmpeg-location", os.path.dirname(self.ffmpeg_path) or ".",
                "--no-warnings", "-q",
                url
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                raise Exception(f"yt-dlp download error: {result.stderr[:300]}")
        
        if not os.path.exists(output_path):
            # yt-dlp might save with slightly different name
            base = output_path.rsplit('.', 1)[0]
            for ext in ['.mp3', '.m4a', '.opus', '.webm']:
                alt = base + ext
                if os.path.exists(alt):
                    # Convert to mp3 if needed
                    if ext != '.mp3':
                        tmp = base + "_conv.mp3"
                        subprocess.run([
                            self.ffmpeg_path, "-i", alt,
                            "-c:a", "libmp3lame", "-b:a", "192k",
                            "-y", tmp
                        ], capture_output=True, timeout=60)
                        os.replace(tmp, output_path)
                        os.remove(alt)
                    else:
                        os.replace(alt, output_path)
                    break
        
        if not os.path.exists(output_path):
            raise Exception(f"BGM download failed - no audio file found at {output_path}")
        
        size_kb = os.path.getsize(output_path) / 1024
        print(f"[TTS_SYNC] 🎵 BGM downloaded: {size_kb:.0f} KB → {output_path}")
        return output_path
    
    def mix_audio_with_video(self,
                            video_path: str,
                            tts_audio_path: str,
                            output_path: str,
                            tts_start_offset: float = 0,
                            bgm_path: Optional[str] = None,
                            bgm_volume: float = 0.15,
                            progress_callback: Optional[Callable] = None) -> str:
        """
        Mix TTS audio with video, optionally adding background music.
        
        Args:
            video_path: Input video path
            tts_audio_path: TTS audio path
            output_path: Output video path
            tts_start_offset: When to start TTS (seconds from video start)
            bgm_path: Optional background music audio file
            bgm_volume: BGM volume (0.0 - 1.0, default 0.15)
            progress_callback: Progress callback
            
        Returns:
            Output video path
        """
        if progress_callback:
            progress_callback("Mixing audio with video...")
        
        voice_vol = self.mix_config.voice_volume
        bg_vol = self.mix_config.background_volume
        
        if self.mix_config.keep_original_audio:
            if bgm_path and os.path.exists(bgm_path):
                # 3-way mix: original audio + TTS voice + background music
                filter_complex = (
                    f"[0:a]volume={bg_vol}[bg];"
                    f"[1:a]adelay={int(tts_start_offset*1000)}|{int(tts_start_offset*1000)},volume={voice_vol}[voice];"
                    f"[2:a]aloop=loop=-1:size=2e+09,volume={bgm_volume}[music];"
                    f"[bg][voice][music]amix=inputs=3:duration=first[aout]"
                )
                cmd = [
                    self.ffmpeg_path,
                    "-i", video_path,
                    "-i", tts_audio_path,
                    "-i", bgm_path,
                    "-filter_complex", filter_complex,
                    "-map", "0:v",
                    "-map", "[aout]",
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-y",
                    output_path
                ]
                print(f"[TTS_SYNC] 🎛️ 3-way mix: video({bg_vol}) + voice({voice_vol}) + BGM({bgm_volume})")
            else:
                # 2-way mix: original audio + TTS voice (existing behavior)
                filter_complex = f"[0:a]volume={bg_vol}[bg];[1:a]adelay={int(tts_start_offset*1000)}|{int(tts_start_offset*1000)},volume={voice_vol}[voice];[bg][voice]amix=inputs=2:duration=first[aout]"
                
                cmd = [
                    self.ffmpeg_path,
                    "-i", video_path,
                    "-i", tts_audio_path,
                    "-filter_complex", filter_complex,
                    "-map", "0:v",
                    "-map", "[aout]",
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-y",
                    output_path
                ]
        else:
            # Replace audio entirely
            # -fflags +genpts regenerates PTS to avoid frozen initial frames
            # -avoid_negative_ts prevents timestamp discontinuities from concat input
            cmd = [
                self.ffmpeg_path,
                "-fflags", "+genpts",
                "-i", video_path,
                "-i", tts_audio_path,
                "-map", "0:v",
                "-map", "1:a",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                "-avoid_negative_ts", "make_zero",
                "-y",
                output_path
            ]
        
        print(f"[TTS_SYNC] Mix cmd: {' '.join(cmd[:6])}...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if result.returncode != 0:
            # Show tail of stderr (actual error) not head (version info)
            err_lines = [l for l in result.stderr.splitlines() if l.strip()]
            err_msg = '\n'.join(err_lines[-5:]) if err_lines else result.stderr[-500:]
            raise Exception(f"FFmpeg mix error: {err_msg}")
        
        return output_path
    
    def generate_ass_subtitle(self,
                              word_timings: List[Dict],
                              output_path: str,
                              video_width: int = 1080,
                              video_height: int = 1920) -> str:
        """
        Generate ASS subtitle with word-by-word highlighting
        
        Args:
            word_timings: List of {"text": "...", "start": 0.5, "duration": 0.3}
            output_path: Output .ass file path
            video_width/height: Video dimensions for positioning
            
        Returns:
            Path to generated .ass file
        """
        style = self.subtitle_style
        
        # ASS header
        header = f"""[Script Info]
Title: TTS Subtitles
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style.font_name},{style.font_size},{style.primary_color},&H000000FF,{style.outline_color},&H80000000,{-1 if style.bold else 0},0,0,0,100,100,0,0,1,{style.outline_width},{style.shadow},{style.alignment},20,20,{style.margin_v},1
Style: Highlight,{style.font_name},{style.font_size},{style.highlight_color},&H000000FF,{style.outline_color},&H80000000,{-1 if style.bold else 0},0,0,0,100,100,0,0,1,{style.outline_width},{style.shadow},{style.alignment},20,20,{style.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        
        events = []
        
        # Group words into subtitle lines (max 6 words per line)
        chunks = self._group_words_for_highlight(word_timings)
        
        for chunk in chunks:
            start_time = self._format_ass_time(chunk["start"])
            end_time = self._format_ass_time(chunk["end"])
            text = chunk["text"]
            
            # Add dialogue line
            events.append(f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{text}")
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(header)
            f.write("\n".join(events))
        
        return output_path
    
    def _group_words_for_highlight(self,
                                   word_timings: List[Dict],
                                   max_words: int = 5,
                                   max_duration: float = 2.5) -> List[Dict]:
        """Group words for subtitle display with highlighting"""
        chunks = []
        current_words = []
        chunk_start = 0
        
        for i, word in enumerate(word_timings):
            if not current_words:
                chunk_start = word["start"]
            
            current_words.append(word["text"])
            chunk_end = word["start"] + word.get("duration", 0.3)
            
            # Check if should create new chunk
            duration = chunk_end - chunk_start
            is_end = word["text"].rstrip().endswith((".", "!", "?", ",", ";"))
            
            if (len(current_words) >= max_words or 
                duration >= max_duration or 
                is_end or 
                i == len(word_timings) - 1):
                
                chunks.append({
                    "text": " ".join(current_words),
                    "start": chunk_start,
                    "end": chunk_end
                })
                current_words = []
        
        return chunks
    
    def burn_subtitles(self,
                      video_path: str,
                      subtitle_path: str,
                      output_path: str,
                      progress_callback: Optional[Callable] = None) -> str:
        """
        Burn subtitles into video
        
        Args:
            video_path: Input video
            subtitle_path: .ass or .srt subtitle file
            output_path: Output video
            progress_callback: Progress callback
            
        Returns:
            Output video path
        """
        if progress_callback:
            progress_callback("Burning subtitles into video...")
        
        # Escape path for FFmpeg filter
        sub_path_escaped = subtitle_path.replace("\\", "/").replace(":", "\\:").replace("'", "'\\''")
        
        # Use GPU encoding if available (subtitle burn requires re-encode)
        enc_args = self._get_video_encoder_args()
        
        # -fflags +genpts ensures clean PTS from input (fixes frozen frames from concat/copy)
        cmd = [
            self.ffmpeg_path,
            "-fflags", "+genpts",
            "-i", video_path,
            "-vf", f"ass='{sub_path_escaped}'",
        ] + enc_args + [
            "-bf", "0",
            "-c:a", "copy",
            "-movflags", "+faststart",
            "-y",
            output_path
        ]
        
        print(f"[TTS_SYNC] Burn subtitles cmd: {' '.join(cmd[:8])}...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        
        if result.returncode != 0:
            # Try SRT format
            cmd = [
                self.ffmpeg_path,
                "-fflags", "+genpts",
                "-i", video_path,
                "-vf", f"subtitles='{sub_path_escaped}'",
            ] + enc_args + [
                "-bf", "0",
                "-c:a", "copy",
                "-movflags", "+faststart",
                "-y",
                output_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            
            if result.returncode != 0:
                raise Exception(f"FFmpeg subtitle error: {result.stderr[:500]}")
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centisecs = int((seconds % 1) * 100)
        return f"{hours}:{minutes:02d}:{secs:02d}.{centisecs:02d}"
    
    # ==================================================================
    # HARDCODED SUBTITLE REMOVAL
    # ==================================================================
    
    def _probe_video_dimensions(self, video_path: str) -> Tuple[int, int]:
        """Get video width and height via ffprobe"""
        ffprobe_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
        ffprobe = os.path.join(os.path.dirname(self.ffmpeg_path), ffprobe_name)
        cmd = [
            ffprobe, "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0",
            video_path
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                parts = r.stdout.strip().split(",")
                return int(parts[0]), int(parts[1])
        except Exception:
            pass
        return 1080, 1920  # safe fallback for portrait video
    
    def remove_hardcoded_subtitles(self,
                                    video_path: str,
                                    output_path: str,
                                    region: str = "bottom",
                                    region_percent: int = 12,
                                    offset_percent: int = 0,
                                    method: str = "delogo",
                                    progress_callback: Optional[Callable] = None) -> str:
        """
        Remove/cover hardcoded subtitles from video using FFmpeg.
        
        Args:
            video_path: Input video path
            output_path: Output video path (clean video)
            region: Where subtitles are ("bottom", "top", "both")
            region_percent: Height percentage of the removal band (5-35)
            offset_percent: Shift the band inward from the edge (0-40).
            method: "delogo" (double-pass interpolate), "blur" (strong gaussian), or "black"
            progress_callback: Optional callback
            
        Returns:
            output_path
        """
        if progress_callback:
            progress_callback("Removing hardcoded subtitles...")
        
        # Clamp to safe ranges
        pct = max(5, min(35, region_percent))
        off = max(0, min(40, offset_percent))
        
        # Probe real video dimensions (delogo needs pixel values, not expressions)
        vid_w, vid_h = self._probe_video_dimensions(video_path)
        band_h = int(vid_h * pct / 100)
        
        def _calc_y(rgn):
            """Calculate Y pixel position for a region"""
            if rgn == "bottom":
                return vid_h - int(vid_h * (pct + off) / 100)
            else:  # top
                return int(vid_h * off / 100)
        
        def _build_filter(rgn):
            """Build filter for a single region"""
            y_px = _calc_y(rgn)
            
            if method == "delogo":
                # Double-pass delogo with integer pixel values
                return (
                    f"delogo=x=0:y={y_px}:w={vid_w}:h={band_h}:band=5,"
                    f"delogo=x=0:y={y_px}:w={vid_w}:h={band_h}:band=5"
                )
            elif method == "blur":
                # Strong blur — use expressions for crop (supports ih/iw),
                # but use H (main height) for overlay positioning
                if rgn == "bottom":
                    crop_y = f"ih-ih*{pct+off}/100"
                    ov_y = f"H-h-H*{off}/100" if off > 0 else "H-h"
                else:
                    crop_y = f"ih*{off}/100" if off > 0 else "0"
                    ov_y = f"H*{off}/100" if off > 0 else "0"
                return (
                    f"split[main][sub];"
                    f"[sub]crop=iw:ih*{pct}/100:0:{crop_y},"
                    f"boxblur=30:30[blurred];"
                    f"[main][blurred]overlay=0:{ov_y}"
                )
            else:  # black — drawbox supports expressions
                if rgn == "bottom":
                    y_expr = f"ih-ih*{pct+off}/100"
                else:
                    y_expr = f"ih*{off}/100" if off > 0 else "0"
                return f"drawbox=x=0:y={y_expr}:w=iw:h=ih*{pct}/100:color=black:t=fill"
        
        # Build the complete video filter
        if region == "both":
            if method == "blur":
                bot_y_px = _calc_y("bottom")
                top_y_px = _calc_y("top")
                bot_crop_y = f"ih-ih*{pct+off}/100"
                top_crop_y = f"ih*{off}/100" if off > 0 else "0"
                bot_ov_y = f"H-h-H*{off}/100" if off > 0 else "H-h"
                top_ov_y = f"H*{off}/100" if off > 0 else "0"
                h_expr = f"ih*{pct}/100"
                vf = (
                    f"split=3[main][bot][top];"
                    f"[bot]crop=iw:{h_expr}:0:{bot_crop_y},"
                    f"boxblur=30:30[bbot];"
                    f"[top]crop=iw:{h_expr}:0:{top_crop_y},"
                    f"boxblur=30:30[btop];"
                    f"[main][bbot]overlay=0:{bot_ov_y}[tmp];"
                    f"[tmp][btop]overlay=0:{top_ov_y}"
                )
            else:
                vf = f"{_build_filter('bottom')},{_build_filter('top')}"
        else:
            vf = _build_filter(region)
        
        enc_args = self._get_video_encoder_args()
        
        cmd = [
            self.ffmpeg_path,
            "-i", video_path,
            "-vf", vf,
        ] + enc_args + [
            "-c:a", "copy",
            "-y",
            output_path
        ]
        
        print(f"[TTS_SYNC] 🧹 Removing subtitles: region={region} {pct}% offset={off}% method={method}")
        print(f"  → Video: {vid_w}x{vid_h} | band_h={band_h}px")
        print(f"  → Filter: {vf[:200]}...")
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        
        if result.returncode != 0:
            stderr_tail = result.stderr[-800:] if len(result.stderr) > 800 else result.stderr
            print(f"[TTS_SYNC] ⚠️ FFmpeg stderr: {stderr_tail}")
            
            # Fallback chain: delogo → blur → black
            if method == "delogo":
                print(f"[TTS_SYNC] ⚠️ delogo failed, falling back to blur...")
                return self.remove_hardcoded_subtitles(
                    video_path, output_path, region, pct, off, "blur", progress_callback
                )
            elif method == "blur":
                print(f"[TTS_SYNC] ⚠️ blur failed, falling back to black fill...")
                return self.remove_hardcoded_subtitles(
                    video_path, output_path, region, pct, off, "black", progress_callback
                )
            raise Exception(f"FFmpeg subtitle removal error: {stderr_tail[:500]}")
        
        print(f"[TTS_SYNC] 🧹 Subtitle removal complete → {output_path}")
        return output_path
    
    # ==================================================================
    # SEGMENT-BASED DUBBING (duration-matched)
    # ==================================================================
    
    def combine_tts_segments_to_track(self,
                                       segments: List[TTSSegment],
                                       total_duration: float,
                                       output_path: str,
                                       progress_callback: Optional[Callable] = None) -> str:
        """
        Combine multiple TTS segments into a single audio track
        aligned to the video timeline using FFmpeg concat.
        
        Uses sequential concat (not amix) for dramatically faster processing:
        silence_gap → segment → silence_gap → segment → ... → trailing_silence
        
        amix processes all N inputs sample-by-sample in parallel = O(N*T) = very slow.
        concat appends streams sequentially = O(T) = fast.
        """
        if not segments:
            raise ValueError("No TTS segments to combine")
        
        if progress_callback:
            progress_callback("Combining voice segments into audio track...")
        
        # Sort by start time to build sequential concat
        segments = sorted(segments, key=lambda s: s.start_time)
        
        # Build FFmpeg inputs: alternating silence gaps and TTS segments
        cmd = [self.ffmpeg_path]
        input_idx = 0
        current_time = 0.0
        input_labels = []  # track input indices for filter
        
        for seg in segments:
            gap = seg.start_time - current_time
            
            # Insert silence gap before this segment (min 10ms)
            if gap > 0.01:
                cmd.extend(["-f", "lavfi", "-t", f"{gap:.3f}",
                            "-i", "anullsrc=r=44100:cl=mono"])
                input_labels.append(input_idx)
                input_idx += 1
            
            # Insert the TTS segment audio
            cmd.extend(["-i", seg.audio_path])
            input_labels.append(input_idx)
            input_idx += 1
            
            # Advance timeline past this segment
            current_time = seg.start_time + seg.duration
        
        # Add trailing silence to reach total video duration
        remaining = total_duration - current_time
        if remaining > 0.01:
            cmd.extend(["-f", "lavfi", "-t", f"{remaining:.3f}",
                        "-i", "anullsrc=r=44100:cl=mono"])
            input_labels.append(input_idx)
            input_idx += 1
        
        # Build filter_complex: normalize all inputs to same format, then concat
        filter_parts = []
        for i, idx in enumerate(input_labels):
            # Resample all inputs to uniform 44100Hz mono for concat compatibility
            filter_parts.append(
                f"[{idx}]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=mono[n{i}]"
            )
        
        concat_str = "".join(f"[n{i}]" for i in range(len(input_labels)))
        filter_parts.append(
            f"{concat_str}concat=n={len(input_labels)}:v=0:a=1[out]"
        )
        
        filter_complex = ";".join(filter_parts)
        
        # Write filter to temp file to avoid command-line length limits
        filter_file = output_path + ".filter.txt"
        try:
            with open(filter_file, "w", encoding="utf-8") as f:
                f.write(filter_complex)
            
            cmd.extend(["-filter_complex_script", filter_file, "-map", "[out]",
                        "-y", output_path])
            
            n_silence = input_idx - len(segments)
            print(f"  → FFmpeg concat: {input_idx} inputs "
                  f"({len(segments)} TTS + {n_silence} silence gaps) | "
                  f"total={total_duration:.1f}s")
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                raise Exception(f"FFmpeg combine segments error: {result.stderr[:500]}")
        except subprocess.TimeoutExpired:
            raise Exception("FFmpeg combine segments timed out after 300s")
        finally:
            try:
                os.remove(filter_file)
            except:
                pass
        
        return output_path
    
    def process_video_with_timed_segments(self,
                                           video_path: str,
                                           timed_segments: List[Dict],
                                           video_duration: float,
                                           output_path: str,
                                           include_subtitle: bool = True,
                                           remove_original_subs: bool = False,
                                           sub_removal_config: Optional[Dict] = None,
                                           bgm_url: Optional[str] = None,
                                           bgm_volume: float = 0.15,
                                           progress_callback: Optional[Callable] = None,
                                           pregenerated_tts: Optional[List[Dict]] = None) -> Dict:
        """
        Complete segment-based dubbing pipeline:
        0. (Optional) Remove hardcoded subtitles / Download BGM
        1. Generate TTS for each transcript segment (with auto rate adjustment)
        2. Combine into single audio track aligned to video timeline
        3. Mix with original video (voice + lowered original audio + optional BGM)
        4. Optionally burn subtitles
        
        Args:
            video_path: Input video path
            timed_segments: List of {"text": "...", "start": 0.5, "end": 3.2}
            video_duration: Total video duration in seconds
            output_path: Output video path
            include_subtitle: Whether to burn subtitles
            remove_original_subs: Whether to remove hardcoded subtitles first
            sub_removal_config: {"region": "bottom", "region_percent": 15, "method": "delogo"}
            bgm_url: Optional URL (TikTok, YouTube, etc.) to extract background music
            bgm_volume: BGM volume 0.0-1.0 (default 0.15)
            progress_callback: Optional fn(percent: float, msg: str)
            
        Returns:
            Dict with output info including coverage_percent
        """
        temp_dir = tempfile.mkdtemp()
        
        try:
            total = len(timed_segments)
            all_word_timings = []
            tts_results = []  # List[TTSSegment]
            
            import time as _time
            pipeline_start = _time.time()
            
            print(f"\n{'='*60}")
            print(f"[DUBBING] Starting generation pipeline")
            print(f"[DUBBING] Video: {os.path.basename(video_path)} ({video_duration:.1f}s)")
            print(f"[DUBBING] Segments: {total}")
            print(f"[DUBBING] Output: {output_path}")
            print(f"[DUBBING] Subtitle: {include_subtitle}")
            print(f"[DUBBING] Remove original subs: {remove_original_subs}")
            print(f"[DUBBING] BGM: {bgm_url[:60] + '...' if bgm_url and len(bgm_url) > 60 else bgm_url or 'None'}")
            print(f"[DUBBING] GPU: {self.gpu_encoder_args[1] if self.gpu_encoder_args else 'CPU (libx264)'}")
            print(f"{'='*60}")
            
            # ====== Step 0: Remove hardcoded subtitles / Download BGM ======
            working_video = video_path
            step0_time = 0
            bgm_path = None
            
            if remove_original_subs or bgm_url:
                step0_start = _time.time()
            
            if remove_original_subs:
                cfg = sub_removal_config or {}
                region = cfg.get("region", "bottom")
                region_pct = cfg.get("region_percent", 12)
                offset_pct = cfg.get("offset_percent", 0)
                method = cfg.get("method", "delogo")
                
                print(f"\n[STEP 0] 🧹 Removing hardcoded subtitles (region={region} {region_pct}% offset={offset_pct}% method={method})...")
                if progress_callback:
                    progress_callback(2, f"🧹 Removing original subtitles ({method})...")
                
                clean_video = os.path.join(temp_dir, "clean_video.mp4")
                self.remove_hardcoded_subtitles(
                    video_path, clean_video,
                    region=region, region_percent=region_pct,
                    offset_percent=offset_pct, method=method
                )
                working_video = clean_video
            
            if bgm_url:
                print(f"\n[STEP 0] 🎵 Downloading background music...")
                if progress_callback:
                    progress_callback(3, "🎵 Downloading background music...")
                
                bgm_path = os.path.join(temp_dir, "bgm.mp3")
                try:
                    self.download_audio_from_url(bgm_url, bgm_path)
                except Exception as e:
                    print(f"[STEP 0] ⚠️ BGM download failed: {e} — continuing without BGM")
                    bgm_path = None
            
            if remove_original_subs or bgm_url:
                step0_time = _time.time() - step0_start
                print(f"[STEP 0] ✅ Done in {step0_time:.1f}s")
            
            # ====== Step 1: Generate TTS per segment (5-40%) ======
            step1_start = _time.time()
            
            if pregenerated_tts:
                # Use pre-generated TTS audio from TTS Studio
                print(f"\n[STEP 1/4] Using {len(pregenerated_tts)} pre-generated TTS segments...")
                if progress_callback:
                    progress_callback(35, f"🔊 Using {len(pregenerated_tts)} pre-generated TTS segments")
                
                for i, ptts in enumerate(pregenerated_tts):
                    seg_start = float(ptts.get("target_start", ptts.get("start", 0)))
                    duration = float(ptts.get("tts_duration", 0))
                    audio_path = ptts.get("audio_path", "")
                    text = ptts.get("text", "")
                    
                    if not audio_path or not os.path.exists(audio_path):
                        print(f"  ⚠ Seg {i+1}: audio file missing, skipping")
                        continue
                    
                    print(f"  [{i+1}/{len(pregenerated_tts)}] {self._fmt_time(seg_start)} | "
                          f"TTS={duration:.1f}s | \"{text[:40]}{'...' if len(text)>40 else ''}\"")
                    
                    # Offset word timings to absolute video position
                    word_timings = ptts.get("word_timings", [])
                    if word_timings:
                        for wt in word_timings:
                            wt["start"] = wt.get("start", 0) + seg_start
                        all_word_timings.extend(word_timings)
                    
                    tts_results.append(TTSSegment(
                        text=text,
                        start_time=seg_start,
                        end_time=seg_start + duration,
                        audio_path=audio_path,
                        duration=duration
                    ))
            else:
                print(f"\n[STEP 1/4] Generating TTS for {total} segments...")
                
                for i, seg in enumerate(timed_segments):
                    text = seg.get("text", "").strip()
                    if not text:
                        continue
                    
                    seg_start = float(seg.get("start", 0))
                    seg_end = float(seg.get("end", seg_start + 5))
                    target_duration = seg_end - seg_start
                    
                    pct = 5 + (i / max(total, 1) * 35)
                    if progress_callback:
                        progress_callback(pct, f"🔊 TTS segment {i+1}/{total} [{self._fmt_time(seg_start)}-{self._fmt_time(seg_end)}]")
                    
                    seg_path = os.path.join(temp_dir, f"seg_{i:03d}.mp3")
                    
                    seg_t = _time.time()
                    # Generate TTS at configured speed
                    audio_path, duration, word_timings = self.tts_manager.generate_audio_sync(
                        text, seg_path
                    )
                    
                    rate_adjusted = False
                    # Auto rate adjustment: if TTS is too long for the time slot
                    if duration > target_duration * 1.15 and target_duration > 0.5:
                        speed_factor = duration / target_duration
                        max_speed = 1.40  # cap at +40% speed
                        actual_speed = min(speed_factor, max_speed)
                        rate_pct = int((actual_speed - 1) * 100)
                        
                        # Save original rate, generate faster, restore
                        old_rate = self.tts_manager.engine.rate
                        self.tts_manager.engine.set_rate(f"+{rate_pct}%")
                        audio_path, duration, word_timings = self.tts_manager.generate_audio_sync(
                            text, seg_path
                        )
                        self.tts_manager.engine.set_rate(old_rate)
                        rate_adjusted = True
                    
                    elapsed = _time.time() - seg_t
                    rate_info = f" (rate+{rate_pct}%)" if rate_adjusted else ""
                    print(f"  [{i+1}/{total}] {self._fmt_time(seg_start)}-{self._fmt_time(seg_end)} | "
                          f"TTS={duration:.1f}s / target={target_duration:.1f}s{rate_info} | "
                          f"{elapsed:.1f}s | \"{text[:40]}{'...' if len(text)>40 else ''}\"")
                    
                    # Offset word timings to absolute video position
                    if word_timings:
                        for wt in word_timings:
                            wt["start"] = wt.get("start", 0) + seg_start
                        all_word_timings.extend(word_timings)
                    
                    tts_results.append(TTSSegment(
                        text=text,
                        start_time=seg_start,
                        end_time=seg_start + duration,
                        audio_path=seg_path,
                        duration=duration
                    ))
            
            step1_time = _time.time() - step1_start
            print(f"[STEP 1/4] ✅ Done: {len(tts_results)} segments in {step1_time:.1f}s")
            
            if not tts_results:
                raise ValueError("No valid segments could be generated")
            
            # ====== Step 2: Combine segments into single audio track (40-50%) ======
            step2_start = _time.time()
            print(f"\n[STEP 2/4] Combining {len(tts_results)} TTS segments into audio track...")
            if progress_callback:
                progress_callback(42, f"🎵 Combining {len(tts_results)} voice segments...")
            
            combined_audio = os.path.join(temp_dir, "combined_voice.mp3")
            # Sub-methods expect callback(msg), not callback(pct, msg)
            sub_cb = (lambda msg: progress_callback(45, f"🎵 {msg}")) if progress_callback else None
            self.combine_tts_segments_to_track(
                tts_results, video_duration, combined_audio, sub_cb
            )
            step2_time = _time.time() - step2_start
            print(f"[STEP 2/4] ✅ Done in {step2_time:.1f}s")
            
            # ====== Step 3: Mix with video (50-65%) ======
            step3_start = _time.time()
            bgm_info = f" + BGM({bgm_volume})" if bgm_path else ""
            print(f"\n[STEP 3/4] Mixing voice + original audio{bgm_info}...")
            if progress_callback:
                progress_callback(52, "🎛️ Mixing voice + original audio...")
            
            mixed_video = os.path.join(temp_dir, "mixed.mp4")
            mix_cb = (lambda msg: progress_callback(55, f"🎛️ {msg}")) if progress_callback else None
            self.mix_audio_with_video(
                working_video, combined_audio, mixed_video,
                bgm_path=bgm_path,
                bgm_volume=bgm_volume,
                progress_callback=mix_cb
            )
            step3_time = _time.time() - step3_start
            print(f"[STEP 3/4] ✅ Done in {step3_time:.1f}s")
            
            # ====== Step 4: Subtitles (65-90%) ======
            if include_subtitle and all_word_timings:
                step4_start = _time.time()
                print(f"\n[STEP 4/4] Generating & burning subtitles ({len(all_word_timings)} words)...")
                if progress_callback:
                    progress_callback(68, "📝 Generating subtitles...")
                
                from video_analyzer import VideoAnalyzer
                analyzer = VideoAnalyzer()
                vinfo = analyzer.get_video_info(video_path)
                
                ass_path = os.path.join(temp_dir, "subtitle.ass")
                self.generate_ass_subtitle(
                    all_word_timings, ass_path, vinfo.width, vinfo.height
                )
                print(f"  ASS subtitle generated: {os.path.getsize(ass_path)} bytes")
                
                if progress_callback:
                    progress_callback(78, "🔥 Burning subtitles into video (GPU)..." if self.gpu_encoder_args else "🔥 Burning subtitles into video (CPU)...")
                
                burn_cb = (lambda msg: progress_callback(82, f"🔥 {msg}")) if progress_callback else None
                self.burn_subtitles(mixed_video, ass_path, output_path, burn_cb)
                step4_time = _time.time() - step4_start
                print(f"[STEP 4/4] ✅ Done in {step4_time:.1f}s")
            else:
                import shutil
                shutil.copy(mixed_video, output_path)
                print(f"\n[STEP 4/4] ⏭️ Subtitles skipped (no word timings or disabled)")
            
            # ====== Stats ======
            total_tts = sum(s.duration for s in tts_results)
            coverage = (total_tts / video_duration * 100) if video_duration > 0 else 0
            
            total_time = _time.time() - pipeline_start
            output_size = os.path.getsize(output_path) / (1024 * 1024)  # MB
            
            print(f"\n{'='*60}")
            print(f"[DUBBING] ✅ PIPELINE COMPLETE")
            print(f"[DUBBING] Segments: {len(tts_results)}")
            print(f"[DUBBING] TTS total: {total_tts:.1f}s / {video_duration:.1f}s ({coverage:.0f}% coverage)")
            print(f"[DUBBING] Words: {len(all_word_timings)}")
            print(f"[DUBBING] Output: {output_path} ({output_size:.1f} MB)")
            print(f"[DUBBING] Total time: {total_time:.1f}s")
            if remove_original_subs or bgm_url:
                print(f"  Step 0 (Prep):     {step0_time:.1f}s")
            print(f"  Step 1 (TTS):      {step1_time:.1f}s")
            print(f"  Step 2 (Combine):  {step2_time:.1f}s")
            print(f"  Step 3 (Mix):      {step3_time:.1f}s")
            if include_subtitle and all_word_timings:
                print(f"  Step 4 (Subtitle): {step4_time:.1f}s")
            print(f"{'='*60}\n")
            
            if progress_callback:
                progress_callback(95, f"✅ Done! Coverage: {coverage:.0f}% of video")
            
            return {
                "output_path": output_path,
                "segments_count": len(tts_results),
                "total_tts_duration": total_tts,
                "video_duration": video_duration,
                "coverage_percent": coverage,
                "word_count": len(all_word_timings),
                "success": True
            }
            
        except Exception as e:
            import traceback
            print(f"\n{'='*60}")
            print(f"[DUBBING] ❌ PIPELINE FAILED")
            print(f"[DUBBING] Error: {str(e)}")
            print(f"[DUBBING] Traceback:\n{traceback.format_exc()}")
            print(f"{'='*60}\n")
            return {
                "output_path": None,
                "error": str(e),
                "success": False
            }
        finally:
            try:
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
            except:
                pass
    
    @staticmethod
    def _fmt_time(seconds: float) -> str:
        """Format seconds to MM:SS"""
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m:02d}:{s:02d}"
    
    def process_video_with_tts(self,
                              video_path: str,
                              script: str,
                              output_path: str,
                              include_subtitle: bool = True,
                              progress_callback: Optional[Callable] = None) -> Dict:
        """
        Complete pipeline: TTS + mix + subtitle
        
        Args:
            video_path: Input video
            script: Voiceover script
            output_path: Output video
            include_subtitle: Whether to burn subtitles
            progress_callback: Progress callback
            
        Returns:
            Dict with output info
        """
        temp_dir = tempfile.mkdtemp()
        
        try:
            # 1. Generate TTS
            if progress_callback:
                progress_callback("Step 1/4: Generating voice audio...")
            
            tts_audio = os.path.join(temp_dir, "voice.mp3")
            tts_subtitle = os.path.join(temp_dir, "voice.srt")
            
            audio_path, duration, word_timings = self.generate_tts_audio(
                script, tts_audio, progress_callback
            )
            
            # 2. Mix audio
            if progress_callback:
                progress_callback("Step 2/4: Mixing audio...")
            
            mixed_video = os.path.join(temp_dir, "mixed.mp4")
            self.mix_audio_with_video(video_path, tts_audio, mixed_video, 
                                      progress_callback=progress_callback)
            
            # 3. Generate subtitle
            if include_subtitle and word_timings:
                if progress_callback:
                    progress_callback("Step 3/4: Generating subtitles...")
                
                # Get video dimensions
                from video_analyzer import VideoAnalyzer
                analyzer = VideoAnalyzer()
                video_info = analyzer.get_video_info(video_path)
                
                ass_subtitle = os.path.join(temp_dir, "subtitle.ass")
                self.generate_ass_subtitle(
                    word_timings, ass_subtitle,
                    video_info.width, video_info.height
                )
                
                # 4. Burn subtitles
                if progress_callback:
                    progress_callback("Step 4/4: Burning subtitles...")
                
                self.burn_subtitles(mixed_video, ass_subtitle, output_path, progress_callback)
            else:
                # Just copy mixed video
                import shutil
                shutil.copy(mixed_video, output_path)
            
            if progress_callback:
                progress_callback("Complete!")
            
            return {
                "output_path": output_path,
                "tts_duration": duration,
                "word_count": len(word_timings) if word_timings else 0,
                "success": True
            }
            
        except Exception as e:
            return {
                "output_path": None,
                "error": str(e),
                "success": False
            }
        finally:
            # Cleanup temp files
            try:
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
            except:
                pass


def quick_dub_video(video_path: str, 
                   script: str, 
                   output_path: str,
                   config: Dict = None) -> Dict:
    """
    Quick function to dub a video with TTS
    
    Args:
        video_path: Input video
        script: Voiceover script
        output_path: Output video path
        config: Optional configuration
        
    Returns:
        Result dict with success status
    """
    syncer = TTSVideoSync(config)
    return syncer.process_video_with_tts(video_path, script, output_path)


if __name__ == "__main__":
    print("TTS Video Sync Test")
    print("=" * 50)
    
    # Show available voices
    from edge_tts_engine import EdgeTTSManager
    voices = EdgeTTSManager.get_voice_options()
    
    print("\nAvailable Indonesian voices:")
    for v in voices:
        print(f"  - {v['name']}: {v['description']}")
    
    print("\nTo test, provide a video file and script.")
