# Documentary Studio Revision V3 — Implementation State

## Status

**completed — staged implementation and deterministic verification passed**

Completed stages:

- Stage 00: contract/state/scope
- Stage 01: source intake/policy/budget
- Stage 02: script/footage/review gate
- Stage 03: materialize/duration/16:9 timeline
- Stage 04: voice/render/cancel/resume
- Stage 05: UI/browser/regression hardening

## Verification boundary

Compile and deterministic mock checks passed, including a real request-path
simulation for the local OpenAI-compatible proxy, preservation of API narration,
explicit API failure when fallback is disabled, and explicit fallback mode.
Live provider/API verification, real media end-to-end rendering, and
interactive six-mode navigation remain environment-dependent and are listed as
limitations below.

## Current invariants

- Final canvas is 1920×1080.
- Candidate/unverified/rejected assets cannot be materialized.
- Default run-full stops at `review_required`.
- Explicit auto-approval is recorded as an override.
- Render requires approved assets and valid media artifacts.
- Browser discovery candidates remain unverified until source review.
- Script generation does not silently replace an API failure with template text
  unless `script_first.fallback_enabled` is explicitly enabled.
- The Script Editor and Review panel show the script source and full narration
  text for each segment.

## Known limitations

- Live Pexels/Pixabay, TTS, FFmpeg, and browser-agent verification requires the
  user's configured environment and credentials.
- No real media fixture was committed to the repository.
- UI smoke navigation must be run in a desktop session with CustomTkinter.
