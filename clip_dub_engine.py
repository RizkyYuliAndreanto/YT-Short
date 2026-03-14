"""
Clip+Dub Engine - Combines Clipping + Dubbing into a single workflow.

Takes a long YouTube video + user context/pattern, then:
1. Downloads video + subtitles + heatmap
2. AI finds relevant clips based on context (not generic virality)
3. Assembles clips into 30-120s draft
4. AI generates narration script based on context + clip analysis
5. User edits script (interactive)
6. TTS dubbing + subtitle burn → final Shorts video

Reuses: clipper_core.py (download, clip), tts_sync.py (TTS, mix),
        script_generator.py (script gen), video_analyzer.py (analysis)
"""

import os
import json
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Callable, Tuple
from datetime import datetime

from utils.logger import debug_log
from utils.helpers import get_ffmpeg_path, get_ytdlp_path


# ─── Pre-defined Patterns ──────────────────────────────────────────
PATTERNS = {
    "documentary": {
        "id": "documentary",
        "name": "Dokumenter / Fakta Alam",
        "icon": "🌍",
        "description": "Video edukasi, dokumenter alam, sains, sejarah — rangkum jadi fakta-fakta padat yang bikin takjub.",
        "example": "Ringkas dokumenter tentang elang peregrine jadi fakta-fakta menarik 60 detik",
        "tags": ["documentary", "nature", "science", "education", "wildlife", "animal", "history", "planet", "sea", "ocean", "space"],
        "clip_prompt": (
            "Cari klip yang berisi fakta paling menarik dan visual paling memukau. "
            "Prioritaskan: close-up subjek utama, momen aksi dramatis (berburu, terbang, dll), "
            "fakta mengejutkan dengan visual pendukung, dan momen yang menunjukkan skala/perbandingan. "
            "Hindari bagian perkenalan generik dan filler tanpa informasi baru."
        ),
        "script_prompt": (
            "Buat narasi dokumenter singkat yang kaya fakta dan memukau. "
            "ATURAN: "
            "- Hook 3 detik pertama: langsung sebut subjek + fakta paling mengejutkan. "
            "- Setiap segment: 1 fakta utama + detail pendukung yang spesifik (angka, perbandingan). "
            "- Narasi WAJIB sinkron dengan visual: jika klip menunjukkan elang menukik, ceritakan tentang kecepatan menukiknya. "
            "- Gunakan pengetahuanmu untuk menambah fakta menarik yang akurat. "
            "- Akhiri dengan fakta paling mind-blowing atau pertanyaan retoris."
        ),
        "content_type": "narration"
    },
    "profile": {
        "id": "profile",
        "name": "Profil / Tokoh",
        "icon": "👤",
        "description": "Memperkenalkan siapa tokoh, kreator, atau figur dalam video — latar belakang dan daya tariknya.",
        "example": "Perkenalkan siapa Outdoor Boys dan kenapa kontennya menarik",
        "tags": ["profile", "creator", "youtuber", "celebrity", "athlete", "interview", "biography", "who is"],
        "clip_prompt": (
            "Cari klip yang menampilkan tokoh utama: close-up wajah, momen menunjukkan keahlian, "
            "momen emosional atau iconic, dan aksi khas mereka. "
            "Prioritaskan variasi: wajah + aksi + reaksi + pencapaian."
        ),
        "script_prompt": (
            "Buat narasi profil yang menarik tentang tokoh dalam video ini. "
            "ATURAN: "
            "- Hook: pertanyaan retoris atau fakta mengejutkan tentang tokoh. "
            "- Body: siapa mereka, apa keahlian/keunikan, pencapaian paling impressive. "
            "- Close: mengapa penonton harus tahu/follow mereka. "
            "- Jika informasi kurang dari transcript, BOLEH tambahkan dari pengetahuanmu."
        ),
        "content_type": "entertainment"
    },
    "process": {
        "id": "process",
        "name": "Proses / Transformasi",
        "icon": "🔧",
        "description": "Video proses, restorasi, before-after, cooking — rangkum transformasi dari awal ke hasil akhir.",
        "example": "Rangkum proses restorasi mobil tua dari rongsok sampai mengkilap",
        "tags": ["process", "restoration", "repair", "build", "cooking", "recipe", "before after", "transformation", "diy", "craft"],
        "clip_prompt": (
            "Cari klip yang menunjukkan alur transformasi: "
            "1) Kondisi awal (rusak/mentah/kotor), "
            "2) 2-3 tahap pengerjaan paling dramatic, "
            "3) Hasil akhir (reveal). "
            "Pastikan ada kontras visual yang jelas antara sebelum dan sesudah."
        ),
        "script_prompt": (
            "Buat narasi proses transformasi yang satisfying. "
            "ATURAN: "
            "- Hook: tunjukkan kondisi awal yang 'parah' untuk bikin penasaran. "
            "- Body: jelaskan langkah kunci secara singkat, fokus pada momen WOW. "
            "- Reveal: bangun antisipasi sebelum tunjukkan hasil akhir. "
            "- Tone: antusias, pacing cepat, satisfying."
        ),
        "content_type": "entertainment"
    },
    "listicle": {
        "id": "listicle",
        "name": "Listicle / Top N",
        "icon": "🏆",
        "description": "Video ranking, top 10, best of — ambil 3-7 momen terbaik dengan format countdown.",
        "example": "Ambil 5 momen paling epik dari pertandingan UFC ini",
        "tags": ["top", "best", "worst", "ranking", "list", "countdown", "moments", "compilation", "vs", "comparison"],
        "clip_prompt": (
            "Cari 3-7 momen terbaik/paling impactful dari video ini. "
            "Prioritaskan: reaksi emosional tinggi, momen climax, visual dramatic. "
            "Urutkan dari yang bagus ke yang PALING bagus (build suspense)."
        ),
        "script_prompt": (
            "Buat narasi listicle countdown yang bikin penonton stay sampai akhir. "
            "ATURAN: "
            "- Hook: 'Nomor X akan bikin kamu...' (teaser ending). "
            "- Format: countdown dari nomor besar → nomor 1. "
            "- Setiap nomor: mini-hook + penjelasan singkat kenapa masuk list. "
            "- Nomor 1: reveal paling dramatis + reaksi/komentar penutup."
        ),
        "content_type": "entertainment"
    },
    "tutorial": {
        "id": "tutorial",
        "name": "Tutorial / How-To",
        "icon": "📖",
        "description": "Video tutorial atau how-to — padatkan jadi step-by-step singkat yang actionable.",
        "example": "Buat tutorial 60 detik cara edit foto aesthetic di Lightroom",
        "tags": ["tutorial", "how to", "guide", "tips", "trick", "learn", "step", "cara", "setup", "install"],
        "clip_prompt": (
            "Cari klip yang menunjukkan langkah-langkah instruksi inti (aksi nyata). "
            "Potong semua basa-basi, sponsor, dan penjelasan berulang. "
            "Hanya ambil momen demo/aksi yang essential untuk mengikuti tutorial."
        ),
        "script_prompt": (
            "Buat narasi tutorial step-by-step yang ringkas dan actionable. "
            "ATURAN: "
            "- Hook: sebut hasil akhir yang akan dicapai. "
            "- Format: 'Langkah 1: ...', 'Langkah 2: ...', dst. "
            "- Setiap langkah: 1 kalimat aksi + 1 kalimat tips (jika perlu). "
            "- Langsung ke inti, tanpa basa-basi. "
            "- Close: tips bonus atau common mistake yang harus dihindari."
        ),
        "content_type": "tutorial"
    },
    "debunking": {
        "id": "debunking",
        "name": "Mitos vs Fakta",
        "icon": "🔍",
        "description": "Video debunking, myth-busting, atau edukasi yang meluruskan kesalahpahaman.",
        "example": "Bantah 3 mitos tentang hiu yang bikin orang takut berenang",
        "tags": ["myth", "fact", "debunk", "truth", "false", "real", "fake", "misconception", "actually", "wrong"],
        "clip_prompt": (
            "Cari klip yang menunjukkan kontradiksi, pembuktian, atau surprise reveal. "
            "Perhatikan kalimat: 'banyak yang mengira...', 'faktanya...', 'ternyata...'. "
            "Prioritaskan momen visual yang membuktikan fakta (eksperimen, bukti, data)."
        ),
        "script_prompt": (
            "Buat narasi 'Mitos vs Fakta' yang membuat penonton terkejut. "
            "ATURAN: "
            "- Hook: sebut mitos yang dipercaya banyak orang. "
            "- Format per mitos: 'MITOS: [kepercayaan umum] → FAKTA: [kebenaran]'. "
            "- Setiap fakta harus didukung data/angka spesifik. "
            "- Gunakan pengetahuanmu untuk memastikan fakta akurat."
        ),
        "content_type": "narration"
    },
    "highlight": {
        "id": "highlight",
        "name": "Highlight / Teaser",
        "icon": "🎬",
        "description": "Podcast, wawancara, vlog — ambil momen paling seru sebagai teaser yang bikin penasaran.",
        "example": "Ambil pernyataan paling kontroversial dari podcast Deddy Corbuzier",
        "tags": ["podcast", "interview", "vlog", "reaction", "drama", "controversial", "funny", "emotional", "clip"],
        "clip_prompt": (
            "Cari momen dengan emosi tertinggi: pernyataan kontroversial, "
            "reaksi terkejut, momen lucu/dramatis, atau reveal mengejutkan. "
            "Prioritaskan momen yang akan memancing komentar dan share."
        ),
        "script_prompt": (
            "Buat narasi teaser/trailer yang bikin penonton HARUS nonton video full. "
            "ATURAN: "
            "- Hook: provokasi atau pertanyaan kontroversial. "
            "- Body: bangun konteks singkat + tease momen paling seru. "
            "- Close: cliffhanger — jangan kasih jawaban lengkap. "
            "- Tone: dramatis, bikin penasaran."
        ),
        "content_type": "entertainment"
    },
    "custom": {
        "id": "custom",
        "name": "Custom (Manual)",
        "icon": "✏️",
        "description": "Kamu yang tentukan sendiri — tulis instruksi sebebas mungkin sesuai kebutuhanmu.",
        "example": "Tulis konteks dan instruksi detail sesuai kebutuhanmu",
        "tags": ["custom"],
        "clip_prompt": "",
        "script_prompt": "",
        "content_type": "dubbing"
    }
}


# ─── Clip & Duration Recommendation ────────────────────────────────

def recommend_clips_and_duration(video_duration_seconds: int) -> dict:
    """Calculate optimal primary clips, spare clips, and target duration
    based on source video length. Pure logic — no AI needed.
    
    Returns:
        {
            "primary_clips": int,
            "spare_clips": int,
            "target_duration": int,
            "reason": str,
            "detail": str,
        }
    """
    dur_min = video_duration_seconds / 60
    
    # Average output clip length ~12-18s
    avg_clip = 15
    
    if dur_min <= 5:
        target, primary, spare = 30, 3, 2
    elif dur_min <= 10:
        target, primary, spare = 60, 4, 3
    elif dur_min <= 20:
        target, primary, spare = 90, 6, 5
    elif dur_min <= 30:
        target, primary, spare = 90, 7, 7
    elif dur_min <= 45:
        target, primary, spare = 120, 8, 8
    elif dur_min <= 60:
        target, primary, spare = 120, 10, 10
    elif dur_min <= 90:
        target, primary, spare = 150, 12, 12
    else:
        target, primary, spare = 180, 15, 15
    
    total = primary + spare
    dur_str = (f"{int(dur_min)}m" if dur_min < 60
               else f"{int(dur_min//60)}h{int(dur_min%60):02d}m")
    
    reason = (
        f"Video {dur_str} → {primary} klip utama + {spare} cadangan, "
        f"target ~{target} detik"
    )
    detail = (
        f"• {primary} klip utama mengisi durasi ~{target}s "
        f"(rata-rata ~{avg_clip}s/klip)\n"
        f"• {spare} klip cadangan sebagai opsi pengganti jika "
        f"ada klip utama yang kurang bagus\n"
        f"• Total {total} klip diminta ke AI, durasi output bisa "
        f"±10% dari target"
    )
    
    return {
        "primary_clips": primary,
        "spare_clips": spare,
        "target_duration": target,
        "reason": reason,
        "detail": detail,
    }


# ─── AI Recommendation Helpers ─────────────────────────────────────

def fetch_video_info_light(url: str, config: dict = None) -> dict:
    """Fetch video title + description without downloading.
    Returns {"title": ..., "description": ..., "channel": ..., "duration": ...}"""
    import yt_dlp
    
    cookies_path = None
    if config:
        cp = config.get("cookies_path", "cookies.txt")
        if cp and os.path.isfile(cp):
            cookies_path = cp
    
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
    }
    if cookies_path:
        ydl_opts["cookiefile"] = cookies_path
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    
    return {
        "title": info.get("title", ""),
        "description": (info.get("description") or "")[:500],
        "channel": info.get("channel", ""),
        "duration": info.get("duration", 0),
    }


