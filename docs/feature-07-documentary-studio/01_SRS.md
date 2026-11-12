# SRS — Documentary Studio (Feature 07)

## 1. Tujuan dokumen

Software Requirements Specification untuk implementasi **Documentary Studio**, fitur ke-7 standalone pada YT-Shorts. Dokumen ini memandu AI agent agar arsitektur tetap konsisten dengan project existing dan tidak merusak fitur lama.

## 2. Ruang lingkup

Sistem baru terdiri dari:

- Satu halaman GUI baru untuk workflow Documentary Studio.
- Satu engine orkestrator baru untuk pipeline dokumenter.
- Adapter/provider kecil untuk TTS, LLM, dan stock footage (Pexels/Pixabay) yang sudah ada.
- Integrasi minimal ke `app.py` dan `pages/landing_page_v2.py` untuk navigasi.
- Config namespace baru `documentary`.

Sistem tidak menggantikan engine existing; ia memanggilnya sebagai library.

## 3. Arsitektur sistem

```text
┌──────────────────────────────────────────────────────────────────────┐
│                         CONTEN CREATOR AGENT                         │
├──────────────────────────────────────────────────────────────────────┤
│ Landing Page V2                                                      │
│   ├─ YouTube Clipper        (existing, untouched)                    │
│   ├─ AI Dubbing Studio      (existing, untouched)                    │
│   ├─ Clip + Dub Studio      (existing, untouched)                    │
│   ├─ Clip Cutter            (existing, untouched)                    │
│   ├─ TTS Maker              (existing, untouched)                    │
│   ├─ Auto Caption           (existing, untouched)                    │
│   └─ Documentary Studio     (NEW feature 07)                         │
└──────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    Documentary Studio Frontend                        │
│  pages/documentary_page.py                                           │
│  - Brief & sources wizard                                            │
│  - Outline review                                                    │
│  - Segment/clip review                                               │
│  - Voice/subtitle/BGM settings                                       │
│  - Render progress + resume                                          │
└──────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     Documentary Engine Layer                          │
│  documentary_engine.py                                               │
│  - DocumentaryEngine orchestrator                                    │
│  - SourceManager / TranscriptService                                 │
│  - OutlineService / SegmentPlanner                                   │
│  - StockFootageService / SourceRanker (Pexels/Pixabay)               │
│  - TimelineAssembler / RenderService                                 │
│  - MetadataService                                                   │
└──────────────────────────────────────────────────────────────────────┘
        │                 │                 │                 │
        ▼                 ▼                 ▼                 ▼
┌───────────────┐ ┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│ clip_cutter_  │ │ video_        │ │ script_       │ │ tts_sync /    │
│ core.py       │ │ analyzer.py   │ │ generator.py  │ │ edge_tts /    │
│ ClipCutterCore│ │ VideoAnalyzer │ │ ScriptGenerator│ │ future        │
│               │ │               │ │               │ │ Chatterbox    │
└───────────────┘ └───────────────┘ └───────────────┘ └───────────────┘
        │                 │                 │                 │
        └─────────────────┴────────┬────────┴─────────────────┘
                                   ▼
                    FFmpeg / yt-dlp / OpenCV utils
                    Pexels/Pixabay API (stock footage)
                    config.ai_providers + config.documentary
```

## 4. Modul yang diusulkan

### 4.1 File baru

| File | Tanggung jawab |
|---|---|
| `documentary_engine.py` | Orkestrator pipeline: source → transcript → outline → segment plan → clips → timeline → TTS → subtitle → render → metadata. |
| `documentary_tts.py` | Adapter TTS provider untuk Documentary Studio; baseline Edge TTS, extensible ke Chatterbox. |
| `documentary_stock.py` | Adapter stock footage Pexels/Pixabay: search, download, license/attribution metadata, base_url override. |
| `pages/documentary_page.py` | UI wizard Documentary Studio. |
| `pages/documentary_widgets.py` | Opsional: komponen UI khusus seperti source list editor, outline card, segment review card. |
| `config/documentary_defaults.py` | Opsional: default config namespace `documentary`. Bisa juga langsung di `ConfigManager`. |
| `tests/test_documentary_engine.py` | Opsional tapi disarankan untuk pure logic: parse brief, normalize plan, aspect handling, manifest. |

### 4.2 File existing yang boleh disentuh minimal

