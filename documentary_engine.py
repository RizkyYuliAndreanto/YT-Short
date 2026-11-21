"""
Documentary Studio engine — Feature 07.

Standalone long-form documentary pipeline: sources -> transcripts -> outline ->
segment plan -> stock footage candidates -> clip selection -> 16:9 assembly ->
TTS voiceover -> subtitles/BGM -> per-segment render -> concat -> metadata.

This engine reuses existing project services as libraries and never mutates the
six legacy modes.
"""

import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
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

OPEN_ARCHIVE_HOSTS = (
    "wikipedia.org", "wikimedia.org", "wiktionary.org", "archive.org",
    "nasa.gov", "loc.gov", "europeana.eu", "gutenberg.org",
)
SOCIAL_PLATFORMS = {"tiktok", "instagram", "facebook"}


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
        self._llm_health: Dict[str, Dict[str, Any]] = {}

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

    # ------------------------------------------------------------- source policy
    def _policy_cfg(self) -> Dict[str, Any]:
        return self.doc_cfg.get("source_policy") or {}

    def _policy_enabled(self) -> bool:
        return bool(self._policy_cfg().get("enabled", True))

    def _resource_mode(self) -> str:
        return str(self.doc_cfg.get("resource_mode") or "economy").lower()

    def _source_mode(self) -> str:
        mode = str(self.doc_cfg.get("source_mode") or "mixed").lower().strip()
        return mode if mode in {"manual_urls", "stock_footage", "mixed"} else "mixed"

    def _duration_planner_cfg(self) -> Dict[str, Any]:
        return self.doc_cfg.get("duration_planner") or {}

    def _asset_budget_cfg(self) -> Dict[str, Any]:
        return self.doc_cfg.get("asset_budget") or {}

    def _script_first_cfg(self) -> Dict[str, Any]:
        return self.doc_cfg.get("script_first") or {}

    def _footage_density_cfg(self) -> Dict[str, Any]:
        return self.doc_cfg.get("footage_density") or {}

    def _coverage_model_cfg(self) -> Dict[str, Any]:
        return self.doc_cfg.get("coverage_model") or {}

    def _review_gate_cfg(self) -> Dict[str, Any]:
        return self.doc_cfg.get("review_gate") or {}

    def _duration_policy_cfg(self) -> Dict[str, Any]:
        return self.doc_cfg.get("duration_policy") or {}

    def _slots_limit_for_segment(self) -> int:
        density = self._footage_density_cfg().get(self._resource_mode()) or self._footage_density_cfg().get("economy") or {}
        hard = int((self._asset_budget_cfg().get("max_footage_slots_per_segment", 3) or 3))
        return max(1, min(hard, int(density.get("slots_per_segment_max", 2) or 2)))

    def _planned_duration_seconds(self, brief: Dict[str, Any]) -> float:
        planner = self._duration_planner_cfg()
        default_duration = float(self.doc_cfg.get("default_duration_seconds") or 300)
        try:
            raw = float((brief or {}).get("target_duration_seconds") or planner.get("default_seconds") or default_duration)
        except Exception:
            raw = float(planner.get("default_seconds") or default_duration)
        policy = self._duration_policy_cfg()
        if not planner.get("enabled", True):
            return max(60.0, raw)
        min_sec = float(planner.get("min_seconds", 600) or 600)
        max_sec = float(planner.get("max_seconds", 1800) or 1800)
        if policy.get("allow_below_min", True) and raw < min_sec:
            return max(60.0, raw)
        return max(min_sec, min(max_sec, raw))

    def _render_profile(self) -> Dict[str, Any]:
        render_cfg = self.doc_cfg.get("render", {}) or {}
        mode = self._resource_mode()
        width = int(render_cfg.get("width", 1920) or 1920)
        height = int(render_cfg.get("height", 1080) or 1080)
        if mode == "quality":
            return {
                "width": width,
                "height": height,
                "fps": int(render_cfg.get("fps", 30) or 30),
                "video_bitrate": render_cfg.get("video_bitrate", "8M"),
                "preset": render_cfg.get("preset", "medium"),
                "concat_stream_copy": False,
            }
        if mode == "balanced":
            return {
                "width": width,
                "height": height,
                "fps": int(render_cfg.get("fps", 30) or 30),
                "video_bitrate": "6M",
                "preset": "veryfast",
                "concat_stream_copy": False,
            }
        return {
            "width": width,
            "height": height,
            "fps": int(render_cfg.get("fps", 30) or 30),
            "video_bitrate": "4M",
            "preset": "veryfast",
            "concat_stream_copy": False,
        }

    @staticmethod
    def _url_host(url: str) -> str:
        import urllib.parse
        return (urllib.parse.urlparse(url or "").netloc or "").lower()

    def _policy_platform(self, platform: str, url: str) -> str:
        pf = str(platform or "unknown").lower()
        if pf and pf != "unknown":
            return pf
        host = self._url_host(url)
        if any(domain in host for domain in OPEN_ARCHIVE_HOSTS):
            return "open_archive"
        if "tiktok.com" in host:
            return "tiktok"
        if "instagram.com" in host:
            return "instagram"
        if "youtube.com" in host or "youtu.be" in host:
            return "youtube"
        if "facebook.com" in host or "fb.watch" in host:
            return "facebook"
        return pf or "unknown"

    def _license_signal_for(self, platform: str) -> str:
        if platform == "stock":
            return "stock_provider_license"
        if platform == "open_archive":
            return "explicit_archive_license"
        if platform in SOCIAL_PLATFORMS:
            return "social_platform_standard_review"
        if platform in {"youtube", "youtube_shorts"}:
            return "youtube_channel_review"
        return "manual_review"

    def _source_policy(self, platform: str, url: str, title: str = "", channel: str = "", duration: float = 0.0) -> Dict[str, Any]:
        cfg = self._policy_cfg()
        if not self._policy_enabled():
            return {"enabled": False, "status": "disabled", "intended_use": "manual", "review_status": "not_required", "license_signal": "", "reasons": [], "policy_warning": False}
        pf = self._policy_platform(platform, url)
        social_min = float(cfg.get("social_media_min_clip_seconds", 5) or 5)
        social_max = float(cfg.get("social_media_max_clip_seconds", 15) or 15)
        reasons: List[str] = []
        status = "ok"
        review_status = "pending" if cfg.get("require_user_review", True) else "approved_candidate"

        if pf == "stock":
            intended_use = "stock"
            license_signal = "stock_provider_license"
            status = "ok"
            review_status = "approved_candidate"
        elif pf == "open_archive":
            intended_use = "licensed_archive"
            license_signal = "explicit_archive_license"
            status = "ok"
        elif pf in SOCIAL_PLATFORMS:
            intended_use = "broll_short"
            license_signal = "social_platform_standard_review"
            if duration and duration > social_max:
                reasons.append(f"social_clip_exceeds_{int(social_max)}s_policy")
                status = "warning"
            if duration and duration < social_min:
                reasons.append("social_clip_shorter_than_policy_min")
        elif pf in {"youtube", "youtube_shorts"}:
            intended_use = "backbone_candidate"
            license_signal = "youtube_channel_review"
            blob = f"{channel} {title}".lower()
            if "doczone" in blob or "narasi" in blob:
                reasons.append("possible_narration_documentary_channel")
                status = "warning"
            if any(k in blob for k in ("clip", "reupload", "fans clip", "editan")):
                reasons.append("possible_reupload_or_clipping_channel")
                status = "warning"
        else:
            intended_use = "manual_review"
            license_signal = self._license_signal_for(pf)
            status = "warning"
            reasons.append("platform_policy_unknown")

        return {
            "enabled": True,
            "status": status,
            "intended_use": intended_use,
            "review_status": review_status,
            "license_signal": license_signal,
            "channel_or_account": channel or "",
            "platform": pf,
            "clip_duration_seconds": float(duration or 0.0),
            "reasons": reasons,
            "policy_warning": status == "warning",
        }

    def _apply_clip_policy(self, clip: Dict[str, Any], source: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if clip.get("kind") == "stock":
            cand = clip.get("candidate") or {}
            pol = self._source_policy("stock", cand.get("source_page_url") or "", cand.get("title") or clip.get("title") or "", cand.get("provider") or "", float(cand.get("duration") or 0.0))
            clip["license"] = cand.get("license")
            clip["attribution"] = cand.get("attribution")
            clip["source_page_url"] = cand.get("source_page_url")
        else:
            src = source or {}
            platform = clip.get("provider") or src.get("platform") or src.get("provider") or "unknown"
            channel = src.get("channel_or_account") or src.get("uploader") or ""
            start = float(clip.get("start") or 0.0)
            end = float(clip.get("end") or 0.0)
            duration = max(0.0, end - start)
            pol = self._source_policy(platform, clip.get("url") or src.get("url") or "", clip.get("title") or src.get("title") or "", channel, duration)
            cfg = self._policy_cfg()
            social_max = float(cfg.get("social_media_max_clip_seconds", 15) or 15)
            if self._policy_enabled() and pol.get("platform") in SOCIAL_PLATFORMS and duration > social_max and end > start:
                clip["end"] = round(start + social_max, 3)
                pol["clip_duration_seconds"] = social_max
                pol.setdefault("reasons", []).append("capped_to_social_broll_max")
                pol["status"] = "warning" if pol.get("status") == "ok" else pol.get("status")
                clip["policy_action"] = "capped_to_social_broll"
            src_duration = float(src.get("duration") or 0.0)
            if src_duration > 0 and float(clip.get("end") or 0.0) > src_duration:
                clip["end"] = round(src_duration, 3)
        clip["source_policy"] = pol
        clip["policy_status"] = pol.get("status")
        clip["policy_reasons"] = pol.get("reasons") or []
        clip["intended_use"] = pol.get("intended_use")
        clip["review_status"] = pol.get("review_status")
        clip["license_signal"] = pol.get("license_signal")
        clip["channel_or_account"] = pol.get("channel_or_account") or clip.get("channel_or_account") or ""
        return clip

    def _run(self, cmd: List[str], cwd: Optional[str] = None) -> Tuple[int, str, str]:
        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=SUBPROCESS_FLAGS,
        )
        started = time.monotonic()
        while True:
            self._check_cancel()
            try:
                stdout, stderr = process.communicate(timeout=0.5)
                return process.returncode, stdout or "", stderr or ""
            except subprocess.TimeoutExpired:
                if time.monotonic() - started > 3600:
                    process.terminate()
                    stdout, stderr = process.communicate()
                    raise RuntimeError(f"Command timeout: {cmd[0]}")
            except PipelineCancelled:
                process.terminate()
                process.communicate()
                raise

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
            "video_codec": (video or {}).get("codec_name") or "",
            "audio_codec": (audio or {}).get("codec_name") or "",
        }

    def _artifact_valid(self, path: Any) -> bool:
        try:
            p = Path(path)
            return p.exists() and p.is_file() and p.stat().st_size > 1024
        except Exception:
            return False

    def _media_artifact_valid(self, path: Any, require_audio: bool = False, require_video: bool = False) -> bool:
        if not self._artifact_valid(path):
            return False
        probe = self._probe(str(path))
        if float(probe.get("duration") or 0.0) <= 0:
            return False
        if require_audio and not probe.get("has_audio"):
            return False
        if require_video and (int(probe.get("width") or 0) <= 0 or int(probe.get("height") or 0) <= 0):
            return False
        return True

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
            "llm_health": self.llm_health_summary(),
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
            "script_plan": self.session_data.get("script_plan", {}),
            "footage_plan": self.session_data.get("footage_plan", {}),
            "selected_assets": self.session_data.get("selected_assets", {}),
            "stock_status": self.stock.provider_status(),
            "tts_status": self.tts.provider_status(),
            "llm_health": self.llm_health_summary(),
        }

    # ------------------------------------------------------------- sources
    def discover_stock_sources(self, brief: Optional[Dict[str, Any]] = None, max_results: int = 8) -> List[Dict[str, Any]]:
        """Discover stock footage directly through configured Pexels/Pixabay APIs."""
        self._check_cancel()
        if not self.stock.available_providers():
            raise RuntimeError("Tidak ada provider stock aktif. Isi PEXELS_API_KEY atau PIXABAY_API_KEY.")
        brief = brief or self.session_data.get("brief", {}) or {}
        if not self.session_id:
            self.create_session(brief)
        topic = str(brief.get("topic") or brief.get("title") or "documentary").strip()
        style = str(brief.get("style") or self.doc_cfg.get("style") or "documentary").strip()
        queries = [f"{topic} documentary b-roll", f"{topic} people environment", f"{topic} detail atmosphere"]
        try:
            raw = self._call_llm(
                f"""Buat 3 query pencarian video stock untuk Pexels dan Pixabay.
Topik: {topic}
Gaya: {style}
Query harus berupa adegan visual konkret dalam bahasa Inggris, bukan nama platform,
bukan URL, dan bukan kata umum seperti stock footage.
Output JSON saja: {{"queries":["query 1","query 2","query 3"]}}""",
                system_prompt="Kamu membuat query visual untuk API Pexels/Pixabay. Output JSON valid.",
                max_tokens=500,
                task="stock_discovery_queries",
            )
            parsed = self._extract_json(raw)
            generated = parsed.get("queries", []) if isinstance(parsed, dict) else []
            if generated:
                queries = [str(q).strip() for q in generated if str(q).strip()][:3] or queries
        except Exception as exc:
            self.log(f"Generate stock discovery queries gagal, pakai query deterministik: {exc}")

        source_cap = max(1, min(int(max_results or 8), 20))
        per_page = max(1, min(int(self.stock.per_segment_candidates or 5), source_cap))
        candidates = []
        seen = set()
        for query in queries:
            self._check_cancel()
            for candidate in self.stock.search(query, per_page=per_page):
                key = f"{candidate.get('provider')}:{candidate.get('id')}"
                if key in seen:
                    continue
                seen.add(key)
                item = dict(candidate)
                item["status"] = "candidate"
                item["selected"] = False
                item["source"] = "stock_api_discovery"
                candidates.append(item)
                if len(candidates) >= source_cap:
                    break
            if len(candidates) >= source_cap:
                break
        self.stock_candidates = candidates[:source_cap]
        self._write_json(self.plan_dir / "stock_candidates.json", self.stock_candidates)
        self.session_data["stock_candidates"] = self.stock_candidates
        self._save_session()
        self._emit_progress("Stock API discovery complete", 1.0)
        return self.stock_candidates

    def discover_sources(self, brief: Optional[Dict[str, Any]] = None, max_results: int = 8, queries: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """AI-assisted source discovery: LLM makes search queries, yt-dlp ytsearch fetches candidate URLs."""
        self._check_cancel()
        if self._source_mode() == "stock_footage":
            return self.discover_stock_sources(brief=brief, max_results=max_results)
        brief = brief or self.session_data.get("brief", {}) or {}
        if not queries:
            queries = self._generate_source_queries(brief)
        ydl_mod = _ensure_yt_dlp()
        if ydl_mod is None:
            raise RuntimeError("yt-dlp module tidak tersedia untuk source discovery")
        source_cap = max(1, int(self._asset_budget_cfg().get("max_source_candidates", 12) or 12))
        max_results = max(1, min(int(max_results or 8), 20, source_cap))
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
        query_limit = max(1, min(4, int(self._asset_budget_cfg().get("max_browser_queries_per_run", 8) or 8)))
        for q in (queries or [])[:query_limit]:
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

    def discover_sources_browser(self, brief: Optional[Dict[str, Any]] = None, max_results: int = 8, queries: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Use agent-browser (real Chrome) to discover public video source links."""
        if self._source_mode() == "stock_footage":
            return self.discover_stock_sources(brief=brief, max_results=max_results)
        from documentary_browser import BrowserAssetFinder
        brief = brief or self.session_data.get("brief", {}) or {}
        if not queries:
            queries = self._generate_source_queries(brief)
        query_limit = max(1, min(4, int(self._asset_budget_cfg().get("max_browser_queries_per_run", 8) or 8)))
        queries = (queries or [])[:query_limit]
        discovery_cfg = self.doc_cfg.get("source_discovery", {}) or {}
        finder = BrowserAssetFinder(timeout_seconds=int(discovery_cfg.get("browser_timeout_seconds", 60) or 60))
        if not finder.is_available():
            raise RuntimeError("agent-browser tidak ditemukan di PATH")
        platforms = [str(p).lower() for p in (discovery_cfg.get("platforms") or ["youtube", "tiktok", "instagram", "facebook"])]
        source_cap = max(1, int(self._asset_budget_cfg().get("max_source_candidates", 12) or 12))
        max_results = max(1, min(int(max_results or 8), 20, source_cap))
        candidates: List[Dict[str, Any]] = []
        if "youtube" in platforms:
            candidates.extend(finder.discover_video_sources(queries=queries, max_results=max_results))
        other_platforms = [p for p in platforms if p != "youtube"]
        if other_platforms:
            candidates.extend(finder.discover_media_sources(queries=queries, max_results=max_results, platforms=other_platforms))
        merged: List[Dict[str, Any]] = []
        seen_urls = set()
        for candidate in candidates:
            url = str(candidate.get("url") or "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            merged.append(candidate)
        return merged[:max_results]

    def _generate_source_queries(self, brief: Dict[str, Any]) -> List[str]:
        topic = brief.get("topic") or brief.get("title") or ""
        style = brief.get("style") or self.doc_cfg.get("style") or "documentary"
        language = brief.get("language") or self.doc_cfg.get("language") or "id"
        prompt = f"""Buat 3-5 query pencarian untuk menemukan video sumber dokumenter di YouTube, TikTok, Instagram, Facebook, atau website video publik.
Topik: {topic}
Gaya: {style}
Bahasa narasi nanti: {language}
Query boleh bahasa Indonesia/Inggris, harus spesifik untuk video panjang/edukatif/footage, bukan stock footage.

Output JSON valid:
{{"queries": ["query 1", "query 2", "query 3"]}}"""
        try:
            raw = self._call_llm(prompt, system_prompt="Kamu membuat query pencarian video. Output JSON valid.", max_tokens=800, task="source_queries")
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
        max_duration = float((self.doc_cfg.get("limits", {}) or {}).get("max_source_duration_seconds", 7200) or 7200)
        source_mode = self._source_mode()
        if len(urls) > max_sources:
            self.log(f"Jumlah URL melebihi limit {max_sources}; hanya {max_sources} pertama dipakai")
            urls = urls[:max_sources]
        self.sources = []
        cutter = None if source_mode == "stock_footage" else self._cutter_core()
        seen_urls = set()
        for idx, url in enumerate(urls, start=1):
            self._check_cancel()
            url = (url or "").strip()
            if not url:
                continue
            source_id = f"src_{idx:03d}"
            self._emit_progress(f"Analyzing source {idx}/{len(urls)}", (idx - 1) / max(1, len(urls)))
            normalized_url = url.lower().rstrip("/")
            validation_error = ""
            if normalized_url in seen_urls:
                validation_error = "duplicate_source_url"
            else:
                seen_urls.add(normalized_url)
            if not validation_error:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    validation_error = "invalid_source_url"
            if source_mode == "stock_footage" and not validation_error:
                validation_error = "manual_url_disallowed_in_stock_footage_mode"

            info = {}
            platform = "unknown"
            if not validation_error:
                try:
                    info = cutter.get_video_info(url) or {}
                    platform = detect_platform(url).get("platform", "unknown")
                except Exception as exc:
                    validation_error = f"source_metadata_error: {str(exc)[:180]}"
            entry = {
                "source_id": source_id,
                "type": "url",
                "provider": platform,
                "url": url,
                "title": info.get("title") or url,
                "duration": float(info.get("duration") or 0.0),
                "platform": platform,
                "supports_partial": bool(info.get("supports_partial")),
                "uploader": info.get("uploader") or "",
                "channel_or_account": info.get("uploader") or "",
                "thumbnail": info.get("thumbnail") or "",
                "local_path": "",
                "transcript_path": "",
                "transcript_segments": [],
                "status": "ready" if not (info.get("error") or validation_error) else "error",
                "error": validation_error or info.get("error") or "",
                "selected": not bool(info.get("error") or validation_error) and source_mode != "stock_footage",
            }
            if not validation_error and not info.get("error") and max_duration > 0 and entry["duration"] > max_duration:
                entry["status"] = "error"
                entry["error"] = f"source_duration_exceeds_limit_{int(max_duration)}s"
                entry["selected"] = False
            entry["source_policy"] = self._source_policy(platform, url, entry.get("title") or "", entry.get("channel_or_account") or "", float(entry.get("duration") or 0.0))
            entry["license_signal"] = entry["source_policy"].get("license_signal")
            entry["review_status"] = entry["source_policy"].get("review_status")
            entry["intended_use"] = entry["source_policy"].get("intended_use")
            entry["policy_warning"] = bool(entry["source_policy"].get("policy_warning"))
            policy_platform = entry["source_policy"].get("platform")
            if policy_platform and policy_platform != "unknown":
                entry["platform"] = policy_platform
                entry["provider"] = policy_platform
            self.sources.append(entry)
        self._save_session()
        self._emit_progress("Sources prepared", 1.0)
        return self.sources

    def download_sources(self, selected_only: bool = True) -> List[Dict[str, Any]]:
        self._check_cancel()
        self._emit_step(2, "Download Sources", "")
        if self._source_mode() == "stock_footage":
            self.log("Source mode stock_footage: manual URL download dilewati")
            return self.sources
        candidates = [
            s for s in self.sources
            if s.get("type") == "url"
            and s.get("status") not in {"error", "download_failed", "download_deferred"}
            and (s.get("selected", True) if selected_only else True)
        ]
        max_downloads = int(self._asset_budget_cfg().get("max_downloads_per_run", 12) or 12)
        downloaded_count = sum(1 for s in self.sources if self._artifact_valid(s.get("local_path")))
        total = max(1, len(candidates))
        for idx, src in enumerate(candidates, start=1):
            self._check_cancel()
            if self._media_artifact_valid(src.get("local_path"), require_video=True):
                continue
            if max_downloads > 0 and downloaded_count >= max_downloads:
                src["status"] = "download_deferred"
                src["error"] = f"max_downloads_per_run_reached_{max_downloads}"
                self.log(f"Download ditunda {src['source_id']}: batas run tercapai")
                self._save_session()
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
                downloaded_count += 1
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
        targets = [
            s for s in self.sources
            if s.get("type") == "url"
            and s.get("status") not in {"error", "download_failed", "download_deferred"}
            and self._artifact_valid(s.get("local_path"))
        ]
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
        override = self.doc_cfg.get("llm_override") or {}
        if override.get("enabled") and override.get("base_url") and override.get("model"):
            providers.append({
                "base_url": override.get("base_url"),
                "api_key": "",
                "api_key_env": override.get("api_key_env") or "",
                "model": override.get("model"),
                "_task": "documentary_override",
            })
        for key in preferred:
            cfg = ai.get(key)
            if isinstance(cfg, dict) and (cfg.get("base_url") or cfg.get("api_key")):
                providers.append(dict(cfg, _task=key))
        for key, cfg in ai.items():
            if key in {"caption_maker", "hook_maker"}:
                continue
            if isinstance(cfg, dict) and (cfg.get("base_url") or cfg.get("api_key")) and cfg not in providers:
                providers.append(dict(cfg, _task=key))
        if not providers:
            providers.append({
                "base_url": "https://api.groq.com/openai/v1",
                "api_key": "",
                "model": "llama-3.3-70b-versatile",
                "_task": "fallback",
            })
        return providers

    def _llm_gateway_cfg(self) -> Dict[str, Any]:
        return self.doc_cfg.get("llm_gateway") or {}

    @staticmethod
    def _llm_provider_key(cfg: Dict[str, Any]) -> str:
        return f"{cfg.get('_task') or 'provider'}|{cfg.get('model') or ''}|{cfg.get('base_url') or ''}"

    @staticmethod
    def _classify_llm_error(exc: Exception) -> Tuple[str, bool]:
        text = " ".join(str(exc).split())
        low = text.lower()
        status = getattr(exc, "status_code", None)
        if status is None:
            status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404 or "404" in low or "not_found" in low or "requested entity was not found" in low or "does not exist" in low or "no such model" in low:
            return "model_invalid", False
        if status in (401, 403) or "invalid api key" in low or "unauthorized" in low or "authentication" in low or "forbidden" in low:
            return "auth_error", False
        if status == 429 or "rate limit" in low or "ratelimit" in low or "quota" in low or "resource_exhausted" in low or "insufficient_quota" in low or "too many requests" in low:
            return "rate_limited", True
        if status in (500, 502, 503, 504) or "temporary unavailable" in low or "unavailable" in low or "overloaded" in low or "timeout" in low or "timed out" in low or "connection" in low or "service unavailable" in low:
            return "temporary_unavailable", True
        return "unknown", True

    def _llm_health_mark(self, key: str, cfg: Dict[str, Any], exc: Optional[Exception] = None, success: bool = False):
        now = time.time()
        health = self._llm_health.setdefault(key, {
            "provider": cfg.get("_task") or "provider",
            "model": cfg.get("model") or "",
            "base_url": cfg.get("base_url") or "",
            "failures": 0,
            "cooldown_until": 0.0,
            "last_error_class": "",
            "last_error": "",
        })
        if success:
            health.update({"failures": 0, "cooldown_until": 0.0, "last_error_class": "ok", "last_error": ""})
            return None
        err_class, retryable = self._classify_llm_error(exc or RuntimeError("unknown"))
        health["failures"] = int(health.get("failures", 0)) + 1
        health["last_error_class"] = err_class
        health["last_error"] = " ".join(str(exc).split())[:180]
        cooldown = float(self._llm_gateway_cfg().get("cooldown_seconds", 120) or 120)
        if err_class in ("model_invalid", "auth_error"):
            health["cooldown_until"] = float("inf")
        elif err_class == "rate_limited":
            health["cooldown_until"] = now + cooldown * 2
        elif retryable:
            health["cooldown_until"] = now + cooldown * min(3, int(health["failures"]))
        else:
            health["cooldown_until"] = now + cooldown
        return err_class, retryable

    def llm_health_summary(self) -> List[Dict[str, Any]]:
        now = time.time()
        out = []
        for health in self._llm_health.values():
            cd = float(health.get("cooldown_until") or 0.0)
            if cd == float("inf"):
                remaining = None
                active = True
            else:
                remaining = max(0.0, cd - now)
                active = remaining > 0
            failures = int(health.get("failures", 0) or 0)
            out.append({
                "provider": health.get("provider"),
                "model": health.get("model"),
                "base_url": health.get("base_url"),
                "status": "cooldown" if active else ("ok" if failures == 0 else "degraded"),
                "failures": failures,
                "cooldown_remaining_seconds": remaining,
                "last_error_class": health.get("last_error_class") or "",
                "last_error": health.get("last_error") or "",
            })
        return out

    def _llm_cache_path(self) -> Optional[Path]:
        if not self.session_id:
            return None
        return self.session_dir / "llm_cache.json"

    @staticmethod
    def _llm_cache_key(task: str, prompt: str, system_prompt: str) -> str:
        digest = hashlib.sha256(f"{system_prompt}\n{prompt}".encode("utf-8", "ignore")).hexdigest()
        return f"{task}:{digest}"

    def _llm_cache_get(self, task: str, prompt: str, system_prompt: str) -> Optional[str]:
        path = self._llm_cache_path()
        if not path or not path.exists():
            return None
        data = self._read_json(path, {}) or {}
        return data.get(self._llm_cache_key(task, prompt, system_prompt))

    def _llm_cache_set(self, task: str, prompt: str, system_prompt: str, response: str):
        path = self._llm_cache_path()
        if not path or not response:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self._read_json(path, {}) or {}
        data[self._llm_cache_key(task, prompt, system_prompt)] = response
        self._write_json(path, data)

    def _resolve_llm_api_key(self, cfg: Dict[str, Any]) -> str:
        if cfg.get("api_key_resolved"):
            return str(cfg.get("api_key_resolved"))
        env_name = str(cfg.get("api_key_env") or "").strip()
        if env_name:
            val = os.environ.get(env_name)
            if val:
                return val
        override = self.doc_cfg.get("llm_override") or {}
        if (override.get("base_url") or "") == (cfg.get("base_url") or "") and override.get("api_key_env"):
            val = os.environ.get(str(override.get("api_key_env")))
            if val:
                return val
        provider = detect_provider_from_url(cfg.get("base_url", ""))
        return get_api_key_from_env(provider, cfg.get("api_key", ""))

    def llm_endpoints(self, max_endpoints: int = 4, base_url: str = "") -> List[Dict[str, Any]]:
        manual = []
        base_url = (base_url or "").strip()
        if base_url:
            manual.append({"label": "manual", "task": "manual", "base_url": base_url, "model": "", "_task": "manual"})
        seen = set()
        out = []
        for cfg in manual + self._llm_provider_chain():
            base_url = cfg.get("base_url") or ""
            if not base_url or base_url in seen:
                continue
            seen.add(base_url)
            out.append({
                "label": cfg.get("_task") or "provider",
                "task": cfg.get("_task") or "",
                "base_url": base_url,
                "model": cfg.get("model") or "",
            })
            if len(out) >= max(1, int(max_endpoints or 4)):
                break
        return out

    def list_llm_models(self, max_endpoints: int = 3, base_url: str = "") -> List[Dict[str, Any]]:
        from openai import OpenAI
        results = []
        endpoint_limit = 1 if (base_url or "").strip() else max_endpoints
        for ep in self.llm_endpoints(max_endpoints=endpoint_limit, base_url=base_url):
            base_url = ep.get("base_url") or ""
            cfg = next((c for c in self._llm_provider_chain() if (c.get("base_url") or "") == base_url), {"base_url": base_url})
            api_key = self._resolve_llm_api_key(cfg)
            item = dict(ep)
            item.update({"ok": False, "models": [], "error": "", "error_class": ""})
            if not api_key:
                item["error"] = "API key tidak ditemukan untuk endpoint ini"
                item["error_class"] = "no_key"
                results.append(item)
                continue
            try:
                client = OpenAI(api_key=api_key, base_url=base_url, timeout=30, max_retries=0)
                resp = client.models.list()
                models = [str(getattr(m, "id", m)) for m in (getattr(resp, "data", None) or [])]
                item["models"] = sorted({m for m in models if m})
                item["ok"] = True
            except Exception as exc:
                err_class, _ = self._classify_llm_error(exc)
                item["error"] = " ".join(str(exc).split())[:220]
                item["error_class"] = err_class
            results.append(item)
        return results

    def check_llm_models(self, base_url: str, models: List[str], max_models: int = 12, progress_callback=None) -> List[Dict[str, Any]]:
        from openai import OpenAI
        base_url = (base_url or "").strip()
        cfg = next((c for c in self._llm_provider_chain() if (c.get("base_url") or "") == base_url), {"base_url": base_url, "model": "", "_task": "manual"})
        api_key = self._resolve_llm_api_key(cfg)
        probe_models = [str(m).strip() for m in (models or []) if str(m).strip()][:max(1, int(max_models or 12))]
        total = len(probe_models)

        def emit(result, index):
            if not progress_callback:
                return
            try:
                progress_callback(result, index, total)
            except Exception:
                pass

        if not api_key:
            results = [{"model": m, "ok": False, "error_class": "no_key", "error": "API key tidak ditemukan", "latency_ms": 0} for m in probe_models]
            for idx, result in enumerate(results, 1):
                emit(result, idx)
            return results
        gateway = self._llm_gateway_cfg()
        probe_timeout = float(gateway.get("probe_timeout_seconds", gateway.get("timeout_seconds", 60)) or 60)
        probe_max_tokens = int(gateway.get("probe_max_tokens", 16) or 16)
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=probe_timeout, max_retries=0)
        results = []
        for index, model in enumerate(probe_models, 1):
            emit({"model": model, "ok": None, "error_class": "testing", "error": "sedang mengetes", "latency_ms": 0}, index)
            started = time.time()
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "Kamu adalah model uji. Jawab hanya JSON valid."},
                        {"role": "user", "content": 'Jawab tepat: {"ok": true}'},
                    ],
                    temperature=0,
                    max_tokens=probe_max_tokens,
                )
                content = (resp.choices[0].message.content or "").strip()
                result = {"model": model, "ok": bool(content), "error_class": "ok" if content else "empty_response", "error": "" if content else "empty response", "latency_ms": int((time.time() - started) * 1000)}
            except Exception as exc:
                err_class, _ = self._classify_llm_error(exc)
                result = {"model": model, "ok": False, "error_class": err_class, "error": " ".join(str(exc).split())[:220], "latency_ms": int((time.time() - started) * 1000)}
            results.append(result)
            emit(result, index)
        return results

    def _call_llm(self, prompt: str, system_prompt: str = "", max_tokens: int = 4000, task: str = "general") -> str:
        from openai import OpenAI

        gateway = self._llm_gateway_cfg()
        if gateway.get("cache_enabled", True):
            cached = self._llm_cache_get(task, prompt, system_prompt)
            if cached:
                self.log(f"LLM cache hit untuk task '{task}'")
                self._emit_progress(f"API/cache siap: {task}", 0.35)
                return cached

        timeout = float(gateway.get("timeout_seconds", 60) or 60)
        attempts = max(1, int(gateway.get("max_attempts_per_provider", 2) or 2))
        backoff_base = float(gateway.get("backoff_base_seconds", 2.0) or 2.0)
        backoff_max = float(gateway.get("backoff_max_seconds", 8.0) or 8.0)
        jitter = float(gateway.get("jitter_seconds", 1.0) or 0.0)

        last_error = None
        summaries: List[str] = []
        for cfg in self._llm_provider_chain():
            key = self._llm_provider_key(cfg)
            health = self._llm_health.get(key) or {}
            cooldown_until = float(health.get("cooldown_until") or 0.0)
            if cooldown_until and cooldown_until > time.time():
                summaries.append(f"{cfg.get('_task') or 'provider'}:cooldown")
                continue

            provider_label = cfg.get("_task") or cfg.get("model") or cfg.get("base_url") or "unknown"
            base_url = cfg.get("base_url", "")
            model = cfg.get("model", "")
            provider = detect_provider_from_url(base_url)
            api_key = self._resolve_llm_api_key(cfg)
            local_proxy = any(host in str(base_url).lower() for host in ("localhost", "127.0.0.1", "::1"))
            if not api_key and not local_proxy:
                summaries.append(f"{provider_label}:no_key")
                continue
            if not api_key and local_proxy:
                api_key = "local-proxy"

            for attempt in range(1, attempts + 1):
                try:
                    self._emit_progress(
                        f"API request: {task} ({provider_label}) percobaan {attempt}/{attempts}",
                        0.10,
                    )
                    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)
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
                    result = (resp.choices[0].message.content or "").strip()
                    self._llm_health_mark(key, cfg, success=True)
                    self._emit_progress(f"API response diterima: {task}", 0.65)
                    if gateway.get("cache_enabled", True):
                        self._llm_cache_set(task, prompt, system_prompt, result)
                    return result
                except Exception as exc:
                    last_error = exc
                    err_class, retryable = self._llm_health_mark(key, cfg, exc)
                    err_text = " ".join(str(exc).split())[:180]
                    self.log(f"LLM task '{task}' provider {provider_label} attempt {attempt}/{attempts}: {err_class} {err_text}")
                    self._emit_progress(f"API gagal: {task} ({err_class})", 0.20)
                    if not retryable or attempt >= attempts:
                        break
                    sleep_s = min(backoff_max, backoff_base * attempt) + random.uniform(0, jitter)
                    time.sleep(sleep_s)
            health = self._llm_health.get(key) or {}
            summaries.append(f"{provider_label}:{health.get('last_error_class') or 'failed'}")
        raise RuntimeError(f"Semua LLM provider gagal untuk task '{task}': {'; '.join(summaries) or last_error}")

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
        target_duration = self._planned_duration_seconds(brief)
        style = brief.get("style") or self.doc_cfg.get("style") or "documentary"
        language = brief.get("language") or self.doc_cfg.get("language") or "id"

        planner = self._duration_planner_cfg()
        seg_min = max(30.0, float(planner.get("segment_min_seconds", 45) or 45))
        planner_max_segments = max(4, int(planner.get("max_segments", 14) or 14))
        limits_max_segments = int((self.doc_cfg.get("limits", {}) or {}).get("max_segments", 30) or 30)
        max_segments = max(4, min(planner_max_segments, limits_max_segments, int(target_duration // seg_min)))
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
      "clip_context": {{"narrative_role": "cause_pressure", "viewer_should_feel": "tekanan", "setting": "urban", "time_of_day": "night", "shot_types": ["wide", "medium"], "avoid": ["unrelated"], "sensitivity": ["no_brand_focus"]}},
      "source_requirements": ["explain", "context"],
      "subtitle_style_hint": "documentary"
    }}
  ]
}}

Aturan:
- Buat {max_segments} segmen; total target_duration harus mendekati {target_duration:.0f} detik.
- narration_text harus natural untuk TTS, tidak terlalu panjang.
- visual_intent harus spesifik dan searchable (contoh: "aerial city traffic night", "close up hands typing code").
- clip_context menentukan relevansi naratif: narrative_role, emosi penonton, setting, time_of_day, shot_types, avoid, sensitivity. Judul klip tidak boleh jadi satu-satunya alasan relevansi.
- Jangan gunakan markdown, output JSON saja."""

        system = "Kamu adalah scriptwriter dokumenter profesional. Output harus JSON valid tanpa markdown."
        raw = self._call_llm(prompt, system_prompt=system, max_tokens=5000, task="outline")
        data = self._extract_json(raw)
        self.outline = data if isinstance(data, dict) else {}
        self.segments = self._normalize_segments(self.outline.get("segments", []), target_duration)
        self.outline["segments"] = self.segments
        self.outline["duration_plan"] = {
            "target_duration_seconds": target_duration,
            "segment_count": len(self.segments),
            "resource_mode": self._resource_mode(),
            "asset_budget": self._asset_budget_cfg(),
        }
        self.session_data["duration_plan"] = self.outline["duration_plan"]
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
            seg_max = float((self._duration_planner_cfg().get("segment_max_seconds", 180) or 180))
            target = max(10.0, min(seg_max, target))
            total_target += target
            normalized.append({
                "segment_id": seg.get("segment_id") or f"seg_{idx:03d}",
                "order": int(seg.get("order") or idx),
                "title": seg.get("title") or f"Segmen {idx}",
                "narration_text": narration,
                "target_duration": target,
                "visual_intent": seg.get("visual_intent") or "",
                "clip_context": seg.get("clip_context") or {},
                "footage_slots": seg.get("footage_slots") or [],
                "narrative_role": seg.get("narrative_role") or (seg.get("clip_context") or {}).get("narrative_role") or "",
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
                seg_max = float((self._duration_planner_cfg().get("segment_max_seconds", 180) or 180))
                for seg in normalized:
                    seg["target_duration"] = max(10.0, min(seg_max, round(seg["target_duration"] * ratio, 1)))
        limits_max = int((self.doc_cfg.get("limits", {}) or {}).get("max_segments", 30) or 30)
        planner_max = int((self._duration_planner_cfg().get("max_segments", 14) or 14))
        max_segments = min(limits_max, planner_max)
        if len(normalized) > max_segments:
            self.log(f"Segment plan melebihi limit {max_segments}; segmen dipangkas")
            normalized = normalized[:max_segments]
        return normalized

    # ------------------------------------------------------------- script-first V2
    def generate_script_plan(self, brief: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self._check_cancel()
        self._emit_step(4, "Script Plan", "")
        self._emit_progress("Script: menyiapkan prompt", 0.05)
        if not self.session_id:
            self.create_session(brief or {})
        brief = brief or self.session_data.get("brief", {}) or {}
        target_duration = self._planned_duration_seconds(brief)
        planner = self._duration_planner_cfg()
        seg_min = max(30.0, float(planner.get("segment_min_seconds", 45) or 45))
        max_segments = max(4, min(int(planner.get("max_segments", 14) or 14), int((self.doc_cfg.get("limits", {}) or {}).get("max_segments", 30) or 30)))
        segment_count = max(4, min(max_segments, int(target_duration // seg_min) or max_segments))
        density = self._footage_density_cfg().get(self._resource_mode()) or self._footage_density_cfg().get("economy") or {}
        slots_min = int(density.get("slots_per_segment_min", 1) or 1)
        slots_max = int(density.get("slots_per_segment_max", 2) or 2)
        coverage = self._coverage_model_cfg()
        topic = brief.get("topic") or brief.get("title") or "Documentary"
        style = brief.get("style") or self.doc_cfg.get("style") or "documentary"
        language = brief.get("language") or self.doc_cfg.get("language") or "id"

        prompt = f"""Buat SCRIPT PLAN video dokumenter YouTube dalam Bahasa {language}.
Topik: {topic}
Target durasi total: {target_duration:.0f} detik
Gaya: {style}
Jumlah segmen yang harus dibuat: {segment_count}
Coverage model target: backbone={coverage.get('backbone_ratio',0.35)}, broll={coverage.get('broll_ratio',0.35)}, archive={coverage.get('archive_ratio',0.10)}, stock={coverage.get('stock_ratio',0.20)}
Footage slots per segmen: minimal {slots_min}, maksimal {slots_max}.

Output JSON valid tanpa markdown:
{{
  "title": "judul video",
  "logline": "satu kalimat",
  "segments": [
    {{
      "segment_id": "seg_001",
      "order": 1,
      "planned_start_sec": 0,
      "planned_end_sec": 75,
      "title": "judul segmen",
      "narration_text": "naskah narasi untuk TTS",
      "target_duration": 75,
      "visual_intent": "visual utama dalam bahasa Inggris",
      "clip_context": {{"narrative_role":"problem_setup","viewer_should_feel":"tekanan","setting":"urban","time_of_day":"morning_night","shot_types":["wide","medium"],"avoid":["unrelated"],"sensitivity":["no_brand_focus"]}},
      "footage_slots": [
        {{"idea":"orang berangkat kerja pagi","search_query_en":"people commuting to work morning city","search_query_id":"orang berangkat kerja pagi kota","needed_seconds":8,"shot_type":"wide","platform_priority":["pexels","pixabay"],"avoid":["gaming"]}}
      ]
    }}
  ]
}}

Aturan:
- LLM tidak boleh output URL.
- planned_start_sec/planned_end_sec harus kumulatif dan total mendekati {target_duration:.0f}.
- Setiap segmen wajib punya narration_text dan 1-{slots_max} footage_slots.
- footage_slots harus visual spesifik, bukan keyword topik umum.
- Jangan gunakan markdown, output JSON saja."""
        data = {}
        try:
            raw = self._call_llm(prompt, system_prompt="Kamu membuat script plan dokumenter. Output JSON valid.", max_tokens=int(self._script_first_cfg().get("max_tokens_outline", 8000) or 8000), task="script_plan")
            self._emit_progress("Script: memvalidasi response API", 0.75)
            parsed = self._extract_json(raw)
            if isinstance(parsed, dict):
                data = parsed
        except Exception as exc:
            self.log(f"Script plan via LLM gagal: {exc}")
        if not (data.get("segments") if isinstance(data, dict) else []):
            if not self._script_first_cfg().get("fallback_enabled", False):
                raise RuntimeError(
                    "Script plan LLM gagal dan fallback nonaktif. "
                    "Periksa status API/LLM di panel Review dan endpoint/model yang dipilih."
                )
            self.log("Script plan pakai fallback deterministik")
            self._emit_progress("Script: API tidak menghasilkan plan, memakai fallback", 0.70)
            data = self._fallback_script_plan(brief, target_duration, segment_count)
        self.outline = self._normalize_script_plan(data, brief, target_duration, segment_count)
        self.segments = self.outline.get("segments", [])
        self.session_data["script_plan"] = self.outline
        self.session_data["outline"] = self.outline
        self.session_data["segments"] = self.segments
        self._write_json(self.plan_dir / "script_plan.json", self.outline)
        self._write_json(self.plan_dir / "segment_plan.json", {"segments": self.segments})
        self.session_data["status"] = "script_plan_ready"
        self._save_session()
        self._emit_progress(f"Script plan ready: {len(self.segments)} segmen", 1.0)
        return self.outline

    def _normalize_script_plan(self, data: Dict[str, Any], brief: Dict[str, Any], target_duration: float, segment_count: int) -> Dict[str, Any]:
        data = data if isinstance(data, dict) else {}
        raw_segments = data.get("segments") or []
        base = self._normalize_segments(raw_segments[:segment_count], target_duration)
        self._finalize_script_segments(base, target_duration)
        return {
            "title": data.get("title") or (brief.get("topic") or brief.get("title") or "Documentary"),
            "logline": data.get("logline") or "",
            "style": data.get("style") or brief.get("style") or self.doc_cfg.get("style") or "documentary",
            "language": data.get("language") or brief.get("language") or self.doc_cfg.get("language") or "id",
            "target_duration_seconds": target_duration,
            "duration_plan": {
                "target_duration_seconds": target_duration,
                "segment_count": len(base),
                "resource_mode": self._resource_mode(),
                "coverage_model": self._coverage_model_cfg(),
                "asset_budget": self._asset_budget_cfg(),
            },
            "script_source": data.get("script_source") or "llm",
            "needs_review": bool(data.get("needs_review")),
            "segments": base,
        }

    def _finalize_script_segments(self, segments: List[Dict[str, Any]], target_duration: float):
        total = sum(float(s.get("target_duration") or 0.0) for s in segments) or float(target_duration or 0.0)
        cursor = 0.0
        for seg in segments:
            dur = float(seg.get("target_duration") or 0.0)
            mapped = (dur / total * target_duration) if total else (float(target_duration) / max(1, len(segments)))
            seg["planned_start_sec"] = round(cursor, 3)
            seg["planned_end_sec"] = round(cursor + mapped, 3)
            seg["footage_slots"] = self._normalize_footage_slots(seg)
            cursor += mapped
        return segments

    def _normalize_footage_slots(self, seg: Dict[str, Any]) -> List[Dict[str, Any]]:
        raw_slots = seg.get("footage_slots") or []
        max_slots = self._slots_limit_for_segment()
        if not raw_slots:
            raw_slots = [{"idea": seg.get("visual_intent") or seg.get("title") or "documentary footage", "shot_type": "wide"}]
        target = max(10.0, float(seg.get("target_duration") or 30.0))
        source_slots = raw_slots[:max_slots]
        weights = [
            max(1.0, float(slot.get("needed_seconds") or target / max(1, len(source_slots))))
            if isinstance(slot, dict) else target / max(1, len(source_slots))
            for slot in source_slots
        ]
        total_weight = sum(weights) or 1.0
        planned_seconds = [target * weight / total_weight for weight in weights]
        if planned_seconds:
            planned_seconds[-1] = max(3.0, target - sum(planned_seconds[:-1]))
        slots = []
        for idx, (slot, planned) in enumerate(zip(source_slots, planned_seconds), start=1):
            slot = slot if isinstance(slot, dict) else {}
            idea = str(slot.get("idea") or slot.get("footage_idea") or slot.get("visual_intent") or seg.get("visual_intent") or seg.get("title") or "documentary footage").strip()
            q_en = str(slot.get("search_query_en") or slot.get("query_en") or idea).strip()
            q_id = str(slot.get("search_query_id") or slot.get("query_id") or idea).strip()
            slots.append({
                "slot_id": f"{seg.get('segment_id')}_f{idx}",
                "segment_id": seg.get("segment_id"),
                "order": idx,
                "idea": idea,
                "search_query_en": q_en,
                "search_query_id": q_id,
                "needed_seconds": round(max(3.0, planned), 3),
                "shot_type": slot.get("shot_type") or "wide",
                "platform_priority": slot.get("platform_priority") or ["pexels", "pixabay"],
                "avoid": slot.get("avoid") or [],
                "clip_context": slot.get("clip_context") or seg.get("clip_context") or {},
                "status": "planned",
                "candidates": [],
                "selected": None,
                "review_required": True,
            })
        return slots

    def _fallback_script_plan(self, brief: Dict[str, Any], target_duration: float, segment_count: int) -> Dict[str, Any]:
        topic = brief.get("topic") or brief.get("title") or "Documentary"
        words = [w for w in re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\-]{2,}", topic) if w.lower() not in {"yang", "dan", "untuk", "dari", "dengan", "pada", "adalah"}]
        base = " ".join(words[:5]) or str(topic)
        roles = ["hook", "problem_setup", "cause_pressure", "emotional_trigger", "symptom_behavior", "consequence", "resolution"]
        segments = []
        for idx in range(1, segment_count + 1):
            role = roles[(idx - 1) % len(roles)]
            segments.append({
                "segment_id": f"seg_{idx:03d}",
                "order": idx,
                "title": f"Bagian {idx}: {base}",
                "narration_text": f"Bagian {idx} membahas {base} secara runtut, dengan konteks dan penjelasan yang mudah dipahami.",
                "target_duration": round(target_duration / segment_count, 1),
                "visual_intent": f"documentary footage about {base} part {idx}",
                "clip_context": {"narrative_role": role, "viewer_should_feel": "informasi", "setting": "documentary", "time_of_day": "neutral", "shot_types": ["wide", "medium"], "avoid": ["unrelated"], "sensitivity": ["no_graphic_content"]},
                "source_requirements": ["context", "broll"],
            })
        return {"title": topic, "logline": f"Dokumenter tentang {topic}", "segments": segments, "script_source": "fallback", "needs_review": True}

    def build_footage_plan(self) -> Dict[str, Any]:
        self._check_cancel()
        self._emit_step(5, "Footage Plan", "")
        if not self.segments:
            raise RuntimeError("Script plan belum ada")
        footage_plan = {"generated_at": datetime.now().isoformat(timespec="seconds"), "review_required": True, "segments": []}
        total = max(1, len(self.segments))
        for idx, seg in enumerate(self.segments, start=1):
            self._check_cancel()
            slots = seg.get("footage_slots") or self._normalize_footage_slots(seg)
            seg["footage_slots"] = slots
            planned_slots = []
            for slot in slots:
                candidates = self._search_slot_candidates(slot, seg)
                slot["candidates"] = candidates
                slot["selected"] = None
                slot["review_required"] = True
                slot["status"] = "planned"
                planned_slots.append({
                    "slot_id": slot.get("slot_id"),
                    "segment_id": seg.get("segment_id"),
                    "idea": slot.get("idea"),
                    "needed_seconds": slot.get("needed_seconds"),
                    "planned_time_range": {"start": seg.get("planned_start_sec"), "end": seg.get("planned_end_sec")},
                    "candidates": candidates,
                    "selected": None,
                    "review_required": True,
                })
            footage_plan["segments"].append({
                "segment_id": seg.get("segment_id"),
                "order": seg.get("order"),
                "title": seg.get("title"),
                "planned_time_range": {"start": seg.get("planned_start_sec"), "end": seg.get("planned_end_sec")},
                "narration_excerpt": (seg.get("narration_text") or "")[:240],
                "slots": planned_slots,
            })
            self._emit_progress(f"Footage plan {idx}/{total}: {seg.get('title')}", (idx - 1) / total)
            self._save_session()
        self.session_data["segments"] = self.segments
        if isinstance(self.session_data.get("outline"), dict):
            self.session_data["outline"]["segments"] = self.segments
        if isinstance(self.outline, dict):
            self.outline["segments"] = self.segments
        self.session_data["footage_plan"] = footage_plan
        self._write_json(self.plan_dir / "footage_plan.json", footage_plan)
        self.session_data["status"] = "footage_plan_ready"
        self._save_session()
        self._emit_progress("Footage plan ready", 1.0)
        return footage_plan

    def _slot_query_variants(self, slot: Dict[str, Any]) -> List[str]:
        queries = []
        for key in ("search_query_en", "search_query_id", "idea"):
            q = str(slot.get(key) or "").strip()
            if q and q not in queries:
                queries.append(q)
        return queries

    def _search_slot_candidates(self, slot: Dict[str, Any], seg: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not self.stock.available_providers():
            return []
        budget = self._asset_budget_cfg()
        max_queries = max(1, int(budget.get("max_queries_per_slot", 1) or 1))
        max_candidates = max(1, int(budget.get("max_candidates_per_slot", 3) or 3))
        per_page = min(max(1, int(self.stock.per_segment_candidates or 5)), max_candidates, 5)
        results = []
        seen = set()
        for query in self._slot_query_variants(slot)[:max_queries]:
            self._check_cancel()
            error_count = len(self.stock.last_errors)
            try:
                found = self.stock.search(query, per_page=per_page)
            except Exception as exc:
                self.log(f"Footage slot search gagal '{query}': {str(exc)[:160]}")
                continue
            for error in self.stock.last_errors[error_count:]:
                self.log(
                    f"Stock provider {error.get('provider')} gagal "
                    f"({error.get('error_class')}): {error.get('message')}"
                )
            for cand in found or []:
                key = f"{cand.get('provider')}:{cand.get('id')}"
                if key in seen:
                    continue
                seen.add(key)
                item = dict(cand)
                item.update({
                    "slot_id": slot.get("slot_id"),
                    "segment_id": seg.get("segment_id"),
                    "query": query,
                    "status": "candidate",
                    "evidence": str(cand.get("tags") or cand.get("description") or "")[:180],
                    "warnings": [],
                    "score": float(cand.get("score", 0.0) or 0.0),
                })
                item["source_policy"] = self._source_policy("stock", item.get("source_page_url") or "", item.get("title") or "", item.get("provider") or "", float(item.get("duration") or 0.0))
                results.append(item)
        results.sort(key=lambda c: float(c.get("score", 0.0)), reverse=True)
        return results[:max_candidates]

    def _allocate_slot_seconds(self, seg: Dict[str, Any]) -> List[float]:
        slots = seg.get("footage_slots") or [{}]
        target = max(10.0, float(seg.get("target_duration") or 30.0))
        weights = [max(1.0, float(slot.get("needed_seconds") or target * 0.15)) for slot in slots]
        total_w = sum(weights) or 1.0
        seconds = [max(3.0, target * w / total_w) for w in weights]
        if sum(seconds) > target:
            factor = target / sum(seconds)
            seconds = [max(1.0, s * factor) for s in seconds]
        if len(seconds) > 1:
            seconds[-1] = max(1.0, target - sum(seconds[:-1]))
        else:
            seconds[0] = target
        return [round(s, 3) for s in seconds]

    def set_candidate_review(self, segment_id: str, slot_id: str, candidate_id: Any, action: str) -> Dict[str, Any]:
        """Record an explicit user selection or rejection for one footage candidate."""
        if action not in {"select", "reject"}:
            raise ValueError("Candidate action harus select atau reject")
        for seg in self.segments:
            if str(seg.get("segment_id")) != str(segment_id):
                continue
            for slot in seg.get("footage_slots") or []:
                if str(slot.get("slot_id")) != str(slot_id):
                    continue
                for candidate in slot.get("candidates") or []:
                    if str(candidate.get("id")) != str(candidate_id):
                        continue
                    if action == "reject":
                        candidate["status"] = "rejected"
                        candidate["rejected_at"] = datetime.now().isoformat(timespec="seconds")
                        candidate["rejection_reason"] = "explicit_user_rejection"
                        if str(slot.get("selected_candidate_id")) == str(candidate_id):
                            slot["selected_candidate_id"] = None
                            slot["selected"] = None
                        slot["status"] = "candidate"
                    else:
                        candidate["status"] = "selected_pending_review"
                        slot["selected_candidate_id"] = candidate.get("id")
                        slot["selected"] = {
                            "source_id": candidate.get("id"),
                            "provider": candidate.get("provider"),
                            "score": candidate.get("score"),
                            "query": candidate.get("query"),
                        }
                        slot["status"] = "selected_pending_review"
                    slot["selection_action"] = f"user_{action}"
                    self._save_session()
                    return candidate
        raise ValueError(f"Candidate tidak ditemukan: {segment_id}/{slot_id}/{candidate_id}")

    def approve_footage_plan(self, auto: bool = False) -> List[Dict[str, Any]]:
        self._check_cancel()
        self._emit_step(6, "Approve Footage", "")
        if not self.segments:
            raise RuntimeError("Script plan belum ada")
        usable_sources = [s for s in self.sources if s.get("type") == "url" and self._artifact_valid(s.get("local_path"))]
        source_mode = self._source_mode()
        stock_review_required = source_mode == "stock_footage" or (source_mode == "mixed" and not usable_sources)
        if not auto and stock_review_required:
            missing = [
                f"{seg.get('segment_id')}/{slot.get('slot_id')}"
                for seg in self.segments
                for slot in (seg.get("footage_slots") or [])
                if not (slot.get("selected_candidate_id") or (slot.get("selected") or {}).get("source_id"))
            ]
            if missing:
                raise RuntimeError(
                    "Pilih satu kandidat untuk setiap slot sebelum menyetujui footage. "
                    f"Belum dipilih: {', '.join(missing[:8])}"
                )
        selected_assets = {"approved_at": datetime.now().isoformat(timespec="seconds"), "auto": bool(auto), "segments": []}
        for seg in self.segments:
            self._check_cancel()
            slots = seg.get("footage_slots") or self._normalize_footage_slots(seg)
            allocated = self._allocate_slot_seconds(seg)
            clips = []
            for slot, alloc in zip(slots, allocated):
                candidates = slot.get("candidates") or []
                selected_id = slot.get("selected_candidate_id") or (slot.get("selected") or {}).get("source_id")
                if auto and selected_id is None:
                    slot["selection_action"] = "auto_approve_highest_score"
                elif selected_id is not None:
                    slot["selection_action"] = "user_selected"
                else:
                    slot["selection_action"] = "awaiting_selection"
                best = None
                for cand in candidates:
                    allow_stock = source_mode == "stock_footage" or (source_mode == "mixed" and not usable_sources)
                    if not allow_stock:
                        break
                    policy = cand.get("source_policy") or {}
                    if cand.get("status") == "rejected" or policy.get("status") == "rejected":
                        continue
                    if selected_id is not None and str(cand.get("id")) == str(selected_id):
                        best = cand
                        break
                    if auto and (best is None or float(cand.get("score", 0.0)) > float(best.get("score", 0.0))):
                        best = cand
                if not best:
                    continue
                best["status"] = "approved"
                best["review_status"] = "approved"
                best["approved_at"] = selected_assets["approved_at"]
                best["approval_reason"] = "explicit_auto_approve" if auto else "explicit_user_selection"
                cand_duration = float(best.get("duration") or 0.0)
                end = min(alloc, cand_duration) if cand_duration > 0 else alloc
                clip = {
                    "kind": "stock",
                    "provider": best.get("provider"),
                    "source_id": f"stock_{best.get('provider')}_{best.get('id')}",
                    "title": best.get("title"),
                    "candidate": best,
                    "start": 0.0,
                    "end": round(end, 3),
                    "reason": f"Footage slot {slot.get('slot_id')}: {slot.get('idea')}",
                    "local_path": "",
                    "footage_slot_id": slot.get("slot_id"),
                    "review_status": "approved" if auto else "selected_pending_review",
                }
                self._apply_clip_policy(clip)
                clip["review_status"] = "approved"
                clip["approval_reason"] = "explicit_auto_approve" if auto else "explicit_user_selection"
                clips.append(clip)
                slot["selected"] = {"source_id": best.get("id"), "provider": best.get("provider"), "score": best.get("score"), "query": best.get("query")}
                slot["status"] = "approved"
            if not clips and usable_sources and source_mode != "stock_footage":
                fallback_clip = self._choose_source_clip(seg, usable_sources)
                if fallback_clip:
                    self._apply_clip_policy(fallback_clip, next((s for s in usable_sources if str(s.get("source_id")) == str(fallback_clip.get("source_id"))), None))
                    fallback_clip["review_status"] = "approved"
                    fallback_clip["approval_reason"] = "explicit_manual_source_approval"
                    clips.append(fallback_clip)
            seg["selected_clips"] = clips
            seg["needs_manual_asset"] = not clips
            selected_assets["segments"].append({
                "segment_id": seg.get("segment_id"),
                "planned_time_range": {"start": seg.get("planned_start_sec"), "end": seg.get("planned_end_sec")},
                "slots": [{
                    "slot_id": s.get("slot_id"),
                    "selected_source_id": (s.get("selected") or {}).get("source_id"),
                    "selected_provider": (s.get("selected") or {}).get("provider"),
                    "selected_score": (s.get("selected") or {}).get("score"),
                    "selection_action": s.get("selection_action") or "awaiting_selection",
                    "review_status": "approved" if s.get("status") == "approved" else "pending",
                } for s in slots],
                "clip_count": len(clips),
            })
            self._save_session()
        self.session_data["segments"] = self.segments
        if isinstance(self.session_data.get("outline"), dict):
            self.session_data["outline"]["segments"] = self.segments
        if isinstance(self.session_data.get("script_plan"), dict):
            self.session_data["script_plan"]["segments"] = self.segments
        if isinstance(self.outline, dict):
            self.outline["segments"] = self.segments
        self.session_data["selected_assets"] = selected_assets
        self._write_json(self.plan_dir / "selected_assets.json", selected_assets)
        self.session_data["status"] = "assets_approved"
        self._save_session()
        self._emit_progress("Footage plan approved", 1.0)
        return self.segments

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
        budget = self._asset_budget_cfg()
        max_queries = max(1, int(budget.get("max_stock_queries_per_segment", 2) or 2))
        candidate_limit = min(max(3, self.stock.per_segment_candidates), max(1, int(budget.get("max_candidates_per_segment", 4) or 4)))
        all_candidates = []
        total = max(1, len(self.segments))
        for idx, seg in enumerate(self.segments, start=1):
            self._check_cancel()
            queries = queries_by_segment.get(seg["segment_id"]) or queries_by_segment.get(str(seg.get("order"))) or []
            if not queries:
                queries = self._fallback_queries(seg)
            seg_candidates = []
            for q in queries[:max_queries]:
                error_count = len(self.stock.last_errors)
                try:
                    seg_candidates.extend(self.stock.search(q, per_page=self.stock.per_segment_candidates))
                except Exception as exc:
                    self.log(f"Stock search gagal untuk '{q}': {exc}")
                for error in self.stock.last_errors[error_count:]:
                    self.log(
                        f"Stock provider {error.get('provider')} gagal "
                        f"({error.get('error_class')}): {error.get('message')}"
                    )
            # Deduplicate by provider+id and keep top candidates.
            seen = set()
            dedup = []
            for cand in sorted(seg_candidates, key=lambda c: float(c.get("score", 0.0)), reverse=True):
                key = f"{cand.get('provider')}:{cand.get('id')}"
                if key in seen:
                    continue
                seen.add(key)
                cand["segment_id"] = seg["segment_id"]
                cand["source_policy"] = self._source_policy("stock", cand.get("source_page_url") or "", cand.get("title") or "", cand.get("provider") or "", float(cand.get("duration") or 0.0))
                dedup.append(cand)
            dedup = dedup[:candidate_limit]
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
                "clip_context": seg.get("clip_context") or {},
                "narrative_role": seg.get("narrative_role") or "",
                "narration_excerpt": (seg.get("narration_text") or "")[:300],
            })
        prompt = f"""Untuk tiap segmen dokumenter, buat 1-3 search query footage stock dalam bahasa Inggris.
Query harus spesifik, visual, dan cocok untuk Pexels/Pixabay video.
Pilih berdasarkan clip_context/narrative_role dan visual_intent; jangan hanya menyalin judul.

Segmen:
{json.dumps(payload, ensure_ascii=False)}

Output JSON valid:
{{"queries": {{"seg_001": ["query1", "query2"], "seg_002": ["query3"]}}}}"""
        try:
            raw = self._call_llm(prompt, system_prompt="Kamu membuat search query stock footage. Output JSON valid.", max_tokens=2000, task="stock_queries")
            data = self._extract_json(raw)
            queries = data.get("queries", {}) if isinstance(data, dict) else {}
            return {str(k): [str(q) for q in (v or [])] for k, v in queries.items()}
        except Exception as exc:
            self.log(f"Generate stock queries via LLM gagal, pakai fallback: {exc}")
            return {}

    @staticmethod
    def _clip_context_text(seg: Dict[str, Any]) -> str:
        ctx = seg.get("clip_context") or {}
        parts = [str(seg.get("narrative_role") or ""), str(seg.get("viewer_should_feel") or "")]
        for key in ("narrative_role", "viewer_should_feel", "visual_intent", "setting", "time_of_day", "shot_types", "avoid", "sensitivity"):
            val = ctx.get(key)
            if isinstance(val, list):
                parts.extend(str(x) for x in val)
            elif val:
                parts.append(str(val))
        return " ".join(p for p in parts if p)

    @staticmethod
    def _fallback_queries(seg: Dict[str, Any]) -> List[str]:
        text = f"{seg.get('visual_intent', '')} {seg.get('title', '')} {seg.get('narration_text', '')[:160]} {DocumentaryEngine._clip_context_text(seg)}"
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
        source_mode = self._source_mode()
        src_by_id = {str(s.get("source_id")): s for s in usable_sources}
        total = max(1, len(self.segments))
        for idx, seg in enumerate(self.segments, start=1):
            self._check_cancel()
            self._emit_progress(f"Selecting clips {idx}/{total}: {seg.get('title')}", (idx - 1) / total)
            clips = []
            stock_cands = seg.get("stock_candidates") or []
            # Manual sources remain the backbone in mixed mode whenever available.
            if source_mode == "stock_footage" and stock_cands:
                cand = stock_cands[0]
                clip = {
                    "kind": "stock",
                    "provider": cand.get("provider"),
                    "source_id": f"stock_{cand.get('provider')}_{cand.get('id')}",
                    "title": cand.get("title"),
                    "candidate": cand,
                    "start": 0.0,
                    "end": float(seg.get("target_duration") or cand.get("duration") or 30.0),
                    "reason": f"Stock B-roll ({cand.get('provider')}): {cand.get('query') or seg.get('visual_intent')}",
                    "local_path": "",
                }
                self._apply_clip_policy(clip)
                clips.append(clip)
            elif source_mode != "stock_footage" and usable_sources:
                clip = self._choose_source_clip(seg, usable_sources)
                if clip:
                    self._apply_clip_policy(clip, src_by_id.get(str(clip.get("source_id"))))
                    clips.append(clip)
            elif source_mode == "mixed" and stock_cands and self._should_use_stock(seg):
                cand = stock_cands[0]
                clip = {
                    "kind": "stock",
                    "provider": cand.get("provider"),
                    "source_id": f"stock_{cand.get('provider')}_{cand.get('id')}",
                    "title": cand.get("title"),
                    "candidate": cand,
                    "start": 0.0,
                    "end": float(seg.get("target_duration") or cand.get("duration") or 30.0),
                    "reason": f"Stock fallback ({cand.get('provider')}): {cand.get('query') or seg.get('visual_intent')}",
                    "local_path": "",
                }
                self._apply_clip_policy(clip)
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
        text = f"{seg.get('narration_text', '')} {seg.get('visual_intent', '')} {seg.get('title', '')} {self._clip_context_text(seg)}".lower()
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
        if not (self.session_data.get("script_plan") or self.outline):
            raise RuntimeError("Script plan belum dibuat; Generate Script harus selesai sebelum TTS")
        if self.session_data.get("status") not in {
            "assets_approved", "voice_ready", "subtitles_ready", "rendering", "completed"
        }:
            raise RuntimeError(
                "TTS ditahan: selesaikan Generate Script, Footage Plan, review, dan Approve Footage terlebih dahulu"
            )
        total = max(1, len(self.segments))
        for idx, seg in enumerate(self.segments, start=1):
            self._check_cancel()
            text = (seg.get("narration_text") or "").strip()
            if not text:
                continue
            voice_path = self.clips_dir / f"{seg['segment_id']}.voice.mp3"
            voice_json = self.clips_dir / f"{seg['segment_id']}.voice.json"
            if self._media_artifact_valid(voice_path, require_audio=True) and self._artifact_valid(voice_json):
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
                if not self._media_artifact_valid(result.get("audio_path") or voice_path, require_audio=True):
                    raise RuntimeError("TTS menghasilkan artifact audio yang tidak valid")
                if float(result.get("duration") or 0.0) <= 0:
                    result["duration"] = float(self._probe(result.get("audio_path") or voice_path).get("duration") or 0.0)
                result["status"] = "completed"
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
            return self._clamp_subtitle_cues(cues, duration)
        # Estimated timing fallback.
        words = (fallback_text or "").split()
        if not words or duration <= 0:
            return self._clamp_subtitle_cues([(0.0, duration or 1.0, fallback_text or "")], duration)
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
        return self._clamp_subtitle_cues(cues, duration)

    @staticmethod
    def _srt_time(seconds: float) -> str:
        total_ms = int(round(max(0.0, float(seconds)) * 1000))
        h = total_ms // 3600000
        m = (total_ms % 3600000) // 60000
        s = (total_ms % 60000) // 1000
        ms = total_ms % 1000
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    @staticmethod
    def _clamp_subtitle_cues(cues: List[Tuple[float, float, str]], duration: float) -> List[Tuple[float, float, str]]:
        limit = max(0.1, float(duration or 0.1))
        normalized = []
        previous_end = 0.0
        for start, end, text in cues:
            start = max(previous_end, min(limit, float(start)))
            end = max(start, min(limit, float(end)))
            if end <= start or not (text or "").strip():
                continue
            normalized.append((start, end, text))
            previous_end = end
        return normalized

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
        if clip.get("review_status") != "approved":
            raise RuntimeError(
                f"Asset {clip.get('source_id') or clip.get('title') or 'unknown'} "
                "belum approved dan tidak boleh dimaterialize"
            )
        kind = clip.get("kind")
        if kind == "stock":
            cand = clip.get("candidate") or {}
            safe_id = re.sub(r"[^A-Za-z0-9_\-]+", "_", str(clip.get("source_id") or f"stock_{clip_idx}"))
            dest = self.sources_dir / f"{safe_id}.mp4"
            if not self._media_artifact_valid(dest, require_video=True):
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
            "-stream_loop", "-1",
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
        if self._media_artifact_valid(video_path, require_audio=True, require_video=True):
            return str(video_path)

        profile = self._render_profile()
        width = int(profile.get("width", 1920) or 1920)
        height = int(profile.get("height", 1080) or 1080)
        normalized = []
        voice_duration = float((seg.get("voice") or {}).get("duration") or 0.0)
        target_duration = max(1.0, voice_duration or float(seg.get("target_duration") or 30.0))
        source_durations = [
            max(1.0, float(c.get("end") or 0.0) - float(c.get("start") or 0.0))
            for c in (seg.get("selected_clips") or [])
        ]
        total_source_duration = sum(source_durations) or target_duration
        for cidx, clip in enumerate(seg.get("selected_clips") or [], start=1):
            self._check_cancel()
            src_path = self._materialize_clip(clip, seg_id, cidx)
            if not src_path:
                continue
            start = float(clip.get("start") or 0.0)
            end = float(clip.get("end") or 0.0)
            source_duration = max(1.0, end - start) if end > start else target_duration
            duration = target_duration * source_duration / total_source_duration
            out = self.clips_dir / f"{seg_id}_src{cidx}.mp4"
            if not self._media_artifact_valid(out, require_audio=True, require_video=True):
                if not self._normalize_clip(src_path, out, start, duration, width, height):
                    continue
            normalized.append(str(out))
        if not normalized:
            raise RuntimeError(f"Tidak ada clip valid untuk {seg_id}")
        if not self._concat_video_only(normalized, video_path):
            raise RuntimeError(f"Gagal assemble video {seg_id}")
        seg["timeline"] = {
            "planned_time_range": {
                "start": seg.get("planned_start_sec"),
                "end": seg.get("planned_end_sec"),
            },
            "target_duration": round(target_duration, 3),
            "materialized_duration": round(sum(
                float(self._probe(path).get("duration") or 0.0) for path in normalized
            ), 3),
            "duration_basis": "voice" if voice_duration > 0 else "segment_target",
        }
        return str(video_path)

    def _prepare_bgm(self) -> str:
        bgm_cfg = self.doc_cfg.get("bgm", {}) or {}
        if not bgm_cfg.get("enabled"):
            return ""
        source = (bgm_cfg.get("source") or "").strip()
        if not source:
            return ""
        dest = self.session_dir / "bgm.mp3"
        if self._media_artifact_valid(dest, require_audio=True):
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
            return str(dest) if self._media_artifact_valid(dest, require_audio=True) else ""
        except Exception as exc:
            self.log(f"BGM gagal disiapkan: {exc}")
            return ""

    def render_segment(self, seg: Dict[str, Any]) -> str:
        seg_id = seg["segment_id"]
        final_path = self.render_dir / f"{seg_id}.final.mp4"
        if self._media_artifact_valid(final_path, require_audio=True, require_video=True):
            seg.setdefault("render", {})["status"] = "completed"
            seg["render"]["output"] = str(final_path)
            return str(final_path)

        video_path = self.assemble_segment_video(seg)
        voice = seg.get("voice") or {}
        voice_path = voice.get("audio_path") or str(self.clips_dir / f"{seg_id}.voice.mp3")
        if not self._media_artifact_valid(voice_path, require_audio=True):
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
        profile = self._render_profile()
        bitrate = profile.get("video_bitrate", "8M")
        preset = profile.get("preset", "veryfast")
        cmd += [
            "-c:v", "libx264", "-preset", str(preset), "-b:v", str(bitrate),
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
        if self.session_data.get("status") not in {"assets_approved", "voice_ready", "subtitles_ready", "rendering", "completed"}:
            raise RuntimeError("Review footage belum selesai; assets harus approved sebelum render")
        for seg in self.segments:
            for clip in seg.get("selected_clips") or []:
                if clip.get("review_status") != "approved":
                    raise RuntimeError(
                        f"Asset {clip.get('source_id') or clip.get('title') or 'unknown'} "
                        "belum approved"
                    )
        # Ensure voice + subtitles exist before rendering.
        self.generate_voice()
        self.write_segment_subtitles()

        total = max(1, len(self.segments))
        existing_manifest = self._read_json(self.render_dir / "render_manifest.json", {}) or {}
        self.render_manifest = {
            "segments": dict(existing_manifest.get("segments") or {}),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.session_data["status"] = "rendering"
        self._save_session()
        timeline_cursor = 0.0
        for idx, seg in enumerate(self.segments, start=1):
            self._check_cancel()
            self._emit_progress(f"Render {idx}/{total}: {seg.get('title')}", (idx - 1) / total)
            try:
                out = self.render_segment(seg)
                duration = float(self._probe(out).get("duration") or 0.0)
                seg.setdefault("timeline", {})["actual_time_range"] = {
                    "start": round(timeline_cursor, 3),
                    "end": round(timeline_cursor + duration, 3),
                }
                seg["timeline"]["actual_duration"] = round(duration, 3)
                timeline_cursor += duration
                self.render_manifest["segments"][seg["segment_id"]] = {
                    "status": "completed",
                    "output": out,
                    "duration": duration,
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
        self.session_data["status"] = "subtitles_ready" if any(
            (seg.get("render") or {}).get("status") != "completed" for seg in self.segments
        ) else "rendering"
        self._save_session()
        self._emit_progress("Segment renders complete", 1.0)
        return self.segments

    def _validate_concat_inputs(self, inputs: List[str]) -> None:
        profile = self._render_profile()
        expected = (int(profile.get("width", 1920)), int(profile.get("height", 1080)))
        baseline = None
        for path in inputs:
            probe = self._probe(path)
            actual = (
                int(probe.get("width") or 0),
                int(probe.get("height") or 0),
                round(float(probe.get("fps") or 0.0), 3),
                str(probe.get("video_codec") or ""),
                bool(probe.get("has_audio")),
                str(probe.get("audio_codec") or ""),
            )
            if actual[0:2] != expected:
                raise RuntimeError(
                    f"Concat incompatible: {Path(path).name} berukuran "
                    f"{actual[0]}x{actual[1]}, wajib {expected[0]}x{expected[1]}"
                )
            if baseline is None:
                baseline = actual
            elif actual != baseline:
                raise RuntimeError(
                    f"Concat incompatible: {Path(path).name} berbeda dari baseline "
                    f"(resolution/fps/codec/audio)"
                )

    def concat_final(self) -> str:
        self._check_cancel()
        self._emit_step(10, "Concat Final", "")
        finals = []
        failed = []
        for seg in self.segments:
            render = seg.get("render") or {}
            out = render.get("output") or str(self.render_dir / f"{seg['segment_id']}.final.mp4")
            if render.get("status") == "failed" or not self._media_artifact_valid(out, require_audio=True, require_video=True):
                failed.append(seg.get("segment_id"))
            else:
                finals.append(out)
        if failed:
            raise RuntimeError(f"Masih ada segmen gagal/belum render: {', '.join(failed)}")
        if not finals:
            raise RuntimeError("Tidak ada segment final yang valid untuk concat")
        self._validate_concat_inputs(finals)
        final_path = self.session_dir / "final.mp4"
        list_path = self.render_dir / "concat_list.txt"
        with open(list_path, "w", encoding="utf-8") as f:
            for p in finals:
                f.write(f"file '{Path(p).as_posix()}'\n")
        profile = self._render_profile()
        cmd = [self.ffmpeg_path, "-y", "-f", "concat", "-safe", "0", "-i", str(list_path)]
        if profile.get("concat_stream_copy"):
            cmd += ["-c", "copy", "-movflags", "+faststart", str(final_path)]
        else:
            cmd += [
                "-c:v", "libx264", "-preset", str(profile.get("preset", "veryfast")), "-crf", "20",
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
        asset_policy = []
        policy_warnings = []
        for seg in self.segments:
            for clip in seg.get("selected_clips") or []:
                policy = clip.get("source_policy") or {}
                asset_item = {
                    "segment_id": seg.get("segment_id"),
                    "kind": clip.get("kind"),
                    "provider": clip.get("provider"),
                    "source_id": clip.get("source_id"),
                    "title": clip.get("title"),
                    "channel_or_account": clip.get("channel_or_account") or policy.get("channel_or_account") or "",
                    "platform": policy.get("platform") or clip.get("provider"),
                    "license": clip.get("license"),
                    "license_signal": clip.get("license_signal") or policy.get("license_signal"),
                    "attribution": clip.get("attribution"),
                    "source_page_url": clip.get("source_page_url"),
                    "intended_use": clip.get("intended_use") or policy.get("intended_use"),
                    "clip_duration_seconds": round(max(0.0, float(clip.get("end") or 0.0) - float(clip.get("start") or 0.0)), 3),
                    "review_status": clip.get("review_status") or policy.get("review_status"),
                    "policy_status": clip.get("policy_status") or policy.get("status"),
                    "policy_reasons": clip.get("policy_reasons") or policy.get("reasons") or [],
                }
                asset_policy.append(asset_item)
                if asset_item.get("policy_status") in {"warning", "rejected"}:
                    policy_warnings.append(asset_item)
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
            "asset_policy": asset_policy,
            "policy_warnings": policy_warnings,
            "providers": {
                "tts": self.tts.provider_status(),
                "stock": self.stock.provider_status(),
            },
            "status": "completed" if self._media_artifact_valid(final_path, require_audio=True, require_video=True) else "rendering",
            "created_at": self.session_data.get("created_at"),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._write_json(self.session_dir / "data.json", data)
        self.session_data["status"] = "completed" if self._media_artifact_valid(final_path, require_audio=True, require_video=True) else self.session_data.get("status", "rendering")
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
            if (self.doc_cfg.get("script_first") or {}).get("enabled", True):
                self.generate_script_plan(brief)
                self.build_footage_plan()
                review = self._review_gate_cfg()
                if review.get("enabled", True) and not review.get("auto_approve_run_full", False):
                    self.session_data["status"] = "review_required"
                    self.session_data["review_gate"] = {
                        "required": True,
                        "reason": "explicit_footage_review_required",
                        "created_at": datetime.now().isoformat(timespec="seconds"),
                    }
                    self._save_session()
                    self.log("Review gate: run_full berhenti sebelum approval footage")
                    return {
                        "success": True,
                        "awaiting_review": True,
                        "session_id": self.session_id,
                        "final_path": None,
                        "data": self.session_data,
                    }
                self.approve_footage_plan(auto=True)
            else:
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
