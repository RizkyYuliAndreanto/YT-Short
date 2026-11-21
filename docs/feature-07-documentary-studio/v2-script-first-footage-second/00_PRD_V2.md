# PRD V2 — Documentary Studio Script-First / Footage-Second

## 1. Ringkasan

Documentary Studio V2 mengubah urutan produksi:

- ** Lama**: input topik → cari URL/sumber → download/transcribe → outline → pilih clip.
- **V2**: input topik + durasi → LLM membuat script plan + footage plan → engine mencari footage per slot → verifikasi → user review → download/render.

Tujuannya agar footage yang dipakai benar-benar relevan dengan **peran naratif segmen**, bukan sekadar mirip judul/topik.

## 2. Problem statement

- AI bisa mengembalikan banyak URL tanpa memastikan isi video cocok.
- Judul/thumbnail sering menyesatkan; konten bisa clickbait atau off-topic.
- Clip sosial/media bisa terpilih padahal hanya cocok secara visual sesaat.
- User tidak punya checkpoint yang jelas sebelum aset di-download/render.
- Untuk target YouTube 10–30 menit, discovery/download terlalu dini membuang resource laptop.

## 3. Goals

1. Script plan dibuat lebih dulu dari brief + durasi target.
2. Setiap segmen punya `planned_time_range`, `narration_text`, `clip_context`, dan `footage_slots`.
3. Footage dicari per slot dengan query spesifik, bukan per topik secara umum.
4. Kandidat wajib diverifikasi lewat metadata/transcript/description/preview sebelum dipilih.
5. User bisa review script + footage plan sebelum download/render.
6. Pipeline tetap staged, resumable, dan hemat resource.
7. Fitur tetap standalone; 6 mode lama tidak berubah.

## 4. Non-goals

- Tidak auto-publish/upload.
- Tidak mengubah flow 6 mode existing.
- Tidak menjadikan LLM sebagai verifier isi video; LLM hanya membuat query/konteks.
- Tidak scraping platform untuk download; tetap pakai yt-dlp/API resmi/adapter yang sudah ada.
- Tidak menghapus source policy V1; justru diperketat untuk footage slots.

## 5. User stories

### US-V2-01 — Script dulu baru footage

Sebagai kreator, saya ingin setelah mengisi topik dan durasi, AI langsung menghasilkan rancangan video: segmen, detik berapa sampai berapa, narasi, dan footage yang dibutuhkan.

Acceptance:
- Output berisi `segment_plan` dengan `planned_start_sec`, `planned_end_sec`, `narration_text`, `clip_context`, `footage_slots`.
- Tidak ada URL final dari LLM.
- Total durasi mendekati target user.

### US-V2-02 — Footage per slot

Sebagai kreator, saya ingin setiap ide footage dicari terpisah, misal “orang berangkat kerja”, “desak-desakan di kereta”, “tagihan masuk”, “scroll marketplace”.

Acceptance:
- Satu `footage_slot` menghasilkan beberapa kandidat terverifikasi.
- Kandidat punya `slot_id`, `segment_id`, `query`, `provider`, `score`, `status`, `evidence`, `warnings`.
- Maksimal budget per slot dihormati.

### US-V2-03 — Review sebelum download

Sebagai editor, saya ingin melihat script dan footage plan sebelum sistem download/render.

Acceptance:
- Ada review gate untuk script plan dan footage plan.
- User bisa approve/reject kandidat per slot.
- Hanya kandidat approved yang materialize/download.

### US-V2-04 — Hemat resource untuk video panjang

Sebagai user laptop terbatas, saya ingin proses 10–30 menit berjalan bertahap dan bisa resume.

Acceptance:
- `resource_mode=economy` default untuk laptop terbatas.
- Render per segmen, concat di akhir.
- Budget pencarian/download dibatasi.
- Checkpoint per tahap; gagal di segmen X tidak mengulang semua.

## 6. Functional requirements

### FR-V2-01 Duration planner

- Input durasi user authoritative dalam rentang yang dikonfigurasi.
- Default target: 900 detik.
- Range yang didukung: minimal 300 detik, ideal 600–1800 detik.
- Jika user input <600 detik, tampilkan warning “di bawah target YouTube long-form” tetapi tetap bisa jalan.
- `duration_planner` menghitung `segment_count`, `avg_segment_seconds`, `broll_need_seconds`, dan `source_mix`.