| File | Perubahan yang diizinkan |
|---|---|
| `app.py` | Import page baru, create page, register `self.pages["documentary"]`, handler navigasi/progress bila perlu. |
| `pages/landing_page_v2.py` | Tambah kartu mode ke-7 dan penyesuaian layout grid agar tidak overlap. |
| `config/config_manager.py` | Tambah default `documentary` namespace dan migrasi aman jika belum ada. |
| `utils/helpers.py` | Hanya jika perlu helper path/output khusus; jangan ubah perilaku helper existing. |

### 4.3 File existing yang tidak boleh diubah perilakunya

- `clip_dub_engine.py` portrait/shorts flow.
- `clipper_core.py` highlight/portrait pipeline.
- `pages/clip_dub_page.py`, `pages/youtube_clipper_page.py`, `pages/dubbing_studio_page_v2.py`, `pages/clip_cutter_page.py`, `pages/tts_maker_page.py`, `pages/auto_caption_page.py`.
- Settings existing kecuali penambahan namespace `documentary` yang backward compatible.

## 5. Spesifikasi fungsional per modul

### 5.1 `pages/documentary_page.py`

UI wizard dengan tahap:

1. **Brief & Sources**
   - Input brief/topik.
   - Target durasi.
   - Gaya narasi: dokumenter formal, storytelling, edukatif, investigatif.
   - Aspect ratio default `16:9`; opsi `9:16` hanya jika user eksplisit memilih mode vertikal.
   - Mode sumber: `manual_urls`, `stock_footage`, atau campuran.
   - Daftar URL sumber: tambah/hapus/urutkan.
   - Toggle provider stock footage: Pexels/Pixabay; tampilkan status API key dan `base_url` efektif.
   - Tombol analyze sources / find stock candidates.

2. **Source Review**
   - Tampilkan metadata, durasi, platform/provider, status subtitle/transcript untuk URL sources.
   - Untuk stock footage: tampilkan provider, query, kandidat, preview, license/attribution.
   - Centang sumber/kandidat yang dipakai.
   - Tampilkan estimasi biaya/waktu kasar bila memungkinkan.

3. **Outline Review**
   - Tampilkan outline JSON yang mudah dibaca.
   - Tombol regenerate outline.
   - Edit manual opsional untuk judul/logline/bab.

4. **Segment Plan Review**
   - Tampilkan segmen: judul, target durasi, narasi, visual intent, sumber kandidat.
   - Preview clip terpilih.
   - Replace/exclude segmen.

5. **Voice & Subtitle Settings**
   - TTS provider: `edge_tts` default; `chatterbox` disabled sampai provider tersedia.
   - Voice, speed, pitch.
   - Subtitle on/off, style, timing offset.
   - BGM URL/file opsional, volume.

6. **Render**
   - Progress per tahap dan per segmen.
   - Cancel/resume.
   - Buka folder output.

### 5.2 `documentary_engine.py`

Orkestrator utama dengan tahap:

1. `prepare_sources(urls)` — validasi URL, deteksi platform, ambil metadata ringan.
2. `download_sources(selected)` — download video/audio perlu saja via Clip Cutter/yt-dlp.
3. `transcribe_sources()` — extract audio + Whisper-compatible transcription.
4. `generate_outline()` — LLM outline dari brief + transcript ringkas + metadata.
5. `plan_segments()` — pecah outline menjadi segment plan.
6. `find_stock_candidates()` — untuk segmen yang butuh B-roll, generate query via LLM lalu call Pexels/Pixabay sesuai config.
7. `select_clips()` — pilih start/end dari transcript sources dan/atau stock candidates untuk tiap segmen.
8. `assemble_timeline()` — potong segmen, normalisasi 16:9, gabung draft per bab.
9. `generate_voice()` — TTS per segmen via adapter.
10. `align_subtitles()` — subtitle per segmen; fallback alignment bila TTS tidak memberi word timing.
11. `render_segments()` — burn subtitle/mix audio/BGM per segmen.
12. `concat_final()` — gabungkan bab menjadi video final.
13. `write_metadata()` — `session_data.json`, `manifest.json`, `data.json`.

Public callback yang disarankan:

- `log_callback(str)`
- `progress_callback(status: str, progress: float)`
- `step_callback(step_num: int, step_name: str, detail: str = "")`
- `cancel_check()` / `is_cancelled()`

### 5.3 `documentary_tts.py`

Adapter TTS untuk Documentary Studio.

MVP:
- `EdgeTTSAdapter` membungkus `EdgeTTSEngine`/`EdgeTTSManager`.
- Output minimal: `audio_path`, `duration`, `word_timings` bila ada.

