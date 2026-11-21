# Stage 03 — Materialize, Duration, and 16:9 Timeline

## PRD

### Masalah

Clip dialokasikan dari target segment, bukan durasi voice aktual. Profile
economy/balanced juga berbeda dari klaim 1920x1080. Concat compatibility belum
divalidasi.

### Hasil wajib

- Hanya approved asset yang didownload.
- Durasi clip disesuaikan dengan voice/segment timing.
- Semua input dinormalisasi ke output profile yang disepakati.
- Portrait, landscape, dan mixed aspect menghasilkan canvas konsisten.
- Timeline memiliki actual time range dan tidak mengandalkan planned range saja.

## SDLC

1. Tambahkan materialize boundary setelah approval.
2. Validasi artifact media dengan ffprobe.
3. Implementasikan durasi aktual dan padding/trim yang deterministik.
4. Tetapkan satu output profile per resource mode.
5. Tambahkan compatibility precheck sebelum concat.
6. Tambahkan fixture landscape/portrait/no-audio.

## Guardrails

- Jangan materialize candidate/unverified/rejected.
- Jangan memaksa portrait menjadi crop 9:16.
- Jangan menyatakan 1920x1080 jika profile menghasilkan ukuran lain.
- Jangan stream-copy concat tanpa compatibility check.
- Jangan menghapus asset valid ketika satu asset gagal.
- Semua materialized asset harus menyimpan license/attribution/source URL.

## JEV

### File/symbol target

- `documentary_engine.py`: `_materialize_clip`, `_normalize_clip`,
  `assemble_segment_video`, `concat_final`, `_render_profile`

### Test wajib

- candidate belum approved ditolak
- landscape 16:9
- portrait 9:16
- mixed aspect
- source tanpa audio
- clip lebih pendek/panjang dari kebutuhan
- incompatible codec/FPS/resolution
- final metadata sesuai output profile

### Verification

```powershell
python -m py_compile documentary_engine.py
```

Dengan media fixture pendek, verifikasi menggunakan ffprobe:

- width/height,
- duration,
- codec,
- audio stream,
- FPS.

### PASS

Semua segment output memenuhi contract profile. Concat menolak input
incompatible dengan error actionable. Planned dan actual timing tersimpan.

### Handoff

Stage 04 menerima segment video yang sudah normalized dan asset manifest yang
lengkap. Stage 04 tidak boleh memperbaiki policy/source secara diam-diam.

