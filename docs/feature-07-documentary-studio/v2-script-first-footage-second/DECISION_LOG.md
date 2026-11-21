# Decision Log — Documentary Studio V2

## D-001 — Script-first pipeline
Date: 2026-11-13
Decision: Ubah logic utama Documentary Studio menjadi script-first → footage-second.
Reason: Alur lama source-first menghasilkan URL/kandidat terlalu dini dan berisiko memilih clip yang tidak relevan dengan narasi.
Impact: `documentary_engine.py`, `pages/documentary_page.py`, config `documentary`, docs V2.
Status: implemented-partial

## D-002 — LLM tidak output URL
Date: 2026-11-13
Decision: LLM hanya membuat script plan, `clip_context`, `footage_slots`, dan query; engine yang mencari kandidat URL/footage.
Reason: Mencegah halusinasi URL dan memastikan aset berasal dari search/API nyata.
Impact: prompt schema, footage plan, candidate retrieval.
Status: implemented-partial

## D-003 — Review gate wajib
Date: 2026-11-13
Decision: User harus review script plan dan footage plan sebelum download/render massal.
Reason: Mengurangi risiko download/render footage yang salah konteks dan boros resource.
Impact: UI review section, `selected_assets.json`, pipeline stages.
Status: implemented-partial — staged UI now has `Approve Footage`; rich per-candidate review UI still pending.

## D-004 — Context preservation protocol
Date: 2026-11-13
Decision: Semua pekerjaan V2 harus update `IMPLEMENTATION_STATE.md` dan `DECISION_LOG.md`; AI harus membaca docs/state sebelum lanjut.
Reason: Mencegah kehilangan arah saat konteks habis atau thread dilanjutkan.
Impact: dokumentasi dan workflow agent.
Status: accepted-ongoing

## D-005 — V2 config keys
Date: 2026-11-13
Decision: Tambahkan config `script_first`, `footage_density`, `coverage_model`, `duration_policy`, `review_gate`, dan asset budget per tipe aset.
Reason: Menjalankan audit V2: density dan budget harus beda per resource mode dan tipe aset, bukan satu global count.
Impact: `config/config_manager.py`, `documentary_engine.py`.
Status: implemented

## D-006 — Duration below planner minimum
Date: 2026-11-13
Decision: Input target <600 detik tidak lagi di-clamp paksa ke 600; `duration_policy.allow_below_min=true` mengizinkan durasi lebih pendek dengan planner min tetap sebagai default long-form.
Reason: Audit menemukan 9 menit tidak boleh berubah diam-diam menjadi 10 menit.
Impact: `_planned_duration_seconds()`.
Status: implemented

## D-007 — Deterministic fallback script plan
Date: 2026-11-13
Decision: Jika LLM gagal total dan `script_first.fallback_enabled=true`, engine membuat fallback chapter/segment plan dengan `script_source="fallback"` dan `needs_review=true`.
Reason: Pipeline tidak boleh crash irrecoverably saat 9router/provider down.
Impact: `_fallback_script_plan()`, `generate_script_plan()`.
Status: implemented

## D-008 — Footage slots preserved through normalization
Date: 2026-11-13
Decision: `_normalize_segments()` menyimpan `footage_slots`; `_finalize_script_segments()` menormalkan slot menjadi `slot_id`, query ID/EN, `needed_seconds`, `platform_priority`, candidates, selected, dan review status.
Reason: LLM-provided footage ideas harus sampai ke footage search, bukan hilang saat segment dinormalisasi.
Impact: `_normalize_segments()`, `_normalize_footage_slots()`.
Status: implemented

## D-009 — Slot-level approve MVP
Date: 2026-11-13
Decision: `approve_footage_plan()` memilih kandidat terbaik per `footage_slot` berdasarkan score dan source policy, menulis `selected_assets.json`, dan menandai segmen tanpa kandidat sebagai `needs_manual_asset`.
Reason: Review gate MVP harus sederhana dan tidak membuat UI terlalu berat; per-candidate replace UI bisa fase berikutnya.
Impact: `approve_footage_plan()`, `selected_assets.json`, UI button `Approve Footage`.
Status: implemented-partial

## D-010 — Run-full auto-approve logged
Date: 2026-11-13
Decision: `run_full_pipeline()` tetap one-click dan auto-approve footage plan setelah `build_footage_plan()`, tetapi log memperingatkan bahwa review manual sebaiknya lewat pipeline bertahap.
Reason: Menjaga UX one-click sambil mempertahankan staged review path.
Impact: `run_full_pipeline()`, `review_gate.auto_approve_run_full` config key.
Status: implemented

## D-011 — Editable script plan + session persistence
Date: 2026-11-13
Decision: Tambahkan Script Editor UI untuk edit judul/narasi per segmen, simpan ke `script_plan.json`/`segment_plan.json`, dan sinkronkan `outline`/`segments`/`script_plan` di session data.
Reason: User harus bisa merevisi narasi TTS sebelum footage approve/render; Load Session harus mengembalikan segmen yang bisa diedit, bukan outline lama.
Impact: `pages/documentary_page.py`, `documentary_engine.py` persistence di `generate_script_plan()`, `build_footage_plan()`, `approve_footage_plan()`.
Status: implemented

## D-012 — UI flow reorder script-first
Date: 2026-11-13
Decision: Susun ulang UI menjadi `AI/LLM → Konteks+Generate Script → Script Editor → Footage & Source Search/Preview → Approve & Render → Review`.
Reason: User feedback: urutan lama terasa acak; flow harus jelas konteks → script → footage/search → preview thumbnail → render.
Impact: `pages/documentary_page.py` section order, button labels, `Generate Script`, `Build Footage Plan`, `Footage Preview`.
Status: implemented

## D-013 — Manual candidate selection respected
Date: 2026-11-13
Decision: Preview footage menampilkan thumbnail/kandidat per slot dengan tombol `Pilih`; pilihan user disimpan sebagai `selected_candidate_id` dan dipakai `approve_footage_plan()` sebelum fallback ke score tertinggi.
Reason: User harus bisa memilih footage berdasarkan preview, bukan hanya score otomatis.
Impact: `_render_footage_preview()`, `_select_candidate_for_slot()`, `approve_footage_plan()`.
Status: implemented
