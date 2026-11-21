# Feature 07 V2 — Script-First / Footage-Second Planning Pack

Folder ini adalah sumber kebenaran untuk **revisi logic Documentary Studio** dari alur lama `source-first` menjadi `script-first → footage-second`.

## Masalah yang diperbaiki

Alur lama terlalu cepat mencari URL/sumber dan langsung mendapat kandidat dalam jumlah besar. Akibatnya:

- AI bisa mengembalikan URL tanpa konteks naratif yang kuat.
- Clip bisa terpilih karena judul/metadata, bukan karena relevan dengan segmen.
- User tidak sempat mereview apakah footage benar-benar cocok untuk cerita.
- Untuk video YouTube 10–30 menit, resource bisa boros karena discovery/download terlalu dini.

## Keputusan utama V2

1. **Script first**: setelah brief + durasi, LLM membuat script plan: segmen, time range, narasi, `clip_context`, dan `footage_slots`.
2. **Footage second**: engine mencari footage per `footage_slot`, bukan mencari URL topik secara umum.
3. **LLM tidak output URL**: LLM hanya output ide visual, query, dan konteks. Engine yang mencari kandidat.
4. **Verification before selection**: kandidat wajib melewati metadata/content check; judul tidak cukup.
5. **Review gate**: user review script + footage plan sebelum download/render massal.
6. **Resource-aware**: mode `economy/balanced/quality`, budget pencarian/download, render bertahap, checkpoint/resume.

## Dokumen

| File | Isi |
|---|---|
| `00_PRD_V2.md` | Kebutuhan produk untuk logic script-first/footage-second. |
| `01_SDLC_V2.md` | Rencana fase engineering, task, exit criteria, verification. |
| `02_GUARDRAILS_V2.md` | Aturan wajib agar AI tidak keluar arah saat implementasi. |
| `03_CONTEXT_PRESERVATION.md` | Protokol menjaga konteks agar AI tidak kehilangan arah saat konteks habis/reset. |

## Status

- Status: `planning-v2`
- Implementasi V2 belum dieksekusi.
- Dokumen V1 tetap berlaku untuk hal yang tidak bertentangan; jika konflik, **dokumen V2 lebih prioritas** untuk logic pencarian/footage/script.
