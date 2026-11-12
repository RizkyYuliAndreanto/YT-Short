"""
Documentary Studio engine — Feature 07.

Standalone long-form documentary pipeline: sources -> transcripts -> outline ->
segment plan -> stock footage candidates -> clip selection -> 16:9 assembly ->
TTS voiceover -> subtitles/BGM -> per-segment render -> concat -> metadata.

This engine reuses existing project services as libraries and never mutates the
six legacy modes.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from clip_cutter_core import ClipCutterCore, detect_platform, format_time, _ensure_yt_dlp
from config.config_manager import detect_provider_from_url, get_api_key_from_env
from documentary_stock import StockFootageService
from documentary_tts import DocumentaryTTS, probe_audio_duration
from utils.helpers import get_app_dir, get_ffmpeg_path, get_ytdlp_path
from video_analyzer import VideoAnalyzer


SUBPROCESS_FLAGS = 0
if sys.platform == "win32":
    SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW


class PipelineCancelled(Exception):
    pass


class DocumentaryEngine:
    """Orchestrator for Documentary Studio."""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        output_dir: Optional[str] = None,
        cookies_path: Optional[str] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[str, float], None]] = None,
        step_callback: Optional[Callable[[int, str, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ):
        self.config = config or {}
        self.doc_cfg = self.config.get("documentary", {}) or {}
        base_output = Path(output_dir or self.config.get("output_dir") or (get_app_dir() / "output"))
        self.root_output = base_output / "documentaries"
        self.cookies_path = cookies_path or str(get_app_dir() / "cookies.txt")
        self.log_callback = log_callback or (lambda msg: print(msg))
        self.progress_callback = progress_callback or (lambda status, progress: None)
        self.step_callback = step_callback or (lambda step_num, step_name, detail="": None)
        self.cancel_check = cancel_check or (lambda: False)

        self.session_id = ""
        self.session_dir = Path()
        self.sources_dir = Path()
        self.plan_dir = Path()
        self.clips_dir = Path()
        self.render_dir = Path()
        self.session_data: Dict[str, Any] = {}
        self.sources: List[Dict[str, Any]] = []
        self.outline: Dict[str, Any] = {}
        self.segments: List[Dict[str, Any]] = []
        self.stock_candidates: List[Dict[str, Any]] = []
        self.render_manifest: Dict[str, Any] = {}
        self.bgm_path = ""

        self.ffmpeg_path = get_ffmpeg_path()
        self.ffprobe_path = self._ffprobe_path()
        self.stock = StockFootageService(self.config)
        self.tts = DocumentaryTTS(self.config)
        self.analyzer = VideoAnalyzer(self.config)
        self._cutter = None
        self._llm_clients = []

    # ------------------------------------------------------------------ utils
    def _ffprobe_path(self) -> str:
        if self.ffmpeg_path and self.ffmpeg_path != "ffmpeg":
            candidate = Path(self.ffmpeg_path).parent / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
            if candidate.exists():
                return str(candidate)
        return "ffprobe"

    def log(self, msg: str):
        self.log_callback(msg)

    def _emit_progress(self, status: str, progress: float):
        try:
            self.progress_callback(status, max(0.0, min(1.0, float(progress))))
        except Exception:
            pass

    def _emit_step(self, step_num: int, step_name: str, detail: str = ""):
        try:
            self.step_callback(step_num, step_name, detail)
        except Exception:
            pass

    def _check_cancel(self):
        if self.cancel_check():
            raise PipelineCancelled("Dibatalkan oleh user")

    def _run(self, cmd: List[str], cwd: Optional[str] = None) -> Tuple[int, str, str]:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            creationflags=SUBPROCESS_FLAGS,
            timeout=3600,
        )
        return result.returncode, result.stdout or "", result.stderr or ""

    def _run_required(self, cmd: List[str], cwd: Optional[str] = None, label: str = "ffmpeg") -> str:
        code, out, err = self._run(cmd, cwd=cwd)
        if code != 0:
            tail = (err or out or "").strip().splitlines()[-12:]
            raise RuntimeError(f"{label} gagal (code {code}): {' | '.join(tail)}")
        return out

    def _probe(self, path: str) -> Dict[str, Any]:
        path = str(path)
        if not path or not Path(path).exists():
            return {}
        code, out, err = self._run([
            self.ffprobe_path, "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", path,
        ])
        if code != 0:
            return {}
        try:
            data = json.loads(out or "{}")
        except Exception:
            return {}
        video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
        audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
        fmt = data.get("format", {})
        fps = 30.0
        if video:
            r = video.get("r_frame_rate", "30/1")
            if "/" in str(r):
                try:
                    num, den = str(r).split("/")
                    fps = float(num) / float(den) if float(den) else 30.0
                except Exception:
                    fps = 30.0
        return {
            "duration": float(fmt.get("duration") or (video or {}).get("duration") or 0.0),
            "width": int((video or {}).get("width") or 0),
            "height": int((video or {}).get("height") or 0),
            "fps": fps,
            "has_audio": audio is not None,
        }

    def _artifact_valid(self, path: Any) -> bool:
        try:
            p = Path(path)
            return p.exists() and p.is_file() and p.stat().st_size > 1024
        except Exception:
            return False

    def _write_json(self, path: Path, data: Any):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _read_json(self, path: Path, default: Any = None) -> Any:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    def _save_session(self):
        self.session_data.update({
            "feature": "documentary_studio",
            "session_id": self.session_id,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "sources": self.sources,
            "outline": self.outline,
            "segments": self.segments,
            "stock_candidates": self.stock_candidates,
            "render_manifest": self.render_manifest,
        })
        self._write_json(self.session_dir / "session_data.json", self.session_data)

    def _cutter_core(self) -> ClipCutterCore:
        if self._cutter is None:
            self._cutter = ClipCutterCore(
                ffmpeg_path=self.ffmpeg_path,
                ytdlp_path=get_ytdlp_path(),
                output_dir=str(self.sources_dir),
                cookies_path=self.cookies_path,
                deno_path=None,
                log_callback=self.log,
                progress_callback=lambda pct, msg: self._emit_progress(msg, pct),
                cancel_check=self.cancel_check,
            )
        return self._cutter

    # ------------------------------------------------------------- session
    def create_session(self, brief: Dict[str, Any]) -> str:
        self.session_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-docu"
        self.session_dir = self.root_output / self.session_id
        self.sources_dir = self.session_dir / "sources"
        self.plan_dir = self.session_dir / "plan"
        self.clips_dir = self.session_dir / "clips"
        self.render_dir = self.session_dir / "render"
        for d in (self.session_dir, self.sources_dir, self.plan_dir, self.clips_dir, self.render_dir):
            d.mkdir(parents=True, exist_ok=True)

        self.session_data = {
            "feature": "documentary_studio",
            "session_id": self.session_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "status": "created",
            "brief": brief or {},
            "sources": [],
            "outline": {},
            "segments": [],
            "stock_candidates": [],
            "render_manifest": {},
            "errors": [],
        }
        self.sources = []
        self.outline = {}
        self.segments = []
        self.stock_candidates = []
        self.render_manifest = {}
        self._save_session()
        return self.session_id

    def load_session(self, session_id: str) -> bool:
        self.session_id = session_id
        self.session_dir = self.root_output / session_id
        if not (self.session_dir / "session_data.json").exists():
            return False
        data = self._read_json(self.session_dir / "session_data.json", {})
        self.session_data = data
        self.sources_dir = self.session_dir / "sources"
        self.plan_dir = self.session_dir / "plan"
        self.clips_dir = self.session_dir / "clips"
        self.render_dir = self.session_dir / "render"
        self.sources = data.get("sources", []) or []
        self.outline = data.get("outline", {}) or {}
        self.segments = data.get("segments", []) or []
        self.stock_candidates = data.get("stock_candidates", []) or []
        self.render_manifest = data.get("render_manifest", {}) or {}
        return True

    def list_sessions(self) -> List[Dict[str, Any]]:
        sessions = []
        if not self.root_output.exists():
            return sessions
        for d in sorted(self.root_output.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            data = self._read_json(d / "session_data.json", {})
            sessions.append({
                "session_id": d.name,
                "status": data.get("status", "unknown"),
                "created_at": data.get("created_at", ""),
                "title": (data.get("outline") or {}).get("title") or (data.get("brief") or {}).get("topic", d.name),
                "dir": str(d),
            })
        return sessions

    def get_review_data(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "session_dir": str(self.session_dir),
            "status": self.session_data.get("status", ""),
            "sources": self.sources,
            "outline": self.outline,
            "segments": self.segments,
            "stock_candidates": self.stock_candidates,
            "render_manifest": self.render_manifest,
            "stock_status": self.stock.provider_status(),
            "tts_status": self.tts.provider_status(),
        }

    # ------------------------------------------------------------- sources
    def discover_sources(self, brief: Optional[Dict[str, Any]] = None, max_results: int = 8, queries: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """AI-assisted source discovery: LLM makes search queries, yt-dlp ytsearch fetches candidate URLs."""
        self._check_cancel()
        brief = brief or self.session_data.get("brief", {}) or {}
        if not queries:
            queries = self._generate_source_queries(brief)
        ydl_mod = _ensure_yt_dlp()
        if ydl_mod is None:
            raise RuntimeError("yt-dlp module tidak tersedia untuk source discovery")
        max_results = max(1, min(int(max_results or 8), 20))
        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "playlistend": max_results,
            "skip_download": True,
        }
        if self.cookies_path and Path(self.cookies_path).exists():
            opts["cookiefile"] = self.cookies_path

        candidates: List[Dict[str, Any]] = []
        seen = set()
        for q in (queries or [])[:4]:
            self._check_cancel()
            q = (q or "").strip()
            if not q:
                continue
            self.log(f"Source discovery query: {q}")
            try:
                with ydl_mod.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(f"ytsearch{max_results}:{q}", download=False)
                for ent in (info.get("entries") or []):
                    if not ent:
                        continue
                    vid = str(ent.get("id") or "")
                    url = ent.get("webpage_url") or ent.get("url") or ""
                    if vid and "youtube.com/watch" not in str(url) and "youtu.be" not in str(url):
                        url = f"https://www.youtube.com/watch?v={vid}"
                    if not url or vid in seen:
                        continue
                    seen.add(vid)
                    candidates.append({
                        "type": "url",
                        "provider": "youtube",
                        "platform": "youtube",
                        "url": url,
                        "title": ent.get("title") or url,
                        "duration": float(ent.get("duration") or 0.0),
                        "thumbnail": ent.get("thumbnail") or "",
                        "query": q,
                        "source": "ai_discovery",
                        "status": "candidate",
                        "selected": True,
                        "local_path": "",
                        "transcript_path": "",
                        "transcript_segments": [],
                    })
                    if len(candidates) >= max_results:
                        break
            except Exception as exc:
                self.log(f"Source discovery gagal untuk '{q}': {str(exc)[:160]}")
            if len(candidates) >= max_results:
                break
        self._emit_progress("Source discovery complete", 1.0)
        return candidates[:max_results]

    def _generate_source_queries(self, brief: Dict[str, Any]) -> List[str]:
        topic = brief.get("topic") or brief.get("title") or ""
        style = brief.get("style") or self.doc_cfg.get("style") or "documentary"
        language = brief.get("language") or self.doc_cfg.get("language") or "id"
        prompt = f"""Buat 3-5 query pencarian YouTube untuk menemukan video sumber dokumenter.
