# Acceptance Criteria — AI Provider & Model Routing

## AC-01 — Provider registry

- [x] 9router dapat dipilih dan dikonfigurasi.
- [x] Omnirouter dapat dipilih dan dikonfigurasi (OpenAI-compatible, env OMNIROUTER_API_KEY, capability chat).
- [x] Provider yang sudah ada tetap tersedia (Groq, OpenRouter, OpenAI, Gemini, Anthropic, dll).
- [x] Custom provider tetap dapat dipakai.
- [x] Provider disabled tidak dipanggil dalam routing / fallback.

## AC-02 — API key resolution

- [x] Key dari `config.json` dapat dipakai dengan prioritas pertama.
- [x] Key dari `.env` dapat dipakai bila config kosong/placeholder.
- [x] Key placeholder (`MASUKKAN_`, `KOSONGKAN_`, dll.) tidak dianggap valid.
- [x] Key tidak tampil penuh di UI/log (masking dengan `sanitize_text`).
- [x] Missing key menghasilkan pesan error yang jelas dan actionable.

## AC-03 — Model discovery

- [x] Load Models memanggil `/models` pada provider compatible.
- [x] Model ditampilkan dalam dropdown dan di-cache dalam `model_cache`.
- [x] Loading dan validasi berjalan di background thread tanpa freeze GUI.
- [x] Timeout menghasilkan penanganan error yang rapi dan reset status tombol loading.
- [x] Model lama tetap tersedia jika reload gagal.

## AC-04 — Per-feature selection

- [x] Highlight Finder memakai provider/model pilihannya (default `ag/gemini-3.8-flash-high`).
- [x] Caption Maker memakai provider/model pilihannya (Whisper).
- [x] Hook Maker memakai provider/model pilihannya.
- [x] Title Generator memakai provider/model pilihannya.
- [x] Konfigurasi disimpan dan dimuat ulang dengan provider+model pair.

## AC-05 — Fallback

- [x] Urutan fallback dapat diatur secara global di `ai_gateway["fallback_providers"]`.
- [x] Primary gagal menghasilkan attempt fallback ke provider berikutnya.
- [x] Provider tanpa capability yang relevan tidak dipanggil (misal: provider chat tidak dipanggil untuk transcription).
- [x] Semua gagal menghasilkan status gagal yang jelas tanpa silent error.
- [x] Tidak ada retry loop tak terbatas (loop terikat pada panjang chain).

## AC-06 — Backward compatibility

- [x] Config lama tetap terbaca via migration layer.
- [x] Config lama tanpa `ai_gateway` otomatis disintesis tanpa merusak data lama.
- [x] Migrasi tidak menghapus key/model/base_url lama.
- [x] Base URL 9router tetap dikenali otomatis.
- [x] Config custom tetap dianggap custom.

## AC-07 — Runtime consistency

- [x] Semua pemanggil AI membaca provider/model hasil resolver terpusat (`get_resolved_ai_providers` / `ai_router`).
- [x] Tidak ada pemanggil yang membuat base URL router sendiri secara bertentangan.
- [x] Route provider/model dapat dilacak non-secret.
- [x] Engine lama tidak crash saat key/provider hilang.

## AC-08 — GUI

- [x] Status provider jelas (Configured, No API key, No model, Not set).
- [x] Status key dan model terpampang di setiap card.
- [x] Provider offline tidak crash halaman settings.
- [x] UI dapat kembali ke halaman sebelumnya dengan tombol Back.

## AC-09 — Security

- [x] Tidak ada API key di source/test/log baru.
- [x] Sanitasi masking key dan bearer token aktif.
- [x] Exception tidak menampilkan secret.

## AC-10 — Regression

- [x] YouTube Clipper tetap berjalan dan kompatibel.
- [x] Auto Caption tidak berubah.
- [x] Clip+Dub tidak berubah.
- [x] Dubbing Studio tidak berubah.
- [x] Clip Cutter tidak berubah.
- [x] TTS Maker tidak berubah.
- [x] Documentary Studio tidak terganggu.
