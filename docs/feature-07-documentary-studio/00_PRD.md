# PRD — Documentary Studio (Feature 07)

## 1. Ringkasan produk

Documentary Studio adalah mode baru mandiri di YT-Shorts yang menghasilkan **video dokumenter YouTube landscape 16:9** dari beberapa sumber video dan narasi yang ditulis AI. Pengguna cukup memberi brief/topik dan/atau URL sumber; aplikasi membantu mencari/mengunduh bahan, menyalin teks, memilih momen visual, menyusun timeline, membuat suara narasi, membakar subtitle, dan me-render video akhir.

Berbeda dengan Clip+Dub yang berorientasi Shorts 9:16 dan durasi pendek, Documentary Studio berorientasi **video YouTube biasa**: aspect ratio 16:9, durasi lebih panjang, struktur bertahap per bab/segmen, dan suara narasi yang lebih penting daripada sekadar highlight pendek.

## 2. Problem statement

Konten kreator yang ingin membuat video dokumenter sering malas atau tidak punya waktu untuk:

- mencari sumber video yang relevan,
- mengunduh banyak video secara manual,
- menonton dan memilih momen yang cocok,
- menulis naskah narasi yang sinkron dengan visual,
- mengedit, memberi subtitle, BGM, dan render final.

Fitur existing sudah memiliki banyak komponen, tetapi belum ada mode yang menggabungkannya menjadi pipeline **long-form documentary** yang berdiri sendiri.

## 3. Goals

1. Membuat video dokumenter 16:9 dari brief/topik dan/atau beberapa URL sumber.
2. Memanfaatkan AI untuk outline, pemilihan segmen, dan penulisan narasi per bagian.
3. Mendukung stock footage provider Pexels/Pixabay untuk mencari, merekomendasikan, dan mengunduh B-roll yang relevan.
4. Mendukung narasi TTS yang terdengar natural; arsitektur harus siap untuk Chatterbox TTS Bahasa Indonesia.
5. Menjaga pipeline tetap aman untuk video panjang melalui render per segmen/bab dan checkpoint.
6. Tidak mengubah perilaku 6 mode yang sudah ada.
7. Memakai ulang engine existing sebagai library/service sebisa mungkin.

## 4. Non-goals untuk MVP

- Tidak menggantikan YouTube Clipper, Clip+Dub, Dubbing Studio, Clip Cutter, TTS Maker, atau Auto Caption.
- Tidak auto-publish ke YouTube/TikTok/Instagram secara default.
- Tidak menjamin hak cipta footage; tetap ada disclaimer dan kontrol manual.
- Pencarian video panjang otomatis (`ytsearch`/YouTube Data API) tetap fase lanjut; stock footage B-roll Pexels/Pixabay adalah provider terpisah yang boleh dipakai lebih awal jika API key terkonfigurasi.
- Tidak mengubah pipeline portrait 9:16 yang sudah ada.
- Tidak mengharuskan Chatterbox TTS untuk MVP; Edge TTS adalah baseline, Chatterbox adalah provider lanjutan.

## 5. Target pengguna

- **Lazy creator**: ingin hasil video dokumenter tanpa editing manual.
- **Semi-pro editor**: mau kontrol brief, sumber, dan revisi script sebelum render.
- **AI hobbyist**: ingin memanfaatkan 9router/LLM gratisan dan TTS lokal untuk produksi konten.

## 6. User stories

### US-01 — Brief ke video dokumenter

Sebagai kreator malas, saya ingin memasukkan topik seperti “Perbandingan kereta cepat Indonesia vs Jepang” dan beberapa URL sumber, lalu mendapat video dokumenter 16:9 dengan narasi, subtitle, dan BGM opsional.

Acceptance:
- User bisa input brief, durasi target, gaya bahasa, dan daftar URL.
- Sistem menghasilkan outline yang bisa direview sebelum render berat.
- Output akhir adalah file video 16:9 playable.

### US-02 — Review sebelum render

Sebagai editor, saya ingin melihat outline, daftar segmen, sumber clip yang dipilih, dan script per segmen sebelum tombol render final ditekan.

Acceptance:
- Ada tahap review outline/script.
- User bisa regenerate outline/script per segmen.
- User bisa exclude sumber/segmen tertentu.

### US-03 — Multi-source clip selection

Sebagai kreator, saya ingin aplikasi memilih potongan dari beberapa video sumber yang sesuai dengan narasi tiap bab, bukan hanya satu video utuh.

