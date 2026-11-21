"""
Configuration manager for YT Short Clipper
"""

import json
import uuid
from pathlib import Path

from config.ai_router import (
    apply_active_router_to_config,
    auto_detect_and_select_router,
    detect_provider_from_url as router_detect_provider_from_url,
    execute_with_fallback as router_execute_with_fallback,
    get_default_gateway_config,
    get_enabled_providers as router_get_enabled_providers,
    get_fallback_chain as router_get_fallback_chain,
    get_provider as router_get_provider,
    load_models as router_load_models,
    migrate_to_gateway_config,
    probe_router,
    resolve_api_key,
    resolve_task_provider as router_resolve_task_provider,
)

# Load .env file
try:
    from dotenv import load_dotenv
    # Load from .env file in app directory
    env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(env_path)
except ImportError:
    pass  # python-dotenv not installed, use os.environ only


def get_api_key_from_env(provider_key: str, config_api_key: str = "") -> str:
    """
    Get API key with priority: config > environment variable.
    Delegates to centralized resolve_api_key.
    """
    return resolve_api_key(provider_key, config_api_key)


def detect_provider_from_url(base_url: str) -> str:
    """Detect provider key from base URL"""
    return router_detect_provider_from_url(base_url)


class ConfigManager:
    """Manages application configuration"""
    
    def __init__(self, config_file: Path, output_dir: Path):
        self.config_file = config_file
        self.output_dir = output_dir
        self.config = self.load()
    
    def load(self):
        """Load configuration from file"""
        if self.config_file.exists():
            with open(self.config_file, "r", encoding="utf-8") as f:
                config = json.load(f)
                
                # Migrate old config to new multi-provider structure
                if "api_key" in config and "ai_providers" not in config:
                    config = self._migrate_to_multi_provider(config)
                
                # Add default system_prompt if not exists
                if "system_prompt" not in config:
                    from clipper_core import AutoClipperCore
                    config["system_prompt"] = AutoClipperCore.get_default_prompt()
                # Add default temperature if not exists
                if "temperature" not in config:
                    config["temperature"] = 1.0
                # Add default tts_model if not exists (for backward compatibility)
                if "tts_model" not in config:
                    config["tts_model"] = "tts-1"
                # Add default watermark settings if not exists
                if "watermark" not in config:
                    config["watermark"] = {
                        "enabled": False,
                        "image_path": "",
                        "position_x": 0.85,  # 0-1 (percentage from left)
                        "position_y": 0.05,  # 0-1 (percentage from top)
                        "opacity": 0.8,      # 0-1
                        "scale": 0.15        # 0-1 (percentage of video width)
                    }
                # Add default face tracking mode if not exists
                if "face_tracking_mode" not in config:
                    config["face_tracking_mode"] = "opencv"  # "opencv" or "mediapipe"
                # Add default MediaPipe settings if not exists
                if "mediapipe_settings" not in config:
                    config["mediapipe_settings"] = {
                        "lip_activity_threshold": 0.15,
                        "switch_threshold": 0.3,
                        "min_shot_duration": 90,
                        "center_weight": 0.3
                    }
                # Generate installation_id if not exists
                if "installation_id" not in config:
                    config["installation_id"] = str(uuid.uuid4())
                    self.save_config(config)
                
                # Ensure ai_providers structure exists
                if "ai_providers" not in config:
                    config["ai_providers"] = self._get_default_ai_providers()
                    self.save_config(config)
                
                # Add default Repliz settings if not exists
                if "repliz" not in config:
                    config["repliz"] = {
                        "access_key": "",
                        "secret_key": ""
                    }
                
                # Add default GPU settings if not exists
                if "gpu_acceleration" not in config:
                    config["gpu_acceleration"] = {
                        "enabled": False
                    }

                # Add default Documentary Studio settings if not exists
                if "documentary" not in config:
                    config["documentary"] = self._get_default_documentary_config()

                # Ensure ai_gateway structure exists and is migrated
                config = migrate_to_gateway_config(config)

                return config
        
        # Default config with system prompt
        from clipper_core import AutoClipperCore
        config = {
            "api_key": "",  # Kept for backward compatibility
            "base_url": "https://api.openai.com/v1",  # Kept for backward compatibility
            "model": "gpt-4.1",  # Kept for backward compatibility
            "tts_model": "tts-1",  # Kept for backward compatibility
            "temperature": 1.0,
            "output_dir": str(self.output_dir),
            "system_prompt": AutoClipperCore.get_default_prompt(),
            "installation_id": str(uuid.uuid4()),
            "ai_providers": self._get_default_ai_providers(),
            "watermark": {
                "enabled": False,
                "image_path": "",
                "position_x": 0.85,
                "position_y": 0.05,
                "opacity": 0.8,
                "scale": 0.15
            },
            "face_tracking_mode": "opencv",
            "mediapipe_settings": {
                "lip_activity_threshold": 0.15,
                "switch_threshold": 0.3,
                "min_shot_duration": 90,
                "center_weight": 0.3
            },
            "repliz": {
                "access_key": "",
                "secret_key": ""
            },
            "gpu_acceleration": {
                "enabled": False
            },
            "documentary": self._get_default_documentary_config(),
            "ai_gateway": get_default_gateway_config()
        }
        self.save_config(config)
        return config
    
    def _get_default_ai_providers(self):
        """Get default AI provider configuration (uses Groq by default - FREE)"""
        return {
            "highlight_finder": {
                "base_url": "https://api.groq.com/openai/v1",
                "api_key": "",  # Will be loaded from GROQ_API_KEY env var
                "model": "llama-3.3-70b-versatile"
            },
            "script_generator": {
                "base_url": "https://api.groq.com/openai/v1",
                "api_key": "",  # Will be loaded from GROQ_API_KEY env var
                "model": "llama-3.3-70b-versatile"
            },
            "caption_maker": {
                "base_url": "https://api.groq.com/openai/v1",
                "api_key": "",  # Will be loaded from GROQ_API_KEY env var
                "model": "whisper-large-v3"
            },
            "hook_maker": {
                "base_url": "https://api.openai.com/v1",
                "api_key": "",  # Will be loaded from OPENAI_API_KEY env var (TTS requires OpenAI)
                "model": "tts-1"
            },
            "youtube_title_maker": {
                "base_url": "https://api.groq.com/openai/v1",
                "api_key": "",  # Will be loaded from GROQ_API_KEY env var
                "model": "llama-3.3-70b-versatile"
            }
        }

    def _get_default_documentary_config(self):
        """Default configuration for Documentary Studio (Feature 07)."""
        return {
            "enabled": True,
            "default_aspect": "16:9",
            "default_duration_seconds": 900,
            "style": "documentary",
            "language": "id",
            "source_mode": "stock_footage",
            "resource_mode": "economy",
            "duration_planner": {
                "enabled": True,
                "min_seconds": 600,
                "max_seconds": 1800,
                "default_seconds": 900,
                "segment_min_seconds": 45,
                "segment_max_seconds": 180,
                "max_segments": 14
            },
            "asset_budget": {
                "max_source_candidates": 12,
                "max_candidates_per_segment": 4,
                "max_downloads_per_run": 12,
                "max_browser_queries_per_run": 8,
                "max_stock_queries_per_segment": 2,
                "max_social_clips_total": 12,
                "max_backbone_sources": 4,
                "max_footage_slots_per_segment": 3,
                "max_queries_per_slot": 1,
                "max_candidates_per_slot": 3,
                "max_stock_downloads_per_run": 40,
                "max_backbone_excerpts": 12,
                "max_archive_assets": 8
            },
            "script_first": {
                "enabled": True,
                "batch_segments_per_call": 4,
                "max_tokens_outline": 8000,
                "fallback_enabled": False
            },
            "footage_density": {
                "economy": {"slots_per_segment_min": 1, "slots_per_segment_max": 2},
                "balanced": {"slots_per_segment_min": 2, "slots_per_segment_max": 3},
                "quality": {"slots_per_segment_min": 3, "slots_per_segment_max": 4}
            },
            "coverage_model": {
                "backbone_ratio": 0.35,
                "broll_ratio": 0.35,
                "archive_ratio": 0.10,
                "stock_ratio": 0.20
            },
            "duration_policy": {
                "allow_below_min": True,
                "warn_below_seconds": 600
            },
            "review_gate": {
                "enabled": True,
                "mode": "slot_review",
                "auto_approve_run_full": False
            },
            "source_policy": {
                "enabled": True,
                "require_user_review": True,
                "store_license_signal": True,
                "backbone_preference": ["foreign_news_documentary", "official_institutions", "open_archive", "wikimedia"],
                "avoid_as_backbone": ["narration_documentary_channels", "local_non_open_channels", "reupload_clipping_channels"],
                "social_media_min_clip_seconds": 5,
                "social_media_max_clip_seconds": 15
            },
            "llm_gateway": {
                "enabled": True,
                "cache_enabled": True,
                "timeout_seconds": 300,
                "probe_timeout_seconds": 200,
                "probe_max_tokens": 16,
                "max_attempts_per_provider": 2,
                "backoff_base_seconds": 2.0,
                "backoff_max_seconds": 8.0,
                "jitter_seconds": 1.0,
                "cooldown_seconds": 200
            },
            "llm_override": {
                "enabled": False,
                "base_url": "",
                "model": "",
                "api_key_env": ""
            },
            "source_discovery": {
                "backend": "auto",
                "browser_timeout_seconds": 60,
                "max_results": 12,
                "platforms": ["pexels", "pixabay"]
            },
            "stock_footage": {
                "enabled": True,
                "providers": {
                    "pexels": {
                        "enabled": True,
                        "api_key_env": "PEXELS_API_KEY",
                        "base_url": "https://api.pexels.com",
                        "timeout_seconds": 30
                    },
                    "pixabay": {
                        "enabled": True,
                        "api_key_env": "PIXABAY_API_KEY",
                        "base_url": "https://pixabay.com/api",
                        "timeout_seconds": 30
                    }
                },
                "search": {
                    "per_segment_candidates": 5,
                    "orientation": "landscape",
                    "safe_search": True,
                    "language": "en",
                    "max_per_provider": 10
                },
                "license": {
                    "require_attribution": True,
                    "store_metadata": True
                }
            },
            "tts_provider": "edge_tts",
            "edge_tts": {
                "voice": "id-ID-ArdiNeural",
                "rate": "+0%",
                "pitch": "+0Hz",
                "volume": "+0%"
            },
            "chatterbox": {
                "enabled": False,
                "endpoint": "http://localhost:5000",
                "voice_id": "default",
                "timeout_seconds": 120
            },
            "subtitle": {
                "enabled": True,
                "mode": "segment",
                "burn_in": True,
                "style": "documentary"
            },
            "bgm": {
                "enabled": False,
                "source": "",
                "volume": 0.15,
                "source_volume": 1.0
            },
            "render": {
                "width": 1920,
                "height": 1080,
                "fps": 30,
                "video_bitrate": "8M",
                "segment_render": True,
                "keep_intermediates": False
            },
            "limits": {
                "max_sources": 8,
                "max_segments": 30,
                "max_source_duration_seconds": 7200
            }
        }

    def _migrate_to_multi_provider(self, old_config):
        """Migrate old single-provider config to new multi-provider structure"""
        api_key = old_config.get("api_key", "")
        base_url = old_config.get("base_url", "https://api.openai.com/v1")
        model = old_config.get("model", "gpt-4.1")
        tts_model = old_config.get("tts_model", "tts-1")
        
        old_config["ai_providers"] = {
            "highlight_finder": {
                "base_url": base_url,
                "api_key": api_key,
                "model": model
            },
            "caption_maker": {
                "base_url": base_url,
                "api_key": api_key,
                "model": "whisper-1"
            },
            "hook_maker": {
                "base_url": base_url,
                "api_key": api_key,
                "model": tts_model
            },
            "youtube_title_maker": {
                "base_url": base_url,
                "api_key": api_key,
                "model": model
            }
        }
        
        return old_config

    def save(self):
        """Save configuration to file"""
        self.save_config(self.config)
    
    def save_config(self, config):
        """Save configuration dict to file"""
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    
    def get(self, key, default=None):
        """Get configuration value"""
        return self.config.get(key, default)
    
    def get_resolved_ai_providers(self):
        """
        Get AI providers config with API keys and models resolved via centralized AI Router.
        Priority: config value > environment variable.
        Preserves complete backward compatibility for all legacy callers.
        """
        ai_providers = self.config.get("ai_providers", self._get_default_ai_providers())
        resolved = {}

        for task_key in ai_providers.keys():
            task_res = router_resolve_task_provider(self.config, task_key)
            resolved[task_key] = {
                "base_url": task_res.get("base_url", ""),
                "api_key": task_res.get("api_key", ""),
                "model": task_res.get("model", ""),
                "system_message": task_res.get("system_message", ""),
                "provider": task_res.get("provider", ""),
                "capabilities": task_res.get("capabilities", ["chat"])
            }

        return resolved

    def get_ai_gateway(self) -> dict:
        """Get the ai_gateway configuration dictionary"""
        if "ai_gateway" not in self.config:
            self.config = migrate_to_gateway_config(self.config)
        return self.config.get("ai_gateway", {})

    def get_provider(self, provider_id: str) -> dict:
        """Get merged provider configuration dictionary"""
        return router_get_provider(self.config, provider_id)

    def get_enabled_providers(self, capability: str = None) -> list:
        """Get list of enabled providers, optionally filtered by capability"""
        return router_get_enabled_providers(self.config, capability=capability)

    def resolve_task_provider(self, task_key: str) -> dict:
        """Resolve provider, model, URL, key, and capabilities for a specific task"""
        return router_resolve_task_provider(self.config, task_key)

    def get_fallback_chain(self, task_key: str, capability: str = "chat") -> list:
        """Get ordered fallback provider chain for a task"""
        return router_get_fallback_chain(self.config, task_key, capability=capability)

    def execute_with_fallback(self, task_key: str, capability: str, operation, logger=None):
        """Execute an operation across the fallback chain for a task"""
        return router_execute_with_fallback(self.config, task_key, capability, operation, logger=logger)

    def load_models_for_provider(self, provider_id: str, timeout_seconds: int = 20) -> list:
        """Load available models for provider from OpenAI-compatible endpoint"""
        models = router_load_models(provider_id, config=self.config, timeout_seconds=timeout_seconds)
        self.save()
        return models

    def probe_router(self, provider_id: str, timeout: float = 3.5) -> dict:
        """Probe a specific router (9router or omnirouter)"""
        return probe_router(provider_id, config=self.config, timeout=timeout)

    def probe_routers(self, timeout: float = 3.5) -> dict:
        """Probe both 9router and Omnirouter to check which one is reachable and functional"""
        return auto_detect_and_select_router(self.config, timeout=timeout)

    def auto_select_working_router(self, timeout: float = 3.5) -> dict:
        """
        Probe 9router and Omnirouter, and automatically apply the working one to config.
        """
        result = auto_detect_and_select_router(self.config, timeout=timeout)
        working_probe = result.get("working_probe")
        if working_probe and working_probe.get("ok"):
            self.config = apply_active_router_to_config(self.config, working_probe)
            self.save()
            result["applied"] = True
        else:
            result["applied"] = False
        return result

    def set(self, key, value):
        """Set configuration value and save"""
        self.config[key] = value
        self.save()
