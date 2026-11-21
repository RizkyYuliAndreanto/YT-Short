# Documentary Studio Revision V3 — Decision Log

| Decision | Rationale |
|---|---|
| Final output is always 1920×1080 | Resource mode must not contradict the Documentary contract. |
| Manual sources are the mixed-mode backbone | User-provided sources must not be silently replaced by stock footage. |
| Review is mandatory by default | Candidate score is not user approval or license verification. |
| Auto-approve is explicit and audited | Automation remains available without hiding the override. |
| ffprobe validates media artifacts | File size alone cannot detect corrupt or non-media files. |
| Concat is re-encoded by default | Resolution/FPS/codec/audio compatibility must be deterministic. |
| Browser candidates start unverified | Discovery metadata is not evidence of rights or suitability. |