Topik: {topic}
Gaya: {style}
Bahasa narasi nanti: {language}
Query boleh bahasa Indonesia/Inggris, harus spesifik untuk video panjang/edukatif, bukan stock footage.

Output JSON valid:
{{"queries": ["query 1", "query 2", "query 3"]}}"""
        try:
            raw = self._call_llm(prompt, system_prompt="Kamu membuat query pencarian video. Output JSON valid.", max_tokens=800)
            data = self._extract_json(raw)
            queries = data.get("queries", []) if isinstance(data, dict) else []
            queries = [str(q).strip() for q in queries if str(q).strip()]
            if queries:
                return queries[:5]
        except Exception as exc:
            self.log(f"Generate source queries via LLM gagal, pakai fallback: {exc}")

        stop = {"yang", "dengan", "untuk", "dari", "pada", "adalah", "ini", "itu", "dan", "atau", "the", "and", "for", "with", "video", "documentary"}
        words = [w for w in re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\-]{2,}", f"{topic} {style}") if w.lower() not in stop]
        base = " ".join(words[:6]).strip() or str(topic).strip() or "documentary"
        return [base, f"{base} documentary", f"{base} fakta", f"{base} history"][:4]

    def prepare_sources(self, urls: List[str]) -> List[Dict[str, Any]]:
        self._check_cancel()
        self._emit_step(1, "Prepare Sources", f"{len(urls)} URL")
        max_sources = int((self.doc_cfg.get("limits", {}) or {}).get("max_sources", 8) or 8)
        if len(urls) > max_sources:
            self.log(f"Jumlah URL melebihi limit {max_sources}; hanya {max_sources} pertama dipakai")
            urls = urls[:max_sources]
        self.sources = []
        cutter = self._cutter_core()
        for idx, url in enumerate(urls, start=1):
            self._check_cancel()
            url = (url or "").strip()
            if not url:
                continue
            source_id = f"src_{idx:03d}"
            self._emit_progress(f"Analyzing source {idx}/{len(urls)}", (idx - 1) / max(1, len(urls)))
            info = cutter.get_video_info(url)
            platform = detect_platform(url).get("platform", "unknown")
            entry = {
                "source_id": source_id,
                "type": "url",
                "provider": platform,
                "url": url,
                "title": info.get("title") or url,
                "duration": float(info.get("duration") or 0.0),
                "platform": platform,
                "supports_partial": bool(info.get("supports_partial")),
                "thumbnail": info.get("thumbnail") or "",
                "local_path": "",
                "transcript_path": "",
                "transcript_segments": [],
                "status": "ready" if not info.get("error") else "error",
                "error": info.get("error") or "",
                "selected": not bool(info.get("error")),
            }
            self.sources.append(entry)
        self._save_session()
        self._emit_progress("Sources prepared", 1.0)
        return self.sources

    def download_sources(self, selected_only: bool = True) -> List[Dict[str, Any]]:
        self._check_cancel()
        self._emit_step(2, "Download Sources", "")
        candidates = [s for s in self.sources if s.get("type") == "url" and (s.get("selected", True) if selected_only else True)]
        total = max(1, len(candidates))
        for idx, src in enumerate(candidates, start=1):
            self._check_cancel()
            if self._artifact_valid(src.get("local_path")):
                continue
            self._emit_progress(f"Downloading {src.get('title', src['source_id'])}", (idx - 1) / total)
            out_name = f"{src['source_id']}.mp4"
            path, err = self._cutter_core().download_clip(
                src["url"],
                start_time=None,
                end_time=None,
                quality="best",
                use_partial_download=False,
                remove_watermark=False,
                output_filename=out_name,
            )
            if err or not path:
                src["status"] = "download_failed"
                src["error"] = err or "download failed"
                self.log(f"Download gagal {src['source_id']}: {src['error']}")
            else:
                src["local_path"] = path
                src["status"] = "downloaded"
                probe = self._probe(path)
                if probe.get("duration"):
                    src["duration"] = probe["duration"]
                self.log(f"Downloaded {src['source_id']}: {Path(path).name}")
            self._save_session()
        self._emit_progress("Downloads complete", 1.0)
        return self.sources

    def transcribe_sources(self) -> List[Dict[str, Any]]:
        self._check_cancel()
        self._emit_step(3, "Transcribe Sources", "")
        targets = [s for s in self.sources if s.get("type") == "url" and self._artifact_valid(s.get("local_path"))]
        total = max(1, len(targets))
        for idx, src in enumerate(targets, start=1):
            self._check_cancel()
            transcript_path = self.sources_dir / f"{src['source_id']}.transcript.json"
            if self._artifact_valid(transcript_path):
                src["transcript_path"] = str(transcript_path)
                cached = self._read_json(transcript_path, {}) or {}
                src["transcript_segments"] = cached.get("segments", []) if isinstance(cached, dict) else (cached or [])
                src["status"] = "transcribed"
                continue
            self._emit_progress(f"Transcribing {src.get('title', src['source_id'])}", (idx - 1) / total)
            audio_path = self.sources_dir / f"{src['source_id']}_audio.mp3"
            try:
                self.analyzer.extract_audio(src["local_path"], str(audio_path))
                lang = (self.doc_cfg.get("language") or "id")
                segments, full_text = self.analyzer.transcribe_audio(
                    str(audio_path), language=lang, progress_callback=self.log
                )
                seg_dicts = []
                for seg in segments:
                    seg_dicts.append({
                        "text": getattr(seg, "text", "") or "",
                        "start": float(getattr(seg, "start", 0.0) or 0.0),
                        "end": float(getattr(seg, "end", 0.0) or 0.0),
                        "words": getattr(seg, "words", None),
                    })
                self._write_json(transcript_path, {"full_text": full_text, "segments": seg_dicts})
                self._write_srt(self.sources_dir / f"{src['source_id']}.srt", seg_dicts)
                src["transcript_path"] = str(transcript_path)
                src["transcript_segments"] = seg_dicts
                src["status"] = "transcribed"
                src["transcript_chars"] = len(full_text or "")
                self.log(f"Transcript {src['source_id']}: {len(seg_dicts)} segmen")
            except Exception as exc:
                src["status"] = "transcribe_failed"
                src["error"] = str(exc)
                self.log(f"Transcribe gagal {src['source_id']}: {exc}")
            self._save_session()
        self._emit_progress("Transcription complete", 1.0)
        return self.sources

    # ------------------------------------------------------------- LLM
    def _llm_provider_chain(self) -> List[Dict[str, Any]]:
        ai = self.config.get("ai_providers", {}) or {}
        preferred = ["documentary_writer", "script_generator", "highlight_finder", "youtube_title_maker"]
        providers = []
        for key in preferred:
            cfg = ai.get(key)
            if isinstance(cfg, dict) and (cfg.get("base_url") or cfg.get("api_key")):
                providers.append(cfg)
        for key, cfg in ai.items():
            if key in {"caption_maker", "hook_maker"}:
                continue
            if isinstance(cfg, dict) and (cfg.get("base_url") or cfg.get("api_key")) and cfg not in providers:
                providers.append(cfg)
        if not providers:
            providers.append({
                "base_url": "https://api.groq.com/openai/v1",
                "api_key": "",
                "model": "llama-3.3-70b-versatile",
            })
        return providers

    def _call_llm(self, prompt: str, system_prompt: str = "", max_tokens: int = 4000) -> str:
        from openai import OpenAI

        last_error = None
        for cfg in self._llm_provider_chain():
            try:
                base_url = cfg.get("base_url", "")
                model = cfg.get("model", "")
                config_key = cfg.get("api_key", "")
                provider = detect_provider_from_url(base_url)
                api_key = cfg.get("api_key_resolved") or get_api_key_from_env(provider, config_key)
                if not api_key:
                    continue
                client = OpenAI(api_key=api_key, base_url=base_url)
                messages = []
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": prompt})
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.4,
                    max_tokens=max_tokens,
                )
                return (resp.choices[0].message.content or "").strip()
            except Exception as exc:
                last_error = exc
                self.log(f"LLM provider gagal, coba berikutnya: {str(exc)[:120]}")
                continue
        raise RuntimeError(f"Semua LLM provider gagal: {last_error}")

    @staticmethod
    def _extract_json(text: str) -> Any:
        text = (text or "").strip()
        if "```" in text:
            parts = text.split("```")
            for part in parts[1:]:
                part = part.strip()
                if part.lower().startswith("json"):
                    part = part[4:].strip()
                if part.startswith("{") or part.startswith("["):
                    text = part
                    break
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("Response LLM bukan JSON valid")
        return json.loads(text[start:end + 1])

    def _source_summary(self) -> str:
        lines = []
        for s in self.sources:
            lines.append(f"- {s.get('source_id')}: {s.get('title')} ({format_time(s.get('duration') or 0)}) [{s.get('provider')}]")
        return "\n".join(lines) or "- Tidak ada sumber"

    def _transcript_summary(self, max_chars_per_source: int = 1800) -> str:
        parts = []
        for s in self.sources:
            segs = s.get("transcript_segments") or []
            if not segs:
                continue
            text = " ".join((seg.get("text") or "").strip() for seg in segs if seg.get("text"))
            parts.append(f"[{s.get('source_id')}] {text[:max_chars_per_source]}")
        return "\n\n".join(parts) or "Transcript tidak tersedia"

    # ------------------------------------------------------------- outline/plan
    def generate_outline(self) -> Dict[str, Any]:
        self._check_cancel()
        self._emit_step(4, "AI Outline", "")
        brief = self.session_data.get("brief", {}) or {}
        topic = brief.get("topic") or brief.get("title") or "Documentary"
        target_duration = float(brief.get("target_duration_seconds") or self.doc_cfg.get("default_duration_seconds") or 300)
        style = brief.get("style") or self.doc_cfg.get("style") or "documentary"
        language = brief.get("language") or self.doc_cfg.get("language") or "id"

        max_segments = max(3, min(12, int(target_duration // 45)))
        prompt = f"""Buat outline video dokumenter YouTube dalam Bahasa {language}.

