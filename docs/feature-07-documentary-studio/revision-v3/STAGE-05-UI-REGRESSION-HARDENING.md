# Stage 05 — UI Thread Safety, Browser, Regression, and Release Gate

## PRD

### Masalah

UI melakukan operasi Tkinter dari worker thread, callback dapat terjadi setelah
halaman ditutup, browser discovery hanya memberi metadata dangkal, dan
acceptance/regression belum dibuktikan dengan media nyata.

### Hasil wajib

- Semua operasi Tkinter dijalankan di main thread.
- Worker hanya mengerjakan I/O/CPU dan mengirim hasil melalui callback.
- Cancel/back aman ketika proses berjalan.
- Browser discovery menghasilkan candidate yang jujur: belum terverifikasi
  tetap `unverified`.
- Semua enam mode lama lulus smoke/regression.
- Dokumentasi dan status implementasi diperbarui.

## SDLC

1. Audit semua callback/background UI.
2. Pindahkan messagebox dan widget mutation ke `after()`.
3. Tambahkan lifecycle guard saat page destroyed.
4. Perbaiki browser candidate metadata/policy handoff.
5. Jalankan end-to-end staged test dengan provider mock dan media pendek.
6. Jalankan regression enam mode.
7. Perbarui implementation state dan acceptance evidence.

## Guardrails

- Jangan memanggil widget Tkinter langsung dari worker.
- Jangan memanggil `messagebox` dari worker.
- Jangan swallow exception UI tanpa log.
- Browser discovery tidak boleh menyatakan lisensi aman.
- Jangan mengubah flow enam mode lama untuk mempermudah Documentary.
- Jangan menutup session/page tanpa mempertahankan artifact.
- Jangan menyatakan fitur selesai jika live/provider verification belum dilakukan.

## JEV

### File/symbol target

- `pages/documentary_page.py`: `_run_thread`, callbacks, `go_back`,
  `cancel`, discovery actions
- `documentary_browser.py`: discovery normalization
- `app.py`, `pages/landing_page_v2.py`: navigation only if required
- documentation status/acceptance evidence

### Test wajib

- import/compile semua file touched
- open Documentary card
- back saat idle
- back saat processing
- cancel saat processing
- load session
- refresh preview setelah page reload
- browser unavailable fallback
- browser candidate invalid/unknown
- six legacy mode navigation smoke

### Verification

```powershell
python -m py_compile documentary_browser.py documentary_engine.py documentary_stock.py documentary_tts.py pages\documentary_page.py app.py pages\landing_page_v2.py config\config_manager.py
```

Lakukan smoke manual atau automated dengan checklist:

- landing menampilkan tujuh mode,
- Documentary terbuka,
- staged flow berhenti di review,
- output final dapat dibuka,
- enam mode lama tetap terbuka.

### PASS

Tidak ada Tkinter cross-thread operation yang tersisa. Browser fallback dan
error terlihat jelas. Acceptance criteria yang relevan memiliki bukti. Tidak
ada regression pada enam mode lama.

### Release gate

Fitur baru boleh disebut selesai hanya jika:

- semua P0 selesai,
- semua P1 selesai atau memiliki waiver tertulis,
- JEV Stage 00–05 PASS,
- compile/import PASS,
- deterministic tests PASS,
- media integration test PASS,
- six-mode regression PASS,
- tidak ada secret di diff,
- dokumentasi status tidak lagi menyatakan “verification pending”.

### Handoff akhir

Agent terakhir wajib memperbarui:

- `IMPLEMENTATION_STATE.md`
- `DECISION_LOG.md`
- acceptance evidence
- daftar known limitations

Jika ada test gagal, status harus tetap `blocked` atau `verification_pending`,
bukan `completed`.

