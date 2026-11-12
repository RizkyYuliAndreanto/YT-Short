"""
Configuration manager for YT Short Clipper
"""

import json
import os
import uuid
from pathlib import Path

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
    Get API key with priority: config > environment variable
    
    Environment variable mapping:
    - groq -> GROQ_API_KEY
    - openrouter -> OPENROUTER_API_KEY  
    - openai -> OPENAI_API_KEY
    - google -> GOOGLE_API_KEY
    - anthropic -> ANTHROPIC_API_KEY
    """
    # If config has a real API key (not placeholder), use it
    if config_api_key and not config_api_key.startswith("MASUKKAN_") and not config_api_key.startswith("KOSONGKAN_"):
        return config_api_key
    
    # Otherwise, try environment variable
    env_mapping = {
        "9router": "NINE_ROUTER_API_KEY",
        "groq": "GROQ_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "openai": "OPENAI_API_KEY",
        "google": "GOOGLE_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "ytclip": "YTCLIP_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "together": "TOGETHER_API_KEY",
        "cohere": "COHERE_API_KEY",
    }

    env_var = env_mapping.get(provider_key, "")
    if env_var:
        val = os.environ.get(env_var)
        if val:
            return val

    if provider_key == "9router":
        val = os.environ.get("ROUTER_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        if val:
            return val

    return config_api_key


def detect_provider_from_url(base_url: str) -> str:
    """Detect provider key from base URL"""
    url_mapping = {
        ":20128": "9router",
        "9router": "9router",
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
    
    for url_part, provider in url_mapping.items():
        if url_part in base_url:
            return provider
    
    return "custom"


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
            "documentary": self._get_default_documentary_config()
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
            "default_duration_seconds": 300,
            "style": "documentary",
            "language": "id",
            "source_mode": "mixed",
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
        Get AI providers config with API keys resolved from environment variables.
        Priority: config value > environment variable
        """
        ai_providers = self.config.get("ai_providers", self._get_default_ai_providers())
        resolved = {}
        
        for task_key, provider_config in ai_providers.items():
            base_url = provider_config.get("base_url", "")
            config_api_key = provider_config.get("api_key", "")
            
            # Detect provider from URL and resolve API key
            provider_key = detect_provider_from_url(base_url)
            resolved_api_key = get_api_key_from_env(provider_key, config_api_key)
            
            resolved[task_key] = {
                "base_url": base_url,
                "api_key": resolved_api_key,
                "model": provider_config.get("model", ""),
                "system_message": provider_config.get("system_message", "")
            }
        
        return resolved
    
    def set(self, key, value):
        """Set configuration value and save"""
        self.config[key] = value
        self.save()
