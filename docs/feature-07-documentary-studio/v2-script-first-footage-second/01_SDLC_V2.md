# SDLC Plan V2 — Documentary Studio Script-First / Footage-Second

## 1. Pendekatan

V2 adalah **refactor logic pipeline**, bukan rewrite total. Pertahankan engine/session/render/TTS yang sudah ada, tetapi ubah urutan dan artifact plan.

Prinsip:

- Script plan menjadi source of truth naratif.
- Footage plan menjadi source of truth aset visual.
- Setiap tahap menghasilkan artifact JSON yang bisa di-resume.
- User review sebelum download/render massal.
- Resource mode dan budget wajib dihormati.

## 2. Fase pengerjaan

### Fase V2-0 — Freeze context & docs

Tujuan: AI/dev punya arah yang sama sebelum coding.

Task:
- Baca folder ini: `README.md`, `00_PRD_V2.md`, `01_SDLC_V2.md`, `02_GUARDRAILS_V2.md`, `03_CONTEXT_PRESERVATION.md`.
- Baca docs V1 yang relevan dan file implementasi saat ini.
- Buat `IMPLEMENTATION_STATE.md` di folder ini saat mulai coding.
- Jangan mengubah kode production sebelum state/docs jelas.

Exit criteria:
- Ada keputusan tertulis: script-first, footage-second, LLM no URL, review gate wajib.

### Fase V2-1 — Schema & session artifacts

Tujuan: artifact plan baru punya struktur stabil.

Task:
- Definisikan schema `script_plan.json`, `footage_plan.json`, `verification.json`, `selected_assets.json`.
- Tambah helper `_write_json/_read_json` yang sudah ada untuk artifact baru.
- Update `session_data.json` status transitions untuk tahap V2.
- Tambah config keys: `script_first`, `footage_slots`, `review_gate`, perluasan `asset_budget`.

Exit criteria:
- Engine bisa menulis/membaca artifact plan tanpa crash.
- Config lama tetap load; key baru backward compatible.

### Fase V2-2 — Script plan generator

Tujuan: brief + durasi → script plan tanpa mencari URL.

Task:
- Ubah/tambah `generate_script_plan()` terpisah dari `generate_outline()` lama.
- Prompt LLM meminta JSON dengan `planned_start_sec`, `planned_end_sec`, `narration_text`, `clip_context`, `footage_slots`.
- Normalisasi time range dan durasi segmen.
- Hitung `duration_plan`, `segment_count`, `broll_need_seconds`, `source_mix`.
- Cache LLM response per session.

Exit criteria:
- Brief dummy menghasilkan script plan valid.
- Total durasi mendekati target; segmen tidak melebihi `segment_max_seconds`.
- Tidak ada URL di output LLM.

### Fase V2-3 — Footage slot expander & search planner

Tujuan: setiap footage idea menjadi slot pencarian yang bisa dieksekusi engine.

Task:
- Normalisasi `footage_slots`: `slot_id`, `segment_id`, `idea`, `query_en`, `query_id`, `needed_seconds`, `shot_type`, `platform_priority`, `avoid`.
- Batasi jumlah slot per segmen sesuai budget.
- Generate query deterministik/fallback jika LLM gagal.
- Pisahkan `context_need` opsional untuk backbone/manual sources.

Exit criteria:
- Setiap segmen punya footage slots yang jelas.
- Query spesifik visual, bukan keyword topik umum.
- Budget `max_footage_slots_per_segment` dan `max_queries_per_slot` diterapkan.

### Fase V2-4 — Footage candidate retrieval per slot

Tujuan: cari kandidat per slot, sequential dan hemat resource.

Task:
- Stock footage: query Pexels/Pixabay per slot dengan `max_candidates_per_slot`.
- Backbone/manual sources: opsional, terpisah dari footage B-roll.
- Browser/social discovery: hanya untuk texture, hormati budget dan platform policy.
- Normalisasi kandidat: `url`, `provider`, `platform`, `duration`, `title`, `channel`, `license_signal`, `thumbnail`, `description/tags`, `subtitle_available`.
- Dedupe by URL/provider+id.

Exit criteria:
- Satu slot menghasilkan kandidat tanpa banjir URL global.
- Kandidat membawa `slot_id` dan `segment_id`.
- Tidak ada download massal di tahap ini.

### Fase V2-5 — Verification & scoring

Tujuan: pilih berdasarkan bukti, bukan judul.

Task:
- Implement verification ladder L0–L3.
- Untuk stock: metadata/tags/provider license + optional preview/frame.
- Untuk YouTube/backbone: transcript/description/channel policy.
- Untuk social: durasi cap 5–15 detik untuk B-roll.
- Scoring: `narrative_fit`, `content_evidence`, `visual_quality`, `license_safety`, `duration_fit`, `diversity`, `policy_penalty`.
- Simpan `evidence`, `confidence`, `warnings`.

Exit criteria:
- Tidak ada kandidat `selected` hanya dari judul.
- Kandidat lemah menjadi `unverified`/`rejected` dengan alasan.
- Policy warning tampil di review.

### Fase V2-6 — Review gate UI

Tujuan: user approve sebelum download/render.

Task:
- Tambah section review script plan + footage plan di `pages/documentary_page.py`.
- Tampilkan per segmen: time range, narasi ringkas, footage slots, kandidat, status, warnings.
- Tombol approve/reject per slot atau per segmen.
- Simpan `selected_assets.json`.

Exit criteria:
- User bisa melihat rencana sebelum aset berat di-download.
- Hanya approved assets yang materialize.

### Fase V2-7 — Materialize, voice, render integration

Tujuan: pakai footage plan yang sudah approved ke pipeline existing.

Task:
- Ubah `select_clips()` agar membaca `footage_plan.selected`, bukan memilih langsung dari kandidat mentah.
- `assemble_segment_video()` memakai clip per slot dengan `needed_seconds` dan `actual_time_range`.
- Setelah TTS, hitung `actual_time_range` dan adjust clip duration bila perlu.
- Pertahankan render per segmen, subtitle/BGM, concat, metadata.

Exit criteria:
- Segment render memakai footage yang approved.
- Clip duration menyesuaikan durasi voiceover aktual.
- Resume per segment tetap jalan.

### Fase V2-8 — Acceptance & regression

Tujuan: pastikan V2 tidak merusak existing.

Task:
- Compile/import smoke.
- Unit/smoke untuk schema normalization, time range, scoring, budget.
- Synthetic render kecil untuk 1–2 segmen.
- Regression manual 6 mode lama.
- Update docs status.

Exit criteria:
- Acceptance criteria V2 lulus.
- 6 mode lama tetap berfungsi.

## 3. Migrasi dari V1

- `generate_outline()` lama boleh tetap ada untuk kompatibilitas, tetapi flow utama V2 memakai `generate_script_plan()`.
- `discover_sources()` tidak lagi menjadi tahap utama; menjadi helper opsional untuk backbone/manual sources.
- `select_clips()` V1 tetap ada, tetapi V2 sebaiknya memakai `select_footage_from_plan()`.
- Config V1 tetap dibaca; key V2 additive.

## 4. Definition of Done V2

- Script plan dan footage plan tersimpan per session.
- Review gate ada dan wajib sebelum materialize massal.
- Tidak ada auto-select berbasis judul.
- Budget/resource mode dihormati.
- Render economy/balanced/quality bekerja.
- Docs dan `IMPLEMENTATION_STATE.md` diperbarui.
