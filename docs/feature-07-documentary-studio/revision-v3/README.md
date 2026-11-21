# Documentary Studio — Revision V3

Paket ini adalah rencana revisi terkontrol untuk Feature 07 setelah audit
menemukan masalah pada review gate, source mode, policy, sinkronisasi durasi,
resume/cancel, dan thread-safety UI.

## Cara memakai paket ini

1. Agent membaca `00_MASTER_PLAN.md`.
2. Agent hanya mengerjakan satu tahap aktif.
3. Agent membaca dokumen tahap tersebut sampai selesai sebelum menyentuh kode.
4. Agent menjalankan JEV (Job Execution & Verification) tahap tersebut.
5. Agent tidak melanjutkan tahap berikutnya jika gate tahap aktif gagal.
6. Saat konteks habis, agent berikutnya membaca:
   - master plan,
   - dokumen tahap aktif,
   - artefak dan hasil test yang disebut pada JEV,
   - status git sebelum mengubah file.

## Dokumen tahap

| Tahap | Dokumen | Tujuan |
|---|---|---|
| 0 | `STAGE-00-CONTRACT.md` | Mengunci kontrak perilaku dan state |
| 1 | `STAGE-01-SOURCE-POLICY.md` | Memperbaiki intake, source mode, policy, dan error |
| 2 | `STAGE-02-SCRIPT-FOOTAGE-REVIEW.md` | Membuat review gate benar-benar wajib |
| 3 | `STAGE-03-MATERIALIZE-TIMELINE.md` | Memperbaiki materialize, durasi, dan 16:9 |
| 4 | `STAGE-04-VOICE-RENDER-RESUME.md` | Menyelaraskan TTS, subtitle, render, cancel, resume |
| 5 | `STAGE-05-UI-REGRESSION-HARDENING.md` | Memperbaiki UI thread-safety dan regression |

## Definisi JEV

JEV berarti **Job Execution & Verification**. JEV bukan saran umum; JEV adalah
kontrak kerja agent yang berisi:

- input yang harus tersedia,
- file/symbol yang boleh disentuh,
- urutan eksekusi,
- test yang wajib dijalankan,
- bukti yang harus disimpan,
- kondisi PASS/FAIL,
- informasi handoff ke tahap berikutnya.

## Aturan umum

- Jangan mengubah enam fitur lama kecuali perubahan import/navigation wajib dan
  terbukti backward compatible.
- Jangan menghapus perubahan pengguna yang sudah ada di worktree.
- Jangan mengganti nama artifact lama tanpa migration/compatibility reader.
- Jangan memakai auto-success ketika provider, policy, render, atau test gagal.
- Jangan menganggap thumbnail, judul, atau score sebagai verifikasi isi video.
- Jangan commit secret/API key.
- Perubahan kode harus kecil, dapat diuji, dan sesuai tahap aktif saja.

