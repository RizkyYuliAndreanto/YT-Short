# Task Breakdown — Documentary Studio (Feature 07)

Task di bawah disusun agar bisa dieksekusi AI agent secara bertahap. Setiap task punya ID, file target, dependency, dan acceptance check. Jangan mulai task lanjutan sebelum dependency selesai.

## Grup A — Fondasi

| ID | Task | File target | Dependency | Acceptance |
|---|---|---|---|---|
| DOC-001 | Baca docs fitur & petakan reuse | `docs/feature-07-documentary-studio/*` | - | Agent bisa menyebut engine reuse tanpa mengubah fitur lama. |
| DOC-002 | Tambah default config `documentary` | `config/config_manager.py` | DOC-001 | Config lama load normal; `config["documentary"]` muncul dengan default SRS. |
| DOC-003 | Buat engine skeleton + session manager | `documentary_engine.py` | DOC-002 | Bisa create `output/documentaries/<session>/`, tulis `session_data.json`, status transitions. |
| DOC-004 | Implement callback interface | `documentary_engine.py` | DOC-003 | `log_callback`, `progress_callback`, `step_callback`, cancel check tersedia. |
| DOC-005 | Implement pure helpers: schema/manifest | `documentary_engine.py` atau `documentary_utils.py` | DOC-003 | Segment/outline/sources tervalidasi; manifest bisa ditulis. |

## Grup B — Source & transcript

| ID | Task | File target | Dependency | Acceptance |
|---|---|---|---|---|
| DOC-010 | Implement `prepare_sources()` | `documentary_engine.py` | DOC-004 | Multi-URL divalidasi; platform terdeteksi; metadata ringan tersimpan. |
| DOC-011 | Implement source screening UI-data | `documentary_engine.py` | DOC-010 | Metadata/subtitle availability bisa ditampilkan ke UI nanti. |
| DOC-012 | Implement download selected sources | `documentary_engine.py`, reuse `clip_cutter_core.py` | DOC-010 | Source tersimpan di session `sources/`; cancel bekerja. |
| DOC-013 | Implement extract audio + transcribe | `documentary_engine.py`, reuse `video_analyzer.py` | DOC-012 | Transcript per sumber tersimpan; provider `caption_maker` dipakai. |
| DOC-014 | Simpan transcript artifacts | `documentary_engine.py` | DOC-013 | `sources/source_xxx.transcript.json` dan/atau `.srt` ada. |

## Grup C — AI outline & plan

| ID | Task | File target | Dependency | Acceptance |
|---|---|---|---|---|
| DOC-020 | Implement provider resolver LLM | `documentary_engine.py` | DOC-002 | Prioritas `script_generator` → `highlight_finder` → fallback existing; 9router bisa dipakai. |
| DOC-021 | Implement `generate_outline()` | `documentary_engine.py` | DOC-014, DOC-020 | Brief + transcript ringkas → `plan/outline.json` valid. |
| DOC-022 | Implement JSON repair/validation | `documentary_engine.py` | DOC-021 | Response LLM kotor tetap diparse atau retry; error jelas jika gagal. |
| DOC-023 | Implement `plan_segments()` | `documentary_engine.py` | DOC-021 | `plan/segment_plan.json` sesuai schema SRS. |
| DOC-024 | Implement review data untuk UI | `documentary_engine.py` | DOC-023 | UI bisa membaca outline/segments/sources tanpa logika berat. |

## Grup D — Clip selection & assembly 16:9

| ID | Task | File target | Dependency | Acceptance |
|---|---|---|---|---|
| DOC-030 | Implement `select_clips()` | `documentary_engine.py` | DOC-023 | Tiap segmen punya selected clips + reason + start/end. |
| DOC-031 | Implement cut segment clips | `documentary_engine.py`, reuse FFmpeg/ClipCutter | DOC-030 | Clip mentah per segmen tersimpan. |
| DOC-032 | Implement normalize 16:9 | `documentary_engine.py` | DOC-031 | Output 1920×1080; portrait/mixed aspect di-handle pad/blur/fit. |
| DOC-033 | Implement draft assembly per bab | `documentary_engine.py` | DOC-032 | Draft bab playable; transition opsional. |
| DOC-034 | Simpan clip review metadata | `documentary_engine.py` | DOC-030 | UI bisa preview clip terpilih dan alasan pemilihan. |
| DOC-035 | Buat stock footage config/provider resolver | `documentary_stock.py`, `config/config_manager.py` | DOC-002 | `PEXELS_API_KEY`/`PIXABAY_API_KEY` via env; `base_url` default resmi + override aman. |
| DOC-036 | Implement Pexels/Pixabay search adapters | `documentary_stock.py` | DOC-035 | Search request shape benar; kandidat dinormalisasi; error quota/rate limit jelas. |
| DOC-037 | Implement LLM query generation per segmen | `documentary_engine.py` | DOC-023, DOC-036 | `visual_intent`/narasi → query stock yang masuk akal; output `plan/stock_candidates.json`. |
| DOC-038 | Implement ranking/fusion stock vs transcript clips | `documentary_engine.py` | DOC-030, DOC-037 | `select_clips()` bisa memilih stock candidate dengan reason; manual URL tetap prioritas bila lebih relevan. |
| DOC-039 | Download stock assets + license metadata | `documentary_engine.py`, `documentary_stock.py` | DOC-036, DOC-038 | Aset stock tersimpan; `license`/`attribution`/`source_page_url` masuk manifest. |

