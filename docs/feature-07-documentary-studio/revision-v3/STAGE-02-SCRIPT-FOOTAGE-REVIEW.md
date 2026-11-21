# Stage 02 — Script, Footage Plan, and Mandatory Review Gate

## PRD

### Masalah

`run_full_pipeline()` melakukan auto-approve. `approve_footage_plan()` juga
memilih score tertinggi jika user belum memilih kandidat. Ini membatalkan tujuan
review gate V2.

### Hasil wajib

- Script plan tetap dibuat sebelum footage.
- Setiap slot memiliki candidate/evidence/warning/status.
- Kandidat hanya masuk selected assets setelah approval eksplisit.
- User dapat pilih, reject, dan mengganti kandidat.
- Run-all berhenti di review gate kecuali mode auto-approve diaktifkan eksplisit.

### State contract

```text
candidate → selected_pending_review → approved → materialized
candidate → rejected
candidate → unverified
```

`candidate` tidak boleh langsung menjadi `approved`.

## SDLC

1. Perbaiki selection semantics di engine.
2. Pisahkan `select_candidate` dan `approve_candidate`.
3. Tambahkan reject/exclude state.
4. Ubah run-full agar berhenti pada review gate default.
5. Simpan reviewer action, timestamp, dan reason.
6. Tambahkan test untuk bypass prevention.

## Guardrails

- Jangan memilih score tertinggi sebagai approval implisit.
- Jangan menggunakan `auto=True` sebagai default.
- Jangan menghapus candidate dari plan; simpan status rejected.
- LLM hanya membuat query/konteks, bukan menyatakan lisensi aman.
- Kandidat stock tetap `visual_unverified` sampai review yang diwajibkan.
- User override policy harus tercatat di session dan metadata.

## JEV

### File/symbol target

- `documentary_engine.py`: `build_footage_plan`,
  `approve_footage_plan`, `select_clips`, `run_full_pipeline`
- `pages/documentary_page.py`: preview candidate actions

### Test wajib

- belum memilih candidate → tidak ada selected clip
- memilih candidate A → hanya A yang approved
- reject candidate → tidak dirender
- score B lebih tinggi tetapi A dipilih user → A tetap dipakai
- run-full default berhenti pada review gate
- explicit auto-approve tercatat sebagai override
- empty slot menghasilkan `needs_manual_asset`, bukan fake URL

### Verification

```powershell
python -m py_compile documentary_engine.py pages\documentary_page.py
```

Gunakan session fixture tanpa media nyata untuk membuktikan state transition.

### PASS

Tidak ada jalur produksi yang dapat merender candidate tanpa approval yang
sesuai contract. Artifact selected assets memuat action dan review state.

### Handoff

Stage 03 hanya boleh menerima `approved` assets. Jika asset belum approved,
materialize harus menolak dengan error yang jelas.