Acceptance:
- Sistem menerima minimal 1 URL dan mendukung multi-URL.
- Setiap segmen output punya referensi sumber, start/end, dan alasan pemilihan.
- User bisa preview clip terpilih.

### US-04 — TTS natural dan sinkron

Sebagai kreator, saya ingin suara narasi terdengar natural dan subtitle mengikuti suara, dengan opsi memakai Chatterbox TTS Indonesia jika tersedia.

Acceptance:
- MVP memakai Edge TTS Indonesia.
- Arsitektur TTS provider memungkinkan Chatterbox tanpa mengubah pipeline video.
- Jika word timing tidak tersedia dari TTS, sistem punya fallback alignment/subtitle.

### US-05 — Aman untuk video panjang

Sebagai user, saya ingin render video 10–20 menit tidak gagal total jika error di tengah; saya bisa resume atau render ulang per bagian.

Acceptance:
- Render dilakukan per segmen/bab.
- Ada session/checkpoint.
- Progress, log, dan cancel tersedia.

### US-06 — Stock footage B-roll dari Pexels/Pixabay

Sebagai kreator malas, saya ingin AI membantu mencari footage B-roll dari Pexels/Pixabay berdasarkan visual intent tiap segmen, lalu merekomendasikan kandidat terbaik untuk saya setujui sebelum dipakai.

Acceptance:
- User bisa mengisi API key Pexels/Pixabay dan `base_url` bila perlu.
- AI membuat query pencarian per segmen dari `visual_intent`/narasi.
- Sistem menampilkan kandidat footage dengan preview/metadata singkat.
- User bisa memilih kandidat; sistem mengunduh aset dan menyimpan license/attribution.

## 7. Functional requirements

### FR-01 Source intake

Sistem harus menerima:
- Satu atau lebih URL video dari platform yang didukung existing Clip Cutter/yt-dlp.
- Metadata opsional: judul manual, channel, deskripsi singkat.
- Mode sumber: `manual_urls`, `stock_footage` (Pexels/Pixabay), dan fase lanjut `auto_search`/`ytsearch`.
- API key Pexels/Pixabay via env/config dan `base_url` opsional untuk endpoint/proxy.

### FR-02 Source preview & screening

Sebelum download penuh, sistem harus bisa menampilkan metadata dan subtitle/heatmap bila tersedia untuk membantu AI shortlist sumber.

### FR-03 Transcription

Sistem harus mengekstrak audio dan menranskripsi sumber memakai provider Whisper-compatible yang sudah dikonfigurasi (`caption_maker`).

### FR-04 Outline generation

Sistem harus membuat outline dokumenter via LLM provider yang dikonfigurasi, default diarahkan ke 9router bila tersedia. Outline minimal berisi: judul, logline, bab, tujuan segmen, target durasi, gaya narasi.

### FR-05 Segment plan

Sistem harus memecah outline menjadi segmen render dengan:
- `segment_id`
- `title`
- `narration_text`
- `target_duration`
- `source_requirements`
- `visual_intent`
- `subtitle_style_hint`

### FR-06 Clip selection

Sistem harus memilih start/end clip dari sumber yang sudah ditranskripsi untuk tiap segmen. Selection harus mempertimbangkan relevansi transcript, visual intent, dan durasi target.

### FR-06A Stock footage discovery (Pexels/Pixabay)

Sistem harus dapat mencari footage B-roll dari provider stock yang dikonfigurasi (Pexels dan/atau Pixabay). AI/LLM hanya menghasilkan query pencarian dan ranking/rekomendasi; download dilakukan lewat API/provider adapter, bukan scraping HTML.

### FR-06B Stock footage candidate review

Untuk tiap segmen, sistem harus menampilkan kandidat footage stock dengan metadata minimal: provider, judul/ID, durasi/resolusi bila ada, URL preview/download, license/attribution, dan alasan rekomendasi.

### FR-06C Stock footage license & attribution

Sistem harus menyimpan metadata license/attribution untuk footage stock yang dipakai dan menuliskannya ke manifest/`data.json` agar output tetap patuh terhadap ketentuan provider.

### FR-07 Timeline assembly 16:9

Sistem harus merakit segmen menjadi video landscape 16:9. Untuk sumber non-16:9, sistem harus menormalkan dengan fit/pad/blur sesuai konfigurasi, bukan portrait crop.

### FR-08 Voiceover

Sistem harus mensintesis narasi per segmen memakai TTS provider terkonfigurasi. Baseline MVP: Edge TTS `id-ID-ArdiNeural`/`id-ID-GadisNeural`. Provider lanjutan: Chatterbox.

