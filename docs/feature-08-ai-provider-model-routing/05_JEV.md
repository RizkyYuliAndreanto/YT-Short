# JEV — AI Provider & Model Routing

JEV ini menjadi kontrak eksekusi untuk fase implementasi nanti. Dokumen ini bukan izin untuk mulai coding saat ini.

## 1. Status

- JEV status: `approved`
- Execution status: `COMPLETED`
- Scope: satu fitur/provider routing, bukan rewrite aplikasi

## 2. Prerequisites

Wajib tersedia sebelum Job 1:

- URL Omnirouter OpenAI-compatible.
- Environment variable API key Omnirouter.
- Kemampuan Omnirouter pada `/v1/models`.
- Scope layanan yang wajib memakai routing.
- Worktree dibaca dan file target dikunci.
- Config lama dibackup atau dapat rollback.

## 3. Job sequence

| Job | Kerja | Evidence wajib |
|---|---|---|
| 01 | Konfirmasi Omnirouter dan update registry | command/output smoke atau keputusan blocked |
| 02 | Tambah provider/key resolver | unit test PASS |
| 03 | Tambah backward-compatible migration | migration test PASS |
| 04 | Tambah model discovery/cache | mock and/or live smoke PASS |
| 05 | Ubah Settings UI | UI smoke/evidence screenshot atau log |
| 06 | Sinkronkan task runtime | automated tests per task |
| 07 | Implementasikan fallback | mock fallback test PASS |
| 08 | Jalankan regression | compile/test evidence |
| 09 | Tulis execution report | execution report + risk/blocker |

## 4. Allowed file scope

Scope awal:
- `config/ai_provider_config.py`
- `config/config_manager.py`
- `pages/settings/ai_api_settings.py`
- `pages/settings/ai_providers/base_provider.py`
- `pages/settings/ai_providers/caption_maker.py`
- `pages/settings/ai_providers/hook_maker.py`
- `pages/settings/ai_providers/highlight_finder.py`
- `pages/settings/ai_providers/title_generator.py`
- `dialogs/model_selector.py`
- module resolver baru
- test files
- dokumentasi fitur ini

File existing lain hanya boleh diubah bila pemanggilan AI memerlukan routing terpusat.

## 5. Verification steps

### 5.1 Static

```powershell
python -m py_compile config/config_manager.py config/ai_provider_config.py pages/settings/ai_api_settings.py pages/settings/ai_providers/base_provider.py pages/settings/ai_providers/caption_maker.py pages/settings/ai_providers/hook_maker.py pages/settings/ai_providers/highlight_finder.py pages/settings/ai_providers/title_generator.py
```

### 5.2 Unit

```powershell
python -m pytest tests/test_ai_provider_routing.py -q
```

Jika test belum ada, agent harus membuat test kecil yang relevan; jangan mengklaim PASS karena compile saja.

### 5.3 Provider smoke

Wajib memvalidasi:
- 9router model discovery bila local service aktif.
- Omnirouter model discovery bila credential tersedia.
- missing key.
- unreachable provider.
- unsupported model.
- fallback success.
- fallback all-failed.

### 5.4 UI smoke

Manual:
1. Buka Settings -> AI API.
2. Aktifkan provider.
3. Load model.
4. Cari model.
5. Pilih model per fitur.
6. Simpan.
7. Buka lagi dan pastikan nilai tetap.
8. Putus provider utama dan pastikan fallback jalan bila enabled.

### 5.5 Regression

Manual atau automated:
- YouTube Clipper.
- Clip+Dub.
- Dubbing Studio.
- Clip Cutter.
- TTS Maker.
- Auto Caption.
- Documentary Studio.

## 6. PASS conditions

PASS hanya jika:
- Semua evidence terkumpul.
- Tidak ada syntax/error test yang belum dijelaskan.
- Config lama terbaca.
- 9router dan Omnirouter dapat dipilih bila tersedia.
- Model dapat dimuat/dipilih.
- Runtime memakai pilihan yang disimpan.
- Fallback test lulus.
- Tidak ada key tersembunyi di log/output.
- Acceptance criteria lulus.

## 7. FAIL conditions

FAIL jika:
- Ada secret pada log, screenshot, atau artifact.
- Config lama rusak.
- Fallback menghasilkan success palsu.
- UI freeze pada network.
- Provider yang disabled tetap dipanggil.
- Satu UI bisa menyimpan model tetapi engine tidak membacanya.
- Model manual tidak tersimpan untuk Caption/Hook.
- Regression existing gagal.

## 8. Handoff

Setelah selesai, buat:
- ringkasan file changed
- migration behavior
- test evidence
- provider smoke evidence
- blocker/risk tersisa
- state PASS/FAIL