## Grup E — TTS, subtitle, BGM

| ID | Task | File target | Dependency | Acceptance |
|---|---|---|---|---|
| DOC-040 | Buat `documentary_tts.py` adapter | `documentary_tts.py` | DOC-002 | Edge TTS generate audio per segmen; return path/duration/word_timings. |
| DOC-041 | Integrate TTS ke engine | `documentary_engine.py` | DOC-040, DOC-033 | `segment_xxx.voice.mp3` dibuat; duration tercatat. |
| DOC-042 | Implement subtitle per segmen | `documentary_engine.py`, reuse `caption_generator.py` | DOC-041 | `.ass`/subtitle per segmen; fallback estimated alignment jika perlu. |
| DOC-043 | Implement BGM opsional | `documentary_engine.py`, reuse `tts_sync.py` ideas | DOC-041 | BGM URL/file bisa dimix dengan volume config. |
| DOC-044 | Implement audio mix per segmen | `documentary_engine.py` | DOC-041, DOC-043 | Voice + ambience/BGM per segmen tidak clipping parah. |

## Grup F — Render, resume, metadata

| ID | Task | File target | Dependency | Acceptance |
|---|---|---|---|---|
| DOC-050 | Implement render per segmen | `documentary_engine.py` | DOC-042, DOC-044 | `render/segment_xxx.final.mp4` valid 1920×1080. |
| DOC-051 | Implement render manifest & resume | `documentary_engine.py` | DOC-050 | Segmen valid di-skip; segmen gagal bisa retry. |
| DOC-052 | Implement concat final | `documentary_engine.py` | DOC-051 | Semua segmen valid → `final.mp4`. |
| DOC-053 | Implement metadata output | `documentary_engine.py` | DOC-052 | `data.json`/manifest berisi sources, segments, duration, status. |
| DOC-054 | Implement open output helper | `pages/documentary_page.py` nanti | DOC-052 | User bisa buka folder session/output. |

## Grup G — UI & navigasi

| ID | Task | File target | Dependency | Acceptance |
|---|---|---|---|---|
| DOC-060 | Buat `pages/documentary_page.py` shell | `pages/documentary_page.py` | DOC-003 | Halaman wizard muncul tanpa crash. |
| DOC-061 | Implement Brief & Sources UI | `pages/documentary_page.py` | DOC-010, DOC-024 | User input brief + URL list; analyze button memanggil engine. |
| DOC-062 | Implement Source/Outline/Segment review UI | `pages/documentary_page.py` | DOC-024 | User bisa review sebelum render. |
| DOC-063 | Implement Voice/Subtitle/BGM settings UI | `pages/documentary_page.py` | DOC-040 | Provider/voice/subtitle/BGM settings tersimpan ke config/session. |
| DOC-064 | Implement Render progress/cancel/resume UI | `pages/documentary_page.py` | DOC-050 | Progress per tahap/segmen; cancel bekerja; resume ditawarkan. |
| DOC-065 | Register page di `app.py` | `app.py` | DOC-060 | `self.pages["documentary"]` ada; `show_page("documentary")` bekerja. |
| DOC-066 | Tambah kartu mode ke-7 di landing | `pages/landing_page_v2.py` | DOC-065 | Kartu Documentary Studio muncul; layout 7 kartu rapi; mode lama tetap jalan. |

## Grup H — Hardening & lanjutan

| ID | Task | File target | Dependency | Acceptance |
|---|---|---|---|---|
| DOC-070 | Tambah unit tests pure logic | `tests/test_documentary_engine.py` | DOC-005, DOC-023 | Test schema/manifest/provider mapping lulus. |
| DOC-071 | Regression check 6 mode | manual/`app.py` | DOC-066 | Semua mode existing masih bisa dibuka/dijalankan normal. |
| DOC-072 | Dokumentasi user singkat | `GUIDE.md`/`PANDUAN.md` opsional | DOC-071 | Cara pakai Documentary Studio terdokumentasi. |
| DOC-073 | Opsional auto-search video panjang YouTube | `documentary_engine.py` | DOC-012 | `ytsearch`/YouTube Data API suggestion bekerja terbatas; stock footage Pexels/Pixabay tetap di Grup D. |
| DOC-074 | Chatterbox TTS provider | `documentary_tts.py` | model/server ready | Chatterbox generate audio per segmen dengan fallback alignment. |

## Aturan eksekusi task

- Jangan mengerjakan task UI sebelum engine punya data yang bisa ditampilkan.
- Jangan mengubah perilaku task existing; jika terpaksa, hentikan dan tanya.
- Setiap task berat harus punya progress + cancel.
- Semua artifact session harus berada di bawah `output/documentaries/` kecuali config global.