def recommend_pattern_and_context(video_info: dict, config: dict) -> dict:
    """Use AI to recommend best pattern + context suggestions for a video.
    
    Args:
        video_info: {"title": ..., "description": ..., "channel": ..., "duration": ...}
        config: App config with ai_providers
    
    Returns:
        {"pattern_id": str, "pattern_reason": str, "contexts": [str, str, ...]}
    """
    from script_generator import ScriptGenerator
    
    title = video_info.get("title", "Unknown")
    desc = video_info.get("description", "")
    channel = video_info.get("channel", "")
    dur = video_info.get("duration", 0)
    dur_str = f"{dur // 60}:{dur % 60:02d}" if dur else "?"
    
    # Build pattern list for prompt
    pattern_options = []
    for pid, p in PATTERNS.items():
        if pid == "custom":
            continue
        pattern_options.append(
            f'- "{pid}": {p["name"]} — {p["description"]}'
        )
    patterns_text = "\n".join(pattern_options)
    
    prompt = f"""Analisis video YouTube ini dan rekomendasikan pattern + konteks terbaik untuk membuat short video clip dub.

VIDEO INFO:
- Judul: {title}
- Channel: {channel}
- Durasi: {dur_str}
- Deskripsi: {desc[:300]}

PATTERN YANG TERSEDIA:
{patterns_text}

TUGAS:
1. Pilih 1 pattern yang PALING cocok untuk video ini.
2. Jelaskan singkat (1-2 kalimat) MENGAPA pattern itu cocok.
3. Buat 3 konteks/instruksi berbeda yang bisa dipakai user untuk membuat clip dari video ini.
   - Setiap konteks harus spesifik, actionable, dan sesuai dengan isi video.
   - Variasikan angle: informatif, emosional, clickbait-friendly.

RESPOND DALAM FORMAT JSON SAJA (tanpa markdown code block):
{{
  "pattern_id": "id_pattern",
  "pattern_reason": "Alasan singkat kenapa pattern ini cocok",
  "contexts": [
    "Konteks pertama yang spesifik...",
    "Konteks kedua dengan angle berbeda...",
    "Konteks ketiga yang menarik..."
  ]
}}"""

    system_msg = (
        "Kamu adalah AI assistant yang membantu creator membuat short-form content dari video YouTube. "
        "Kamu ahli dalam memilih strategi konten dan menulis brief yang jelas. "
        "Selalu respond dalam JSON valid."
    )
    
    sg = ScriptGenerator(config)
    raw = sg._call_llm(prompt, system_msg)
    
    # Parse JSON from response (handle markdown code blocks)
    import re
    json_match = re.search(r'\{[\s\S]*\}', raw)
    if json_match:
        result = json.loads(json_match.group())
    else:
        raise ValueError(f"AI response is not valid JSON: {raw[:200]}")
    
    # Validate pattern_id exists
    if result.get("pattern_id") not in PATTERNS or result.get("pattern_id") == "custom":
        result["pattern_id"] = "documentary"
    
    # Ensure contexts is a list
    if not isinstance(result.get("contexts"), list):
        result["contexts"] = [str(result.get("contexts", ""))]
    
    return result


CONTENT_TYPE_MAP = {
    "dubbing": "DUBBING",
    "narration": "NARRATION",
    "entertainment": "ENTERTAINMENT",
    "tutorial": "TUTORIAL",
    "shopping": "SHOPPING"
}


