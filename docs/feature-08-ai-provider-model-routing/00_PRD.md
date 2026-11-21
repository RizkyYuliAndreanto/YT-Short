# PRD — AI Provider & Model Routing

## 1. Ringkasan produk

Fitur ini memungkinkan pengguna mengatur provider AI, API key, base URL, model, dan urutan fallback langsung dari aplikasi. Pengguna dapat mengaktifkan 9router dan Omnirouter sekaligus, tetapi memilih provider/model secara terpisah untuk setiap fitur AI.

Fitur ini bukan penambahan provider AI baru semata. Fitur ini membentuk lapisan routing yang menjadi sumber tunggal keputusan:

```text
Fitur AI -> Provider utama -> Model -> Fallback providers -> Hasil
```

## 2. Problem statement

Konfigurasi saat ini menyimpan `base_url`, `api_key`, dan `model` langsung pada empat layanan. Hal ini menyebabkan:

- 9router dan provider lain tidak mudah dikelola sebagai gateway terpisah.
- Omnirouter tidak dikenali sebagai provider bawaan.
- Pengguna harus mengubah setiap fitur satu per satu.
- Model yang sudah dimuat tidak terpusat.
- `base_url` lama dapat terdeteksi salah sebagai `custom`.
- API key dari `.env` dan `config.json` mempunyai resolusi yang tersebar.
- Fallback antar-provider belum ada.

## 3. Goals

1. Pengguna dapat mengaktifkan atau menonaktifkan beberapa provider.
2. Pengguna dapat memuat model dari provider yang mendukung endpoint `/models`.
3. Pengguna dapat memilih model untuk setiap fitur AI.
4. Pengguna dapat menentukan urutan fallback.
5. API key dapat disimpan di aplikasi atau dibaca dari `.env`.
6. Konfigurasi lama tetap dapat dimuat dan disimpan secara aman.
7. Semua layanan existing tetap berfungsi tanpa perubahan perilaku.

## 4. Non-goals

- Tidak mengubah prompt highlight atau perilaku production clip.
- Tidak menghapus atau menormalkan API key lama secara diam-diam.
- Tidak menambahkan provider selain 9router, Omnirouter, dan provider yang sudah didaftarkan jika tidak diperlukan.
- Tidak mengubah endpoint Whisper atau TTS menjadi chat model.
- Tidak mempublikasikan atau mengunggah video secara otomatis.
- Tidak mengirim API key ke log, crash report, atau prompt.

## 5. Target pengguna

- Kreator yang memakai beberapa gateway AI.
- Pengguna 9router lokal dan Omnirouter.
- Pengguna yang ingin model murah/cepat untuk tugas tertentu.
- Pengguna yang ingin model berbeda untuk highlight, caption, hook, dan judul.
- Editor yang membutuhkan fallback tanpa berhenti jika satu gateway mati.

## 6. User stories

### US-01 — Mengaktifkan gateway

Sebagai pengguna, saya ingin mengaktifkan 9router dan Omnirouter sekaligus sehingga saya bisa memilih satu untuk setiap fitur atau menggunakan fallback.

Acceptance:
- Kedua gateway dapat muncul sebagai provider aktif.
- Status enabled disimpan.
- Gateway yang gagal koneksi tidak menggagalkan startup aplikasi.

### US-02 — Memuat model

Sebagai pengguna, saya ingin menekan Load Models pada gateway tertentu sehingga model yang tersedia muncul dan dapat dicari.

Acceptance:
- Hanya provider yang memiliki endpoint compatible yang memanggil `/models`.
- Loading berjalan di background thread.
- Model gagal dimuat menampilkan error yang dapat ditindaklanjuti.
- Nilai model lama tetap bertahan jika reload gagal.

### US-03 — Memilih model per fitur

Sebagai pengguna, saya ingin memilih provider dan model yang berbeda untuk setiap fitur.

Acceptance:
- Highlight Finder memiliki pilihan independen.
- Caption Maker memiliki pilihan model independen.
- Hook Maker memiliki pilihan model independen.
- Title Generator memiliki pilihan independen.
- Service lain yang memakai AI juga dapat memakai kontrak yang sama.

### US-04 — Fallback

Sebagai pengguna, saya ingin sistem mencoba gateway lain jika gateway utama mengembalikan error koneksi, auth, atau model.

Acceptance:
- Urutan fallback dapat diatur.
- Provider berikutnya hanya dicoba sesuai policy.
- Provider/model yang berhasil dicatat non-secret untuk debugging.
- Semua gagal menghasilkan pesan ringkas dan artifact/error yang dapat dibaca.

