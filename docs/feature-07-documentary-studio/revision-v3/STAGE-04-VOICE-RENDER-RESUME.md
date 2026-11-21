# Stage 04 — Voice, Subtitle, Render, Cancel, and Resume

## PRD

### Masalah

Voiceover belum menjadi sumber timing yang authoritative. Cancel tidak
menghentikan semua operasi blocking. Resume memeriksa ukuran file saja dan
manifest dapat kehilangan detail.

### Hasil wajib

- Durasi voice aktual dicatat dan digunakan untuk timing.
- Subtitle fallback tidak overlap dan tidak melewati durasi audio.
- BGM gagal menghasilkan status/error yang jelas.
- Cancel menghentikan operasi yang dapat dihentikan.
- Resume memvalidasi media, bukan hanya ukuran file.
- Segmen valid tidak dirender ulang.

## SDLC

1. Finalisasi kontrak TTS result.
2. Reconcile segment timing dengan durasi voice.
3. Perbaiki subtitle clamping/alignment.
4. Tambahkan cancellation boundary ke requests/subprocess.
5. Tambahkan artifact validator berbasis ffprobe.
6. Perbaiki manifest merge saat resume.

## Guardrails

- Jangan menganggap file >1 KB sebagai media valid.
- Jangan menutupi TTS failure dengan success-shaped result.
- Fallback Edge TTS harus menyimpan alasan fallback.
- Jangan menghapus render artifact valid saat cancel.
- Status `cancelled`, `failed`, dan `completed` harus berbeda.
- Render final hanya boleh terjadi jika semua segment wajib valid.

## JEV

### File/symbol target

- `documentary_tts.py`: `generate`, provider result
- `documentary_engine.py`: `generate_voice`,
  `_word_timings_to_srt_cues`, `write_segment_subtitles`,
  `render_segments`, `concat_final`, `run_render_only`

### Test wajib

- TTS normal
- TTS tanpa word timing
- Chatterbox failure → fallback yang tercatat
- subtitle cue clamping
- BGM missing/timeout
- cancel sebelum, saat, dan sesudah segment
- resume dengan segment valid dan segment gagal
- corrupt media artifact

### Verification

```powershell
python -m py_compile documentary_engine.py documentary_tts.py
```

Gunakan media pendek dan mock TTS/provider. Verifikasi:

- manifest tidak kehilangan segment sebelumnya,
- session status tepat,
- final tidak dibuat jika ada segment wajib gagal,
- `data.json` dan `session_data.json` sinkron.

### PASS

Cancel/resume dapat diuji deterministik. Media corrupt tidak dianggap valid.
Voice, subtitle, render manifest, dan final metadata konsisten.

### Handoff

Stage 05 menerima engine pipeline yang sudah aman secara state. UI hanya boleh
memanggil public method dan callback, bukan mengubah state engine sembarangan.

