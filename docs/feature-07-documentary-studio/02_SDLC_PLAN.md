# SDLC Plan — Documentary Studio (Feature 07)

## 1. Pendekatan engineering

Gunakan **phased vertical-slice development**: setiap fase harus menghasilkan artefak yang bisa dicoba user, bukan menunggu semua selesai. Fokus utama adalah menjaga fitur tetap standalone dan tidak merusak 6 mode existing.

Prinsip:

- Build engine dulu dengan mock/provider nyata secukupnya, UI menyusul per tahap.
- Setiap fase punya exit criteria dan minimal verification.
- Perubahan ke file existing harus minimal dan backward compatible.
- Selalu prioritaskan cancel/resume/checkpoint untuk workflow panjang.

## 2. Fase pengerjaan

### Fase 0 — Foundation & guardrails

Tujuan: memastikan agent punya konteks dan tidak menyentuh fitur lama.

Task:
- Baca `AGENTS.md`, `DOCUMENTATION.md`, folder `docs/feature-07-documentary-studio/`.
- Petakan dependency existing: Clip Cutter, VideoAnalyzer, ScriptGenerator, Edge TTS, CaptionGenerator, ConfigManager.
- Tentukan namespace config `documentary` dan session folder `output/documentaries/`.
- Siapkan branch/commit plan.

Exit criteria:
- Tidak ada perubahan kode production.
- Agent bisa menyebut file reuse dan file baru yang akan dibuat.

### Fase 1 — Engine skeleton & config

Tujuan: pipeline bisa berjalan end-to-end dengan data mock/mini sample.

Task:
- Buat `documentary_engine.py` dengan class `DocumentaryEngine`.
- Implementasikan session folder creation, `session_data.json`, status transitions, checkpoint helpers.
- Tambah `documentary` defaults ke `ConfigManager` backward compatible.
- Implementasikan callback interface: log/progress/step/cancel.
- Buat pure helper: parse/validate segment plan, write manifest.

Exit criteria:
- Engine bisa membuat session folder dan menulis session state.
- Config lama tetap load normal; config baru muncul dengan default.
- `python -m py_compile documentary_engine.py config/config_manager.py` lulus.

### Fase 2 — Source intake & transcription

Tujuan: user bisa memasukkan URL dan sistem bisa menyiapkan sumber.

Task:
- Implement `prepare_sources()` memakai `detect_platform`/`ClipCutterCore`.
- Implement metadata screening ringan: durasi, judul, platform, ketersediaan subtitle.
- Implement download source terpilih ke `output/documentaries/<session>/sources/`.
- Implement extract audio + transcribe via `VideoAnalyzer`/`caption_maker`.
- Simpan transcript JSON/SRT per sumber.

Exit criteria:
- Satu URL valid menghasilkan source artifact + transcript/mock transcript.
- URL invalid menghasilkan error jelas tanpa crash.
- Cancel saat download/transcribe bekerja.

### Fase 3 — Outline & segment plan via 9router/LLM

Tujuan: brief menjadi outline dan segment plan yang bisa direview.

Task:
- Implement `generate_outline()` memakai `ScriptGenerator` atau client OpenAI-compatible dengan provider chain.
- Prompt outline harus meminta JSON valid: judul, logline, bab, segmen, visual intent, target duration.
- Implement `plan_segments()` dengan schema dari SRS.
- Tambah validasi/repair JSON dan retry terbatas.
- Pastikan provider mapping: LLM ke `highlight_finder`/`script_generator`; jangan pakai `caption_maker` untuk chat.

Exit criteria:
- Brief dummy menghasilkan outline valid.
- Jika provider gagal, engine fallback/error jelas.
- Segment plan tersimpan di `plan/segment_plan.json`.

### Fase 4 — Clip selection & 16:9 timeline assembly

Tujuan: segmen punya visual clip yang relevan dan output landscape.

Task:
- Implement `select_clips()` dari transcript + visual_intent + target duration.
- Implement `find_stock_candidates()` untuk B-roll: generate query via LLM, call Pexels/Pixabay sesuai config.
- Implement stock provider adapters `documentary_stock.py` dengan API key env dan `base_url` override.
- Implement ranking/fusion antara clip transcript dan stock candidates.
- Implement download stock assets terpilih + simpan license/attribution.
- Implement cut segment via FFmpeg/ClipCutterCore.
- Implement normalize ke canvas 16:9 `1920x1080`: landscape fit, vertical pad/blur, mixed aspect handling.
- Implement concat per bab/draft.
- Preview metadata clip/kandidat terpilih untuk UI review.

Exit criteria:
- Minimal satu segmen menghasilkan clip final 1920×1080.
- Sumber portrait tidak dipaksa crop 9:16; di-handle sebagai 16:9 dengan padding/blur.
- Reason pemilihan clip/kandidat tersimpan di manifest.
- Jika API key Pexels/Pixabay tersedia, sistem dapat mencari kandidat stock; jika tidak ada key, flow manual URL tetap jalan.

