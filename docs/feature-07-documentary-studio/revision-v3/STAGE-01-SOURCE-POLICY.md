# Stage 01 — Source Intake, Mode Routing, and Policy

## PRD

### Masalah

URL invalid, source mode, policy, budget, dan provider error belum ditangani
secara konsisten. Manual URL juga dapat diabaikan ketika stock tersedia.

### Hasil wajib

- `manual_urls`, `stock_footage`, dan `mixed` benar-benar berbeda.
- URL invalid tidak menghentikan URL valid.
- Source policy menyimpan alasan, status, dan review state.
- Provider failure terlihat actionable.
- Budget source diterapkan, bukan hanya disimpan di config.

### Acceptance

- Invalid source menghasilkan `status=error` terstruktur.
- Tidak ada source error yang masuk ke download/transcribe.
- Social clip dibatasi sesuai policy.
- Policy warning tidak hilang ketika clip berpindah dari candidate ke selected.
- API key tidak pernah ditulis ke log atau artifact.

## SDLC

1. Tambahkan normalisasi dan validasi URL per source.
2. Pisahkan routing berdasarkan `source_mode`.
3. Terapkan limit source/download/social/backbone.
4. Perbaiki policy classification dan audit fields.
5. Perbaiki error propagation stock provider.
6. Tambahkan test dengan provider mock.

## Guardrails

- Jangan menganggap platform sebagai bukti lisensi.
- Jangan mengubah warning menjadi approved otomatis.
- Jangan mengunduh source yang statusnya error atau tidak selected.
- Jangan swallow exception provider tanpa menyimpan error terstruktur.
- Jangan menaruh URL credential atau API key di log.
- Jangan menambah scraping provider di luar adapter resmi yang sudah disetujui.

## JEV

### File/symbol target

- `documentary_engine.py`: `prepare_sources`, `download_sources`,
  `_source_policy`, `approve_footage_plan`
- `documentary_stock.py`: `StockFootageService.search`
- config documentary source policy dan asset budget

### Test wajib

- 1 valid + 1 invalid URL
- duplicate URL
- masing-masing source mode
- stock provider timeout/401/invalid base URL
- social clip di atas batas
- source policy warning dan override audit
- max source/download/social limit

### Verification

```powershell
python -m py_compile documentary_engine.py documentary_stock.py
```

Jalankan test provider mock tanpa internet. Pastikan hasil error menyebut
provider, kategori error, dan tindakan user.

### PASS

Routing source mode dapat dibuktikan dari test. Source error terisolasi.
Policy dan budget terlihat di session/artifact. Tidak ada silent failure.

### Handoff

Stage 02 menerima source/candidate yang sudah memiliki status policy dan tidak
boleh mengulang klasifikasi policy dengan aturan berbeda.

