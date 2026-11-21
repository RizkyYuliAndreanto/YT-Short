# Acceptance Criteria — Documentary Studio (Feature 07)

Kriteria ini harus dipakai untuk menilai apakah fitur ke-7 sudah layak disebut selesai. Semua skenario mengasumsikan fitur berjalan sebagai mode standalone dan tidak merusak 6 mode existing.

## A. Navigasi & isolasi fitur

| # | Given | When | Then |
|---|---|---|---|
| AC-01 | App dibuka | Landing page tampil | Muncul kartu Documentary Studio sebagai mode ke-7; 6 kartu lama tetap ada. |
| AC-02 | User klik kartu Documentary Studio | Navigasi terjadi | Halaman `pages/documentary_page.py` terbuka dengan wizard Brief → Sources → Outline → Segments → Voice → Render. |
| AC-03 | User selesai/sedang di Documentary Studio | Klik back | Kembali ke landing tanpa error. |
| AC-04 | User membuka mode lain | Navigasi ke mode lama | YouTube Clipper, AI Dubbing Studio, Clip+Dub, Clip Cutter, TTS Maker, Auto Caption tetap berfungsi normal. |

## B. Brief & source intake

| # | Given | When | Then |
|---|---|---|---|
| AC-05 | User mengisi brief, target durasi, gaya, dan 1 URL valid | Analyze sources | Sistem mendeteksi platform, mengambil metadata ringan, dan menampilkan preview/source status. |
| AC-06 | User memasukkan 2–4 URL valid | Analyze sources | Semua sumber divalidasi; user bisa memilih subset sumber. |
| AC-07 | User memasukkan URL invalid/campuran valid-invalid | Analyze sources | URL invalid ditandai jelas; sumber valid tetap bisa diproses; tidak ada crash. |
| AC-08 | Cookies YouTube belum ada | Proses sumber YouTube yang butuh auth | UI menampilkan panduan cookies; error ramah; tidak crash. |

## B2. Stock footage providers (Pexels/Pixabay)

| # | Given | When | Then |
|---|---|---|---|
| AC-33 | Config `documentary.stock_footage` ada | App/engine start | API key dibaca dari env `PEXELS_API_KEY`/`PIXABAY_API_KEY`; `base_url` default resmi dan override tervalidasi. |
| AC-34 | Segment plan punya `visual_intent` | Generate stock candidates | LLM membuat query pencarian per segmen; `plan/stock_candidates.json` tersimpan. |
| AC-35 | API key Pexels/Pixabay valid | Search stock footage | Provider mengembalikan kandidat ternormalisasi: provider, id, preview/download URL, license, attribution, source_page_url. |
| AC-36 | Kandidat stock ada | Select clips | Sistem bisa memilih stock candidate dengan reason; manual URL tetap bisa diprioritaskan bila lebih relevan. |
| AC-37 | User memilih stock candidate | Download/assemble | Aset stock tersimpan; license/attribution masuk manifest dan `data.json`. |
| AC-38 | API key kosong/salah atau `base_url` invalid | Search stock footage | Provider ditandai gagal/nonaktif untuk session; error actionable; flow manual URL tetap berjalan. |

## B3. Source asset policy & lisensi

| # | Given | When | Then |
|---|---|---|---|
| AC-39 | Kandidat berasal dari channel narasi dokumenter/channel lokal non-open/reupload | Select clips | Sistem menandai `policy_warning` atau `rejected_by_policy`; tidak otomatis dipakai sebagai backbone tanpa override user. |
| AC-40 | Kandidat dari channel berita/dokumenter luar negeri, institusi publik, atau arsip open-access | Select clips | Kandidat boleh diprioritaskan sebagai backbone; channel/uploader dan license signal dicatat. |
| AC-41 | Kandidat dari Facebook/TikTok/Instagram untuk aset lokal/third-party | Select clips | Hanya boleh dipakai sebagai B-roll pendek ~5–15 detik; durasi lebih panjang ditandai melanggar policy. |
| AC-42 | Kandidat dari Wikimedia/Wikipedia/Wikivideo/Archive.org dengan lisensi eksplisit | Select clips | Excerpt lebih panjang boleh dipakai; license/attribution wajib masuk manifest dan `data.json`. |
| AC-43 | User override kandidat yang kena policy warning | Render | Override tercatat di session/manifest dengan status review user; tidak disembunyikan. |
| AC-44 | Aset apa pun dipilih | Simpan artifact | `source_policy`/license/attribution minimum tersimpan per aset; LLM tidak menandai “lisensi aman” hanya dari judul. |

## C. Transcription & AI plan

