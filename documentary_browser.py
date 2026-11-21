"""
Browser-assisted asset/link discovery for Documentary Studio.

Uses the `agent-browser` CLI (real Chrome) to open search pages and extract
candidate links. This is for public discovery only: no login, no credential
use, and results are still reviewed by the user before download.
"""

import base64
import json
import os
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

from clip_cutter_core import detect_platform


SUBPROCESS_FLAGS = 0
if sys.platform == "win32":
    SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW


def _parse_duration_seconds(text: str) -> float:
    text = (text or "").strip()
    if not text or not all(part.isdigit() for part in text.split(":")):
        return 0.0
    parts = [int(p) for p in text.split(":")]
    if len(parts) == 2:
        return float(parts[0] * 60 + parts[1])
    if len(parts) == 3:
        return float(parts[0] * 3600 + parts[1] * 60 + parts[2])
    return 0.0


def _classify_media_platform(url: str) -> str:
    try:
        info = detect_platform(url)
        platform = str(info.get("platform") or "unknown")
        if platform != "unknown":
            return platform
    except Exception:
        pass
    parsed = urllib.parse.urlparse(url or "")
    host = (parsed.netloc or "").lower()
    full = (url or "").lower()
    qs = urllib.parse.parse_qs(parsed.query)
    if "tiktok.com" in host and ("/video/" in full or "/t/" in full or "vm.tiktok.com" in host or "vt.tiktok.com" in host):
        return "tiktok"
    if "instagram.com" in host and any(marker in full for marker in ("/p/", "/reel/", "/reels/", "/tv/")):
        return "instagram"
    if ("youtube.com" in host or "youtu.be" in host) and (
        "/watch" in full or "youtu.be/" in full or "/shorts/" in full or "/embed/" in full
    ):
        return "youtube"
    if ("facebook.com" in host or "fb.watch" in host) and (
        "fb.watch" in host or "/reel/" in full or "/videos/" in full or ("/watch/" in full and "v" in qs)
    ):
        return "facebook"
    return "unknown"


def _unwrap_search_redirect(url: str) -> str:
    """Resolve common search-engine redirect wrappers to the real target URL."""
    url = (url or "").strip()
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.netloc or "").lower()
        qs = urllib.parse.parse_qs(parsed.query)
        uddg = (qs.get("uddg") or [None])[0]
        if uddg:
            decoded = urllib.parse.unquote(str(uddg))
            if decoded.startswith("http"):
                return decoded
        bing_u = (qs.get("u") or [None])[0]
        if bing_u and str(bing_u).startswith("a1") and ("bing.com" in host or "bing.net" in host):
            b64 = str(bing_u)[2:]
            b64 += "=" * (-len(b64) % 4)
            try:
                decoded = base64.urlsafe_b64decode(b64).decode("utf-8", "replace")
            except Exception:
                decoded = ""
            if decoded.startswith("http"):
                return decoded
    except Exception:
        pass
    return url