Topik: {topic}
Target durasi total: {target_duration:.0f} detik
Gaya: {style}
Sumber video yang tersedia:
{self._source_summary()}

Ringkasan transcript sumber:
{self._transcript_summary()}

Buat JSON valid dengan struktur:
{{
  "title": "judul video",
  "logline": "satu kalimat ringkasan",
  "style": "{style}",
  "language": "{language}",
  "target_duration_seconds": {target_duration:.0f},
  "segments": [
    {{
      "segment_id": "seg_001",
      "order": 1,
      "title": "judul segmen",
      "narration_text": "naskah narasi Bahasa {language} untuk segmen ini",
      "target_duration": 40,
      "visual_intent": "deskripsi visual/B-roll yang dibutuhkan, dalam bahasa Inggris untuk stock search",
      "source_requirements": ["explain", "context"],
      "subtitle_style_hint": "documentary"
    }}
  ]
}}

Aturan:
- Buat {max_segments} segmen; total target_duration harus mendekati {target_duration:.0f} detik.
- narration_text harus natural untuk TTS, tidak terlalu panjang.
- visual_intent harus spesifik dan searchable (contoh: "aerial city traffic night", "close up hands typing code").
- Jangan gunakan markdown, output JSON saja."""

        system = "Kamu adalah scriptwriter dokumenter profesional. Output harus JSON valid tanpa markdown."
        raw = self._call_llm(prompt, system_prompt=system, max_tokens=5000)
        data = self._extract_json(raw)
        self.outline = data if isinstance(data, dict) else {}
        self.segments = self._normalize_segments(self.outline.get("segments", []), target_duration)
        self.outline["segments"] = self.segments
        self._write_json(self.plan_dir / "outline.json", self.outline)
        self._write_json(self.plan_dir / "segment_plan.json", {"segments": self.segments})
        self.session_data["status"] = "segment_plan_ready"
        self._save_session()
        self._emit_progress("Outline & segment plan ready", 1.0)
        return self.outline

    def _normalize_segments(self, raw_segments: List[Dict[str, Any]], target_duration: float) -> List[Dict[str, Any]]:
        normalized = []
        total_target = 0.0
        for idx, seg in enumerate(raw_segments or [], start=1):
            narration = (seg.get("narration_text") or seg.get("text") or "").strip()
            if not narration:
                continue
            target = float(seg.get("target_duration") or seg.get("duration") or 40)
            target = max(10.0, min(180.0, target))
            total_target += target
            normalized.append({
                "segment_id": seg.get("segment_id") or f"seg_{idx:03d}",
                "order": int(seg.get("order") or idx),
                "title": seg.get("title") or f"Segmen {idx}",
                "narration_text": narration,
                "target_duration": target,
                "visual_intent": seg.get("visual_intent") or "",
                "source_requirements": seg.get("source_requirements") or [],
                "subtitle_style_hint": seg.get("subtitle_style_hint") or "documentary",
                "selected_clips": [],
                "voice": {},
                "subtitle": {"enabled": bool(self.doc_cfg.get("subtitle", {}).get("enabled", True)), "mode": "segment"},
                "render": {"status": "pending"},
            })
        if not normalized:
            raise ValueError("Outline tidak menghasilkan segmen narasi")
        # Normalize durations to requested total if wildly off.
        if target_duration and total_target > 0:
            ratio = target_duration / total_target
            if ratio < 0.6 or ratio > 1.6:
                for seg in normalized:
                    seg["target_duration"] = max(10.0, round(seg["target_duration"] * ratio, 1))
        max_segments = int((self.doc_cfg.get("limits", {}) or {}).get("max_segments", 30) or 30)
        if len(normalized) > max_segments:
            self.log(f"Segment plan melebihi limit {max_segments}; segmen dipangkas")
            normalized = normalized[:max_segments]
        return normalized

    # ------------------------------------------------------------- stock footage
    def find_stock_candidates(self) -> List[Dict[str, Any]]:
        self._check_cancel()
        self._emit_step(5, "Stock Footage", "")
        if not self.segments:
            raise RuntimeError("Segment plan belum ada")
        if not self.stock.available_providers():
            self.stock_candidates = []
            self._write_json(self.plan_dir / "stock_candidates.json", [])
            self._emit_progress("Stock footage providers tidak tersedia", 1.0)
            return []
        queries_by_segment = self._generate_stock_queries()
        all_candidates = []
        total = max(1, len(self.segments))
        for idx, seg in enumerate(self.segments, start=1):
            self._check_cancel()
            queries = queries_by_segment.get(seg["segment_id"]) or queries_by_segment.get(str(seg.get("order"))) or []
            if not queries:
                queries = self._fallback_queries(seg)
            seg_candidates = []
            for q in queries[:3]:
                try:
                    seg_candidates.extend(self.stock.search(q, per_page=self.stock.per_segment_candidates))
                except Exception as exc:
                    self.log(f"Stock search gagal untuk '{q}': {exc}")
            # Deduplicate by provider+id and keep top candidates.
            seen = set()
            dedup = []
            for cand in sorted(seg_candidates, key=lambda c: float(c.get("score", 0.0)), reverse=True):
                key = f"{cand.get('provider')}:{cand.get('id')}"
                if key in seen:
                    continue
                seen.add(key)
                cand["segment_id"] = seg["segment_id"]
                dedup.append(cand)
            dedup = dedup[: max(3, self.stock.per_segment_candidates)]
            all_candidates.extend(dedup)
            seg["stock_candidates"] = dedup
            self._emit_progress(f"Stock candidates {idx}/{total}: {seg.get('title')}", (idx - 1) / total)
            self._save_session()
        self.stock_candidates = all_candidates
        self._write_json(self.plan_dir / "stock_candidates.json", all_candidates)
        self._emit_progress("Stock candidates ready", 1.0)
        return all_candidates

    def _generate_stock_queries(self) -> Dict[str, List[str]]:
        if not self.stock.available_providers():
            return {}
        payload = []
        for seg in self.segments:
            payload.append({
                "segment_id": seg["segment_id"],
                "title": seg.get("title"),
                "visual_intent": seg.get("visual_intent"),
                "narration_excerpt": (seg.get("narration_text") or "")[:300],
            })
        prompt = f"""Untuk tiap segmen dokumenter, buat 1-3 search query footage stock dalam bahasa Inggris.