class ClipDubEngine:
    """
    Orchestrates Clip+Dub workflow by reusing existing modules.
    
    Pipeline:
    1. Download video (clipper_core → download_video)
    2. Context-aware clipping (AI → find clips matching user context)
    3. Assemble clips into draft (FFmpeg concat)
    4. Generate narration script (script_generator)
    5. Interactive script editing (user loop)
    6. TTS + Mix + Subtitle burn (tts_sync)
    """
    
    def __init__(self, config: Dict, 
                 log_callback: Optional[Callable] = None,
                 progress_callback: Optional[Callable] = None,
                 cancel_check: Optional[Callable] = None,
                 step_callback: Optional[Callable] = None):
        self.config = config
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        self.cancel_check = cancel_check or (lambda: False)
        self.step_callback = step_callback  # (step_num, step_total, step_name, detail)
        
        self.ffmpeg_path = get_ffmpeg_path()
        self.ytdlp_path = get_ytdlp_path()
        
        # Session state
        self.session_dir: Optional[Path] = None
        self.temp_dir: Optional[Path] = None
        self.video_path: Optional[str] = None
        self.srt_path: Optional[str] = None
        self.video_info: Optional[Dict] = None
        self.heatmap_data: Optional[List] = None
        self.transcript: Optional[str] = None
        self.highlights: Optional[List] = None
        self.spare_highlights: Optional[List] = None  # Backup clips
        self.clip_files: Dict[int, str] = {}  # idx -> cut clip path
        self.draft_video_path: Optional[str] = None
        self.script_data: Optional[Dict] = None
        self.final_output: Optional[str] = None
        self._clipper_core = None  # Reusable core instance
        
        # GPU settings
        self._gpu_args = self._detect_gpu()
        
        # Step timing
        self._step_timers: Dict[int, float] = {}  # step_num -> start_time
        self._step_elapsed: Dict[int, float] = {}  # step_num -> elapsed_seconds
        self._pipeline_start: Optional[float] = None
    
    def log(self, msg: str):
        if self.log_callback:
            self.log_callback(msg)
        debug_log(msg)
    
    def set_progress(self, status: str, progress: float):
        if self.progress_callback:
            self.progress_callback(status, progress)
    
    def emit_step(self, step_num: int, step_name: str, detail: str = "",
                  total_steps: int = 6):
        """Emit structured step update for UI progress panel."""
        # End previous step timer
        if self._step_timers:
            prev_step = max(self._step_timers.keys())
            if prev_step != step_num and prev_step in self._step_timers:
                elapsed = time.time() - self._step_timers[prev_step]
                self._step_elapsed[prev_step] = elapsed
                self.log(f"  ⏱ Step {prev_step} selesai dalam {self._format_duration(elapsed)}")
        
        # Start new step timer
        self._step_timers[step_num] = time.time()
        if self._pipeline_start is None:
            self._pipeline_start = time.time()
        
        # Calculate total elapsed
        total_elapsed = time.time() - self._pipeline_start
        elapsed_str = self._format_duration(total_elapsed)
        
        if self.step_callback:
            self.step_callback(step_num, total_steps, step_name, detail)
        
        self.log(f"  ⏱ Total elapsed: {elapsed_str}")
    
    def _finish_step_timer(self, step_num: int):
        """Finish timing for a specific step."""
        if step_num in self._step_timers:
            elapsed = time.time() - self._step_timers[step_num]
            self._step_elapsed[step_num] = elapsed
            self.log(f"  ⏱ Step {step_num} selesai dalam {self._format_duration(elapsed)}")
    
    def get_timing_summary(self) -> str:
        """Get a summary of all step timings."""
        if not self._step_elapsed:
            return "No timing data"
        
        lines = ["⏱ TIMING SUMMARY:"]
        step_names = {
            1: "Download", 2: "Cari Klip", 3: "Assemble",
            4: "Script", 5: "Revisi", 6: "Render"
        }
        total = 0.0
        for sn in sorted(self._step_elapsed.keys()):
            elapsed = self._step_elapsed[sn]
            total += elapsed
            name = step_names.get(sn, f"Step {sn}")
            lines.append(f"  Step {sn} ({name}): {self._format_duration(elapsed)}")
        
        if self._pipeline_start:
            wall = time.time() - self._pipeline_start
            lines.append(f"  Total wall time: {self._format_duration(wall)}")
        
        return "\n".join(lines)
    
    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format seconds into human-readable string."""
        if seconds < 60:
            return f"{seconds:.1f}s"
        minutes = int(seconds // 60)
        secs = seconds % 60
        if minutes < 60:
            return f"{minutes}m {secs:.0f}s"
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours}h {mins}m"
    
    def is_cancelled(self) -> bool:
        return self.cancel_check()
    
    @staticmethod
    def _srt_to_seconds(ts: str) -> float:
        """Convert SRT timestamp (HH:MM:SS,mmm or HH:MM:SS.mmm) to seconds."""
        ts = ts.strip().replace(",", ".")
        parts = ts.split(":")
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        return float(ts)
    
    def _build_cut_cmd(self, start_ts: str, duration: float, output_path: str) -> list:
        """Build FFmpeg cut command with double-seek for accuracy.
        
        Uses coarse pre-input seek + precise post-input seek to avoid
        blue/corrupt frames from keyframe-based seeking.
        -threads 1 prevents async_lock assertion crash.
        -force_key_frames ensures first frame is a keyframe (no blue start).
        """
        start_secs = self._srt_to_seconds(start_ts)
        # Coarse seek: jump to 10s before target (fast, keyframe-based)
        coarse = max(0, start_secs - 10)
        # Fine seek: precise remaining offset (decode-level, accurate)
        fine = start_secs - coarse
        
        # Build GPU args but inject -threads 1 before encoder
        gpu_args = list(self._gpu_args)
        
        return [
            self.ffmpeg_path, "-y",
            "-threads", "1",
            "-ss", f"{coarse:.3f}",
            "-i", self.video_path,
            "-ss", f"{fine:.3f}",
            "-t", f"{duration:.3f}",
            *gpu_args,
            "-force_key_frames", "expr:eq(t,0)",
            "-c:a", "aac", "-b:a", "192k",
            "-threads", "1",
            str(output_path)
        ]
    
    def _get_duration(self, file_path: str) -> float:
        """Get duration of a media file in seconds using ffprobe."""
        try:
            # Build ffprobe path correctly: only replace the filename, not the directory
            ffprobe_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
            ffprobe = os.path.join(os.path.dirname(self.ffmpeg_path), ffprobe_name)
            cmd = [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(file_path)
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            )
            if result.returncode == 0 and result.stdout.strip():
                dur = float(result.stdout.strip())
                if dur > 0:
                    return dur
        except Exception:
            pass
        return 0.0
    
    def _detect_gpu(self) -> list:
        """Detect GPU encoder"""
        gpu_settings = self.config.get("gpu_acceleration", {})
        if not gpu_settings.get("enabled", False):
            return ["-c:v", "libx264", "-preset", "fast", "-crf", "23"]
        try:
            cmd = [self.ffmpeg_path, "-hide_banner", "-encoders"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if "h264_nvenc" in result.stdout:
                return ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23"]
        except Exception:
            pass
        return ["-c:v", "libx264", "-preset", "fast", "-crf", "23"]
    
    # ─── STEP 1: Download ─────────────────────────────────────────────
    
    def download_video(self, url: str) -> Dict:
        """Download video, subtitles, and heatmap using clipper_core."""
        from clipper_core import AutoClipperCore
        
        self.log("━" * 50)
        self.log("[STEP 1/6] 📥 Downloading video...")
        self.emit_step(1, "Download Video", "Memulai download...")
        self.set_progress("Downloading video...", 0.05)
        
        # Create session
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path(self.config.get("output_dir", "output"))
        self.session_dir = output_dir / "sessions" / f"clipdub_{timestamp}"
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir = self.session_dir / "_temp"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        # Get subtitle language preference
        subtitle_lang = self.config.get("subtitle_language", "id")
        
        # Get AI provider config
        ai_providers = self.config.get("ai_providers", {})
        hf_config = ai_providers.get("highlight_finder", {})
        
        core = AutoClipperCore(
            client=None,  # Will use ai_providers
            ffmpeg_path=self.ffmpeg_path,
            ytdlp_path=self.ytdlp_path,
            output_dir=str(self.session_dir),
            model=hf_config.get("model", "llama-3.3-70b-versatile"),
            temperature=self.config.get("temperature", 0.7),
            ai_providers=ai_providers,
            subtitle_language=subtitle_lang,
            log_callback=self.log_callback,
            progress_callback=self.progress_callback,
            cancel_check=self.cancel_check
        )
        core.temp_dir = self.temp_dir
        
        # Enable GPU
        gpu_settings = self.config.get("gpu_acceleration", {})
        if gpu_settings.get("enabled", False):
            core.enable_gpu_acceleration(True)
        
        # Download
        video_path, srt_path, video_info = core.download_video(url)
        
        self.video_path = video_path
        self.srt_path = srt_path
        self.video_info = video_info or {}
        self.heatmap_data = core.heatmap_data
        
        has_subs = srt_path is not None
        has_heatmap = self.heatmap_data is not None
        
        self.log(f"  ✓ Video: {self.video_info.get('title', 'Unknown')}")
        self.log(f"  ✓ Subtitle: {'Yes' if has_subs else 'No'}")
        self.log(f"  ✓ Heatmap: {'Yes (' + str(len(self.heatmap_data)) + ' segments)' if has_heatmap else 'No'}")
        
        if not has_subs:
            self.log("  ⚠️ Video tidak memiliki subtitle!")
            self.log("  ⚠️ Clipping context-aware membutuhkan subtitle sebagai acuan.")
            self.log("  ⚠️ Tanpa subtitle, AI tidak bisa menentukan momen relevan secara akurat.")
        
        self._finish_step_timer(1)
        return {
            "video_path": video_path,
            "srt_path": srt_path,
            "video_info": video_info,
            "has_subtitle": has_subs,
            "has_heatmap": has_heatmap,
            "session_dir": str(self.session_dir)
        }
    
    # ─── STEP 2: Context-Aware Clipping ───────────────────────────────
    
    def find_context_clips(self, user_context: str, pattern_id: str = "custom",
                          primary_clips: int = 7, spare_clips: int = 5,
                          target_duration: int = 90) -> List[Dict]:
        """
        Find clips relevant to the user's context/pattern.
        
        primary_clips: jumlah klip utama yang akan dipakai.
        spare_clips: jumlah klip cadangan untuk opsi pengganti.
        target_duration: estimasi durasi output (fleksibel ±10%).
        
        Returns: primary clips list. Spare clips stored in self.spare_highlights.
        Requires subtitle.
        """
        if not self.srt_path:
            self.log("❌ Tidak bisa melakukan clipping tanpa subtitle.")
            self.log("   Subtitle diperlukan sebagai acuan untuk menentukan momen yang relevan.")
            self.log("   Video tanpa narasi/percakapan (misal: restorasi mekanik tanpa dialog)")
            self.log("   tidak dapat diproses oleh fitur ini.")
            raise Exception(
                "❌ Subtitle tidak tersedia!\n\n"
                "Fitur Clip+Dub memerlukan subtitle sebagai acuan untuk menemukan "
                "momen yang relevan dengan konteks Anda.\n\n"
                "Video tanpa narasi/percakapan (misal: video restorasi mekanik "
                "yang hanya menunjukkan proses tanpa dialog) tidak dapat diproses.\n\n"
                "💡 SOLUSI:\n"
                "1. Gunakan video yang memiliki subtitle/narasi\n"
                "2. Coba bahasa subtitle lain (en, id, auto-generated)\n"
                "3. Untuk video tanpa dialog, gunakan AI Dubbing Studio langsung "
                "dengan video yang sudah di-clip manual"
            )
        
        self.log("━" * 50)
        self.log("[STEP 2/6] 🔍 Finding context-aware clips...")
        self.emit_step(2, "Cari Klip", "Parsing subtitle & analisis AI...")
        self.set_progress("Finding relevant clips...", 0.15)
        
        # Store target duration for downstream use (assemble_draft trimming)
        self.config["_target_duration"] = target_duration
        
        # Get pattern config
        pattern = PATTERNS.get(pattern_id, PATTERNS["custom"])
        
        # Parse transcript
        from clipper_core import AutoClipperCore
        ai_providers = self.config.get("ai_providers", {})
        hf_config = ai_providers.get("highlight_finder", {})
        
        core = AutoClipperCore(
            client=None,
            ffmpeg_path=self.ffmpeg_path,
            ytdlp_path=self.ytdlp_path,
            output_dir=str(self.session_dir),
            model=hf_config.get("model", "llama-3.3-70b-versatile"),
            temperature=self.config.get("temperature", 0.7),
            ai_providers=ai_providers,
            subtitle_language=self.config.get("subtitle_language", "id"),
            log_callback=self.log_callback,
            progress_callback=self.progress_callback,
            cancel_check=self.cancel_check
        )
        core.temp_dir = self.temp_dir
        
        # Transfer heatmap data
        if self.heatmap_data:
            core.heatmap_data = self.heatmap_data
            core.use_heatmap = True
        
        # Parse SRT
        self.transcript = core.parse_srt(self.srt_path)
        
        if not self.transcript or len(self.transcript.strip()) < 50:
            raise Exception("Transcript terlalu pendek atau kosong. Video mungkin tidak punya narasi.")
        
        # Request primary + spare + buffer from AI
        total_requested = primary_clips + spare_clips + 5
        self.log(f"  📊 Requesting {total_requested} clips ({primary_clips} utama + {spare_clips} cadangan)")
        
        # Build context-aware system prompt (judul video diinjeksi untuk akurasi lebih baik)
        video_title = self.video_info.get("title", "") if self.video_info else ""
        if video_title:
            self.log(f"  📺 Judul video digunakan sebagai konteks tambahan: \"{video_title}\"")
        
        context_prompt = self._build_context_clip_prompt(
            user_context, pattern, total_requested, target_duration
        )
        
        # Override system prompt temporarily
        original_prompt = core.system_prompt
        core.system_prompt = context_prompt
        
        # Find highlights (force_system_prompt=True to keep our context-aware prompt
        # even for long transcripts that would normally switch to compact prompt)
        self.set_progress("AI analyzing transcript...", 0.20)
        highlights = core.find_highlights(self.transcript, self.video_info, total_requested,
                                            min_duration=10, max_duration=50,
                                            force_system_prompt=True)
        
        # If not enough clips, retry with relaxed duration filter
        if len(highlights) < primary_clips:
            self.log(f"  ⚠ Only {len(highlights)} clips in 10-50s range, retrying with wider range...")
            core.system_prompt = context_prompt
            highlights_wider = core.find_highlights(self.transcript, self.video_info, total_requested,
                                                      min_duration=8, max_duration=70,
                                                      force_system_prompt=True)
            # Merge: keep originals + add new unique ones
            existing_starts = {h.get("start_time") for h in highlights}
            for h in highlights_wider:
                if h.get("start_time") not in existing_starts:
                    highlights.append(h)
                    existing_starts.add(h.get("start_time"))
        
        # Restore
        core.system_prompt = original_prompt
        
        if not highlights:
            raise Exception("AI tidak menemukan klip yang relevan dengan konteks yang diberikan.")
        
        # ── Frame Analysis: score clips for visual interest ──
        self.set_progress("Analyzing frames for visual content...", 0.30)
        highlights = self._score_and_filter_clips(highlights)
        
        # Split into primary + spare
        self.highlights = highlights[:primary_clips]
        self.spare_highlights = highlights[primary_clips:]
        
        primary_count = len(self.highlights)
        spare_count = len(self.spare_highlights)
        self.log(f"  ✓ Found {len(highlights)} clips ({primary_count} primary + {spare_count} spare)")
        
        # Auto-reorder: pindahkan clip "best_for_hook" ke posisi pertama
        # agar hook menampilkan objek utama secara jelas
        self._reorder_hook_clip()
        
        for i, h in enumerate(highlights, 1):
            hm = h.get('heatmap_score', 0)
            hm_str = f" | 📊{hm:.0%}" if hm > 0 else ""
            vs = h.get('visual_subject', '')
            vs_str = f" | 👁️{vs}" if vs else ""
            tag = "🔵" if i <= primary_count else "⚪"
            self.log(f"    {tag} {i}. [{h['start_time']} → {h['end_time']}] {h['title']}{hm_str}{vs_str}")
        
        # Store clipper core for later reuse
        self._clipper_core = core
        
        self._finish_step_timer(2)
        return self.highlights
    
    def _reorder_hook_clip(self):
        """Move the best_for_hook clip to position 0 for a strong opening.
        
        The AI marks clips with 'best_for_hook': true when the main visual
        subject is clearly visible. This clip should be first so the hook
        immediately shows the topic's main object.
        """
        if not self.highlights or len(self.highlights) < 2:
            return
        
        hook_idx = None
        for i, h in enumerate(self.highlights):
            if h.get("best_for_hook", False) and i > 0:
                hook_idx = i
                break
        
        if hook_idx is not None:
            hook_clip = self.highlights.pop(hook_idx)
            # Transfer hook_text to this clip if it doesn't have one
            if not hook_clip.get("hook_text") and self.highlights:
                hook_clip["hook_text"] = self.highlights[0].get("hook_text", "")
                if "hook_text" in self.highlights[0]:
                    del self.highlights[0]["hook_text"]
            self.highlights.insert(0, hook_clip)
            self.log(f"  🎯 Auto-reorder: Clip '{hook_clip['title'][:40]}' dipindah ke posisi 1 (objek utama terlihat jelas)")
    
    def _score_and_filter_clips(self, highlights: List[Dict]) -> List[Dict]:
        """Score clips using frame analysis and filter out visually empty ones.
        
        Uses OpenCV to sample frames from each clip's timestamps and measure
        visual interest (edge density, color variance, contours).
        Clips with low scores (e.g., plain sky, blank screens) get deprioritized.
        """
        if not self.video_path or not os.path.exists(self.video_path):
            return highlights
        
        try:
            from utils.frame_analyzer import FrameAnalyzer
            analyzer = FrameAnalyzer(self.ffmpeg_path)
        except ImportError:
            self.log("  ⚠ FrameAnalyzer not available, skipping frame scoring")
            return highlights
        
        self.log(f"  🔍 Scoring {len(highlights)} clips with frame analysis...")
        
        scored = []
        for i, h in enumerate(highlights):
            try:
                start_sec = self._srt_to_seconds(h.get("start_time", "00:00:00,000"))
                duration = h.get("duration_seconds", 20)
                
                result = analyzer.score_clip(self.video_path, start_sec, duration, sample_count=3)
                h["frame_score"] = result
                
                score = result.get("interest_score", 0)
                has_sub = result.get("has_subject", False)
                tag = "✓" if has_sub else "✗"
                self.log(f"    {tag} Clip {i+1}: score={score:.3f} subject={has_sub} | {h['title'][:35]}")
            except Exception as e:
                h["frame_score"] = {"interest_score": 0.5, "has_subject": True}
                self.log(f"    ⚠ Clip {i+1}: frame analysis failed ({e})")
            
            scored.append(h)
        
        # Sort: clips WITH subject first, then by combined score (AI virality + frame interest)
        for h in scored:
            fs = h.get("frame_score", {})
            ai_score = h.get("virality_score", 5) / 10.0  # Normalize to 0-1
            frame_score = fs.get("interest_score", 0.5)
            has_subject = 1.0 if fs.get("has_subject", True) else 0.0
            # Combined: 40% frame, 30% AI, 30% subject presence
            h["_combined_score"] = has_subject * 0.30 + frame_score * 0.40 + ai_score * 0.30
        
        scored.sort(key=lambda x: x.get("_combined_score", 0), reverse=True)
        
        # Remove duplicates: if two clips have very similar frame scores AND timestamps, keep best
        filtered = self._deduplicate_by_visual(scored)
        
        good = [h for h in filtered if h.get("frame_score", {}).get("has_subject", True)]
        weak = [h for h in filtered if not h.get("frame_score", {}).get("has_subject", True)]
        
        self.log(f"  ✓ Frame analysis: {len(good)} good clips, {len(weak)} weak clips")
        
        # Return good clips first, then weak as fallback
        return good + weak
    
    def _deduplicate_by_visual(self, clips: List[Dict]) -> List[Dict]:
        """Remove clips that actually overlap in time range.
        
        Only removes clips whose time ranges overlap each other.
        Keeps the one with higher combined score (already sorted).
        """
        if not clips:
            return clips
        
        unique = []
        for clip in clips:
            try:
                start = self._srt_to_seconds(clip.get("start_time", "00:00:00,000"))
                end = self._srt_to_seconds(clip.get("end_time", clip.get("start_time", "00:00:00,000")))
            except:
                unique.append(clip)
                continue
            
            is_dup = False
            for existing in unique:
                try:
                    ex_start = self._srt_to_seconds(existing.get("start_time", "00:00:00,000"))
                    ex_end = self._srt_to_seconds(existing.get("end_time", existing.get("start_time", "00:00:00,000")))
                except:
                    continue
                # Only deduplicate if time ranges actually OVERLAP
                overlaps = (ex_start <= start < ex_end) or (start <= ex_start < end)
                if overlaps:
                    is_dup = True
                    break
            
            if not is_dup:
                unique.append(clip)
        
        if len(unique) < len(clips):
            self.log(f"  🔄 Deduplicated: {len(clips)} → {len(unique)} unique clips")
        
        return unique
    
    def _build_context_clip_prompt(self, user_context: str, pattern: Dict,
                                   num_clips: int, target_duration: int) -> str:
        """Build a system prompt for context-aware clip finding."""
        
        pattern_clip_guide = pattern.get("clip_prompt", "")
        
        # Heatmap context
        heatmap_context = ""
        if self.heatmap_data:
            from clipper_core import AutoClipperCore
            temp_core = AutoClipperCore.__new__(AutoClipperCore)
            temp_core.heatmap_data = self.heatmap_data
            temp_core.use_heatmap = True
            heatmap_context = temp_core.format_heatmap_for_prompt()
        
        # Bangun konteks video dari judul & deskripsi untuk membantu AI memahami topik
        video_title = ""
        video_desc_snippet = ""
        if self.video_info:
            video_title = self.video_info.get("title", "")
            raw_desc = self.video_info.get("description", "")
            if raw_desc:
                # Ambil 200 karakter pertama deskripsi (biasanya ringkasan topik)
                video_desc_snippet = raw_desc[:200].strip()
        
        # Gabungkan judul video + konteks user agar AI paham topik lengkap
        enriched_context = ""
        if video_title:
            enriched_context += f"📺 VIDEO: \"{video_title}\"\n"
            if video_desc_snippet:
                enriched_context += f"📝 DESKRIPSI: {video_desc_snippet}\n"
            enriched_context += f"\n🎯 PERMINTAAN USER:\n{user_context}"
        else:
            enriched_context = user_context
        
        clip_count_rule = f"""1. Cari {num_clips} segment yang PALING RELEVAN dengan konteks di atas
   - Setiap clip berdurasi 10-45 detik (total gabungan target: ~{target_duration} detik)
   - VARIASIKAN durasi clip (jangan semua 30 detik)
   - Urutkan berdasarkan RELEVANSI & KUALITAS konten"""
        
        prompt = f"""Kamu adalah AI Video Clipper yang bertugas menemukan segment video yang RELEVAN dengan konteks yang diberikan user.

KONTEKS PENCARIAN:
{enriched_context}

INSTRUKSI PENTING:
- Gunakan JUDUL VIDEO di atas untuk memahami topik utama dan OBJEK UTAMA video (misal: elang, kucing, mobil, dll)
- Kombinasikan pemahaman topik video + permintaan user untuk menemukan segment terbaik
- Jika permintaan user kurang spesifik, gunakan judul video sebagai panduan topik

{'PANDUAN PATTERN (' + pattern.get("name", "") + '):' if pattern_clip_guide else ''}
{pattern_clip_guide}

{heatmap_context}

{'{video_context}'}

ATURAN CLIPPING:
{clip_count_rule}
2. Clip HARUS berisi momen yang mendukung konteks/cerita yang diminta
3. WAJIB gunakan timestamp dari transcript — jangan karang timestamp
4. Urutkan clip secara kronologis agar alur cerita logis
5. Jika ada heatmap data, prioritaskan segment yang engagement-nya tinggi DAN relevan
6. KUALITAS VARIASI: Setiap clip harus menampilkan momen/informasi BERBEDA
   - JANGAN ambil segment yang isinya pengulangan/mirip
   - Pastikan setiap clip punya nilai informasi baru
   - Hindari segment yang hanya menampilkan teks/grafik tanpa narasi bermakna
   - SKIP bagian intro/outro yang generik atau layar hitam/teks statis
