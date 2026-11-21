"""
Auto Clipper Core - Processing logic
Refactored to use OpenAI Whisper API instead of local model
Optimized for long videos (3-12+ hours)
"""

import subprocess
import os
import re
import json
import tempfile
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from openai import OpenAI
from utils.logger import debug_log
from utils.helpers import get_deno_path, get_ffmpeg_path, is_ytdlp_module_available

# Lazy-loaded heavy modules (cv2 ~500MB, numpy ~150MB, yt_dlp ~100MB)
# These are only imported when actually needed to save ~800MB RAM at idle
cv2 = None
np = None

def _ensure_cv2():
    """Lazy import cv2 + numpy only when video processing starts"""
    global cv2, np
    if cv2 is None:
        import cv2 as _cv2
        import numpy as _np
        cv2 = _cv2
        np = _np
    return cv2, np

# Setup Deno and FFmpeg in PATH before importing yt-dlp
_deno_path = get_deno_path()
_ffmpeg_path = get_ffmpeg_path()

if _deno_path and Path(_deno_path).exists():
    _deno_dir = str(Path(_deno_path).parent)
    if "PATH" in os.environ:
        if _deno_dir not in os.environ["PATH"]:
            os.environ["PATH"] = f"{_deno_dir}{os.pathsep}{os.environ['PATH']}"
    else:
        os.environ["PATH"] = _deno_dir
    debug_log(f"Deno added to PATH: {_deno_dir}")

if _ffmpeg_path and Path(_ffmpeg_path).exists():
    _ffmpeg_dir = str(Path(_ffmpeg_path).parent)
    if "PATH" in os.environ:
        if _ffmpeg_dir not in os.environ["PATH"]:
            os.environ["PATH"] = f"{_ffmpeg_dir}{os.pathsep}{os.environ['PATH']}"
    else:
        os.environ["PATH"] = _ffmpeg_dir
    debug_log(f"FFmpeg added to PATH: {_ffmpeg_dir}")

# Import yt-dlp module if available (lazy — only flag presence to save RAM)
import importlib
try:
    _yt_dlp_spec = importlib.util.find_spec("yt_dlp")
    YTDLP_MODULE_AVAILABLE = _yt_dlp_spec is not None
except Exception:
    YTDLP_MODULE_AVAILABLE = False

# Google GenAI — lazy loaded on demand
try:
    _genai_spec = importlib.util.find_spec("google.generativeai")
    GOOGLE_GENAI_AVAILABLE = _genai_spec is not None
except Exception:
    GOOGLE_GENAI_AVAILABLE = False

genai = None   # lazy loaded
yt_dlp = None  # lazy loaded

def _ensure_yt_dlp():
    """Lazy import yt_dlp only when needed (saves ~100MB RAM)"""
    global yt_dlp
    if yt_dlp is None and YTDLP_MODULE_AVAILABLE:
        import yt_dlp as _yt_dlp
        yt_dlp = _yt_dlp
    return yt_dlp

def _ensure_genai():
    """Lazy import google.generativeai only when needed"""
    global genai
    if genai is None and GOOGLE_GENAI_AVAILABLE:
        import google.generativeai as _genai
        genai = _genai
    return genai

# Hide console window on Windows
SUBPROCESS_FLAGS = 0
if sys.platform == "win32":
    SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW


