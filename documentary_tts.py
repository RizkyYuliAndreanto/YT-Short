"""
TTS adapter for Documentary Studio.

Baseline provider: Edge TTS (free, Indonesian voices).
Optional provider: Chatterbox TTS via local HTTP endpoint when configured.
"""

import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from utils.helpers import get_ffmpeg_path


SUBPROCESS_FLAGS = 0
if sys.platform == "win32":
    SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW


def _ffprobe_path() -> str:
    ffmpeg = get_ffmpeg_path()
    if ffmpeg and ffmpeg != "ffmpeg":
        candidate = Path(ffmpeg).parent / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
        if candidate.exists():
            return str(candidate)
    return "ffprobe"


def probe_audio_duration(path: str) -> float:
    try:
        cmd = [
            _ffprobe_path(), "-v", "quiet", "-print_format", "json",
            "-show_format", path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS, timeout=20)
        data = json.loads(result.stdout or "{}")
        return float((data.get("format") or {}).get("duration") or 0.0)
    except Exception:
        return 0.0


class DocumentaryTTS:
    """Provider-agnostic TTS facade for documentary narration segments."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = (config or {}).get("documentary", {}) or {}
        self.config = cfg
        self.provider_name = (cfg.get("tts_provider") or "edge_tts").lower()
        self.edge_cfg = cfg.get("edge_tts", {}) or {}
        self.chatterbox_cfg = cfg.get("chatterbox", {}) or {}
        self._edge_manager = None

    def _get_edge_manager(self):
        if self._edge_manager is None:
            from edge_tts_engine import EdgeTTSManager
            self._edge_manager = EdgeTTSManager(self.edge_cfg)
        return self._edge_manager

    def provider_status(self) -> Dict[str, Any]:
        chatterbox_enabled = bool(self.chatterbox_cfg.get("enabled"))
        endpoint = (self.chatterbox_cfg.get("endpoint") or "").strip()
        return {
            "provider": self.provider_name,
            "edge_tts": {"available": True, "voice": self.edge_cfg.get("voice", "id-ID-ArdiNeural")},
            "chatterbox": {
                "enabled": chatterbox_enabled,
                "endpoint": endpoint,
                "available": chatterbox_enabled and bool(endpoint),
            },
        }

    def generate(self, text: str, output_path: str, voice: Optional[str] = None) -> Dict[str, Any]:
        text = (text or "").strip()
        if not text:
            raise ValueError("Teks narasi kosong")

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        if self.provider_name == "chatterbox" and self.chatterbox_cfg.get("enabled"):
            try:
                return self._generate_chatterbox(text, str(out), voice)
            except Exception as exc:
                # Fall back to Edge TTS so the segment is not lost.
                result = self._generate_edge(text, str(out), voice)
                result["fallback"] = "edge_tts"
                result["error"] = str(exc)
                return result

        return self._generate_edge(text, str(out), voice)

    def _generate_edge(self, text: str, output_path: str, voice: Optional[str]) -> Dict[str, Any]:
        cfg = dict(self.edge_cfg)
        if voice:
            cfg["voice"] = voice
        manager = self._get_edge_manager()
        manager.update_config(cfg)
        audio_path, duration, word_timings = manager.generate_audio_sync(text, output_path)
        return {
            "provider": "edge_tts",
            "audio_path": audio_path,
            "duration": float(duration or 0.0),
            "word_timings": word_timings or [],
            "alignment_method": "edge_tts_word_boundary",
            "voice": cfg.get("voice", "id-ID-ArdiNeural"),
        }

    def _generate_chatterbox(self, text: str, output_path: str, voice: Optional[str]) -> Dict[str, Any]:
        endpoint = (self.chatterbox_cfg.get("endpoint") or "").strip().rstrip("/")
        if not endpoint:
            raise ValueError("Chatterbox endpoint belum dikonfigurasi")
        timeout = int(self.chatterbox_cfg.get("timeout_seconds", 120) or 120)
        payload = {
            "text": text,
            "voice_id": voice or self.chatterbox_cfg.get("voice_id", "default"),
            "output_path": output_path,
        }
        # Keep payload minimal for common local servers; extra keys are ignored by most APIs.
        for key in ("speed", "pitch", "language", "speaker"):
            if key in self.chatterbox_cfg:
                payload[key] = self.chatterbox_cfg[key]

        resp = requests.post(f"{endpoint}/tts", json=payload, timeout=timeout)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        data = None

        if "audio" in content_type or resp.content[:4] in {b"RIFF", b"ID3\x03", b"ID3\x04", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}:
            Path(output_path).write_bytes(resp.content)
        else:
            data = resp.json()
            audio_b64 = data.get("audio_base64") or data.get("audio") or ""
            audio_url = data.get("audio_url") or data.get("url") or ""
            if audio_b64:
                Path(output_path).write_bytes(base64.b64decode(audio_b64))
            elif audio_url:
                with requests.get(audio_url, timeout=timeout, stream=True) as audio_resp:
                    audio_resp.raise_for_status()
                    with open(output_path, "wb") as f:
                        for chunk in audio_resp.iter_content(chunk_size=1024 * 256):
                            if chunk:
                                f.write(chunk)
            else:
                raise ValueError("Response Chatterbox tidak berisi audio")

        duration = float(data.get("duration") or 0.0) if isinstance(data, dict) else 0.0
        if duration <= 0:
            duration = probe_audio_duration(output_path)
        word_timings = data.get("word_timings") if isinstance(data, dict) else []
        return {
            "provider": "chatterbox",
            "audio_path": output_path,
            "duration": duration,
            "word_timings": word_timings or [],
            "alignment_method": "chatterbox" if word_timings else "estimated",
            "voice": payload.get("voice_id", "default"),
        }


def get_documentary_tts(config: Optional[Dict[str, Any]] = None) -> DocumentaryTTS:
    return DocumentaryTTS(config)