7. TRANSISI ALAMI: Pilih clip yang ujung segment-nya bisa tersambung logis
   - Akhir clip A harus bisa mengalir ke awal clip B
   - Hindari pemotongan di tengah kalimat

🎯 ATURAN VISUAL OBJECT (SANGAT PENTING):
8. IDENTIFIKASI OBJEK UTAMA dari judul video dan konteks user
   - Contoh: judul "Elang Peregrine" → objek utama = elang
   - Contoh: judul "Review iPhone 16" → objek utama = iPhone
9. PRIORITASKAN segment dimana OBJEK UTAMA sedang TERLIHAT atau dibahas secara detail
   - Pilih segment yang mendeskripsikan penampilan/aksi/gerakan objek utama
   - HINDARI segment yang hanya membahas latar belakang umum tanpa objek (misal: hanya langit, rumput, gedung tanpa objek utama)
   - Cari keyword di transcript yang menunjukkan objek sedang on-screen: "terlihat", "tampak", "di sini", "ini dia", "perhatikan", "lihat", "menunjukkan", "memperlihatkan", dll
10. HOOK CLIP (clip pertama) WAJIB menampilkan objek utama secara jelas
    - Pilih segment dimana narrator sedang mendeskripsikan objek secara langsung
    - Jika clip pertama kronologis tidak menampilkan objek, CARI clip lain yang menampilkan objek dan tandai sebagai "best_for_hook": true
11. Setiap clip beri field "visual_subject" yang menjelaskan apa yang TERLIHAT di layar
    - Contoh: "Elang peregrine terbang menukik" atau "Grafik kecepatan elang" atau "Langit biru tanpa objek"
    - Ini membantu untuk menghindari clip yang hanya menampilkan latar kosong

TRANSCRIPT:
{'{transcript}'}

OUTPUT FORMAT (WAJIB JSON VALID):
[
  {{
    "start_time": "HH:MM:SS,mmm",
    "end_time": "HH:MM:SS,mmm",
    "title": "Judul singkat segment (max 60 karakter)",
    "description": "Kenapa segment ini relevan dengan konteks (max 150 karakter)",
    "visual_subject": "Apa yang TERLIHAT di layar pada segment ini (max 80 karakter)",
    "best_for_hook": false,
    "virality_score": 7,
    "hook_text": "Hook menarik untuk seluruh video (hanya di item pertama, max 15 kata)",
    "duration_seconds": 30
  }}
]

