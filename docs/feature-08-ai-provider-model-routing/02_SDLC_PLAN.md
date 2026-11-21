# SDLC Plan — AI Provider & Model Routing

## 1. Pendekatan

Gunakan implementasi bertahap berbasis vertical slice:

1. Foundation registry/resolver.
2. Backward compatibility.
3. Provider dan model UI.
4. Runtime routing.
5. Fallback.
6. Regression dan acceptance.

Setiap tahap harus menghasilkan test atau smoke check yang dapat dibuktikan.

## 2. Phase 0 — Contract lock

Task:
- Konfirmasi URL dan environment variable Omnirouter.
- Konfirmasi endpoint `/models`.
- Konfirmasi capability chat/audio/TTS.
- Kunci schema config.
- Kunci daftar fitur yang memakai AI.

Exit criteria:
- Tidak ada implementasi sebelum keputusan endpoint Omnirouter dibuat.
- PRD/SRS/JEV dianggap locked untuk scope tahap.

## 3. Phase 1 — Config foundation

Task:
- Tambah provider registry.
- Tambah API key resolver.
- Tambah migration config lama.
- Tambah task resolver.
- Tambah unit test pure logic.

Exit criteria:
- 9router, OpenRouter, Groq, OpenAI, Custom dapat terdeteksi.
- Config lama dapat dibaca.
- Secret tidak masuk output test/log.
- `py_compile` config modules lulus.

## 4. Phase 2 — Model discovery

Task:
- Tambah model loader OpenAI-compatible.
- Tambah timeout/cancel/error classification.
- Tambah model cache.
- Tambah Omnirouter apabila endpoint tersedia.

Exit criteria:
- Model dapat dimuat pada endpoint compatible.
- Model lama tetap ada saat discovery gagal.
- Thread tidak freeze GUI.
- Validation menghasilkan status jelas.

## 5. Phase 3 — Settings UI

Task:
- Tambah provider gateway list.
- Tambah enable/disable.
- Tambah base URL/key/model manual.
- Tambah searchable model dropdown.
- Tambah fallback ordering.
- Tambah per-feature provider/model selection.
- Perbaiki bug model entry untuk Caption/Hook.

Exit criteria:
- Pengguna dapat mengaktifkan 9router dan Omnirouter.
- Pengguna dapat memilih model per fitur.
- Status saved/loading/error dapat dilihat.
- UI tidak crash bila provider offline.

## 6. Phase 4 — Runtime routing

Task:
- Sinkronkan semua pemanggil AI ke resolver terpusat.
- Pertahankan signature lama bila ada.
- Hindari perubahan prompt dan media pipeline.

Target minimal:
- Highlight Finder
- Caption Maker
- Hook Maker
- Title Generator
- Script Generator
- Documentary Studio
- Dubbing/Clip+Dub

Exit criteria:
- Pilihan model provider baru benar-benar dipakai.
- Tidak ada pemanggil yang membaca provider registry lama secara independen.
- Existing provider config masih bekerja.

## 7. Phase 5 — Fallback

Task:
- Tambahkan fallback chain.
- Tambahkan capability check.
- Tambahkan fallback classification.
- Tambahkan retry terbatas.
- Tambahkan non-secret request route log.

Exit criteria:
- Primary gagal -> fallback dipanggil.
- Provider tidak mendukung task tidak dipanggil.
- Semua provider gagal menghasilkan error final.
- Tidak ada infinite retry.

## 8. Phase 6 — Hardening

Task:
- Unit tests untuk resolver dan migration.
- Integration test dengan mock provider.
- Smoke test 9router/Omnirouter bila tersedia.
- Regression 6 mode existing.
- Documentation update.

Exit criteria:
- Semua acceptance criteria lulus.
- Tidak ada secret tersimpan.
- Regression manual dan automated terekam.

## 3. Definition of Ready

Task siap dikerjakan jika:
- PRD dan SRS mencakup requirement.
- Input/expected output jelas.
- File target dikenal.
- Test yang akan dijalankan sudah ditentukan.
- Tidak ada perubahan diam-diam pada prompt/video pipeline.

## 4. Definition of Done

- Implementasi sesuai guardrails.
- Compile/syntax check lulus.
- Unit/integration test lulus.
- Konfigurasi lama terbaca.
- Semua service AI memakai resolver.
- UI responsive dan error tidak silent.
- Evidence JEV tersedia.
- Tidak ada secret baru di repository.

## 5. Testing strategy

| Tingkat | Scope |
|---|---|
| Unit | migration, provider detection, key resolver, fallback chain |
| Mock integration | OpenAI-compatible `/models`, success/failure response |
| Widget/UI smoke | settings page, per-feature selection, load models |
| Provider smoke | 9router dan Omnirouter bila endpoint tersedia |
| Regression | enam mode existing, navigation, save config |
| End-to-end | satu task AI per fitur dengan provider utama/fallback |

## 6. Risks

- Omnirouter tidak punya `/models`.
- Omnirouter tidak mendukung endpoint native yang sama untuk semua fitur.
- API key environment names berbeda.
- Config lama memiliki string base URL yang sulit dideteksi.
- Provider chain lama menganggap fallback sebagai primary.

