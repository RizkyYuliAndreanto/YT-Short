"""
Stock footage providers for Documentary Studio.

Adapters for Pexels and Pixabay video APIs. The LLM only generates queries and
rankings; this module performs the actual API calls and normalizes candidates.
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests


DEFAULT_PEXELS_BASE_URL = "https://api.pexels.com"
DEFAULT_PIXABAY_BASE_URL = "https://pixabay.com/api"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _validate_base_url(base_url: str, provider: str) -> str:
    base_url = (base_url or "").strip().rstrip("/")
    if not base_url:
        return ""
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"{provider} base_url tidak valid: {base_url}")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError(f"{provider} base_url harus https (kecuali localhost): {base_url}")
    return base_url


def _pick_pexels_file(video: Dict[str, Any], preferred_height: int = 1080) -> Dict[str, Any]:
    files = [f for f in video.get("video_files", []) if f.get("file_type") == "video/mp4" or str(f.get("link", "")).lower().endswith(".mp4")]
    if not files:
        files = list(video.get("video_files", []))
    if not files:
        return {}

    def height_key(f):
        h = int(f.get("height") or 0)
        return abs(h - preferred_height) if h else 9999

    files.sort(key=height_key)
    return files[0]


def _normalize_pexels(raw: Dict[str, Any], query: str, score: float = 0.0) -> Dict[str, Any]:
    video_file = _pick_pexels_file(raw)
    user = raw.get("user") or {}
    duration = raw.get("duration") or video_file.get("duration") or 0
    width = raw.get("width") or video_file.get("width") or 0
    height = raw.get("height") or video_file.get("height") or 0
    return {
        "provider": "pexels",
        "id": str(raw.get("id", "")),
        "title": raw.get("alt") or raw.get("url", "Pexels video"),
        "duration": float(duration or 0),
        "width": int(width or 0),
        "height": int(height or 0),
        "preview_url": raw.get("image") or "",
        "download_url": video_file.get("link") or "",
        "license": "Pexels License",
        "attribution": user.get("name") or "Pexels",
        "source_page_url": raw.get("url") or "",
        "query": query,
        "score": float(score),
        "raw": raw,
    }


def _pick_pixabay_video(videos: Dict[str, Any], preferred_height: int = 1080) -> Dict[str, Any]:
    if not isinstance(videos, dict):
        return {}
    for key in ("large", "medium", "small", "tiny"):
        item = videos.get(key)
        if item and item.get("url"):
            h = int(item.get("height") or 0)
            if h and h <= preferred_height:
                return item
    for key in ("large", "medium", "small", "tiny"):
        item = videos.get(key)
        if item and item.get("url"):
            return item
    return {}


def _normalize_pixabay(raw: Dict[str, Any], query: str, score: float = 0.0) -> Dict[str, Any]:
    video = _pick_pixabay_video(raw.get("videos") or {})
    user = raw.get("user") or ""
    duration = raw.get("duration") or video.get("duration") or 0
    width = video.get("width") or 0
    height = video.get("height") or 0
    return {
        "provider": "pixabay",
        "id": str(raw.get("id", "")),
        "title": (raw.get("tags") or "Pixabay video").split(",")[0].strip() or "Pixabay video",
        "duration": float(duration or 0),
        "width": int(width or 0),
        "height": int(height or 0),
        "preview_url": video.get("thumbnail") or raw.get("picture_id") and f"https://i.vimeocdn.com/video/{raw.get('picture_id')}_295x166.jpg" or "",
        "download_url": video.get("url") or "",
        "license": "Pixabay Content License",
        "attribution": user or "Pixabay",
        "source_page_url": raw.get("pageURL") or "",
        "query": query,
        "score": float(score),
        "raw": raw,
    }


class StockFootageProvider:
    """Base provider interface for stock footage search/download."""

    name = "stock"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        self.api_key_env = self.config.get("api_key_env", "")
        self.base_url = _validate_base_url(
            self.config.get("base_url", ""), self.name
        )
        self.api_key = _env(self.api_key_env) or _env(self.name.upper() + "_API_KEY")
        self.timeout = int(self.config.get("timeout_seconds", 30) or 30)

    def is_available(self) -> bool:
        return self.enabled and bool(self.api_key) and bool(self.base_url)

    def status(self) -> Dict[str, Any]:
        return {
            "provider": self.name,
            "enabled": self.enabled,
            "has_api_key": bool(self.api_key),
            "base_url": self.base_url,
            "available": self.is_available(),
        }

    def search(self, query: str, per_page: int = 5, **kwargs) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def download_asset(self, candidate: Dict[str, Any], dest_path: str) -> str:
        url = candidate.get("download_url") or ""
        if not url:
            raise ValueError("candidate tidak punya download_url")
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(url, stream=True, timeout=self.timeout) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
        return str(dest)


class PexelsStockProvider(StockFootageProvider):
    name = "pexels"
    default_base_url = DEFAULT_PEXELS_BASE_URL

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = dict(config or {})
        if not cfg.get("base_url"):
            cfg["base_url"] = self.default_base_url
        super().__init__(cfg)

    def search(self, query: str, per_page: int = 5, orientation: str = "landscape", **kwargs) -> List[Dict[str, Any]]:
        if not self.is_available():
            return []
        params = {
            "query": query,
            "per_page": max(1, min(int(per_page or 5), 80)),
            "orientation": orientation or "landscape",
        }
        headers = {"Authorization": self.api_key, "Accept": "application/json"}
        resp = requests.get(
            f"{self.base_url}/videos/search",
            params=params,
            headers=headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for idx, raw in enumerate(data.get("videos", [])[: int(params["per_page"])]):
            cand = _normalize_pexels(raw, query=query, score=1.0 - (idx * 0.05))
            if cand.get("download_url"):
                results.append(cand)
        return results


class PixabayStockProvider(StockFootageProvider):
    name = "pixabay"
    default_base_url = DEFAULT_PIXABAY_BASE_URL

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = dict(config or {})
        if not cfg.get("base_url"):
            cfg["base_url"] = self.default_base_url
        super().__init__(cfg)

    def search(self, query: str, per_page: int = 5, **kwargs) -> List[Dict[str, Any]]:
        if not self.is_available():
            return []
        params = {
            "key": self.api_key,
            "q": query,
            "per_page": max(1, min(int(per_page or 5), 200)),
            "safesearch": "true",
            "video_type": "film",
        }
        resp = requests.get(f"{self.base_url}/videos/", params=params, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for idx, raw in enumerate(data.get("hits", [])[: int(params["per_page"])]):
            cand = _normalize_pixabay(raw, query=query, score=1.0 - (idx * 0.05))
            if cand.get("download_url"):
                results.append(cand)
        return results


class StockFootageService:
    """Facade for stock footage providers used by DocumentaryEngine."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        root = config or {}
        if "stock_footage" in root:
            cfg = root.get("stock_footage") or {}
        elif isinstance(root.get("documentary"), dict):
            cfg = root["documentary"].get("stock_footage") or {}
        else:
            cfg = {}
        self.config = cfg
        self.enabled = bool(cfg.get("enabled", True))
        providers_cfg = cfg.get("providers", {}) or {}
        self.providers = {
            "pexels": PexelsStockProvider(providers_cfg.get("pexels", {})),
            "pixabay": PixabayStockProvider(providers_cfg.get("pixabay", {})),
        }
        search_cfg = cfg.get("search", {}) or {}
        self.per_segment_candidates = int(search_cfg.get("per_segment_candidates", 5) or 5)
        self.orientation = search_cfg.get("orientation", "landscape")
        self.max_per_provider = int(search_cfg.get("max_per_provider", 10) or 10)
        self.license_cfg = cfg.get("license", {}) or {}
        self.last_errors: List[Dict[str, str]] = []

    def provider_status(self) -> List[Dict[str, Any]]:
        status = []
        for provider in self.providers.values():
            item = provider.status()
            errors = [e for e in self.last_errors if e.get("provider") == provider.name]
            if errors:
                item["last_error"] = errors[-1].get("message", "")
                item["last_error_class"] = errors[-1].get("error_class", "provider_error")
            status.append(item)
        return status

    def available_providers(self) -> List[StockFootageProvider]:
        return [p for p in self.providers.values() if p.is_available()]

    def search(self, query: str, providers: Optional[List[str]] = None, per_page: Optional[int] = None) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []
        wanted = set((providers or list(self.providers.keys())))
        limit = int(per_page or self.per_segment_candidates)
        results = []
        for name, provider in self.providers.items():
            if name not in wanted or not provider.is_available():
                continue
            try:
                results.extend(provider.search(query, per_page=min(limit, self.max_per_provider), orientation=self.orientation))
            except Exception as exc:
                message = " ".join(str(exc).split())[:240]
                lower = message.lower()
                if "401" in lower or "403" in lower or "unauthor" in lower:
                    error_class = "authentication"
                elif "429" in lower or "quota" in lower or "rate" in lower:
                    error_class = "quota"
                elif "timeout" in lower or "timed out" in lower:
                    error_class = "timeout"
                else:
                    error_class = "provider_error"
                self.last_errors.append({
                    "provider": name,
                    "error_class": error_class,
                    "message": message or "provider search failed",
                    "query": str(query)[:160],
                })
                continue
        results.sort(key=lambda c: float(c.get("score", 0.0)), reverse=True)
        return results[: max(1, limit * len(wanted))]

    def download_candidate(self, candidate: Dict[str, Any], dest_path: str) -> str:
        provider_name = candidate.get("provider", "")
        provider = self.providers.get(provider_name)
        if provider is None or not provider.is_available():
            raise ValueError(f"Provider stock footage tidak tersedia: {provider_name}")
        return provider.download_asset(candidate, dest_path)


def get_stock_service(config: Optional[Dict[str, Any]] = None) -> StockFootageService:
    return StockFootageService(config)
