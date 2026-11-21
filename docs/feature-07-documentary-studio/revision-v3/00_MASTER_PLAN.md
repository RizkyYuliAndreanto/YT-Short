# Master Plan — Documentary Studio Revision V3

## Tujuan akhir

Documentary Studio harus menjadi pipeline long-form yang:

1. script-first,
2. footage-second,
3. review user wajib sebelum materialize,
4. source policy dapat diaudit,
5. durasi voice dan video selaras,
6. output landscape konsisten,
7. cancel/resume dapat dipercaya,
8. UI aman untuk operasi background,
9. tidak merusak enam mode existing.

## Urutan tahap dan dependency

```text
Stage 00 Contract
    ↓
Stage 01 Source + Policy
    ↓
Stage 02 Script + Footage Review
    ↓
Stage 03 Materialize + Timeline
    ↓
Stage 04 Voice + Render + Resume
    ↓
Stage 05 UI + Regression + Hardening
```

Tidak boleh mengerjakan tahap berikutnya jika gate tahap sebelumnya FAIL,
kecuali agent hanya melakukan investigasi read-only yang dicatat terpisah.

## Kontrak perilaku final

### Source mode

- `manual_urls`: hanya URL manual yang boleh menjadi sumber utama.
- `stock_footage`: hanya kandidat stock yang boleh dipakai.
- `mixed`: manual URL dipakai sebagai backbone jika tersedia; stock dipakai
  sebagai B-roll sesuai slot.

### Selection

- Kandidat `candidate` tidak boleh dirender.
- Kandidat `selected` harus berasal dari aksi user atau opsi auto-approve yang
  diaktifkan secara eksplisit.
- Kandidat `rejected` tidak boleh dipakai.
- Kandidat tanpa evidence harus berstatus `unverified`.

### Output

- Profile output harus dinyatakan jelas: `1920x1080` atau profile economy yang
  terdokumentasi.
- Semua segmen harus kompatibel sebelum concat.
- `data.json`, `session_data.json`, dan render manifest harus konsisten.

## Prioritas defect

### P0 — wajib sebelum dianggap usable

- bypass review gate,
- auto-select kandidat yang belum direview,
- source mode tidak ditegakkan,
- durasi voice/video tidak sinkron,
- cancel/resume tidak aman,
- operasi Tkinter dari worker thread.

### P1 — wajib sebelum release

- policy override/audit,
- 16:9 contract,
- budget enforcement,
- provider error yang actionable,
- manifest consistency,
- concat compatibility.

### P2 — polish

- preview video/frame,
- outline editor lengkap,
- estimasi biaya/waktu,
- UX nomor tahap dan wording.

## Handoff minimum

Setiap tahap harus meninggalkan:

- status perubahan,
- daftar file yang disentuh,
- test command dan hasil,
- known limitation,
- keputusan yang tidak boleh diubah tahap berikutnya.