PENTING:
- Output HANYA JSON array, tanpa markdown
- Timestamp HARUS ada di transcript
- Clip harus saling melengkapi untuk membentuk satu cerita utuh
- virality_score 1-10 berdasarkan relevansi dengan konteks (bukan virality umum)
- Item PERTAMA WAJIB punya "hook_text" yang menarik untuk opening video
- MINIMAL 1 clip harus punya "best_for_hook": true (clip dimana objek utama paling jelas terlihat)
- Jika objek utama tidak jelas terlihat di clip manapun, tetap pilih clip dengan DESKRIPSI PALING DETAIL tentang objek tersebut"""
        
        return prompt
    
    # ─── STEP 2b: Cut Individual Clips ─────────────────────────────────
    
    def cut_individual_clips(self, highlights: Optional[List] = None) -> Dict[int, str]:
        """
        Cut each highlight as a separate clip file for preview.
        Returns dict of {index: clip_path}.
        Also cuts spare clips for replacement.
        """
        all_highlights = list(highlights or self.highlights or [])
        # Also cut spares
        if self.spare_highlights:
            all_highlights = all_highlights + self.spare_highlights
        
        if not all_highlights:
            raise Exception("No clips to cut")
        
        self.log("━" * 50)
        self.log("[STEP 2b] ✂️ Cutting individual clips for preview...")
        self.emit_step(2, "Cari Klip", "Memotong klip untuk preview...")
        
        clips_dir = self.temp_dir / "clips_individual"
        clips_dir.mkdir(exist_ok=True)
        
        self.clip_files = {}
        total = len(all_highlights)
        
        for i, h in enumerate(all_highlights):
            if self.is_cancelled():
                raise Exception("Cancelled by user")
            
            start = h["start_time"].replace(",", ".")
            end = h["end_time"].replace(",", ".")
            
            pct = 0.25 + (0.15 * i / total)
            self.set_progress(f"Cutting clip {i+1}/{total}...", pct)
            
            clip_path = clips_dir / f"clip_{i:03d}.mp4"
            duration = h.get("duration_seconds", 30)
            
            cmd = self._build_cut_cmd(start, duration, str(clip_path))
            
            result = subprocess.run(cmd, capture_output=True, text=True,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            
            if result.returncode != 0:
                self.log(f"  ⚠ Failed: clip {i+1}: {result.stderr[-200:]}")
                continue
            
            h["clip_path"] = str(clip_path)
            self.clip_files[i] = str(clip_path)
            
            # Measure ACTUAL duration (AI estimate may be inaccurate)
            actual_dur = self._get_duration(str(clip_path))
            if actual_dur > 0:
                h["duration_seconds"] = round(actual_dur, 2)
            
            self.log(f"  ✓ Clip {i+1}: [{start} → {end}] {actual_dur:.1f}s {h['title'][:40]}")
        
        self.log(f"  ✓ Cut {len(self.clip_files)} clips total")
        self.set_progress("Clips ready for preview", 0.40)
        return self.clip_files
    
    def cut_single_clip(self, highlight: Dict, index: int) -> Optional[str]:
        """
        Cut a single clip (for replacement). Returns clip path or None.
        """
        clips_dir = self.temp_dir / "clips_individual"
        clips_dir.mkdir(exist_ok=True)
        
        start = highlight["start_time"].replace(",", ".")
        end = highlight["end_time"].replace(",", ".")
        
        clip_path = clips_dir / f"clip_{index:03d}_alt.mp4"
        duration = highlight.get("duration_seconds", 30)
        
        cmd = self._build_cut_cmd(start, duration, str(clip_path))
        
        result = subprocess.run(cmd, capture_output=True, text=True,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        
        if result.returncode != 0:
            self.log(f"  ⚠ Failed to cut replacement clip: {result.stderr[-200:]}")
            return None
        
        highlight["clip_path"] = str(clip_path)
        return str(clip_path)
    
    def find_replacement_clip(self, exclude_indices: List[int] = None) -> Optional[Dict]:
        """
        Pop the next spare clip as a replacement.
        If no spares, try AI to find one more.
        Returns highlight dict with clip_path set, or None.
        """
        if self.spare_highlights:
            replacement = self.spare_highlights.pop(0)
            # Cut it if not already cut
            if not replacement.get("clip_path"):
                idx = len(self.clip_files) + 100  # Avoid index collision
                path = self.cut_single_clip(replacement, idx)
                if not path:
                    return None
            return replacement
        
        # No spares — try AI for one more
        self.log("  ⚠ No spare clips left, asking AI for one more...")
        if not self._clipper_core or not self.transcript:
            return None
        
        try:
            # Collect timestamps to exclude
            exclude_ranges = []
            all_clips = list(self.highlights or []) + (self.spare_highlights or [])
            for h in all_clips:
                exclude_ranges.append(f"{h['start_time']} - {h['end_time']}")
            
            extra_prompt = (
                f"\n\nSUDAH DIGUNAKAN (JANGAN ULANGI):\n" + 
                "\n".join(exclude_ranges) +
                f"\n\nCari 1 segment BARU yang berbeda dari yang sudah ada."
            )
            
            original_prompt = self._clipper_core.system_prompt
            self._clipper_core.system_prompt += extra_prompt
            
            new_highlights = self._clipper_core.find_highlights(
                self.transcript, self.video_info, 1)
            
            self._clipper_core.system_prompt = original_prompt
            
            if new_highlights:
                h = new_highlights[0]
                idx = len(self.clip_files) + 200
                path = self.cut_single_clip(h, idx)
                if path:
                    return h
        except Exception as e:
            self.log(f"  ⚠ Failed to find replacement: {e}")
        
        return None
    
    # ─── STEP 3: Assemble Draft ───────────────────────────────────────
    
    def assemble_draft(self, selected_highlights: Optional[List] = None,
                      convert_portrait: bool = True,
                      transition: str = "none",
                      transition_duration: float = 0.5,
                      add_hook: bool = False,
                      hook_voice: str = "id-ID-ArdiNeural") -> str:
        """
        Concatenate selected clips (already cut) into a single draft video.
        If clips are not pre-cut, cuts them first.
        Converts to 9:16 portrait for Shorts.
        
        transition: "none", "fade", "dissolve", "wipe_left", "wipe_right"
        transition_duration: durasi transisi dalam detik (0.3-1.0)
        add_hook: tambah hook scene di awal video
        hook_voice: voice Edge TTS untuk hook
        """
        highlights = selected_highlights or self.highlights
        if not highlights:
            raise Exception("No clips to assemble")
        
        self.log("━" * 50)
        self.log("[STEP 3/6] 🎬 Assembling draft video...")
        self.emit_step(3, "Assemble Draft", "Menggabungkan klip...")
        self.set_progress("Assembling clips...", 0.45)
        
        clips_dir = self.temp_dir / "clips"
        clips_dir.mkdir(exist_ok=True)
        
        clip_files = []
        total = len(highlights)
        
        for i, h in enumerate(highlights):
            if self.is_cancelled():
                raise Exception("Cancelled by user")
            
            # Use pre-cut clip if available
            if h.get("clip_path") and os.path.exists(h["clip_path"]):
                clip_files.append(Path(h["clip_path"]))
                self.log(f"  ✓ Clip {i+1}: {h['title'][:40]} (pre-cut)")
                continue
            
            # Otherwise cut on-the-fly
            start = h["start_time"].replace(",", ".")
            end = h["end_time"].replace(",", ".")
            
            pct = 0.45 + (0.10 * i / total)
            self.set_progress(f"Cutting clip {i+1}/{total}...", pct)
            
            clip_path = clips_dir / f"clip_{i:03d}.mp4"
            duration = h.get("duration_seconds", 30)
            
            cmd = self._build_cut_cmd(start, duration, str(clip_path))
            
            result = subprocess.run(cmd, capture_output=True, text=True,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            
            if result.returncode != 0:
                self.log(f"  ⚠ Failed to cut clip {i+1}: {result.stderr[-200:]}")
                continue
            
            h["clip_path"] = str(clip_path)
            clip_files.append(clip_path)
            self.log(f"  ✓ Clip {i+1}: [{start} → {end}] {h['title'][:40]}")
        
        if not clip_files:
            raise Exception("Semua clip gagal di-cut. Cek format video.")
        
        # Convert each clip to portrait BEFORE concatenation
        # This allows per-clip smart cropping (each clip may have subject in different position)
        portrait_clips = clip_files
        if convert_portrait:
            self.set_progress("Smart portrait crop per-clip...", 0.52)
            portrait_clips = self._crop_clips_to_portrait(clip_files, highlights)
        
        # Concatenate portrait clips with optional transitions
        self.set_progress("Concatenating clips...", 0.55)
        draft_path = self.temp_dir / "draft_portrait.mp4" if convert_portrait else self.temp_dir / "draft_landscape.mp4"
        
        if transition != "none" and len(portrait_clips) > 1:
            self._concat_with_transitions(portrait_clips, str(draft_path), 
                                          transition, transition_duration)
        else:
            self._concat_simple(portrait_clips, str(draft_path))
        
        self.log(f"  ✓ Concatenated {len(portrait_clips)} clips" + 
                 (f" ({transition} transition)" if transition != "none" else ""))
        
        # Portrait already applied per-clip
        self.draft_video_path = str(draft_path)
        if convert_portrait:
            self.log("  ✓ Per-clip smart portrait crop applied")
        
        # Get draft duration
        draft_duration = self._get_duration(self.draft_video_path)
        
        # Validate draft duration — if 0, concat likely failed silently
        if draft_duration <= 0 and highlights:
            expected_dur = sum(h.get("duration_seconds", 25) for h in highlights)
            self.log(f"  ⚠ Draft duration=0 (expected ~{expected_dur:.0f}s), retrying with simple concat...")
            self._concat_simple(portrait_clips, str(draft_path))
            draft_duration = self._get_duration(self.draft_video_path)
            if draft_duration <= 0:
                self.log(f"  ⚠ Duration still 0, using expected duration {expected_dur:.0f}s")
                draft_duration = expected_dur
        
        # Enforce target duration: trim if draft is too long
        target_dur = self.config.get("_target_duration", 0)
        if target_dur > 0 and draft_duration > target_dur * 1.1:
            self.log(f"  ✂️ Draft {draft_duration:.0f}s exceeds target {target_dur}s, trimming...")
            trimmed_path = self.temp_dir / "draft_trimmed.mp4"
            cmd = [
                self.ffmpeg_path, "-y",
                "-i", self.draft_video_path,
                "-t", f"{target_dur:.3f}",
                "-c:v", "copy", "-c:a", "copy",
                str(trimmed_path)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            if result.returncode == 0 and os.path.exists(str(trimmed_path)):
                self.draft_video_path = str(trimmed_path)
                draft_duration = self._get_duration(self.draft_video_path)
                self.log(f"  ✓ Trimmed to {draft_duration:.0f}s")
        
        # Add hook scene di awal video (jika diminta)
        if add_hook and self.highlights:
            self.set_progress("Menambahkan hook scene...", 0.59)
            hook_text = self.highlights[0].get("hook_text", "")
            if not hook_text:
                # Fallback: gunakan judul video
                hook_text = (self.video_info or {}).get("title", "")
            
            if hook_text:
                hooked_path = self.temp_dir / "draft_hooked.mp4"
                hook_dur = self._add_hook_scene(
                    self.draft_video_path, hook_text, str(hooked_path),
                    voice=hook_voice
                )
                if hook_dur > 0 and os.path.exists(str(hooked_path)):
                    self.draft_video_path = str(hooked_path)
                    draft_duration += hook_dur
                    self.log(f"  🎣 Hook: \"{hook_text[:50]}\" ({hook_dur:.1f}s)")
        
        self.log(f"  ✓ Draft video: {draft_duration:.1f}s")
        
        self._finish_step_timer(3)
        return self.draft_video_path
    
    def _convert_portrait(self, input_path: str, output_path: str):
        """Convert video to 9:16 portrait using object-aware crop.
        
        Analyzes frames to find where the main visual subject is, then
        crops around that position instead of always center.
        Falls back to center crop if analysis fails.
        """
        self.log("  Converting to 9:16 portrait (smart object-aware crop)...")
        
        # Try to find best horizontal crop position using frame analysis
        crop_x = 0.5  # Default: center
        try:
            from utils.frame_analyzer import FrameAnalyzer
            analyzer = FrameAnalyzer(self.ffmpeg_path)
            
            duration = self._get_duration(input_path)
            if duration > 0:
                crop_x = analyzer.find_best_crop_x(input_path, 0, duration, sample_count=7)
                if abs(crop_x - 0.5) > 0.05:  # Only log if significantly off-center
                    self.log(f"    📐 Object detected at x={crop_x:.2f} (0.5=center)")
                else:
                    self.log(f"    📐 Object near center (x={crop_x:.2f})")
        except Exception as e:
            self.log(f"    ⚠ Frame analysis failed, using center crop: {e}")
            crop_x = 0.5
        
        self._smart_crop_portrait(input_path, output_path, crop_x)
    
    def _smart_crop_portrait(self, input_path: str, output_path: str, center_x: float = 0.5):
        """Crop to 9:16 portrait at a specific horizontal position.
        
        center_x: normalized horizontal position (0.0=left, 0.5=center, 1.0=right)
        Uses FFmpeg crop filter with calculated x offset.
        Uses min(crop_w, iw) to handle videos narrower than 9:16.
        """
        # crop_w = min(ih*9/16, iw) to handle narrow videos
        # x_offset clamped to valid range
        crop_w = "'min(ih*9/16,iw)'"
        x_expr = f"'max(0,(iw-ih*9/16)*{center_x:.3f})'"
        crop_filter = f"crop={crop_w}:ih:{x_expr}:0,scale=1080:1920"
        
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", input_path,
            "-vf", crop_filter,
            *self._gpu_args,
            "-bf", "0",
            "-c:a", "aac",
            str(output_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if result.returncode != 0:
            # Fallback: simple center crop
            self.log(f"    ⚠ Smart crop failed, falling back to center crop")
            self._center_crop_portrait(input_path, output_path)
    
    def _center_crop_portrait(self, input_path: str, output_path: str):
        """Fallback: simple center crop to 9:16."""
        crop_filter = "crop='min(ih*9/16,iw)':ih,scale=1080:1920"
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", input_path,
            "-vf", crop_filter,
            *self._gpu_args,
            "-bf", "0",
            "-c:a", "aac",
            str(output_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if result.returncode != 0:
            raise Exception(f"Portrait crop failed: {result.stderr[-300:]}")
    
    def _has_video_stream(self, file_path: str) -> bool:
        """Check if file has at least one video stream using ffprobe."""
        try:
            ffprobe_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
            ffprobe = os.path.join(os.path.dirname(self.ffmpeg_path), ffprobe_name)
            cmd = [
                ffprobe, "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_type",
                "-of", "csv=p=0",
                str(file_path)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            return result.returncode == 0 and "video" in result.stdout.strip()
        except Exception:
            return False

    def _has_audio_stream(self, file_path: str) -> bool:
        """Check if file has at least one audio stream."""
        try:
            ffprobe_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
            ffprobe = os.path.join(os.path.dirname(self.ffmpeg_path), ffprobe_name)
            cmd = [
                ffprobe, "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=codec_type",
                "-of", "csv=p=0",
                str(file_path)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            return result.returncode == 0 and "audio" in (result.stdout or "").strip().lower()
        except Exception:
            return False

    def _normalize_clip_for_transition(self, input_path: str, output_path: str):
        """Normalize clip stream format so xfade chain gets uniform inputs.

        Produces H.264/AAC, 1080x1920, 30fps, yuv420p, stereo 48k.
        If source has no audio stream, injects silent audio.
        """
        has_audio = self._has_audio_stream(input_path)

        base_cmd = [
            self.ffmpeg_path, "-y",
            "-threads", "1",
            "-i", input_path,
        ]

        if not has_audio:
            base_cmd.extend([
                "-f", "lavfi",
                "-i", "anullsrc=r=48000:cl=stereo",
            ])

        base_cmd.extend([
            "-map", "0:v:0",
            "-map", "0:a:0" if has_audio else "1:a:0",
            "-vf", "scale=1080:1920:flags=lanczos,fps=30,format=yuv420p",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-r", "30",
            "-af", "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo",
            "-c:a", "aac",
            "-ar", "48000",
            "-ac", "2",
            "-shortest",
            output_path,
        ])

        result = subprocess.run(base_cmd, capture_output=True, text=True,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if result.returncode != 0:
            raise Exception(f"Normalize transition clip failed: {result.stderr[-300:]}")
    
    def _crop_clips_to_portrait(self, clip_files: list, highlights: list) -> list:
        """Crop each clip to 9:16 portrait individually with per-clip object detection.
        
        Strategy per clip:
        1. Sample frames to find subject position spread
        2. If subject stays roughly in one area → fast FFmpeg static crop
        3. If subject moves significantly → use clipper_core's per-frame tracking
        
        Returns list of portrait clip paths.
        """
        try:
            from utils.frame_analyzer import FrameAnalyzer
            analyzer = FrameAnalyzer(self.ffmpeg_path)
            use_analyzer = True
        except ImportError:
            analyzer = None
            use_analyzer = False
        
        # Check if clipper_core per-frame tracking is available
        has_core_tracking = False
        try:
            from clipper_core import AutoClipperCore
            has_core_tracking = True
        except ImportError:
            pass
        
        portrait_dir = self.temp_dir / "clips_portrait"
        portrait_dir.mkdir(exist_ok=True)
        
        portrait_clips = []
        total = len(clip_files)
        
        for i, clip_path in enumerate(clip_files):
            if self.is_cancelled():
                raise Exception("Cancelled by user")
            
            portrait_path = portrait_dir / f"portrait_{i:03d}.mp4"
            crop_x = 0.5  # Default center
            use_tracking = False  # Whether to use per-frame tracking
            manual_crop = highlights[i].get("manual_crop") if i < len(highlights) else None

            # 1) Manual crop from Portrait Studio has highest priority
            if manual_crop and manual_crop.get("enabled", True):
                try:
                    self.log(f"    🧭 Clip {i+1}/{total}: applying manual portrait crop")
                    self._manual_crop_portrait_cv2(
                        str(clip_path),
                        str(portrait_path),
                        manual_crop
                    )
                    if os.path.exists(str(portrait_path)) and self._has_video_stream(str(portrait_path)):
                        portrait_clips.append(portrait_path)
                        continue
                except Exception as e:
                    self.log(f"    ⚠ Manual crop failed clip {i+1}, fallback ke auto: {e}")
            
            # Analyze subject position across frames
            if use_analyzer:
                try:
                    dur = self._get_duration(str(clip_path))
                    if dur > 0:
                        # Sample MORE frames (7) to detect movement pattern
                        crop_x = analyzer.find_best_crop_x(str(clip_path), 0, dur, sample_count=7)
                        
                        # Check if the subject MOVES significantly across the clip
                        # by comparing positions at start vs middle vs end
                        spread = self._check_subject_spread(analyzer, str(clip_path), dur)
                        
                        if spread > 0.15 and has_core_tracking:
                            # Subject moves >15% of frame width → need per-frame tracking
                            use_tracking = True
                            self.log(f"    🎯 Clip {i+1}/{total}: subject moves (spread={spread:.2f}), using frame tracking")
                        else:
                            # Blend with highlight frame_score if available
                            if i < len(highlights):
                                fs = highlights[i].get("frame_score", {})
                                region = fs.get("best_region", {})
                                if region and region.get("density", 0) > 0.01:
                                    fs_x = region.get("center_x", 0.5)
                                    crop_x = crop_x * 0.6 + fs_x * 0.4
                                    crop_x = max(0.15, min(0.85, crop_x))
                except Exception:
                    crop_x = 0.5
            
            try:
                if use_tracking:
                    # Use clipper_core's per-frame tracking (face/body detection + smoothing)
                    try:
                        self._tracking_crop_portrait(str(clip_path), str(portrait_path))
                    except Exception as e:
                        self.log(f"    ⚠ Frame tracking failed, using static crop: {e}")
                        self._smart_crop_portrait(str(clip_path), str(portrait_path), crop_x)
                else:
                    position = "center" if abs(crop_x - 0.5) < 0.05 else f"x={crop_x:.2f}"
                    self.log(f"    📐 Clip {i+1}/{total}: crop at {position}")
                    self._smart_crop_portrait(str(clip_path), str(portrait_path), crop_x)
            except Exception as e:
                self.log(f"    ⚠ Portrait crop failed clip {i+1}, using landscape: {e}")
            
            # Validate output: must exist AND have video stream
            if os.path.exists(str(portrait_path)) and self._has_video_stream(str(portrait_path)):
                portrait_clips.append(portrait_path)
            else:
                # Fallback: use original (landscape)
                self.log(f"    ↩ Clip {i+1}: fallback to landscape")
                portrait_clips.append(clip_path)
        
        return portrait_clips

    @staticmethod
    def _interpolate_manual_center_x(t_sec: float, base_center_x: float, keyframes: list) -> float:
        """Interpolate center_x at time t using linear interpolation over keyframes."""
        cx = max(0.1, min(0.9, float(base_center_x)))
        if not keyframes:
            return cx

        points = []
        for k in keyframes:
            try:
                points.append((float(k.get("t", 0.0)), float(k.get("x", cx))))
            except Exception:
                continue
        if not points:
            return cx

        points.sort(key=lambda p: p[0])
        if t_sec <= points[0][0]:
            return max(0.1, min(0.9, points[0][1]))
        if t_sec >= points[-1][0]:
            return max(0.1, min(0.9, points[-1][1]))

        for i in range(len(points) - 1):
            t1, x1 = points[i]
            t2, x2 = points[i + 1]
            if t1 <= t_sec <= t2 and t2 > t1:
                a = (t_sec - t1) / (t2 - t1)
                return max(0.1, min(0.9, x1 + (x2 - x1) * a))

        return cx

    def _manual_crop_portrait_cv2(self, input_path: str, output_path: str, manual_crop: dict):
        """Render manual portrait crop frame-by-frame based on user-set center/keyframes.

        Produces stable 1080x1920 output and remuxes original clip audio.
        """
        import cv2

        base_center_x = float(manual_crop.get("base_center_x", 0.5))
        keyframes = list(manual_crop.get("keyframes", []))

        cap = cv2.VideoCapture(input_path, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            raise Exception("Failed to open input clip for manual crop")

        cap.set(cv2.CAP_PROP_N_THREADS, 1)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

        ret, frame = cap.read()
        if not ret:
            cap.release()
            raise Exception("Cannot read first frame for manual crop")

        h, w = frame.shape[:2]
        crop_w = min(int(h * 9 / 16), w)
        crop_w = max(2, crop_w)

        # Silent intermediate file (video only), then remux audio.
        tmp_silent = str(Path(output_path).with_suffix(".silent.mp4"))
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(tmp_silent, fourcc, fps, (1080, 1920))
        if not writer.isOpened():
            cap.release()
            raise Exception("Failed to create temp writer for manual crop")

        frame_idx = 0
        while ret:
            t_sec = frame_idx / fps if fps > 0 else 0.0
            cx = self._interpolate_manual_center_x(t_sec, base_center_x, keyframes)
            center_px = int(cx * w)

            x1 = max(0, min(center_px - (crop_w // 2), w - crop_w))
            x2 = x1 + crop_w

            crop = frame[:, x1:x2]
            if crop.size == 0:
                crop = frame[:, max(0, (w // 2) - (crop_w // 2)):max(0, (w // 2) - (crop_w // 2)) + crop_w]

            out_frame = cv2.resize(crop, (1080, 1920), interpolation=cv2.INTER_LANCZOS4)
            writer.write(out_frame)

            ret, frame = cap.read()
            frame_idx += 1

            if self.is_cancelled():
                break

        writer.release()
        cap.release()

        if not os.path.exists(tmp_silent):
            raise Exception("Manual crop temp output missing")

        # Remux source audio if available; if not, keep silent result.
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", tmp_silent,
            "-i", input_path,
            "-map", "0:v:0",
            "-map", "1:a:0?",
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            output_path,
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

        if result.returncode != 0:
            # Fallback: keep silent cropped clip
            os.replace(tmp_silent, output_path)
        else:
            try:
                os.remove(tmp_silent)
            except Exception:
                pass

        if total_frames > 0:
            self.log(f"    🧭 Manual crop rendered: {frame_idx}/{total_frames} frames")
    
    def _check_subject_spread(self, analyzer, clip_path: str, duration: float) -> float:
        """Check how much the subject moves across a clip.
        
        Samples 3 positions (start, middle, end) and returns the spread
        (max - min center_x). High spread = subject moves a lot.
        """
        import cv2
        cap = cv2.VideoCapture(clip_path, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            return 0.0
        
        try:
            cap.set(cv2.CAP_PROP_N_THREADS, 1)
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            
            # Sample at 10%, 50%, 90% of clip
            positions = []
            for frac in [0.1, 0.5, 0.9]:
                t = duration * frac
                frame_num = int(t * fps)
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                ret, frame = cap.read()
                if not ret:
                    continue
                
                h, w = frame.shape[:2]
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                edges = cv2.Canny(gray, 50, 150)
                contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                significant = [c for c in contours if cv2.contourArea(c) > (h * w * 0.001)]
                region = analyzer._find_subject_region(frame, edges, significant)
                if region:
                    positions.append(region["center_x"])
            
            if len(positions) < 2:
                return 0.0
            
            return max(positions) - min(positions)
        finally:
            cap.release()
    
    def _tracking_crop_portrait(self, input_path: str, output_path: str):
        """Use clipper_core's per-frame tracking for portrait crop.
        
        This is heavier but much better for clips with moving subjects.
        Reuses existing face/body detection + position smoothing.
        """
        from clipper_core import AutoClipperCore
        
        ai_providers = self.config.get("ai_providers", {})
        hf_config = ai_providers.get("highlight_finder", {})
        
        core = AutoClipperCore(
            client=None,
            ffmpeg_path=self.ffmpeg_path,
            ytdlp_path=self.ytdlp_path,
            output_dir=str(self.session_dir),
            model=hf_config.get("model", "llama-3.3-70b-versatile"),
            temperature=0.7,
            ai_providers=ai_providers,
            log_callback=self.log_callback,
        )
        
        gpu_settings = self.config.get("gpu_acceleration", {})
        if gpu_settings.get("enabled", False):
            core.enable_gpu_acceleration(True)
        
        core.convert_to_portrait(input_path, output_path)
    
    def _concat_simple(self, clip_files: list, output_path: str):
        """Simple concat menggunakan concat demuxer + threads 1 untuk hindari async_lock bug.
        
        Uses -fflags +genpts to regenerate PTS from concat demuxer,
        -bf 0 to avoid B-frame DTS/PTS reordering issues that cause frozen initial frames,
        and -movflags +faststart for better playback compatibility.
        """
        concat_file = self.temp_dir / "concat_list.txt"
        with open(concat_file, "w", encoding="utf-8") as f:
            for cp in clip_files:
                # Use forward slashes for FFmpeg concat demuxer compatibility on Windows
                safe_path = str(cp).replace(chr(92), '/')
                f.write(f"file '{safe_path}'\n")
        
        cmd = [
            self.ffmpeg_path, "-y",
            "-threads", "1",
            "-fflags", "+genpts",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            *self._gpu_args,
            "-bf", "0",
            "-c:a", "aac",
            "-movflags", "+faststart",
            "-threads", "1",
            output_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        
        if result.returncode != 0:
            raise Exception(f"Concat failed: {result.stderr[-300:]}")
    
    def _concat_with_transitions(self, clip_files: list, output_path: str,
                                  transition: str = "fade", duration: float = 0.5):
        """Concat clips dengan transisi antar segment menggunakan xfade filter.
        
        Supported transitions: fade, dissolve, wipeleft, wiperight, slideup, slidedown
        """
        if len(clip_files) < 2:
            return self._concat_simple(clip_files, output_path)
        
        # Normalize all clips first so xfade receives uniform stream parameters.
        # This significantly reduces random filter_complex failures.
        normalized_dir = self.temp_dir / "clips_transition_norm"
        normalized_dir.mkdir(exist_ok=True)

        normalized_clips = []
        for i, cp in enumerate(clip_files):
            norm_path = normalized_dir / f"norm_{i:03d}.mp4"
            try:
                self._normalize_clip_for_transition(str(cp), str(norm_path))
                if os.path.exists(str(norm_path)) and self._has_video_stream(str(norm_path)):
                    normalized_clips.append(norm_path)
                else:
                    self.log(f"  ⚠ Normalized clip invalid, fallback to simple concat")
                    return self._concat_simple(clip_files, output_path)
            except Exception as e:
                self.log(f"  ⚠ Normalize clip gagal ({i+1}/{len(clip_files)}): {e}")
                return self._concat_simple(clip_files, output_path)

        # Dapatkan durasi setiap clip
        clip_durations = []
        for cp in normalized_clips:
            dur = self._get_duration(str(cp))
            clip_durations.append(dur)
        
        # If any clip has 0 duration, xfade offsets will be wrong → fall back to simple concat
        if any(d <= 0 for d in clip_durations):
            self.log(f"  ⚠ Some clips have 0 duration, falling back to simple concat")
            return self._concat_simple(clip_files, output_path)
        
        # Map transition name
        xfade_map = {
            "fade": "fade",
            "dissolve": "dissolve", 
            "wipe_left": "wipeleft",
            "wipe_right": "wiperight",
            "slide_up": "slideup",
            "slide_down": "slidedown",
        }
        xfade_type = xfade_map.get(transition, "fade")
        
        # Build input args
        input_args = []
        for cp in normalized_clips:
            input_args.extend(["-i", str(cp)])
        
        # Build xfade filter chain
        # Untuk N clips, butuh N-1 xfade filters
        n = len(clip_files)
        filter_parts = []
        
        # Hitung offset kumulatif
        # offset[i] = sum(durations[0:i+1]) - (i+1) * transition_duration 
        cumulative = 0
        for i in range(n - 1):
            offset = cumulative + clip_durations[i] - duration
            if offset < 0:
                offset = cumulative + clip_durations[i] * 0.5  # Fallback: 50% dari clip
            
            if i == 0:
                src = "[0:v]"
                src2 = "[1:v]"
            else:
                src = f"[vfade{i-1}]"
                src2 = f"[{i+1}:v]"
            
            out_label = f"[vfade{i}]" if i < n - 2 else "[vout]"
            filter_parts.append(
                f"{src}{src2}xfade=transition={xfade_type}:duration={duration}:offset={offset:.3f}{out_label}"
            )
            cumulative = offset
        
        # Audio: simple concat (aconccat) — transisi audio via crossfade
        audio_inputs = "".join(f"[{i}:a]" for i in range(n))
        filter_parts.append(f"{audio_inputs}concat=n={n}:v=0:a=1[aout]")
        
        filter_complex = ";".join(filter_parts)
        
        cmd = [
            self.ffmpeg_path, "-y",
            "-threads", "1",
            *input_args,
            "-filter_complex", filter_complex,
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-r", "30",
            "-c:a", "aac",
            "-ar", "48000",
            "-ac", "2",
            "-movflags", "+faststart",
            "-threads", "1",
            output_path
        ]
        
        self.log(f"  Applying {xfade_type} transitions ({duration}s) between {n} clips...")
        result = subprocess.run(cmd, capture_output=True, text=True,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        
        if result.returncode != 0:
            # Fallback ke simple concat jika xfade gagal
            self.log(f"  ⚠ Transition failed, falling back to simple concat: {result.stderr[-200:]}")
            self._concat_simple(clip_files, output_path)
    
    def _add_hook_scene(self, video_path: str, hook_text: str, output_path: str,
                        voice: str = "id-ID-ArdiNeural", speed: str = "+0%") -> float:
        """Tambah hook scene di awal video — freeze frame pertama + TTS + teks overlay.
        
        Returns: durasi hook dalam detik
        """
        import re
        
        self.log(f"  🎣 Membuat hook scene: \"{hook_text[:50]}...\"")
        
        # Generate TTS audio menggunakan Edge TTS
        hook_audio = str(self.temp_dir / "hook_audio.mp3")
        
        try:
            from edge_tts_engine import EdgeTTSEngine
            tts = EdgeTTSEngine()
            tts.voice = voice
            tts.rate = speed
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            audio_path, audio_dur, _ = loop.run_until_complete(
                tts.generate_audio(hook_text, hook_audio)
            )
            loop.close()
        except Exception as e:
            self.log(f"  ⚠ Edge TTS gagal: {e}, skip hook")
            return 0.0
        
        if not os.path.exists(hook_audio) or os.path.getsize(hook_audio) < 100:
            self.log("  ⚠ Hook audio kosong, skip hook")
            return 0.0
        
        # Dapatkan durasi TTS
        hook_duration = self._get_duration(hook_audio) + 0.3  # +0.3s padding
        
        # Dapatkan info video (fps, resolusi)
        ffprobe = os.path.join(os.path.dirname(self.ffmpeg_path),
                               "ffprobe.exe" if os.name == "nt" else "ffprobe")
        probe_cmd = [self.ffmpeg_path, "-i", video_path]
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True,
                                      creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        
        fps_match = re.search(r'(\d+(?:\.\d+)?)\s*fps', probe_result.stderr)
        fps = float(fps_match.group(1)) if fps_match else 30
        
        res_match = re.search(r'(\d{3,4})x(\d{3,4})', probe_result.stderr)
        if res_match:
            width, height = int(res_match.group(1)), int(res_match.group(2))
        else:
            width, height = 1080, 1920
        
        # Format teks hook: uppercase, split per 3 kata
        hook_upper = hook_text.upper()
        words = hook_upper.split()
        lines = []
        current_line = []
        for word in words:
            current_line.append(word)
            if len(current_line) >= 3:
                lines.append(" ".join(current_line))
                current_line = []
        if current_line:
            lines.append(" ".join(current_line))
        
        # Buat hook video: freeze frame pertama + text overlay + TTS audio
        hook_video = str(self.temp_dir / "hook_scene.mp4")
        
        # Build drawtext filter
        font_size = max(40, min(58, width // 18))
        line_height = font_size + 30
        total_text_height = len(lines) * line_height
        start_y = (height // 3) - (total_text_height // 2)
        
        drawtext_filters = []
        for i, line in enumerate(lines):
            # Escape untuk FFmpeg
            escaped = line.replace("'", "'\\\\\\''").replace(":", "\\\\:")
            y_pos = start_y + (i * line_height)
            drawtext_filters.append(
                f"drawtext=text='{escaped}':"
                f"fontsize={font_size}:"
                f"fontcolor=#FFD700:"
                f"box=1:boxcolor=white@0.9:boxborderw=10:"
                f"x=(w-text_w)/2:y={y_pos}"
            )
        
        # Calculate loop count: enough frames for hook duration + buffer
        loop_count = int(hook_duration * fps) + 10
        
        vf = (f"trim=start=0:end=0.08,setpts=PTS-STARTPTS,"
              f"loop=loop={loop_count}:size=1:start=0,"
              f"setpts=N/{fps}/TB,"
              f"{','.join(drawtext_filters)},"
              f"trim=start=0:end={hook_duration},setpts=PTS-STARTPTS")
        
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", video_path,
            "-i", hook_audio,
            "-filter_complex",
            f"[0:v]{vf}[v];[1:a]aresample=44100,apad=whole_dur={hook_duration}[a]",
            "-map", "[v]", "-map", "[a]",
            *self._gpu_args,
            "-r", str(fps),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-ar", "44100", "-ac", "2",
            "-t", str(hook_duration),
            "-threads", "1",
            hook_video
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        
        if result.returncode != 0:
            self.log(f"  ⚠ Hook video failed: {result.stderr[-200:]}")
            # Fallback: coba tanpa drawtext (teks saja yang gagal)
            cmd_simple = [
                self.ffmpeg_path, "-y",
                "-i", video_path,
                "-i", hook_audio,
                "-filter_complex",
                f"[0:v]trim=start=0:end=0.08,setpts=PTS-STARTPTS,"
                f"loop=loop={loop_count}:size=1:start=0,setpts=N/{fps}/TB,"
                f"trim=start=0:end={hook_duration},setpts=PTS-STARTPTS[v];"
                f"[1:a]aresample=44100,apad=whole_dur={hook_duration}[a]",
                "-map", "[v]", "-map", "[a]",
                *self._gpu_args,
                "-c:a", "aac", "-b:a", "192k",
                "-t", str(hook_duration),
                "-threads", "1",
                hook_video
            ]
            result2 = subprocess.run(cmd_simple, capture_output=True, text=True,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            if result2.returncode != 0:
                self.log(f"  ⚠ Hook completely failed, skipping")
                return 0.0
        
        # Validate hook video has a video stream (not just audio)
        if os.path.exists(hook_video):
            probe_cmd = [
                os.path.join(os.path.dirname(self.ffmpeg_path),
                             "ffprobe.exe" if os.name == "nt" else "ffprobe"),
                "-v", "error", "-select_streams", "v",
                "-show_entries", "stream=codec_type",
                "-of", "csv=p=0", hook_video
            ]
            probe_r = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10,
                                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            if "video" not in probe_r.stdout:
                self.log(f"  ⚠ Hook scene has no video stream, skipping hook")
                return 0.0
        
        # Concat hook + main video
        concat_file = str(self.temp_dir / "hook_concat.txt")
        # Re-encode main video agar format identik
        main_reenc = str(self.temp_dir / "main_for_hook.mp4")
        reencode_cmd = [
            self.ffmpeg_path, "-y",
            "-i", video_path,
            *self._gpu_args,
            "-r", str(fps),
            "-s", f"{width}x{height}",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-ar", "44100", "-ac", "2",
            "-threads", "1",
            main_reenc
        ]
        result = subprocess.run(reencode_cmd, capture_output=True, text=True,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if result.returncode != 0:
            self.log(f"  ⚠ Re-encode failed, skipping hook")
            return 0.0
        
        with open(concat_file, "w", encoding="utf-8") as f:
            f.write(f"file '{hook_video.replace(chr(92), '/')}'\n")
            f.write(f"file '{main_reenc.replace(chr(92), '/')}'\n")
        
        concat_cmd = [
            self.ffmpeg_path, "-y",
            "-threads", "1",
            "-f", "concat", "-safe", "0",
            "-i", concat_file,
            "-c", "copy",
            output_path
        ]
        result = subprocess.run(concat_cmd, capture_output=True, text=True,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        
        if result.returncode != 0:
            self.log(f"  ⚠ Hook concat failed: {result.stderr[-200:]}")
            return 0.0
        
        self.log(f"  ✓ Hook scene ditambahkan ({hook_duration:.1f}s)")
        return hook_duration
    
    # ─── STEP 4: Generate Script ──────────────────────────────────────
    
    def generate_script(self, user_context: str, pattern_id: str = "custom",
                       custom_instructions: str = "") -> Dict:
        """
        Generate narration script based on context + assembled clips.
        
        Returns dict with:
        - full_script: Complete narration text
        - segments: List of {text, target_start, target_end, tone}
        - word_count, estimated_duration
        """
        self.log("━" * 50)
        self.log("[STEP 4/6] ✍️ Generating narration script...")
        self.emit_step(4, "Generate Script", "AI sedang menulis narasi...")
        self.set_progress("Generating script...", 0.60)
        
        pattern = PATTERNS.get(pattern_id, PATTERNS["custom"])
        
        # Get draft duration
        draft_duration = self._get_duration(self.draft_video_path) if self.draft_video_path else 90
        
        # Fallback: if draft reports 0, compute from highlight durations
        if draft_duration <= 0 and self.highlights:
            draft_duration = sum(h.get("duration_seconds", 25) for h in self.highlights)
        
        # Build script prompt with rich timestamp context per clip
        clip_descriptions = ""
        running_time = 0.0
        if self.highlights:
            for i, h in enumerate(self.highlights, 1):
                clip_dur = h.get("duration_seconds", 25)
                clip_start_in_draft = running_time
                clip_end_in_draft = running_time + clip_dur
                visual = h.get("visual_subject", h.get("description", ""))
                
                clip_descriptions += f"\n📎 Clip {i}: [{h['start_time']} → {h['end_time']}] (durasi: {clip_dur:.0f}s)"
                clip_descriptions += f"\n   ⏱️ Posisi di draft: {clip_start_in_draft:.1f}s → {clip_end_in_draft:.1f}s"
                clip_descriptions += f"\n   📌 Judul: {h['title']}"
                clip_descriptions += f"\n   👁️ Visual: {visual}"
                clip_descriptions += f"\n   📝 Deskripsi: {h.get('description', '')}\n"
                
                running_time = clip_end_in_draft
        
        # Use transcript context for richer information
        transcript_excerpt = ""
        if self.transcript:
            transcript_excerpt = self.transcript[:4000]
        
        script_system = pattern.get("script_prompt", "")
        
        # Build exact timing map from clips for segment enforcement
        segment_timing_guide = ""
        if self.highlights and running_time > 0:
            segment_timing_guide = "\n⏱️ TIMING DAN JUMLAH KATA WAJIB PER-SEGMENT:\n"
            rt = 0.0
            for i, h in enumerate(self.highlights, 1):
                cd = h.get("duration_seconds", 25)
                # 2.5 words/second target = ensure narration fills 80-95% of clip
                min_words = max(5, int(cd * 2.0))
                max_words = int(cd * 2.8)
                segment_timing_guide += (
                    f"  Segment {i}: start={rt:.1f}s, end={rt + cd:.1f}s, "
                    f"durasi={cd:.0f}s → TULIS {min_words}-{max_words} KATA\n"
                )
                rt += cd
            segment_timing_guide += f"\n  TOTAL DURASI: {rt:.1f}s (harus = {draft_duration:.0f}s)\n"
            segment_timing_guide += "  JUMLAH SEGMENT HARUS SAMA DENGAN JUMLAH KLIP!\n"
            segment_timing_guide += (
                "\n  ⚠️ PERINGATAN: Jika narasi terlalu pendek, akan ada KEKOSONGAN suara!\n"
                "  Pastikan setiap segment narasi MENGISI durasi klip secara penuh.\n"
                "  Lebih baik sedikit kebanyakan kata daripada kekurangan.\n"
            )
        
        prompt = f"""Kamu adalah AI Script Writer profesional untuk YouTube Shorts (Bahasa Indonesia).

