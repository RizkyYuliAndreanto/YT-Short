# Context Preservation — Documentary Studio V2

Dokumen ini khusus untuk mencegah AI kehilangan arah saat konteks habis, thread dipotong, atau sesi dilanjutkan nanti.

## 1. Source of truth

Urutan prioritas jika ada konflik:

1. Instruksi terbaru dari user.
2. Docs V2 di folder ini.
3. Docs V1 Feature 07.
4. Kode implementasi saat ini.
5. Asumsi agent — hanya jika tidak bertentangan dan harus didokumentasikan.

Jangan pernah menganggap memori percakapan sebagai satu-satunya sumber kebenaran.

## 2. Wajib dibaca sebelum coding V2

Agent harus membaca secara berurutan:

1. `docs/feature-07-documentary-studio/v2-script-first-footage-second/README.md`
2. `00_PRD_V2.md`
3. `01_SDLC_V2.md`
4. `02_GUARDRAILS_V2.md`
5. `03_CONTEXT_PRESERVATION.md`
6. `IMPLEMENTATION_STATE.md` jika sudah ada
7. `DECISION_LOG.md` jika sudah ada
8. Docs V1 yang relevan: `00_PRD.md`, `04_AI_AGENT_GUARDRAILS.md`, `05_ACCEPTANCE_CRITERIA.md`

## 3. Artifact yang harus dibuat/diupdate saat implementasi

Di repo/docs:

- `docs/feature-07-documentary-studio/v2-script-first-footage-second/IMPLEMENTATION_STATE.md`
- `docs/feature-07-documentary-studio/v2-script-first-footage-second/DECISION_LOG.md`

Di session output:

- `output/documentaries/<session_id>/plan/script_plan.json`
- `output/documentaries/<session_id>/plan/footage_plan.json`
- `output/documentaries/<session_id>/plan/verification.json`
- `output/documentaries/<session_id>/plan/selected_assets.json`
- `output/documentaries/<session_id>/session_data.json`

## 4. Format IMPLEMENTATION_STATE.md

```markdown
# Implementation State — Documentary Studio V2

## Current phase
<phase id dan nama>

## Completed
- <task yang sudah selesai>

## In progress
- <task yang sedang dikerjakan>

## Next actions
1. <langkah berikutnya>
2. <langkah berikutnya>

## Blockers / assumptions
- <blocker atau asumsi>

## Files touched
- <file yang diubah>

## Verification status
- <compile/import/smoke/manual>
```

## 5. Format DECISION_LOG.md

```markdown
# Decision Log — Documentary Studio V2

## D-001 — Script-first pipeline
Date: <date>
Decision: <keputusan>
Reason: <alasan>
Impact: <file/config yang terpengaruh>
Status: accepted
```

Setiap keputusan penting harus dicatat: schema, budget, urutan pipeline, review gate, resource mode, fallback behavior.

## 6. Resume checklist saat konteks reset/habis

Sebelum menulis kode lagi, agent wajib:

1. Baca ulang README + PRD + SDLC + Guardrails V2.
2. Baca `IMPLEMENTATION_STATE.md` dan `DECISION_LOG.md`.
3. Cek `git status` dan file yang sedang modified.
4. Baca artifact session terakhir jika ada.
5. Restate ke user: fase saat ini, apa yang sudah selesai, langkah berikutnya.
6. Jangan mengulang pekerjaan yang sudah tercatat selesai.

## 7. Anti-drift rules

Agent dilarang:

- Kembali ke logic `cari URL dulu baru outline`.
- Meminta LLM mengarang URL footage.
- Auto-select footage hanya dari judul.
- Mengabaikan `footage_slots` dan `planned_time_range`.
- Melebihi budget resource tanpa alasan tercatat.
- Mengubah 6 mode existing.
- Melanjutkan refactor besar tanpa update state/docs.

## 8. Context budget protocol

Jika pekerjaan besar:

- Pecah jadi task kecil dengan ID, misal `V2-T01 schema`, `V2-T02 script plan`, `V2-T03 footage plan`.
- Setelah setiap task selesai, update `IMPLEMENTATION_STATE.md`.
- Jika harus berhenti di tengah, tulis `Next actions` yang sangat eksplisit.
- Jangan meninggalkan perubahan setengah jadi tanpa catatan file apa yang rusak/belum selesai.

## 9. Definition of “tidak kehilangan arah”

Sebuah sesi dianggap aman untuk dilanjutkan AI lain jika:

- Ada docs V2 yang jelas.
- Ada `IMPLEMENTATION_STATE.md` terbaru.
- Ada `DECISION_LOG.md` untuk keputusan non-trivial.
- Artifact plan/session bisa dibaca ulang.
- Verifikasi terakhir tercatat.
- Tidak ada perubahan production tanpa task ID dan alasan.
