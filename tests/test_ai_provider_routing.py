"""
Unit and Integration Tests for AI Provider & Model Routing (Feature 08)
"""

import os
import unittest
from unittest.mock import MagicMock, patch

from config.ai_provider_config import (
    AI_PROVIDERS_CONFIG,
    get_provider_capabilities,
    has_capability,
)
from config.ai_router import (
    apply_active_router_to_config,
    auto_detect_and_select_router,
    detect_provider_from_url,
    execute_with_fallback,
    get_default_gateway_config,
    get_enabled_providers,
    get_fallback_chain,
    get_provider,
    is_valid_key,
    load_models,
    migrate_to_gateway_config,
    normalize_model_for_provider,
    probe_router,
    probe_single_endpoint,
    resolve_api_key,
    resolve_task_provider,
    sanitize_text,
)


class TestAIProviderRouting(unittest.TestCase):
    """Test suite for AI router logic, key resolution, migration, and fallback."""

    def setUp(self):
        self.mock_env = {
            "NINE_ROUTER_API_KEY": "test-9router-key",
            "OMNIROUTER_API_KEY": "test-omnirouter-key",
            "GROQ_API_KEY": "gsk_testgroqkey12345",
            "OPENROUTER_API_KEY": "sk-or-testkey12345",
            "OPENAI_API_KEY": "sk-testopenaikey12345",
        }

    def test_provider_url_detection(self):
        """Verify URL mapping detects standard and custom providers accurately."""
        self.assertEqual(detect_provider_from_url("http://localhost:20128/v1"), "9router")
        self.assertEqual(detect_provider_from_url("http://127.0.0.1:20128/v1"), "9router")
        self.assertEqual(detect_provider_from_url("https://omnirouter.internal/v1"), "omnirouter")
        self.assertEqual(detect_provider_from_url("https://api.groq.com/openai/v1"), "groq")
        self.assertEqual(detect_provider_from_url("https://openrouter.ai/api/v1"), "openrouter")
        self.assertEqual(detect_provider_from_url("https://api.openai.com/v1"), "openai")
        self.assertEqual(detect_provider_from_url("http://localhost:8000/v1"), "custom")
        self.assertEqual(detect_provider_from_url(""), "custom")

    def test_key_validation_and_placeholders(self):
        """Ensure placeholders are rejected and real keys accepted."""
        self.assertFalse(is_valid_key(""))
        self.assertFalse(is_valid_key(None))
        self.assertFalse(is_valid_key("MASUKKAN_KEY_ANDA"))
        self.assertFalse(is_valid_key("KOSONGKAN_JIKA_TIDAK_ADA"))
        self.assertFalse(is_valid_key("sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"))
        self.assertFalse(is_valid_key("optional"))
        self.assertFalse(is_valid_key("abc"))  # too short
        self.assertTrue(is_valid_key("sk-validkey123456789"))
        self.assertTrue(is_valid_key("my_custom_secret_key"))

    def test_normalize_model_prefixes(self):
        """Verify model prefix normalization between 9router ('ag/') and Omnirouter ('antigravity/')."""
        # Omnirouter expects 'antigravity/' prefix
        self.assertEqual(
            normalize_model_for_provider("ag/gemini-3.8-flash-high", "omnirouter"),
            "antigravity/gemini-3.8-flash-high",
        )
        self.assertEqual(
            normalize_model_for_provider("antigravity/gemini-3.8-flash-high", "omnirouter"),
            "antigravity/gemini-3.8-flash-high",
        )
        # 9router expects 'ag/' prefix
        self.assertEqual(
            normalize_model_for_provider("antigravity/gemini-3.8-flash-high", "9router"),
            "ag/gemini-3.8-flash-high",
        )
        self.assertEqual(
            normalize_model_for_provider("ag/gemini-3.8-flash-high", "9router"),
            "ag/gemini-3.8-flash-high",
        )
        # Other providers remain untouched
        self.assertEqual(
            normalize_model_for_provider("gpt-4o", "openai"),
            "gpt-4o",
        )

    def test_api_key_resolution_priority(self):
        """Test resolution priority: explicit config key > gateway config key > env var."""
        with patch.dict(os.environ, self.mock_env, clear=True):
            # 1. Explicit key provided
            key = resolve_api_key("9router", explicit_key="explicit-secret-key")
            self.assertEqual(key, "explicit-secret-key")

            # 2. Placeholder explicit key -> should fallback to env var
            key = resolve_api_key("9router", explicit_key="MASUKKAN_KEY")
            self.assertEqual(key, "test-9router-key")

            # 3. Omnirouter env var resolution
            key = resolve_api_key("omnirouter", explicit_key="")
            self.assertEqual(key, "test-omnirouter-key")

            # 4. Unknown provider with no env
            key = resolve_api_key("unknown_provider", explicit_key="")
            self.assertEqual(key, "")

    def test_text_sanitization(self):
        """Verify API keys and Bearer tokens are masked from logs and errors."""
        raw = "Error 401: Unauthorized for Bearer sk-1234567890abcdef and gsk_9876543210zyxw"
        cleaned = sanitize_text(raw)
        self.assertNotIn("sk-1234567890abcdef", cleaned)
        self.assertNotIn("gsk_9876543210zyxw", cleaned)
        self.assertIn("[MASKED]", cleaned)

    def test_config_migration(self):
        """Verify legacy configurations are migrated to ai_gateway structure seamlessly."""
        legacy_config = {
            "ai_providers": {
                "highlight_finder": {
                    "base_url": "http://localhost:20128/v1",
                    "api_key": "",
                    "model": "ag/gemini-3.8-flash-high",
                },
                "caption_maker": {
                    "base_url": "https://api.groq.com/openai/v1",
                    "api_key": "gsk_customkey",
                    "model": "whisper-large-v3-turbo",
                },
            }
        }

        migrated = migrate_to_gateway_config(legacy_config)

        self.assertIn("ai_gateway", migrated)
        gw = migrated["ai_gateway"]
        self.assertTrue(gw["enabled"])
        self.assertIn("9router", gw["providers"])
        self.assertIn("omnirouter", gw["providers"])
        self.assertIn("groq", gw["providers"])

        # Check that provider pair was set on tasks
        self.assertEqual(migrated["ai_providers"]["highlight_finder"]["provider"], "9router")
        self.assertEqual(migrated["ai_providers"]["caption_maker"]["provider"], "groq")

        # Check that groq adopted the valid custom key
        self.assertEqual(gw["providers"]["groq"]["api_key"], "gsk_customkey")

    def test_resolve_task_provider(self):
        """Verify resolve_task_provider resolves provider, model, and capabilities."""
        config = {
            "ai_gateway": get_default_gateway_config(),
            "ai_providers": {
                "highlight_finder": {
                    "provider": "9router",
                    "model": "ag/gemini-3.8-flash-high",
                    "base_url": "http://localhost:20128/v1",
                }
            },
        }

        with patch.dict(os.environ, self.mock_env, clear=True):
            resolved = resolve_task_provider(config, "highlight_finder")
            self.assertEqual(resolved["provider"], "9router")
            self.assertEqual(resolved["model"], "ag/gemini-3.8-flash-high")
            self.assertEqual(resolved["api_key"], "test-9router-key")
            self.assertTrue(resolved["has_key"])
            self.assertIn("chat", resolved["capabilities"])

    def test_fallback_chain_capabilities(self):
        """Verify fallback chain filters providers by capability (e.g. transcription vs chat)."""
        config = {
            "ai_gateway": {
                "enabled": True,
                "preferred_provider": "9router",
                "fallback_enabled": True,
                "fallback_providers": ["9router", "omnirouter", "groq", "openrouter", "openai"],
                "providers": {
                    "9router": {"enabled": True, "base_url": "http://localhost:20128/v1", "capabilities": ["chat", "tts"]},
                    "omnirouter": {"enabled": True, "base_url": "http://localhost:20129/v1", "capabilities": ["chat"]},
                    "groq": {"enabled": True, "base_url": "https://api.groq.com/openai/v1", "capabilities": ["chat", "transcription"]},
                    "openrouter": {"enabled": True, "base_url": "https://openrouter.ai/api/v1", "capabilities": ["chat"]},
                    "openai": {"enabled": True, "base_url": "https://api.openai.com/v1", "capabilities": ["chat", "transcription", "tts"]},
                },
            },
            "ai_providers": {
                "highlight_finder": {"provider": "9router", "model": "ag/gemini-3.8-flash-high"},
                "caption_maker": {"provider": "groq", "model": "whisper-large-v3"},
            },
        }

        # 1. Chat fallback chain for highlight_finder
        chat_chain = get_fallback_chain(config, "highlight_finder", capability="chat")
        provider_ids = [p["provider"] for p in chat_chain]
        self.assertEqual(provider_ids[0], "9router")
        self.assertIn("omnirouter", provider_ids)
        self.assertIn("groq", provider_ids)
        self.assertIn("openrouter", provider_ids)

        # 2. Transcription fallback chain for caption_maker (only groq and openai support transcription)
        stt_chain = get_fallback_chain(config, "caption_maker", capability="transcription")
        stt_ids = [p["provider"] for p in stt_chain]
        self.assertEqual(stt_ids, ["groq", "openai"])
        self.assertNotIn("omnirouter", stt_ids)
        self.assertNotIn("openrouter", stt_ids)

    def test_execute_with_fallback_success_on_secondary(self):
        """Verify that when primary provider fails, execution succeeds on fallback provider."""
        config = {
            "ai_gateway": {
                "enabled": True,
                "preferred_provider": "9router",
                "fallback_enabled": True,
                "fallback_providers": ["9router", "groq"],
                "providers": {
                    "9router": {"enabled": True, "base_url": "http://localhost:20128/v1", "api_key": "k1", "capabilities": ["chat"]},
                    "groq": {"enabled": True, "base_url": "https://api.groq.com/openai/v1", "api_key": "k2", "capabilities": ["chat"]},
                },
            },
            "ai_providers": {
                "highlight_finder": {"provider": "9router", "model": "ag/gemini-3.8-flash-high"},
            },
        }

        call_records = []

        def mock_operation(client, prov_info):
            call_records.append(prov_info["provider"])
            if prov_info["provider"] == "9router":
                raise ConnectionError("Local 9router connection refused")
            return "SUCCESS_FROM_GROQ"

        result = execute_with_fallback(config, "highlight_finder", "chat", mock_operation)

        self.assertEqual(result, "SUCCESS_FROM_GROQ")
        self.assertEqual(call_records, ["9router", "groq"])

    def test_execute_with_fallback_all_fail(self):
        """Verify clean RuntimeError when all providers in fallback chain fail."""
        config = {
            "ai_gateway": {
                "enabled": True,
                "fallback_enabled": True,
                "fallback_providers": ["9router"],
                "providers": {
                    "9router": {"enabled": True, "base_url": "http://localhost:20128/v1", "api_key": "k1", "capabilities": ["chat"]},
                },
            },
            "ai_providers": {
                "highlight_finder": {"provider": "9router", "model": "test"},
            },
        }

        def failing_operation(client, prov_info):
            raise TimeoutError("Endpoint timed out")

        with self.assertRaises(RuntimeError) as ctx:
            execute_with_fallback(config, "highlight_finder", "chat", failing_operation)

        self.assertIn("All AI providers in fallback chain failed", str(ctx.exception))

    def test_probe_and_auto_select_omnirouter_when_9router_fails(self):
        """Verify that when 9router fails (401), probe auto-detects and selects working Omnirouter."""
        config = {
            "ai_gateway": {
                "preferred_provider": "9router",
                "providers": {
                    "9router": {"base_url": "http://localhost:20128/v1", "api_key": "bad-key"},
                    "omnirouter": {"base_url": "http://localhost:20129/v1", "api_key": "good-key"},
                },
            },
            "ai_providers": {
                "highlight_finder": {"provider": "9router", "model": "ag/gemini-3.8-flash-high"}
            }
        }

        with patch("config.ai_router.probe_single_endpoint") as mock_probe:
            # When probing 9router on port 20128 -> returns 401
            # When probing omnirouter on port 20129 -> returns success
            def side_effect(url, key, timeout=3.5):
                if "20128" in url:
                    return {"ok": False, "status": "auth_error", "base_url": url, "api_key": key, "models": [], "error": "401 Unauthorized"}
                if "20129" in url:
                    return {"ok": True, "status": "connected", "base_url": url, "api_key": key, "models": ["ag/gemini-3.8-flash-high", "ag/gemini-2.5-flash"], "error": ""}
                return {"ok": False, "status": "unreachable", "base_url": url, "api_key": key, "models": [], "error": "Connection refused"}

            mock_probe.side_effect = side_effect

            result = auto_detect_and_select_router(config)
            self.assertEqual(result["active_provider"], "omnirouter")
            self.assertTrue(result["working_probe"]["ok"])
            self.assertEqual(result["working_probe"]["base_url"], "http://localhost:20129/v1")

            # Apply to config
            updated = apply_active_router_to_config(config, result["working_probe"])
            self.assertEqual(updated["ai_gateway"]["preferred_provider"], "omnirouter")
            self.assertEqual(updated["ai_providers"]["highlight_finder"]["provider"], "omnirouter")
            self.assertEqual(updated["ai_providers"]["highlight_finder"]["base_url"], "http://localhost:20129/v1")
            self.assertEqual(updated["ai_providers"]["highlight_finder"]["model"], "ag/gemini-3.8-flash-high")


if __name__ == "__main__":
    unittest.main()