KONTEKS USER:
{user_context}

{'PANDUAN SCRIPT (' + pattern.get("name", "") + '):' if script_system else ''}
{script_system}

VIDEO INFO:
- Judul: {self.video_info.get('title', 'Unknown') if self.video_info else 'Unknown'}
- Channel: {self.video_info.get('channel', 'Unknown') if self.video_info else 'Unknown'}
- Durasi draft: {draft_duration:.0f} detik
- Total klip: {len(self.highlights) if self.highlights else 0}

KLIP YANG TERSUSUN DALAM VIDEO (dengan posisi waktu di draft):
{clip_descriptions}
{segment_timing_guide}

TRANSCRIPT REFERENSI:
{transcript_excerpt}

{custom_instructions if custom_instructions else ''}

TUGAS:
1. Buat script narasi voiceover yang SESUAI dengan konteks di atas
2. Script harus pas dengan durasi {draft_duration:.0f} detik (target 130-150 kata/menit)
3. BUAT TEPAT {len(self.highlights) if self.highlights else 1} SEGMENT — satu segment per klip video
   - Gunakan timing WAJIB di atas sebagai target_start dan target_end
   - Segment 1 = narasi untuk Clip 1, Segment 2 = narasi untuk Clip 2, dst
   - Narasi setiap segment harus MENGISI PENUH durasi klip — JANGAN terlalu pendek!