Future:
- `ChatterboxTTSAdapter` memanggil server/model Chatterbox lokal.
- Kontrak output harus sama: `audio_path`, `duration`, opsional `word_timings`; jika tidak ada word timing, kembalikan `alignment_method="estimated"` atau `"whisper"`.

### 5.4 Reuse services

| Kebutuhan | Service existing | Catatan |
|---|---|---|
| Deteksi platform/download/cut | `clip_cutter_core.ClipCutterCore` | Untuk manual multi-platform sources. |
| Metadata/audio/transkripsi | `video_analyzer.VideoAnalyzer` | Pakai `caption_maker` untuk Whisper-compatible. |
| LLM outline/script | `script_generator.ScriptGenerator` | Prioritaskan `script_generator`/`highlight_finder` agar bisa diarahkan ke 9router. |
| TTS baseline | `edge_tts_engine` via adapter baru | Jangan ubah Edge engine existing. |
| Subtitle ASS | `caption_generator.CaptionGenerator` | Opsional untuk style konsisten. |
| FFmpeg helpers/progress | `utils.helpers`, `clip_dub_engine` sebagai referensi | Lebih baik buat helper render sendiri agar tidak tergantung state ClipDub. |
| GPU detection | `utils.gpu_detector.GPUDetector` | Untuk encoder recommendation. |

### 5.5 `documentary_stock.py`

Adapter stock footage untuk Documentary Studio.

MVP/opsional:
- `PexelsStockProvider` dan `PixabayStockProvider` (atau satu class `StockFootageProvider` dengan provider key).
- Fungsi minimal: `search(query, per_page, orientation, duration_hint)`, `download_asset(candidate)`, `normalize_candidate(raw)`.
- API key dibaca dari env/config (`PEXELS_API_KEY`, `PIXABAY_API_KEY`); jangan hardcode.
- `base_url` default ke endpoint resmi, tapi bisa dioverride lewat config untuk proxy/self-hosted mirror.
- Output kandidat minimal: `provider`, `id`, `title`, `duration`, `width`, `height`, `preview_url`, `download_url`, `license`, `attribution`, `source_page_url`, `query`, `score/reason`.
- LLM hanya membuat query dan ranking; adapter yang memanggil API resmi.

## 6. Config schema yang diusulkan

Tambahkan namespace `documentary` di `config.json` melalui `ConfigManager`, backward compatible:

```json
{
  "documentary": {
    "enabled": true,
    "default_aspect": "16:9",
    "default_duration_seconds": 300,
    "style": "documentary",
    "language": "id",
    "source_mode": "mixed",
    "stock_footage": {
      "enabled": true,
      "providers": {
        "pexels": {
          "enabled": true,
          "api_key_env": "PEXELS_API_KEY",
          "base_url": "https://api.pexels.com"
        },
        "pixabay": {
          "enabled": true,
          "api_key_env": "PIXABAY_API_KEY",
          "base_url": "https://pixabay.com/api"
        }
      },
      "search": {
        "per_segment_candidates": 5,
        "orientation": "landscape",
        "safe_search": true,
        "language": "en",
        "max_per_provider": 10
      },
      "license": {
        "require_attribution": true,
        "store_metadata": true
      }
    },
    "tts_provider": "edge_tts",
    "edge_tts": {
      "voice": "id-ID-ArdiNeural",
      "rate": "+0%",
      "pitch": "+0Hz"
    },
    "chatterbox": {
      "enabled": false,
      "endpoint": "http://localhost:5000",
      "voice_id": "default",
      "timeout_seconds": 120
    },
    "subtitle": {
      "enabled": true,
      "mode": "segment",
      "burn_in": true,
      "style": "documentary"
    },
    "bgm": {
      "enabled": false,
      "source": "",
      "volume": 0.15
    },
    "render": {
      "width": 1920,
      "height": 1080,
      "fps": 30,
      "video_bitrate": "8M",
      "segment_render": true,
      "keep_intermediates": false
    },
    "limits": {
      "max_sources": 8,
      "max_segments": 30,
      "max_source_duration_seconds": 7200
    }
  }
}
```