### FR-09 Subtitle & caption

Sistem harus menghasilkan subtitle sinkron per segmen dan membakarnya ke video final atau file terpisah sesuai pilihan user.

### FR-10 BGM & mix

Sistem harus mendukung BGM opsional dari URL/file dan pengaturan volume BGM, volume narasi, dan volume ambience original bila dipakai.

### FR-11 Render & concat

Sistem harus render per segmen/bab lalu menggabungkan menjadi video final. Output akhir minimal H.264/AAC, 1920×1080, fps stabil.

### FR-12 Session & resume

Sistem harus menyimpan session data dan artifact per tahap agar user bisa resume setelah cancel/error.

### FR-13 Metadata output

Sistem harus menghasilkan `data.json`/manifest berisi judul, deskripsi, tags, sumber, segmen, durasi, dan status render.

## 8. Non-functional requirements

- GUI tidak boleh freeze: semua download/transcribe/render berjalan di background thread.
- Error harus masuk `error.log` via `utils.logger` dan tampil ramah di UI.
- Config harus lewat `ConfigManager`; secrets tidak boleh di-hardcode.
- Mendukung GPU acceleration opsional; fallback ke CPU encoder.
- Harus hemat RAM untuk video panjang: proses per segmen, bersihkan temp, lazy import berat.
- Harus mendukung cancel di tahap download, transcribe, TTS, dan render.
- Output harus mudah dibuka dari UI.

## 9. Dependencies

- FFmpeg/ffprobe, yt-dlp, Deno melalui `utils/dependency_manager`/helpers.
- Cookies YouTube untuk sumber yang membutuhkan autentikasi.
- AI providers di `config.ai_providers`: minimal LLM untuk outline/script dan Whisper-compatible untuk transkripsi.
- 9router local proxy untuk LLM bila user menginginkan “AI gratisan”.
- Edge TTS untuk baseline voice; Chatterbox untuk provider lokal lanjutan.
- Pexels API dan/atau Pixabay API untuk stock footage B-roll; API key via env/config dan `base_url` opsional.
- Opsional: YouTube Data API/ytsearch untuk auto-search video panjang fase lanjut.

## 10. Risks & mitigations

| Risiko | Dampak | Mitigasi |
|---|---|---|
| Hak cipta footage | Legal/YouTube claim | Manual review, disclaimer, jangan auto-publish, dokumentasikan sumber. |
| YouTube/yt-dlp block | Download gagal | Cookies, retry, fallback metadata/subtitle-only, pesan error jelas. |
| 9router down/model jelek | Outline/script gagal | Provider fallback chain, validasi JSON, retry prompt. |
| Whisper tidak support provider | Transkripsi gagal | Pastikan `caption_maker` diarahkan ke Whisper-compatible; dokumentasikan setting. |
| Chatterbox berat/tidak stabil | TTS gagal/lambat | Provider opsional, queue server, fallback Edge TTS. |
| Render panjang gagal | Video tidak jadi | Render per segmen, checkpoint, concat terakhir. |
| Aspect campuran | Output jelek | Normalisasi 16:9 dengan pad/blur/fit; preview sebelum render. |
| API quota/rate limit Pexels/Pixabay | Stock search/download gagal | Cache kandidat, backoff, batasi jumlah request, fallback ke URL manual. |
| License/attribution stock footage terlewat | Risiko hukum/claim | Simpan license metadata per aset dan tampilkan di manifest/output. |
| `base_url` stock provider salah/proxy tidak stabil | Search/download gagal | Default ke endpoint resmi; validasi URL; error actionable; jangan scraping HTML. |

## 11. Success metrics

- User dapat menghasilkan video dokumenter 16:9 minimal 3 menit dari brief + URL tanpa editing manual.
- Mayoritas error dapat di-resume tanpa mengulang semua tahap.
- Fitur baru tidak menyebabkan regresi pada 6 mode existing.
- Waktu setup minimum: isi brief + tempel URL + review outline + render.

## 12. Rollout plan

- **MVP:** manual multi-URL + stock footage Pexels/Pixabay opsional, 16:9, Edge TTS, subtitle, BGM opsional, render per segmen, session resume.
- **v1.1:** ytsearch/YouTube Data API auto-source suggestion untuk video panjang.
- **v1.2:** Chatterbox TTS provider lokal.
- **v1.3:** polish metadata/title/thumbnail, upload manual opsional.
