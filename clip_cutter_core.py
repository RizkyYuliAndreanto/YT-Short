"""
Clip Cutter Core - Multi-platform video segment downloader
Supports YouTube (partial download), TikTok, Instagram, Facebook
"""

import os
import re
import sys
import json
import tempfile
import subprocess
import importlib.util
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable, Tuple, Dict, Any

# Lazy loading for yt_dlp (saves ~100MB RAM)
YTDLP_MODULE_AVAILABLE = importlib.util.find_spec("yt_dlp") is not None
yt_dlp = None

def _ensure_yt_dlp():
    """Lazy import yt_dlp only when needed"""
    global yt_dlp
    if yt_dlp is None and YTDLP_MODULE_AVAILABLE:
        import yt_dlp as _yt_dlp
        yt_dlp = _yt_dlp
    return yt_dlp

# Windows subprocess flags
SUBPROCESS_FLAGS = 0
if sys.platform == "win32":
    SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW


# Platform detection patterns
# Note: youtube_shorts is separate from youtube - short-form videos don't need partial download
PLATFORM_PATTERNS = {
    'youtube_shorts': [
        r'(?:youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})',
    ],
    'youtube': [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})',
    ],
    'tiktok': [
        r'(?:tiktok\.com\/@[\w.-]+\/video\/)(\d+)',
        r'(?:vm\.tiktok\.com\/)(\w+)',
        r'(?:tiktok\.com\/t\/)(\w+)',
    ],
    'instagram': [
        r'(?:instagram\.com\/(?:p|reel|reels|tv)\/)([A-Za-z0-9_-]+)',
    ],
    'facebook': [
        r'(?:facebook\.com\/.*\/videos\/)(\d+)',
        r'(?:fb\.watch\/)(\w+)',
        r'(?:facebook\.com\/watch\/)(\d+)',
    ],
}


def detect_platform(url: str) -> Dict[str, Any]:
    """
    Detect platform from URL

    Returns:
        dict with keys:
            - 'platform': 'youtube', 'youtube_shorts', 'tiktok', 'instagram', 'facebook', or 'unknown'
            - 'video_id': extracted video ID if possible
            - 'supports_partial': bool (True only for regular YouTube, NOT for Shorts)
            - 'has_watermark': bool (True for TikTok, Instagram)
            - 'is_short_form': bool (True for YT Shorts, TikTok, Instagram, Facebook)
    """
    url_lower = url.lower()

    for platform, patterns in PLATFORM_PATTERNS.items():
        for pattern in patterns:
            match = re.search(pattern, url, re.IGNORECASE)
            if match:
                # Only regular YouTube videos support partial download
                # Short-form content (Shorts, TikTok, IG, FB) should use full download
                supports_partial = (platform == 'youtube')
                is_short_form = platform in ('youtube_shorts', 'tiktok', 'instagram', 'facebook')

                return {
                    'platform': platform,
                    'video_id': match.group(1) if match.groups() else None,
                    'supports_partial': supports_partial,
                    'has_watermark': platform in ('tiktok', 'instagram'),
                    'is_short_form': is_short_form,
                }

    return {
        'platform': 'unknown',
        'video_id': None,
        'supports_partial': False,
        'has_watermark': False,
        'is_short_form': False,
    }


def parse_time_input(time_str: str) -> float:
    """
    Parse user time input to seconds
    Supports: "4:30", "04:30", "1:04:30", "4m30s", "270", "4:30.5"
    """
    if not time_str:
        return 0.0

    time_str = time_str.strip()

    # Already a number (seconds)
    try:
        return float(time_str)
    except ValueError:
        pass

    # Format: 4m30s or 1h4m30s
    match = re.match(r'(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s?)?$', time_str, re.IGNORECASE)
    if match:
        h, m, s = match.groups()
        total = 0
        if h:
            total += int(h) * 3600
        if m:
            total += int(m) * 60
        if s:
            total += float(s)
        return total

    # Format: HH:MM:SS or MM:SS or MM:SS.ms
    parts = time_str.split(':')
    if len(parts) == 2:
        # MM:SS
        return int(parts[0]) * 60 + float(parts[1])
    elif len(parts) == 3:
        # HH:MM:SS
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])

    return 0.0


