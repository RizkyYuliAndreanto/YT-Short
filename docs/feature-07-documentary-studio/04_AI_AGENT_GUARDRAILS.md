# AI Agent Guardrails — Documentary Studio (Feature 07)

Dokumen ini adalah aturan wajib untuk AI agent yang mengimplementasikan Documentary Studio. Tujuannya: fitur baru kuat, tapi existing app tetap stabil.

## 1. Misi

Bangun **Documentary Studio**, mode ke-7 standalone, untuk menghasilkan video dokumenter YouTube 16:9 dari brief/topik dan/atau multi-URL sumber, dengan narasi TTS dan subtitle sinkron. Fitur harus memakai ulang engine existing sebagai library, bukan mengubah flow 6 mode lama.

## 2. Non-negotiables

1. **Jangan ubah perilaku 6 mode existing**: YouTube Clipper, AI Dubbing Studio, Clip+Dub Studio, Clip Cutter, TTS Maker, Auto Caption.
2. **Standalone first**: perubahan ke `app.py` dan `landing_page_v2.py` hanya untuk registrasi/navigasi/kartu mode baru.
3. **Reuse via import/service**, bukan copy-paste engine besar atau memodifikasi state internal engine lama.
4. **Config via `ConfigManager`**; tambah namespace `documentary` backward compatible.
5. **Secrets tidak boleh masuk repo/log**: API key dari config/`.env`; cookies tetap lokal.
6. **Semua operasi berat di background thread**; GUI tidak boleh freeze.
7. **Setiap proses panjang wajib punya progress, log, dan cancel.**
8. **Output default 16:9 landscape 1920×1080** untuk Documentary Studio; jangan paksa pipeline portrait 9:16.
9. **LLM/9router hanya untuk chat/LLM tasks**; transcription tetap Whisper-compatible; TTS baseline Edge TTS, Chatterbox opsional lewat adapter.
10. **Stock footage Pexels/Pixabay lewat API/provider adapter resmi**; API key via env/config, `base_url` default resmi dan hanya dioverride untuk proxy/mirror yang disengaja; simpan license/attribution; jangan scraping HTML bila API tersedia.
11. **Tidak ada auto-publish/upload default.**
12. **Source asset policy wajib dipatuhi**: jangan menjadikan channel narasi dokumenter atau channel lokal non-open-access sebagai backbone utama; utamakan sumber open-access/arsip resmi, Wikimedia/Wikipedia/Wikivideo, dan channel luar negeri yang minim watermark/clearance lebih baik; aset media sosial lokal hanya untuk klip pendek ~5–15 detik sebagai B-roll, bukan tulang punggung video.

## 3. Sebelum coding

Agent wajib:

- Baca `AGENTS.md` dan `DOCUMENTATION.md`.
- Baca seluruh file di `docs/feature-07-documentary-studio/`.
- Inspect file reuse yang relevan sebelum menulis kode:
  - `pages/landing_page_v2.py`, `app.py`
  - `clip_cutter_core.py`, `video_analyzer.py`, `script_generator.py`
  - `edge_tts_engine.py`, `tts_sync.py`, `caption_generator.py`
  - `config/config_manager.py`, `config/ai_provider_config.py`
  - `components/ui_theme.py`, `components/page_layout.py`, `components/video_preview.py`
- Jika requirement ambigu, buat asumsi paling konservatif dan dokumentasikan di session/PR, jangan diam-diam mengubah scope.

## 4. Aturan arsitektur

- Buat engine baru `documentary_engine.py` sebagai orkestrator; jangan menaruh logic UI di engine.
- Buat adapter TTS `documentary_tts.py` dan stock footage `documentary_stock.py`; jangan hardcode provider di banyak tempat.
- Session artifact hanya di `output/documentaries/<session_id>/`.
- Semua path memakai `pathlib.Path` dan aman untuk Windows.
- Gunakan lazy import untuk modul berat (`cv2`, `numpy`, `mediapipe`, `edge_tts`) bila engine di-load di startup.
- Fungsi core sebaiknya punya type hints untuk argumen/return penting.
- Komentar seperlunya saja; ikuti gaya project yang compact.

## 5. Aturan UI

- Gunakan `customtkinter` + `components.ui_theme` (`Colors`, `Fonts`, `Spacing`, `BorderRadius`, `create_styled_button`, `create_styled_label`).
- Halaman baru harus punya back navigation ke landing dan header konsisten.
- Semua proses blocking harus dibungkus `threading.Thread(..., daemon=True)` dan update UI lewat `self.after(0, ...)`.
- Tangkap exception dan tampilkan `messagebox.showerror` ramah; jangan biarkan GUI crash.
- Progress harus membedakan tahap: prepare sources, download, transcribe, outline, plan, select clips, assemble, TTS, subtitle, render, concat.
- Cancel harus membersihkan state `processing` dan menawarkan resume jika session valid.

## 6. Aturan provider AI

- Untuk LLM: prioritaskan `ai_providers.script_generator`, fallback `highlight_finder`, lalu default existing. Ini membuat 9router/OpenAI-compatible mudah dipakai.
- Untuk transcription: gunakan `ai_providers.caption_maker` sebagai Whisper-compatible endpoint. Jangan mengarahkan `caption_maker` ke endpoint chat 9router kecuali provider itu benar-benar support audio transcription.
- Untuk TTS: `documentary_tts.py` memilih provider dari `config["documentary"]["tts_provider"]`.
  - `edge_tts`: baseline.
  - `chatterbox`: hanya jika config enabled dan endpoint/model tersedia; jika gagal, fallback ke Edge TTS atau tandai segment gagal dengan pesan jelas.
