# Guardrails V2 — Documentary Studio Script-First / Footage-Second

Dokumen ini aturan wajib saat mengimplementasikan V2. Tujuannya agar AI tidak kehilangan arah, tidak kembali ke logic lama, dan tidak mengorbankan resource.

## 1. Non-negotiables

1. **Script-first**: topik + durasi harus menghasilkan script plan sebelum footage dicari.
2. **Footage-second**: footage dicari per `footage_slot`, bukan per topik secara umum.
3. **LLM tidak output URL**: LLM hanya membuat narasi, `clip_context`, `footage_slots`, query, dan kriteria. Engine yang mencari kandidat.
4. **Judul bukan bukti**: judul/thumbnail hanya untuk recall; seleksi wajib pakai transcript/description/tags/preview/review.
5. **Review gate wajib**: tidak ada download/render massal sebelum user approve footage plan.
6. **Resource-aware**: semua discovery/download/render harus sequential, budgeted, checkpointed, dan cancellable.
7. **Standalone**: jangan mengubah behavior 6 mode existing.
8. **Secrets aman**: API key/env tidak masuk prompt, log, UI, atau repo.
9. **Source policy V1 tetap berlaku**: social B-roll 5–15 detik, hindari channel narasi dokumenter sebagai backbone, utamakan open-access/archive/stock.
10. **Dokumentasi state wajib**: setiap milestone update `IMPLEMENTATION_STATE.md` dan artifact plan.

## 2. Aturan logic yang dilarang

- Jangan kembali ke `discover_sources()` sebagai tahap utama yang menghasilkan URL lalu berharap clip cocok.
- Jangan auto-pilih footage hanya karena judul mengandung kata kunci topik.
- Jangan memakai social clip sebagai backbone atau lebih dari batas durasi policy.
- Jangan download semua kandidat; download hanya `selected/approved`.
- Jangan render sebelum `footage_plan` dan `script_plan` tervalidasi.
- Jangan menebak URL/ID footage; semua URL harus dari search/API nyata.
- Jangan mengubah durasi segmen menjadi > `segment_max_seconds` hanya untuk mengejar target total.
- Jangan menjalankan beberapa LLM/download/render berat paralel untuk mode `economy`.

## 3. Aturan schema

- `script_plan.json` harus punya `segments[].planned_start_sec`, `planned_end_sec`, `narration_text`, `clip_context`, `footage_slots`.
- `footage_plan.json` harus punya `slots[].slot_id`, `segment_id`, `idea`, `needed_seconds`, `candidates`, `selected`, `review_required`.
- Setiap kandidat wajib punya `status`, `score`, `evidence`, `warnings`, `source_policy`.
- Setiap slot wajib punya `query_en` dan/atau `query_id`, `platform_priority`, `shot_type`, `avoid`.
- Jika field wajib hilang, engine harus repair ringan atau mark plan `needs_review`, bukan crash.

## 4. Aturan LLM/provider

- LLM task untuk script plan: task `script_plan` atau `outline` dengan provider chain existing.
- LLM task untuk footage query: task `footage_queries`/`stock_queries` dengan output JSON valid.
- LLM harus diminta output JSON saja; repair JSON ringan maksimal 1–2 retry.
- Cache semua response LLM per session; jangan generate ulang script/footage plan saat resume.
- Hormati `llm_gateway` timeout/backoff/cooldown; jangan spam provider gratis.

## 5. Aturan search & selection

- Query harus visual dan spesifik: shot, setting, action, mood.
- Hindari query yang hanya berisi nama topik.
- Untuk tiap slot, ambil kandidat terbatas lalu verifikasi.
- Skor minimal mempertimbangkan: `narrative_fit`, `content_evidence`, `visual_quality`, `license_safety`, `duration_fit`, `diversity`, `policy_penalty`.
- Ambang yang disarankan: `>=70` shortlist, `50–69` review manual, `<50` reject.
- Kalau evidence lemah → `unverified`, bukan `selected`.

## 6. Aturan UI

- Section review harus menampilkan script plan dan footage plan sebelum pipeline render.
- Progress harus per tahap V2: script plan → footage plan → review → materialize → voice → render → concat.
- Cancel harus aman dan session bisa resume dari artifact terakhir.
- Jangan tampilkan API key; tampilkan provider/model/status saja.

## 7. Aturan resource

- `resource_mode=economy` default: sequential, budget kecil, render 720p/veryfast.
- Budget harus dibaca dari `documentary.asset_budget`; jangan hardcode angka besar.
- Sebelum render, cek disk free dan estimasi ukuran; blokir jika di bawah threshold.
- Render per segmen; concat stream-copy untuk economy/balanced bila codec seragam.
- Hapus temp/preview hanya jika tidak dibutuhkan resume.

## 8. Verifikasi minimum sebelum klaim selesai

```bash
python -m py_compile documentary_engine.py documentary_stock.py documentary_tts.py pages/documentary_page.py config/config_manager.py app.py pages/landing_page_v2.py
```

Smoke wajib:
- import `documentary_engine`, `pages.documentary_page`, `config.config_manager`.
- schema normalization untuk `script_plan` dan `footage_plan`.
- time range normalization total ≈ target durasi.
- scoring menolak kandidat tanpa evidence.
- budget membatasi slot/query/kandidat.
- render economy menghasilkan profile 720p/veryfast/stream-copy.

## 9. Jika ragu

- Kalau requirement ambigu, pilih opsi paling konservatif: lebih sedikit download, lebih banyak review, jangan auto-select.
- Kalau konteks hampir habis, update `IMPLEMENTATION_STATE.md` dan `DECISION_LOG.md` sebelum lanjut.
- Jangan melanjutkan coding besar tanpa membaca ulang docs V2 dan state terbaru.
