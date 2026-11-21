# SRS — AI Provider & Model Routing

## 1. Technical scope

Lapisan baru wajib terpusat pada:

- provider registry
- API key resolver
- model discovery/cache
- provider capability
- fallback chain
- task routing

UI dan engine tidak boleh membuat resolver sendiri.

## 2. Proposed config model

```json
{
  "ai_gateway": {
    "enabled": true,
    "preferred_provider": "omnirouter",
    "fallback_enabled": true,
    "fallback_providers": ["9router", "openrouter"],
    "providers": {
      "9router": {
        "enabled": true,
        "base_url": "http://localhost:20128/v1",
        "api_key": "",
        "api_key_env": "ROUTER_API_KEY",
        "model_cache": [],
        "capabilities": ["chat", "tts"]
      },
      "omnirouter": {
        "enabled": true,
        "base_url": "",
        "api_key": "",
        "api_key_env": "OMNIROUTER_API_KEY",
        "model_cache": [],
        "capabilities": ["chat"]
      }
    }
  },
  "ai_providers": {
    "highlight_finder": {
      "provider": "9router",
      "model": "ag/gemini-3.8-flash-high"
    }
  }
}
```

Kontrak ini adalah target. Implementasi bertahap boleh memakai compatibility adapter sebelum schema final aktif.

## 3. Modules

### 3.1 Config/registry

File target:
- `config/ai_provider_config.py`
- `config/config_manager.py`

Tanggung jawab:
- mendaftarkan provider
- migration config lama
- resolusi key
- resolusi provider/model task
- persist provider metadata

### 3.2 UI

File target:
- `pages/settings/ai_api_settings.py`
- `pages/settings/ai_providers/base_provider.py`
- empat halaman provider yang sudah ada
- `dialogs/model_selector.py` bila perlu diperluas

Tanggung jawab:
- gateway list
- enable/disable
- base URL/key
- model discovery
- model search
- task selection
- fallback ordering
- status/validation

### 3.3 Runtime routing

Implementasi harus menyediakan resolver reusable, dapat dipanggil dari:
- `clipper_core.py`
- `app.py`
- `script_generator.py`
- `video_analyzer.py`
- `documentary_engine.py`
- `clip_dub_engine.py`
- `pages/auto_caption_page.py`
- `pages/clip_dub_page.py`
- `pages/dubbing_studio_page_v2.py`
- `webview_app.py`

Tidak boleh hanya memperbaiki satu UI tanpa memperbaiki pemanggil runtime.

## 4. Core interfaces

```python
def get_enabled_providers() -> list[dict]:
    pass


def get_provider(provider_id: str) -> dict:
    pass


def resolve_api_key(provider_id: str, explicit_key: str = "") -> str:
    pass


def load_models(provider_id: str, timeout_seconds: int = 30) -> list[str]:
    pass


def resolve_task_provider(task_key: str) -> dict:
    pass


def get_fallback_chain(task_key: str) -> list[dict]:
    pass


def execute_with_fallback(task_key: str, capability: str, operation):
    pass
```

Nama pasti dapat disesuaikan dengan pola project, tetapi kontrak harus tercapai.

## 5. State model

### Provider

```text
disabled
enabled_unchecked
enabled_connected
enabled_key_missing
enabled_error
```

### Model discovery

```text
idle
loading
loaded
empty
error
```

### Request route

```text
primary
fallback_1
fallback_2
failed
```

## 6. Data invariant

- Pair provider+model selalu menjadi identitas model.
- Tidak boleh hanya menyimpan model tanpa provider pada konfigurasi baru.
- Tidak boleh menyimpan secret pada model cache.
- Provider yang disabled tidak boleh dipanggil.
- Capability tidak boleh dilanggar.
- Task dengan config lama harus di-migrate in-memory atau saved migration.
- Fallback chain tidak boleh berisi duplikat provider.

## 7. Backward compatibility

Konfigurasi lama yang diterima:

```json
{
  "base_url": "https://...",
  "api_key": "...",
  "model": "...",
  "ai_providers": {
    "highlight_finder": {
      "base_url": "...",
      "api_key": "...",
      "model": "..."
    }
  }
}
```

Migrasi harus:
- mendeteksi provider dari base URL
- mempertahankan custom/unknown sebagai custom provider
- mempertahankan model lama
- mempertahankan API key eksplisit
- tidak menulis ulang secret ke file tambahan
- tidak mengubah pilihan lama secara diam-diam

## 8. API error handling

Sistem wajib membedakan:
- missing key
- invalid key
- base URL unreachable
- invalid response
- unsupported model
- unsupported capability
- timeout
- all providers failed

Pesan UI tidak boleh mencantumkan nilai key.

## 9. Network behavior

- Timeout wajib diset untuk load models dan validation.
- Retry hanya untuk kegagalan sementara yang layak.
- Tidak boleh retry provider berbayar tanpa batas.
- Cancel UI harus menghentikan update UI yang tidak relevan.
- Background worker harus memakai `threading.Thread(..., daemon=True)`.

## 10. Security requirements

- `.env` adalah sumber alternatif, bukan output yang disarankan untuk UI.
- Jangan log Authorization header atau request body yang berisi key.
- Jangan tampilkan API key penuh.
- Sanitasi exception sebelum ditampilkan.
- `config.json` yang mengandung key harus tidak dikomit.