### US-05 — Migrasi konfigurasi lama

Sebagai pengguna lama, saya ingin konfigurasi 9router/Groq/OpenRouter/OpenAI yang sudah tersimpan tetap bekerja setelah fitur baru dipasang.

Acceptance:
- Konfigurasi lama dapat dibaca.
- Tidak ada key hilang saat migrasi.
- Migrasi default tidak mengubah pilihan model lama.
- Fallback pertama tidak mengubah provider yang tersimpan.

## 7. Functional requirements

### FR-01 Provider registry

Sistem harus memiliki registry provider yang berisi:
- key/provider id
- display name
- enabled
- base_url
- api_key
- api_key_env
- model cache
- capabilities
- default model

### FR-02 Provider discovery

Sistem harus mendukung loading model melalui OpenAI-compatible endpoint.

Provider yang sudah tersedia harus tetap mengenali:
- 9router
- OpenRouter
- Groq
- OpenAI
- Google
- Anthropic
- Custom

Omnirouter harus dapat didaftarkan sebagai provider bawaan setelah detail endpoint dikonfirmasi.

### FR-03 Per-feature selection

Konfigurasi setiap fitur wajib menyimpan:
- provider
- model
- optional system prompt

`base_url` disimpan pada registry gateway, bukan diduplikasi sebagai sumber konfigurasi utama.

### FR-04 API key resolution

Urutan resolusi API key:
1. Nilai eksplisit yang valid pada registry/provider.
2. Environment variable yang dipetakan provider.
3. Nilai lama pada konfigurasi task jika masih ada.

Nilai placeholder dan nilai kosong tidak dianggap valid.

### FR-04A Backward-compatible alias

Untuk konfigurasi lama, task config yang hanya memiliki `base_url/api_key/model` harus ditransformasikan ke provider registry secara in-memory.

### FR-05 Fallback chain

Fallback bersifat konfigurable per aplikasi dan dapat dioverride per task. Fallback tidak boleh dipakai untuk transcription/TTS bila provider tidak mendukung capability tersebut.

### FR-06 Validation

Sistem harus memvalidasi:
- URL
- API key
- model
- capability provider
- authentication
- endpoint models

### FR-07 Status UI

UI harus menampilkan:
- provider aktif/nonaktif
- key tersedia/tidak tersedia
- provider reachable/unreachable
- model loaded/none
- provider/model yang digunakan fitur.

## 8. Non-functional requirements

- Semua network model discovery dan validation tidak boleh freeze GUI.
- Semua error harus punya pesan actionable.
- API key tidak boleh tampil penuh di UI/log.
- Kegagalan satu provider tidak boleh membuat aplikasi gagal startup.
- Loading model harus memiliki timeout.
- Retry terbatas; default maksimum dua fallback attempt per request.
- Cache model di `config.json` hanya model ID, bukan secret.
- Semua perubahan backward-compatible.

## 9. Assumptions and dependencies

Asumsi sementara:
- Omnirouter menyediakan endpoint OpenAI-compatible atau kompatibel hampir penuh.
- Omnirouter mendukung `/v1/models`.
- Omnirouter dapat dipilih sebagai chat provider.
- 9router tetap menggunakan `http://localhost:20128/v1`.
- Caption/Hook tidak boleh otomatis memakai chat model pada provider yang tidak mendukung modalitas tersebut.

Dependency terbuka:
- URL base Omnirouter.
- Nama environment variable API key.
- Kemampuan Omnirouter pada `/v1/models`.
- Model alias resmi.
- Dukungan chat completion dan audio/TTS model.

## 10. Risks

| Risiko | Dampak | Mitigasi |
|---|---|---|
| Omnirouter endpoint tidak kompatibel | Model discovery atau chat gagal | Custom OpenAI-compatible adapter dan test smoke |
| API key tetap tersebar | Kebocoran atau resolusi salah | Central resolver dan secret guardrail |
| Migrasi mengubah config lama | Regression fitur | Dry-run migration, schema default lama, rollback in-memory |
| Model yang sama memiliki nama berbeda | Pilihan salah provider | Simpan provider+model sebagai pair |
| Fallback menambah biaya | Pengeluaran tak terduga | Jatah fallback, budget warning, disable default fallback untuk provider berbayar |
| Model tidak mendukung modality | TTS/Whisper gagal | Capability check sebelum dispatch |

