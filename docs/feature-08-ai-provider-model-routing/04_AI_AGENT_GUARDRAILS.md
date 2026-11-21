# AI Agent Guardrails — AI Provider & Model Routing

## 1. Misi

Implementasikan routing provider/model sebagai lapisan terpusat tanpa mengubah prompt, transcript, FFmpeg, hook, subtitle, atau behavior production yang tidak berkaitan.

## 2. Larangan

- Jangan mengubah prompt `SYSTEM_PROMPT.md` atau highlight behavior.
- Jangan mengubah portrait/crop logic untuk kebutuhan routing.
- Jangan hardcode API key.
- Jangan commit `.env`, `config.json` berisi key, atau cookies.
- Jangan log Authorization header atau request payload secret.
- Jangan menghapus konfigurasi lama tanpa backup/migration.
- Jangan memasang fallback provider berbayar secara default jika belum disetujui.
- Jangan menyebut sukses provider hanya berdasarkan dropdown/model cache.
- Jangan mengeksekusi work ini sebelum JEV disetujui.
- Jangan menjalankan destructive command pada output/config user.
- Jangan push remote tanpa permintaan.

## 3. Wajib dibaca sebelum implementation

- `AGENTS.md`
- `DOCUMENTATION.md`
- folder fitur ini
- `config/config_manager.py`
- `config/ai_provider_config.py`
- `pages/settings/ai_api_settings.py`
- `pages/settings/ai_providers/base_provider.py`
- semua pemanggil `get_resolved_ai_providers()`

## 4. Architectural rules

- Resolver provider API key/model harus tunggal.
- UI tidak boleh menjadi sumber truth provider.
- Engine tidak boleh membuat inferensi provider dari model string.
- Provider dan model disimpan sebagai pair.
- Base URL adalah property provider, bukan sumber truth terpisah pada setiap task.
- Tugas lama yang hanya menyimpan `base_url/model` harus dibaca melalui compatibility layer.

## 5. UI rules

- Semua load/validate network berjalan di background thread.
- UI update melalui `self.after(0, ...)`.
- Tombol loading dinonaktifkan agar tidak ada double request.
- Input key harus mask.
- Jangan menampilkan key penuh pada status/error.
- Cetak nama provider/model saja pada log non-secret.
- Gunakan pola CustomTkinter dan tema yang sudah ada.

## 6. Provider rules

- 9router hanya dipanggil bila enabled dan URL/key tersedia.
- Omnirouter hanya dapat masuk sebagai provider bawaan setelah endpoint dikonfirmasi.
- Provider custom tetap dapat dipakai.
- OpenAI Whisper-compatible tidak boleh diarahkan ke chat endpoint yang salah.
- TTS tidak boleh memakai chat model bila provider tidak mendukung audio/TTS.
- Fallback hanya boleh memakai provider dengan capability yang relevan.

## 7. Data and migration rules

- Tambahkan schema baru tanpa membuang key lama.
- Migration harus punya dry-run atau in-memory mode jika memungkinkan.
- Cache hanya menyimpan model ID dan timestamp.
- Tidak menyimpan response HTTP penuh jika berisi metadata secret.
- API key resolusi mengutamakan explicit config bila valid, lalu env.

## 8. Error handling

- Kegagalan provider adalah keadaan terkontrol.
- Tidak boleh memakai success-shaped fallback.
- Pesan error harus menyebut provider dan jenis kegagalan.
- Jangan menutup exception tanpa log/debug yang cukup.
- Jika semua fallback gagal, hasil akhir harus gagal dengan alasan.

## 9. Testing

Minimum:
- `python -m py_compile config/config_manager.py config/ai_provider_config.py pages/settings/ai_api_settings.py pages/settings/ai_providers/base_provider.py`
- unit test migration/resolver
- mock provider test
- settings UI smoke
- provider smoke jika tersedia
- regression 6 mode lama

## 10. Stop conditions

Agent berhenti dan meminta keputusan jika:
- Omnirouter tidak punya endpoint `/models`.
- Omnirouter memerlukan protocol berbeda dari OpenAI-compatible.
- Migrasi dapat mengubah secret key lama.
- Perubahan memerlukan memodifikasi banyak pemanggil runtime sekaligus.
- Acceptance evidence tidak dapat dibuat.
- User worktree berubah pada file scoped.

