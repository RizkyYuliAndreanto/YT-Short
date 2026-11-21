# Stage 01 Execution Report

## Status

**PASS — ready for user approval**

Stage 01 was completed without changing the UI, rendering pipeline, TTS, or
Stage 02 behavior.

## Implemented

- Added source mode normalization and routing for `manual_urls`,
  `stock_footage`, and `mixed`.
- Added URL validation and duplicate detection without aborting valid sources.
- Prevented metadata probing and downloading of manual URLs in
  `stock_footage` mode.
- Enforced source duration and per-run download budgets.
- Prevented errored/deferred sources from entering download or transcription.
- Preserved source policy warning/status fields on source and selected clips.
- Added structured stock provider errors with authentication, quota, timeout,
  and generic provider classifications.
- Exposed the latest provider error through `provider_status()` without
  exposing API keys.
- Logged provider name, error category, and sanitized message through the
  Documentary engine.
- Kept manual sources as the backbone in `mixed` mode whenever a usable manual
  source exists; stock is used only as a fallback when no usable manual source
  exists.

## Verification

Executed successfully:

```powershell
python -m py_compile documentary_engine.py documentary_stock.py
```

Deterministic mock checks passed for:

- valid, invalid, and duplicate URLs;
- manual URL rejection in `stock_footage` mode without metadata probing;
- provider `401` classification as `authentication`;
- provider status exposure;
- all three source modes;
- manual backbone precedence in `mixed` mode.

No internet access or real API key was used by the checks.

## Guardrail review

- Candidate sources are not treated as downloaded artifacts.
- Invalid, errored, and deferred sources are excluded from download/transcribe.
- Stock provider exceptions are no longer silently discarded.
- Provider messages are truncated and do not include configuration secrets.
- Policy warnings remain attached to source/clip records for later review.

## Handoff

Stage 02 is **not started**. It may begin only after explicit user approval.