def format_time(seconds: float) -> str:
    """Format seconds to HH:MM:SS or MM:SS"""
    if seconds < 0:
        return "00:00"

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes:02d}:{secs:02d}"


def format_time_for_ytdlp(seconds: float) -> str:
    """Format seconds to HH:MM:SS.mm for yt-dlp"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:05.2f}"


class ClipCutterCore:
    """Core processing logic for Clip Cutter feature"""

    def __init__(
        self,
        ffmpeg_path: str = "ffmpeg",
        ytdlp_path: str = "yt_dlp_module",
        output_dir: str = "output/clips",
        cookies_path: str = None,
        deno_path: str = None,
        log_callback: Callable[[str], None] = None,
        progress_callback: Callable[[float, str], None] = None,
        cancel_check: Callable[[], bool] = None
    ):
        self.ffmpeg_path = ffmpeg_path
        self.ytdlp_path = ytdlp_path
        self.output_dir = Path(output_dir)
        self.cookies_path = cookies_path
        self.deno_path = deno_path
        self.log_callback = log_callback or (lambda x: print(x))
        self.progress_callback = progress_callback or (lambda p, s: None)
        self.cancel_check = cancel_check or (lambda: False)

        # GPU acceleration
        self.gpu_enabled = False
        self.gpu_encoder_args = []

        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Temp directory
        self.temp_dir = Path(tempfile.mkdtemp(prefix="clip_cutter_"))

    def log(self, msg: str):
        """Log message"""
        self.log_callback(msg)

    def set_gpu_acceleration(self, enabled: bool, encoder_args: list = None):
        """Configure GPU acceleration"""
        self.gpu_enabled = enabled
        self.gpu_encoder_args = encoder_args or []

    def _is_cancelled(self) -> bool:
        """Check if operation was cancelled"""
        return self.cancel_check()

    def get_video_info(self, url: str) -> Dict[str, Any]:
        """
        Get video metadata without downloading

        Returns:
            dict with keys:
                - 'title': str
                - 'duration': float (seconds)
                - 'thumbnail': str (URL)
                - 'platform': str
                - 'formats': list
                - 'has_watermark': bool
                - 'error': str or None
        """
        self.log("Fetching video info...")

        platform_info = detect_platform(url)

        try:
            _ensure_yt_dlp()
            if yt_dlp is None:
                return {'error': 'yt-dlp module not available'}

            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
            }

            # Add cookies if available
            if self.cookies_path and os.path.exists(self.cookies_path):
                ydl_opts['cookiefile'] = self.cookies_path

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

                # Get available formats
                formats = []
                if 'formats' in info:
                    seen_heights = set()
                    for f in info['formats']:
                        height = f.get('height')
                        if height and height not in seen_heights and height >= 360:
                            seen_heights.add(height)
                            formats.append({
                                'height': height,
                                'label': f"{height}p",
                            })
                    formats.sort(key=lambda x: x['height'], reverse=True)

                return {
                    'title': info.get('title', 'Unknown'),
                    'duration': info.get('duration', 0),
                    'thumbnail': info.get('thumbnail', ''),
                    'platform': platform_info['platform'],
                    'supports_partial': platform_info['supports_partial'],
                    'has_watermark': platform_info['has_watermark'],
                    'formats': formats,
                    'uploader': info.get('uploader', ''),
                    'error': None,
                }

        except Exception as e:
            error_msg = str(e)
            if "Sign in" in error_msg or "login" in error_msg.lower():
                error_msg = "This content requires authentication. Please configure cookies."
            elif "Private" in error_msg or "private" in error_msg:
                error_msg = "This video is private or unavailable."
            elif "age" in error_msg.lower():
                error_msg = "Age-restricted content. Please configure cookies."

            return {
                'error': error_msg,
                'platform': platform_info['platform'],
            }

    def download_clip(
        self,
        url: str,
        start_time: float = None,
        end_time: float = None,
        quality: str = "best",
        use_partial_download: bool = True,
        remove_watermark: bool = False,
        output_filename: str = None
    ) -> Tuple[str, Optional[str]]:
        """
        Download video clip with optional time range

        Args:
            url: Video URL
            start_time: Start time in seconds (optional)
            end_time: End time in seconds (optional)
            quality: Quality preference ('best', '1080', '720', '480', '360')
            use_partial_download: Use partial download for long YouTube videos (efficient)
            remove_watermark: Remove watermark (for TikTok, Instagram)
            output_filename: Custom output filename

        Returns:
            Tuple of (output_path, error_message)
        """
        platform_info = detect_platform(url)
        platform = platform_info['platform']
        is_short_form = platform_info.get('is_short_form', False)
        supports_partial = platform_info['supports_partial']

        self.log(f"Platform: {platform.upper()}")

        # Determine download method:
        # - Partial download ONLY for regular YouTube videos (not Shorts)
        # - Short-form content (YT Shorts, TikTok, Instagram, Facebook) should ALWAYS use full download
        # This saves resources and avoids ffmpeg issues with short videos
        should_use_partial = (
            supports_partial and
            use_partial_download and
            start_time is not None and
            end_time is not None and
            not is_short_form
        )

        if should_use_partial:
            self.log("Using partial download (long-form YouTube video)")
            return self._download_youtube_partial(url, start_time, end_time, quality, output_filename)
        else:
            if is_short_form:
                self.log("Using full download (short-form content - no partial needed)")
            return self._download_full_and_cut(
                url, platform, start_time, end_time, quality,
                remove_watermark, output_filename
            )

    def _download_youtube_partial(
        self,
        url: str,
        start_time: float,
        end_time: float,
        quality: str,
        output_filename: str = None
    ) -> Tuple[str, Optional[str]]:
        """
        Download only a segment of YouTube video (efficient)
        Uses yt-dlp's download_ranges feature
        """
        self.log(f"Using partial download: {format_time(start_time)} - {format_time(end_time)}")
        self.progress_callback(0.1, "Preparing partial download...")

        try:
            _ensure_yt_dlp()
            if yt_dlp is None:
                return None, "yt-dlp module not available"

            # Generate output filename
            if not output_filename:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_filename = f"clip_{timestamp}.mp4"

            output_path = self.output_dir / output_filename

            # Format selector based on quality
            format_selector = self._get_format_selector(quality)

            # Progress hook
            def progress_hook(d):
                if self._is_cancelled():
                    raise Exception("Download cancelled")

                if d['status'] == 'downloading':
                    total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    downloaded = d.get('downloaded_bytes', 0)
                    if total > 0:
                        pct = (downloaded / total) * 0.7 + 0.1  # 10-80%
                        self.progress_callback(pct, "Downloading segment...")
                elif d['status'] == 'finished':
                    self.progress_callback(0.8, "Processing...")

            # yt-dlp options with download_ranges
            ydl_opts = {
                'format': format_selector,
                'merge_output_format': 'mp4',
                'outtmpl': str(output_path),
                'download_ranges': yt_dlp.utils.download_range_func(
                    None, [(start_time, end_time)]
                ),
                'force_keyframes_at_cuts': True,
                'progress_hooks': [progress_hook],
                'quiet': True,
                'no_warnings': True,
            }

            # Add ffmpeg location if available
            if self.ffmpeg_path and self.ffmpeg_path != "ffmpeg":
                ydl_opts['ffmpeg_location'] = str(Path(self.ffmpeg_path).parent)

            # Add cookies if available
            if self.cookies_path and os.path.exists(self.cookies_path):
                ydl_opts['cookiefile'] = self.cookies_path

            # Add deno for JS runtime if available
            if self.deno_path and os.path.exists(self.deno_path):
                ydl_opts['js_runtimes'] = {'deno': {'path': self.deno_path}}

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                self.log("Starting partial download...")
                ydl.download([url])

            if self._is_cancelled():
                return None, "Download cancelled"

            self.progress_callback(1.0, "Complete!")
            self.log(f"Saved to: {output_path}")

            return str(output_path), None

        except Exception as e:
            error_msg = str(e)
            self.log(f"Error: {error_msg}")
            return None, error_msg

    def _download_full_and_cut(
        self,
        url: str,
        platform: str,
        start_time: float,
        end_time: float,
        quality: str,
        remove_watermark: bool,
        output_filename: str = None
    ) -> Tuple[str, Optional[str]]:
        """
        Download full video then cut segment using FFmpeg
        Used for: TikTok, Instagram, Facebook, or YouTube without partial download
        """
        try:
            _ensure_yt_dlp()
            if yt_dlp is None:
                return None, "yt-dlp module not available"

            # Step 1: Download full video
            self.progress_callback(0.1, f"Downloading from {platform}...")

            temp_video = self.temp_dir / "source_video.mp4"

            # Format selector
            format_selector = self._get_format_selector_platform(platform, quality, remove_watermark)

            # Progress hook
            def progress_hook(d):
                if self._is_cancelled():
                    raise Exception("Download cancelled")

                if d['status'] == 'downloading':
                    total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    downloaded = d.get('downloaded_bytes', 0)
                    if total > 0:
                        pct = (downloaded / total) * 0.5 + 0.1  # 10-60%
                        self.progress_callback(pct, "Downloading video...")
                elif d['status'] == 'finished':
                    self.progress_callback(0.6, "Download complete, processing...")

            ydl_opts = {
                'format': format_selector,
                'merge_output_format': 'mp4',
                'outtmpl': str(temp_video),
                'progress_hooks': [progress_hook],
                'quiet': True,
                'no_warnings': True,
            }

            # Add ffmpeg location
            if self.ffmpeg_path and self.ffmpeg_path != "ffmpeg":
                ydl_opts['ffmpeg_location'] = str(Path(self.ffmpeg_path).parent)

            # Add cookies if available
            if self.cookies_path and os.path.exists(self.cookies_path):
                ydl_opts['cookiefile'] = self.cookies_path

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                self.log(f"Downloading from {platform}...")
                info = ydl.extract_info(url, download=True)
                video_title = info.get('title', 'clip')

            if self._is_cancelled():
                return None, "Download cancelled"

            # Find the downloaded file (might have different extension)
            downloaded_files = list(self.temp_dir.glob("source_video.*"))
            if not downloaded_files:
                return None, "Download failed: no file found"

            temp_video = downloaded_files[0]
            self.log(f"Downloaded: {temp_video.name}")

            # Step 2: Cut segment if time range specified
            if start_time is not None and end_time is not None:
                self.progress_callback(0.7, "Cutting segment...")
                cut_video = self.temp_dir / "cut_video.mp4"

                success = self._ffmpeg_cut(temp_video, cut_video, start_time, end_time)
                if not success:
                    return None, "Failed to cut video segment"

                temp_video = cut_video

            # Step 3: Remove watermark if requested
            if remove_watermark and platform in ('tiktok', 'instagram'):
                self.progress_callback(0.85, "Removing watermark...")
                clean_video = self.temp_dir / "clean_video.mp4"

                success = self._remove_watermark(temp_video, clean_video, platform)
                if success:
                    temp_video = clean_video
                else:
                    self.log("Watermark removal failed, using original")

            # Step 4: Move to output directory
            if not output_filename:
                # Clean title for filename
                clean_title = re.sub(r'[<>:"/\\|?*]', '', video_title)[:50]
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_filename = f"{clean_title}_{timestamp}.mp4"

            output_path = self.output_dir / output_filename

            # Copy to output
            import shutil
            shutil.copy2(temp_video, output_path)

            self.progress_callback(1.0, "Complete!")
            self.log(f"Saved to: {output_path}")

            return str(output_path), None

        except Exception as e:
            error_msg = str(e)
            self.log(f"Error: {error_msg}")
            return None, error_msg

    def _get_format_selector(self, quality: str) -> str:
        """Get yt-dlp format selector for quality"""
        quality_map = {
            'best': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best',
            '1080': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]',
            '720': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[height<=720]',
            '480': 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=480]+bestaudio/best[height<=480]',
            '360': 'bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=360]+bestaudio/best[height<=360]',
        }
        return quality_map.get(quality, quality_map['best'])

    def _get_format_selector_platform(self, platform: str, quality: str, no_watermark: bool) -> str:
        """Get platform-specific format selector"""
        if platform == 'tiktok' and no_watermark:
            # TikTok no-watermark format
            return 'download_addr-0/download_addr/best'
        elif platform == 'instagram':
            return 'best'
        elif platform == 'facebook':
            return 'best'
        elif platform == 'youtube_shorts':
            # YouTube Shorts - use best available
            return 'best'
        else:
            return self._get_format_selector(quality)

    def _ffmpeg_cut(self, input_path: Path, output_path: Path, start: float, end: float) -> bool:
        """Cut video segment using FFmpeg"""
        try:
            duration = end - start

            # Use stream copy for speed (no re-encoding)
            cmd = [
                self.ffmpeg_path, '-y',
                '-ss', str(start),
                '-i', str(input_path),
                '-t', str(duration),
                '-c', 'copy',
                '-avoid_negative_ts', 'make_zero',
                str(output_path)
            ]

            self.log(f"Cutting: {format_time(start)} - {format_time(end)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                creationflags=SUBPROCESS_FLAGS
            )

            if result.returncode != 0:
                # Fallback: re-encode if stream copy fails
                self.log("Stream copy failed, re-encoding...")

                encoder_args = self.gpu_encoder_args if self.gpu_enabled else ['-c:v', 'libx264', '-preset', 'fast']

                cmd = [
                    self.ffmpeg_path, '-y',
                    '-i', str(input_path),
                    '-ss', str(start),
                    '-t', str(duration),
                    *encoder_args,
                    '-c:a', 'aac', '-b:a', '128k',
                    str(output_path)
                ]

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    creationflags=SUBPROCESS_FLAGS
                )

            return result.returncode == 0 and output_path.exists()

        except Exception as e:
            self.log(f"FFmpeg cut error: {e}")
            return False

    def _remove_watermark(self, input_path: Path, output_path: Path, platform: str) -> bool:
        """Remove watermark by cropping"""
        try:
            # Platform-specific crop filters
            crop_filters = {
                'tiktok': 'crop=iw:ih-100:0:0',  # Crop 100px from bottom
                'instagram': 'crop=iw:ih*0.92:0:0',  # Crop bottom 8%
            }

            crop_filter = crop_filters.get(platform)
            if not crop_filter:
                return False

            encoder_args = self.gpu_encoder_args if self.gpu_enabled else ['-c:v', 'libx264', '-preset', 'fast', '-crf', '18']

            cmd = [
                self.ffmpeg_path, '-y',
                '-i', str(input_path),
                '-vf', crop_filter,
                *encoder_args,
                '-c:a', 'copy',
                str(output_path)
            ]

            self.log(f"Removing watermark ({platform})...")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                creationflags=SUBPROCESS_FLAGS
            )

            return result.returncode == 0 and output_path.exists()

        except Exception as e:
            self.log(f"Watermark removal error: {e}")
            return False

    def cleanup(self):
        """Clean up temporary files"""
        try:
            import shutil
            if self.temp_dir.exists():
                shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass
