# Implementation State — Documentary Studio V2

## Current phase
V2-1 — Core script-first engine + staged UI implemented; verification in progress.

## Completed
- V2 config keys added in `config/config_manager.py`:
  - `documentary.script_first`
  - `documentary.footage_density` per `economy` / `balanced` / `quality`
  - `documentary.coverage_model`
  - `documentary.duration_policy.allow_below_min`
  - `documentary.review_gate`
  - split `documentary.asset_budget` for slots, queries, candidates, stock/backbone/archive/social.
- Engine helpers added in `documentary_engine.py`:
  - `_script_first_cfg()`, `_footage_density_cfg()`, `_coverage_model_cfg()`, `_review_gate_cfg()`, `_duration_policy_cfg()`
  - `_slots_limit_for_segment()`
- `_planned_duration_seconds()` now honors `duration_policy.allow_below_min`, so a 9-minute request is not silently changed to 10 minutes.
- Script-first methods added:
  - `generate_script_plan()`
  - `_normalize_script_plan()`
  - `_finalize_script_segments()`
  - `_normalize_footage_slots()`
  - `_fallback_script_plan()`
  - `build_footage_plan()`
  - `_slot_query_variants()`
  - `_search_slot_candidates()`
  - `_allocate_slot_seconds()`
  - `approve_footage_plan()`
- `_normalize_segments()` now preserves `footage_slots` from LLM output.
- Session artifacts now include:
  - `plan/script_plan.json`
  - `plan/footage_plan.json`
  - `plan/selected_assets.json`
  - `session_data["script_plan"]`, `session_data["footage_plan"]`, `session_data["selected_assets"]`
- `get_review_data()` exposes `script_plan`, `footage_plan`, and `selected_assets`.
- Script-first session persistence fixed: `generate_script_plan()`, `build_footage_plan()`, and `approve_footage_plan()` now keep `session_data["outline"]`, `session_data["segments"]`, `session_data["script_plan"]`, and `self.outline/self.segments` in sync so Load Session restores editable segments.
- Script Editor UI added in `pages/documentary_page.py`:
  - New section `Script Editor` with per-segment editable title + narration textbox.
  - Buttons: `Muat Script`, `Simpan Script`, `Rebuild Footage Plan`.
  - `Simpan Script` writes edits back to `script_plan.json` / `segment_plan.json` and session data.
  - `Rebuild Footage Plan` saves edits then reruns `build_footage_plan()` without regenerating the script.
- UI flow reordered to match script-first logic:
  - `0. AI / LLM Provider` setup first.
  - `1. Konteks Documentary` now has a primary `Generate Script` button beside the brief fields.
  - `2. Script Editor` appears immediately after context/script generation.
  - `3. Footage & Source Search` contains `Build Footage Plan`, `Refresh Preview`, and a scrollable `Footage Preview` area.
  - `4. Approve & Render` keeps optional source buttons plus `Approve Footage`, `Render Final`, `Jalankan Semua`.
- Footage Preview UI added:
  - Per-segment/per-slot candidate cards with thumbnail (`preview_url`/`thumbnail`), provider, duration, score, license, evidence, and a `Pilih`/`Dipilih` button.
  - Manual selection writes `slot["selected_candidate_id"]` and `slot["selected"]` into session segments.
- `approve_footage_plan()` now respects `slot["selected_candidate_id"]`/`slot["selected"]` before falling back to highest score.
- `run_full_pipeline()` uses script-first path when `script_first.enabled` is true; it logs that run-full auto-approves footage for the one-click path.
- UI in `pages/documentary_page.py`:
  - Pipeline button renamed to `3. Script + Footage Plan`.
  - New button `3b. Approve Footage` calls `approve_footage_plan(auto=False)`.
- Verification already run:
  - `python -m py_compile documentary_engine.py documentary_tts.py documentary_stock.py pages/documentary_page.py app.py pages/landing_page_v2.py config/config_manager.py` — OK.
  - Import smoke `documentary_engine`, `pages.documentary_page`, `config.config_manager` — OK.
  - Targeted engine tests for duration policy, density cap, slot preservation, fallback plan, footage plan artifact, approve/no-candidate path, and Load Session restoring `segments`/`script_plan`/`footage_slots` — OK.
  - `pages.documentary_page` import smoke after Script Editor + Footage Preview — OK.
  - Targeted approve test: manual `selected_candidate_id` overrides higher-score candidate — OK.

## In progress
- Live-provider verification is still pending: real 9router `script_plan`, real stock API search, real TTS/render.

## Next actions
1. Test `generate_script_plan()` against configured 9router/OpenAI-compatible provider and inspect `script_plan.json` quality.
2. Test `build_footage_plan()` with real Pexels/Pixabay keys and verify per-slot candidates/evidence.
3. Show footage slot candidates/evidence inside Script Editor or Review UI before `Approve Footage`.
4. Add TTS-aware `reconcile_footage_plan()` so `actual_time_range` is based on voice duration, not only planned range.
5. Add explicit stock `visual_unverified` handling/frame sampling before auto-approve.
6. Add concat compatibility precheck for codec/resolution/FPS before stream-copy concat.
7. Keep social/archive/Wikimedia adapters optional and budgeted; do not let them become backbone by default.

## Blockers / assumptions
- No code blocker known.
- Live tests depend on environment: 9router endpoint/key, Pexels/Pixabay keys, FFmpeg, yt-dlp, and laptop resources.
- Current approve step is slot-level MVP: it selects best candidate per footage slot. Per-candidate manual replace UI is not implemented yet.

## Files touched
- `config/config_manager.py`
- `documentary_engine.py`
- `pages/documentary_page.py`
- `docs/feature-07-documentary-studio/v2-script-first-footage-second/IMPLEMENTATION_STATE.md`
- `docs/feature-07-documentary-studio/v2-script-first-footage-second/DECISION_LOG.md`

## Verification status
- Compile/import smoke: passed.
- Deterministic engine tests: passed.
- Live LLM/stock/render acceptance: not run yet.
