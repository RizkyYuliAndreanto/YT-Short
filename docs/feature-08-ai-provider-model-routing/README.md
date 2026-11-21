# Feature 08 — AI Provider & Model Routing

Dokumentasi perencanaan untuk perubahan:

- Pemilihan **provider AI** dan **base model** dari aplikasi.
- Dukungan bersamaan untuk 9router dan Omnirouter.
- Pemilihan model berbeda untuk setiap fitur AI.
- Model discovery melalui endpoint OpenAI-compatible.
- Urutan fallback antar provider.
- Backward compatibility dengan konfigurasi lama.

## Dokumen

| File | Isi |
|---|---|
| `00_PRD.md` | Masalah, tujuan, scope, user story, requirement, dan metrik produk. |
| `01_SRS.md` | Kontrak teknis, data model, state, interface, dan error handling. |
| `02_SDLC_PLAN.md` | Tahap implementasi, dependency, testing, dan release lifecycle. |
| `07_TAIL_GATE.md` | Guard tail/release gate yang wajib lulus sebelum eksekusi ditutup. |
| `03_TASK_BREAKDOWN.md` | Pecahan pekerjaan untuk implementasi bertahap. |
| `04_AI_AGENT_GUARDRAILS.md` | Larangan dan aturan wajib untuk AI agent. |
| `05_JEV.md` | Job Execution & Verification untuk eksekusi nanti. |
| `06_ACCEPTANCE_CRITERIA.md` | Kriteria penerimaan dan evidence yang diperlukan. |
| `DECISION_LOG.md` | Keputusan sementara, asumsi, dan daftar pertanyaan terbuka. |

## Status

- Status: `in-execution`
- Implementasi: **aktif**
- Keputusan Omnirouter: **disetujui (konfigurable OpenAI-compatible, env OMNIROUTER_API_KEY, capability chat)**
- Fallback Policy: **disetujui (Global Fallback Chain)**
- Konfigurasi lama: tetap dibaca dengan migrasi backward-compatible ganda