4. Narasi HARUS mendeskripsikan apa yang TERLIHAT di layar (lihat field 👁️ Visual)
   - Jika visual menunjukkan elang terbang → narasi harus tentang elang terbang
   - Jika visual menunjukkan grafik → narasi harus menjelaskan data di grafik
   - JANGAN menulis narasi yang tidak match dengan visual yang sedang ditampilkan
5. Gunakan hook yang kuat di awal (3 detik pertama) — langsung sebut objek utama
6. Akhiri dengan kalimat yang memorable/CTA
7. Jika ada informasi penting yang kurang dari transcript, 
   BOLEH gunakan pengetahuanmu dari sumber kredibel untuk melengkapi

ATURAN JUMLAH KATA PER SEGMENT (KRITIS — HARUS DIPATUHI):
- Kecepatan bicara TTS: ~2.5 kata/detik
- RUMUS: Segment berdurasi X detik → tulis MINIMAL (X × 2) kata, MAKSIMAL (X × 2.8) kata
- Contoh:
  * Segment 10s → tulis 20-28 kata (BUKAN 5-10 kata!)
  * Segment 15s → tulis 30-42 kata
  * Segment 20s → tulis 40-56 kata
  * Segment 30s → tulis 60-84 kata
- JIKA NARASI TERLALU PENDEK, AKAN ADA KEHENINGAN PANJANG TANPA SUARA!
- Pastikan narasi CUKUP PANJANG untuk mengisi durasi klip
- Lebih baik sedikit lebih banyak dari target daripada kekurangan
- Lihat kolom "TULIS X-Y KATA" di timing guide di atas dan PATUHI

OUTPUT FORMAT (WAJIB JSON):
{{
    "full_script": "Script narasi lengkap di sini...",
    "segments": [
        {{"text": "Kalimat 1...", "target_start": 0, "target_end": 5, "tone": "hook"}},
        {{"text": "Kalimat 2...", "target_start": 5, "target_end": 15, "tone": "informative"}}
    ],
    "word_count": 200,
    "estimated_duration": {draft_duration:.0f}
}}

HANYA OUTPUT JSON YANG VALID."""
        
        # Call LLM
        from script_generator import ScriptGenerator, ContentType
        
        content_type_str = pattern.get("content_type", "dubbing")
        ct_map = {
            "dubbing": ContentType.DUBBING,
            "narration": ContentType.NARRATION,
            "entertainment": ContentType.ENTERTAINMENT,
            "tutorial": ContentType.TUTORIAL,
            "shopping": ContentType.SHOPPING
        }
        content_type = ct_map.get(content_type_str, ContentType.DUBBING)
        
        gen = ScriptGenerator(self.config)
        
        # We use _call_llm directly with our rich prompt
        system_msg = ("Kamu adalah script writer profesional untuk YouTube Shorts Bahasa Indonesia. "
                      "Selalu output dalam format JSON yang valid. "
                      "Jika kamu kekurangan informasi tentang topik yang dibahas, "
                      "gunakan pengetahuanmu dari sumber kredibel untuk melengkapi.")
        
        result_text = gen._call_llm(prompt, system_msg, lambda msg: self.log(f"  {msg}"))
        
        # Parse result
        try:
            if "```" in result_text:
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
            result_text = result_text.strip()
            
            self.script_data = json.loads(result_text)
        except json.JSONDecodeError:
            self.script_data = {
                "full_script": result_text,
                "segments": [{"text": result_text, "target_start": 0, 
                             "target_end": draft_duration, "tone": "narration"}],
                "word_count": len(result_text.split()),
                "estimated_duration": draft_duration
            }
        
        # Post-validation: force-align segment timing to actual clip durations
        self._align_script_segments_to_clips(draft_duration)
        
        word_count = self.script_data.get("word_count", len(self.script_data["full_script"].split()))
        self.log(f"  ✓ Script generated: {word_count} words, ~{self.script_data.get('estimated_duration', draft_duration):.0f}s")
        self.log(f"  📝 Segments: {len(self.script_data.get('segments', []))}")
        
        self._finish_step_timer(4)
        return self.script_data
    
    def _align_script_segments_to_clips(self, draft_duration: float):
        """Force-align script segment timings to actual clip durations.
        
        Ensures each segment's target_start/target_end matches the real
        position of each clip in the assembled draft video.
        """
        if not self.script_data or not self.highlights:
            return
        
        segments = self.script_data.get("segments", [])
        if not segments:
            return
        
        # Build the correct timing from actual clips
        clip_timings = []
        running = 0.0
        for h in self.highlights:
            dur = h.get("duration_seconds", 25)
            clip_timings.append((running, running + dur))
            running += dur
        
        # If segment count matches clip count, align 1:1
        if len(segments) == len(clip_timings):
            for i, (seg, (start, end)) in enumerate(zip(segments, clip_timings)):
                seg["target_start"] = round(start, 1)
                seg["target_end"] = round(end, 1)
            self.log(f"  ✅ Segment timing aligned 1:1 with {len(clip_timings)} clips")
        elif len(segments) > len(clip_timings):
            # More segments than clips — distribute segments across clips
            segs_per_clip = len(segments) / max(len(clip_timings), 1)
            for i, seg in enumerate(segments):
                clip_idx = min(int(i / segs_per_clip), len(clip_timings) - 1)
                clip_start, clip_end = clip_timings[clip_idx]
                clip_dur = clip_end - clip_start
                # Distribute evenly within the clip's duration
                sub_idx = i - int(clip_idx * segs_per_clip)
                sub_total = max(1, int(segs_per_clip))
                seg["target_start"] = round(clip_start + (clip_dur * sub_idx / sub_total), 1)
                seg["target_end"] = round(clip_start + (clip_dur * (sub_idx + 1) / sub_total), 1)
            self.log(f"  ⚠️ {len(segments)} segments distributed across {len(clip_timings)} clips")
        else:
            # Fewer segments than clips — spread each segment across clip range
            clips_per_seg = len(clip_timings) / max(len(segments), 1)
            for i, seg in enumerate(segments):
                first_clip = int(i * clips_per_seg)
                last_clip = min(int((i + 1) * clips_per_seg) - 1, len(clip_timings) - 1)
                seg["target_start"] = round(clip_timings[first_clip][0], 1)
                seg["target_end"] = round(clip_timings[last_clip][1], 1)
            self.log(f"  ⚠️ {len(segments)} segments spread across {len(clip_timings)} clips")
        
        # Ensure last segment ends at draft duration
        if segments and draft_duration > 0:
            segments[-1]["target_end"] = round(min(segments[-1]["target_end"], draft_duration), 1)
        
        # Post-validate: check word count vs segment duration
        short_segments = []
        for i, seg in enumerate(segments):
            seg_dur = seg.get("target_end", 0) - seg.get("target_start", 0)
            word_count = len(seg.get("text", "").split())
            min_words = max(5, int(seg_dur * 1.8))  # minimum ~1.8 words/sec
            if word_count < min_words and seg_dur > 3:
                short_segments.append((i + 1, word_count, min_words, seg_dur))
        
        if short_segments:
            self.log(f"  ⚠️ {len(short_segments)} segment(s) terlalu pendek untuk durasinya:")
            for seg_num, wc, min_w, sd in short_segments:
                self.log(f"    Seg {seg_num}: {wc} kata untuk {sd:.0f}s (minimum {min_w} kata)")
            self.log(f"  ⚠️ Ini bisa menyebabkan keheningan di tengah video!")
            self.log(f"  💡 Akan dilakukan auto-extend narasi untuk mengisi kekosongan...")
            
            # Auto-extend short segments by padding with contextual filler
            self._extend_short_segments(segments)
        
        self.script_data["segments"] = segments
        # Rebuild full_script from segments to keep in sync
        self.script_data["full_script"] = " ".join(
            seg.get("text", "") for seg in segments if seg.get("text")
        )
        self.script_data["word_count"] = len(self.script_data["full_script"].split())
        self.script_data["estimated_duration"] = round(draft_duration, 1)
    
    def _extend_short_segments(self, segments: list):
        """Extend narration text for segments that are too short for their duration.
        Uses AI to generate additional text that fits the context."""
        
        short_segs = []
        for i, seg in enumerate(segments):
            seg_dur = seg.get("target_end", 0) - seg.get("target_start", 0)
            word_count = len(seg.get("text", "").split())
            target_words = int(seg_dur * 2.2)  # aim for 2.2 words/sec
            if word_count < int(seg_dur * 1.8) and seg_dur > 3:
                short_segs.append({
                    "index": i,
                    "current_text": seg.get("text", ""),
                    "current_words": word_count,
                    "target_words": target_words,
                    "duration": seg_dur,
                })
        
        if not short_segs:
            return
        
        # Build prompt explaining what needs extending
        extend_list = ""
        for s in short_segs:
            extend_list += (
                f"\nSegment {s['index']+1} (durasi {s['duration']:.0f}s, "
                f"saat ini {s['current_words']} kata, TARGET {s['target_words']} kata):\n"
                f"  Teks saat ini: \"{s['current_text']}\"\n"
            )
        
        video_title = self.video_info.get("title", "") if self.video_info else ""
        
        prompt = f"""Beberapa segment narasi terlalu PENDEK dan akan menyebabkan keheningan di video.
