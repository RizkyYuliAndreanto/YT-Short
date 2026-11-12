# Feature 07 — Documentary Studio Documentation Pack

Dokumentasi perencanaan untuk **fitur ke-7** pada YT-Shorts / CONTEN CREATOR AGENT: **Documentary Studio**.

Tujuan folder ini adalah menjadi sumber kebenaran untuk AI agent dan developer agar implementasi tetap **standalone**, **tidak merusak 6 fitur yang sudah ada**, dan bisa dipandu bertahap dari PRD sampai guardrail eksekusi.

## Dokumen

| File | Isi |
|---|---|
| `00_PRD.md` | Product Requirements Document: masalah, tujuan, user story, scope, risiko, metrik. |
| `01_SRS.md` | Software Requirements Specification: arsitektur, modul, interface, data model, config, error handling. |
| `02_SDLC_PLAN.md` | Rencana SDLC/engineering: fase, milestone, definition of ready/done, strategi testing. |
| `03_TASK_BREAKDOWN.md` | Rincian task implementasi per file/modul dengan dependency dan acceptance check. |
| `04_AI_AGENT_GUARDRAILS.md` | Aturan wajib untuk AI agent saat coding: larangan, pola reuse, threading, config, secrets, verifikasi. |
| `05_ACCEPTANCE_CRITERIA.md` | Kriteria penerimaan MVP dan edge cases yang harus lulus sebelum fitur dianggap selesai. |

## Keputusan utama yang sudah disepakati

- Fitur ini adalah **mode ke-7 yang berdiri sendiri**, bukan revisi YouTube Clipper, AI Dubbing Studio, Clip+Dub, Clip Cutter, TTS Maker, atau Auto Caption.
- Output utama adalah **video YouTube landscape 16:9**, biasanya berdurasi menengah-panjang.
- Fokus awal: **clip-clip dari sumber video + narasi teks yang sinkron per segmen**.
- Sumber: **manual multi-URL** + **stock footage provider opsional (Pexels/Pixabay)**. API key dan `base_url` bisa dikonfigurasi; AI menghasilkan query/pencarian/rekomendasi footage, sedangkan download tetap lewat API/provider adapter resmi.
- Pencarian video panjang otomatis (`ytsearch`/YouTube Data API) tetap fase lanjutan; stock footage B-roll Pexels/Pixabay boleh masuk scope lebih awal jika API key tersedia.
- LLM/otak: utamakan **9router** sebagai OpenAI-compatible chat provider untuk outline, pemilihan segmen, dan penulisan narasi.
- Transkripsi: tetap lewat provider Whisper-compatible seperti **Groq Whisper/OpenAI Whisper**; jangan paksa 9router untuk audio transcription.
- TTS: pakai **Edge TTS dulu** sebagai baseline gratis, dengan arsitektur provider agar **Chatterbox TTS Bahasa Indonesia** bisa dipasang belakangan.
- Reuse engine lama sebagai **library/service**, bukan dengan memodifikasi flow UI fitur lama.
- Tidak ada auto-publish/upload default; upload tetap opsional dan manual.

## Status

- Status dokumen: `implemented-mvp`
- Status implementasi: `MVP selesai, menunggu acceptance/regression manual`
- File implementasi MVP: `documentary_engine.py`, `documentary_stock.py`, `documentary_tts.py`, `pages/documentary_page.py`.
- File existing yang disentuh minimal: `app.py`, `pages/landing_page_v2.py`, `config/config_manager.py`.
- Entry point UI: kartu **Documentary Studio** di landing page → `pages/documentary_page.py` → `documentary_engine.py`.
- Verifikasi otomatis yang sudah jalan: `py_compile` untuk file baru/diubah, import smoke test, engine session smoke test, provider availability check.
- Belum diverifikasi: render end-to-end dengan media nyata, Pexels/Pixabay dengan API key asli, Chatterbox endpoint, dan regression manual 6 mode lama.
