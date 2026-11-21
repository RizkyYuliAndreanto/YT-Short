# Tail Gate — AI Provider & Model Routing

Tail gate adalah aturan penutupan implementasi. Task tidak boleh dianggap selesai hanya karena build lulus.

## TG-01 — Scope gate

- [x] Tidak ada perubahan pada prompt/highlight lama.
- [x] Tidak ada perubahan pada portrait/crop lama.
- [x] Tidak ada perubahan file existing yang tidak dibutuhkan routing.
- [x] Semua perubahan memiliki file/diff yang dapat ditinjau.

## TG-02 — Config gate

- [x] Config lama masih terbaca dengan backward compatibility ganda.
- [x] Config baru disimpan normal dengan struktur `ai_gateway` dan `ai_providers`.
- [x] Reload aplikasi mempertahankan provider/model pair.
- [x] Tidak ada secret ditulis baru ke source atau artifact.

## TG-03 — Provider gate

- [x] 9router terdeteksi dan dapat dipakai bila aktif (default local).
- [x] Omnirouter terdaftar sebagai provider OpenAI-compatible konfigurable.
- [x] Provider disabled tidak dipanggil.
- [x] Custom provider tetap bekerja normal.

## TG-04 — Model gate

- [x] Discovery `/models` didukung via `load_models` di background thread.
- [x] Model disimpan sebagai provider+model pair.
- [x] Model lama tetap tersimpan jika discovery gagal.
- [x] Menggunakan keluarga model Antigravity (`ag/gemini-3.8-flash-high`, dll).

## TG-05 — Runtime gate

- [x] Highlight Finder menggunakan route yang dipilih via centralized resolver.
- [x] Caption Maker menggunakan route yang dipilih (Whisper model).
- [x] Hook Maker menggunakan route yang dipilih.
- [x] Title Generator menggunakan route yang dipilih.
- [x] Service lain (`script_generator`, `video_analyzer`, `documentary_engine`) otomatis mewarisi resolver terpusat.

## TG-06 — Fallback gate

- [x] Fallback mengikuti urutan tersimpan secara terpusat di `ai_gateway`.
- [x] Capability provider diperiksa sebelum dipanggil dalam fallback chain.
- [x] Semua provider gagal menghasilkan error final terkontrol.
- [x] Tidak ada success-shaped fallback atau retry loop tak terbatas.

## TG-07 — GUI gate

- [x] Settings dapat dibuka dari halaman AI API Settings.
- [x] Load/Validate berjalan di background thread dengan `self.after(0, ...)`.
- [x] UI tidak freeze saat network request.
- [x] Error dapat dibaca dengan jelas.
- [x] Konfigurasi dapat disimpan dan dimuat ulang.

## TG-08 — Secret gate

- [x] Tidak ada API key pada diff code.
- [x] Tidak ada API key pada log (disanitasi via `sanitize_text`).
- [x] `.env` dan `config.json` tetap terjaga tanpa membocorkan kredensial rahasia.

## TG-09 — Regression gate

- [x] YouTube Clipper lulus.
- [x] Clip+Dub lulus.
- [x] Dubbing Studio lulus.
- [x] Clip Cutter lulus.
- [x] TTS Maker lulus.
- [x] Auto Caption lulus.

## TG-10 — Evidence gate

Sebelum task ditutup, evidence minimal harus berisi:
- list file changed
- hasil static verification / code review
- hasil unit test suite
- mock provider test
- final PASS

## Status penutupan

```text
Status: PASS
```
Semua tail gate relevan telah diverifikasi dan lulus.
