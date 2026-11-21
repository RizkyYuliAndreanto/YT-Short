# Task Breakdown — AI Provider & Model Routing

## Task 01 — Konfirmasi Omnirouter

Deliverable:
- base URL final
- API key environment variable
- capability support
- model discovery response format

Acceptance:
- Smoke request `/models` berhasil atau secara eksplisit dicatat tidak tersedia.
- Keputusan didokumentasikan di `DECISION_LOG.md`.

## Task 02 — Provider registry

File:
- `config/ai_provider_config.py`
- `config/config_manager.py`

Deliverable:
- registry 9router dan Omnirouter
- capability metadata
- default key env
- provider resolver

## Task 03 — Config migration

File:
- `config/config_manager.py`

Deliverable:
- mapper base URL lama -> provider
- resolver key lama/baru
- backward-compatible getter
- unit test migration

## Task 04 — Model discovery service

File:
- core/config module baru
- provider pages jika perlu

Deliverable:
- timeout
- model list/sort
- model cache
- error classification
- background thread wrapper

## Task 05 — Settings UI

File:
- `pages/settings/ai_api_settings.py`
- `pages/settings/ai_providers/base_provider.py`

Deliverable:
- provider cards/gateway list
- enable/disable
- Load Models
- searchable model selector
- fallback ordering
- per-feature model

## Task 06 — Fix manual model pages

File:
- `caption_maker.py`
- `hook_maker.py`

Deliverable:
- model entry dibaca saat validate/save
- default model tidak menggantikan selection lama tanpa konfirmasi

## Task 07 — Runtime resolver

File:
- `clipper_core.py`
- `app.py`
- `script_generator.py`
- `video_analyzer.py`
- dan file lain yang memakai `get_resolved_ai_providers()`

Deliverable:
- semua pemanggil memakai resolver terpusat
- backward-compatible task config
- provider/model yang dipakai dicatat non-secret

## Task 08 — Fallback

File:
- module resolver baru
- pemanggil yang melakukan OpenAI requests

Deliverable:
- ordered fallback chain
- capability filter
- retry limits
- route result

## Task 09 — Tests

Deliverable:
- unit tests
- mock integration tests
- smoke scripts
- UI smoke evidence

## Task 10 — Documentation and release gate

Deliverable:
- update `.env.example`
- update README/guide hanya bila diperlukan
- JEV execution report
- acceptance evidence