### Fase 5 — Voiceover, subtitle, BGM

Tujuan: audio narasi dan subtitle per segmen.

Task:
- Implement `documentary_tts.py` adapter Edge TTS.
- Generate TTS per segmen ke `clips/segment_xxx.voice.mp3`.
- Ukur durasi audio; fit-to-slot sederhana atau flag `needs_adjust`.
- Implement subtitle per segmen; jika word timing tidak ada, gunakan estimated/alignment Whisper.
- Implement BGM download/mix opsional dan volume controls.

Exit criteria:
- Satu segmen menghasilkan voice + subtitle + mixed audio.
- Subtitle tidak overlap aneh; offset bisa diatur.
- Edge TTS failure menghasilkan fallback/error yang jelas.

### Fase 6 — Render per segmen & concat final

Tujuan: video panjang aman dan resume-able.

Task:
- Render setiap segmen ke `render/segment_xxx.final.mp4`.
- Simpan `render_manifest.json` berisi status per segmen.
- Concat final hanya jika semua segmen valid.
- Tulis `final.mp4` dan `data.json` metadata.
- Implement resume: skip artifact valid, retry segmen gagal.

Exit criteria:
- Video final 16:9 playable.
- Cancel di tengah render bisa resume dari segmen terakhir.
- Satu segmen gagal tidak menghapus hasil segmen lain.

### Fase 7 — UI Documentary Studio

Tujuan: user bisa memakai fitur tanpa CLI.

Task:
- Buat `pages/documentary_page.py` dengan wizard tahap Brief → Sources → Outline → Segments → Voice → Render.
- Tambah progress/log/cancel/open output.
- Tambah source list editor dan segment review sederhana.
- Tambah entry di `app.py` dan kartu di `landing_page_v2.py`.
- Sesuaikan layout landing agar 7 kartu tetap rapi.

Exit criteria:
- Kartu mode ke-7 muncul dan membuka halaman baru.
- User bisa menjalankan MVP dari UI.
- 6 mode lama masih bisa dibuka normal.

### Fase 8 — Hardening & opsional

Tujuan: siap produksi/polish.

Task:
- Tambah tests untuk pure logic dan stock footage adapters.
- Dokumentasikan setup 9router, Groq Whisper, cookies, Edge TTS, Pexels/Pixabay API key.
- Tambah opsional `ytsearch`/YouTube Data API auto-source suggestion untuk video panjang.
- Polish stock footage providers: rate limit, cache kandidat, attribution output.
- Tambah provider Chatterbox setelah model/server siap.
- Packaging check jika diperlukan.

Exit criteria:
- Acceptance criteria MVP lulus.
- Tidak ada regression pada mode existing.
- Dokumentasi user/agent diperbarui.

## 3. Definition of Ready

Task dianggap siap dikerjakan jika:
- Requirement terkait sudah jelas di PRD/SRS/task breakdown.
- Dependency file sudah diidentifikasi.
- Ada acceptance check.
- Tidak mengubah perilaku fitur existing tanpa persetujuan.

## 4. Definition of Done

Task dianggap selesai jika:
- Kode mengikuti guardrail.
- Error handling dan cancel/progress tersedia untuk operasi berat.
- Config backward compatible.
- Minimal compile/import check lulus.
- Dokumentasi/session artifact sesuai SRS.
- Tidak ada secret/credential di repo.
- Regression check mode existing dilakukan untuk perubahan UI/navigation.

## 5. Strategi testing per fase

- Fase 1–3: unit/mock test dan compile check.
- Fase 4–6: integration test dengan video pendek dan mock AI bila perlu.
- Fase 7: manual UI test end-to-end.
- Fase 8: regression test enam mode + acceptance criteria.

## 6. Risiko proyek & mitigasi SDLC

| Risiko | Fase rawan | Mitigasi |
|---|---|---|
| Scope melebar ke auto-search video panjang | 8 | Kunci MVP manual URLs + stock footage Pexels/Pixabay; auto-search video panjang jadi task terpisah. |
| Stock API quota/license issue | 4/8 | Adapter resmi, cache kandidat, simpan attribution, fallback manual URL. |
| Chatterbox belum siap | 5/8 | Adapter opsional; Edge TTS baseline. |
| Render panjang gagal | 6 | Segment render + checkpoint + resume. |
| 9router tidak stabil | 3 | Provider fallback + prompt JSON repair + error jelas. |
| Aspect campuran jelek | 4 | Normalisasi 16:9 + preview sebelum render. |
| Regression UI landing | 7 | Uji navigasi keenam mode setelah tambah kartu. |
