"""
Centralized AI Provider & Model Routing Engine
Provides provider registry, API key resolution, model discovery, task routing,
fallback execution, and backward-compatible migration.
"""

import copy
import os
import re
from typing import Any, Callable, Dict, List, Optional

from config.ai_provider_config import (
    AI_PROVIDERS_CONFIG,
    SPECIALIZED_MODELS,
    get_provider_base_url,
    get_provider_capabilities,
    get_provider_name,
    has_capability,
)

# Placeholders that must never be considered valid API keys
KEY_PLACEHOLDERS = (
    "MASUKKAN_",
    "KOSONGKAN_",
    "sk-xxxxxxxx",
    "gsk_xxxxxxx",
    "AIzaxxxxxxx",
    "optional",
    "your_key_here",
    "sk-ant-xxxxx",
    "ytc-xxxxx",
)

# Standard URL mapping for provider detection
URL_MAPPING = {
    ":20128": "9router",
    "9router": "9router",
    "omnirouter": "omnirouter",
    "api.groq.com": "groq",
    "openrouter.ai": "openrouter",
    "api.openai.com": "openai",
    "generativelanguage.googleapis.com": "google",
    "api.anthropic.com": "anthropic",
    "ytclip.org": "ytclip",
    "api.mistral.ai": "mistral",
    "api.together.xyz": "together",
    "api.cohere.ai": "cohere",
}