Query harus spesifik, visual, dan cocok untuk Pexels/Pixabay video.

Segmen:
{json.dumps(payload, ensure_ascii=False)}

Output JSON valid:
{{"queries": {{"seg_001": ["query1", "query2"], "seg_002": ["query3"]}}}}"""
        try:
            raw = self._call_llm(prompt, system_prompt="Kamu membuat search query stock footage. Output JSON valid.", max_tokens=2000)
            data = self._extract_json(raw)
            queries = data.get("queries", {}) if isinstance(data, dict) else {}
            return {str(k): [str(q) for q in (v or [])] for k, v in queries.items()}
        except Exception as exc:
            self.log(f"Generate stock queries via LLM gagal, pakai fallback: {exc}")
            return {}

    @staticmethod
    def _fallback_queries(seg: Dict[str, Any]) -> List[str]:
        text = f"{seg.get('visual_intent', '')} {seg.get('title', '')} {seg.get('narration_text', '')[:160]}"
        words = [w for w in re.findall(r"[A-Za-z][A-Za-z\-]{2,}", text) if w.lower() not in {
            "the", "and", "for", "with", "this", "that", "dari", "yang", "untuk", "dengan", "video", "footage", "stock"
        }]
        # Prefer visual_intent words first.
        visual_words = re.findall(r"[A-Za-z][A-Za-z\-]{2,}", seg.get("visual_intent", ""))
        ordered = []
        for w in visual_words + words:
            lw = w.lower()
            if lw not in {x.lower() for x in ordered}:
                ordered.append(w)
        queries = []
        if ordered:
            queries.append(" ".join(ordered[:5]))
            queries.append(" ".join(ordered[:3]))
        if seg.get("title"):
            queries.append(str(seg.get("title"))[:80])
        return [q for q in queries if q.strip()][:3]

    # ------------------------------------------------------------- clip selection
    def select_clips(self) -> List[Dict[str, Any]]:
        self._check_cancel()
        self._emit_step(6, "Select Clips", "")
        if not self.segments:
            raise RuntimeError("Segment plan belum ada")
        usable_sources = [s for s in self.sources if s.get("type") == "url" and self._artifact_valid(s.get("local_path"))]
        total = max(1, len(self.segments))
        for idx, seg in enumerate(self.segments, start=1):
            self._check_cancel()
            self._emit_progress(f"Selecting clips {idx}/{total}: {seg.get('title')}", (idx - 1) / total)
            clips = []
            stock_cands = seg.get("stock_candidates") or []
            # Prefer stock footage when visual_intent clearly needs B-roll and candidates exist.
            if stock_cands and self._should_use_stock(seg):
                cand = stock_cands[0]
                clips.append({
                    "kind": "stock",
                    "provider": cand.get("provider"),
                    "source_id": f"stock_{cand.get('provider')}_{cand.get('id')}",
                    "title": cand.get("title"),
                    "candidate": cand,
                    "start": 0.0,
                    "end": float(seg.get("target_duration") or cand.get("duration") or 30.0),
                    "reason": f"Stock B-roll ({cand.get('provider')}): {cand.get('query') or seg.get('visual_intent')}",
                    "local_path": "",
                })
            else:
                clip = self._choose_source_clip(seg, usable_sources)
                if clip:
                    clips.append(clip)
            seg["selected_clips"] = clips
            self._save_session()
        self._emit_progress("Clip selection complete", 1.0)
        return self.segments

    def _should_use_stock(self, seg: Dict[str, Any]) -> bool:
        # Use stock when segment explicitly asks for b-roll/stock, when there are
        # no usable URL sources, or when sources have no transcripts.
        usable = [s for s in self.sources if s.get("type") == "url" and self._artifact_valid(s.get("local_path"))]
        if not usable:
            return True
        reqs = " ".join(seg.get("source_requirements") or []).lower()
        intent = (seg.get("visual_intent") or "").lower()
        if any(k in reqs for k in ["broll", "b-roll", "stock", "atmosphere", "aerial", "nature"]):
            return True
        if any(k in intent for k in ["aerial", "stock", "b-roll", "broll", "timelapse", "drone"]):
            return True
        if not any(s.get("transcript_segments") for s in usable):
            return True
        return False

    def _choose_source_clip(self, seg: Dict[str, Any], usable_sources: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not usable_sources:
            return None
        target = float(seg.get("target_duration") or 30.0)
        text = f"{seg.get('narration_text', '')} {seg.get('visual_intent', '')} {seg.get('title', '')}".lower()
        keywords = {w for w in re.findall(r"[a-zA-ZÀ-ÿ]{4,}", text) if w not in {
            "yang", "dengan", "untuk", "dari", "pada", "adalah", "ini", "itu", "dan", "atau", "the", "and", "for", "with"
        }}

        best = None
        best_score = -1.0
        for src in usable_sources:
            segs = src.get("transcript_segments") or []
            duration = float(src.get("duration") or 0.0)
            if not duration:
                probe = self._probe(src.get("local_path"))
                duration = float(probe.get("duration") or 0.0)
            if duration <= 0:
                continue

            if segs:
                best_ts = None
                best_hits = -1
                for ts in segs:
                    ts_text = (ts.get("text") or "").lower()
                    hits = sum(1 for kw in keywords if kw in ts_text)
                    if hits > best_hits:
                        best_hits = hits
                        best_ts = ts
                if best_ts is None:
                    best_ts = segs[0]
                start = float(best_ts.get("start") or 0.0)
                win_start = max(0.0, start - target * 0.25)
                win_end = min(duration, win_start + target)
                if win_end - win_start < min(target * 0.5, duration * 0.5):
                    win_start = max(0.0, duration - target)
                    win_end = duration
                score = float(best_hits) + min(2.0, duration / 600.0)
                if score > best_score:
                    best_score = score
                    best = {
                        "kind": "url",
                        "provider": src.get("provider") or src.get("platform"),
                        "source_id": src.get("source_id"),
                        "title": src.get("title"),
                        "local_path": src.get("local_path"),
                        "url": src.get("url"),
                        "start": round(win_start, 3),
                        "end": round(win_end, 3),
                        "reason": f"Transcript match hits={best_hits} dari {src.get('source_id')}",
                    }
            else:
                order = int(seg.get("order") or 1)
                total = max(1, len(self.segments))
                start = duration * ((order - 1) / total)
                end = min(duration, start + target)
                score = 0.1 + min(1.0, duration / 1200.0)
                if score > best_score:
                    best_score = score
                    best = {
                        "kind": "url",
                        "provider": src.get("provider") or src.get("platform"),
                        "source_id": src.get("source_id"),
                        "title": src.get("title"),
                        "local_path": src.get("local_path"),
                        "url": src.get("url"),
                        "start": round(start, 3),
                        "end": round(end, 3),
                        "reason": f"Proporsional window dari {src.get('source_id')} (tanpa transcript)",
                    }
        return best

    # ------------------------------------------------------------- voice/subtitle
    def generate_voice(self) -> List[Dict[str, Any]]:
        self._check_cancel()
        self._emit_step(7, "Voiceover", "")
        if not self.segments:
            raise RuntimeError("Segment plan belum ada")
        total = max(1, len(self.segments))
        for idx, seg in enumerate(self.segments, start=1):
            self._check_cancel()
            text = (seg.get("narration_text") or "").strip()
            if not text:
                continue
            voice_path = self.clips_dir / f"{seg['segment_id']}.voice.mp3"
            voice_json = self.clips_dir / f"{seg['segment_id']}.voice.json"
            if self._artifact_valid(voice_path) and self._artifact_valid(voice_json):
                seg["voice"] = self._read_json(voice_json, {}) or {}
                continue
            self._emit_progress(f"TTS {idx}/{total}: {seg.get('title')}", (idx - 1) / total)
            try:
                tts_provider = getattr(self.tts, "provider_name", "edge_tts")
                if tts_provider == "chatterbox":
                    voice = (self.doc_cfg.get("chatterbox", {}) or {}).get("voice_id")
                else:
                    voice = (self.doc_cfg.get("edge_tts", {}) or {}).get("voice")
                result = self.tts.generate(text, str(voice_path), voice=voice)
                self._write_json(voice_json, result)
                seg["voice"] = result
                self.log(f"Voice {seg['segment_id']}: {result.get('duration', 0):.1f}s via {result.get('provider')}")
            except Exception as exc:
                seg["voice"] = {"error": str(exc), "status": "tts_failed"}
                self.log(f"TTS gagal {seg['segment_id']}: {exc}")
            self._save_session()
        self._emit_progress("Voiceover complete", 1.0)
        return self.segments

    def _word_timings_to_srt_cues(self, word_timings: List[Dict[str, Any]], fallback_text: str, duration: float) -> List[Tuple[float, float, str]]:
        cues = []
        if word_timings:
            words = []
            for w in word_timings:
                txt = (w.get("text") or "").strip()
                if not txt:
                    continue
                start = float(w.get("start") or 0.0)
                dur = float(w.get("duration") or w.get("end", start) - start or 0.2)
                words.append((start, start + dur, txt))
            buf, buf_start, buf_end, buf_text = [], 0.0, 0.0, []
            for start, end, txt in words:
                if buf and (len(" ".join(buf_text + [txt])) > 64 or len(buf_text) >= 9 or start - buf_end > 0.9):
                    cues.append((buf_start, buf_end, " ".join(buf_text)))
                    buf, buf_text = [], []
                if not buf:
                    buf_start = start
                buf_end = end
                buf_text.append(txt)
                buf.append(txt)
            if buf_text:
                cues.append((buf_start, buf_end, " ".join(buf_text)))
            return cues
        # Estimated timing fallback.
        words = (fallback_text or "").split()
        if not words or duration <= 0:
            return [(0.0, duration or 1.0, fallback_text or "")]
        per_word = duration / len(words)
        buf_text, buf_start = [], 0.0
        for i, w in enumerate(words):
            start = i * per_word
            end = start + per_word
            if buf_text and (len(" ".join(buf_text + [w])) > 64 or len(buf_text) >= 9):
                cues.append((buf_start, start, " ".join(buf_text)))
                buf_text, buf_start = [], start
            buf_text.append(w)
        if buf_text:
            cues.append((buf_start, duration, " ".join(buf_text)))
        return cues

    @staticmethod
    def _srt_time(seconds: float) -> str:
        total_ms = int(round(max(0.0, float(seconds)) * 1000))
        h = total_ms // 3600000
        m = (total_ms % 3600000) // 60000
        s = (total_ms % 60000) // 1000
        ms = total_ms % 1000
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    def _write_srt(self, path: Path, segments: List[Dict[str, Any]]):
        lines = []
        for i, seg in enumerate(segments, start=1):
            lines.append(str(i))
            lines.append(f"{self._srt_time(seg.get('start', 0))} --> {self._srt_time(seg.get('end', 0))}")
            lines.append((seg.get("text") or "").strip())
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")

    def write_segment_subtitles(self) -> List[Dict[str, Any]]:
        self._check_cancel()
        self._emit_step(8, "Subtitles", "")
        for idx, seg in enumerate(self.segments, start=1):
            voice = seg.get("voice") or {}
            if voice.get("status") == "tts_failed" or not voice.get("audio_path"):
                continue
            srt_path = self.clips_dir / f"{seg['segment_id']}.srt"
            if self._artifact_valid(srt_path) and not self.doc_cfg.get("subtitle", {}).get("burn_in", True):
                seg.setdefault("subtitle", {})["srt_path"] = str(srt_path)
                continue
            cues = self._word_timings_to_srt_cues(
                voice.get("word_timings") or [],
                seg.get("narration_text") or "",
                float(voice.get("duration") or 0.0),
            )
            seg_dicts = [{"start": a, "end": b, "text": t} for a, b, t in cues]
            self._write_srt(srt_path, seg_dicts)
            seg.setdefault("subtitle", {})["srt_path"] = str(srt_path)
            seg.setdefault("subtitle", {})["alignment_method"] = voice.get("alignment_method", "estimated")
            self._emit_progress(f"Subtitles {idx}/{len(self.segments)}", (idx - 1) / max(1, len(self.segments)))
            self._save_session()
        self._emit_progress("Subtitles complete", 1.0)
        return self.segments

    # ------------------------------------------------------------- assembly/render
    def _materialize_clip(self, clip: Dict[str, Any], seg_id: str, clip_idx: int) -> str:
        kind = clip.get("kind")
        if kind == "stock":
            cand = clip.get("candidate") or {}
            safe_id = re.sub(r"[^A-Za-z0-9_\-]+", "_", str(clip.get("source_id") or f"stock_{clip_idx}"))
            dest = self.sources_dir / f"{safe_id}.mp4"
            if not self._artifact_valid(dest):
                self.stock.download_candidate(cand, str(dest))
            clip["local_path"] = str(dest)
            clip["provider"] = cand.get("provider")
            clip["license"] = cand.get("license")
            clip["attribution"] = cand.get("attribution")
            clip["source_page_url"] = cand.get("source_page_url")
            return str(dest)
        return str(clip.get("local_path") or "")

    def _normalize_clip(self, input_path: str, output_path: Path, start: float, duration: float, width: int, height: int) -> bool:
        if not input_path or not Path(input_path).exists():
            return False
        probe = self._probe(input_path)
        has_audio = bool(probe.get("has_audio"))
        dur = max(0.5, float(duration or probe.get("duration") or 5.0))
        fps = int((self.doc_cfg.get("render", {}) or {}).get("fps", 30) or 30)
        vf = (
            f"[0:v]split=2[bg][fg];"
            f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},gblur=sigma=20[bg2];"
            f"[fg]scale={width}:{height}:force_original_aspect_ratio=decrease[fg2];"
            f"[bg2][fg2]overlay=(W-w)/2:(H-h)/2,fps={fps},setsar=1,format=yuv420p[v]"
        )
        if has_audio:
            af = "[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,volume=0.30[a]"
        else:
            af = f"anullsrc=r=48000:cl=stereo,atrim=duration={dur:.3f},asetpts=PTS-STARTPTS[a]"
        fc = f"{vf};{af}"
        cmd = [
            self.ffmpeg_path, "-y",
            "-ss", f"{max(0.0, start):.3f}",
            "-i", input_path,
            "-t", f"{dur:.3f}",
            "-filter_complex", fc,
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "160k",
            "-movflags", "+faststart",
            str(output_path),
        ]
        try:
            self._run_required(cmd, label="normalize clip")
            return True
        except Exception as exc:
            self.log(f"Normalize gagal: {exc}")
            return False

    def _concat_video_only(self, inputs: List[str], output_path: Path) -> bool:
        if not inputs:
            return False
        if len(inputs) == 1:
            shutil.copy2(inputs[0], output_path)
            return True
        list_path = self.clips_dir / f"{output_path.stem}_list.txt"
        with open(list_path, "w", encoding="utf-8") as f:
            for p in inputs:
                f.write(f"file '{Path(p).as_posix()}'\n")
        cmd = [
            self.ffmpeg_path, "-y", "-f", "concat", "-safe", "0",
            "-i", str(list_path),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "160k",
            "-movflags", "+faststart",
            str(output_path),
        ]
        try:
            self._run_required(cmd, label="concat segment clips")
            return True
        except Exception as exc:
            self.log(f"Concat clip gagal: {exc}")
            return False

    def assemble_segment_video(self, seg: Dict[str, Any]) -> str:
        seg_id = seg["segment_id"]
        video_path = self.clips_dir / f"{seg_id}.video.mp4"
        if self._artifact_valid(video_path):
            return str(video_path)

        width = int(self.doc_cfg.get("render", {}).get("width", 1920) or 1920)
        height = int(self.doc_cfg.get("render", {}).get("height", 1080) or 1080)
        normalized = []
        for cidx, clip in enumerate(seg.get("selected_clips") or [], start=1):
            self._check_cancel()
            src_path = self._materialize_clip(clip, seg_id, cidx)
            if not src_path:
                continue
            start = float(clip.get("start") or 0.0)
            end = float(clip.get("end") or 0.0)
            duration = max(1.0, end - start) if end > start else float(seg.get("target_duration") or 30.0)
            out = self.clips_dir / f"{seg_id}_src{cidx}.mp4"
            if not self._artifact_valid(out):
                if not self._normalize_clip(src_path, out, start, duration, width, height):
                    continue
            normalized.append(str(out))
        if not normalized:
            raise RuntimeError(f"Tidak ada clip valid untuk {seg_id}")
        if not self._concat_video_only(normalized, video_path):
            raise RuntimeError(f"Gagal assemble video {seg_id}")
        return str(video_path)

    def _prepare_bgm(self) -> str:
        bgm_cfg = self.doc_cfg.get("bgm", {}) or {}
        if not bgm_cfg.get("enabled"):
            return ""
        source = (bgm_cfg.get("source") or "").strip()
        if not source:
            return ""
        dest = self.session_dir / "bgm.mp3"
        if self._artifact_valid(dest):
            return str(dest)
        try:
            if source.startswith("http://") or source.startswith("https://"):
                import requests
                with requests.get(source, stream=True, timeout=60) as resp:
                    resp.raise_for_status()
                    with open(dest, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=1024 * 256):
                            if chunk:
                                f.write(chunk)
            else:
                src = Path(source)
                if not src.exists():
                    return ""
                shutil.copy2(src, dest)
            return str(dest) if self._artifact_valid(dest) else ""
        except Exception as exc:
            self.log(f"BGM gagal disiapkan: {exc}")
            return ""

    def render_segment(self, seg: Dict[str, Any]) -> str:
        seg_id = seg["segment_id"]
        final_path = self.render_dir / f"{seg_id}.final.mp4"
        if self._artifact_valid(final_path):
            seg.setdefault("render", {})["status"] = "completed"
            seg["render"]["output"] = str(final_path)
            return str(final_path)

        video_path = self.assemble_segment_video(seg)
        voice = seg.get("voice") or {}
        voice_path = voice.get("audio_path") or str(self.clips_dir / f"{seg_id}.voice.mp3")
        if not self._artifact_valid(voice_path):
            raise RuntimeError(f"Voiceover tidak ditemukan untuk {seg_id}")

        subtitle_cfg = seg.get("subtitle", {}) or {}
        doc_sub_cfg = self.doc_cfg.get("subtitle", {}) or {}
        srt_path = subtitle_cfg.get("srt_path") or ""
        burn_in = bool(doc_sub_cfg.get("burn_in", True))
        use_sub = burn_in and bool(subtitle_cfg.get("enabled", True)) and bool(srt_path) and Path(srt_path).exists()

        inputs = [video_path, voice_path]
        filter_parts = []
        video_label = "0:v"
        if use_sub:
            # subtitles filter needs a relative/simple path; run ffmpeg inside clips dir.
            srt_name = Path(srt_path).name
            filter_parts.append(f"[0:v]subtitles={srt_name}[vout]")
            video_label = "[vout]"

        bgm_path = getattr(self, "bgm_path", "") or self._prepare_bgm()
        self.bgm_path = bgm_path
        bgm_cfg = self.doc_cfg.get("bgm", {}) or {}
        bgm_vol = float(bgm_cfg.get("volume", 0.15) or 0.15)
        source_vol = float(bgm_cfg.get("source_volume", 1.0) or 1.0)

        audio_inputs = ["[0:a]", "[1:a]"]
        filter_parts.append(f"[0:a]volume={source_vol:.2f}[srca]")
        filter_parts.append("[1:a]volume=1.00[voice]")
        mix_labels = ["[srca]", "[voice]"]
        if bgm_path and Path(bgm_path).exists():
            inputs.append(bgm_path)
            filter_parts.append(f"[{len(inputs)-1}:a]volume={bgm_vol:.2f}[bgma]")
            mix_labels.append("[bgma]")
        filter_parts.append(f"{''.join(mix_labels)}amix=inputs={len(mix_labels)}:duration=longest:dropout_transition=0[aout]")

        cmd = [self.ffmpeg_path, "-y"]
        for inp in inputs:
            cmd += ["-i", inp]
        if filter_parts:
            cmd += ["-filter_complex", ";".join(filter_parts)]
        cmd += ["-map", video_label, "-map", "[aout]"]
        render_cfg = self.doc_cfg.get("render", {}) or {}
        bitrate = render_cfg.get("video_bitrate", "8M")
        cmd += [
            "-c:v", "libx264", "-preset", "veryfast", "-b:v", str(bitrate),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            "-shortest",
            str(final_path),
        ]
        self._run_required(cmd, cwd=str(self.clips_dir), label=f"render {seg_id}")
        seg.setdefault("render", {})["status"] = "completed"
        seg["render"]["output"] = str(final_path)
        return str(final_path)

    def render_segments(self) -> List[Dict[str, Any]]:
        self._check_cancel()
        self._emit_step(9, "Render Segments", "")
        if not self.segments:
            raise RuntimeError("Segment plan belum ada")
        # Ensure voice + subtitles exist before rendering.
        self.generate_voice()
        self.write_segment_subtitles()

        total = max(1, len(self.segments))
        self.render_manifest = {"segments": {}, "updated_at": datetime.now().isoformat(timespec="seconds")}
        for idx, seg in enumerate(self.segments, start=1):
            self._check_cancel()
            self._emit_progress(f"Render {idx}/{total}: {seg.get('title')}", (idx - 1) / total)
            try:
                out = self.render_segment(seg)
                self.render_manifest["segments"][seg["segment_id"]] = {
                    "status": "completed",
                    "output": out,
                    "duration": self._probe(out).get("duration", 0.0),
                }
            except PipelineCancelled:
                raise
            except Exception as exc:
                seg.setdefault("render", {})["status"] = "failed"
                seg["render"]["error"] = str(exc)
                self.render_manifest["segments"][seg["segment_id"]] = {"status": "failed", "error": str(exc)}
                self.log(f"Render gagal {seg['segment_id']}: {exc}")
            self._save_session()
        self._write_json(self.render_dir / "render_manifest.json", self.render_manifest)
        self._emit_progress("Segment renders complete", 1.0)
        return self.segments

    def concat_final(self) -> str:
        self._check_cancel()
        self._emit_step(10, "Concat Final", "")
        finals = []
        failed = []
        for seg in self.segments:
            render = seg.get("render") or {}
            out = render.get("output") or str(self.render_dir / f"{seg['segment_id']}.final.mp4")
            if render.get("status") == "failed" or not self._artifact_valid(out):
                failed.append(seg.get("segment_id"))
            else:
                finals.append(out)
        if failed:
            raise RuntimeError(f"Masih ada segmen gagal/belum render: {', '.join(failed)}")
        if not finals:
            raise RuntimeError("Tidak ada segment final yang valid untuk concat")
        final_path = self.session_dir / "final.mp4"
        list_path = self.render_dir / "concat_list.txt"
        with open(list_path, "w", encoding="utf-8") as f:
            for p in finals:
                f.write(f"file '{Path(p).as_posix()}'\n")
        cmd = [
            self.ffmpeg_path, "-y", "-f", "concat", "-safe", "0",
            "-i", str(list_path),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            str(final_path),
        ]
        self._run_required(cmd, label="concat final")
        self.session_data["final_path"] = str(final_path)
        return str(final_path)

    def write_metadata(self) -> Dict[str, Any]:
        self._check_cancel()
        self._emit_step(11, "Metadata", "")
        final_path = self.session_data.get("final_path") or str(self.session_dir / "final.mp4")
        probe = self._probe(final_path) if Path(final_path).exists() else {}
        stock_used = []
        for seg in self.segments:
            for clip in seg.get("selected_clips") or []:
                if clip.get("kind") == "stock":
                    stock_used.append({
                        "segment_id": seg.get("segment_id"),
                        "provider": clip.get("provider"),
                        "title": clip.get("title"),
                        "license": clip.get("license"),
                        "attribution": clip.get("attribution"),
                        "source_page_url": clip.get("source_page_url"),
                    })
        data = {
            "feature": "documentary_studio",
            "session_id": self.session_id,
            "title": (self.outline or {}).get("title") or (self.session_data.get("brief") or {}).get("topic", "Documentary"),
            "logline": (self.outline or {}).get("logline", ""),
            "final_path": final_path,
            "duration": probe.get("duration", 0.0),
            "width": probe.get("width", 0),
            "height": probe.get("height", 0),
            "fps": probe.get("fps", 0.0),
            "sources": self.sources,
            "segments": self.segments,
            "stock_footage_attribution": stock_used,
            "providers": {
                "tts": self.tts.provider_status(),
                "stock": self.stock.provider_status(),
            },
            "status": "completed" if self._artifact_valid(final_path) else "rendering",
            "created_at": self.session_data.get("created_at"),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._write_json(self.session_dir / "data.json", data)
        self.session_data["status"] = "completed" if self._artifact_valid(final_path) else self.session_data.get("status", "rendering")
        self._save_session()
        self._emit_progress("Metadata written", 1.0)
        return data

    # ------------------------------------------------------------- pipeline
    def run_full_pipeline(self, urls: List[str], brief: Dict[str, Any]) -> Dict[str, Any]:
        self.create_session(brief)
        try:
            self.prepare_sources(urls)
            self.download_sources()
            self.transcribe_sources()
            self.generate_outline()
            self.find_stock_candidates()
            self.select_clips()
            self.render_segments()
            self.concat_final()
            data = self.write_metadata()
            return {"success": True, "session_id": self.session_id, "final_path": data.get("final_path"), "data": data}
        except PipelineCancelled:
            self.session_data["status"] = "cancelled"
            self._save_session()
            return {"success": False, "cancelled": True, "session_id": self.session_id}
        except Exception as exc:
            self.session_data["status"] = "failed"
            self.session_data.setdefault("errors", []).append(str(exc))
            self._save_session()
            raise

    def run_render_only(self) -> Dict[str, Any]:
        """Resume/render from existing session state."""
        try:
            self.render_segments()
            self.concat_final()
            data = self.write_metadata()
            return {"success": True, "session_id": self.session_id, "final_path": data.get("final_path"), "data": data}
        except PipelineCancelled:
            self.session_data["status"] = "cancelled"
            self._save_session()
            return {"success": False, "cancelled": True, "session_id": self.session_id}
        except Exception as exc:
            self.session_data["status"] = "failed"
            self.session_data.setdefault("errors", []).append(str(exc))
            self._save_session()
            raise