Perpanjang setiap segment agar MENGISI durasi klip secara penuh.

VIDEO: {video_title}

SEGMENT YANG PERLU DIPERPANJANG:
{extend_list}

TUGAS:
- Perpanjang teks setiap segment hingga mencapai TARGET jumlah kata
- JANGAN ubah makna atau topik — tambahkan detail, fakta, atau elaborasi
- Pertahankan tone dan gaya bahasa yang sama
- Output HANYA JSON array dengan format: [{{"index": 0, "text": "teks lengkap yang sudah diperpanjang..."}}]
- JANGAN sertakan markdown code block"""

        try:
            from script_generator import ScriptGenerator
            gen = ScriptGenerator(self.config)
            system_msg = "Kamu adalah script writer. Perpanjang narasi agar mengisi durasi. Output JSON valid saja."
            raw = gen._call_llm(prompt, system_msg)
            
            import re
            json_match = re.search(r'\[[\s\S]*\]', raw)
            if json_match:
                extensions = json.loads(json_match.group())
                for ext in extensions:
                    idx = ext.get("index", -1)
                    new_text = ext.get("text", "").strip()
                    if 0 <= idx < len(segments) and new_text:
                        old_wc = len(segments[idx].get("text", "").split())
                        new_wc = len(new_text.split())
                        if new_wc > old_wc:
                            segments[idx]["text"] = new_text
                            self.log(f"    ✓ Seg {idx+1}: {old_wc} → {new_wc} kata")
                
                self.log(f"  ✅ Auto-extend selesai")
        except Exception as e:
            self.log(f"  ⚠️ Auto-extend gagal: {e}")
    
    # ─── STEP 5: Refine Script ────────────────────────────────────────
    
    def refine_script(self, feedback: str) -> Dict:
        """
        Refine script based on user feedback.
        Only regenerates based on specific feedback, preserving good parts.
        """
        if not self.script_data:
            raise Exception("No script to refine. Generate script first.")
        
        self.log("━" * 50)
        self.log("[STEP 5] 🔄 Refining script...")
        self.emit_step(5, "Revisi Script", "AI memperbaiki narasi...")
        self.set_progress("Refining script...", 0.65)
        
        draft_duration = self._get_duration(self.draft_video_path) if self.draft_video_path else 90
        if draft_duration <= 0 and self.highlights:
            draft_duration = sum(h.get("duration_seconds", 25) for h in self.highlights)
        
        prompt = f"""Script narasi saat ini:
---
{self.script_data['full_script']}
---

Segments:
{json.dumps(self.script_data.get('segments', []), indent=2, ensure_ascii=False)}

FEEDBACK / PERMINTAAN PERUBAHAN:
{feedback}

ATURAN:
1. Perbaiki HANYA bagian yang diminta dalam feedback
2. Pertahankan bagian yang sudah baik
3. Durasi target tetap {draft_duration:.0f} detik
4. Output tetap format JSON dengan segments yang tersinkron
5. Jika diminta menambah informasi, gunakan pengetahuanmu dari sumber kredibel

OUTPUT FORMAT (WAJIB JSON):
{{
    "full_script": "Script yang sudah direvisi...",
    "segments": [
        {{"text": "...", "target_start": 0, "target_end": 5, "tone": "..."}},
    ],
    "word_count": 200,
    "estimated_duration": {draft_duration:.0f},
    "changes_made": "Penjelasan singkat apa yang diubah"
}}

HANYA OUTPUT JSON YANG VALID."""
        
        from script_generator import ScriptGenerator
        gen = ScriptGenerator(self.config)
        
        system_msg = ("Kamu adalah editor script profesional. "
                      "Perbaiki script sesuai feedback tanpa mengubah bagian yang sudah benar. "
                      "Gunakan pengetahuan dari sumber kredibel jika diminta menambah informasi.")
        
        result_text = gen._call_llm(prompt, system_msg, lambda msg: self.log(f"  {msg}"))
        
        try:
            if "```" in result_text:
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
            result_text = result_text.strip()
            
            self.script_data = json.loads(result_text)
        except json.JSONDecodeError:
            self.script_data["full_script"] = result_text
        
        changes = self.script_data.get("changes_made", "Script diperbarui")
        self.log(f"  ✓ Script refined: {changes}")
        
        # Re-align timing after refinement
        self._align_script_segments_to_clips(draft_duration)
        
        self._finish_step_timer(5)
        return self.script_data
    
    # ─── STEP 6: Render Final Video ──────────────────────────────────
    
    def render_final(self, script_data: Optional[Dict] = None,
                    voice: str = "id-ID-ArdiNeural",
                    speed: str = "+0%",
                    pitch: str = "+0Hz",
                    include_subtitle: bool = True,
                    bgm_url: Optional[str] = None,
                    bgm_volume: float = 0.15,
                    tts_previews: Optional[List[Dict]] = None) -> str:
        """
        Final render: TTS + Mix audio + Burn subtitles.
        Uses tts_sync.py pipeline.
        """
        script = script_data or self.script_data
        if not script:
            raise Exception("No script data. Generate or refine script first.")
        if not self.draft_video_path:
            raise Exception("No draft video. Assemble draft first.")
        
        self.log("━" * 50)
        self.log("[STEP 6/6] 🎤 Rendering final video...")
        self.emit_step(6, "Render Final", "TTS + subtitle + mixing...")
        self.set_progress("Starting TTS rendering...", 0.70)
        
        from tts_sync import TTSVideoSync
        
        # For ClipDub: remove original YouTube audio, replace entirely with TTS
        render_config = dict(self.config)
        render_config["mix_config"] = {
            "voice_volume": 1.0,
            "background_volume": 0.0,
            "keep_original_audio": False,
        }
        
        tts_sync = TTSVideoSync(render_config)
        
        # Configure voice
        tts_sync.voice = voice
        tts_sync.rate = speed
        tts_sync.pitch = pitch
        
        # Build timed segments for tts_sync
        segments = script.get("segments", [])
        draft_dur = self._get_duration(self.draft_video_path)
        
        # Fallback: if draft_dur is 0, compute from highlight durations
        if draft_dur <= 0 and self.highlights:
            draft_dur = sum(h.get("duration_seconds", 25) for h in self.highlights)
            self.log(f"  ⚠ Draft file reports 0s, using calculated duration: {draft_dur:.0f}s")
        
        if not segments:
            # Fallback: single segment
            segments = [{
                "text": script["full_script"],
                "start": 0,
                "end": draft_dur
            }]
        else:
            # Convert format and validate timing
            timed_segments = []
            for seg in segments:
                start = float(seg.get("target_start", 0))
                end = float(seg.get("target_end", start + 5))
                # Clamp to draft duration
                start = min(start, draft_dur)
                end = min(end, draft_dur)
                text = seg.get("text", "").strip()
                if text and end > start:
                    timed_segments.append({
                        "text": text,
                        "start": start,
                        "end": end
                    })
            segments = timed_segments if timed_segments else [{
                "text": script["full_script"],
                "start": 0,
                "end": draft_dur
            }]
        
        self.log(f"  📊 Draft duration: {draft_dur:.1f}s | Segments: {len(segments)}")
        for i, seg in enumerate(segments, 1):
            wc = len(seg['text'].split())
            self.log(f"    Seg {i}: [{seg['start']:.1f}s → {seg['end']:.1f}s] ({wc} words) \"{seg['text'][:50]}...\"")
        
        draft_duration = draft_dur  # Reuse already-computed duration
        
        # Output path
        final_output = self.session_dir / "clips" / "final_clipdub.mp4"
        final_output.parent.mkdir(parents=True, exist_ok=True)
        
        def render_progress(pct, msg):
            # Map 0-100 to 0.70-0.95
            overall = 0.70 + (pct / 100) * 0.25
            self.set_progress(msg, overall)
            self.log(f"  {msg}")
        
        # Use the full dubbing pipeline
        result = tts_sync.process_video_with_timed_segments(
            video_path=self.draft_video_path,
            timed_segments=segments,
            video_duration=draft_duration,
            output_path=str(final_output),
            include_subtitle=include_subtitle,
            bgm_url=bgm_url,
            bgm_volume=bgm_volume,
            progress_callback=render_progress,
            pregenerated_tts=tts_previews
        )
        
        # Check if pipeline succeeded
        if not result.get("success", False) or not os.path.exists(str(final_output)):
            error_msg = result.get("error", "Unknown render error")
            raise Exception(f"Render gagal: {error_msg}")
        
        self.final_output = str(final_output)
        self._finish_step_timer(6)
        self.set_progress("Done!", 1.0)
        
        self.log("━" * 50)
        self.log(f"✅ Final video: {self.final_output}")
        self.log(f"   Duration: {result.get('final_duration', draft_duration):.1f}s")
        self.log(f"   Coverage: {result.get('coverage_percent', 0):.0f}%")
        self.log("")
        self.log(self.get_timing_summary())
        
        # Save session data
        self._save_session()
        
        return self.final_output
    
    # ─── TTS Preview Generation ───────────────────────────────────────
    
    def generate_tts_previews(self, script_data: Dict,
                              voice: str = "id-ID-ArdiNeural",
                              speed: str = "+0%",
                              pitch: str = "+0Hz",
                              progress_callback=None) -> List[Dict]:
        """Generate TTS audio preview for each segment.
        
        Returns list of dicts with audio_path, tts_duration, word_timings per segment.
        """
        segments = script_data.get("segments", [])
        if not segments:
            raise Exception("No segments in script data.")
        
        self.log("[TTS Preview] Generating TTS for all segments...")
        
        from edge_tts_engine import EdgeTTSManager
        tts = EdgeTTSManager({"voice": voice, "rate": speed, "pitch": pitch})
        
        preview_dir = self.session_dir / "_temp" / "tts_preview"
        preview_dir.mkdir(parents=True, exist_ok=True)
        
        results = []
        total = len(segments)
        for i, seg in enumerate(segments):
            text = seg.get("text", "").strip()
            if not text:
                continue
            
            start = float(seg.get("target_start", 0))
            end = float(seg.get("target_end", start + 5))
            
            if progress_callback:
                progress_callback(i, total, f"🔊 TTS segment {i+1}/{total}...")
            
            output_path = str(preview_dir / f"seg_{i:03d}.mp3")
            audio_path, duration, word_timings = tts.generate_audio_sync(text, output_path)
            
            slot_dur = end - start
            self.log(f"  Seg {i+1}: TTS={duration:.1f}s / slot={slot_dur:.1f}s")
            
            results.append({
                "index": i,
                "text": text,
                "target_start": start,
                "target_end": end,
                "audio_path": audio_path,
                "tts_duration": duration,
                "word_timings": word_timings or []
            })
        
        self.log(f"[TTS Preview] Generated {len(results)} TTS previews.")
        return results
    
    def generate_single_tts_preview(self, text: str, segment_index: int,
                                    voice: str = "id-ID-ArdiNeural",
                                    speed: str = "+0%",
                                    pitch: str = "+0Hz") -> Dict:
        """Generate TTS preview for a single segment."""
        from edge_tts_engine import EdgeTTSManager
        tts = EdgeTTSManager({"voice": voice, "rate": speed, "pitch": pitch})
        
        preview_dir = self.session_dir / "_temp" / "tts_preview"
        preview_dir.mkdir(parents=True, exist_ok=True)
        
        output_path = str(preview_dir / f"seg_{segment_index:03d}.mp3")
        audio_path, duration, word_timings = tts.generate_audio_sync(text, output_path)
        
        self.log(f"  [TTS Regen] Seg {segment_index+1}: {duration:.1f}s")
        return {
            "audio_path": audio_path,
            "tts_duration": duration,
            "word_timings": word_timings or []
        }
    
    # ─── Session Management ───────────────────────────────────────────
    
    def _save_session(self):
        """Save session data for resume capability."""
        if not self.session_dir:
            return
        
        session_file = self.session_dir / "session_data.json"
        data = {
            "type": "clip_dub",
            "created_at": datetime.now().isoformat(),
            "video_path": self.video_path,
            "srt_path": self.srt_path,
            "video_info": self.video_info,
            "highlights": self.highlights,
            "spare_highlights": self.spare_highlights,
            "clip_files": self.clip_files,
            "draft_video_path": self.draft_video_path,
            "script_data": self.script_data,
            "final_output": self.final_output,
            "session_dir": str(self.session_dir)
        }
        
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def get_session_data(self) -> Dict:
        """Get current session state."""
        return {
            "session_dir": str(self.session_dir) if self.session_dir else None,
            "video_path": self.video_path,
            "video_info": self.video_info,
            "has_subtitle": self.srt_path is not None,
            "has_heatmap": self.heatmap_data is not None,
            "highlights": self.highlights,
            "draft_video_path": self.draft_video_path,
            "script_data": self.script_data,
            "final_output": self.final_output
        }
