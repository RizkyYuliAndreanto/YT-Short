# Stage 00 Contract Specification

Status: `approved-for-implementation`

Dokumen ini mengunci kontrak target. Ini bukan klaim bahwa seluruh kontrak sudah
diimplementasikan; gap implementasi ditangani oleh Stage 01–05.

## 1. Pipeline state machine

```text
created
  -> sources_prepared
  -> sources_downloaded
  -> sources_transcribed
  -> script_plan_ready
  -> footage_plan_ready
  -> review_required
  -> assets_approved
  -> materializing
  -> voice_ready
  -> subtitles_ready
  -> rendering
  -> completed
```

Terminal/error states:

```text
any non-terminal state -> cancelled
any processing state   -> failed
failed                 -> retryable processing state
cancelled              -> retryable processing state
```

Compatibility status lama yang boleh dibaca:

| Status lama | Status canonical |
|---|---|
| `segment_plan_ready` | `script_plan_ready` |
| `footage_selected` | `assets_approved` |
| `script_edited` | `script_plan_ready` |
| `rendering` | `rendering` |
| `completed` | `completed` |
| `failed` | `failed` |
| `cancelled` | `cancelled` |

Loader tidak boleh menghapus status lama dari artifact; normalisasi hanya boleh
dilakukan di memory.

## 2. Source contract

Setiap source memiliki minimal:

```json
{
  "source_id": "src_001",
  "type": "url|local|stock",
  "url": "",
  "provider": "youtube|pexels|pixabay|unknown",
  "platform": "youtube|tiktok|instagram|facebook|stock|unknown",
  "title": "",
  "duration": 0,
  "local_path": "",
  "transcript_path": "",
  "status": "candidate|ready|error|downloaded|transcribed|rejected",
  "selected": false,
  "source_policy": {},
  "error": ""
}
```

Invariant:

- source dengan `status=error` tidak boleh di-download/transcribe.
- source hanya dipakai jika `selected=true`.
- source policy selalu tersimpan, termasuk jika statusnya warning.
- source mode menentukan source yang boleh menjadi backbone.

## 3. Source mode contract

| Mode | Backbone | B-roll |
|---|---|---|
| `manual_urls` | approved manual URL | approved manual URL atau manual fallback |
| `stock_footage` | stock candidate | stock candidate |
| `mixed` | manual URL jika tersedia, lalu archive/approved source | stock dan approved secondary source |

Mode tidak boleh berubah diam-diam karena provider kosong. Jika provider tidak
tersedia, engine mengembalikan status actionable dan tidak mengarang source.

## 4. Candidate and selection contract

Candidate status:

```text
candidate -> selected_pending_review -> approved -> materialized
candidate -> rejected
candidate -> unverified
```

Invariant:

- `candidate` tidak boleh masuk `selected_clips`.
- `selected_pending_review` belum boleh dimaterialize.
- `rejected` tidak boleh dipakai walaupun score-nya paling tinggi.
- `unverified` harus ditampilkan sebagai warning dan tidak boleh auto-approve.
- `approved` harus memiliki `review_action`, `reviewed_at`, dan `review_reason`.
- auto-approve hanya boleh jika konfigurasi eksplisit dan tercatat sebagai
  `review_action=auto_approve`.

## 5. Segment contract

Setiap segment memiliki minimal:

```json
{
  "segment_id": "seg_001",
  "order": 1,
  "title": "",
  "narration_text": "",
  "target_duration": 0,
  "planned_start_sec": 0,
  "planned_end_sec": 0,
  "actual_start_sec": null,
  "actual_end_sec": null,
  "footage_slots": [],
  "selected_clips": [],
  "voice": {},
  "subtitle": {},
  "render": {
    "status": "pending"
  }
}
```

Invariant:

- `planned_*` adalah rencana; `actual_*` berasal dari artifact nyata.
- segment tanpa approved clip harus berstatus `needs_manual_asset`.
- voice duration menjadi input rekonsiliasi timing.
- segment render tidak boleh dianggap selesai hanya karena file ada; file harus
  lolos media validation.

## 6. Session/artifact contract

Session minimal:

```json
{
  "feature": "documentary_studio",
  "session_id": "",
  "status": "created",
  "brief": {},
  "sources": [],
  "outline": {},
  "segments": [],
  "script_plan": {},
  "footage_plan": {},
  "selected_assets": {},
  "render_manifest": {},
  "errors": []
}
```

Artifact canonical:

```text
session_data.json
plan/script_plan.json
plan/footage_plan.json
plan/selected_assets.json
render/render_manifest.json
data.json
final.mp4
```

`data.json`, `session_data.json`, dan `render_manifest.json` harus memiliki
status yang dapat direkonsiliasi. Tidak boleh ada artifact valid yang hilang
hanya karena satu segment gagal.

## 7. Output profile decision

Keputusan Stage 00:

- Semua final output Documentary Studio wajib `1920x1080`.
- Semua output memakai pixel format `yuv420p`.
- `resource_mode` hanya mengatur bitrate, preset, dan strategi processing;
  bukan resolusi final.
- Semua segment harus dinormalisasi ke profile tersebut sebelum concat.

Dengan keputusan ini, acceptance criteria 1920x1080 tetap konsisten dan mode
economy tidak menghasilkan kontrak output yang berbeda.

## 8. Stage boundaries

- Stage 01 boleh mengubah source intake, source policy, dan provider errors.
- Stage 02 boleh mengubah candidate selection dan review gate.
- Stage 03 boleh mengubah materialize, timing, normalization, dan concat check.
- Stage 04 boleh mengubah TTS, subtitle, render, cancel, dan resume.
- Stage 05 boleh mengubah UI callbacks, browser metadata, dan regression.

Tidak ada stage yang boleh mengambil ownership stage lain tanpa memperbarui
kontrak ini dan JEV tahap terkait.

