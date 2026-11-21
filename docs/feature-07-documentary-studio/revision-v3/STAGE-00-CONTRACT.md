# Stage 00 — Contract, State, and Scope

## PRD

### Masalah

Implementasi, SRS, PRD V2, dan acceptance criteria memiliki kontrak yang
berbeda. Agent berikutnya berisiko memperbaiki satu layer tetapi merusak layer
lain.

### Hasil wajib

- Satu state machine pipeline yang eksplisit.
- Satu schema status source, candidate, clip, segment, dan session.
- Keputusan output profile yang konsisten.
- Daftar invariant yang menjadi acuan semua tahap berikutnya.

### Scope kode

Read-only terlebih dahulu. Jika perlu perubahan, hanya:

- `documentary_engine.py`
- `config/config_manager.py`
- artifact schema/test baru yang relevan.

Jangan menyentuh UI, browser, stock provider, atau TTS pada tahap ini.

## SDLC

1. Inventarisasikan method pipeline aktual.
2. Bandingkan dengan PRD/SRS/V2.
3. Tulis schema/state contract dalam test atau helper murni.
4. Tambahkan validation tanpa mengubah alur produksi besar.
5. Jalankan compile dan test deterministic.

## Guardrails

- Jangan membuat fallback yang mengubah error menjadi sukses.
- Jangan menghapus field session lama.
- Semua field baru harus backward compatible saat load.
- `candidate`, `selected`, `approved`, `materialized`, dan `rendered` tidak boleh
  dipakai sebagai sinonim.
- Jangan memutuskan resolusi final tanpa memperbarui acceptance contract.

## JEV

### Input

- `00_MASTER_PLAN.md`
- PRD/SRS/acceptance criteria lama
- `documentary_engine.py`

### Pemeriksaan

- [ ] Pipeline stage aktual terdaftar.
- [ ] Status transition valid terdaftar.
- [ ] Source mode contract tertulis.
- [ ] Selection contract tertulis.
- [ ] Output profile diputuskan.
- [ ] Backward-compatible loader teruji.

### Verification

```powershell
python -m py_compile documentary_engine.py config\config_manager.py
```

Tambahkan/run test deterministic untuk:

- session baru,
- load session lama,
- status candidate versus selected,
- profile output,
- malformed/missing optional fields.

### PASS

Tidak ada kontrak ambigu yang tersisa untuk Stage 01–05. Semua test
deterministic lulus.

### Handoff

Agent berikutnya wajib membaca hasil contract dan tidak boleh membuat field
status baru tanpa memperbarui contract terlebih dahulu.

