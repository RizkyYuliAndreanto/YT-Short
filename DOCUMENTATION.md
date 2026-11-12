# 📚 YT-Short-Clipper - Dokumentasi Lengkap

> Dokumentasi teknis lengkap untuk maintenance, pengembangan, dan troubleshooting

---

## 📑 Daftar Isi

1. [Gambaran Umum Proyek](#1-gambaran-umum-proyek)
2. [Arsitektur Sistem](#2-arsitektur-sistem)
3. [Daftar Fitur & File Utama](#3-daftar-fitur--file-utama)
4. [Struktur Direktori](#4-struktur-direktori)
5. [Panduan Maintenance per Fitur](#5-panduan-maintenance-per-fitur)
6. [Alur Data & Proses](#6-alur-data--proses)
7. [Konfigurasi & Settings](#7-konfigurasi--settings)
8. [Troubleshooting Guide](#8-troubleshooting-guide)

---

## 1. Gambaran Umum Proyek

### Apa itu YT-Short-Clipper?

Aplikasi desktop untuk mengotomasi pembuatan konten short-form (TikTok, Reels, Shorts) dari video YouTube panjang. Aplikasi ini menggunakan:

- **AI (GPT-4, Whisper)** untuk deteksi highlight dan captioning
- **Computer Vision (OpenCV)** untuk smart cropping/face tracking
- **FFmpeg** untuk processing video
- **yt-dlp** untuk download video

### Tech Stack

| Komponen         | Teknologi                |
| ---------------- | ------------------------ |
| Bahasa           | Python 3.10+             |
| GUI              | CustomTkinter            |
| Video Processing | FFmpeg, OpenCV           |
| Download         | yt-dlp                   |
| AI/LLM           | OpenAI API, Groq, Gemini |
| TTS              | OpenAI TTS, Edge TTS     |
| Transcription    | OpenAI Whisper           |

---

## 2. Arsitektur Sistem

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         YT-SHORT-CLIPPER                                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                        FRONTEND (GUI)                            │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐   │   │
│  │  │ app.py   │ │ pages/   │ │components│ │ dialogs/         │   │   │
│  │  │(Main App)│ │(Screens) │ │(Widgets) │ │(Popups/Modals)   │   │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      BACKEND (Core Logic)                        │   │
│  │  ┌──────────────┐ ┌────────────────┐ ┌───────────────────────┐  │   │
│  │  │clipper_core  │ │caption_generator│ │clip_dub_engine       │  │   │
│  │  │(Main Engine) │ │(Auto Caption)   │ │(Clip+Dub Workflow)   │  │   │
│  │  └──────────────┘ └────────────────┘ └───────────────────────┘  │   │
│  │  ┌──────────────┐ ┌────────────────┐ ┌───────────────────────┐  │   │
│  │  │clip_cutter   │ │tts_maker_core  │ │script_generator       │  │   │
│  │  │(Video Cutter)│ │(TTS Engine)    │ │(AI Script Writer)     │  │   │
│  │  └──────────────┘ └────────────────┘ └───────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                     EXTERNAL SERVICES                            │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐   │   │
│  │  │ yt-dlp   │ │ FFmpeg   │ │ OpenAI   │ │ YouTube/TikTok   │   │   │
│  │  │(Download)│ │(Process) │ │ API      │ │ Upload APIs      │   │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Daftar Fitur & File Utama

### 🎯 FITUR UTAMA

| #   | Fitur                      | Deskripsi                                                  | File Utama                                  | File Pendukung                                                       |
| --- | -------------------------- | ---------------------------------------------------------- | ------------------------------------------- | -------------------------------------------------------------------- |
| 1   | **YouTube Auto Clipper**   | Otomatis potong highlight dari video YouTube panjang       | `clipper_core.py`                           | `pages/youtube_clipper_page.py`, `pages/highlight_selection_page.py` |
| 2   | **AI Highlight Detection** | GPT-4 menemukan momen menarik dari transkrip               | `clipper_core.py` → `find_highlights()`     | `pages/settings/ai_providers/highlight_finder.py`                    |
| 3   | **Portrait Conversion**    | Konversi landscape ke portrait (9:16) dengan face tracking | `clipper_core.py` → `convert_to_portrait()` | `components/portrait_crop_editor.py`                                 |
| 4   | **Auto Caption**           | Generate subtitle word-by-word dengan Whisper              | `caption_generator.py`                      | `pages/auto_caption_page.py`                                         |
| 5   | **Hook Generation**        | Buat intro dengan TTS dan overlay teks                     | `clipper_core.py` → `generate_hook()`       | `pages/settings/ai_providers/hook_maker.py`                          |
| 6   | **Clip+Dub**               | Potong video + dubbing dengan AI narration                 | `clip_dub_engine.py`                        | `pages/clip_dub_page.py`, `script_generator.py`                      |
| 7   | **Clip Cutter**            | Potong segment dari berbagai platform                      | `clip_cutter_core.py`                       | `pages/clip_cutter_page.py`                                          |
| 8   | **TTS Maker**              | Generate audio dari teks dengan Edge TTS                   | `tts_maker_core.py`                         | `pages/tts_maker_page.py`, `edge_tts_engine.py`                      |
| 9   | **Video Analyzer**         | Analisis konten video dengan AI                            | `video_analyzer.py`                         | -                                                                    |
| 10  | **YouTube Upload**         | Upload hasil ke YouTube                                    | `youtube_uploader.py`                       | `dialogs/youtube_upload.py`                                          |
| 11  | **TikTok Upload**          | Upload hasil ke TikTok                                     | `tiktok_uploader.py`                        | `dialogs/tiktok_upload.py`                                           |

### 📄 HALAMAN GUI (pages/)

| Halaman             | File                                | Deskripsi                          |
| ------------------- | ----------------------------------- | ---------------------------------- |
| Landing Page        | `pages/landing_page_v2.py`          | Halaman utama dengan menu fitur    |
| YouTube Clipper     | `pages/youtube_clipper_page.py`     | Input URL & mulai proses clipping  |
| Highlight Selection | `pages/highlight_selection_page.py` | Pilih highlight yang akan diproses |
| Processing          | `pages/processing_page.py`          | Tampilan progress saat proses      |
| Results             | `pages/results_page.py`             | Tampilan hasil clip yang dibuat    |
| Clip+Dub            | `pages/clip_dub_page.py`            | Workflow clip + dubbing            |
| Clip Cutter         | `pages/clip_cutter_page.py`         | Potong segment dari video          |
| TTS Maker           | `pages/tts_maker_page.py`           | Generate TTS dari teks             |
| Auto Caption        | `pages/auto_caption_page.py`        | Tambah caption ke video            |
| Dubbing Studio      | `pages/dubbing_studio_page_v2.py`   | Studio dubbing lengkap             |
| Settings            | `pages/settings_page.py`            | Halaman pengaturan utama           |
| Session Browser     | `pages/session_browser_page.py`     | Browse sesi processing sebelumnya  |
| Browse              | `pages/browse_page.py`              | Browse file output                 |

### ⚙️ SETTINGS (pages/settings/)

| Setting          | File                           | Deskripsi                      |
| ---------------- | ------------------------------ | ------------------------------ |
| AI API Settings  | `ai_api_settings.py`           | Konfigurasi API key untuk AI   |
| YouTube API      | `youtube_api_settings.py`      | Konfigurasi YouTube OAuth      |
| Watermark        | `watermark_settings.py`        | Pengaturan watermark           |
| Credit Watermark | `credit_watermark_settings.py` | Watermark kredit/branding      |
| Output Settings  | `output_settings.py`           | Pengaturan output video        |
| Performance      | `performance_settings.py`      | Pengaturan performa (GPU, dll) |
| Repliz Upload    | `repliz_settings.py`           | Konfigurasi Repliz             |
| About            | `about_settings.py`            | Info tentang aplikasi          |

### 🤖 AI PROVIDERS (pages/settings/ai_providers/)

| Provider         | File                  | Deskripsi                           |
| ---------------- | --------------------- | ----------------------------------- |
| Base Provider    | `base_provider.py`    | Abstract class untuk semua provider |
| Highlight Finder | `highlight_finder.py` | AI untuk cari highlight             |
| Caption Maker    | `caption_maker.py`    | AI untuk buat caption               |
| Hook Maker       | `hook_maker.py`       | AI untuk buat hook text             |
| Title Generator  | `title_generator.py`  | AI untuk generate title SEO         |

---

## 4. Struktur Direktori

```
yt-short-clipper/
│
├── 📄 app.py                      # Entry point utama aplikasi
├── 📄 clipper_core.py             # Engine utama untuk clipping
├── 📄 caption_generator.py        # Engine auto caption
├── 📄 clip_cutter_core.py         # Engine potong video multi-platform
├── 📄 clip_dub_engine.py          # Engine clip + dubbing
├── 📄 edge_tts_engine.py          # Edge TTS wrapper
├── 📄 tts_maker_core.py           # TTS engine scalable
├── 📄 tts_sync.py                 # Sinkronisasi TTS dengan video
├── 📄 script_generator.py         # AI script generator
├── 📄 video_analyzer.py           # Video analysis dengan AI
├── 📄 youtube_uploader.py         # YouTube upload handler
├── 📄 tiktok_uploader.py          # TikTok upload handler
├── 📄 version.py                  # Info versi aplikasi
├── 📄 webview_app.py              # Webview wrapper (alternatif GUI)
│
├── 📁 pages/                      # Halaman GUI
│   ├── landing_page_v2.py         # Halaman utama
│   ├── youtube_clipper_page.py    # Halaman YouTube clipper
│   ├── highlight_selection_page.py # Pilih highlight
│   ├── processing_page.py         # Progress processing
│   ├── results_page.py            # Hasil clips
│   ├── clip_dub_page.py           # Clip+Dub workflow
│   ├── clip_cutter_page.py        # Clip cutter
│   ├── tts_maker_page.py          # TTS maker
│   ├── auto_caption_page.py       # Auto caption
│   ├── dubbing_studio_page_v2.py  # Dubbing studio
│   ├── settings_page.py           # Settings utama
│   ├── session_browser_page.py    # Browse session
│   ├── browse_page.py             # Browse output
│   ├── contact_page.py            # Contact/support
│   ├── clipping_page.py           # (Legacy) clipping
│   └── 📁 settings/               # Sub-pages untuk settings
│       ├── ai_api_settings.py
│       ├── youtube_api_settings.py
│       ├── watermark_settings.py
│       ├── output_settings.py
│       ├── performance_settings.py
│       └── 📁 ai_providers/       # AI provider configs
│           ├── base_provider.py
│           ├── highlight_finder.py
│           ├── caption_maker.py
│           ├── hook_maker.py
│           └── title_generator.py
│
├── 📁 components/                 # Komponen UI reusable
│   ├── ai_provider_card.py        # Card untuk setting AI provider
│   ├── page_layout.py             # Layout template halaman
│   ├── portrait_crop_editor.py    # Editor crop portrait
│   ├── progress_step.py           # Progress indicator
│   ├── ui_theme.py                # Theme & styling
│   └── video_preview.py           # Preview video widget
│
├── 📁 dialogs/                    # Dialog/modal windows
│   ├── model_selector.py          # Pilih model AI
│   ├── youtube_upload.py          # Dialog upload YouTube
│   ├── tiktok_upload.py           # Dialog upload TikTok
│   └── repliz_upload.py           # Dialog upload Repliz
│
├── 📁 config/                     # Konfigurasi
│   ├── config_manager.py          # Manager untuk config.json
│   └── ai_provider_config.py      # Konfigurasi AI providers
│
├── 📁 utils/                      # Utilitas
│   ├── dependency_manager.py      # Auto-download dependencies
│   ├── frame_analyzer.py          # Analisis frame video
│   ├── gpu_detector.py            # Deteksi GPU untuk HW accel
│   ├── helpers.py                 # Helper functions
│   └── logger.py                  # Logging system
│
├── 📁 web/                        # Web interface (alternatif)
│   ├── index.html
│   ├── app.js
│   ├── css/
│   └── components/
│
├── 📁 assets/                     # Assets (icon, gambar)
│   ├── icon.png
│   ├── icon.ico
│   └── docs/                      # Screenshot untuk dokumentasi
│
├── 📁 output/                     # Folder output (auto-created)
│   ├── _temp/                     # File temporary
│   └── [timestamp]/               # Folder per session
│       ├── master.mp4             # Video final
│       └── data.json              # Metadata
│
├── 📄 config.json                 # User settings
├── 📄 cookies.txt                 # YouTube cookies
├── 📄 requirements.txt            # Python dependencies
├── 📄 README.md                   # User documentation
├── 📄 GUIDE.md                    # User guide (English)
├── 📄 PANDUAN.md                  # User guide (Indonesia)
├── 📄 AGENTS.md                   # AI developer guide
└── 📄 CONTRIBUTING.md             # Contribution guide
```

---

## 5. Panduan Maintenance per Fitur

### 🔧 FITUR 1: YouTube Auto Clipper

**Deskripsi:** Otomatis download video YouTube, deteksi highlight dengan AI, potong, convert portrait, tambah hook dan caption.

**File Utama:**

- `clipper_core.py` - Class `AutoClipperCore`

**Flow:**

```
1. download_video()     → Download video + subtitle dengan yt-dlp
2. parse_srt()          → Parse file .srt ke list segment
3. find_highlights()    → Kirim transcript ke GPT-4, dapat highlight timestamps
4. process_clip()       → Untuk setiap highlight:
   ├── cut_clip()           → Potong video dengan FFmpeg
   ├── convert_to_portrait() → Crop ke 9:16 dengan face tracking
   ├── generate_hook()       → Buat intro scene dengan TTS
   └── add_captions()        → Burn subtitle dengan Whisper
```

**Troubleshooting:**
| Problem | Penyebab | Solusi | File |
|---------|----------|--------|------|
| Download gagal | Cookies expired | Re-export cookies dari browser | `clipper_core.py` → `download_video()` |
| Highlight tidak relevan | Prompt kurang optimal | Edit `SYSTEM_PROMPT.md` | `SYSTEM_PROMPT.md` |
| Face tracking salah | OpenCV gagal detect | Coba MediaPipe mode | `clipper_core.py` → `convert_to_portrait()` |
| Caption tidak sinkron | Whisper timing offset | Adjust timing di caption_generator | `caption_generator.py` |

---

### 🔧 FITUR 2: AI Highlight Detection

**Deskripsi:** Menggunakan LLM (GPT-4/Gemini/Groq) untuk menemukan momen menarik dari transkrip video.

**File Utama:**

- `clipper_core.py` → method `find_highlights()`
- `pages/settings/ai_providers/highlight_finder.py`

**Flow:**

```
1. Baca file .srt dari download
2. Parse transcript dengan timestamp
3. Construct prompt: SYSTEM_PROMPT.md + transcript
4. Kirim ke LLM API
5. Parse JSON response → list highlight dengan start/end time + hook text
```

**Config yang Relevan:**

```json
{
  "ai_highlight": {
    "base_url": "https://api.openai.com/v1",
    "api_key": "sk-xxx",
    "model": "gpt-4-turbo",
    "temperature": 1.0
  }
}
```

**Troubleshooting:**
| Problem | Penyebab | Solusi | File |
|---------|----------|--------|------|
| API error 401 | API key invalid | Cek API key di settings | `config/config_manager.py` |
| Response tidak valid JSON | Model salah format | Tambah retry dengan prompt lebih strict | `clipper_core.py` |
| Highlight terlalu pendek/panjang | Parameter salah | Adjust min/max duration | Settings → AI API |

---

### 🔧 FITUR 3: Portrait Conversion (Smart Crop)

**Deskripsi:** Konversi video landscape (16:9) ke portrait (9:16) dengan face tracking dan simulated camera cuts.

**File Utama:**

- `clipper_core.py` → method `convert_to_portrait()`
- `components/portrait_crop_editor.py`

**Mode:**

1. **OpenCV (Fast)** - Crop ke wajah terbesar, cepat tapi basic
2. **MediaPipe (Smart)** - Track active speaker via lip movement, akurat tapi 2-3x lebih lambat

**Flow:**

```
1. Detect semua wajah di frame pertama
2. Track wajah di setiap frame
3. Jika MediaPipe: analisis lip movement untuk deteksi speaker aktif
4. Calculate crop window 9:16
5. Smooth transition antar "shot" (simulated camera cut)
6. Apply crop dengan FFmpeg
```

**Troubleshooting:**
| Problem | Penyebab | Solusi | File |
|---------|----------|--------|------|
| Crop tidak smooth | switch_threshold terlalu rendah | Naikkan di config | `clipper_core.py` |
| Wajah tidak terdeteksi | Lighting buruk / angle aneh | Gunakan manual crop | `components/portrait_crop_editor.py` |
| Processing terlalu lama | MediaPipe + video panjang | Gunakan OpenCV mode | Settings → Performance |

---

### 🔧 FITUR 4: Auto Caption

**Deskripsi:** Generate subtitle word-by-word dengan highlight ala CapCut/TikTok menggunakan Whisper.

**File Utama:**

- `caption_generator.py` - Class `CaptionGenerator`
- `pages/auto_caption_page.py`

**Flow:**

```
1. Extract audio dari video (FFmpeg)
2. Kirim ke Whisper API → dapat word-level timestamps
3. Generate file .ass dengan styling:
   - Font: Arial Black / Montserrat
   - Highlight: Yellow pada kata aktif
   - Outline: Black
4. Burn subtitle ke video dengan FFmpeg
```

**Styling Options:**

```python
CAPTION_MODES = {
    "sentence": "Full Sentence (default)",
    "word_by_word": "Word-by-Word (TikTok style)",
    "word_highlight": "Karaoke Highlight",
    "chunk": "2-3 Word Chunks",
}
```

**Troubleshooting:**
| Problem | Penyebab | Solusi | File |
|---------|----------|--------|------|
| Caption tidak muncul | Path font salah | Cek font installed | `caption_generator.py` |
| Timing tidak akurat | Audio quality buruk | Coba model whisper-1 | Settings → AI API |
| Font tidak sesuai | Font tidak ada di sistem | Install font atau ganti | `caption_generator.py` → `AVAILABLE_FONTS` |

---

### 🔧 FITUR 5: Hook Generation

**Deskripsi:** Buat intro scene dengan hook text overlay dan TTS voiceover.

**File Utama:**

- `clipper_core.py` → method `generate_hook()`
- `pages/settings/ai_providers/hook_maker.py`

**Flow:**

```
1. Extract frame pertama dari clip
2. Generate TTS audio dari hook text (OpenAI TTS)
3. Buat scene intro:
   - Background: blurred/dimmed first frame
   - Overlay: hook text dengan styling
   - Audio: TTS voiceover
4. Concatenate hook + main clip
```

**Troubleshooting:**
| Problem | Penyebab | Solusi | File |
|---------|----------|--------|------|
| TTS tidak generate | API key TTS tidak valid | Cek ai_tts config | `config.json` |
| Suara TTS aneh | Voice tidak cocok | Ganti voice (nova/shimmer/alloy) | Settings → Hook Maker |
| Hook text terlalu panjang | max_words tidak diset | Set max_words di config | `clipper_core.py` |

---

### 🔧 FITUR 6: Clip+Dub Engine

**Deskripsi:** Workflow lengkap: potong video + AI script + dubbing narration.

**File Utama:**

- `clip_dub_engine.py` - Class `ClipDubEngine`
- `pages/clip_dub_page.py`
- `script_generator.py`
- `tts_sync.py`

**Flow:**

```
1. Download video + subtitle + heatmap
2. AI cari clips berdasarkan context/pattern user
3. Assemble clips → draft 30-120s
4. AI generate narration script
5. User edit script (interactive)
6. TTS dubbing + subtitle burn → final video
```

**Pre-defined Patterns:**

```python
PATTERNS = {
    "documentary": {...},  # Dokumenter / fakta alam
    "tutorial": {...},      # Tutorial / how-to
    "shopping": {...},      # Product selling
    # dll
}
```

**Troubleshooting:**
| Problem | Penyebab | Solusi | File |
|---------|----------|--------|------|
| Script tidak relevan | Context kurang jelas | Berikan context lebih detail | `script_generator.py` |
| Audio tidak sinkron | Timing mismatch | Adjust di tts_sync | `tts_sync.py` |

---

### 🔧 FITUR 7: Clip Cutter (Multi-Platform)

**Deskripsi:** Potong segment dari berbagai platform: YouTube, TikTok, Instagram, Facebook.

**File Utama:**

- `clip_cutter_core.py` - Class `ClipCutterCore`
- `pages/clip_cutter_page.py`

**Supported Platforms:**

```python
PLATFORM_PATTERNS = {
    'youtube': [...],
    'youtube_shorts': [...],
    'tiktok': [...],
    'instagram': [...],
    'facebook': [...],
}
```

**Flow:**

```
1. Detect platform dari URL
2. Download video (partial untuk YouTube panjang)
3. Cut segment sesuai start/end time
4. Output ke folder
```

**Troubleshooting:**
| Problem | Penyebab | Solusi | File |
|---------|----------|--------|------|
| Platform tidak dikenali | Pattern regex tidak match | Tambah pattern baru | `clip_cutter_core.py` → `PLATFORM_PATTERNS` |
| Partial download gagal | yt-dlp issue | Update yt-dlp | `utils/dependency_manager.py` |

---

### 🔧 FITUR 8: TTS Maker

**Deskripsi:** Generate audio dari teks dengan berbagai voice menggunakan Edge TTS (gratis).

**File Utama:**

- `tts_maker_core.py` - Class `TTSMakerEngine`
- `edge_tts_engine.py` - Class `EdgeTTSEngine`
- `pages/tts_maker_page.py`

**Available Voices (Indonesian):**

```python
INDONESIAN_VOICES = {
    "id-ID-ArdiNeural": {"name": "Ardi", "gender": "Male"},
    "id-ID-GadisNeural": {"name": "Gadis", "gender": "Female"}
}
```

**Flow:**

```
1. User input teks
2. Pilih voice
3. Generate TTS dengan Edge TTS (async)
4. Post-processing audio (normalize, enhance)
5. Output file audio
```

**Troubleshooting:**
| Problem | Penyebab | Solusi | File |
|---------|----------|--------|------|
| TTS gagal generate | Network issue | Cek koneksi internet | `edge_tts_engine.py` |
| Suara patah-patah | Teks terlalu panjang | Split jadi segment | `tts_maker_core.py` |

---

### 🔧 FITUR 9: YouTube/TikTok Upload

**Deskripsi:** Upload hasil video langsung ke YouTube atau TikTok.

**File Utama:**

- `youtube_uploader.py` - Class `YouTubeUploader`
- `tiktok_uploader.py` - Class `TikTokUploader`
- `dialogs/youtube_upload.py`
- `dialogs/tiktok_upload.py`

**YouTube Setup:**

1. Buat project di Google Cloud Console
2. Enable YouTube Data API v3
3. Buat OAuth credentials
4. Download `client_secret.json`

**TikTok Setup:**

1. Daftar di TikTok Developer
2. Buat app, enable scopes: `user.info.basic`, `video.upload`, `video.publish`
3. Simpan Client Key & Secret

**Troubleshooting:**
| Problem | Penyebab | Solusi | File |
|---------|----------|--------|------|
| OAuth error | Redirect URI mismatch | Cek config di Google Console | `youtube_uploader.py` |
| TikTok "Something went wrong" | Redirect URI salah | Set ke `https://www.tiktok.com/` | `tiktok_uploader.py` |
| Upload limit | API quota exceeded | Tunggu reset quota | - |

---

## 6. Alur Data & Proses

### Main Processing Flow (YouTube Clipper)

```
User Input (URL)
       │
       ▼
┌──────────────┐     cookies.txt
│ Download     │◄────────────────
│ (yt-dlp)     │
└──────────────┘
       │
       ├── video.mp4
       └── video.id.srt
              │
              ▼
┌──────────────┐     SYSTEM_PROMPT.md
│ AI Highlight │◄────────────────────
│ Detection    │     + transcript
└──────────────┘
       │
       └── highlights.json
              │
              ▼
┌──────────────────────────────────────────┐
│ Process Each Highlight                   │
│  ┌────────┐  ┌──────────┐  ┌──────────┐ │
│  │  Cut   │→│ Portrait │→│  Hook    │ │
│  │ Clip   │  │ Convert  │  │ Generate │ │
│  └────────┘  └──────────┘  └──────────┘ │
│                              │           │
│                              ▼           │
│                         ┌──────────┐    │
│                         │ Caption  │    │
│                         │ Burn     │    │
│                         └──────────┘    │
└──────────────────────────────────────────┘
       │
       ▼
┌──────────────┐
│ Output       │
│ ├── master.mp4
│ └── data.json
└──────────────┘
       │
       ▼
┌──────────────┐
│ Upload       │ (Optional)
│ YouTube/TikTok
└──────────────┘
```

---

## 7. Konfigurasi & Settings

### config.json Structure

```json
{
  "output_dir": "output",

  "ai_highlight": {
    "base_url": "https://api.openai.com/v1",
    "api_key": "sk-xxx",
    "model": "gpt-4-turbo",
    "temperature": 1.0
  },

  "ai_caption": {
    "base_url": "https://api.openai.com/v1",
    "api_key": "sk-xxx",
    "model": "whisper-1"
  },

  "ai_tts": {
    "base_url": "https://api.openai.com/v1",
    "api_key": "sk-xxx",
    "model": "tts-1",
    "voice": "nova"
  },

  "ai_hook": {
    "base_url": "https://api.openai.com/v1",
    "api_key": "sk-xxx",
    "model": "gpt-4-turbo"
  },

  "clip_settings": {
    "num_clips": 5,
    "min_duration": 60,
    "max_duration": 120,
    "target_duration": 90
  },

  "portrait_settings": {
    "output_width": 1080,
    "output_height": 1920,
    "detection_mode": "opencv",
    "min_frames_before_switch": 210,
    "switch_threshold": 3.0
  },

  "watermark": {
    "enabled": false,
    "path": "",
    "position": "bottom_right",
    "opacity": 0.8,
    "scale": 0.15
  },

  "performance": {
    "use_gpu": true,
    "gpu_encoder": "h264_nvenc"
  }
}
```

### Environment Variables (Optional)

```env
OPENAI_API_KEY=sk-xxx
GROQ_API_KEY=gsk_xxx
GOOGLE_API_KEY=xxx
```

---

## 8. Troubleshooting Guide

### Quick Reference Table

| Kategori    | Problem                     | File untuk Dicek                              |
| ----------- | --------------------------- | --------------------------------------------- |
| Download    | Video tidak bisa didownload | `clipper_core.py`, `cookies.txt`              |
| AI          | API error / response aneh   | `config.json`, AI provider files              |
| Video       | Output corrupt / tidak play | `clipper_core.py` → FFmpeg commands           |
| Caption     | Subtitle tidak muncul/salah | `caption_generator.py`                        |
| TTS         | Audio tidak generate        | `edge_tts_engine.py`, `tts_maker_core.py`     |
| Upload      | OAuth error                 | `youtube_uploader.py`, `tiktok_uploader.py`   |
| GUI         | Crash / freeze              | `app.py`, check threading                     |
| Performance | Terlalu lambat              | `utils/gpu_detector.py`, performance settings |

### Debug Mode

Untuk enable debug logging, set di `utils/logger.py`:

```python
DEBUG_MODE = True
```

Log akan ditulis ke `error.log`.

### Common FFmpeg Issues

```bash
# Check FFmpeg version
ffmpeg -version

# Test basic encoding
ffmpeg -i input.mp4 -c:v libx264 -c:a aac output.mp4
```

### Reset Config

Jika config corrupt, hapus `config.json` dan restart app. Config baru akan di-generate.

---

## 📝 Changelog & Version History

Lihat `version.py` untuk versi terkini dan `CHANGELOG.md` (jika ada) untuk history perubahan.

---

## 👨‍💻 Kontak & Support

- **Discord:** https://s.id/ytsdiscord
- **GitHub Issues:** Untuk bug report
- **Email:** Lihat di app → Settings → About

---

_Dokumentasi ini dibuat untuk membantu maintenance dan pengembangan YT-Short-Clipper. Update secara berkala sesuai perubahan fitur._