class BrowserAssetFinder:
    """Thin wrapper around agent-browser CLI for public link discovery."""

    def __init__(self, timeout_seconds: int = 60):
        self.timeout = max(10, int(timeout_seconds or 60))
        exe = shutil.which("agent-browser") or shutil.which("agent-browser.cmd") or "agent-browser"
        self.executable = exe
        self._node_js = None
        if str(exe).lower().endswith((".cmd", ".bat")):
            js = Path(exe).parent / "node_modules" / "agent-browser" / "bin" / "agent-browser.js"
            node = shutil.which("node")
            if js.exists() and node:
                self.executable = node
                self._node_js = str(js)
        self._available = bool(self.executable) and (
            self._node_js is not None
            or shutil.which(self.executable) is not None
            or os.path.exists(self.executable)
        )

    def is_available(self) -> bool:
        return self._available

    def _run(self, args: List[str], timeout: Optional[int] = None) -> str:
        exe = self.executable
        args = [str(a) for a in args]
        if self._node_js:
            cmd = [exe, self._node_js] + args
        elif exe.lower().endswith((".cmd", ".bat")):
            cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/c", exe] + args
        else:
            cmd = [exe] + args
        result = subprocess.run(
            cmd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout or self.timeout,
            creationflags=SUBPROCESS_FLAGS,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(err[-500:] or f"agent-browser {args[0]} gagal")
        return result.stdout or ""

    @staticmethod
    def _parse_eval(raw: str) -> Any:
        raw = (raw or "").strip()
        if not raw:
            return None
        try:
            val = json.loads(raw)
        except Exception:
            return None
        if isinstance(val, str):
            try:
                return json.loads(val)
            except Exception:
                return val
        return val

    def _eval_json(self, js: str) -> Any:
        raw = self._run(["eval", js], timeout=45)
        return self._parse_eval(raw)

    def discover_video_sources(self, queries: List[str], max_results: int = 8) -> List[Dict[str, Any]]:
        if not self.is_available():
            raise RuntimeError("agent-browser tidak ditemukan di PATH")
        max_results = max(1, min(int(max_results or 8), 20))
        results: List[Dict[str, Any]] = []
        seen = set()
        js = r"""
JSON.stringify((() => {
  const out = [];
  const seen = new Set();
  const nodes = document.querySelectorAll('ytd-video-renderer, ytd-rich-item-renderer, ytd-grid-video-renderer');
  nodes.forEach((el) => {
    const a = el.querySelector('a#video-title')
      || el.querySelector('a.yt-lockup-metadata-view-model-wiz__title')
      || el.querySelector('a[href*="/watch?v="]')
      || el.querySelector('a[href*="youtu.be/"]');
    if (!a) return;
    const href = a.getAttribute('href') || '';
    const m = href.match(/[?&]v=([A-Za-z0-9_-]{11})/) || href.match(/youtu\.be\/([A-Za-z0-9_-]{11})/);
    if (!m || seen.has(m[1])) return;
    seen.add(m[1]);
    const title = (a.getAttribute('title') || a.textContent || '').trim();
    const durEl = el.querySelector('ytd-thumbnail-overlay-time-status-renderer, .yt-lockup-metadata-view-model-wiz__thumbnail-overlay-time-status-renderer, #duration, span.inline-metadata-item');
    const durationText = durEl ? (durEl.textContent || '').trim() : '';
    out.push({ id: m[1], title, duration_text: durationText, url: 'https://www.youtube.com/watch?v=' + m[1] });
  });
  return out.slice(0, 12);
})())
""".strip()

        try:
            for q in (queries or [])[:4]:
                q = (q or "").strip()
                if not q:
                    continue
                search_url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(q)
                self._run(["open", search_url], timeout=45)
                self._run(["wait", "2500"], timeout=15)
                data = self._eval_json(js)
                for item in data or []:
                    vid = str(item.get("id") or "")
                    url = str(item.get("url") or "")
                    if not vid or not url or vid in seen:
                        continue
                    seen.add(vid)
                    results.append({
                        "type": "url",
                        "provider": "youtube",
                        "platform": "youtube",
                        "url": url,
                        "title": item.get("title") or url,
                        "duration": _parse_duration_seconds(item.get("duration_text") or ""),
                        "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                        "query": q,
                        "source": "browser_discovery",
                        "status": "candidate",
                        "review_status": "unverified",
                        "verification_status": "unverified",
                        "license_status": "unverified",
                        "selected": False,
                        "local_path": "",
                        "transcript_path": "",
                        "transcript_segments": [],
                    })
                    if len(results) >= max_results:
                        break
                if len(results) >= max_results:
                    break
        finally:
            try:
                self._run(["close"], timeout=10)
            except Exception:
                pass
        return results[:max_results]


    @staticmethod
    def _native_platform_urls(platform: str, query: str) -> List[str]:
        q = urllib.parse.quote(query)
        if platform == "facebook":
            return [
                f"https://m.facebook.com/watch/explore/{q}/",
                f"https://en-gb.facebook.com/watch/explore/{q}/",
            ]
        if platform == "tiktok":
            return [f"https://www.tiktok.com/search?q={q}"]
        if platform == "instagram":
            return [f"https://www.instagram.com/explore/search/?q={q}"]
        if platform == "youtube":
            return [f"https://www.youtube.com/results?search_query={q}"]
        return []

    def _is_platform_media_url(self, platform: str, url: str) -> bool:
        return _classify_media_platform(url) == platform

    def _discover_native_platform(self, platform: str, query: str, max_results: int = 8) -> List[Dict[str, str]]:
        urls = self._native_platform_urls(platform, query)
        if not urls:
            return []
        js = r"""
JSON.stringify(Array.from(document.querySelectorAll('a[href]')).map(a => ({
  title: ((a.getAttribute('aria-label') || a.textContent || '') + '').trim(),
  url: a.href || ''
})).filter(x => x.url && !x.url.startsWith('javascript:')).slice(0, 120))
""".strip()
        out: List[Dict[str, str]] = []
        seen = set()
        for page_url in urls:
            try:
                self._run(["open", page_url], timeout=45)
                self._run(["wait", "2200"], timeout=15)
                data = self._eval_json(js) or []
            except Exception:
                data = []
            for item in data:
                href = _unwrap_search_redirect(str(item.get("url") or ""))
                if not href or href in seen or not self._is_platform_media_url(platform, href):
                    continue
                seen.add(href)
                out.append({"url": href, "title": (item.get("title") or href).strip()})
                if len(out) >= max_results:
                    return out
            if out:
                break
        return out

    def discover_media_sources(self, queries: List[str], max_results: int = 12, platforms: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Discover public video links across YouTube/TikTok/Instagram/Facebook.

        Uses platform public pages first (Facebook watch/explore works without
        login; TikTok/Instagram often require login and may return no candidates),
        then falls back to web search result pages with redirect unwrapping.
        """
        if not self.is_available():
            raise RuntimeError("agent-browser tidak ditemukan di PATH")
        max_results = max(1, min(int(max_results or 12), 30))
        wanted = {str(p).lower() for p in (platforms or ["youtube", "tiktok", "instagram", "facebook"])}
        js = r"""
JSON.stringify((() => {
  const out = [];
  const seen = new Set();
  const nodes = document.querySelectorAll('a.result__a, a.result-link, .result a[href], li.b_algo h2 a, .b_algo h2 a');
  nodes.forEach((a) => {
    let href = a.href || '';
    try {
      const u = new URL(href, location.href);
      const uddg = u.searchParams.get('uddg');
      if (uddg) href = decodeURIComponent(uddg);
    } catch (e) {}
    if (!href || href.startsWith('javascript:') || seen.has(href)) return;
    seen.add(href);
    out.push({ title: (a.textContent || '').trim(), url: href });
  });
  return out.slice(0, 15);
})())
""".strip()

        domain_map = {
            "youtube": "youtube.com",
            "tiktok": "tiktok.com",
            "instagram": "instagram.com",
            "facebook": "facebook.com",
        }
        ordered_platforms = [p for p in ("youtube", "tiktok", "instagram", "facebook") if p in wanted]
        if not ordered_platforms:
            ordered_platforms = list(domain_map)
        engines = [
            "https://www.bing.com/search?q=",
            "https://duckduckgo.com/html/?q=",
            "https://html.duckduckgo.com/html/?q=",
        ]

        results: List[Dict[str, Any]] = []
        seen_urls = set()

        def add_candidate(platform: str, url: str, title: str, query: str, source: str) -> bool:
            url = _unwrap_search_redirect(str(url or ""))
            if not url or url in seen_urls:
                return False
            if _classify_media_platform(url) != platform:
                return False
            seen_urls.add(url)
            results.append({
                "type": "url",
                "provider": platform,
                "platform": platform,
                "url": url,
                "title": (title or url).strip(),
                "duration": 0.0,
                "thumbnail": "",
                "query": query,
                "source": source,
                "status": "candidate",
                "review_status": "unverified",
                "verification_status": "unverified",
                "license_status": "unverified",
                "selected": False,
                "local_path": "",
                "transcript_path": "",
                "transcript_segments": [],
            })
            return True

        try:
            for q in (queries or [])[:3]:
                q = (q or "").strip()
                if not q:
                    continue
                for platform in ordered_platforms:
                    domain = domain_map.get(platform)
                    search_q = f"site:{domain} {q}" if domain else q

                    native_items = self._discover_native_platform(platform, q, max_results=max(2, min(max_results, 8)))
                    for item in native_items:
                        add_candidate(platform, item.get("url"), item.get("title"), q, f"browser_native_{platform}")
                        if len(results) >= max_results:
                            break
                    if native_items or len(results) >= max_results:
                        if len(results) >= max_results:
                            break
                        continue

                    data = []
                    for base in engines:
                        try:
                            self._run(["open", base + urllib.parse.quote(search_q)], timeout=45)
                            self._run(["wait", "1800"], timeout=15)
                            data = self._eval_json(js) or []
                        except Exception:
                            data = []
                        if data:
                            break
                    for item in data or []:
                        if add_candidate(platform, item.get("url"), item.get("title"), search_q, "browser_web_search"):
                            pass
                        if len(results) >= max_results:
                            break
                    if len(results) >= max_results:
                        break
                if len(results) >= max_results:
                    break
        finally:
            try:
                self._run(["close"], timeout=10)
            except Exception:
                pass
        return results[:max_results]


def get_browser_asset_finder(timeout_seconds: int = 60) -> BrowserAssetFinder:
    return BrowserAssetFinder(timeout_seconds=timeout_seconds)