| # | Given | When | Then |
|---|---|---|---|
| AC-09 | Sumber berhasil didownload | Tahap transcribe berjalan | Audio diekstrak dan transcript per sumber tersimpan. |
| AC-10 | Provider LLM 9router aktif | Generate outline | Outline JSON valid berisi judul, logline, bab, segmen, visual intent, target duration. |
| AC-11 | Provider LLM gagal/JSON rusak | Generate outline | Sistem retry/repair terbatas lalu fallback provider atau menampilkan error actionable. |
| AC-12 | Outline berhasil | Lanjut ke segment plan | `segment_plan.json` sesuai schema: segment_id, order, narration_text, target_duration, selected_clips, voice, subtitle, render status. |

## D. Clip selection & assembly 16:9

| # | Given | When | Then |
|---|---|---|---|
| AC-13 | Segment plan siap | Select clips | Setiap segmen punya minimal satu clip kandidat dengan source_id, start, end, reason. |
| AC-14 | Sumber landscape 16:9 | Assemble | Output tetap 1920×1080 tanpa crop portrait aneh. |
| AC-15 | Sumber portrait/vertical | Assemble | Video dinormalisasi ke 16:9 dengan pad/blur/fit; tidak dipaksa crop 9:16. |
| AC-16 | Multi-sumber aspect campuran | Assemble | Semua segmen ternormalisasi ke canvas yang sama sebelum concat. |
| AC-17 | User mereview clips | Sebelum render | UI menampilkan clip terpilih dan alasan pemilihan; user bisa exclude/ganti pada batas wajar MVP. |

## E. TTS, subtitle, BGM

| # | Given | When | Then |
|---|---|---|---|
| AC-18 | Segment plan + draft siap | Generate voice | Tiap segmen punya file audio TTS dan durasi tercatat. |
| AC-19 | Edge TTS normal | Subtitle enabled | Subtitle per segmen dibuat dan timing tidak overlap parah. |
| AC-20 | TTS tidak memberi word timing | Subtitle enabled | Sistem memakai fallback estimated/alignment dan menandai method di manifest. |
| AC-21 | BGM diisi URL/file | Mix audio | BGM tergabung dengan volume sesuai config; jika gagal, error jelas dan video bisa lanjut tanpa BGM sesuai setting. |
| AC-22 | Chatterbox config enabled tapi endpoint mati | Generate voice | Sistem fallback Edge TTS atau menandai segment `tts_failed`; tidak crash total. |

## F. Render, resume, output

| # | Given | When | Then |
|---|---|---|---|
| AC-23 | Semua segmen siap | Render final | `final.mp4` 1920×1080 H.264/AAC playable. |
| AC-24 | Render berjalan | User cancel di tengah | Proses berhenti bersih; session status `cancelled`; artifact valid tidak hilang. |
| AC-25 | Render gagal di segmen ke-3 | Resume/retry | Segmen 1–2 tidak dirender ulang jika valid; segmen 3 bisa retry. |
| AC-26 | Render selesai | Buka output | `data.json`/manifest berisi title, description, tags, duration, sources, segments, provider non-secret, status. |
| AC-27 | Video final dibuat | Quality check | Audio voice jelas, subtitle terbaca, tidak ada aspect ratio berubah jadi portrait. |

## G. Config & security

| # | Given | When | Then |
|---|---|---|---|
| AC-28 | Config lama tanpa `documentary` | App start | Config dimigrasi/default ditambahkan tanpa error; setting existing tidak berubah. |
| AC-29 | API key di `.env`/config | Proses AI | Key tidak muncul di log/UI error; provider tetap resolve dengan benar. |
| AC-30 | User membuka Settings | Cek konfigurasi | Setting existing tidak rusak; namespace `documentary` tidak membingungkan UI lama. |

## H. Regression

| # | Given | When | Then |
|---|---|---|---|
| AC-31 | Setelah implementasi | Buka 6 mode existing | Tidak ada import error, halaman blank, atau perubahan behavior yang tidak diminta. |
| AC-32 | Setelah implementasi | Jalankan `python -m py_compile` file yang diubah | Semua file yang disentuh compile tanpa syntax error. |

## Definition of Done untuk fitur

- Semua AC-01 s.d. AC-38 yang relevan dengan MVP lulus.
- Stock footage Pexels/Pixabay tidak wajib aktif jika API key belum diisi, tetapi jalur config/adapter-nya harus ada dan tidak merusak flow manual URL.
- Tidak ada perubahan perilaku pada 6 mode existing.
- Dokumentasi session/artifact sesuai SRS.
- Guardrail `04_AI_AGENT_GUARDRAILS.md` dipatuhi.