class AutoClipperCore:
    """Core processing logic for Auto Clipper"""
    
    def __init__(
        self,
        client: OpenAI,
        ffmpeg_path: str = "ffmpeg",
        ytdlp_path: str = "yt-dlp",
        output_dir: str = "output",
        model: str = "gpt-4.1",
        tts_model: str = "tts-1",
        temperature: float = 1.0,
        system_prompt: str = None,
        watermark_settings: dict = None,
        credit_watermark_settings: dict = None,
        face_tracking_mode: str = "opencv",
        mediapipe_settings: dict = None,
        ai_providers: dict = None,
        subtitle_language: str = "id",
        log_callback=None,
        progress_callback=None,
        token_callback=None,
        cancel_check=None
    ):
        # Multi-provider support
        self.ai_providers = ai_providers or {}
        
        # Create separate clients for each provider
        if self.ai_providers:
            # Highlight Finder client
            hf_config = self.ai_providers.get("highlight_finder", {})
            self.highlight_client = OpenAI(
                api_key=hf_config.get("api_key", ""),
                base_url=hf_config.get("base_url", "https://api.openai.com/v1")
            )
            self.model = hf_config.get("model", model)
            
            # Caption Maker client (Whisper)
            cm_config = self.ai_providers.get("caption_maker", {})
            self.caption_client = OpenAI(
                api_key=cm_config.get("api_key", ""),
                base_url=cm_config.get("base_url", "https://api.openai.com/v1")
            )
            self.whisper_model = cm_config.get("model", "whisper-1")
            
            # Hook Maker client (TTS)
            hm_config = self.ai_providers.get("hook_maker", {})
            self.tts_client = OpenAI(
                api_key=hm_config.get("api_key", ""),
                base_url=hm_config.get("base_url", "https://api.openai.com/v1")
            )
            self.tts_model = hm_config.get("model", tts_model)
        else:
            # Fallback to single client (backward compatibility)
            self.highlight_client = client
            self.caption_client = client
            self.tts_client = client
            self.model = model
            self.tts_model = tts_model
            self.whisper_model = "whisper-1"
        
        # Keep original client for backward compatibility
        self.client = client
        
        self.ffmpeg_path = ffmpeg_path
        self.ytdlp_path = ytdlp_path
        self.output_dir = Path(output_dir)
        self.temperature = temperature
        self.system_prompt = system_prompt or self.get_default_prompt()
        self.watermark_settings = watermark_settings or {"enabled": False}
        self.credit_watermark_settings = credit_watermark_settings or {"enabled": False}
        self.channel_name = ""  # Will be set after download
        self.face_tracking_mode = face_tracking_mode
        self.mediapipe_settings = mediapipe_settings or {
            "lip_activity_threshold": 0.12,  # Lower threshold = more sensitive
            "switch_threshold": 0.25,
            "min_shot_duration": 60,  # Faster switching for dynamic content
            "center_weight": 0.5,  # Higher weight = prefer center-frame subjects
            "face_size_weight": 0.3,  # Prioritize larger/closer faces
            "upper_body_fallback": True  # Use body detection when face not found
        }
        self.subtitle_language = subtitle_language
        self.log = log_callback or print
        self.set_progress = progress_callback or (lambda s, p: None)
        self.report_tokens = token_callback or (lambda gi, go, w, t: None)
        self.is_cancelled = cancel_check or (lambda: False)
        
        # GPU acceleration settings
        self.gpu_enabled = False
        self.gpu_encoder_args = []
        
        # Heatmap / Most Replayed data
        self.heatmap_data = None  # List[{start_time, end_time, value}] from YouTube
        self.use_heatmap = True   # Whether to use heatmap for scoring
        
        # MediaPipe Face Mesh (lazy loaded)
        self.mp_face_mesh = None
        self.mp_drawing = None
        
        # Create temp directory
        self.temp_dir = self.output_dir / "_temp"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        # Checkpoint file for long video processing
        self.checkpoint_file = self.temp_dir / "processing_checkpoint.json"
        self.checkpoint_lock = threading.Lock()
    
    # ==================== CHECKPOINT SYSTEM ====================
    # For resuming long video processing (3-12+ hours)
    
    def save_checkpoint(self, stage: str, data: dict):
        """Save processing checkpoint for resume capability"""
        checkpoint = {
            "stage": stage,
            "timestamp": datetime.now().isoformat(),
            "data": data
        }
        with self.checkpoint_lock:
            try:
                with open(self.checkpoint_file, 'w', encoding='utf-8') as f:
                    json.dump(checkpoint, f, indent=2, ensure_ascii=False)
                self.log(f"  💾 Checkpoint saved: {stage}")
            except Exception as e:
                self.log(f"  ⚠ Failed to save checkpoint: {e}")
    
    def load_checkpoint(self) -> dict:
        """Load last checkpoint if exists"""
        if not self.checkpoint_file.exists():
            return None
        
        try:
            with open(self.checkpoint_file, 'r', encoding='utf-8') as f:
                checkpoint = json.load(f)
            self.log(f"  📂 Found checkpoint: {checkpoint.get('stage', 'unknown')}")
            return checkpoint
        except Exception as e:
            self.log(f"  ⚠ Failed to load checkpoint: {e}")
            return None
    
    def clear_checkpoint(self):
        """Clear checkpoint after successful completion"""
        if self.checkpoint_file.exists():
            try:
                self.checkpoint_file.unlink()
                self.log("  🗑️ Checkpoint cleared")
            except:
                pass
    
    def get_video_duration_from_srt(self, srt_path: str) -> float:
        """Get video duration from SRT file (last timestamp)"""
        try:
            # Read only the last part of file for efficiency
            file_size = os.path.getsize(srt_path)
            read_size = min(file_size, 10000)  # Last 10KB should have end timestamp
            
            with open(srt_path, 'rb') as f:
                if file_size > read_size:
                    f.seek(-read_size, 2)  # Seek from end
                content = f.read().decode('utf-8', errors='ignore')
            
            # Find last timestamp
            pattern = r'(\d{2}:\d{2}:\d{2},\d{3})'
            matches = re.findall(pattern, content)
            if matches:
                last_timestamp = matches[-1]
                return self.parse_timestamp(last_timestamp)
        except:
            pass
        return 0
    
    def enable_gpu_acceleration(self, enabled: bool = True):
        """Enable or disable GPU acceleration for video encoding"""
        self.gpu_enabled = enabled
        
        if enabled:
            try:
                from utils.gpu_detector import GPUDetector
                detector = GPUDetector(self.ffmpeg_path)
                self.gpu_encoder_args = detector.get_encoder_args(use_gpu=True)
                self.log(f"  ⚡ GPU Acceleration: ENABLED")
                self.log(f"  Encoder args: {' '.join(self.gpu_encoder_args)}")
            except Exception as e:
                self.log(f"  ⚠ GPU Acceleration failed to initialize: {e}")
                self.log(f"  Falling back to CPU encoding")
                self.gpu_enabled = False
                self.gpu_encoder_args = []
        else:
            self.log(f"  💻 GPU Acceleration: DISABLED (using CPU)")
            self.gpu_encoder_args = []
    
    def get_video_encoder_args(self) -> list:
        """Get video encoder arguments based on GPU settings"""
        if self.gpu_enabled and self.gpu_encoder_args:
            return self.gpu_encoder_args
        else:
            # Default CPU encoding
            return ['-c:v', 'libx264', '-preset', 'fast', '-crf', '18']
    
    def log_ffmpeg_command(self, cmd: list, description: str = "FFmpeg"):
        """Log FFmpeg command for debugging"""
        # Format command nicely
        cmd_str = ' '.join(f'"{arg}"' if ' ' in str(arg) else str(arg) for arg in cmd)
        self.log(f"  🎬 {description} Command:")
        self.log(f"     {cmd_str}")
    
    
    @staticmethod
    def get_default_prompt():
        """Get default system prompt for highlight detection"""
        return """Kamu adalah EDITOR SHORT-FORM TIER A untuk konten PODCAST / viral (TikTok / Reels / Shorts).

OUTPUT ANDA AKAN LANGSUNG DIGUNAKAN UNTUK PRODUKSI.
Kesalahan durasi atau format = GAGAL TOTAL.

==================================================
TUGAS UTAMA (NON-NEGOTIABLE)
============================

Dari transcript di bawah, HASILKAN TEPAT {num_clips} segment.

* TIDAK BOLEH kurang.
* TIDAK BOLEH lebih.
* ARRAY KOSONG DILARANG DALAM KONDISI APAPUN.

Jika kesulitan menemukan segmen bagus, WAJIB tetap menghasilkan {num_clips} dengan strategi penggabungan/perpanjangan.

==================================================
⚡ ATURAN CONTEXT-FIRST (PALING KRITIS)
=======================================

Setiap clip WAJIB dimulai dari KONTEKS/PERTANYAAN, BUKAN langsung jawaban.

INI ADALAH ATURAN NOMOR 1 YANG TIDAK BOLEH DILANGGAR.

Alasan: Penonton butuh tahu "APA yang sedang dibahas" sebelum mendengar jawaban.
Tanpa konteks, penonton akan skip karena tidak paham dan tidak tertarik.

ATURAN WAJIB:
1. Jika ada PERTANYAAN sebelum jawaban → clip HARUS dimulai dari pertanyaan
2. Jika ada SETUP sebelum punchline → clip HARUS dimulai dari setup
3. Jika ada PROVOKASI sebelum reaksi → clip HARUS dimulai dari provokasi
4. Jika ada KONTEKS sebelum insight → clip HARUS dimulai dari konteks

CONTOH BENAR vs SALAH:

✗ SALAH (langsung jawaban, penonton bingung):
  start_time = saat dokter bilang "Itu mitos, GERD tidak menyebabkan serangan jantung"
  → Penonton: "Hah? Emang siapa yang nanya? Konteksnya apa?"

✓ BENAR (dimulai dari pertanyaan, penonton penasaran):
  start_time = saat host bertanya "Dok, benarkah GERD bisa menyebabkan serangan jantung?"
  → Penonton: "Wah gue juga mau tau!" → TONTON SAMPAI HABIS

✗ SALAH (langsung punchline):
  start_time = saat tamu bilang "Makanya gue bangkrut"
  → Penonton: "Bangkrut kenapa? Skip ah"

✓ BENAR (dimulai dari cerita):
  start_time = saat tamu mulai cerita "Jadi waktu itu gue invest 2 miliar di..."
  → Penonton: "Invest 2 miliar? Terus gimana?" → TONTON SAMPAI HABIS

PRINSIP: Pertanyaan/setup yang bagus = HOOK TERBAIK.
Penonton akan bertahan menonton kalau mereka PENASARAN dengan jawabannya.

==================================================
STRUKTUR NARATIF YANG DIWAJIBKAN
================================

Setiap clip harus terasa seperti mini-story:

• Awal: Setup / pernyataan pemicu / pertanyaan
• Tengah: Konflik / insight / cerita / jawaban
• Akhir: Punchline / payoff / statement kuat

Jika tidak ada payoff, tambahkan konteks hingga ada.

==================================================
STRUKTUR CLIP YANG OPTIMAL
==========================

Setiap clip harus mengikuti pola ini:

1. HOOK/SETUP (5-15 detik awal):
   - Pertanyaan yang memancing rasa ingin tahu
   - Statement kontroversial yang bikin "HAH?!"
   - Cerita pembuka yang bikin penasaran
   - Klaim mengejutkan yang butuh penjelasan

2. INTI/KONFLIK (30-60 detik tengah):
   - Jawaban/pembahasan dari pertanyaan
   - Cerita konflik/drama/insight
   - Penjelasan yang mengejutkan

3. PAYOFF/PENUTUP (5-15 detik akhir):
   - Kesimpulan yang powerful
   - Punchline yang bikin ngakak/terharu
   - Statement penutup yang memorable
   - Plot twist / fakta mengejutkan

Jika bagian HOOK/SETUP tidak ada di dekat jawaban:
→ MUNDURKAN start_time ke pertanyaan/konteks terdekat
→ Lebih baik clip sedikit lebih panjang tapi punya konteks

==================================================
PRINSIP PEMILIHAN CLIP (WAJIB DIPRIORITASKAN)
=============================================

Prioritaskan segmen dengan karakteristik berikut:

1. Ada PERTANYAAN menarik + JAWABAN mengejutkan (Q&A gold)
2. Ada KONFLIK, ketegangan, kontroversi.
3. Ada PENGAKUAN personal / vulnerability / curhat.
4. Ada STATEMENT tajam / opini berani / hot take.
5. Ada punchline atau momen lucu kuat.
6. Ada cerita lengkap (setup → buildup → payoff).
7. Ada kalimat yang bisa berdiri sendiri sebagai hook viral.
8. Ada FAKTA mengejutkan atau insight baru (untuk dokumenter/edukasi).
9. Ada momen EMOSIONAL kuat (haru, marah, takjub).
10. Ada VISUAL storytelling yang kuat (untuk dokumenter/travel).

JENIS KONTEN YANG DIDUKUNG:
- Podcast: fokus pada statement/punchline/drama
- Interview: fokus pada confession/insight personal
- Dokumenter: fokus pada fakta mengejutkan/momen emosional
- Edukasi: fokus pada mitos vs fakta, tips actionable, aha moment
- Vlog/Travel: fokus pada momen visual memorable
- Live Stream / Marathon Stream: fokus pada momen chaos, interaksi spontan, drama real-time, gurauan antar member, bintang tamu, milestone, cerita emosional

==================================================
🎮 KHUSUS LIVE STREAM / MARATHON STREAM (MARAPTHON-STYLE)
========================================================

Jika konten adalah LIVE STREAM berdurasi panjang (1-12+ jam), perhatikan:

Live stream BERBEDA dari podcast/interview biasa. Di live stream:
- Momen viral muncul SPONTAN dan TIDAK TERPREDIKSI
- Banyak peserta/member yang silih berganti bicara
- Ada interaksi dengan penonton (donasi, chat, video call)
- Ada momen dead air / bengong / filler yang HARUS DIHINDARI

TIPE MOMEN BERNILAI TINGGI DI LIVE STREAM:

1. 🔥 DRAMA & KLARIFIKASI (SKOR 9-10):
   - Member klarifikasi isu kontroversial
   - Asbun (ngomong asal/spontan) yang bikin heboh
   - Perdebatan/roasting antar member
   - Statement mengejutkan yang tidak disengaja
   - Curhat/confession spontan member

2. 😂 MOMEN KOCAK & CHAOS (SKOR 8-10):
   - Gurauan/banter antar member yang bikin ngakak
   - Reaksi berlebihan/kaget dari member
   - Momen awkward yang jadi lucu
   - Prank atau kejadian absurd spontan
   - Member ngomong hal random yang viral

3. 🌟 BINTANG TAMU & KEJUTAN (SKOR 8-10):
   - Tamu spesial datang (selebriti, kreator lain, dll)
   - Reaksi member saat tamu muncul
   - Interaksi unik antara tamu dan host
   - Surprise/kejutan di tengah live

4. 😢 MOMEN EMOSIONAL & CERITA SEDIH (SKOR 8-10):
   - Member cerita pengalaman berat/sedih
   - Momen haru yang bikin penonton ikut terharu
   - Dukungan/support antar member
   - Cerita personal tentang kehilangan/perjuangan
   - Momen tulus yang jarang terlihat

5. 🏆 MILESTONE & PENCAPAIAN (SKOR 7-9):
   - Target donasi/subscriber tercapai
   - Reaksi saat milestone tercapai
   - Pengumuman penting saat live
   - Momen "kita berhasil!" yang membahagiakan

6. 💬 INTERAKSI PENONTON EPIC (SKOR 7-9):
   - Donasi/superchat dengan pesan menarik + reaksi host
   - Video call dengan penonton yang unik/lucu/emosional
   - Chat wars atau momen interaksi massal
   - Media share yang bikin heboh

7. 🎲 GAMES & CHALLENGE (SKOR 6-8):
   - Momen seru saat main game bareng
   - Challenge antar member dengan taruhan
   - Reaksi kalah/menang yang dramatis
   - Momen kompetitif yang intens

8. 💰 MOMEN DERMAWAN & SOSIAL (SKOR 8-10):
   - Pengumuman bantuan sosial (haji, beasiswa, dll)
   - Donasi besar untuk kegiatan amal
   - Momen berbagi yang mengharukan
   - Statement tentang misi sosial live stream

DILARANG KERAS SAAT CLIPPING LIVE STREAM:
* Momen BENGONG / duduk diam tanpa bicara
* Momen loading/buffering/technical issue
* Transisi antar segment tanpa konten
* Obrolan ultra-ringan tanpa substansi ("halo", "gimana kabar")
* Member scroll HP tanpa interaksi
* Momen istirahat/makan tanpa percakapan menarik
* Bagian yang hanya menampilkan layar game tanpa komentar menarik

STRATEGI KHUSUS LIVE STREAM:
→ SKIP semua momen dead air / bengong
→ FOKUS pada puncak emosi, bukan build-up lambat
→ Pastikan setiap clip punya AKSI atau DIALOG yang jelas
→ Jika ada nama member/host → gunakan di hook_text
→ Cari momen dimana BANYAK orang bicara/bereaksi bersamaan
→ Untuk live stream 12+ jam, spread clips MERATA di seluruh durasi
→ JANGAN ambil semua clip dari 1-2 jam pertama saja

Hindari:

* Obrolan filler tanpa substansi
* Basa-basi / salam pembuka
* Intro/outro yang tidak menambah nilai
* Transisi topik tanpa payoff
* Penjelasan teknis panjang tanpa emosi
* Jawaban tanpa pertanyaan (kehilangan konteks)
* Punchline tanpa setup (kehilangan daya kejut)
* Momen bengong/diam tanpa dialog (khusus live stream)
* Bagian technical issue / loading screen (khusus live stream)

Jika harus memilih, utamakan EMOSI & KONFLIK dibanding edukasi netral.

==================================================
ATURAN DURASI (KRITIS – TIDAK BOLEH DILANGGAR)
==============================================

* Setiap clip HARUS 30–120 detik.
* Target ideal: 45–90 detik.
* Hitung durasi dari timestamp transcript.
* JANGAN estimasi berdasarkan panjang teks.
* LEBIH BAIK clip pendek yang powerful daripada clip panjang yang membosankan.

Jika durasi < 30 detik:
→ PERPANJANG ke belakang (mundurkan start_time ke pertanyaan/konteks).
→ PERPANJANG dengan konteks sebelum atau sesudahnya.

Jika durasi > 120 detik:
→ Pangkas bagian yang tidak relevan TANPA memotong pertanyaan awal.
→ Pangkas bagian yang tidak relevan TANPA merusak alur cerita.

==================================================
STRATEGI WAJIB JIKA SEGMENT IDEAL TIDAK ADA
===========================================

Lakukan salah satu atau kombinasi berikut:

1. Gabungkan pertanyaan + jawaban yang masih satu topik.
2. Gabungkan beberapa bagian berurutan yang masih satu topik.
3. Tambahkan setup/pertanyaan sebelum punchline agar ada konteks.
4. Tambahkan payoff setelah cerita agar terasa lengkap.
5. Pangkas filler tapi jaga minimal 30 detik.
6. Mundurkan start_time ke kalimat pemicu/pertanyaan terdekat.

DILARANG:

* Menghasilkan clip < 30 detik
* Memulai clip di tengah jawaban tanpa konteks
* Mengurangi jumlah clip
* Mengabaikan timestamp asli
* Mengarang timestamp

==================================================
FIELD WAJIB (PERSIS 6 FIELD – TIDAK BOLEH LEBIH/KURANG)
=======================================================

Setiap object HARUS memiliki:

1. "start_time" (string) → Format: "HH:MM:SS,mmm"
2. "end_time" (string) → Format: "HH:MM:SS,mmm"
3. "title" (string) → Maks 60 karakter, padat & click-worthy
4. "description" (string) → Maks 150 karakter, jelaskan kenapa viral
5. "virality_score" (integer) → 1–10 (HARUS ANGKA, BUKAN STRING)
6. "hook_text" (string) → Maks 15 kata

DILARANG:

* Field tambahan
* Field "reason"
* virality_score dalam bentuk string
* Komentar atau teks di luar JSON

==================================================
VIRALITY SCORE (WAJIB OBJEKTIF)
===============================

8–10:

* Kontroversial
* Pertanyaan kontroversial + jawaban mengejutkan
* Emosional kuat
* Confession pribadi / Pengakuan berat
* Statement berani / hot take
* Punchline keras / momen lucu viral

5–7:

* Q&A menarik tapi tidak kontroversial
* Insight menarik / cukup engaging
* Cerita cukup engaging / personal ringan
* Momen lucu ringan

1–4:

* Informasi biasa tanpa hook
* Tidak ada pertanyaan menarik
* Tidak ada emosi / konflik
* Tidak ada hook kuat

Jangan kasih semua clip skor tinggi.
Nilai dengan rasional.

==================================================
HOOK TEXT (HARUS TAJAM & MENJUAL)
=================================

WAJIB:

* Maksimal 15 kata
* Bahasa Indonesia casual
* TANPA emoji
* WAJIB menyebut NAMA ORANG yang berbicara
* Harus berupa kutipan, statement tajam, atau punchline
* PRIORITAS: Gunakan PERTANYAAN sebagai hook (karena pertanyaan = rasa penasaran)
* Atau kutipan/statement tajam yang bikin "HAH?!"

Contoh benar (pertanyaan sebagai hook):
"Host ke Dr. Tirta: Dok benarkah GERD bisa bikin serangan jantung?"
"Deddy: Lo pernah hampir mati beneran?"

Contoh benar (statement sebagai hook):
"Andre Taulany: Gua hampir bangkrut gara-gara ini"
"Deddy Corbuzier: Banyak podcaster cuma pura-pura sukses"
"Dr. Tirta: 90% orang salah paham soal GERD"

Contoh benar (live stream / marapthon):
"Aloy tiba-tiba asbun: Gue mau klarifikasi sesuatu!"
"Member nangis cerita soal keluarganya di live"
"SMASH datang ke Marapthon, semua member kaget!"
"Arap: Kita berhasil berangkatkan haji 4 orang!"
"Momen chaos saat donasi tembus target di live"

Hook harus bisa berdiri sendiri sebagai headline viral.

==================================================
SELF-VALIDATION (WAJIB SEBELUM RETURN)
======================================

Periksa:

1. Jumlah segment = {num_clips} ?
2. Semua durasi 30–120 detik ?
3. Setiap clip dimulai dari PERTANYAAN/KONTEKS, bukan tengah jawaban ?
4. Semua punya tepat 6 field ?
5. virality_score berupa integer 1–10 ?
6. Tidak ada field lain ?
7. Tidak ada teks di luar JSON ?

Jika ada kesalahan → PERBAIKI sebelum output.

==================================================
OUTPUT FORMAT (STRICT)
======================

Return HANYA JSON array.
Tanpa markdown.
Tanpa penjelasan.
Tanpa komentar.

Format EXACT seperti ini:

[{{"start_time":"HH:MM:SS,mmm","end_time":"HH:MM:SS,mmm","title":"...","description":"...","virality_score":8,"hook_text":"..."}}]

==================================================
KONTEN
======

{video_context}

Transcript:
{transcript}"""
    
    def process(self, url: str, num_clips: int = 5, add_captions: bool = True, add_hook: bool = True, custom_rules: str = ""):
        """
        Main processing pipeline with checkpoint support for long videos.
        Can resume from last checkpoint if processing was interrupted.
        """
        
        # Check for existing checkpoint
        checkpoint = self.load_checkpoint()
        video_path = None
        srt_path = None
        video_info = None
        highlights = None
        start_clip_index = 0
        
        if checkpoint and checkpoint.get('data', {}).get('url') == url:
            stage = checkpoint.get('stage', '')
            data = checkpoint.get('data', {})
            
            if stage == 'downloaded':
                # Resume from after download
                video_path = data.get('video_path')
                srt_path = data.get('srt_path')
                video_info = data.get('video_info', {})
                if video_path and Path(video_path).exists():
                    self.log(f"  📂 Resuming from checkpoint: download complete")
                else:
                    checkpoint = None  # File not found, restart
                    
            elif stage == 'highlights_found':
                # Resume from after highlights
                video_path = data.get('video_path')
                srt_path = data.get('srt_path')
                video_info = data.get('video_info', {})
                highlights = data.get('highlights', [])
                if video_path and Path(video_path).exists() and highlights:
                    self.log(f"  📂 Resuming from checkpoint: {len(highlights)} highlights found")
                else:
                    checkpoint = None
                    
            elif stage == 'clip_processed':
                # Resume from middle of clip processing
                video_path = data.get('video_path')
                srt_path = data.get('srt_path')
                video_info = data.get('video_info', {})
                highlights = data.get('highlights', [])
                start_clip_index = data.get('last_clip_index', 0)
                if video_path and Path(video_path).exists() and highlights:
                    self.log(f"  📂 Resuming from checkpoint: clip {start_clip_index}/{len(highlights)}")
                else:
                    checkpoint = None
        
        # Step 1: Download video (if not resuming)
        if not video_path:
            self.set_progress("Downloading video...", 0.1)
            video_path, srt_path, video_info = self.download_video(url)
            
            # Save checkpoint after successful download
            self.save_checkpoint('downloaded', {
                'url': url,
                'video_path': video_path,
                'srt_path': srt_path,
                'video_info': video_info
            })
        
        # Store channel name for credit watermark
        self.channel_name = video_info.get("channel", "") if video_info else ""
        
        if self.is_cancelled():
            return
        
        if not srt_path:
            self.log("  ℹ Subtitle YouTube tidak ditemukan langsung, mencoba auto-transcribe dengan Whisper...")
            srt_path = self._auto_transcribe_video_to_srt(video_path)

        if not srt_path:
            # Provide helpful error message with available subtitles
            raise Exception(
                f"❌ ERROR: Subtitle tidak tersedia\n\n"
                f"Video ini tidak memiliki subtitle bahasa: {self.subtitle_language.upper()}\n\n"
                f"SOLUSI:\n"
                f"1. Cek subtitle yang tersedia untuk video ini:\n"
                f"   - Klik tombol 'Check Subtitles' di aplikasi\n"
                f"   - Atau buka video di YouTube dan cek CC/subtitle\n\n"
                f"2. Pilih bahasa subtitle lain yang tersedia\n"
                f"   (contoh: en - English, es - Spanish)\n\n"
                f"3. Atau gunakan video lain yang punya subtitle Indonesia\n\n"
                f"💡 TIP: Video podcast/interview biasanya punya auto-generated subtitle\n"
                f"dalam berbagai bahasa. Pilih yang paling mendekati."
            )
        
        # Log video duration for long videos
        video_duration = self.get_video_duration_from_srt(srt_path)
        if video_duration > 3600:  # > 1 hour
            hours = video_duration / 3600
            self.log(f"  📺 Long video detected: {hours:.1f} hours")
        
        # Step 2: Find highlights (if not resuming)
        if not highlights:
            self.set_progress("Finding highlights...", 0.3)
            transcript = self.parse_srt(srt_path)
            highlights = self.find_highlights(transcript, video_info, num_clips, custom_rules=custom_rules)
            
            # Save checkpoint after finding highlights
            self.save_checkpoint('highlights_found', {
                'url': url,
                'video_path': video_path,
                'srt_path': srt_path,
                'video_info': video_info,
                'highlights': highlights
            })
        
        if self.is_cancelled():
            return
        
        if not highlights:
            raise Exception("No valid highlights found!")
        
        # Step 3: Process each clip (with checkpoint per clip)
        total_clips = len(highlights)
        for i, highlight in enumerate(highlights[start_clip_index:], start_clip_index + 1):
            if self.is_cancelled():
                return
            
            self.process_clip(video_path, highlight, i, total_clips, add_captions=add_captions, add_hook=add_hook)
            
            # Save checkpoint after each clip for long videos
            if video_duration > 3600:
                self.save_checkpoint('clip_processed', {
                    'url': url,
                    'video_path': video_path,
                    'srt_path': srt_path,
                    'video_info': video_info,
                    'highlights': highlights,
                    'last_clip_index': i
                })
        
        # Cleanup
        self.set_progress("Cleaning up...", 0.95)
        self.cleanup()
        
        # Clear checkpoint on successful completion
        self.clear_checkpoint()
        
        self.set_progress("Complete!", 1.0)
        self.log(f"\n✅ Created {total_clips} clips in: {self.output_dir}")
    
    def download_video(self, url: str) -> tuple:
        """Download video and subtitle with progress using yt-dlp module or executable"""
        self.log("[1/4] Downloading video & subtitle...")
        
        # Check if using yt-dlp module
        use_module = YTDLP_MODULE_AVAILABLE and self.ytdlp_path == "yt_dlp_module"
        
        if use_module:
            # Prefer subprocess path for download stability (especially YouTube SABR sessions).
            # We still use the installed module by invoking `python -m yt_dlp` in subprocess mode.
            self.log("  Using module-backed subprocess downloader for better reliability...")
            return self._download_video_subprocess(url)
        else:
            return self._download_video_subprocess(url)
    
    def _download_video_module(self, url: str) -> tuple:
        """Download video using yt-dlp Python module API"""
        _ensure_yt_dlp()
        self.log(f"  Using yt-dlp module v{yt_dlp.version.__version__}")
        
        video_info = {}
        
        # Get FFmpeg and Deno paths
        ffmpeg_path = get_ffmpeg_path()
        deno_path = get_deno_path()
        
        self.log(f"  FFmpeg path: {ffmpeg_path}")
        self.log(f"  Deno path: {deno_path}")
        
        # Setup environment with Deno in PATH
        if deno_path and Path(deno_path).exists():
            deno_dir = str(Path(deno_path).parent)
            if "PATH" in os.environ:
                os.environ["PATH"] = f"{deno_dir}{os.pathsep}{os.environ['PATH']}"
            else:
                os.environ["PATH"] = deno_dir
            self.log(f"  Deno added to PATH: {deno_dir}")
        else:
            self.log(f"  WARNING: Deno not found!")
        
        # Progress hook for yt-dlp
        def progress_hook(d):
            if self.is_cancelled():
                raise Exception("Cancelled by user")
            
            if d['status'] == 'downloading':
                percent_str = d.get('_percent_str', '0%').strip()
                # Extract numeric percent
                match = re.search(r'(\d+\.?\d*)%', percent_str)
                if match:
                    percent = float(match.group(1))
                    self.set_progress(f"Downloading video... {percent:.1f}%", 0.05 + percent / 100 * 0.2)
            elif d['status'] == 'finished':
                self.log("  Download finished, processing...")
                self.set_progress("Processing downloaded file...", 0.25)
        
        # High-quality format selector with fallbacks
        # Use 'bv*+ba/b' as ultimate fallback to get ANY available format
        format_selector = "bestvideo[height>=720][height<=2160]+bestaudio/best[height>=720][height<=2160]/bestvideo+bestaudio/best/bv*+ba/b"
        
        # Base yt-dlp options
        ydl_opts = {
            'format': format_selector,
            'format_sort': ['res', 'br'],
        }
        
        # Only request subtitles if a real language is selected (skip for AI transcription mode)
        if self.subtitle_language and self.subtitle_language != "none":
            ydl_opts['writesubtitles'] = True
            ydl_opts['writeautomaticsub'] = True
            # Include base language as fallback for codes like 'id-orig'
            sub_langs = [self.subtitle_language]
            base_lang = self.subtitle_language.split('-')[0] if '-' in self.subtitle_language else None
            if base_lang and base_lang not in sub_langs:
                sub_langs.append(base_lang)
            ydl_opts['subtitleslangs'] = sub_langs
            ydl_opts['subtitlesformat'] = 'srt'
        else:
            self.log("  Skipping subtitle download (AI transcription mode)")
        
        # Common options
        ydl_opts.update({
            'merge_output_format': 'mp4',
            'outtmpl': str(self.temp_dir / 'source.%(ext)s'),
            'progress_hooks': [progress_hook],
            'quiet': True,
            'no_warnings': False,
            'extract_flat': False,
            'ignore_no_formats_error': True,  # Don't fail if some formats unavailable
            # Network resilience options for unstable connections
            'retries': 10,  # Retry download on error
            'fragment_retries': 10,  # Retry failed fragments
            'file_access_retries': 5,  # Retry file access errors
            'socket_timeout': 30,  # Timeout for socket operations
            'http_chunk_size': 1048576,  # 1MB chunks for better resume
            'noprogress': False,
            'continuedl': True,  # Continue partial downloads
            # NOTE: Don't force specific player_client here - it can prevent
            # auto-generated subtitles from being downloaded (PO token requirement).
            # Let yt-dlp use its default client selection for best compatibility.
        })
        
        # Add Deno JS runtime if available
        if deno_path and Path(deno_path).exists():
            ydl_opts['js_runtimes'] = {'deno': {'path': deno_path}}
            ydl_opts['remote_components'] = ['ejs:github']
            self.log(f"  JS runtime: deno at {deno_path}")
        else:
            self.log(f"  WARNING: Deno not found - some formats may be missing!")
        
        # Add FFmpeg location if available
        if ffmpeg_path and Path(ffmpeg_path).exists():
            ydl_opts['ffmpeg_location'] = str(Path(ffmpeg_path).parent)
            self.log(f"  FFmpeg location: {ydl_opts['ffmpeg_location']}")
            
            # Only add subtitle converter postprocessor if FFmpeg is available
            # This prevents "Postprocessing: Conversion failed!" error
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegSubtitlesConvertor',
                'format': 'srt',
            }]
        else:
            self.log(f"  WARNING: FFmpeg not found - subtitle conversion disabled")
        
        # Add cookies (required)
        from utils.helpers import get_app_dir
        app_dir = get_app_dir()
        cookies_locations = [
            Path("cookies.txt"),  # Current directory
            app_dir / "cookies.txt",  # App directory
        ]
        
        cookies_path = None
        for loc in cookies_locations:
            self.log(f"  Checking cookies at: {loc} - exists: {loc.exists()}")
            if loc.exists():
                cookies_path = loc
                break
        
        if not cookies_path:
            raise Exception("cookies.txt not found!\n\nPlease upload cookies.txt file from home page.")
        
        ydl_opts['cookiefile'] = str(cookies_path)
        self.log(f"  Using cookies from: {cookies_path}")
        
        # Single download attempt (no browser cookies fallback)
        last_error = None
        try:
            self.log(f"  Starting download...")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # First get video info
                self.log("  Fetching video info...")
                info = ydl.extract_info(url, download=False)
                
                if info:
                    video_info = {
                        "title": info.get("title", ""),
                        "description": (info.get("description", "") or "")[:2000],
                        "channel": info.get("channel", ""),
                        "duration": info.get("duration", 0),
                    }
                    self.log(f"  Title: {video_info['title'][:50]}...")
                    
                    # Extract heatmap (Most Replayed) data from YouTube
                    raw_heatmap = info.get("heatmap")
                    if raw_heatmap and isinstance(raw_heatmap, list) and len(raw_heatmap) > 0:
                        self.heatmap_data = raw_heatmap
                        # Find peak engagement
                        peak = max(raw_heatmap, key=lambda x: x.get("value", 0))
                        avg_val = sum(h.get("value", 0) for h in raw_heatmap) / len(raw_heatmap)
                        self.log(f"  📊 Heatmap: {len(raw_heatmap)} segments | peak={peak['value']:.2f} at {peak['start_time']:.0f}s | avg={avg_val:.2f}")
                    else:
                        self.heatmap_data = None
                        self.log(f"  📊 Heatmap: not available for this video")
                
                # Now download
                self.log(f"  Downloading video with {self.subtitle_language} subtitle...")
                ydl.download([url])
            
            video_path = self.temp_dir / "source.mp4"
            part_path = self.temp_dir / "source.mp4.part"
            state_path = self.temp_dir / "source.mp4.ytdl"

            # yt-dlp module mode may finish subtitle download while video stream stalls
            # (e.g. SABR / client-format mismatch). Detect this and fallback to subprocess strategy.
            invalid_video = (
                (not video_path.exists())
                or (video_path.exists() and video_path.stat().st_size == 0)
                or (part_path.exists() and part_path.stat().st_size == 0)
            )
            if invalid_video:
                self.log("  ⚠ Video file not completed in module mode (only partial/subtitle artifacts found)")
                self.log("  ↪ Falling back to subprocess download strategy...")
                for stale_path in (video_path, part_path, state_path):
                    try:
                        if stale_path.exists():
                            stale_path.unlink()
                    except Exception as cleanup_err:
                        self.log(f"  Warning: could not remove stale file {stale_path.name}: {cleanup_err}")
                return self._download_video_subprocess(url)

            self.log(f"  ✓ Download successful!")
                
        except Exception as e:
            last_error = str(e)
            self.log(f"  ✗ Failed: {last_error[:100]}")

            # If module mode failed (e.g. HTTP 403 Forbidden with expired cookies.txt or format issue),
            # try falling back to subprocess strategy which tries Chrome/Edge browser cookies, no-auth, and mobile client!
            if not self.is_cancelled():
                self.log("  ↪ Mencoba strategi download alternatif (subprocess / browser cookies / client fallback)...")
                video_path = self.temp_dir / "source.mp4"
                part_path = self.temp_dir / "source.mp4.part"
                state_path = self.temp_dir / "source.mp4.ytdl"
                for stale_path in (video_path, part_path, state_path):
                    try:
                        if stale_path.exists():
                            stale_path.unlink()
                    except Exception as cleanup_err:
                        self.log(f"  Warning: could not remove stale file {stale_path.name}: {cleanup_err}")
                try:
                    return self._download_video_subprocess(url)
                except Exception as sub_err:
                    last_error = str(sub_err)

            # Provide helpful error message for common issues if all methods failed
            if "403" in last_error or "Forbidden" in last_error:
                raise Exception(
                    "❌ ERROR: YouTube menolak akses (HTTP 403 Forbidden)\n\n"
                    "PENYEBAB:\n"
                    "• Cookies sudah EXPIRED (biasanya 1-2 minggu)\n"
                    "• Cookies tidak lengkap atau tidak valid\n"
                    "• Browser tidak login ke YouTube saat export cookies\n\n"
                    "SOLUSI:\n"
                    "1. Buka youtube.com di browser\n"
                    "2. PASTIKAN sudah LOGIN ke akun YouTube/Google\n"
                    "3. Export cookies BARU menggunakan extension:\n"
                    "   - Chrome/Edge: 'Get cookies.txt LOCALLY'\n"
                    "   - Firefox: 'cookies.txt'\n"
                    "4. Upload cookies.txt yang baru di halaman Home\n\n"
                    "📖 Lihat COOKIES.md untuk panduan lengkap\n\n"
                    f"Detail error:\n{last_error}"
                )
            elif "downloaded file is empty" in last_error.lower() or "file is empty" in last_error.lower():
                raise Exception(
                    "❌ ERROR: File video kosong (0 bytes)\n\n"
                    "PENYEBAB:\n"
                    "• YouTube mendeteksi aktivitas BOT\n"
                    "• Cookies tidak cukup kuat untuk akses video content\n"
                    "• Video mungkin memiliki proteksi khusus\n\n"
                    "SOLUSI:\n"
                    "1. Buka browser INCOGNITO/PRIVATE mode\n"
                    "2. Buka youtube.com dan LOGIN ke akun Google\n"
                    "3. Tonton 2-3 video LENGKAP (bukan skip)\n"
                    "4. Buka video yang ingin di-download, tonton sebentar\n"
                    "5. Export cookies BARU dengan extension:\n"
                    "   - Chrome/Edge: 'Get cookies.txt LOCALLY'\n"
                    "   - Firefox: 'cookies.txt'\n"
                    "6. Upload cookies.txt yang baru\n\n"
                    "💡 TIP: Gunakan akun yang aktif menonton YouTube\n"
                    "📖 Lihat COOKIES.md untuk panduan lengkap"
                )
            elif "Sign in to confirm" in last_error or "bot" in last_error.lower():
                raise Exception(
                    "❌ ERROR: YouTube meminta verifikasi bot\n\n"
                    "PENYEBAB:\n"
                    "• Cookies sudah tidak valid\n"
                    "• YouTube mendeteksi aktivitas mencurigakan\n\n"
                    "SOLUSI:\n"
                    "1. Buka youtube.com di browser INCOGNITO/PRIVATE\n"
                    "2. Login ke akun YouTube/Google\n"
                    "3. Tonton 1-2 video untuk 'warm up' akun\n"
                    "4. Export cookies baru\n"
                    "5. Upload cookies.txt yang baru\n\n"
                    "📖 Lihat COOKIES.md untuk panduan lengkap"
                )
            else:
                raise Exception(f"Download failed!\n\n{last_error}")
        
        video_path = self.temp_dir / "source.mp4"
        srt_path = self._find_subtitle_file()
        
        return str(video_path), str(srt_path) if srt_path else None, video_info
    
    def _find_subtitle_file(self):
        """Find the downloaded subtitle file with fallback logic.
        
        Handles cases where yt-dlp saves the file with a different language
        code than requested (e.g., requesting 'id-orig' but file saved as
        'source.id-orig.srt' or 'source.id.srt').
        """
        # Try exact match first
        srt_path = self.temp_dir / f"source.{self.subtitle_language}.srt"
        if srt_path.exists():
            self.log(f"  ✓ Subtitle found: {srt_path.name}")
            return srt_path
        
        # Try base language (e.g., 'id' for 'id-orig')
        if '-' in self.subtitle_language:
            base_lang = self.subtitle_language.split('-')[0]
            base_path = self.temp_dir / f"source.{base_lang}.srt"
            if base_path.exists():
                self.log(f"  ⚠ {self.subtitle_language} not found, using {base_lang} subtitle instead")
                return base_path
        
        # Glob fallback - any subtitle file
        available_subs = list(self.temp_dir.glob("source.*.srt"))
        if available_subs:
            srt_path = available_subs[0]
            detected_lang = srt_path.stem.split('.')[-1]
            self.log(f"  ⚠ {self.subtitle_language} subtitle not found, using {detected_lang} instead")
            return srt_path
        
        # Nothing found - log available files for debugging
        all_files = list(self.temp_dir.glob("source.*"))
        self.log(f"  ✗ No subtitle found for language: {self.subtitle_language}")
        self.log(f"  Files in temp dir: {[f.name for f in all_files]}")
        return None

    def _auto_transcribe_video_to_srt(self, video_path) -> Optional[Path]:
        """Auto-transcribe video to an SRT file using Whisper API when YouTube has no subtitles"""
        try:
            if not video_path or not Path(video_path).exists():
                return None

            self.log("  🎙 Mengekstrak audio video untuk transkripsi AI Whisper...")
            audio_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False).name
            cmd = [
                self.ffmpeg_path, "-y",
                "-i", str(video_path),
                "-vn",
                "-acodec", "pcm_s16le",
                "-ar", "16000",
                "-ac", "1",
                audio_file
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)
            if result.returncode != 0 or not os.path.exists(audio_file) or os.path.getsize(audio_file) < 1000:
                self.log("  ⚠ Gagal mengekstrak audio untuk transkrip.")
                return None

            self.log(f"  🎙 Mengirim audio ke Whisper ({self.whisper_model})...")
            resp = None
            try:
                with open(audio_file, "rb") as f:
                    resp = self.caption_client.audio.transcriptions.create(
                        model=self.whisper_model,
                        file=f,
                        response_format="verbose_json",
                        timestamp_granularities=["segment"]
                    )
            except Exception as w_err:
                self.log(f"  ⚠ Whisper transkrip error: {w_err}")
                return None
            finally:
                try:
                    os.unlink(audio_file)
                except Exception:
                    pass

            segments = getattr(resp, "segments", None)
            if not segments and isinstance(resp, dict):
                segments = resp.get("segments", [])

            if not segments:
                self.log("  ⚠ Whisper tidak menghasilkan segmen transkrip.")
                return None

            target_lang = self.subtitle_language or "id"
            srt_file = self.temp_dir / f"source.{target_lang}.srt"
            with open(srt_file, "w", encoding="utf-8") as out:
                for idx, seg in enumerate(segments, 1):
                    start = float(seg.get("start", 0) if isinstance(seg, dict) else getattr(seg, "start", 0))
                    end = float(seg.get("end", 0) if isinstance(seg, dict) else getattr(seg, "end", 0))
                    text = str(seg.get("text", "") if isinstance(seg, dict) else getattr(seg, "text", "")).strip()

                    s_h, s_rem = divmod(start, 3600)
                    s_m, s_s = divmod(s_rem, 60)
                    s_ms = int((s_s - int(s_s)) * 1000)

                    e_h, e_rem = divmod(end, 3600)
                    e_m, e_s = divmod(e_rem, 60)
                    e_ms = int((e_s - int(e_s)) * 1000)

                    out.write(f"{idx}\n")
                    out.write(f"{int(s_h):02d}:{int(s_m):02d}:{int(s_s):02d},{s_ms:03d} --> {int(e_h):02d}:{int(e_m):02d}:{int(e_s):02d},{e_ms:03d}\n")
                    out.write(f"{text}\n\n")

            self.log(f"  ✓ Transkrip berhasil dibuat otomatis dengan Whisper: {srt_file.name}")
            return srt_file

        except Exception as e:
            self.log(f"  ⚠ Auto-transcribe gagal: {e}")
            return None
    
    def _download_video_subprocess(self, url: str) -> tuple:
        """Download video using yt-dlp subprocess (fallback)"""
        ytdlp_cmd = [sys.executable, "-m", "yt_dlp"] if self.ytdlp_path == "yt_dlp_module" else [self.ytdlp_path]

        # Validate yt-dlp is available
        try:
            version_check = subprocess.run(
                [*ytdlp_cmd, "--version"],
                capture_output=True,
                text=True,
                creationflags=SUBPROCESS_FLAGS,
                timeout=5
            )
            if version_check.returncode != 0:
                raise Exception(f"yt-dlp not working properly. Path: {self.ytdlp_path}")
            self.log(f"  Using yt-dlp version: {version_check.stdout.strip()}")
        except FileNotFoundError:
            raise Exception(f"yt-dlp not found at: {self.ytdlp_path}\n\nPlease install yt-dlp or check the path in settings.")
        except subprocess.TimeoutExpired:
            raise Exception(f"yt-dlp not responding. Path: {self.ytdlp_path}")
        except Exception as e:
            raise Exception(f"Failed to validate yt-dlp: {str(e)}")
        
        base_args = []
        try:
            help_result = subprocess.run(
                [*ytdlp_cmd, "--help"],
                capture_output=True,
                text=True,
                creationflags=SUBPROCESS_FLAGS,
                timeout=5
            )
            if help_result.returncode == 0:
                help_text = help_result.stdout
                if "--no-impersonate" in help_text:
                    base_args.append("--no-impersonate")
        except Exception:
            pass
        
        # Get video metadata
        self.log("  Fetching video info...")
        meta_cmd = [*ytdlp_cmd, "--dump-json", "--no-download", *base_args, url]
        
        result = subprocess.run(
            meta_cmd, 
            capture_output=True, 
            text=True,
            creationflags=SUBPROCESS_FLAGS
        )
        video_info = {}
        
        if result.returncode == 0:
            try:
                yt_data = json.loads(result.stdout)
                video_info = {
                    "title": yt_data.get("title", ""),
                    "description": yt_data.get("description", "")[:2000],
                    "channel": yt_data.get("channel", ""),
                }
                self.log(f"  Title: {video_info['title'][:50]}...")
            except json.JSONDecodeError:
                self.log("  Warning: Could not parse metadata")
        
        # Download video + subtitle with progress
        self.log(f"  Downloading video with {self.subtitle_language} subtitle...")

        # Resolve cookies file path (prefer app cookies.txt)
        from utils.helpers import get_app_dir
        app_dir = get_app_dir()
        cookie_candidates = [
            Path("cookies.txt"),
            app_dir / "cookies.txt",
        ]
        cookies_file = next((p for p in cookie_candidates if p.exists()), None)
        
        # Try multiple download strategies (fallback on failure)
        download_strategies = []
        if cookies_file:
            download_strategies.append(
                {
                    "name": "cookies.txt file",
                    "extra_args": ["--cookies", str(cookies_file)]
                }
            )
        download_strategies.extend([
            {
                "name": "Browser cookies (Chrome)",
                "extra_args": ["--cookies-from-browser", "chrome"]
            },
            {
                "name": "Browser cookies (Edge)",
                "extra_args": ["--cookies-from-browser", "edge"]
            },
            {
                "name": "Simple format (no auth)",
                "extra_args": []
            },
            {
                "name": "Android client fallback",
                "extra_args": ["--extractor-args", "youtube:player_client=android,web"]
            }
        ])
        
        # High-quality format selector (prioritize 720p+ with fallback)
        format_selector = "bestvideo[height>=720][height<=2160]+bestaudio/best[height>=720][height<=2160]/bestvideo+bestaudio/best"
        
        last_error = None
        for strategy in download_strategies:
            if self.is_cancelled():
                raise Exception("Cancelled by user")
            
            self.log(f"  Trying: {strategy['name']}...")
            
            cmd = [
                *ytdlp_cmd,
                "-f", format_selector,
                "--format-sort", "res,br",
                *base_args,
                *strategy["extra_args"],
            ]
            
            # Only request subtitles if a real language is selected
            if self.subtitle_language and self.subtitle_language != "none":
                # Include base language as fallback (e.g., 'id' for 'id-orig')
                sub_langs = self.subtitle_language
                base_lang = self.subtitle_language.split('-')[0] if '-' in self.subtitle_language else None
                if base_lang:
                    sub_langs = f"{self.subtitle_language},{base_lang}"
                cmd.extend([
                    "--write-sub", "--write-auto-sub",
                    "--sub-lang", sub_langs,
                    "--convert-subs", "srt",
                ])
            
            cmd.extend([
                "--merge-output-format", "mp4",
                "--newline",
                "-o", str(self.temp_dir / "source.%(ext)s"),
                url
            ])
            
            # Run with realtime progress output
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=SUBPROCESS_FLAGS
            )
            
            last_progress = ""
            output_lines = []
            
            while True:
                if self.is_cancelled():
                    process.terminate()
                    process.wait()
                    raise Exception("Cancelled by user")
                
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                
                line = line.strip()
                output_lines.append(line)
                
                if not line:
                    continue
                    
                # Parse download progress
                if "[download]" in line and "%" in line:
                    match = re.search(r'(\d+\.?\d*)%', line)
                    if match:
                        percent = match.group(1)
                        progress_text = f"  Downloading: {percent}%"
                        if progress_text != last_progress:
                            self.set_progress(f"Downloading video... {percent}%", 0.05 + float(percent) / 100 * 0.2)
                            last_progress = progress_text
                elif "[Merger]" in line or "Merging" in line:
                    self.log("  Merging video & audio...")
                    self.set_progress("Merging video & audio...", 0.25)
            
            # Check if successful
            if process.returncode == 0:
                self.log(f"  ✓ Download successful using: {strategy['name']}")
                break
            else:
                # Capture error for logging
                stderr_output = process.stderr.read() if process.stderr else ""
                error_lines = []
                
                for line in output_lines + stderr_output.split('\n'):
                    line = line.strip()
                    if line and ('ERROR' in line or 'error' in line):
                        error_lines.append(line)
                
                last_error = '\n'.join(error_lines[-5:]) if error_lines else f"Return code {process.returncode}"
                self.log(f"  ✗ Failed: {last_error.split(chr(10))[0][:80]}")  # First line only
                
                # Continue to next strategy
                continue
        else:
            # All strategies failed - provide helpful error message
            if last_error and ("403" in last_error or "Forbidden" in last_error):
                raise Exception(
                    "❌ ERROR: YouTube menolak akses (HTTP 403 Forbidden)\n\n"
                    "PENYEBAB:\n"
                    "• Cookies sudah EXPIRED (biasanya 1-2 minggu)\n"
                    "• Cookies tidak lengkap atau tidak valid\n"
                    "• Browser tidak login ke YouTube saat export cookies\n\n"
                    "SOLUSI:\n"
                    "1. Buka youtube.com di browser\n"
                    "2. PASTIKAN sudah LOGIN ke akun YouTube/Google\n"
                    "3. Export cookies BARU menggunakan extension:\n"
                    "   - Chrome/Edge: 'Get cookies.txt LOCALLY'\n"
                    "   - Firefox: 'cookies.txt'\n"
                    "4. Upload cookies.txt yang baru di halaman Home\n\n"
                    "📖 Lihat COOKIES.md untuk panduan lengkap\n\n"
                    f"Detail error:\n{last_error}"
                )
            elif last_error and ("downloaded file is empty" in last_error.lower() or "file is empty" in last_error.lower()):
                raise Exception(
                    "❌ ERROR: File video kosong (0 bytes)\n\n"
                    "PENYEBAB:\n"
                    "• YouTube mendeteksi aktivitas BOT\n"
                    "• Cookies tidak cukup kuat untuk akses video content\n"
                    "• Video mungkin memiliki proteksi khusus\n\n"
                    "SOLUSI:\n"
                    "1. Buka browser INCOGNITO/PRIVATE mode\n"
                    "2. Buka youtube.com dan LOGIN ke akun Google\n"
                    "3. Tonton 2-3 video LENGKAP (bukan skip)\n"
                    "4. Buka video yang ingin di-download, tonton sebentar\n"
                    "5. Export cookies BARU dengan extension:\n"
                    "   - Chrome/Edge: 'Get cookies.txt LOCALLY'\n"
                    "   - Firefox: 'cookies.txt'\n"
                    "6. Upload cookies.txt yang baru\n\n"
                    "💡 TIP: Gunakan akun yang aktif menonton YouTube\n"
                    "📖 Lihat COOKIES.md untuk panduan lengkap\n\n"
                    f"Detail error:\n{last_error}"
                )
            elif last_error and ("Sign in to confirm" in last_error or "bot" in last_error.lower()):
                raise Exception(
                    "❌ ERROR: YouTube meminta verifikasi bot\n\n"
                    "PENYEBAB:\n"
                    "• Cookies sudah tidak valid\n"
                    "• YouTube mendeteksi aktivitas mencurigakan\n\n"
                    "SOLUSI:\n"
                    "1. Buka youtube.com di browser INCOGNITO/PRIVATE\n"
                    "2. Login ke akun YouTube/Google\n"
                    "3. Tonton 1-2 video untuk 'warm up' akun\n"
                    "4. Export cookies baru\n"
                    "5. Upload cookies.txt yang baru\n\n"
                    "📖 Lihat COOKIES.md untuk panduan lengkap\n\n"
                    f"Detail error:\n{last_error}"
                )
            else:
                raise Exception(f"Download failed after trying all methods!\n\nLast error:\n{last_error}")
        
        video_path = self.temp_dir / "source.mp4"
        srt_path = self._find_subtitle_file()
        
        return str(video_path), str(srt_path) if srt_path else None, video_info

    @staticmethod
    def get_available_subtitles(url: str, ytdlp_path: str = "yt-dlp", cookies_path: str = None) -> dict:
        """Get list of available subtitles for a YouTube video with resilient multi-strategy fallback.

        Args:
            url: YouTube video URL
            ytdlp_path: Path to yt-dlp executable or "yt_dlp_module" for module
            cookies_path: Path to cookies.txt file (optional)

        Returns:
            dict with keys:
                - 'subtitles': list of manual subtitle languages
                - 'automatic_captions': list of auto-generated subtitle languages
                - 'error': error message if failed
        """
        # Language name mapping (common ones)
        lang_names = {
            "en": "English",
            "id": "Indonesian",
            "es": "Spanish",
            "fr": "French",
            "de": "German",
            "pt": "Portuguese",
            "ru": "Russian",
            "ja": "Japanese",
            "ko": "Korean",
            "zh": "Chinese",
            "ar": "Arabic",
            "hi": "Hindi",
            "it": "Italian",
            "nl": "Dutch",
            "pl": "Polish",
            "tr": "Turkish",
            "vi": "Vietnamese",
            "th": "Thai",
        }

        # Strategy 1: Quick module mode with cookies
        if YTDLP_MODULE_AVAILABLE and cookies_path and Path(cookies_path).exists():
            debug_log("Trying subtitle fetch Strategy 1: Module with cookies.txt...")
            res = AutoClipperCore._get_subtitles_module(url, cookies_path, lang_names)
            if not res.get("error") and (res.get("subtitles") or res.get("automatic_captions")):
                return res

        # Strategy 2: Quick module mode WITHOUT cookies (avoid expired cookies blocks)
        if YTDLP_MODULE_AVAILABLE:
            debug_log("Trying subtitle fetch Strategy 2: Module anonymous...")
            res = AutoClipperCore._get_subtitles_module(url, None, lang_names)
            if not res.get("error") and (res.get("subtitles") or res.get("automatic_captions")):
                return res

        # Immediate fallback: Return standard language options so user is NEVER blocked
        debug_log("No direct YouTube subtitles. Providing default Whisper / AI transcribe options.")
        return {
            "subtitles": [
                {"code": "id", "name": "Indonesian (id)"},
                {"code": "en", "name": "English (en)"},
            ],
            "automatic_captions": [],
            "error": None
        }

    @staticmethod
    def _get_subtitles_module(url: str, cookies_path: str, lang_names: dict) -> dict:
        """Get subtitles using yt-dlp Python module API with 5s timeout"""
        try:
            _ensure_yt_dlp()

            ydl_opts = {
                'skip_download': True,
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'ignore_no_formats_error': True,
                'socket_timeout': 5,
                'retries': 0,
            }

            if cookies_path and Path(cookies_path).exists():
                ydl_opts['cookiefile'] = str(cookies_path)

            deno_path = get_deno_path()
            if deno_path and Path(deno_path).exists():
                ydl_opts['js_runtimes'] = {'deno': {'path': deno_path}}
                ydl_opts['remote_components'] = ['ejs:github']

            ffmpeg_path = get_ffmpeg_path()
            if ffmpeg_path and Path(ffmpeg_path).exists():
                ydl_opts['ffmpeg_location'] = str(Path(ffmpeg_path).parent)

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                video_data = ydl.extract_info(url, download=False)

            if not video_data:
                return {"error": "Failed to fetch video info", "subtitles": [], "automatic_captions": []}

            subtitles = []
            auto_captions = []

            if "subtitles" in video_data and video_data["subtitles"]:
                for lang_code in video_data["subtitles"].keys():
                    lang_name = lang_names.get(lang_code, lang_code.upper())
                    subtitles.append({"code": lang_code, "name": lang_name})

            if "automatic_captions" in video_data and video_data["automatic_captions"]:
                for lang_code in video_data["automatic_captions"].keys():
                    lang_name = lang_names.get(lang_code, lang_code.upper())
                    auto_captions.append({"code": lang_code, "name": lang_name})

            return {
                "subtitles": subtitles,
                "automatic_captions": auto_captions,
                "error": None
            }
        except Exception as e:
            debug_log(f"yt-dlp module error: {e}")
            return {"error": str(e), "subtitles": [], "automatic_captions": []}

    @staticmethod
    def _get_subtitles_subprocess(url: str, ytdlp_path: str, cookies_path: str, lang_names: dict) -> dict:
        """Get subtitles using yt-dlp subprocess (fallback)"""
        try:
            ytdlp_cmd = [sys.executable, "-m", "yt_dlp"] if ytdlp_path == "yt_dlp_module" else [ytdlp_path]

            env = os.environ.copy()
            deno_path = get_deno_path()
            if deno_path:
                deno_dir = str(Path(deno_path).parent)
                if "PATH" in env:
                    env["PATH"] = f"{deno_dir}{os.pathsep}{env['PATH']}"
                else:
                    env["PATH"] = deno_dir

            cmd = [*ytdlp_cmd, "--dump-json", "--skip-download"]
            if cookies_path and Path(cookies_path).exists():
                cmd.extend(["--cookies", str(cookies_path)])

            cmd.append(url)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                creationflags=SUBPROCESS_FLAGS,
                env=env,
                timeout=25
            )

            if result.returncode != 0:
                error_msg = result.stderr.strip() if result.stderr else "Unknown error"
                return {"error": f"Subprocess error: {error_msg[:80]}", "subtitles": [], "automatic_captions": []}

            video_data = json.loads(result.stdout)
            subtitles = []
            auto_captions = []

            if "subtitles" in video_data and video_data["subtitles"]:
                for lang_code in video_data["subtitles"].keys():
                    lang_name = lang_names.get(lang_code, lang_code.upper())
                    subtitles.append({"code": lang_code, "name": lang_name})

            if "automatic_captions" in video_data and video_data["automatic_captions"]:
                for lang_code in video_data["automatic_captions"].keys():
                    lang_name = lang_names.get(lang_code, lang_code.upper())
                    auto_captions.append({"code": lang_code, "name": lang_name})

            return {
                "subtitles": subtitles,
                "automatic_captions": auto_captions,
                "error": None
            }
        except Exception as e:
            return {"error": str(e), "subtitles": [], "automatic_captions": []}

    @staticmethod
    def _get_subtitles_browser(url: str, ytdlp_path: str, browser: str, lang_names: dict) -> dict:
        """Get subtitles using browser cookies (Chrome/Edge)"""
        try:
            ytdlp_cmd = [sys.executable, "-m", "yt_dlp"] if ytdlp_path == "yt_dlp_module" else [ytdlp_path]
            cmd = [*ytdlp_cmd, "--dump-json", "--skip-download", "--cookies-from-browser", browser, url]
            result = subprocess.run(cmd, capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS, timeout=20)
            if result.returncode != 0:
                return {"error": "Browser cookies failed", "subtitles": [], "automatic_captions": []}
            video_data = json.loads(result.stdout)
            subtitles = []
            auto_captions = []
            if "subtitles" in video_data and video_data["subtitles"]:
                for lang_code in video_data["subtitles"].keys():
                    subtitles.append({"code": lang_code, "name": lang_names.get(lang_code, lang_code.upper())})
            if "automatic_captions" in video_data and video_data["automatic_captions"]:
                for lang_code in video_data["automatic_captions"].keys():
                    auto_captions.append({"code": lang_code, "name": lang_names.get(lang_code, lang_code.upper())})
            return {"subtitles": subtitles, "automatic_captions": auto_captions, "error": None}
        except Exception as e:
            return {"error": str(e), "subtitles": [], "automatic_captions": []}
            
            # Parse JSON output
            video_data = json.loads(result.stdout)
            
            # Extract subtitles
            subtitles = []
            auto_captions = []
            
            # Get manual subtitles
            if "subtitles" in video_data and video_data["subtitles"]:
                for lang_code in video_data["subtitles"].keys():
                    lang_name = lang_names.get(lang_code, lang_code.upper())
                    subtitles.append({"code": lang_code, "name": lang_name})
            
            # Get automatic captions
            if "automatic_captions" in video_data and video_data["automatic_captions"]:
                for lang_code in video_data["automatic_captions"].keys():
                    lang_name = lang_names.get(lang_code, lang_code.upper())
                    auto_captions.append({"code": lang_code, "name": lang_name})
            
            return {
                "subtitles": subtitles,
                "automatic_captions": auto_captions,
                "error": None
            }
            
        except subprocess.TimeoutExpired:
            return {"error": "Timeout fetching subtitles", "subtitles": [], "automatic_captions": []}
        except json.JSONDecodeError:
            return {"error": "Failed to parse video data", "subtitles": [], "automatic_captions": []}
        except Exception as e:
            return {"error": str(e), "subtitles": [], "automatic_captions": []}
    
    def parse_srt(self, srt_path: str) -> str:
        """Parse SRT to text with timestamps - keeps both start/end for duration calculation"""
        return self.parse_srt_streaming(srt_path)
    
    def parse_srt_streaming(self, srt_path: str, chunk_size: int = 8192) -> str:
        """
        Memory-efficient streaming SRT parser for very long videos (3-12+ hours).
        Reads file in chunks instead of loading entire file into memory.
        """
        lines = []
        prev_start = None
        prev_end = None
        accumulated_text = []
        
        # Buffer for incomplete blocks
        buffer = ""
        pattern = re.compile(r"(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n(.*?)(?=\n\n|\Z)", re.DOTALL)
        
        file_size = os.path.getsize(srt_path)
        processed = 0
        
        with open(srt_path, "r", encoding="utf-8") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                
                processed += len(chunk)
                buffer += chunk
                
                # Find complete subtitle blocks (ending with double newline)
                last_complete = buffer.rfind('\n\n')
                if last_complete == -1:
                    continue
                
                # Process complete portion
                complete_portion = buffer[:last_complete + 2]
                buffer = buffer[last_complete + 2:]
                
                matches = pattern.findall(complete_portion)
                
                for idx, start, end, text in matches:
                    clean_text = text.replace("\n", " ").strip()
                    start_short = start.split(',')[0]
                    end_short = end.split(',')[0]
                    
                    if prev_start is None:
                        prev_start = start_short
                        prev_end = end_short
                        accumulated_text = [clean_text]
                    elif len(' '.join(accumulated_text)) < 150:
                        accumulated_text.append(clean_text)
                        prev_end = end_short
                    else:
                        lines.append(f"[{prev_start}→{prev_end}] {' '.join(accumulated_text)}")
                        prev_start = start_short
                        prev_end = end_short
                        accumulated_text = [clean_text]
                
                # Log progress for very long files
                if file_size > 1000000 and processed % (chunk_size * 100) == 0:
                    progress = (processed / file_size) * 100
                    self.log(f"    Parsing SRT: {progress:.1f}%")
        
        # Process remaining buffer
        if buffer.strip():
            matches = pattern.findall(buffer)
            for idx, start, end, text in matches:
                clean_text = text.replace("\n", " ").strip()
                start_short = start.split(',')[0]
                end_short = end.split(',')[0]
                
                if prev_start is None:
                    prev_start = start_short
                    prev_end = end_short
                    accumulated_text = [clean_text]
                elif len(' '.join(accumulated_text)) < 150:
                    accumulated_text.append(clean_text)
                    prev_end = end_short
                else:
                    lines.append(f"[{prev_start}→{prev_end}] {' '.join(accumulated_text)}")
                    prev_start = start_short
                    prev_end = end_short
                    accumulated_text = [clean_text]
        
        # Don't forget last segment
        if accumulated_text:
            lines.append(f"[{prev_start}→{prev_end}] {' '.join(accumulated_text)}")
        
        return "\n".join(lines)
    
    def parse_srt_full(self, srt_path: str) -> str:
        """Parse SRT with full timestamps (for backward compatibility)"""
        with open(srt_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        pattern = r"(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n(.*?)(?=\n\n|\Z)"
        matches = re.findall(pattern, content, re.DOTALL)
        
        lines = []
        for idx, start, end, text in matches:
            clean_text = text.replace("\n", " ").strip()
            lines.append(f"[{start} - {end}] {clean_text}")
        
        return "\n".join(lines)
    
    def estimate_token_count(self, text: str) -> int:
        """Rough estimate of token count (1 token ≈ 4 chars for English/Indonesian)"""
        return len(text) // 4
    
    def chunk_transcript(self, transcript: str, max_tokens: int = 8000) -> list:
        """
        Split transcript into chunks that fit within token limit.
        Optimized for very long videos (3-12+ hours).
        
        Args:
            transcript: Full transcript text
            max_tokens: Maximum tokens per chunk (default 8000 for GROQ free tier safety)
        
        Returns:
            List of transcript chunks with overlap for context
        """
        lines = transcript.split('\n')
        total_lines = len(lines)
        chunks = []
        current_chunk = []
        current_tokens = 0
        
        # Track timestamps for chunk metadata
        chunk_start_time = None
        chunk_end_time = None
        
        for line in lines:
            line_tokens = self.estimate_token_count(line)
            
            # Extract timestamp from line for metadata
            time_match = re.match(r'\[(\d{2}:\d{2}:\d{2})', line)
            if time_match:
                if chunk_start_time is None:
                    chunk_start_time = time_match.group(1)
                chunk_end_time = time_match.group(1)
            
            if current_tokens + line_tokens > max_tokens and current_chunk:
                # Add chunk with timestamp metadata as header
                if chunk_start_time and chunk_end_time:
                    chunk_header = f"[CHUNK: {chunk_start_time} - {chunk_end_time}]\n"
                else:
                    chunk_header = ""
                chunks.append(chunk_header + '\n'.join(current_chunk))
                
                # Keep last 5 lines for better context overlap
                overlap = current_chunk[-5:] if len(current_chunk) >= 5 else current_chunk
                current_chunk = overlap.copy()
                current_tokens = sum(self.estimate_token_count(l) for l in current_chunk)
                
                # Reset timestamps for next chunk (but keep end time for overlap context)
                chunk_start_time = None
                
            current_chunk.append(line)
            current_tokens += line_tokens
        
        # Add remaining chunk
        if current_chunk:
            if chunk_start_time and chunk_end_time:
                chunk_header = f"[CHUNK: {chunk_start_time} - {chunk_end_time}]\n"
            else:
                chunk_header = ""
            chunks.append(chunk_header + '\n'.join(current_chunk))
        
        return chunks
    
    def chunk_transcript_streaming(self, srt_path: str, max_tokens: int = 6000):
        """
        Generator-based chunking directly from SRT file.
        Most memory-efficient for very long videos.
        Yields chunks one at a time instead of loading all into memory.
        """
        current_chunk = []
        current_tokens = 0
        chunk_start_time = None
        chunk_end_time = None
        
        # Stream parse SRT
        buffer = ""
        pattern = re.compile(r"(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n(.*?)(?=\n\n|\Z)", re.DOTALL)
        
        with open(srt_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                buffer += raw_line
                
                # Process when we have complete blocks
                if '\n\n' in buffer:
                    last_complete = buffer.rfind('\n\n')
                    complete = buffer[:last_complete + 2]
                    buffer = buffer[last_complete + 2:]
                    
                    matches = pattern.findall(complete)
                    
                    for idx, start, end, text in matches:
                        clean_text = text.replace("\n", " ").strip()
                        start_short = start.split(',')[0]
                        end_short = end.split(',')[0]
                        
                        line = f"[{start_short}→{end_short}] {clean_text}"
                        line_tokens = self.estimate_token_count(line)
                        
                        if chunk_start_time is None:
                            chunk_start_time = start_short
                        chunk_end_time = end_short
                        
                        if current_tokens + line_tokens > max_tokens and current_chunk:
                            # Yield chunk
                            header = f"[CHUNK: {chunk_start_time} - {chunk_end_time}]\n"
                            yield header + '\n'.join(current_chunk)
                            
                            # Reset with overlap
                            overlap = current_chunk[-5:] if len(current_chunk) >= 5 else current_chunk
                            current_chunk = overlap.copy()
                            current_tokens = sum(self.estimate_token_count(l) for l in current_chunk)
                            chunk_start_time = None
                        
                        current_chunk.append(line)
                        current_tokens += line_tokens
        
        # Process remaining buffer
        if buffer.strip():
            matches = pattern.findall(buffer)
            for idx, start, end, text in matches:
                clean_text = text.replace("\n", " ").strip()
                start_short = start.split(',')[0]
                end_short = end.split(',')[0]
                
                line = f"[{start_short}→{end_short}] {clean_text}"
                current_chunk.append(line)
                if chunk_start_time is None:
                    chunk_start_time = start_short
                chunk_end_time = end_short
        
        # Yield final chunk
        if current_chunk:
            header = f"[CHUNK: {chunk_start_time} - {chunk_end_time}]\n" if chunk_start_time else ""
            yield header + '\n'.join(current_chunk)
    
    def get_compact_prompt(self) -> str:
        """
        Get a compact system prompt optimized for low token usage.
        ~60% smaller than the full prompt while maintaining quality.
        """
        return """Kamu editor short-form untuk konten viral (TikTok/Reels/Shorts).

TUGAS: Dari transcript, hasilkan TEPAT {num_clips} segment viral.

FORMAT TRANSCRIPT:
[HH:MM:SS→HH:MM:SS] teks dialog
Contoh: [00:05:00→00:05:30] Halo semua...

⚡ ATURAN #1 PALING KRITIS - CONTEXT-FIRST:
Setiap clip WAJIB dimulai dari PERTANYAAN/SETUP, BUKAN langsung jawaban.

Alasan: Penonton butuh tahu konteks ("apa yang dibahas?") sebelum jawaban.
Tanpa konteks → penonton skip → video gagal.

CONTOH:
✗ SALAH: Mulai dari "Itu mitos, GERD tidak menyebabkan serangan jantung"
  → Penonton bingung, tidak ada konteks
✓ BENAR: Mulai dari "Dok, benarkah GERD bisa sebabkan serangan jantung?"
  → Penonton penasaran, tonton sampai habis

✗ SALAH: Mulai dari "Makanya gue bangkrut"
✓ BENAR: Mulai dari "Jadi waktu itu gue invest 2 miliar..."

PRINSIP: Pertanyaan/setup = HOOK TERBAIK.

STRUKTUR CLIP OPTIMAL:
1. HOOK (5-15s): Pertanyaan/statement pemicu rasa ingin tahu
2. INTI (30-60s): Jawaban/pembahasan/konflik/insight
3. PAYOFF (5-15s): Kesimpulan/punchline/plot twist

→ Jika jawaban bagus tapi tanpa pertanyaan, MUNDURKAN start_time ke pertanyaan terdekat.

⚠️ ATURAN DURASI WAJIB (KRITIS - TIDAK BOLEH DILANGGAR):
- Setiap clip HARUS berdurasi 60-120 DETIK (1-2 menit)
- HITUNG: end_time - start_time harus 60-120 detik
- Lihat timestamp di transcript untuk memilih range yang tepat
- Target ideal: 45-90 detik
- HITUNG dari timestamp, JANGAN estimasi dari teks

CONTOH PERHITUNGAN DURASI:
✓ BENAR: start="00:02:00,000" end="00:03:30,000" = 90 detik (1.5 menit)
✓ BENAR: start="00:10:00,000" end="00:11:15,000" = 75 detik
✗ SALAH: start="00:05:00,000" end="00:05:15,000" = 15 detik (TERLALU PENDEK!)
✗ SALAH: start="00:05:00,000" end="00:05:30,000" = 30 detik (TERLALU PENDEK!)

JIKA KONTEN MENARIK TAPI PENDEK:
→ GABUNGKAN dengan bagian sebelum/sesudahnya sampai 30+ detik
→ Cari timestamp mulai dari 30-60 DETIK sebelum punchline
→ Mundurkan start_time ke pertanyaan/konteks sebelumnya
→ Gabungkan Q&A berurutan yang satu topik

PRIORITAS KONTEN:
1. Pertanyaan menarik + jawaban mengejutkan (Q&A gold)
2. Konflik/kontroversi/drama
3. Pengakuan personal/curhat/confession
4. Statement tajam/kontroversial/hot take
5. Punchline/momen lucu kuat
6. Cerita lengkap (setup→konflik→payoff)
7. Fakta mengejutkan/insight baru/mitos vs fakta
8. Momen emosional kuat (haru/marah/takjub)

JENIS KONTEN: Podcast, Dokumenter, Interview, Edukasi, Vlog, Live Stream/Marathon

🎮 KHUSUS LIVE STREAM / MARATHON (12+ JAM):
Momen bernilai tinggi di live stream:
- Drama/klarifikasi/asbun member (skor 9-10)
- Momen kocak/chaos/gurauan antar member (skor 8-10)
- Bintang tamu datang + reaksi member (skor 8-10)
- Cerita sedih/emosional member (skor 8-10)
- Milestone tercapai (donasi/subscriber) (skor 7-9)
- Interaksi penonton epic (donasi+reaksi, video call) (skor 7-9)
- Games/challenge seru antar member (skor 6-8)
- Momen dermawan/sosial (haji, amal, berbagi) (skor 8-10)

DILARANG di live stream:
- Momen BENGONG/diam tanpa dialog
- Loading/technical issue/dead air
- Scroll HP tanpa interaksi
- Obrolan ultra-ringan tanpa substansi

STRATEGI LIVE STREAM:
→ SKIP dead air, FOKUS puncak emosi
→ Spread clips MERATA di seluruh durasi (jangan hanya jam pertama)
→ Pastikan setiap clip punya AKSI/DIALOG jelas

HINDARI:
- Jawaban tanpa pertanyaan (kehilangan konteks)
- Punchline tanpa setup (kehilangan daya kejut)
- Filler/basa-basi/transisi tanpa payoff
- Momen bengong/diam/loading (khusus live stream)

OUTPUT: HANYA JSON array, tanpa markdown/penjelasan.

FORMAT (6 field wajib):
- "start_time": "HH:MM:SS,000" (dengan milidetik)
- "end_time": "HH:MM:SS,000" (dengan milidetik)
- "title": max 60 karakter
- "description": max 150 karakter  
- "virality_score": integer 1-10
- "hook_text": max 15 kata, sebut NAMA pembicara, prioritas gunakan PERTANYAAN

VALIDASI SEBELUM OUTPUT:
✓ Semua clip 30-120 detik?
✓ Ada tepat {num_clips} segment?
✓ Setiap clip dimulai dari pertanyaan/konteks, bukan tengah jawaban?

{video_context}

Transcript:
{transcript}"""
    
    def _call_gemini_api(self, prompt: str) -> str:
        """Call Google Gemini API directly (not via OpenAI SDK)"""
        try:
            # Get API key from highlight_client config
            # The API key should be set in base_url as part of the request
            hf_config = self.ai_providers.get("highlight_finder", {})
            api_key = hf_config.get("api_key", "")
            
            if not api_key:
                raise Exception("No API key configured for Google Gemini")
            
            # Configure genai with API key
            _ensure_genai()
            genai.configure(api_key=api_key)
            
            # Create model and call API
            model = genai.GenerativeModel(self.model)
            response = model.generate_content(prompt)
            
            if not response.text:
                raise Exception(f"Empty response from Gemini: {response}")
            
            return response.text
        except Exception as e:
            self.log(f"  ❌ Google Gemini API Error: {e}")
            raise
    
    # ==================================================================
    # HEATMAP / MOST REPLAYED ANALYSIS
    # ==================================================================
    
    def get_heatmap_score(self, start_sec: float, end_sec: float) -> float:
        """Get average heatmap engagement score for a time range.
        
        Args:
            start_sec: Clip start time in seconds
            end_sec: Clip end time in seconds
            
        Returns:
            Average engagement value (0.0 - 1.0). Returns 0.0 if no heatmap data.
        """
        if not self.heatmap_data:
            return 0.0
        
        total_value = 0.0
        overlap_duration = 0.0
        
        for seg in self.heatmap_data:
            seg_start = seg.get("start_time", 0)
            seg_end = seg.get("end_time", 0)
            seg_value = seg.get("value", 0)
            
            # Calculate overlap between clip and heatmap segment
            overlap_start = max(start_sec, seg_start)
            overlap_end = min(end_sec, seg_end)
            
            if overlap_end > overlap_start:
                duration = overlap_end - overlap_start
                total_value += seg_value * duration
                overlap_duration += duration
        
        if overlap_duration > 0:
            return total_value / overlap_duration
        return 0.0
    
    def get_heatmap_peaks(self, min_value: float = 0.6, min_duration: float = 10) -> list:
        """Find peak engagement zones from heatmap data.
        
        Returns list of {start, end, avg_value} for high-engagement zones.
        """
        if not self.heatmap_data:
            return []
        
        peaks = []
        current_peak = None
        
        for seg in self.heatmap_data:
            val = seg.get("value", 0)
            
            if val >= min_value:
                if current_peak is None:
                    current_peak = {
                        "start": seg["start_time"],
                        "end": seg["end_time"],
                        "values": [val]
                    }
                else:
                    current_peak["end"] = seg["end_time"]
                    current_peak["values"].append(val)
            else:
                if current_peak is not None:
                    duration = current_peak["end"] - current_peak["start"]
                    if duration >= min_duration:
                        peaks.append({
                            "start": current_peak["start"],
                            "end": current_peak["end"],
                            "avg_value": sum(current_peak["values"]) / len(current_peak["values"]),
                            "peak_value": max(current_peak["values"]),
                            "duration": duration
                        })
                    current_peak = None
        
        # Don't forget last peak
        if current_peak is not None:
            duration = current_peak["end"] - current_peak["start"]
            if duration >= min_duration:
                peaks.append({
                    "start": current_peak["start"],
                    "end": current_peak["end"],
                    "avg_value": sum(current_peak["values"]) / len(current_peak["values"]),
                    "peak_value": max(current_peak["values"]),
                    "duration": duration
                })
        
        # Sort by avg_value descending
        peaks.sort(key=lambda x: -x["avg_value"])
        return peaks
    
    def format_heatmap_for_prompt(self) -> str:
        """Format heatmap peaks as context for AI prompt."""
        if not self.heatmap_data or not self.use_heatmap:
            return ""
        
        peaks = self.get_heatmap_peaks(min_value=0.5, min_duration=8)
        if not peaks:
            return ""
        
        # Format top peaks (max 15 to avoid bloating prompt)
        lines = ["HEATMAP DATA (Most Replayed by viewers - prioritize these segments!):"]
        for i, p in enumerate(peaks[:15]):
            start_fmt = f"{int(p['start']//3600):02d}:{int(p['start']%3600//60):02d}:{int(p['start']%60):02d}"
            end_fmt = f"{int(p['end']//3600):02d}:{int(p['end']%3600//60):02d}:{int(p['end']%60):02d}"
            bar = "█" * int(p['avg_value'] * 10)
            lines.append(f"  [{start_fmt} → {end_fmt}] engagement={p['avg_value']:.0%} {bar}")
        
        lines.append("")
        lines.append("INSTRUKSI HEATMAP: Segment dengan engagement TINGGI (>60%) artinya penonton sering replay bagian itu — "
                      "WAJIB prioritaskan area ini saat memilih klip. Clip yang overlap dengan zona Most Replayed "
                      "harus mendapat virality_score LEBIH TINGGI (+1 sampai +2 poin).")
        
        return "\n".join(lines)
    
    def boost_highlights_with_heatmap(self, highlights: list) -> list:
        """Post-process highlights: boost virality_score based on heatmap overlap.
        
        Scoring rules:
        - Heatmap avg >= 0.7 (very hot zone): +2 to virality_score  
        - Heatmap avg >= 0.5 (warm zone): +1 to virality_score
        - Heatmap avg < 0.3 (cold zone): -1 to virality_score
        - Cap at 10, floor at 1
        """
        if not self.heatmap_data or not self.use_heatmap:
            return highlights
        
        for h in highlights:
            try:
                start_sec = self.parse_timestamp(h.get("start_time", "00:00:00,000"))
                end_sec = self.parse_timestamp(h.get("end_time", "00:00:00,000"))
            except:
                continue
            
            avg_engagement = self.get_heatmap_score(start_sec, end_sec)
            h["heatmap_score"] = round(avg_engagement, 3)
            
            original_score = h.get("virality_score", 5)
            
            if avg_engagement >= 0.7:
                h["virality_score"] = min(10, original_score + 2)
            elif avg_engagement >= 0.5:
                h["virality_score"] = min(10, original_score + 1)
            elif avg_engagement < 0.3:
                h["virality_score"] = max(1, original_score - 1)
            
            if h["virality_score"] != original_score:
                self.log(f"  📊 Heatmap boost: {h['title'][:40]} | "
                        f"engagement={avg_engagement:.0%} | "
                        f"score {original_score}→{h['virality_score']}")
        
        # Re-sort by boosted virality score
        highlights.sort(key=lambda x: (-x.get("virality_score", 0), x.get("start_time", "")))
        return highlights
    
    def find_highlights(self, transcript: str, video_info: dict, num_clips: int,
                         min_duration: float = 58, max_duration: float = 120,
                         force_system_prompt: bool = False,
                         custom_rules: str = "") -> list:
        """Find highlights using GPT or Gemini - with automatic chunking for long transcripts.

        Args:
            force_system_prompt: If True, always use self.system_prompt instead of compact prompt.
                                 Used by ClipDubEngine to preserve context-aware prompts.
            custom_rules: Specific clipping instructions/rules (e.g. campaign brief).
        """
        self.log(f"[2/4] Finding highlights (using {self.model})...")
        if custom_rules and custom_rules.strip():
            self.log(f"  📋 Custom clipping rules active (Campaign/Brief mode)")

        # Estimate token count
        estimated_tokens = self.estimate_token_count(transcript)
        self.log(f"  📊 Estimated transcript tokens: {estimated_tokens}")

        # Check if we need chunking (GROQ free tier limit: 12000 TPM)
        # Use 8000 as threshold to leave room for prompt + response
        use_chunking = estimated_tokens > 8000
        use_compact_prompt = estimated_tokens > 5000 and not force_system_prompt

        if force_system_prompt:
            self.log(f"  🎯 Using custom system prompt (context-aware mode)")

        if use_chunking:
            self.log(f"  📦 Using chunked processing for long transcript")
            highlights = self._find_highlights_chunked(transcript, video_info, num_clips,
                                                       min_duration=min_duration, max_duration=max_duration,
                                                       force_system_prompt=force_system_prompt,
                                                       custom_rules=custom_rules)
        else:
            # For shorter transcripts, use standard processing
            highlights = self._find_highlights_single(transcript, video_info, num_clips, use_compact_prompt,
                                                      min_duration=min_duration, max_duration=max_duration,
                                                      custom_rules=custom_rules)

        # Post-process: boost virality scores based on heatmap data
        if self.heatmap_data and self.use_heatmap:
            self.log("  📊 Applying heatmap score boosting...")
            highlights = self.boost_highlights_with_heatmap(highlights)

        return highlights

    def _find_highlights_single(self, transcript: str, video_info: dict, num_clips: int, use_compact: bool = False,
                                  min_duration: float = 58, max_duration: float = 120,
                                  custom_rules: str = "") -> list:
        """Process a single transcript (not chunked)"""
        # Request more than needed — many get filtered by duration
        # When using custom system prompt (use_compact=False due to force), request less overhead
        request_clips = max(num_clips + 3, int(num_clips * 1.5)) if not use_compact else max(num_clips + 5, int(num_clips * 2))

        video_context = ""
        if video_info:
            video_context = f"""INFO VIDEO:
- Judul: {video_info.get('title', 'Unknown')}
- Channel: {video_info.get('channel', 'Unknown')}
- Deskripsi: {video_info.get('description', '')[:300]}"""

        # Add custom rules if present
        if custom_rules and custom_rules.strip():
            rules_block = f"""
==================================================
🎯 ATURAN & BRIEF WAJIB DARI USER (PRIORITAS UTAMA / TERTINGGI):
{custom_rules.strip()}
==================================================
⚠️ INSTRUKSI SANGAT PENTING:
- Utamakan & WAJIB cari momen yang secara spesifik memenuhi aturan/brief di atas!
- Filter dan abaikan momen lain yang melanggar pantangan/larangan di atas."""
            video_context = f"{rules_block}\n\n{video_context}" if video_context else rules_block

        # Add heatmap data to video context
        heatmap_context = self.format_heatmap_for_prompt()
        if heatmap_context:
            video_context += f"\n\n{heatmap_context}"
            self.log("  📊 Heatmap data injected into AI prompt")

        # Choose prompt based on token budget
        base_prompt = self.get_compact_prompt() if use_compact else self.system_prompt

        # Replace placeholders safely
        prompt = base_prompt.replace("{num_clips}", str(request_clips))
        prompt = prompt.replace("{video_context}", video_context)
        prompt = prompt.replace("{transcript}", transcript)

        result = self._call_ai_api(prompt)
        return self._parse_highlights_result(result, num_clips,
                                              min_duration=min_duration, max_duration=max_duration)

    def _find_highlights_chunked(self, transcript: str, video_info: dict, num_clips: int,
                                  min_duration: float = 58, max_duration: float = 120,
                                  force_system_prompt: bool = False,
                                  custom_rules: str = "") -> list:
        """
        Process long transcript in chunks with parallel API calls.
        Optimized for videos 3-12+ hours.
        """
        chunks = self.chunk_transcript(transcript, max_tokens=6000)
        num_chunks = len(chunks)
        self.log(f"  📦 Split into {num_chunks} chunks")

        # Smart clip distribution: more clips from beginning/end (typically more interesting)
        # For very long videos, distribute evenly but request more per chunk
        if num_chunks <= 3:
            clips_per_chunk = max(3, (num_clips + 3) // num_chunks + 1)
        elif num_chunks <= 10:
            clips_per_chunk = max(2, (num_clips + 5) // num_chunks + 1)
        else:
            # Very long video (>10 chunks): request fewer per chunk but more total
            clips_per_chunk = max(2, (num_clips * 2) // num_chunks + 1)

        self.log(f"  📊 Requesting {clips_per_chunk} clips per chunk (total: ~{clips_per_chunk * num_chunks})")

        video_context = ""
        if video_info:
            video_context = f"""INFO VIDEO:
- Judul: {video_info.get('title', 'Unknown')}
- Channel: {video_info.get('channel', 'Unknown')}"""

        # Add custom rules if present
        if custom_rules and custom_rules.strip():
            rules_block = f"""
==================================================
🎯 ATURAN & BRIEF WAJIB DARI USER (PRIORITAS UTAMA / TERTINGGI):
{custom_rules.strip()}
==================================================
⚠️ INSTRUKSI SANGAT PENTING:
- Utamakan & WAJIB cari momen yang secara spesifik memenuhi aturan/brief di atas!
- Filter dan abaikan momen lain yang melanggar pantangan/larangan di atas."""
            video_context = f"{rules_block}\n\n{video_context}" if video_context else rules_block

        # Add heatmap data to video context
        heatmap_context = self.format_heatmap_for_prompt()
        if heatmap_context:
            video_context += f"\n\n{heatmap_context}"
            self.log("  📊 Heatmap data injected into chunked AI prompts")
        
        # Use custom system prompt if forced (e.g., ClipDubEngine context-aware prompt)
        use_custom = force_system_prompt and self.system_prompt
        if use_custom:
            self.log("  🎯 Using custom system prompt for chunked processing")
        
        all_highlights = []
        failed_chunks = []
        
        # Determine max parallel workers (limit to avoid rate limiting)
        max_workers = min(3, num_chunks)  # Max 3 parallel API calls
        
        def process_chunk(chunk_data):
            """Process a single chunk"""
            i, chunk = chunk_data
            prompt = self.system_prompt if use_custom else self.get_compact_prompt()
            prompt = prompt.replace("{num_clips}", str(clips_per_chunk))
            prompt = prompt.replace("{video_context}", video_context)
            prompt = prompt.replace("{transcript}", chunk)
            
            try:
                result = self._call_ai_api(prompt)
                highlights = self._parse_highlights_result(result, clips_per_chunk, silent=True,
                                                           min_duration=min_duration, max_duration=max_duration)
                return (i, highlights, None)
            except Exception as e:
                return (i, [], str(e)[:100])
        
        # Use parallel processing for faster results
        if num_chunks > 1 and max_workers > 1:
            self.log(f"  ⚡ Using parallel processing ({max_workers} workers)...")
            
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit all chunks
                futures = {executor.submit(process_chunk, (i, chunk)): i 
                          for i, chunk in enumerate(chunks)}
                
                # Collect results as they complete
                completed = 0
                for future in as_completed(futures):
                    completed += 1
                    idx, highlights, error = future.result()
                    
                    if error:
                        failed_chunks.append(idx)
                        self.log(f"    ⚠ Chunk {idx+1} failed: {error}")
                    else:
                        all_highlights.extend(highlights)
                        self.log(f"    ✓ Chunk {idx+1}: {len(highlights)} highlights ({completed}/{num_chunks})")
        else:
            # Sequential processing for single chunk
            for i, chunk in enumerate(chunks):
                if self.is_cancelled():
                    raise Exception("Cancelled by user")
                
                self.log(f"  🔍 Processing chunk {i+1}/{num_chunks}...")
                idx, highlights, error = process_chunk((i, chunk))
                
                if error:
                    failed_chunks.append(idx)
                    self.log(f"    ⚠ Chunk {i+1} failed: {error}")
                else:
                    all_highlights.extend(highlights)
                    self.log(f"    ✓ Found {len(highlights)} highlights")
        
        if not all_highlights:
            raise Exception(f"Failed to find any highlights from all {num_chunks} chunks")
        
        self.log(f"  📊 Raw highlights: {len(all_highlights)} (from {num_chunks - len(failed_chunks)} chunks)")
        
        # Sort by virality score and timestamp
        all_highlights.sort(key=lambda x: (-x.get('virality_score', 0), x.get('start_time', '')))
        
        # Advanced deduplication: remove overlapping timestamps
        unique_highlights = self._deduplicate_highlights(all_highlights)
        
        self.log(f"  ✓ Final unique highlights: {len(unique_highlights)}")
        return unique_highlights[:num_clips]
    
    def _deduplicate_highlights(self, highlights: list, min_gap_seconds: int = 10) -> list:
        """
        Remove duplicate/overlapping highlights.
        Keeps higher virality_score when timestamps overlap.
        Only removes clips that actually OVERLAP in time range.
        min_gap_seconds: minimum gap between clip START times (default 10s).
        """
        if not highlights:
            return []
        
        unique = []
        for h in highlights:
            try:
                start = self.parse_timestamp(h.get('start_time', '00:00:00,000'))
                end = self.parse_timestamp(h.get('end_time', '00:00:00,000'))
            except:
                continue
            
            is_duplicate = False
            for existing in unique:
                try:
                    ex_start = self.parse_timestamp(existing.get('start_time', '00:00:00,000'))
                    ex_end = self.parse_timestamp(existing.get('end_time', '00:00:00,000'))
                except:
                    continue
                
                # Check for actual time overlap (not just proximity)
                overlaps = (ex_start <= start <= ex_end) or (start <= ex_start <= end)
                too_close = abs(start - ex_start) < min_gap_seconds
                
                if overlaps or too_close:
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                unique.append(h)
        
        return unique
    
    def _call_ai_api(self, prompt: str) -> str:
        """Call AI API (Gemini direct or OpenAI-compatible)"""
        # Only use native Google GenAI SDK if hitting official Google API endpoint
        base_url = str(getattr(self.highlight_client, "base_url", "")).lower()
        if "gemini" in self.model.lower() and GOOGLE_GENAI_AVAILABLE and "generativelanguage.googleapis.com" in base_url:
            return self._call_gemini_api(prompt)
        
        # Use OpenAI SDK for OpenAI, Groq, 9router, Omnirouter, etc.
        # Format prefix: 9router uses 'ag/', Omnirouter uses 'antigravity/'
        candidate_models = [self.model]
        if self.model.startswith("ag/"):
            candidate_models.append("antigravity/" + self.model[3:])
        elif self.model.startswith("antigravity/"):
            candidate_models.append("ag/" + self.model[12:])

        primary_error = None
        for cand_model in candidate_models:
            try:
                response = self.highlight_client.chat.completions.create(
                    model=cand_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.temperature,
                )

                if not response:
                    raise Exception("API returned empty response")

                if not hasattr(response, 'choices') or not response.choices:
                    self.log(f"  ⚠ Unexpected API response structure: {type(response)}")
                    raise Exception("API response missing 'choices' field.")

                if not response.choices[0].message or not response.choices[0].message.content:
                    raise Exception("API returned empty content.")

                # If successful with alternate prefix, update self.model
                if cand_model != self.model:
                    self.log(f"  ✓ Berhasil menggunakan prefix model alternatif: {cand_model}")
                    self.model = cand_model

                # Report token usage
                if hasattr(response, 'usage') and response.usage:
                    self.report_tokens(response.usage.prompt_tokens, response.usage.completion_tokens, 0, 0)

                return response.choices[0].message.content.strip()

            except Exception as e:
                primary_error = e
                err_lower = str(e).lower()
                # If router reported prefix mismatch (e.g. Omnirouter expecting 'antigravity/' instead of 'ag/'), try next candidate
                if any(x in err_lower for x in ["provider: ag", "provider: antigravity", "provider_not_configured", "no active credentials"]):
                    self.log(f"  🔄 Prefix '{cand_model}' tidak sesuai dengan router, mencoba varian prefix lain...")
                    continue
                else:
                    self.log(f"  ⚠ Primary AI client failed with model '{cand_model}': {e}")
                    break

        # Attempt automatic fallback across candidate routers & fallback chain
        try:
            from config.ai_router import get_fallback_chain, normalize_model_for_provider, sanitize_text
            from openai import OpenAI

            dummy_cfg = {"ai_providers": self.ai_providers}
            fallback_chain = get_fallback_chain(dummy_cfg, "highlight_finder", capability="chat")

            curr_url = str(getattr(self.highlight_client, "base_url", "")).rstrip("/")
            for fb in fallback_chain:
                fb_url = str(fb.get("base_url") or "").rstrip("/")
                if fb_url == curr_url and fb.get("provider") == getattr(self, "provider", ""):
                    continue  # skip the exact provider configuration that just failed
                fb_key = fb.get("api_key", "")
                if not fb_key and fb.get("provider") not in ("custom",):
                    continue
                fb_name = fb.get("name") or fb.get("provider", "Fallback")
                fb_model = fb.get("model") or self.model
                fb_model = normalize_model_for_provider(fb_model, fb.get("provider", ""))

                cand_fb_models = [fb_model]
                if fb_model.startswith("ag/"):
                    cand_fb_models.append("antigravity/" + fb_model[3:])
                elif fb_model.startswith("antigravity/"):
                    cand_fb_models.append("ag/" + fb_model[12:])

                fb_success = False
                for cur_fb_model in cand_fb_models:
                    self.log(f"  🔄 Router fallback: mencoba {fb_name} ({cur_fb_model})...")
                    try:
                        fb_client = OpenAI(
                            api_key=fb_key or "optional",
                            base_url=fb_url,
                            timeout=120,
                            max_retries=1,
                        )
                        fb_resp = fb_client.chat.completions.create(
                            model=cur_fb_model,
                            messages=[{"role": "user", "content": prompt}],
                            temperature=self.temperature,
                        )
                        if (
                            fb_resp
                            and hasattr(fb_resp, "choices")
                            and fb_resp.choices
                            and fb_resp.choices[0].message
                            and fb_resp.choices[0].message.content
                        ):
                            self.log(f"  ✓ Fallback {fb_name} ({cur_fb_model}) berhasil digunakan!")
                            if hasattr(fb_resp, "usage") and fb_resp.usage:
                                self.report_tokens(
                                    fb_resp.usage.prompt_tokens,
                                    fb_resp.usage.completion_tokens,
                                    0,
                                    0,
                                    )
                            return fb_resp.choices[0].message.content.strip()
                    except Exception as fb_err:
                        err_text = str(fb_err).lower()
                        if any(x in err_text for x in ["provider: ag", "provider: antigravity", "provider_not_configured"]):
                            continue  # try other prefix variant
                        self.log(f"  ⚠ Fallback {fb_name} gagal: {sanitize_text(str(fb_err))}")
                        break
        except Exception as chain_err:
            self.log(f"  ⚠ Error saat mengeksekusi fallback chain: {chain_err}")

        self.log(f"  ❌ API Error: {primary_error}")
        raise Exception(
            f"Failed to get highlights from AI model.\n\n"
            f"Error: {str(primary_error)}\n\n"
            f"Please check:\n"
            f"1. API key is valid: {self.highlight_client.api_key[:20]}...\n"
            f"2. Base URL is correct: {self.highlight_client.base_url}\n"
            f"3. Model exists: {self.model}\n"
            f"4. You have sufficient credits/quota"
        )
    
    def _parse_json_robust(self, text: str, silent: bool = False) -> list:
        """Parse JSON with automatic repair for common LLM mistakes.
        
        Handles:
        - Mismatched brackets: '] instead of }', '} instead of ]'
        - Trailing commas before ] or }
        - Missing closing brackets
        - Single quotes instead of double quotes
        - Unescaped newlines in strings
        """
        # Step 1: Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        
        # Step 2: Extract JSON array from surrounding text
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            text = match.group(0)
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
        
        # Step 3: Repair common LLM bracket mistakes
        repaired = text
        
        # Fix "], at end of object (should be "},)
        repaired = re.sub(r'\]\s*,\s*\n\s*\{', '},\n{', repaired)
        # Fix "] at end of array item where } expected (but NOT the final ])
        # Pattern: "value"], or "value"]  followed by newline then {
        repaired = re.sub(r'"\]\s*,', '"},', repaired)
        repaired = re.sub(r'"\]\s*\n\s*\{', '"},\n{', repaired)
        # Fix trailing comma before ]
        repaired = re.sub(r',\s*\]', ']', repaired)
        # Fix trailing comma before }
        repaired = re.sub(r',\s*\}', '}', repaired)
        
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass
        
        # Step 4: Single quotes -> double quotes
        repaired2 = repaired.replace("'", '"')
        try:
            return json.loads(repaired2)
        except json.JSONDecodeError:
            pass
        
        # Step 5: Try to fix unbalanced brackets
        open_braces = repaired.count('{')
        close_braces = repaired.count('}')
        open_brackets = repaired.count('[')
        close_brackets = repaired.count(']')
        
        if open_braces > close_braces:
            repaired += '}' * (open_braces - close_braces)
        if open_brackets > close_brackets:
            repaired += ']' * (open_brackets - close_brackets)
        
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass
        
        # Step 6: Last resort - extract individual objects and build array
        try:
            objects = []
            for m in re.finditer(r'\{[^{}]*\}', repaired):
                try:
                    obj = json.loads(m.group(0))
                    if "start_time" in obj and "end_time" in obj:
                        objects.append(obj)
                except json.JSONDecodeError:
                    continue
            
            if objects:
                if not silent:
                    self.log(f"  ⚠ JSON repaired: extracted {len(objects)} highlights from malformed response")
                return objects
        except Exception:
            pass
        
        # All attempts failed
        if not silent:
            self.log(f"\n❌ JSON Parse Error: could not repair LLM response")
            self.log(f"\n📄 Full AI Response:\n{text}")
        raise Exception(
            f"Failed to parse AI response as JSON.\n"
            f"The AI model returned malformed JSON that could not be repaired.\n"
            f"Try running again - LLM outputs can vary between attempts."
        )
    
    def _parse_highlights_result(self, result: str, num_clips: int, silent: bool = False,
                                  min_duration: float = 58, max_duration: float = 120) -> list:
        """Parse AI response into highlights list"""
        if not silent:
            self.log(f"  Raw AI response (first 500 chars):\n{result[:500]}")
        
        if result.startswith("```"):
            result = re.sub(r"```json?\n?", "", result)
            result = re.sub(r"```\n?", "", result)
        
        highlights = self._parse_json_robust(result, silent)
        
        # Filter by duration
        valid = []
        for h in highlights:
            # Fallback: convert "reason" to "description" if exists
            if "reason" in h and "description" not in h:
                h["description"] = h.pop("reason")
            
            try:
                duration = self.parse_timestamp(h["end_time"]) - self.parse_timestamp(h["start_time"])
                h["duration_seconds"] = round(duration, 1)
            except:
                continue
            
            # Ensure required fields exist
            if "virality_score" not in h:
                h["virality_score"] = 5
            if "description" not in h:
                h["description"] = h.get("title", "No description")
            
            if min_duration <= duration <= max_duration:
                valid.append(h)
                if not silent:
                    virality = h.get("virality_score", 5)
                    self.log(f"  ✓ {h['title']} ({duration:.0f}s) [🔥 {virality}/10]")
            elif not silent:
                if duration > max_duration:
                    self.log(f"  ✗ {h['title']} ({duration:.0f}s) - Too long, skipped")
                elif duration < min_duration:
                    self.log(f"  ✗ {h['title']} ({duration:.0f}s) - Too short, skipped")
        
        return valid[:num_clips]
    
    def process_clip(self, video_path: str, highlight: dict, index: int, total_clips: int = 1, add_captions: bool = True, add_hook: bool = True):
        """Process a single clip: cut, portrait, hook (optional), captions (optional)"""
        
        # Check cancel before starting
        if self.is_cancelled():
            return
        
        # Create output folder with unique timestamp per clip
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{index:02d}"
        clip_dir = self.output_dir / timestamp
        clip_dir.mkdir(parents=True, exist_ok=True)
        
        self.log(f"  Output folder: {clip_dir}")
        
        start = highlight["start_time"].replace(",", ".")
        end = highlight["end_time"].replace(",", ".")
        
        self.log(f"\n[Clip {index}] {highlight['title']}")
        
        # Calculate total steps based on options
        total_steps = 2  # Cut + Portrait (always)
        if add_hook:
            total_steps += 1
        if add_captions:
            total_steps += 1
        
        # Helper to report sub-progress with percentage
        def clip_progress(step_name: str, step_num: int, sub_progress: float = 0):
            # Calculate overall progress: base (30%) + clip progress (60%)
            clip_base = 0.3 + (0.6 * (index - 1) / total_clips)
            clip_portion = 0.6 / total_clips
            step_progress = clip_portion * ((step_num + sub_progress) / total_steps)
            overall = clip_base + step_progress
            
            # Format with percentage
            percent = int(sub_progress * 100)
            if percent > 0:
                status = f"Clip {index}/{total_clips}: {step_name} ({percent}%)"
            else:
                status = f"Clip {index}/{total_clips}: {step_name}"
            
            print(f"[DEBUG] clip_progress: {status} (overall: {overall*100:.1f}%)")
            self.set_progress(status, overall)
        
        current_step = 0
        
        # Step 1: Cut video with progress tracking
        if self.is_cancelled():
            return
        clip_progress("Cutting video...", current_step, 0)
        landscape_file = clip_dir / "temp_landscape.mp4"
        
        # Get video duration for progress calculation
        duration = self.parse_timestamp(end) - self.parse_timestamp(start)
        
        # Get encoder args (GPU or CPU)
        encoder_args = self.get_video_encoder_args()
        
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", video_path,
            "-ss", start, "-to", end,
            *encoder_args,  # Use GPU or CPU encoder
            "-c:a", "aac", "-b:a", "192k",
            "-progress", "pipe:1",  # Enable progress output
            str(landscape_file)
        ]
        
        # Log command for debugging
        self.log_ffmpeg_command(cmd, "Cut Video")
        
        self.run_ffmpeg_with_progress(cmd, duration, 
            lambda p: clip_progress("Cutting video...", current_step, p))
        
        self.log("  ✓ Cut video")
        current_step += 1
        
        # Step 2: Convert to portrait with progress
        if self.is_cancelled():
            return
        clip_progress("Converting to portrait...", current_step, 0)
        portrait_file = clip_dir / "temp_portrait.mp4"
        self.convert_to_portrait_with_progress(str(landscape_file), str(portrait_file), 
            lambda p: clip_progress("Converting to portrait...", current_step, p))
        self.log("  ✓ Portrait conversion")
        current_step += 1
        
        # Track which file is the current output
        current_output = portrait_file
        hook_duration = 0
        
        # Step 3: Add hook (optional)
        if add_hook:
            if self.is_cancelled():
                return
            clip_progress("Adding hook...", current_step, 0)
            hooked_file = clip_dir / "temp_hooked.mp4"
            hook_text = highlight.get("hook_text", highlight["title"])
            hook_duration = self.add_hook_with_progress(str(current_output), hook_text, str(hooked_file),
                lambda p: clip_progress("Adding hook...", current_step, p))
            
            # Verify hooked file was created
            if not hooked_file.exists():
                raise Exception(f"Failed to create hooked video: {hooked_file}")
            
            self.log(f"  ✓ Added hook ({hook_duration:.1f}s)")
            current_output = hooked_file
            current_step += 1
        else:
            self.log("  ⊘ Skipped hook (disabled)")
        
        # Step 4: Add captions (optional)
        final_file = clip_dir / "master.mp4"
        if add_captions:
            if self.is_cancelled():
                return
            clip_progress("Adding captions...", current_step, 0)
            
            # Use portrait_file (without hook) as audio source for transcription
            audio_source = str(portrait_file) if add_hook else None
            
            # If watermark enabled, add captions to temp file first
            if self.watermark_settings.get("enabled"):
                temp_captioned = clip_dir / "temp_captioned.mp4"
                self.add_captions_api_with_progress(str(current_output), str(temp_captioned), audio_source, hook_duration,
                    lambda p: clip_progress("Adding captions...", current_step, p))
                
                if not temp_captioned.exists():
                    raise Exception(f"Failed to create captioned video: {temp_captioned}")
                
                current_output = temp_captioned
            else:
                # No watermark, captions go directly to final
                self.add_captions_api_with_progress(str(current_output), str(final_file), audio_source, hook_duration,
                    lambda p: clip_progress("Adding captions...", current_step, p))
                
                if not final_file.exists():
                    raise Exception(f"Failed to create final video: {final_file}")
            
            self.log("  ✓ Added captions")
            current_step += 1
        else:
            self.log("  ⊘ Skipped captions (disabled)")
        
        # Step 5: Add watermark (if enabled)
        if self.watermark_settings.get("enabled"):
            if self.is_cancelled():
                return
            
            # Check if we need to add watermark step to progress
            if not add_captions:
                # Watermark is a new step
                total_steps += 1
            
            clip_progress("Adding watermark...", current_step, 0)
            
            # Apply watermark to current output
            self.add_watermark_with_progress(str(current_output), str(final_file),
                lambda p: clip_progress("Adding watermark...", current_step, p))
            
            if not final_file.exists():
                raise Exception(f"Failed to create final video with watermark: {final_file}")
            
            self.log("  ✓ Added watermark")
            current_output = final_file
            current_step += 1
            
            # Cleanup temp captioned file if exists
            if add_captions:
                try:
                    temp_captioned = clip_dir / "temp_captioned.mp4"
                    if temp_captioned.exists():
                        temp_captioned.unlink()
                except Exception as e:
                    self.log(f"  Warning: Could not delete temp_captioned.mp4: {e}")
        elif not add_captions:
            # No captions and no watermark, just copy current output to final
            import shutil
            shutil.copy(str(current_output), str(final_file))
            current_output = final_file
        
        # Step 6: Add credit watermark (if enabled)
        if self.credit_watermark_settings.get("enabled") and self.channel_name:
            if self.is_cancelled():
                return
            
            total_steps += 1
            clip_progress("Adding credit...", current_step, 0)
            
            # If current_output is already final_file, we need a temp file
            if str(current_output) == str(final_file):
                temp_credit_input = clip_dir / "temp_before_credit.mp4"
                import shutil
                shutil.copy(str(final_file), str(temp_credit_input))
                current_output = temp_credit_input
            
            self.add_credit_watermark_with_progress(str(current_output), str(final_file),
                lambda p: clip_progress("Adding credit...", current_step, p))
            
            if not final_file.exists():
                raise Exception(f"Failed to create final video with credit: {final_file}")
            
            self.log(f"  ✓ Added credit: Source: {self.channel_name}")
            current_step += 1
            
            # Cleanup temp file
            try:
                temp_credit_input = clip_dir / "temp_before_credit.mp4"
                if temp_credit_input.exists():
                    temp_credit_input.unlink()
            except Exception as e:
                self.log(f"  Warning: Could not delete temp_before_credit.mp4: {e}")
        
        # Mark complete
        clip_progress("Done", total_steps, 0)
        
        # Cleanup temp files
        try:
            if landscape_file.exists():
                landscape_file.unlink()
        except Exception as e:
            self.log(f"  Warning: Could not delete {landscape_file.name}: {e}")
        
        try:
            if portrait_file.exists():
                portrait_file.unlink()
        except Exception as e:
            self.log(f"  Warning: Could not delete {portrait_file.name}: {e}")
        
        if add_hook:
            try:
                hooked_file = clip_dir / "temp_hooked.mp4"
                if hooked_file.exists():
                    hooked_file.unlink()
            except Exception as e:
                self.log(f"  Warning: Could not delete temp_hooked.mp4: {e}")
        
        # Save metadata
        metadata = {
            "title": highlight["title"],
            "hook_text": highlight.get("hook_text", highlight["title"]),
            "start_time": highlight["start_time"],
            "end_time": highlight["end_time"],
            "duration_seconds": highlight["duration_seconds"],
            "has_hook": add_hook,
            "has_captions": add_captions,
            "has_watermark": self.watermark_settings.get("enabled", False),
            "has_credit": self.credit_watermark_settings.get("enabled", False),
            "channel_name": self.channel_name,
        }
        
        with open(clip_dir / "data.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
    
    def convert_to_portrait(self, input_path: str, output_path: str):
        """Convert landscape to 9:16 portrait with speaker tracking (router method)"""
        try:
            if self.face_tracking_mode == "mediapipe":
                self.log("  Using MediaPipe (Active Speaker Detection)")
                return self.convert_to_portrait_mediapipe(input_path, output_path)
            else:
                self.log("  Using OpenCV (Fast Mode)")
                return self.convert_to_portrait_opencv(input_path, output_path)
        except Exception as e:
            # Fallback to OpenCV if MediaPipe fails
            if self.face_tracking_mode == "mediapipe":
                self.log(f"  ⚠ MediaPipe failed: {e}")
                self.log("  Falling back to OpenCV mode...")
                return self.convert_to_portrait_opencv(input_path, output_path)
            else:
                raise
    
    def convert_to_portrait_opencv(self, input_path: str, output_path: str):
        """Convert landscape to 9:16 portrait with speaker tracking (OpenCV Haar Cascade)"""
        _ensure_cv2()
        
        cap = cv2.VideoCapture(input_path)
        orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        # Calculate crop dimensions
        target_ratio = 9 / 16
        crop_w = int(orig_h * target_ratio)
        crop_h = orig_h
        out_w, out_h = 1080, 1920
        
        # Multiple face detectors for better coverage
        face_cascade_frontal = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )
        face_cascade_profile = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_profileface.xml'
        )
        # Upper body detector as fallback
        upper_body_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_upperbody.xml'
        )
        
        # First pass: analyze frames
        crop_positions = []
        current_target = orig_w / 2
        face_not_found_count = 0
        center_weight = self.mediapipe_settings.get("center_weight", 0.5)
        
        self.log(f"  Analyzing {total_frames} frames for subject detection...")
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # Try frontal face first
            faces = face_cascade_frontal.detectMultiScale(gray, 1.1, 4, minSize=(60, 60))
            
            # If no frontal face, try profile face
            if len(faces) == 0:
                faces = face_cascade_profile.detectMultiScale(gray, 1.1, 4, minSize=(60, 60))
            
            # If still no face, try upper body detection
            if len(faces) == 0 and self.mediapipe_settings.get("upper_body_fallback", True):
                bodies = upper_body_cascade.detectMultiScale(gray, 1.1, 3, minSize=(100, 100))
                if len(bodies) > 0:
                    # Convert body detection to face-like coordinates (upper part of body)
                    faces = []
                    for (x, y, w, h) in bodies:
                        # Focus on upper 40% of body (head/face area)
                        face_h = int(h * 0.4)
                        faces.append((x, y, w, face_h))
                    faces = np.array(faces)
            
            if len(faces) > 0:
                face_not_found_count = 0
                
                # Score each face: combine size + center position
                best_score = -1
                best_target = current_target
                
                for (x, y, w, h) in faces:
                    face_center_x = x + w / 2
                    face_area = w * h
                    
                    # Normalize scores
                    size_score = face_area / (orig_w * orig_h)  # Bigger = better
                    center_score = 1.0 - abs(face_center_x - orig_w / 2) / (orig_w / 2)  # Center = better
                    
                    # Combined score with configurable center weight
                    combined_score = (size_score * (1 - center_weight)) + (center_score * center_weight)
                    
                    if combined_score > best_score:
                        best_score = combined_score
                        best_target = face_center_x
                
                current_target = best_target
            else:
                face_not_found_count += 1
                # After 30 frames without face, slowly drift to center
                if face_not_found_count > 30:
                    current_target = current_target * 0.95 + (orig_w / 2) * 0.05
            
            crop_x = int(current_target - crop_w / 2)
            crop_x = max(0, min(crop_x, orig_w - crop_w))
            crop_positions.append(crop_x)
        
        # Stabilize positions
        crop_positions = self.stabilize_positions(crop_positions)
        
        # Second pass: create video
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        temp_video = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False).name
        
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(temp_video, fourcc, fps, (out_w, out_h))
        
        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            crop_x = crop_positions[frame_idx] if frame_idx < len(crop_positions) else crop_positions[-1]
            cropped = frame[0:crop_h, crop_x:crop_x+crop_w]
            resized = cv2.resize(cropped, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)
            out.write(resized)
            frame_idx += 1
        
        cap.release()
        out.release()
        
        # Merge with audio using GPU/CPU encoder
        encoder_args = self.get_video_encoder_args()
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", temp_video,
            "-i", input_path,
            *encoder_args,
            "-c:a", "aac", "-b:a", "192k",
            "-map", "0:v:0", "-map", "1:a:0",
            "-shortest",
            output_path
        ]
        self.log_ffmpeg_command(cmd, "Portrait Merge Audio (OpenCV)")
        subprocess.run(cmd, capture_output=True, creationflags=SUBPROCESS_FLAGS)
        os.unlink(temp_video)
    
    def stabilize_positions(self, positions: list) -> list:
        """Stabilize crop positions - reduce jitter and sudden movements"""
        if not positions:
            return positions
        
        # Use longer window for smoother movement
        window_size = 60  # ~2 seconds at 30fps - longer window = smoother
        stabilized = []
        
        for i in range(len(positions)):
            # Get window around current position
            start = max(0, i - window_size // 2)
            end = min(len(positions), i + window_size // 2)
            window = positions[start:end]
            
            # Use median for stability (resistant to outliers)
            avg = int(np.median(window))
            stabilized.append(avg)
        
        # Second pass: detect shot changes and lock position per shot
        # A shot change is when position jumps significantly
        # Use very high threshold to minimize scene switches
        final = []
        shot_start = 0
        threshold = 250  # pixels - very high threshold = less scene switches
        min_shot_duration = 90  # minimum frames (~3 seconds) before allowing switch
        
        for i in range(len(stabilized)):
            frames_since_last_switch = i - shot_start
            
            # Only allow switch if enough time has passed AND position changed significantly
            if i > 0 and frames_since_last_switch >= min_shot_duration:
                if abs(stabilized[i] - stabilized[shot_start]) > threshold:
                    # Shot change detected - lock previous shot to median
                    shot_positions = stabilized[shot_start:i]
                    if shot_positions:
                        shot_median = int(np.median(shot_positions))
                        final.extend([shot_median] * len(shot_positions))
                    shot_start = i
        
        # Handle last shot
        shot_positions = stabilized[shot_start:]
        if shot_positions:
            shot_median = int(np.median(shot_positions))
            final.extend([shot_median] * len(shot_positions))
        
        return final if final else stabilized
    
    def _init_mediapipe(self):
        """Initialize MediaPipe Face Mesh (lazy loading)"""
        if self.mp_face_mesh is None:
            try:
                import mediapipe as mp
                self.mp_face_mesh = mp.solutions.face_mesh
                self.mp_drawing = mp.solutions.drawing_utils
                self.log("  MediaPipe initialized successfully")
            except ImportError:
                raise Exception("MediaPipe not installed. Run: pip install mediapipe")
    
    def convert_to_portrait_mediapipe(self, input_path: str, output_path: str):
        """Convert landscape to 9:16 portrait with active speaker detection (MediaPipe)"""
        _ensure_cv2()
        
        # Initialize MediaPipe
        self._init_mediapipe()
        
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            raise Exception(f"Failed to open video: {input_path}")
        
        orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        if total_frames == 0 or fps == 0:
            cap.release()
            raise Exception(f"Invalid video properties: {total_frames} frames, {fps} fps")
        
        # Calculate crop dimensions
        target_ratio = 9 / 16
        crop_w = int(orig_h * target_ratio)
        crop_h = orig_h
        out_w, out_h = 1080, 1920
        
        # MediaPipe Face Mesh settings
        lip_threshold = self.mediapipe_settings.get("lip_activity_threshold", 0.12)
        switch_threshold = self.mediapipe_settings.get("switch_threshold", 0.25)
        min_shot_duration = self.mediapipe_settings.get("min_shot_duration", 60)
        center_weight = self.mediapipe_settings.get("center_weight", 0.5)
        face_size_weight = self.mediapipe_settings.get("face_size_weight", 0.3)
        
        # First pass: analyze frames with MediaPipe
        self.log("  Pass 1: Analyzing faces and lip movements...")
        crop_positions = []
        face_activities = []  # Store activity scores per frame
        
        with self.mp_face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=5,  # Support up to 5 faces for group content
            refine_landmarks=True,
            min_detection_confidence=0.4,  # Lower threshold for better detection
            min_tracking_confidence=0.4
        ) as face_mesh:
            
            frame_count = 0
            prev_lip_distances = {}  # Track previous lip distances per face
            
            while True:
                if self.is_cancelled():
                    cap.release()
                    raise Exception("Cancelled by user")
                
                ret, frame = cap.read()
                if not ret:
                    break
                
                # Convert to RGB for MediaPipe
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = face_mesh.process(rgb_frame)
                
                best_face_x = orig_w / 2  # Default to center
                max_activity = 0
                
                if results.multi_face_landmarks:
                    faces_data = []
                    
                    for face_id, face_landmarks in enumerate(results.multi_face_landmarks):
                        # Calculate lip activity
                        activity = self._calculate_lip_activity(
                            face_landmarks, 
                            orig_w, 
                            orig_h,
                            prev_lip_distances.get(face_id, None)
                        )
                        
                        # Get face center position (nose tip)
                        face_x = face_landmarks.landmark[1].x * orig_w
                        
                        # Calculate face bounding box for size estimation
                        # Use landmarks: forehead (10), chin (152), left cheek (234), right cheek (454)
                        forehead = face_landmarks.landmark[10]
                        chin = face_landmarks.landmark[152]
                        left_cheek = face_landmarks.landmark[234]
                        right_cheek = face_landmarks.landmark[454]
                        
                        face_height = abs(forehead.y - chin.y) * orig_h
                        face_width = abs(left_cheek.x - right_cheek.x) * orig_w
                        face_area = face_height * face_width
                        max_possible_area = orig_w * orig_h * 0.25  # Face can't be > 25% of frame
                        
                        # Calculate scores
                        center_score = 1.0 - abs(face_x - orig_w / 2) / (orig_w / 2)
                        size_score = min(1.0, face_area / max_possible_area)  # Bigger face = better
                        
                        # Combined score: activity + center + size
                        # Activity weight = remaining after center and size
                        activity_weight = max(0.2, 1.0 - center_weight - face_size_weight)
                        combined_score = (activity * activity_weight) + (center_score * center_weight) + (size_score * face_size_weight)
                        
                        faces_data.append({
                            'x': face_x,
                            'activity': activity,
                            'size': face_area,
                            'combined_score': combined_score
                        })
                        
                        # Update previous lip distance
                        upper_lip = face_landmarks.landmark[13]  # Upper lip center
                        lower_lip = face_landmarks.landmark[14]  # Lower lip center
                        lip_distance = abs(upper_lip.y - lower_lip.y)
                        prev_lip_distances[face_id] = lip_distance
                    
                    # Select face with highest combined score
                    if faces_data:
                        best_face = max(faces_data, key=lambda f: f['combined_score'])
                        best_face_x = best_face['x']
                        max_activity = best_face['activity']
                
                # Calculate crop position
                crop_x = int(best_face_x - crop_w / 2)
                crop_x = max(0, min(crop_x, orig_w - crop_w))
                crop_positions.append(crop_x)
                face_activities.append(max_activity)
                
                frame_count += 1
                
                if frame_count % 30 == 0:
                    self.log(f"    Analyzed {frame_count}/{total_frames} frames...")
        
        self.log(f"  Analyzed {frame_count} frames with MediaPipe")
        
        # Stabilize positions with shot-based switching
        crop_positions = self._stabilize_positions_with_activity(
            crop_positions, 
            face_activities,
            min_shot_duration,
            switch_threshold
        )
        
        # Second pass: create video
        self.log("  Pass 2: Creating portrait video...")
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        temp_video = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False).name
        
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(temp_video, fourcc, fps, (out_w, out_h))
        
        if not out.isOpened():
            cap.release()
            raise Exception(f"Failed to create VideoWriter: {temp_video}")
        
        frame_idx = 0
        while True:
            if self.is_cancelled():
                cap.release()
                out.release()
                try:
                    os.unlink(temp_video)
                except:
                    pass
                raise Exception("Cancelled by user")
            
            ret, frame = cap.read()
            if not ret:
                break
            
            crop_x = crop_positions[frame_idx] if frame_idx < len(crop_positions) else crop_positions[-1]
            cropped = frame[0:crop_h, crop_x:crop_x+crop_w]
            resized = cv2.resize(cropped, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)
            out.write(resized)
            
            frame_idx += 1
            
            if frame_idx % 30 == 0:
                self.log(f"    Created {frame_idx}/{total_frames} frames...")
        
        cap.release()
        out.release()
        
        # Verify temp video was created
        if not os.path.exists(temp_video) or os.path.getsize(temp_video) < 1000:
            raise Exception(f"Failed to create temp video: {temp_video}")
        
        # Merge with audio using GPU/CPU encoder
        self.log("  Pass 3: Merging audio...")
        encoder_args = self.get_video_encoder_args()
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", temp_video,
            "-i", input_path,
            *encoder_args,
            "-c:a", "aac", "-b:a", "192k",
            "-map", "0:v:0", "-map", "1:a:0",
            "-shortest",
            output_path
        ]
        self.log_ffmpeg_command(cmd, "Portrait Merge Audio (MediaPipe)")
        subprocess.run(cmd, capture_output=True, creationflags=SUBPROCESS_FLAGS)
        
        # Cleanup
        try:
            os.unlink(temp_video)
        except:
            pass
    
    def _calculate_lip_activity(self, face_landmarks, frame_width, frame_height, prev_lip_distance=None):
        """Calculate lip movement activity score"""
        
        # Key lip landmarks (MediaPipe Face Mesh indices)
        # Upper lip: 13, Lower lip: 14
        upper_lip = face_landmarks.landmark[13]
        lower_lip = face_landmarks.landmark[14]
        
        # Mouth corners: 61 (left), 291 (right)
        mouth_left = face_landmarks.landmark[61]
        mouth_right = face_landmarks.landmark[291]
        
        # Calculate mouth openness (vertical distance)
        mouth_height = abs(upper_lip.y - lower_lip.y)
        
        # Calculate mouth width (horizontal distance)
        mouth_width = abs(mouth_left.x - mouth_right.x)
        
        # Aspect ratio (height/width) - higher when mouth is open
        if mouth_width > 0:
            aspect_ratio = mouth_height / mouth_width
        else:
            aspect_ratio = 0
        
        # Calculate movement delta (change from previous frame)
        delta = 0
        if prev_lip_distance is not None:
            delta = abs(mouth_height - prev_lip_distance)
        
        # Activity score: combination of openness and movement
        # Weight movement more heavily (0.6) than static openness (0.4)
        activity_score = (aspect_ratio * 0.4) + (delta * 0.6)
        
        return activity_score
    
    def _stabilize_positions_with_activity(self, positions, activities, min_shot_duration, switch_threshold):
        """Stabilize crop positions based on activity scores"""
        if not positions:
            return positions
        
        # First pass: smooth positions with moving median
        window_size = 30
        smoothed = []
        
        for i in range(len(positions)):
            start = max(0, i - window_size // 2)
            end = min(len(positions), i + window_size // 2)
            window = positions[start:end]
            smoothed.append(int(np.median(window)))
        
        # Second pass: lock positions per shot based on activity
        final = []
        shot_start = 0
        current_position = smoothed[0] if smoothed else 0
        
        for i in range(len(smoothed)):
            frames_since_switch = i - shot_start
            
            # Only allow switch if:
            # 1. Minimum shot duration has passed
            # 2. Position changed significantly
            # 3. Activity is high enough (speaker is talking)
            if frames_since_switch >= min_shot_duration:
                position_diff = abs(smoothed[i] - current_position)
                activity = activities[i] if i < len(activities) else 0
                
                # Switch if position changed significantly AND there's activity
                if position_diff > 200 and activity > switch_threshold:
                    # Lock previous shot
                    shot_positions = smoothed[shot_start:i]
                    if shot_positions:
                        shot_median = int(np.median(shot_positions))
                        final.extend([shot_median] * len(shot_positions))
                    
                    shot_start = i
                    current_position = smoothed[i]
        
        # Handle last shot
        shot_positions = smoothed[shot_start:]
        if shot_positions:
            shot_median = int(np.median(shot_positions))
            final.extend([shot_median] * len(shot_positions))
        
        return final if final else smoothed
    
    def _generate_tts_audio(self, hook_text: str, voice: str = "nova") -> str:
        """Generate TTS audio file with resilient fallback (Speech API -> OpenAI direct -> Edge-TTS)."""
        tts_file = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False).name

        # Ensure model is a valid speech model (tts-1 / tts-1-hd), not an LLM chat model
        tts_model = getattr(self, "tts_model", "tts-1")
        if not tts_model or any(x in str(tts_model).lower() for x in ["gemini", "claude", "llama", "deepseek", "gpt-4", "gpt-3.5"]):
            tts_model = "tts-1"

        # Strategy 1: Configured TTS client
        if hasattr(self, "tts_client") and self.tts_client:
            try:
                tts_response = self.tts_client.audio.speech.create(
                    model=tts_model,
                    voice=voice,
                    input=hook_text,
                    speed=1.0
                )
                if tts_response and hasattr(tts_response, "content") and len(tts_response.content) > 100:
                    with open(tts_file, 'wb') as f:
                        f.write(tts_response.content)
                    return tts_file
            except Exception as e:
                self.log(f"  ⚠ Primary TTS API failed ({e}), mencoba fallback...")

        # Strategy 2: Direct OpenAI TTS if key available in environment
        openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if openai_key and not openai_key.startswith("sk-xxxx"):
            try:
                from openai import OpenAI
                direct_client = OpenAI(api_key=openai_key)
                tts_response = direct_client.audio.speech.create(
                    model="tts-1",
                    voice=voice,
                    input=hook_text,
                    speed=1.0
                )
                if tts_response and hasattr(tts_response, "content") and len(tts_response.content) > 100:
                    with open(tts_file, 'wb') as f:
                        f.write(tts_response.content)
                    self.log("  ✓ TTS hook berhasil dibuat menggunakan OpenAI tts-1")
                    return tts_file
            except Exception as e:
                self.log(f"  ⚠ OpenAI TTS fallback failed: {e}")

        # Strategy 3: Edge-TTS (100% Free Indonesian Voice)
        try:
            import asyncio
            import edge_tts

            voice_id = "id-ID-ArdiNeural"
            self.log(f"  🎙 Menghasilkan audio hook dengan Edge-TTS ({voice_id})...")

            async def _run_edge_tts():
                communicate = edge_tts.Communicate(hook_text, voice_id)
                await communicate.save(tts_file)

            asyncio.run(_run_edge_tts())
            if os.path.exists(tts_file) and os.path.getsize(tts_file) > 100:
                self.log("  ✓ TTS hook berhasil dibuat menggunakan Edge-TTS!")
                return tts_file
        except Exception as e:
            self.log(f"  ⚠ Edge-TTS fallback error: {e}")

        raise Exception(
            "Gagal menghasilkan audio TTS untuk hook.\n"
            "Pastikan Hook Maker menggunakan speech model yang valid (misal: 'tts-1') atau koneksi internet aktif untuk Edge-TTS."
        )

    def add_hook(self, input_path: str, hook_text: str, output_path: str) -> float:
        """Add hook scene at the beginning with multi-line yellow text (Fajar Sadboy style)"""

        # Report TTS character usage
        self.report_tokens(0, 0, 0, len(hook_text))

        # Generate TTS audio
        tts_file = self._generate_tts_audio(hook_text, voice="nova")
        
        # Get TTS duration using ffprobe
        probe_cmd = [
            self.ffmpeg_path, "-i", tts_file,
            "-f", "null", "-"
        ]
        result = subprocess.run(probe_cmd, capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)
        duration_match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", result.stderr)
        
        if duration_match:
            h, m, s = duration_match.groups()
            hook_duration = int(h) * 3600 + int(m) * 60 + float(s) + 0.5
        else:
            hook_duration = 3.0
        
        # Format hook text: uppercase, split into lines (max 3 words per line for better visibility)
        hook_upper = hook_text.upper()
        words = hook_upper.split()
        
        # Split into lines (max 3 words per line - Fajar Sadboy style)
        lines = []
        current_line = []
        for word in words:
            current_line.append(word)
            if len(current_line) >= 3:
                lines.append(' '.join(current_line))
                current_line = []
        if current_line:
            lines.append(' '.join(current_line))
        
        # Get input video info
        probe_cmd = [self.ffmpeg_path, "-i", input_path]
        result = subprocess.run(probe_cmd, capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)
        
        # Extract fps
        fps_match = re.search(r'(\d+(?:\.\d+)?)\s*fps', result.stderr)
        fps = float(fps_match.group(1)) if fps_match else 30
        
        # Extract resolution
        res_match = re.search(r'(\d{3,4})x(\d{3,4})', result.stderr)
        if res_match:
            width, height = int(res_match.group(1)), int(res_match.group(2))
        else:
            width, height = 1080, 1920
        
        # Create hook video: freeze first frame + TTS audio + text overlay
        hook_video = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False).name
        
        # Build drawtext filter for each line
        # Style: Yellow/gold text on white background box
        drawtext_filters = []
        line_height = 85  # pixels between lines
        font_size = 58
        total_text_height = len(lines) * line_height
        start_y = (height // 3) - (total_text_height // 2)  # Position at upper third
        
        for i, line in enumerate(lines):
            # Escape special characters for FFmpeg drawtext
            escaped_line = line.replace("'", "'\\''").replace(":", "\\:").replace("\\", "\\\\")
            y_pos = start_y + (i * line_height)
            
            # Yellow/gold text with white box background
            drawtext_filters.append(
                f"drawtext=text='{escaped_line}':"
                f"fontfile='C\\:/Windows/Fonts/arialbd.ttf':"
                f"fontsize={font_size}:"
                f"fontcolor=#FFD700:"  # Golden yellow
                f"box=1:"
                f"boxcolor=white@0.95:"  # White background
                f"boxborderw=12:"  # Padding around text
                f"x=(w-text_w)/2:"
                f"y={y_pos}"
            )
        
        filter_chain = ",".join(drawtext_filters)
        
        # Get encoder args
        encoder_args = self.get_video_encoder_args()
        
        # Step 1: Create hook video with frozen frame + text + TTS audio
        # Use -t to set exact duration, freeze first frame
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", input_path,
            "-i", tts_file,
            "-filter_complex",
            f"[0:v]trim=0:0.04,loop=loop=-1:size=1:start=0,setpts=N/{fps}/TB,{filter_chain},trim=0:{hook_duration},setpts=PTS-STARTPTS[v];"
            f"[1:a]aresample=44100,apad=whole_dur={hook_duration}[a]",
            "-map", "[v]",
            "-map", "[a]",
            *encoder_args,
            "-r", str(fps),
            "-s", f"{width}x{height}",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "44100",
            "-ac", "2",
            "-t", str(hook_duration),
            hook_video
        ]
        self.log_ffmpeg_command(cmd, "Create Hook Video")
        result = subprocess.run(cmd, capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)
        
        if result.returncode != 0:
            error_lines = result.stderr.split('\n') if result.stderr else []
            actual_errors = [line for line in error_lines if 'error' in line.lower()]
            error_msg = '\n'.join(actual_errors[-3:]) if actual_errors else "Unknown error"
            raise Exception(f"Failed to create hook video: {error_msg}")
        
        # Step 2: Re-encode main video to EXACT same format (critical for concat)
        main_reencoded = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False).name
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", input_path,
            *encoder_args,
            "-r", str(fps),
            "-s", f"{width}x{height}",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "44100",
            "-ac", "2",
            main_reencoded
        ]
        self.log_ffmpeg_command(cmd, "Re-encode Main Video")
        result = subprocess.run(cmd, capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)
        
        if result.returncode != 0:
            error_lines = result.stderr.split('\n') if result.stderr else []
            actual_errors = [line for line in error_lines if 'error' in line.lower()]
            error_msg = '\n'.join(actual_errors[-3:]) if actual_errors else "Unknown error"
            raise Exception(f"Failed to re-encode main video: {error_msg}")
        
        # Step 3: Concatenate using concat demuxer (more reliable than filter_complex)
        concat_list = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False).name
        with open(concat_list, 'w') as f:
            f.write(f"file '{hook_video.replace(chr(92), '/')}'\n")
            f.write(f"file '{main_reencoded.replace(chr(92), '/')}'\n")
        
        cmd = [
            self.ffmpeg_path, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_list,
            "-c", "copy",
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)
        
        # If concat demuxer fails, try filter_complex as fallback
        if result.returncode != 0:
            # Extract actual error message (skip ffmpeg version info)
            error_lines = result.stderr.split('\n') if result.stderr else []
            actual_errors = [line for line in error_lines if 'error' in line.lower() or 'invalid' in line.lower() or 'failed' in line.lower()]
            error_summary = '\n'.join(actual_errors[-3:]) if actual_errors else "Unknown concat error"
            
            self.log(f"  Concat demuxer failed: {error_summary[:100]}")
            self.log(f"  Trying filter_complex fallback...")
            
            cmd = [
                self.ffmpeg_path, "-y",
                "-i", hook_video,
                "-i", main_reencoded,
                "-filter_complex",
                "[0:v:0][0:a:0][1:v:0][1:a:0]concat=n=2:v=1:a=1[outv][outa]",
                "-map", "[outv]",
                "-map", "[outa]",
                *encoder_args,
                "-c:a", "aac",
                "-b:a", "192k",
                output_path
            ]
            self.log_ffmpeg_command(cmd, "Concat Hook (filter_complex fallback)")
            result = subprocess.run(cmd, capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)
            
            if result.returncode != 0:
                # Extract actual error, not version info
                error_lines = result.stderr.split('\n') if result.stderr else []
                actual_errors = [line for line in error_lines if 'error' in line.lower() or 'invalid' in line.lower() or 'failed' in line.lower()]
                error_msg = '\n'.join(actual_errors[-3:]) if actual_errors else result.stderr[-200:] if result.stderr else "Unknown error"
                raise Exception(f"Failed to concatenate hook video: {error_msg}")
        
        # Cleanup
        try:
            os.unlink(tts_file)
        except Exception as e:
            pass  # Ignore cleanup errors
        
        try:
            os.unlink(hook_video)
        except Exception as e:
            pass
        
        try:
            os.unlink(main_reencoded)
        except Exception as e:
            pass
        
        try:
            os.unlink(concat_list)
        except Exception as e:
            pass
        
        # Verify output was created
        if not os.path.exists(output_path):
            raise Exception(f"Failed to create hook video at {output_path}")
        
        return hook_duration
    
    def add_captions_api(self, input_path: str, output_path: str, audio_source: str = None, time_offset: float = 0):
        """Add CapCut-style captions using OpenAI Whisper API
        
        Args:
            input_path: Video to burn captions into (with hook)
            output_path: Output video path
            audio_source: Video to extract audio from for transcription (without hook)
            time_offset: Offset to add to all timestamps (hook duration)
        """
        
        # Use audio_source if provided, otherwise use input_path
        transcribe_source = audio_source if audio_source else input_path
        
        # Extract audio from video - use WAV format for better compatibility
        audio_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False).name
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", transcribe_source,
            "-vn",
            "-acodec", "pcm_s16le",  # PCM 16-bit WAV
            "-ar", "16000",  # 16kHz sample rate
            "-ac", "1",  # Mono
            audio_file
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)
        
        if result.returncode != 0:
            self.log(f"  Warning: Audio extraction failed")
            import shutil
            shutil.copy(input_path, output_path)
            return
        
        # Check if audio file exists and has content
        if not os.path.exists(audio_file) or os.path.getsize(audio_file) < 1000:
            self.log(f"  Warning: Audio file too small or missing")
            import shutil
            shutil.copy(input_path, output_path)
            if os.path.exists(audio_file):
                os.unlink(audio_file)
            return
        
        # Get audio duration for token reporting
        probe_cmd = [self.ffmpeg_path, "-i", audio_file, "-f", "null", "-"]
        result = subprocess.run(probe_cmd, capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)
        duration_match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", result.stderr)
        audio_duration = 0
        if duration_match:
            h, m, s = duration_match.groups()
            audio_duration = int(h) * 3600 + int(m) * 60 + float(s)
            self.report_tokens(0, 0, audio_duration, 0)
        
        # Transcribe using OpenAI Whisper API with word-level timestamps
        try:
            with open(audio_file, "rb") as f:
                transcript = self.caption_client.audio.transcriptions.create(
                    model=self.whisper_model,
                    file=f,
                    language="id",
                    response_format="verbose_json",
                    timestamp_granularities=["word"]
                )
        except Exception as e:
            self.log(f"  Warning: Whisper API error: {e}")
            import shutil
            shutil.copy(input_path, output_path)
            os.unlink(audio_file)
            return
        
        os.unlink(audio_file)
        
        # Create ASS subtitle file with time offset for hook
        ass_file = tempfile.NamedTemporaryFile(mode='w', suffix='.ass', delete=False, encoding='utf-8').name
        self.create_ass_subtitle_capcut(transcript, ass_file, time_offset)
        
        # Burn subtitles into video using GPU/CPU encoder
        # Escape path for FFmpeg on Windows
        ass_path_escaped = ass_file.replace('\\', '/').replace(':', '\\:')
        
        encoder_args = self.get_video_encoder_args()
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", input_path,
            "-vf", f"ass='{ass_path_escaped}'",
            *encoder_args,
            "-c:a", "copy",
            output_path
        ]
        
        self.log_ffmpeg_command(cmd, "Burn Captions")
        result = subprocess.run(cmd, capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)
        os.unlink(ass_file)
        
        if result.returncode != 0:
            self.log(f"  Warning: Caption burn failed, copying without captions")
            import shutil
            shutil.copy(input_path, output_path)
    
    def create_ass_subtitle_capcut(self, transcript, output_path: str, time_offset: float = 0):
        """Create ASS subtitle file with CapCut-style word-by-word highlighting"""
        
        # ASS header - CapCut style: white text, yellow highlight, black outline
        ass_content = """[Script Info]
Title: Auto-generated captions
ScriptType: v4.00+
WrapStyle: 0
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,65,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,50,50,400,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        
        events = []
        
        # Check if we have word-level timestamps
        if hasattr(transcript, 'words') and transcript.words:
            words = transcript.words
            
            # Group words into chunks (3-4 words per line for readability)
            chunk_size = 4
            
            for i in range(0, len(words), chunk_size):
                chunk = words[i:i + chunk_size]
                if not chunk:
                    continue
                
                # For each word in the chunk, create a subtitle event with that word highlighted
                for j, current_word in enumerate(chunk):
                    # Add time_offset to account for hook duration
                    word_start = current_word.start + time_offset
                    word_end = current_word.end + time_offset
                    
                    # Build text with current word highlighted in yellow
                    text_parts = []
                    for k, w in enumerate(chunk):
                        word_text = w.word.strip().upper()
                        if k == j:
                            # Highlight current word (yellow: &H00FFFF in BGR)
                            text_parts.append(f"{{\\c&H00FFFF&}}{word_text}{{\\c&HFFFFFF&}}")
                        else:
                            text_parts.append(word_text)
                    
                    text = " ".join(text_parts)
                    
                    events.append({
                        'start': self.format_time(word_start),
                        'end': self.format_time(word_end),
                        'text': text
                    })
        
        # Fallback: use segment-level timestamps if no word timestamps
        elif hasattr(transcript, 'segments') and transcript.segments:
            for segment in transcript.segments:
                start = segment.get('start', 0) + time_offset
                end = segment.get('end', 0) + time_offset
                text = segment.get('text', '').strip().upper()
                
                if text:
                    events.append({
                        'start': self.format_time(start),
                        'end': self.format_time(end),
                        'text': text
                    })
        
        # Write events to ASS file
        for event in events:
            ass_content += f"Dialogue: 0,{event['start']},{event['end']},Default,,0,0,0,,{event['text']}\n"
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(ass_content)
    
    def format_time(self, seconds: float) -> str:
        """Convert seconds to ASS time format"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centisecs = int((seconds % 1) * 100)
        return f"{hours}:{minutes:02d}:{secs:02d}.{centisecs:02d}"
    
    def parse_timestamp(self, ts: str) -> float:
        """Convert timestamp to seconds"""
        ts = ts.replace(",", ".")
        parts = ts.split(":")
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    
    def cleanup(self):
        """Clean up temp files"""
        import shutil
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def run_ffmpeg_with_progress(self, cmd: list, duration: float, progress_callback):
        """Run ffmpeg command and parse progress"""
        print(f"[DEBUG] Running ffmpeg command: {' '.join(cmd[:5])}...")
        print(f"[DEBUG] Expected duration: {duration}s")
        
        # Just run ffmpeg normally without progress parsing for now
        # Progress parsing from ffmpeg is complex due to carriage returns
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            creationflags=SUBPROCESS_FLAGS
        )
        
        # Set to 100% when done
        progress_callback(1.0)
        print(f"[DEBUG] FFmpeg completed with return code: {result.returncode}")
        
        if result.returncode != 0:
            error_msg = result.stderr if result.stderr else "Unknown FFmpeg error"
            
            # Extract the actual error (usually at the end)
            error_lines = error_msg.split('\n')
            relevant_errors = [line for line in error_lines if any(keyword in line.lower() for keyword in 
                ['error', 'invalid', 'failed', 'cannot', 'unable', 'not found', 'does not exist'])]
            
            # Get last 10 lines which usually contain the actual error
            last_lines = '\n'.join(error_lines[-10:])
            
            print(f"[FFMPEG ERROR] Full stderr:\n{error_msg}")
            self.log(f"FFmpeg command failed: {' '.join(cmd)}")
            self.log(f"FFmpeg full error output:\n{error_msg}")
            
            # Show relevant error or last lines
            if relevant_errors:
                error_summary = '\n'.join(relevant_errors[-5:])
            else:
                error_summary = last_lines
            
            raise Exception(f"FFmpeg process failed:\n{error_summary}")
    
    def convert_to_portrait_with_progress(self, input_path: str, output_path: str, progress_callback):
        """Convert landscape to 9:16 portrait with speaker tracking and progress (router method)"""
        try:
            if self.face_tracking_mode == "mediapipe":
                self.log("  Using MediaPipe (Active Speaker Detection)")
                return self.convert_to_portrait_mediapipe_with_progress(input_path, output_path, progress_callback)
            else:
                self.log("  Using OpenCV (Fast Mode)")
                return self.convert_to_portrait_opencv_with_progress(input_path, output_path, progress_callback)
        except Exception as e:
            # Fallback to OpenCV if MediaPipe fails
            if self.face_tracking_mode == "mediapipe":
                self.log(f"  ⚠ MediaPipe failed: {e}")
                self.log("  Falling back to OpenCV mode...")
                return self.convert_to_portrait_opencv_with_progress(input_path, output_path, progress_callback)
            else:
                raise
    
    def convert_to_portrait_opencv_with_progress(self, input_path: str, output_path: str, progress_callback):
        """Convert landscape to 9:16 portrait with speaker tracking and progress (OpenCV)"""
        _ensure_cv2()
        
        self.log("[DEBUG] Starting portrait conversion...")
        print("[DEBUG] Starting portrait conversion...")
        print(f"[DEBUG] Input: {input_path}")
        print(f"[DEBUG] Output: {output_path}")
        sys.stdout.flush()
        
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            raise Exception(f"Failed to open video: {input_path}")
        
        orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        self.log(f"[DEBUG] Video: {orig_w}x{orig_h}, {fps}fps, {total_frames} frames")
        print(f"[DEBUG] Video: {orig_w}x{orig_h}, {fps}fps, {total_frames} frames")
        sys.stdout.flush()
        
        if total_frames == 0 or fps == 0:
            cap.release()
            raise Exception(f"Invalid video properties: {total_frames} frames, {fps} fps")
        
        # Calculate crop dimensions
        target_ratio = 9 / 16
        crop_w = int(orig_h * target_ratio)
        crop_h = orig_h
        out_w, out_h = 1080, 1920
        
        # Face detector
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )
        
        # First pass: analyze frames (0-40%)
        print("[DEBUG] Pass 1: Analyzing frames...")
        sys.stdout.flush()
        
        crop_positions = []
        current_target = orig_w / 2
        frame_count = 0
        last_log_time = 0
        import time
        
        while True:
            # Check for cancellation
            if self.is_cancelled():
                cap.release()
                raise Exception("Cancelled by user")
            
            ret, frame = cap.read()
            if not ret:
                break
            
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.1, 5, minSize=(50, 50))
            
            if len(faces) > 0:
                # Find largest face
                largest = max(faces, key=lambda f: f[2] * f[3])
                current_target = largest[0] + largest[2] / 2
            
            crop_x = int(current_target - crop_w / 2)
            crop_x = max(0, min(crop_x, orig_w - crop_w))
            crop_positions.append(crop_x)
            
            frame_count += 1
            
            # Update progress more frequently with time-based logging
            current_time = time.time()
            if frame_count % 30 == 0 or (current_time - last_log_time) > 2:  # Every 30 frames or 2 seconds
                progress = (frame_count / total_frames) * 0.4  # 0-40%
                print(f"[DEBUG] Pass 1 progress: {progress*100:.1f}% ({frame_count}/{total_frames} frames)")
                sys.stdout.flush()
                progress_callback(progress)
                last_log_time = current_time
        
        print(f"[DEBUG] Analyzed {frame_count} frames")
        
        # Stabilize positions
        crop_positions = self.stabilize_positions(crop_positions)
        progress_callback(0.45)
        
        # Second pass: create video (45-85%)
        print("[DEBUG] Pass 2: Creating portrait video...")
        sys.stdout.flush()  # Force output
        
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        temp_video = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False).name
        
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(temp_video, fourcc, fps, (out_w, out_h))
        
        if not out.isOpened():
            cap.release()
            raise Exception(f"Failed to create VideoWriter: {temp_video}")
        
        frame_idx = 0
        last_log_time = 0
        last_frame_time = time.time()
        import time
        
        while True:
            # Check for cancellation
            if self.is_cancelled():
                cap.release()
                out.release()
                try:
                    os.unlink(temp_video)
                except:
                    pass
                raise Exception("Cancelled by user")
            
            # Watchdog: check if we're stuck (no frame processed in 30 seconds)
            current_time = time.time()
            if current_time - last_frame_time > 30:
                cap.release()
                out.release()
                raise Exception(f"Portrait conversion timeout: stuck at frame {frame_idx}/{total_frames}")
            
            ret, frame = cap.read()
            if not ret:
                break
            
            last_frame_time = current_time  # Update watchdog timer
            
            crop_x = crop_positions[frame_idx] if frame_idx < len(crop_positions) else crop_positions[-1]
            cropped = frame[0:crop_h, crop_x:crop_x+crop_w]
            resized = cv2.resize(cropped, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)
            
            # Write frame with error checking
            success = out.write(resized)
            if not success:
                print(f"[WARNING] Failed to write frame {frame_idx}")
                sys.stdout.flush()
            
            frame_idx += 1
            
            # Update progress more frequently and with time-based logging
            if frame_idx % 30 == 0 or (current_time - last_log_time) > 2:  # Every 30 frames or 2 seconds
                progress = 0.45 + (frame_idx / total_frames) * 0.4  # 45-85%
                print(f"[DEBUG] Pass 2 progress: {progress*100:.1f}% ({frame_idx}/{total_frames} frames)")
                sys.stdout.flush()
                progress_callback(progress)
                last_log_time = current_time
        
        print(f"[DEBUG] Created {frame_idx} frames")
        sys.stdout.flush()
        
        cap.release()
        print("[DEBUG] Released VideoCapture")
        sys.stdout.flush()
        
        out.release()
        print("[DEBUG] Released VideoWriter")
        sys.stdout.flush()
        
        # Verify temp video was created
        if not os.path.exists(temp_video) or os.path.getsize(temp_video) < 1000:
            raise Exception(f"Failed to create temp video: {temp_video}")
        
        print(f"[DEBUG] Temp video size: {os.path.getsize(temp_video)} bytes")
        sys.stdout.flush()
        
        progress_callback(0.85)
        
        # Merge with audio (85-100%) using GPU/CPU encoder
        print("[DEBUG] Pass 3: Merging audio...")
        sys.stdout.flush()
        
        duration = total_frames / fps if fps > 0 else 60
        encoder_args = self.get_video_encoder_args()
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", temp_video,
            "-i", input_path,
            *encoder_args,
            "-c:a", "aac", "-b:a", "192k",
            "-map", "0:v:0", "-map", "1:a:0",
            "-shortest",
            output_path
        ]
        
        # Run without progress parsing for audio merge (quick operation)
        print(f"[DEBUG] Running audio merge command...")
        sys.stdout.flush()
        
        self.log_ffmpeg_command(cmd, "Portrait Merge Audio (with progress)")
        result = subprocess.run(cmd, capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)
        
        if result.returncode != 0:
            print(f"[FFMPEG ERROR] {result.stderr}")
            sys.stdout.flush()
            raise Exception("Audio merge failed")
        
        print("[DEBUG] Audio merge complete")
        sys.stdout.flush()
        
        progress_callback(1.0)
        print("[DEBUG] Portrait conversion complete")
        sys.stdout.flush()
        
        # Cleanup temp video
        try:
            os.unlink(temp_video)
            print("[DEBUG] Cleaned up temp video")
            sys.stdout.flush()
        except Exception as e:
            print(f"[WARNING] Failed to cleanup temp video: {e}")
            sys.stdout.flush()
    
    def convert_to_portrait_mediapipe_with_progress(self, input_path: str, output_path: str, progress_callback):
        """Convert landscape to 9:16 portrait with active speaker detection and progress (MediaPipe)"""
        _ensure_cv2()
        
        # Initialize MediaPipe
        self._init_mediapipe()
        
        self.log("[DEBUG] Starting MediaPipe portrait conversion...")
        print("[DEBUG] Starting MediaPipe portrait conversion...")
        sys.stdout.flush()
        
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            raise Exception(f"Failed to open video: {input_path}")
        
        orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        self.log(f"[DEBUG] Video: {orig_w}x{orig_h}, {fps}fps, {total_frames} frames")
        print(f"[DEBUG] Video: {orig_w}x{orig_h}, {fps}fps, {total_frames} frames")
        sys.stdout.flush()
        
        if total_frames == 0 or fps == 0:
            cap.release()
            raise Exception(f"Invalid video properties: {total_frames} frames, {fps} fps")
        
        # Calculate crop dimensions
        target_ratio = 9 / 16
        crop_w = int(orig_h * target_ratio)
        crop_h = orig_h
        out_w, out_h = 1080, 1920
        
        # MediaPipe settings
        lip_threshold = self.mediapipe_settings.get("lip_activity_threshold", 0.15)
        switch_threshold = self.mediapipe_settings.get("switch_threshold", 0.3)
        min_shot_duration = self.mediapipe_settings.get("min_shot_duration", 90)
        center_weight = self.mediapipe_settings.get("center_weight", 0.3)
        
        # First pass: analyze frames with MediaPipe (0-40%)
        print("[DEBUG] Pass 1: Analyzing lip movements with MediaPipe...")
        sys.stdout.flush()
        
        crop_positions = []
        face_activities = []
        frame_count = 0
        last_log_time = 0
        import time
        
        with self.mp_face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=3,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        ) as face_mesh:
            
            prev_lip_distances = {}
            
            while True:
                if self.is_cancelled():
                    cap.release()
                    raise Exception("Cancelled by user")
                
                ret, frame = cap.read()
                if not ret:
                    break
                
                # Convert to RGB for MediaPipe
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = face_mesh.process(rgb_frame)
                
                best_face_x = orig_w / 2
                max_activity = 0
                
                if results.multi_face_landmarks:
                    faces_data = []
                    
                    for face_id, face_landmarks in enumerate(results.multi_face_landmarks):
                        # Calculate lip activity
                        activity = self._calculate_lip_activity(
                            face_landmarks,
                            orig_w,
                            orig_h,
                            prev_lip_distances.get(face_id, None)
                        )
                        
                        # Get face center position
                        face_x = face_landmarks.landmark[1].x * orig_w
                        
                        # Combined score
                        center_score = 1.0 - abs(face_x - orig_w / 2) / (orig_w / 2)
                        combined_score = (activity * (1 - center_weight)) + (center_score * center_weight)
                        
                        faces_data.append({
                            'x': face_x,
                            'activity': activity,
                            'combined_score': combined_score
                        })
                        
                        # Update previous lip distance
                        upper_lip = face_landmarks.landmark[13]
                        lower_lip = face_landmarks.landmark[14]
                        lip_distance = abs(upper_lip.y - lower_lip.y)
                        prev_lip_distances[face_id] = lip_distance
                    
                    if faces_data:
                        best_face = max(faces_data, key=lambda f: f['combined_score'])
                        best_face_x = best_face['x']
                        max_activity = best_face['activity']
                
                crop_x = int(best_face_x - crop_w / 2)
                crop_x = max(0, min(crop_x, orig_w - crop_w))
                crop_positions.append(crop_x)
                face_activities.append(max_activity)
                
                frame_count += 1
                
                current_time = time.time()
                if frame_count % 30 == 0 or (current_time - last_log_time) > 2:
                    progress = (frame_count / total_frames) * 0.4
                    print(f"[DEBUG] Pass 1 progress: {progress*100:.1f}% ({frame_count}/{total_frames} frames)")
                    sys.stdout.flush()
                    progress_callback(progress)
                    last_log_time = current_time
        
        print(f"[DEBUG] Analyzed {frame_count} frames with MediaPipe")
        sys.stdout.flush()
        
        # Stabilize positions (40-45%)
        progress_callback(0.4)
        crop_positions = self._stabilize_positions_with_activity(
            crop_positions,
            face_activities,
            min_shot_duration,
            switch_threshold
        )
        progress_callback(0.45)
        
        # Second pass: create video (45-85%)
        print("[DEBUG] Pass 2: Creating portrait video...")
        sys.stdout.flush()
        
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        temp_video = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False).name
        
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(temp_video, fourcc, fps, (out_w, out_h))
        
        if not out.isOpened():
            cap.release()
            raise Exception(f"Failed to create VideoWriter: {temp_video}")
        
        frame_idx = 0
        last_log_time = 0
        last_frame_time = time.time()
        
        while True:
            if self.is_cancelled():
                cap.release()
                out.release()
                try:
                    os.unlink(temp_video)
                except:
                    pass
                raise Exception("Cancelled by user")
            
            current_time = time.time()
            if current_time - last_frame_time > 30:
                cap.release()
                out.release()
                raise Exception(f"Portrait conversion timeout: stuck at frame {frame_idx}/{total_frames}")
            
            ret, frame = cap.read()
            if not ret:
                break
            
            last_frame_time = current_time
            
            crop_x = crop_positions[frame_idx] if frame_idx < len(crop_positions) else crop_positions[-1]
            cropped = frame[0:crop_h, crop_x:crop_x+crop_w]
            resized = cv2.resize(cropped, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)
            
            success = out.write(resized)
            if not success:
                print(f"[WARNING] Failed to write frame {frame_idx}")
                sys.stdout.flush()
            
            frame_idx += 1
            
            if frame_idx % 30 == 0 or (current_time - last_log_time) > 2:
                progress = 0.45 + (frame_idx / total_frames) * 0.4
                print(f"[DEBUG] Pass 2 progress: {progress*100:.1f}% ({frame_idx}/{total_frames} frames)")
                sys.stdout.flush()
                progress_callback(progress)
                last_log_time = current_time
        
        print(f"[DEBUG] Created {frame_idx} frames")
        sys.stdout.flush()
        
        cap.release()
        out.release()
        
        if not os.path.exists(temp_video) or os.path.getsize(temp_video) < 1000:
            raise Exception(f"Failed to create temp video: {temp_video}")
        
        print(f"[DEBUG] Temp video size: {os.path.getsize(temp_video)} bytes")
        sys.stdout.flush()
        
        progress_callback(0.85)
        
        # Merge with audio (85-100%) using GPU/CPU encoder
        print("[DEBUG] Pass 3: Merging audio...")
        sys.stdout.flush()
        
        encoder_args = self.get_video_encoder_args()
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", temp_video,
            "-i", input_path,
            *encoder_args,
            "-c:a", "aac", "-b:a", "192k",
            "-map", "0:v:0", "-map", "1:a:0",
            "-shortest",
            output_path
        ]
        
        self.log_ffmpeg_command(cmd, "MediaPipe Portrait Merge Audio")
        result = subprocess.run(cmd, capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)
        
        if result.returncode != 0:
            print(f"[FFMPEG ERROR] {result.stderr}")
            sys.stdout.flush()
            raise Exception("Audio merge failed")
        
        print("[DEBUG] Audio merge complete")
        sys.stdout.flush()
        
        progress_callback(1.0)
        print("[DEBUG] MediaPipe portrait conversion complete")
        sys.stdout.flush()
        
        # Cleanup
        try:
            os.unlink(temp_video)
            print("[DEBUG] Cleaned up temp video")
            sys.stdout.flush()
        except Exception as e:
            print(f"[WARNING] Failed to cleanup temp video: {e}")
            sys.stdout.flush()
    
    def add_hook_with_progress(self, input_path: str, hook_text: str, output_path: str, progress_callback) -> float:
        """Add hook scene at the beginning with progress tracking"""
        
        # Report TTS character usage
        self.report_tokens(0, 0, 0, len(hook_text))
        
        # Generate TTS audio (10% progress)
        progress_callback(0.1)
        tts_file = self._generate_tts_audio(hook_text, voice="nova")
        
        progress_callback(0.2)
        
        # Get TTS duration using ffprobe
        probe_cmd = [
            self.ffmpeg_path, "-i", tts_file,
            "-f", "null", "-"
        ]
        result = subprocess.run(probe_cmd, capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)
        duration_match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", result.stderr)
        
        if duration_match:
            h, m, s = duration_match.groups()
            hook_duration = int(h) * 3600 + int(m) * 60 + float(s) + 0.5
        else:
            hook_duration = 3.0
        
        # Format hook text
        hook_upper = hook_text.upper()
        words = hook_upper.split()
        
        lines = []
        current_line = []
        for word in words:
            current_line.append(word)
            if len(current_line) >= 3:
                lines.append(' '.join(current_line))
                current_line = []
        if current_line:
            lines.append(' '.join(current_line))
        
        # Get input video info
        probe_cmd = [self.ffmpeg_path, "-i", input_path]
        result = subprocess.run(probe_cmd, capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)
        
        fps_match = re.search(r'(\d+(?:\.\d+)?)\s*fps', result.stderr)
        fps = float(fps_match.group(1)) if fps_match else 30
        
        res_match = re.search(r'(\d{3,4})x(\d{3,4})', result.stderr)
        if res_match:
            width, height = int(res_match.group(1)), int(res_match.group(2))
        else:
            width, height = 1080, 1920
        
        progress_callback(0.3)
        
        # Create hook video in our temp directory
        hook_video = str(self.temp_dir / f"hook_{int(time.time() * 1000)}.mp4")
        
        # Create text file for drawtext filter (avoid escaping issues)
        text_file = str(self.temp_dir / f"hook_text_{int(time.time() * 1000)}.txt")
        
        # Write text lines to file
        text_content = '\n'.join(lines)
        with open(text_file, 'w', encoding='utf-8') as f:
            f.write(text_content)
        
        # Use a simpler approach: create static image with text, then combine with audio
        # This avoids complex FFmpeg filter escaping issues
        
        # First, create a simple background video from first frame using GPU/CPU encoder
        bg_video = str(self.temp_dir / f"hook_bg_{int(time.time() * 1000)}.mp4")
        
        encoder_args = self.get_video_encoder_args()
        bg_cmd = [
            self.ffmpeg_path, "-y",
            "-i", input_path,
            "-vf", f"trim=0:0.04,loop=loop=-1:size=1:start=0,setpts=N/{fps}/TB",
            "-t", str(hook_duration),
            *encoder_args,
            "-r", str(fps),
            "-s", f"{width}x{height}",
            "-pix_fmt", "yuv420p",
            "-an",
            bg_video
        ]
        
        self.log_ffmpeg_command(bg_cmd, "Create Hook Background")
        result = subprocess.run(bg_cmd, capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)
        if result.returncode != 0:
            self.log(f"Failed to create background video: {result.stderr}")
            raise Exception("Failed to create background video")
        
        # Verify background video was created successfully
        if not os.path.exists(bg_video) or os.path.getsize(bg_video) < 1000:
            raise Exception("Background video was not created properly")
        
        # Copy font to temp dir to avoid Windows path colon issues in FFmpeg filter
        import shutil
        temp_font = str(self.temp_dir / "arial_bold.ttf")
        if not os.path.exists(temp_font):
            shutil.copy2("C:/Windows/Fonts/arialbd.ttf", temp_font)
        
        # Now add text overlays one by one
        current_video = bg_video
        line_height = 85
        font_size = 58
        total_text_height = len(lines) * line_height
        start_y = (height // 3) - (total_text_height // 2)
        
        for i, line in enumerate(lines):
            # Normalize unicode characters
            normalized_line = line.encode('ascii', 'ignore').decode('ascii')
            if not normalized_line.strip():
                normalized_line = line.replace('\u2026', '...').replace('\u2013', '-').replace('\u2018', "'").replace('\u2019', "'").replace('\u201c', '"').replace('\u201d', '"')
            
            y_pos = start_y + (i * line_height)
            
            next_video = str(self.temp_dir / f"hook_text_{int(time.time() * 1000)}_{i}.mp4")
            
            # Use OpenCV to add text overlay instead of FFmpeg drawtext
            # This avoids all Windows path escaping issues
            self.log(f"Adding text overlay with OpenCV: {normalized_line}")
            
            # Read input video
            cap = cv2.VideoCapture(current_video)
            fps = int(cap.get(cv2.CAP_PROP_FPS))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            
            # Setup video writer
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(next_video, fourcc, fps, (width, height))
            
            # Process each frame
            frame_count = 0
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                # Add text overlay using cv2.putText
                # Calculate text size for centering
                font = cv2.FONT_HERSHEY_SIMPLEX  # Fixed: use SIMPLEX instead of BOLD
                font_scale = 2.0
                thickness = 4
                
                # Get text size
                (text_width, text_height), baseline = cv2.getTextSize(
                    normalized_line, font, font_scale, thickness
                )
                
                # Calculate position (centered horizontally, at y_pos vertically)
                text_x = (width - text_width) // 2
                text_y = y_pos + text_height
                
                # Draw white background box
                box_padding = 12
                box_x1 = text_x - box_padding
                box_y1 = text_y - text_height - box_padding
                box_x2 = text_x + text_width + box_padding
                box_y2 = text_y + baseline + box_padding
                
                # Draw semi-transparent white box
                overlay = frame.copy()
                cv2.rectangle(overlay, (box_x1, box_y1), (box_x2, box_y2), (255, 255, 255), -1)
                cv2.addWeighted(overlay, 0.95, frame, 0.05, 0, frame)
                
                # Draw yellow/gold text (#FFD700 = RGB(255, 215, 0))
                cv2.putText(frame, normalized_line, (text_x, text_y),
                           font, font_scale, (0, 215, 255), thickness, cv2.LINE_AA)
                
                out.write(frame)
                frame_count += 1
            
            cap.release()
            out.release()
            
            self.log(f"Processed {frame_count} frames with text overlay")
            
            # Verify output was created
            if not os.path.exists(next_video) or os.path.getsize(next_video) < 1000:
                raise Exception(f"Text overlay video {i} was not created properly")
            
            # Clean up previous temp file
            if current_video != bg_video:
                try:
                    os.unlink(current_video)
                except:
                    pass
            
            current_video = next_video
        
        # Re-encode OpenCV output to proper H.264 before adding audio using GPU/CPU encoder
        # OpenCV mp4v codec is not compatible with copy codec
        reencoded_video = str(self.temp_dir / f"hook_reenc_{int(time.time() * 1000)}.mp4")
        encoder_args = self.get_video_encoder_args()
        reencode_cmd = [
            self.ffmpeg_path, "-y",
            "-i", current_video,
            *encoder_args,
            "-pix_fmt", "yuv420p",
            "-an",  # No audio yet
            reencoded_video
        ]
        self.log_ffmpeg_command(reencode_cmd, "Re-encode Hook Text Overlay")
        result = subprocess.run(reencode_cmd, capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)
        if result.returncode != 0:
            self.log(f"Failed to re-encode OpenCV output: {result.stderr}")
            raise Exception("Failed to re-encode text overlay video")
        
        # Finally, add audio to re-encoded video
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", reencoded_video,
            "-i", tts_file,
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "44100",
            "-ac", "2",
            "-shortest",
            hook_video
        ]
        
        # Hook creation is 30-60%
        self.run_ffmpeg_with_progress(cmd, hook_duration, 
            lambda p: progress_callback(0.3 + p * 0.3))
        
        # Re-encode main video (60-80%) using GPU/CPU encoder
        progress_callback(0.6)
        main_reencoded = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False).name
        
        # Get main video duration
        probe_cmd = [self.ffmpeg_path, "-i", input_path, "-f", "null", "-"]
        result = subprocess.run(probe_cmd, capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)
        duration_match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", result.stderr)
        main_duration = 60
        if duration_match:
            h, m, s = duration_match.groups()
            main_duration = int(h) * 3600 + int(m) * 60 + float(s)
        
        encoder_args = self.get_video_encoder_args()
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", input_path,
            *encoder_args,
            "-r", str(fps),
            "-s", f"{width}x{height}",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "44100",
            "-ac", "2",
            "-progress", "pipe:1",
            main_reencoded
        ]
        
        self.log_ffmpeg_command(cmd, "Re-encode Main Video for Hook Concat")
        self.run_ffmpeg_with_progress(cmd, main_duration,
            lambda p: progress_callback(0.6 + p * 0.2))
        
        # Concatenate (80-100%)
        progress_callback(0.8)
        concat_list = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False).name
        with open(concat_list, 'w') as f:
            f.write(f"file '{hook_video.replace(chr(92), '/')}'\n")
            f.write(f"file '{main_reencoded.replace(chr(92), '/')}'\n")
        
        cmd = [
            self.ffmpeg_path, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_list,
            "-c", "copy",
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)
        
        if result.returncode != 0:
            # Fallback to filter_complex using GPU/CPU encoder
            encoder_args = self.get_video_encoder_args()
            cmd = [
                self.ffmpeg_path, "-y",
                "-i", hook_video,
                "-i", main_reencoded,
                "-filter_complex",
                "[0:v:0][0:a:0][1:v:0][1:a:0]concat=n=2:v=1:a=1[outv][outa]",
                "-map", "[outv]",
                "-map", "[outa]",
                *encoder_args,
                "-c:a", "aac",
                "-b:a", "192k",
                "-progress", "pipe:1",
                output_path
            ]
            self.log_ffmpeg_command(cmd, "Concat Hook (filter_complex fallback - old)")
            total_duration = hook_duration + main_duration
            self.run_ffmpeg_with_progress(cmd, total_duration,
                lambda p: progress_callback(0.8 + p * 0.2))
        else:
            progress_callback(1.0)
        
        # Cleanup
        try:
            os.unlink(tts_file)
            os.unlink(hook_video)
            os.unlink(main_reencoded)
            os.unlink(concat_list)
            os.unlink(text_file)
            os.unlink(bg_video)
            os.unlink(current_video)
        except:
            pass
        
        return hook_duration
    
    def add_captions_api_with_progress(self, input_path: str, output_path: str, audio_source: str = None, time_offset: float = 0, progress_callback=None):
        """Add CapCut-style captions using OpenAI Whisper API with progress"""
        
        if progress_callback:
            progress_callback(0.1)
        
        # Use audio_source if provided, otherwise use input_path
        transcribe_source = audio_source if audio_source else input_path
        
        # Extract audio from video
        audio_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False).name
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", transcribe_source,
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            audio_file
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)
        
        if result.returncode != 0:
            self.log(f"  Warning: Audio extraction failed")
            import shutil
            shutil.copy(input_path, output_path)
            return
        
        if progress_callback:
            progress_callback(0.2)
        
        # Check if audio file exists
        if not os.path.exists(audio_file) or os.path.getsize(audio_file) < 1000:
            self.log(f"  Warning: Audio file too small or missing")
            import shutil
            shutil.copy(input_path, output_path)
            if os.path.exists(audio_file):
                os.unlink(audio_file)
            return
        
        # Get audio duration for token reporting
        probe_cmd = [self.ffmpeg_path, "-i", audio_file, "-f", "null", "-"]
        result = subprocess.run(probe_cmd, capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)
        duration_match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", result.stderr)
        audio_duration = 0
        if duration_match:
            h, m, s = duration_match.groups()
            audio_duration = int(h) * 3600 + int(m) * 60 + float(s)
            self.report_tokens(0, 0, audio_duration, 0)
        
        if progress_callback:
            progress_callback(0.3)
        
        # Transcribe using OpenAI Whisper API
        try:
            with open(audio_file, "rb") as f:
                transcript = self.caption_client.audio.transcriptions.create(
                    model=self.whisper_model,
                    file=f,
                    language="id",
                    response_format="verbose_json",
                    timestamp_granularities=["word"]
                )
        except Exception as e:
            self.log(f"  Warning: Whisper API error: {e}")
            import shutil
            shutil.copy(input_path, output_path)
            os.unlink(audio_file)
            return
        
        os.unlink(audio_file)
        
        if progress_callback:
            progress_callback(0.5)
        
        # Create ASS subtitle file
        ass_file = tempfile.NamedTemporaryFile(mode='w', suffix='.ass', delete=False, encoding='utf-8').name
        self.create_ass_subtitle_capcut(transcript, ass_file, time_offset)
        
        if progress_callback:
            progress_callback(0.6)
        
        # Burn subtitles into video using GPU/CPU encoder
        ass_path_escaped = ass_file.replace('\\', '/').replace(':', '\\:')
        
        # Get video duration for progress
        probe_cmd = [self.ffmpeg_path, "-i", input_path, "-f", "null", "-"]
        result = subprocess.run(probe_cmd, capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)
        duration_match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", result.stderr)
        video_duration = 60
        if duration_match:
            h, m, s = duration_match.groups()
            video_duration = int(h) * 3600 + int(m) * 60 + float(s)
        
        encoder_args = self.get_video_encoder_args()
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", input_path,
            "-vf", f"ass='{ass_path_escaped}'",
            *encoder_args,
            "-c:a", "copy",
            "-progress", "pipe:1",
            output_path
        ]
        
        self.log_ffmpeg_command(cmd, "Burn Captions (old function)")
        
        # Caption burn is 60-100%
        self.run_ffmpeg_with_progress(cmd, video_duration,
            lambda p: progress_callback(0.6 + p * 0.4) if progress_callback else None)
        
        os.unlink(ass_file)

    def add_watermark_with_progress(self, input_path: str, output_path: str, progress_callback):
        """Add watermark overlay to video with progress tracking"""
        
        watermark_path = self.watermark_settings.get("image_path", "")
        if not watermark_path or not Path(watermark_path).exists():
            self.log("  Warning: Watermark image not found, skipping")
            import shutil
            shutil.copy(input_path, output_path)
            return
        
        progress_callback(0.1)
        
        # Get video dimensions
        probe_cmd = [self.ffmpeg_path, "-i", input_path]
        result = subprocess.run(probe_cmd, capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)
        
        res_match = re.search(r'(\d{3,4})x(\d{3,4})', result.stderr)
        if res_match:
            video_width, video_height = int(res_match.group(1)), int(res_match.group(2))
        else:
            video_width, video_height = 1080, 1920
        
        progress_callback(0.2)
        
        # Calculate watermark size and position
        scale = self.watermark_settings.get("scale", 0.15)
        pos_x = self.watermark_settings.get("position_x", 0.85)
        pos_y = self.watermark_settings.get("position_y", 0.05)
        opacity = self.watermark_settings.get("opacity", 0.8)
        
        # Calculate watermark width in pixels
        watermark_width = int(video_width * scale)
        
        # Calculate position in pixels
        x_pixels = int(pos_x * video_width)
        y_pixels = int(pos_y * video_height)
        
        # Escape watermark path for FFmpeg (Windows paths)
        watermark_escaped = watermark_path.replace('\\', '/').replace(':', '\\:')
        
        # Build FFmpeg overlay filter with proper opacity control
        # Scale watermark, apply opacity via colorchannelmixer, then overlay
        filter_complex = (
            f"[1:v]scale={watermark_width}:-1,format=rgba,"
            f"colorchannelmixer=aa={opacity}[wm];"
            f"[0:v][wm]overlay={x_pixels}:{y_pixels}"
        )
        
        progress_callback(0.3)
        
        # Get video duration for progress
        duration_match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", result.stderr)
        video_duration = 60
        if duration_match:
            h, m, s = duration_match.groups()
            video_duration = int(h) * 3600 + int(m) * 60 + float(s)
        
        # Apply watermark using GPU/CPU encoder
        encoder_args = self.get_video_encoder_args()
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", input_path,
            "-i", watermark_path,
            "-filter_complex", filter_complex,
            *encoder_args,
            "-pix_fmt", "yuv420p",  # Ensure compatibility
            "-c:a", "copy",
            "-movflags", "+faststart",  # Enable streaming
            "-progress", "pipe:1",
            output_path
        ]
        
        self.log_ffmpeg_command(cmd, "Apply Watermark")
        
        # Watermark application is 30-100%
        self.run_ffmpeg_with_progress(cmd, video_duration,
            lambda p: progress_callback(0.3 + p * 0.7))
        
        if not Path(output_path).exists():
            raise Exception("Failed to apply watermark")

    def add_credit_watermark_with_progress(self, input_path: str, output_path: str, progress_callback):
        """Add credit text watermark (channel name) to video with progress tracking"""
        
        if not self.channel_name:
            self.log("  Warning: No channel name available, skipping credit")
            import shutil
            shutil.copy(input_path, output_path)
            return
        
        progress_callback(0.1)
        
        # Get video dimensions
        probe_cmd = [self.ffmpeg_path, "-i", input_path]
        result = subprocess.run(probe_cmd, capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)
        
        res_match = re.search(r'(\d{3,4})x(\d{3,4})', result.stderr)
        if res_match:
            video_width, video_height = int(res_match.group(1)), int(res_match.group(2))
        else:
            video_width, video_height = 1080, 1920
        
        progress_callback(0.2)
        
        # Get credit watermark settings
        size = self.credit_watermark_settings.get("size", 0.03)
        pos_x = self.credit_watermark_settings.get("position_x", 0.5)
        pos_y = self.credit_watermark_settings.get("position_y", 0.95)
        opacity = self.credit_watermark_settings.get("opacity", 0.7)
        
        # Calculate font size in pixels (based on video height)
        font_size = int(video_height * size)
        
        # Calculate position in pixels
        x_pixels = int(pos_x * video_width)
        y_pixels = int(pos_y * video_height)
        
        # Prepare credit text
        credit_text = f"Source: {self.channel_name}"
        # Escape special characters for FFmpeg drawtext
        credit_text_escaped = credit_text.replace("'", "'\\''").replace(":", "\\:")
        
        # Build FFmpeg drawtext filter
        # Use fontfile for portable FFmpeg (avoids fontconfig dependency)
        # Try to find a system font, fallback to built-in if not available
        font_file = None
        if sys.platform == "win32":
            # Windows fonts directory
            windows_fonts = [
                "C:/Windows/Fonts/arial.ttf",
                "C:/Windows/Fonts/segoeui.ttf",
                "C:/Windows/Fonts/tahoma.ttf",
            ]
            for font in windows_fonts:
                if Path(font).exists():
                    font_file = font.replace("\\", "/").replace(":", "\\:")
                    break
        
        # Build filter string
        if font_file:
            filter_str = (
                f"drawtext=fontfile='{font_file}':"
                f"text='{credit_text_escaped}':"
                f"fontsize={font_size}:"
                f"fontcolor=white@{opacity}:"
                f"borderw=2:"
                f"bordercolor=black@{opacity}:"
                f"x={x_pixels}-(text_w/2):"
                f"y={y_pixels}-(text_h/2)"
            )
        else:
            # Fallback without fontfile (may cause fontconfig warning but should still work)
            filter_str = (
                f"drawtext=text='{credit_text_escaped}':"
                f"fontsize={font_size}:"
                f"fontcolor=white@{opacity}:"
                f"borderw=2:"
                f"bordercolor=black@{opacity}:"
                f"x={x_pixels}-(text_w/2):"
                f"y={y_pixels}-(text_h/2)"
            )
        
        progress_callback(0.3)
        
        # Get video duration for progress
        duration_match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", result.stderr)
        video_duration = 60
        if duration_match:
            h, m, s = duration_match.groups()
            video_duration = int(h) * 3600 + int(m) * 60 + float(s)
        
        # Apply credit text using GPU/CPU encoder
        encoder_args = self.get_video_encoder_args()
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", input_path,
            "-vf", filter_str,
            *encoder_args,
            "-c:a", "copy",
            "-movflags", "+faststart",
            "-progress", "pipe:1",
            output_path
        ]
        
        self.log_ffmpeg_command(cmd, "Apply Credit Watermark")
        
        # Credit application is 30-100%
        self.run_ffmpeg_with_progress(cmd, video_duration,
            lambda p: progress_callback(0.3 + p * 0.7))
        
        if not Path(output_path).exists():
            raise Exception("Failed to apply credit watermark")

    def find_highlights_only(self, url: str, num_clips: int = 5, custom_rules: str = "") -> dict:
        """Phase 1: Download video and find highlights (without processing)

        Returns:
            dict with keys:
                - 'session_dir': Path to session directory
                - 'video_path': Path to downloaded video
                - 'srt_path': Path to subtitle file
                - 'highlights': List of highlight dicts with metadata
                - 'video_info': Video metadata (title, channel, etc.)
        """
        # Create session directory with timestamp
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_dir = self.output_dir / "sessions" / timestamp
        session_dir.mkdir(parents=True, exist_ok=True)
        
        # Update temp_dir to session-specific temp
        self.temp_dir = session_dir / "_temp"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        self.log(f"Session directory: {session_dir}")
        
        # Step 1: Download video
        self.set_progress("Downloading video...", 0.1)
        video_path, srt_path, video_info = self.download_video(url)
        
        # Store channel name for credit watermark
        self.channel_name = video_info.get("channel", "") if video_info else ""
        
        if self.is_cancelled():
            return None
        
        if not srt_path:
            self.log("  ℹ Subtitle YouTube tidak ditemukan langsung, mencoba auto-transcribe dengan Whisper...")
            srt_path = self._auto_transcribe_video_to_srt(video_path)

        if not srt_path:
            raise Exception(
                f"❌ ERROR: Subtitle tidak tersedia\n\n"
                f"Video ini tidak memiliki subtitle bahasa: {self.subtitle_language.upper()}\n\n"
                f"SOLUSI:\n"
                f"1. Cek subtitle yang tersedia untuk video ini:\n"
                f"   - Klik tombol 'Check Subtitles' di aplikasi\n"
                f"   - Atau buka video di YouTube dan cek CC/subtitle\n\n"
                f"2. Pilih bahasa subtitle lain yang tersedia\n"
                f"   (contoh: en - English, es - Spanish)\n\n"
                f"3. Atau gunakan video lain yang punya subtitle Indonesia\n\n"
                f"💡 TIP: Video podcast/interview biasanya punya auto-generated subtitle\n"
                f"dalam berbagai bahasa. Pilih yang paling mendekati."
            )
        
        # Step 2: Find highlights
        self.set_progress("Finding highlights with AI...", 0.5)
        transcript = self.parse_srt(srt_path)
        highlights = self.find_highlights(transcript, video_info, num_clips, custom_rules=custom_rules)
        
        if self.is_cancelled():
            return None
        
        if not highlights:
            raise Exception(
                "❌ No valid highlights found!\n\n"
                "Possible causes:\n"
                "1. AI model failed to generate highlights\n"
                "2. Video transcript too short or not suitable\n"
                "3. AI model configuration issue\n\n"
                "Try:\n"
                "- Using a different AI model (GPT-4, Gemini, etc.)\n"
                "- Checking AI API settings\n"
                "- Using a longer video with more content"
            )
        
        self.set_progress("Highlights found!", 1.0)
        self.log(f"\n✅ Found {len(highlights)} highlights")
        
        # Save session data to JSON for resume capability
        session_data_file = session_dir / "session_data.json"
        session_data = {
            "session_dir": str(session_dir),
            "video_path": video_path,
            "srt_path": srt_path,
            "highlights": highlights,
            "video_info": video_info,
            "created_at": datetime.now().isoformat(),
            "status": "highlights_found",
            "heatmap_available": self.heatmap_data is not None,
            "heatmap_peaks": self.get_heatmap_peaks() if self.heatmap_data else []
        }
        
        with open(session_data_file, "w", encoding="utf-8") as f:
            json.dump(session_data, f, indent=2, ensure_ascii=False)
        
        self.log(f"Session data saved to: {session_data_file}")
        
        return session_data
    
    def process_selected_highlights(self, video_path: str, selected_highlights: list, 
                                   session_dir: Path, add_captions: bool = True, 
                                   add_hook: bool = True):
        """Phase 2: Process only selected highlights
        
        Args:
            video_path: Path to source video
            selected_highlights: List of highlight dicts to process
            session_dir: Session directory for output
            add_captions: Whether to add captions
            add_hook: Whether to add hook
        """
        if not selected_highlights:
            raise Exception("No highlights selected for processing")
        
        self.log(f"\n[Processing {len(selected_highlights)} selected clips]")
        
        # Ensure session_dir is Path object
        if isinstance(session_dir, str):
            session_dir = Path(session_dir)
        
        # Update output_dir to session clips folder
        clips_dir = session_dir / "clips"
        clips_dir.mkdir(parents=True, exist_ok=True)
        
        # Process each selected clip
        total_clips = len(selected_highlights)
        for i, highlight in enumerate(selected_highlights, 1):
            if self.is_cancelled():
                return
            
            # Create clip-specific folder
            clip_folder = clips_dir / f"clip_{i:03d}"
            clip_folder.mkdir(parents=True, exist_ok=True)
            
            # Temporarily override output_dir for this clip
            original_output_dir = self.output_dir
            self.output_dir = clip_folder.parent
            
            try:
                self.process_clip(video_path, highlight, i, total_clips, 
                                add_captions=add_captions, add_hook=add_hook)
            finally:
                # Restore original output_dir
                self.output_dir = original_output_dir
        
        # Cleanup temp files
        self.set_progress("Cleaning up...", 0.95)
        self.cleanup()
        
        # Update session status to completed
        session_data_file = session_dir / "session_data.json"
        if session_data_file.exists():
            with open(session_data_file, "r", encoding="utf-8") as f:
                session_data = json.load(f)
            
            session_data["status"] = "completed"
            session_data["completed_at"] = datetime.now().isoformat()
            session_data["clips_processed"] = total_clips
            
            with open(session_data_file, "w", encoding="utf-8") as f:
                json.dump(session_data, f, indent=2, ensure_ascii=False)
        
        self.set_progress("Complete!", 1.0)
        self.log(f"\n✅ Created {total_clips} clips in: {clips_dir}")