### FR-V2-02 Script plan schema

`plan/script_plan.json` minimal berisi:

```json
{
  "title": "...",
  "logline": "...",
  "target_duration_seconds": 900,
  "duration_plan": {},
  "segments": [
    {
      "segment_id": "seg_001",
      "order": 1,
      "planned_start_sec": 0,
      "planned_end_sec": 75,
      "title": "...",
      "narration_text": "...",
      "clip_context": {
        "narrative_role": "problem_setup",
        "viewer_should_feel": "tekanan",
        "setting": "urban",
        "time_of_day": "morning_night",
        "shot_types": ["wide", "medium"],
        "avoid": ["unrelated"],
        "sensitivity": ["no_brand_focus"]
      },
      "footage_slots": [
        {
          "slot_id": "seg_001_f1",
          "idea": "orang berangkat kerja pagi",
          "search_query_en": "people commuting to work morning city",
          "search_query_id": "orang berangkat kerja pagi kota",
          "needed_seconds": 8,
          "shot_type": "wide",
          "platform_priority": ["pexels", "pixabay", "youtube", "facebook"]
        }
      ]
    }
  ]
}
```

### FR-V2-03 Footage plan schema

`plan/footage_plan.json` minimal berisi:

```json
{
  "segment_id": "seg_001",
  "planned_time_range": {"start": 0, "end": 75},
  "slots": [
    {
      "slot_id": "seg_001_f1",
      "idea": "orang berangkat kerja pagi",
      "needed_seconds": 8,
      "candidates": [
        {
          "url": "...",
          "provider": "pexels",
          "score": 82,
          "status": "selected",
          "evidence": "tags/description cocok dengan commute/work",
          "warnings": []
        }
      ],
      "selected": null,
      "review_required": true
    }
  ]
}
```

### FR-V2-04 Verification ladder

Setiap kandidat footage melewati:

- `L0 metadata`: URL valid, platform dikenali, bukan halaman non-media.
- `L1 content_hint`: description/tags/transcript snippet mendukung konteks slot.
- `L2 visual/context check`: preview frame/scene/manual review.
- `L3 selected`: lolos policy + scoring + review user.

Aturan:
- Judul tidak pernah cukup untuk `selected`.
- Kalau transcript/evidence lemah → `unverified`, bukan auto-select.
- Stock footage boleh `metadata_ok` tetapi tetap `visual_unverified` sampai review/vision check.

### FR-V2-05 Selection & diversity

- Pilih maksimal 1–3 clip per `footage_slot`.
- Utamakan variasi shot type dan platform.
- Batasi social B-roll sesuai policy V1.
- Hindari channel/platform sama berulang dalam satu segmen.
- Kalau tidak ada kandidat verified → `needs_manual_asset` atau fallback stock generik, bukan mengarang URL.

### FR-V2-06 Review gate

Sebelum materialize/download massal:

- Tampilkan script plan ringkas.
- Tampilkan footage slots + kandidat + status + evidence + warnings.
- User approve/reject per slot/segmen.
- Hanya approved yang masuk `selected_assets.json`.

### FR-V2-07 Resource budgets

Config `documentary.asset_budget` dan `documentary.resource_mode`:

- `max_footage_slots_per_segment`
- `max_queries_per_slot`
- `max_candidates_per_slot`
- `max_downloads_per_run`
- `max_browser_queries_per_run`
- `max_social_clips_total`
- `max_backbone_sources`

Mode:
- `economy`: default laptop terbatas.
- `balanced`.
- `quality`.

### FR-V2-08 Pipeline stages

Urutan V2:

1. `brief_session`
2. `script_plan`
3. `footage_plan`
4. `review_gate`
5. `asset_materialize`
6. `voice_subtitle`
7. `render_segments`
8. `concat_metadata`

Tahap lama `prepare_sources/download_transcribe` hanya untuk backbone/manual sources opsional, bukan wajib untuk stock footage.

## 7. Acceptance metrics

- Script plan valid JSON untuk brief dummy.
- Footage plan berisi slot per segmen dan tidak ada URL dari LLM.
- Kandidat tidak auto-selected tanpa evidence.
- User bisa review sebelum download.
- Render economy tetap 720p/veryfast/stream-copy concat.
- Regression: 6 mode lama tidak berubah.
