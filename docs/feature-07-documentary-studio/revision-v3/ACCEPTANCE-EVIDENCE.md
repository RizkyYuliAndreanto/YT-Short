# Documentary Studio Revision V3 — Acceptance Evidence

## Passed

- Stage 00 contract/import/compile checks.
- Stage 01 source, policy, budget, provider mock checks.
- Stage 02 review-gate, selection, rejection, and render-block checks.
- Stage 03 approval boundary, profile, timeline, and concat compatibility checks.
- Stage 04 subtitle, corrupt-media, cancellation, and manifest checks.
- Stage 05 full-surface Python compile check.

## Command

```powershell
python -m py_compile documentary_browser.py documentary_engine.py documentary_stock.py documentary_tts.py pages\documentary_page.py app.py pages\landing_page_v2.py config\config_manager.py
```

## Pending environment checks

- Interactive opening of Documentary Studio.
- Browser-agent unavailable fallback in a live desktop session.
- Real FFmpeg/ffprobe short-media render.
- Real TTS/provider fallback.
- Six legacy mode navigation smoke.