Catatan:
- `ai_providers` tetap dipakai bersama; Documentary Studio tidak membuat provider AI baru kecuali adapter TTS/stock footage.
- Untuk 9router, user mengisi `ai_providers.highlight_finder`/`script_generator` dengan `base_url=http://localhost:20128/v1` dan model chat yang sesuai.
- `caption_maker` harus tetap diarahkan ke Whisper-compatible endpoint, bukan 9router chat.
- API key stock footage dibaca dari env yang ditunjuk `api_key_env` (`PEXELS_API_KEY`, `PIXABAY_API_KEY`); jangan simpan key langsung di `config.json` atau log.
- `base_url` stock provider default ke endpoint resmi; override hanya untuk proxy/mirror yang user pahami risikonya. Adapter harus validasi scheme `https` kecuali `localhost`/testing.

## 7. Data model

### 7.1 Session folder

```text
output/documentaries/<session_id>/
  session_data.json
  sources/
    source_001.mp4
    source_001.id.srt / transcript.json
  plan/
    outline.json
    segment_plan.json
    stock_candidates.json
  clips/
    segment_001.mp4
    segment_001.voice.mp3
    segment_001.ass
  render/
    segment_001.final.mp4
    concat_list.txt
  final.mp4
  data.json
```

### 7.2 `session_data.json` minimal

```json
{
  "feature": "documentary_studio",
  "session_id": "20261112-153000-docu",
  "created_at": "ISO-8601",
  "status": "outline_ready|segment_plan_ready|rendering|completed|failed|cancelled",
  "brief": {},
  "sources": [],
  "outline": {},
  "segments": [],
  "render_manifest": {},
  "errors": []
}
```

### 7.3 Segment schema

```json
{
  "segment_id": "seg_001",
  "order": 1,
  "title": "Pembukaan",
  "narration_text": "Teks narasi...",
  "target_duration": 35,
  "visual_intent": "Close-up pemandangan dan grafik perbandingan",
  "source_requirements": ["explain", "comparison"],
  "selected_clips": [
    {
      "source_id": "src_001",
      "provider": "youtube|pexels|pixabay|local",
      "start": 12.5,
      "end": 28.0,
      "reason": "menjelaskan konteks",
      "query": "optional stock search query",
      "download_url": "optional direct asset url",
      "license": "optional license name",
      "attribution": "optional attribution text",
      "source_page_url": "optional provider page"
    }
  ],
  "voice": {"provider": "edge_tts", "voice": "id-ID-ArdiNeural"},
  "subtitle": {"enabled": true, "mode": "segment"},
  "render": {"output": "clips/segment_001.final.mp4", "status": "pending"}
}
```

## 8. Error handling & reliability

- Setiap tahap harus idempotent sebisa mungkin: jika artifact sudah ada dan valid, skip.
- `cancel` harus diperiksa sebelum dan sesudah operasi berat.
- FFmpeg gagal harus menangkap stderr tail, menandai segmen gagal, dan menawarkan retry segment-only.
- Provider AI gagal harus fallback ke provider berikutnya atau menampilkan error yang bisa ditindaklanjuti.
- Stock footage provider gagal/kehabisan quota harus menandai provider nonaktif untuk session, tetap melanjutkan dengan URL manual bila ada, dan menyimpan error non-secret.
- TTS gagal harus fallback ke provider lain bila dikonfigurasi; jika tidak, segment ditandai `tts_failed`.
- Render concat hanya boleh jalan jika semua `segment.final.mp4` valid.

## 9. Keamanan & privasi

- API key hanya dari `config.json`/`.env`; jangan log secret. Ini termasuk `PEXELS_API_KEY` dan `PIXABAY_API_KEY`.
- `cookies.txt` tetap lokal; jangan kirim ke pihak ketiga.
- Stock footage harus memakai API/provider adapter resmi; simpan license/attribution dan jangan scraping HTML bila API tersedia.
- `base_url` stock provider boleh dioverride hanya untuk proxy/mirror yang disengaja; default harus endpoint resmi dan scheme `https`.
- TTS lokal/Chatterbox tidak mengirim teks ke cloud kecuali provider yang memang cloud.
- Berikan disclaimer hak cipta di UI dan metadata output.
- Tidak ada upload/publish otomatis.

## 10. Strategi testing

- Unit test pure logic: parse brief, validasi URL, segment schema, aspect normalize decision, manifest writer.
- Unit test stock footage: query builder, provider adapter request shape, candidate normalization, license/attribution writer, base_url validation.
- Integration test ringan: satu sumber pendek → transcribe mock → outline mock → segment plan mock → stock candidates mock.
- Manual QA: video landscape, video portrait, video mixed aspect, multi-URL, stock footage on/off, missing API key, cancel mid-render, resume, provider failure.
- Regression QA: buka keenam mode existing dan pastikan navigasi masih normal.