- Untuk stock footage: LLM hanya membuat query dan ranking/rekomendasi; `documentary_stock.py` yang memanggil API Pexels/Pixabay.
  - API key dibaca dari env yang dirujuk `api_key_env`; jangan taruh key di prompt, log, atau `config.json`.
  - `base_url` default ke endpoint resmi; override harus `https` dan hanya untuk proxy/mirror yang disengaja.
  - Terapkan rate limit/backoff sederhana; cache kandidat per session untuk resume.
  - Simpan `license`, `attribution`, dan `source_page_url` untuk setiap aset stock yang dipakai.
- Selalu validasi response LLM sebagai JSON; kalau gagal, coba repair ringan lalu retry maksimal 1–2 kali.

## 6A. Aturan sourcing asset & lisensi

Keputusan sourcing yang harus diimplementasikan sebagai guardrail, bukan jaminan hukum:

- **Backbone video** diutamakan dari sumber yang lebih aman/terbuka: channel berita/dokumenter luar negeri bereputasi, institusi publik, arsip resmi, Wikimedia/Wikipedia/Wikivideo/Archive.org bila lisensinya eksplisit.
- **Hindari sebagai backbone utama**: channel narasi dokumenter pada umumnya, channel clipping/reupload, dan channel lokal yang tidak jelas open-access/reuse permission.
- **YouTube**: pilih channel dengan sinyal clearance lebih baik dan minim watermark/reupload; tetap batasi durasi kutipan yang dipakai dan catat channel/uploader.
- **Media sosial** (Facebook/TikTok/Instagram): untuk aset lokal/third-party hanya boleh dipakai sebagai **B-roll pendek ~5–15 detik** untuk mengurangi risiko claim; jangan rakit video panjang hanya dari klip medsos. Konten harus tetap punya nilai tambah narasi/komentar.
- **Wikimedia/Wikipedia/Wikivideo/Archive.org dan sejenisnya**: boleh mengambil excerpt lebih panjang karena lisensi cenderung eksplisit, tetapi license/attribution tetap wajib dicatat dan syarat lisensi dipatuhi.
- **Stock footage Pexels/Pixabay** tetap jadi preferensi untuk B-roll generik karena lisensinya lebih jelas.
- Setiap aset terpilih wajib menyimpan `source_policy`: `channel_or_account`, `platform`, `license_signal`, `intended_use` (`backbone`, `broll_short`, `licensed_archive`, `stock`), `clip_duration_seconds`, `attribution`, `review_status`.
- LLM tidak boleh menandai konten “aman/lisensi jelas” hanya dari judul; penilaian channel/platform tetap memakai metadata, domain, dan review user.
- Jika kandidat melanggar policy, sistem boleh menandai `policy_warning`/`rejected_by_policy`; override hanya boleh lewat persetujuan user yang eksplisit.

## 7. Aturan video/FFmpeg

- Normalisasi output Documentary Studio ke `1920x1080`, H.264/AAC, fps stabil.
- Sumber non-16:9 harus dinormalisasi dengan fit/pad/blur; dilarang memaksa crop portrait 9:16 untuk mode ini.
- Render per segmen/bab; concat hanya setelah semua segmen valid.
- Simpan command FFmpeg penting ke log debug, tapi jangan log path yang mengandung secret.
- Hapus temp file hanya jika aman; jangan hapus artifact session yang dibutuhkan resume.

## 8. Aturan data & session

- Buat `session_data.json` sejak awal dan update status tiap tahap.
- Simpan `outline.json`, `segment_plan.json`, `stock_candidates.json`, transcript per sumber, clip metadata, license/attribution stock footage, render manifest.
- Jika artifact valid sudah ada, engine boleh skip tahap tersebut untuk resume.
- `data.json` final harus berisi minimal: title, description, tags, duration, sources, segments, stock footage attribution/license non-secret, provider info non-secret, status.

## 9. Larangan eksplisit

- Jangan mengubah prompt/behavior `SYSTEM_PROMPT.md` atau flow highlight Shorts.
- Jangan memodifikasi `clip_dub_engine.py` portrait logic untuk keperluan Documentary Studio.
- Jangan menambah dependency besar tanpa kebutuhan jelas; jika perlu Chatterbox, jadikan opsional/adapter.
- Jangan scraping HTML Pexels/Pixabay jika endpoint API tersedia; gunakan API/provider adapter resmi.
- Jangan hardcode API key, `base_url`, atau endpoint stock provider di kode.
- Jangan commit secret, `.env`, `cookies.txt`, `config.json` berisi key.
- Jangan push ke remote kecuali diminta.
- Jangan menjalankan operasi destruktif (`rm -rf`, hapus output user) tanpa konfirmasi.
- Jangan auto-upload/publish video.
- Jangan klaim fitur selesai sebelum acceptance criteria lulus dan regression check dilakukan.

## 10. Verifikasi minimum

Setiap perubahan harus lulus minimal:

```bash
python -m py_compile documentary_engine.py documentary_tts.py documentary_stock.py pages/documentary_page.py app.py pages/landing_page_v2.py config/config_manager.py
```

Jika test tersedia:

```bash
python -m pytest tests/test_documentary_engine.py -q
```

Manual check wajib sebelum dianggap selesai:
- Buka app.
- Pastikan 6 mode lama masih muncul dan bisa dinavigasi.
- Buka Documentary Studio dari kartu ke-7.
- Jalankan minimal satu flow MVP dengan source pendek/mock bila provider belum siap.

## 11. Format jawaban/progress agent

Saat bekerja, agent harus memberi update singkat:

- Task ID yang dikerjakan.
- File yang dibuat/diubah.
- Asumsi yang dibuat.
- Verifikasi yang dijalankan.
- Risiko/blocker.

Jika menemukan kebutuhan mengubah fitur existing, agent harus berhenti dan menjelaskan dampaknya sebelum edit.