# Environment variable mappings
ENV_KEY_MAPPING = {
    "9router": ["NINE_ROUTER_API_KEY", "ROUTER_API_KEY", "ANTHROPIC_AUTH_TOKEN"],
    "omnirouter": ["OMNIROUTER_API_KEY"],
    "groq": ["GROQ_API_KEY"],
    "openrouter": ["OPENROUTER_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
    "google": ["GOOGLE_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY"],
    "ytclip": ["YTCLIP_API_KEY"],
    "mistral": ["MISTRAL_API_KEY"],
    "together": ["TOGETHER_API_KEY"],
    "cohere": ["COHERE_API_KEY"],
    "huggingface": ["HUGGINGFACE_API_KEY"],
    "replicate": ["REPLICATE_API_KEY"],
    "custom": ["CUSTOM_AI_API_KEY"],
}


def sanitize_text(text: str) -> str:
    """Strip potential API keys / Bearer tokens from text/error strings."""
    if not text:
        return ""
    # Mask Bearer tokens
    masked = re.sub(r"(Bearer\s+)[A-Za-z0-9_\-\.]{8,}", r"\1[MASKED]", str(text))
    # Mask common key patterns (sk-..., gsk_..., etc.)
    masked = re.sub(r"\b(sk-[A-Za-z0-9_\-]{8,})", "[MASKED_KEY]", masked)
    masked = re.sub(r"\b(gsk_[A-Za-z0-9_\-]{8,})", "[MASKED_KEY]", masked)
    masked = re.sub(r"\b(AIza[A-Za-z0-9_\-]{8,})", "[MASKED_KEY]", masked)
    return masked


def is_valid_key(api_key: Optional[str]) -> bool:
    """Return True if api_key is non-empty and not a known placeholder."""
    if not api_key:
        return False
    s = str(api_key).strip()
    if not s:
        return False
    for placeholder in KEY_PLACEHOLDERS:
        if s.startswith(placeholder) or s == placeholder:
            return False
    return len(s) >= 4


def normalize_model_for_provider(model: str, provider_id: str) -> str:
    """
    Normalizes model prefix according to router conventions:
    - 9router uses 'ag/' prefix (e.g. 'ag/gemini-3.8-flash-high')
    - Omnirouter uses 'antigravity/' prefix (e.g. 'antigravity/gemini-3.8-flash-high')
    """
    if not model:
        return model
    m = model.strip()
    p_lower = str(provider_id or "").lower()
    if p_lower == "omnirouter":
        if m.startswith("ag/"):
            return "antigravity/" + m[3:]
    elif p_lower == "9router":
        if m.startswith("antigravity/"):
            return "ag/" + m[12:]
    return m


def detect_provider_from_url(base_url: str) -> str:
    """Detect provider key from base URL string."""
    if not base_url:
        return "custom"
    url_lower = str(base_url).lower()
    for pattern, provider in URL_MAPPING.items():
        if pattern.lower() in url_lower:
            return provider
    return "custom"


def get_default_gateway_config() -> Dict[str, Any]:
    """Generate default ai_gateway config dictionary."""
    providers: Dict[str, Any] = {}
    for key, info in AI_PROVIDERS_CONFIG.items():
        providers[key] = {
            "enabled": True,
            "base_url": info.get("base_url", ""),
            "api_key": "",
            "api_key_env": info.get("api_key_env", ""),
            "model_cache": [],
            "capabilities": list(info.get("capabilities", ["chat"])),
            "default_model": (
                info.get("default_models", [""])[0]
                if info.get("default_models")
                else ""
            ),
        }

    return {
        "enabled": True,
        "preferred_provider": "9router",
        "fallback_enabled": True,
        "fallback_providers": ["9router", "omnirouter", "openrouter", "groq"],
        "providers": providers,
    }


def resolve_api_key(
    provider_id: str,
    explicit_key: str = "",
    config: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Resolve API key following priority:
    1. Explicit valid key passed in argument.
    2. Explicit valid key in config['ai_gateway']['providers'][provider_id]['api_key'].
    3. Environment variables mapped to the provider.
    4. Explicit key in task config (if provided via config).
    Returns empty string if no valid key found.
    """
    # 1. Check explicit key
    if is_valid_key(explicit_key):
        return explicit_key.strip()

    # 2. Check ai_gateway configuration
    if config and isinstance(config, dict):
        gw = config.get("ai_gateway", {})
        gw_prov = gw.get("providers", {}).get(provider_id, {})
        gw_key = gw_prov.get("api_key", "")
        if is_valid_key(gw_key):
            return gw_key.strip()

    # 3. Check environment variables
    env_vars = ENV_KEY_MAPPING.get(provider_id, [])
    # Also check if provider config names a specific env var
    if config and isinstance(config, dict):
        custom_env = (
            config.get("ai_gateway", {})
            .get("providers", {})
            .get(provider_id, {})
            .get("api_key_env")
        )
        if custom_env and custom_env not in env_vars:
            env_vars = [custom_env] + env_vars

    for env_var in env_vars:
        val = os.environ.get(env_var, "").strip()
        if is_valid_key(val):
            return val

    # 4. Fallback: check legacy config_api_key if passed
    if explicit_key and not is_valid_key(explicit_key):
        return ""

    return ""


def get_provider(config: Optional[Dict[str, Any]], provider_id: str) -> Dict[str, Any]:
    """
    Get merged provider dictionary combining static registry with dynamic gateway config.
    """
    static_info = AI_PROVIDERS_CONFIG.get(provider_id, {})
    gw_prov: Dict[str, Any] = {}
    if config and isinstance(config, dict):
        gw = config.get("ai_gateway", {})
        gw_prov = gw.get("providers", {}).get(provider_id, {})

    base_url = gw_prov.get("base_url") or static_info.get("base_url", "")
    explicit_key = gw_prov.get("api_key", "")
    resolved_key = resolve_api_key(provider_id, explicit_key, config)

    capabilities = gw_prov.get("capabilities") or static_info.get("capabilities") or ["chat"]
    model_cache = gw_prov.get("model_cache", [])

    return {
        "id": provider_id,
        "name": static_info.get("name", provider_id.title()),
        "enabled": gw_prov.get("enabled", True),
        "base_url": base_url,
        "api_key": resolved_key,
        "has_key": bool(resolved_key),
        "api_key_env": gw_prov.get("api_key_env") or static_info.get("api_key_env", ""),
        "capabilities": list(capabilities),
        "model_cache": list(model_cache),
        "default_models": list(static_info.get("default_models", [])),
    }


def get_enabled_providers(
    config: Optional[Dict[str, Any]], capability: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Return list of enabled providers, optionally filtered by capability."""
    enabled: List[Dict[str, Any]] = []
    # Collect all known provider IDs
    all_keys = list(AI_PROVIDERS_CONFIG.keys())
    if config and isinstance(config, dict):
        gw_providers = config.get("ai_gateway", {}).get("providers", {})
        for k in gw_providers.keys():
            if k not in all_keys:
                all_keys.append(k)

    for pid in all_keys:
        p = get_provider(config, pid)
        if p.get("enabled", True):
            if capability is None or capability in p.get("capabilities", []):
                enabled.append(p)
    return enabled


def resolve_task_provider(
    config: Optional[Dict[str, Any]], task_key: str
) -> Dict[str, Any]:
    """
    Resolve provider, base_url, api_key, model, and capabilities for a specific task.
    Backward compatible with tasks that only had base_url/model.
    """
    if not config or not isinstance(config, dict):
        config = {}

    ai_providers = config.get("ai_providers", {})
    task_cfg = ai_providers.get(task_key, {})

    # Determine provider key
    provider_id = task_cfg.get("provider", "")
    base_url = task_cfg.get("base_url", "")

    if not provider_id:
        if base_url:
            provider_id = detect_provider_from_url(base_url)
        else:
            # Check gateway preferred provider
            provider_id = config.get("ai_gateway", {}).get("preferred_provider", "9router")

    # Get provider config
    provider_info = get_provider(config, provider_id)

    # Effective base_url
    effective_base_url = base_url or provider_info.get("base_url", "")

    # Effective API key
    explicit_task_key = task_cfg.get("api_key", "")
    resolved_key = resolve_api_key(provider_id, explicit_task_key, config)

    # Effective model
    model = task_cfg.get("model", "")
    if not model:
        # Check specialized models
        spec_models = SPECIALIZED_MODELS.get(task_key, {}).get(provider_id, [])
        if spec_models:
            model = spec_models[0]
        elif provider_info.get("default_models"):
            model = provider_info["default_models"][0]

    model = normalize_model_for_provider(model, provider_id)

    system_message = task_cfg.get("system_message", "")

    return {
        "task": task_key,
        "provider": provider_id,
        "name": provider_info.get("name", provider_id),
        "base_url": effective_base_url,
        "api_key": resolved_key,
        "has_key": bool(resolved_key),
        "model": model,
        "system_message": system_message,
        "capabilities": provider_info.get("capabilities", ["chat"]),
    }


def get_fallback_chain(
    config: Optional[Dict[str, Any]],
    task_key: str,
    capability: str = "chat",
) -> List[Dict[str, Any]]:
    """
    Build ordered fallback chain for task_key:
    [primary_resolved_provider, fallback_1, fallback_2, ...]
    Filtered by capability and enabled state without duplicates.
    """
    if not config or not isinstance(config, dict):
        config = {}

    chain: List[Dict[str, Any]] = []
    seen_providers = set()

    # 1. Primary provider
    primary = resolve_task_provider(config, task_key)
    p_id = primary.get("provider")
    if p_id and capability in primary.get("capabilities", []):
        chain.append(primary)
        seen_providers.add(p_id)

    # Check if fallback is globally enabled
    gw = config.get("ai_gateway", {})
    fallback_enabled = gw.get("fallback_enabled", True)
    if not fallback_enabled:
        return chain

    # 2. Global fallback providers
    fb_list = gw.get("fallback_providers", ["9router", "openrouter", "groq"])
    for fb_id in fb_list:
        if fb_id in seen_providers:
            continue

        prov = get_provider(config, fb_id)
        if not prov.get("enabled", True):
            continue
        if capability not in prov.get("capabilities", []):
            continue

        # Determine best model for this fallback provider
        fb_model = ""
        spec_models = SPECIALIZED_MODELS.get(task_key, {}).get(fb_id, [])
        if spec_models:
            fb_model = spec_models[0]
        elif prov.get("model_cache"):
            fb_model = prov["model_cache"][0]
        elif prov.get("default_models"):
            fb_model = prov["default_models"][0]

        fb_model = normalize_model_for_provider(fb_model, fb_id)

        chain.append({
            "task": task_key,
            "provider": fb_id,
            "name": prov.get("name", fb_id),
            "base_url": prov.get("base_url", ""),
            "api_key": prov.get("api_key", ""),
            "has_key": bool(prov.get("api_key")),
            "model": fb_model,
            "system_message": primary.get("system_message", ""),
            "capabilities": prov.get("capabilities", []),
        })
        seen_providers.add(fb_id)

    return chain


def load_models(
    provider_id: str,
    config: Optional[Dict[str, Any]] = None,
    base_url: str = "",
    api_key: str = "",
    timeout_seconds: int = 20,
) -> List[str]:
    """
    Fetch available models from OpenAI-compatible /v1/models endpoint.
    Updates config's model_cache if config is provided.
    Raises actionable exceptions without secret leakage.
    """
    from openai import OpenAI

    prov = get_provider(config, provider_id)
    url = (base_url or prov.get("base_url", "")).strip()
    key = (api_key or prov.get("api_key", "")).strip()

    if not url:
        raise ValueError(f"Provider '{provider_id}' base URL is not configured.")

    if not key and provider_id not in ("custom",):
        raise ValueError(f"API key is missing for provider '{provider_id}'.")

    try:
        client = OpenAI(api_key=key or "optional", base_url=url, timeout=timeout_seconds, max_retries=0)
        resp = client.models.list()
        models = [m.id for m in resp.data if hasattr(m, "id") and m.id]
        models.sort()

        # Update cache in config if provided
        if config and isinstance(config, dict) and "ai_gateway" in config:
            gw_prov = (
                config["ai_gateway"]
                .setdefault("providers", {})
                .setdefault(provider_id, {})
            )
            gw_prov["model_cache"] = models

        return models
    except Exception as e:
        safe_msg = sanitize_text(str(e))
        raise RuntimeError(f"Failed to load models for '{provider_id}' from {url}: {safe_msg}") from None


def execute_with_fallback(
    config: Dict[str, Any],
    task_key: str,
    capability: str,
    operation: Callable[[Any, Dict[str, Any]], Any],
    logger: Optional[Any] = None,
) -> Any:
    """
    Execute an operation with fallback chain routing.
    operation receives (OpenAI_client, resolved_provider_dict).
    """
    from openai import OpenAI

    chain = get_fallback_chain(config, task_key, capability=capability)
    if not chain:
        raise RuntimeError(
            f"No enabled provider with capability '{capability}' available for task '{task_key}'."
        )

    errors = []
    for idx, prov in enumerate(chain):
        p_name = prov.get("name") or prov.get("provider")
        p_model = prov.get("model", "")
        p_url = prov.get("base_url", "")
        p_key = prov.get("api_key", "")

        if not p_key and prov.get("provider") not in ("custom",):
            msg = f"Provider '{p_name}' skipped (API key not configured)"
            if logger:
                logger.warning(msg)
            errors.append(msg)
            continue

        try:
            if logger:
                route_label = "primary" if idx == 0 else f"fallback_{idx}"
                logger.info(f"AI Route [{route_label}]: {p_name} | Model: {p_model}")

            client = OpenAI(
                api_key=p_key or "optional",
                base_url=p_url,
                timeout=120,
                max_retries=1,
            )
            return operation(client, prov)
        except Exception as e:
            safe_err = sanitize_text(str(e))
            fail_msg = f"Provider '{p_name}' (model: {p_model}) failed: {safe_err}"
            if logger:
                logger.warning(fail_msg)
            errors.append(fail_msg)

    # All failed
    combined_errors = "\n".join(f"- {err}" for err in errors)
    raise RuntimeError(
        f"All AI providers in fallback chain failed for task '{task_key}':\n{combined_errors}"
    )


def migrate_to_gateway_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure config has a fully populated, backward-compatible ai_gateway structure.
    Does not delete any legacy keys. Idempotent.
    """
    if "ai_gateway" not in config:
        config["ai_gateway"] = get_default_gateway_config()

    gw = config["ai_gateway"]
    if not isinstance(gw, dict):
        config["ai_gateway"] = get_default_gateway_config()
        gw = config["ai_gateway"]

    # Ensure required fields in ai_gateway
    if "providers" not in gw:
        gw["providers"] = get_default_gateway_config()["providers"]
    if "preferred_provider" not in gw:
        gw["preferred_provider"] = "9router"
    if "fallback_enabled" not in gw:
        gw["fallback_enabled"] = True
    if "fallback_providers" not in gw:
        gw["fallback_providers"] = ["9router", "omnirouter", "openrouter", "groq"]

    # Ensure all registered providers exist in gw["providers"]
    default_gw = get_default_gateway_config()
    for prov_key, default_info in default_gw["providers"].items():
        if prov_key not in gw["providers"]:
            gw["providers"][prov_key] = copy.deepcopy(default_info)
        else:
            p = gw["providers"][prov_key]
            # Merge missing keys
            for k, v in default_info.items():
                if k not in p:
                    p[k] = copy.deepcopy(v)

    # Sync from existing ai_providers tasks
    ai_providers = config.get("ai_providers", {})
    for task_key, task_cfg in ai_providers.items():
        if not isinstance(task_cfg, dict):
            continue
        base_url = task_cfg.get("base_url", "")
        # Detect provider if not set
        if not task_cfg.get("provider"):
            task_cfg["provider"] = detect_provider_from_url(base_url)

        p_id = task_cfg["provider"]
        if p_id in gw["providers"]:
            prov_entry = gw["providers"][p_id]
            # If provider entry has no base_url but task has it, adopt it
            if base_url and not prov_entry.get("base_url"):
                prov_entry["base_url"] = base_url
            # If task has api_key and provider has none, adopt it
            t_key = task_cfg.get("api_key", "")
            if is_valid_key(t_key) and not is_valid_key(prov_entry.get("api_key")):
                prov_entry["api_key"] = t_key

    return config


def probe_single_endpoint(base_url: str, api_key: str = "", timeout: float = 3.5) -> Dict[str, Any]:
    """
    Test an OpenAI-compatible endpoint with models.list().
    Returns dict with {ok, status, base_url, api_key, models, error}
    """
    from openai import OpenAI

    url = str(base_url or "").strip().rstrip("/")
    if not url:
        return {
            "ok": False,
            "status": "no_url",
            "base_url": "",
            "api_key": "",
            "models": [],
            "error": "No base URL configured",
        }

    key = str(api_key or "optional").strip()
    try:
        client = OpenAI(api_key=key, base_url=url, timeout=timeout, max_retries=0)
        resp = client.models.list()
        models = [str(getattr(m, "id", m)) for m in (getattr(resp, "data", None) or [])]
        models = sorted({m for m in models if m})
        return {
            "ok": True,
            "status": "connected",
            "base_url": url,
            "api_key": key,
            "models": models,
            "error": "",
        }
    except Exception as e:
        safe_err = sanitize_text(str(e))
        err_lower = safe_err.lower()
        if (
            "401" in err_lower
            or "unauthorized" in err_lower
            or "forbidden" in err_lower
            or "auth" in err_lower
        ):
            status = "auth_error"
        elif (
            "connection" in err_lower
            or "refused" in err_lower
            or "offline" in err_lower
        ):
            status = "unreachable"
        elif "timeout" in err_lower or "timed out" in err_lower:
            status = "timeout"
        else:
            status = "error"
        return {
            "ok": False,
            "status": status,
            "base_url": url,
            "api_key": key,
            "models": [],
            "error": safe_err,
        }


def probe_router(
    provider_id: str,
    config: Optional[Dict[str, Any]] = None,
    timeout: float = 3.5,
) -> Dict[str, Any]:
    """
    Probes candidate URLs and candidate API keys for a router (9router or omnirouter).
    Tests connectivity and authorization, returning detailed results.
    """
    gw_prov: Dict[str, Any] = {}
    if config and isinstance(config, dict):
        gw_prov = config.get("ai_gateway", {}).get("providers", {}).get(provider_id, {})

    # 1. Candidate URLs
    candidate_urls: List[str] = []
    cfg_url = gw_prov.get("base_url") or AI_PROVIDERS_CONFIG.get(provider_id, {}).get("base_url", "")
    if cfg_url:
        candidate_urls.append(cfg_url)

    if provider_id == "9router":
        env_url = os.environ.get("NINE_ROUTER_BASE_URL") or os.environ.get("ROUTER_BASE_URL")
        if env_url:
            candidate_urls.append(env_url)
        candidate_urls.extend(["http://localhost:20128/v1", "http://127.0.0.1:20128/v1"])
    elif provider_id == "omnirouter":
        env_url = os.environ.get("OMNIROUTER_BASE_URL")
        if env_url:
            candidate_urls.append(env_url)
        candidate_urls.extend([
            "http://localhost:20129/v1",
            "http://127.0.0.1:20129/v1",
            "http://localhost:20128/v1",
            "http://localhost:8000/v1",
            "http://localhost:3000/v1",
        ])

    seen_urls = set()
    dedup_urls: List[str] = []
    for u in candidate_urls:
        clean = u.strip().rstrip("/")
        if clean and clean not in seen_urls:
            seen_urls.add(clean)
            dedup_urls.append(clean)

    # 2. Candidate Keys
    candidate_keys: List[str] = []
    cfg_key = gw_prov.get("api_key", "")
    if cfg_key:
        candidate_keys.append(cfg_key)

    if provider_id == "9router":
        for env_var in ["NINE_ROUTER_API_KEY", "ROUTER_API_KEY", "ANTHROPIC_AUTH_TOKEN"]:
            val = os.environ.get(env_var, "").strip()
            if val:
                candidate_keys.append(val)
        candidate_keys.extend(["optional", "sk-antigravity", ""])
    elif provider_id == "omnirouter":
        for env_var in ["OMNIROUTER_API_KEY", "NINE_ROUTER_API_KEY"]:
            val = os.environ.get(env_var, "").strip()
            if val:
                candidate_keys.append(val)
        candidate_keys.extend(["optional", "sk-antigravity", ""])

    seen_keys = set()
    dedup_keys: List[str] = []
    for k in candidate_keys:
        if k not in seen_keys:
            seen_keys.add(k)
            dedup_keys.append(k)

    last_failure = None
    for url in dedup_urls:
        for key in dedup_keys:
            res = probe_single_endpoint(url, key, timeout=timeout)
            if res["ok"]:
                res["provider"] = provider_id
                return res
            if last_failure is None or res["status"] == "auth_error":
                last_failure = res

    if last_failure:
        last_failure["provider"] = provider_id
        return last_failure

    return {
        "ok": False,
        "status": "unreachable",
        "provider": provider_id,
        "base_url": dedup_urls[0] if dedup_urls else "",
        "api_key": dedup_keys[0] if dedup_keys else "",
        "models": [],
        "error": "No reachable endpoint found",
    }


def auto_detect_and_select_router(config: Dict[str, Any], timeout: float = 3.5) -> Dict[str, Any]:
    """
    Probes both 9router and Omnirouter and determines which router can be called and works.
    Returns:
    {
        "active_provider": "9router" | "omnirouter" | None,
        "working_probe": probe_result_dict or None,
        "probes": {
            "9router": {...},
            "omnirouter": {...}
        },
        "summary": "..."
    }
    """
    probe_9router = probe_router("9router", config=config, timeout=timeout)
    probe_omni = probe_router("omnirouter", config=config, timeout=timeout)

    active_provider = None
    working_probe = None

    pref = config.get("ai_gateway", {}).get("preferred_provider", "9router")

    if probe_9router["ok"] and probe_omni["ok"]:
        if pref in ("9router", "omnirouter"):
            active_provider = pref
            working_probe = probe_9router if pref == "9router" else probe_omni
        else:
            active_provider = "9router"
            working_probe = probe_9router
        summary = f"Kedua router aktif! Menggunakan {active_provider} ({working_probe['base_url']})."
    elif probe_9router["ok"]:
        active_provider = "9router"
        working_probe = probe_9router
        summary = f"9router aktif dan berfungsi ({working_probe['base_url']})! {len(working_probe['models'])} model tersedia."
    elif probe_omni["ok"]:
        active_provider = "omnirouter"
        working_probe = probe_omni
        summary = f"Omnirouter aktif dan berfungsi ({working_probe['base_url']})! {len(working_probe['models'])} model tersedia."
    else:
        active_provider = None
        working_probe = None
        err_9 = probe_9router.get("error") or probe_9router.get("status")
        err_omni = probe_omni.get("error") or probe_omni.get("status")
        summary = f"Tidak ada router lokal yang merespons (9router: {err_9} | Omnirouter: {err_omni})."

    return {
        "active_provider": active_provider,
        "working_probe": working_probe,
        "probes": {
            "9router": probe_9router,
            "omnirouter": probe_omni,
        },
        "summary": summary,
    }


def apply_active_router_to_config(config: Dict[str, Any], working_probe: Dict[str, Any]) -> Dict[str, Any]:
    """
    Applies the working router probe result to config so the app immediately uses it.
    """
    if not working_probe or not working_probe.get("ok"):
        return config

    prov_id = working_probe.get("provider")
    base_url = working_probe.get("base_url")
    api_key = working_probe.get("api_key", "")
    models = working_probe.get("models", [])

    gw = config.setdefault("ai_gateway", get_default_gateway_config())
    gw["preferred_provider"] = prov_id
    gw_prov = gw.setdefault("providers", {}).setdefault(prov_id, {})
    gw_prov["enabled"] = True
    gw_prov["base_url"] = base_url
    if api_key:
        gw_prov["api_key"] = api_key
    if models:
        gw_prov["model_cache"] = models

    # Find best antigravity model from models or default
    if prov_id == "omnirouter":
        best_model = "antigravity/gemini-3.8-flash-high"
        ag_candidates = [
            "antigravity/gemini-3.8-flash-high",
            "antigravity/gemini-3.8-flash-medium",
            "antigravity/gemini-2.5-flash",
        ]
    else:
        best_model = "ag/gemini-3.8-flash-high"
        ag_candidates = [
            "ag/gemini-3.8-flash-high",
            "ag/gemini-3.8-flash-medium",
            "ag/gemini-2.5-flash",
        ]

    for cand in ag_candidates:
        if cand in models:
            best_model = cand
            break
    if not any(cand in models for cand in ag_candidates) and models:
        best_model = models[0]

    best_model = normalize_model_for_provider(best_model, prov_id)

    # Update relevant AI tasks in config
    ai_providers = config.setdefault("ai_providers", {})
    for task_key in ["highlight_finder", "youtube_title_maker"]:
        task_cfg = ai_providers.setdefault(task_key, {})
        task_cfg["provider"] = prov_id
        task_cfg["base_url"] = base_url
        if api_key:
            task_cfg["api_key"] = api_key
        task_cfg["model"] = best_model

    # Hook Maker is a Speech (TTS) model task, not a chat model task
    hook_cfg = ai_providers.setdefault("hook_maker", {})
    if any(x in str(hook_cfg.get("model", "")).lower() for x in ["gemini", "claude", "llama", "deepseek", "gpt-4", "gpt-3.5"]):
        hook_cfg["model"] = "tts-1"
    elif not hook_cfg.get("model"):
        hook_cfg["model"] = "tts-1"

    return config
