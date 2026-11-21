# Decision Log — AI Provider & Model Routing

## DL-01 — Provider separation

Keputusan:
- Provider dianggap sebagai gateway registry.
- Task menyimpan provider+model pair.
- Base URL disimpan pada provider registry.

Status: `approved`

## DL-02 — Omnirouter

Keputusan:
- Omnirouter didaftarkan sebagai provider gateway OpenAI-compatible.
- Base URL: Konfigurasi default di UI/config (default dapat diisi oleh user atau kosong).
- Environment variable API key: `OMNIROUTER_API_KEY`.
- Capability: `["chat"]`.
- Model discovery: Mendukung `/v1/models` OpenAI-compatible.

Status: `approved`

## DL-03 — 9router

Keputusan:
- 9router tetap sebagai provider lokal default.
- Base URL default: `http://localhost:20128/v1`.
- API key menggunakan environment variable `NINE_ROUTER_API_KEY`, fallback ke `ROUTER_API_KEY` dan `ANTHROPIC_AUTH_TOKEN`.
- Capability: `["chat", "tts"]`.

Status: `approved`

## DL-04 — Fallback default

Keputusan:
- Menggunakan Global Fallback Chain di `ai_gateway` (contoh: `["9router", "openrouter", "groq"]`).
- Fallback chain disaring berdasarkan capability yang dibutuhkan fitur (misal: Whisper hanya untuk provider yang punya capability transcription).
- Fallback diatur dengan batas percobaan maksimum (retry limit) dan tidak boleh loop tak terbatas.

Status: `approved`

## DL-05 — Migration

Keputusan:
- Config lama tetap dibaca.
- Config baru boleh ditulis bersamaan dengan alias lama untuk transisi.
- Migration tidak boleh menghapus field lama pada tahap awal.

Status: `approved`

## Resolved questions

1. Apa exact base URL Omnirouter? -> Konfigurable via UI/config (OpenAI-compatible).
2. Environment variable mana yang akan dipakai? -> `OMNIROUTER_API_KEY`.
3. Apakah Omnirouter mendukung `/v1/models`? -> Ya, protokol OpenAI-compatible.
4. Apakah Omnirouter mendukung chat, audio transcription, dan TTS? -> Default `chat`.
5. Apakah fallback global atau per task? -> Global Fallback Chain.
6. Apakah API key harus disimpan di UI atau hanya dari `.env` untuk Omnirouter? -> Keduanya didukung (resolusi priority: config eksplisit > .env).
