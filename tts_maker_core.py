"""
TTS Maker Core - Scalable Text-to-Speech Engine
Supports multiple TTS providers with audio post-processing for natural voice output.

Architecture:
- TTSProvider (Abstract Base Class) - interface for all TTS providers
- EdgeTTSProvider - Edge TTS implementation (Ardi & Gadis)
- Future: XTTSv2Provider, VITSProvider, etc.
- TTSMakerEngine - Main engine with audio enhancement
"""

import os
import sys
import asyncio
import subprocess
import tempfile
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable, Tuple
from enum import Enum

# Windows subprocess flags
SUBPROCESS_FLAGS = 0
if sys.platform == "win32":
    SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW


class TTSProviderType(Enum):
    """Supported TTS Provider Types"""
    EDGE_TTS = "edge_tts"
    XTTS_V2 = "xtts_v2"  # Future
    VITS = "vits"  # Future
    OPENAI_TTS = "openai_tts"  # Future


@dataclass
class VoiceInfo:
    """Voice information"""
    id: str
    name: str
    gender: str
    language: str
    provider: TTSProviderType
    description: str = ""
    sample_rate: int = 22050
    supports_ssml: bool = True
    supports_word_timing: bool = True


@dataclass
class TTSConfig:
    """TTS Configuration"""
    voice_id: str = "id-ID-ArdiNeural"
    rate: float = 0.0  # Speed adjustment: -50% to +50%
    pitch: float = 0.0  # Pitch adjustment: -20Hz to +20Hz
    volume: float = 0.0  # Volume adjustment: -50% to +50%

    # Audio enhancement options
    enable_enhancement: bool = True
    normalize_audio: bool = True
    reduce_noise: bool = False
    add_subtle_variation: bool = False  # DISABLED - compand can be dangerous
    equalize_voice: bool = False  # DISABLED - EQ can cause phase issues

    # Pause/gap control
    reduce_long_pauses: bool = False  # Reduce long silent gaps from punctuation (DISABLED by default for safety)
    max_pause_duration: float = 0.5  # Max pause duration in seconds (0.4-0.8 recommended)
    normalize_punctuation: bool = True  # Pre-process text to normalize punctuation

    # End-of-sentence prosody fix
    fix_abrupt_ending: bool = True  # Fix abrupt cutoff at end of sentences
    add_trailing_silence: float = 0.3  # Add silence padding at end (seconds)
    fade_out_duration: float = 0.15  # Fade out duration for natural release (seconds)


@dataclass
class TTSResult:
    """Result from TTS generation"""
    success: bool
    audio_path: Optional[str] = None
    duration: float = 0.0
    word_timings: Optional[List[Dict]] = None
    subtitle_path: Optional[str] = None
    error: Optional[str] = None
    provider: TTSProviderType = TTSProviderType.EDGE_TTS


# =====================================================================
# Available Indonesian Voices
# =====================================================================

INDONESIAN_VOICES = {
    "id-ID-ArdiNeural": VoiceInfo(
        id="id-ID-ArdiNeural",
        name="Ardi",
        gender="Pria",
        language="Indonesian",
        provider=TTSProviderType.EDGE_TTS,
        description="Suara pria dewasa, cocok untuk narasi dan konten profesional",
    ),
    "id-ID-GadisNeural": VoiceInfo(
        id="id-ID-GadisNeural",
        name="Gadis",
        gender="Wanita",
        language="Indonesian",
        provider=TTSProviderType.EDGE_TTS,
        description="Suara wanita dewasa, cocok untuk tutorial dan konten friendly",
    ),
}

# Multilingual voices for future expansion
MULTILINGUAL_VOICES = {
    "en-US-GuyNeural": VoiceInfo(
        id="en-US-GuyNeural",
        name="Guy",
        gender="Male",
        language="English",
        provider=TTSProviderType.EDGE_TTS,
        description="American English male voice",
    ),
    "en-US-JennyNeural": VoiceInfo(
        id="en-US-JennyNeural",
        name="Jenny",
        gender="Female",
        language="English",
        provider=TTSProviderType.EDGE_TTS,
        description="American English female voice",
    ),
}


def get_all_voices() -> Dict[str, VoiceInfo]:
    """Get all available voices"""
    return {**INDONESIAN_VOICES, **MULTILINGUAL_VOICES}


def get_indonesian_voices() -> Dict[str, VoiceInfo]:
    """Get Indonesian voices only"""
    return INDONESIAN_VOICES


# =====================================================================
# Text Preprocessor - Normalize punctuation for natural TTS
# =====================================================================

class TextPreprocessor:
    """
    Pre-process text to reduce excessive pauses from punctuation.
    Edge TTS tends to add long pauses for certain punctuation patterns.
    Also fixes abrupt ending issues by adding proper sentence termination.
    """

    @staticmethod
    def normalize_for_tts(text: str, config: TTSConfig) -> str:
        """
        Normalize text punctuation to reduce long pauses.

        Issues addressed:
        - Multiple periods (...) cause very long pauses
        - Multiple exclamation/question marks cause long pauses
        - Excessive commas cause choppy speech
        - Newlines can cause unnatural pauses
        """
        if not config.normalize_punctuation:
            return text

        import re

        # Store original for comparison
        result = text

        # 1. Normalize ellipsis (... → single period, or use SSML break)
        # Multiple dots create very long pauses
        result = re.sub(r'\.{3,}', '.', result)  # ... → .
        result = re.sub(r'\.{2}', '.', result)   # .. → .

        # 2. Reduce multiple exclamation/question marks
        result = re.sub(r'!{2,}', '!', result)   # !! → !
        result = re.sub(r'\?{2,}', '?', result)  # ?? → ?
        result = re.sub(r'[!?]{2,}', '?', result)  # !? or ?! → ?

        # 3. Normalize multiple commas or semicolons
        result = re.sub(r',{2,}', ',', result)   # ,, → ,
        result = re.sub(r';{2,}', ';', result)   # ;; → ;

        # 4. Handle newlines - replace with space or single period
        # Multiple newlines often cause long pauses
        result = re.sub(r'\n{2,}', '. ', result)  # Multiple newlines → period + space
        result = re.sub(r'\n', ' ', result)       # Single newline → space

        # 5. Remove excessive spaces
        result = re.sub(r' {2,}', ' ', result)

        # 6. Handle dash patterns that cause pauses
        result = re.sub(r'--+', ',', result)      # -- → comma (softer pause)
        result = re.sub(r'—+', ',', result)       # em dash → comma

        # 7. Clean up space before punctuation
        result = re.sub(r' +([.,!?;:])', r'\1', result)

        # 8. Ensure space after punctuation (for natural flow)
        result = re.sub(r'([.,!?;:])([A-Za-z])', r'\1 \2', result)

        # 9. Fix abrupt ending - ensure proper sentence termination
        if config.fix_abrupt_ending:
            result = TextPreprocessor._fix_sentence_ending(result)

        return result.strip()

    @staticmethod
    def _fix_sentence_ending(text: str) -> str:
        """
        Fix abrupt ending issues by adding proper sentence termination markers.

        Edge TTS cuts off abruptly when there's no clear sentence ending.
        This method ensures proper prosody release at the end.
        """
        text = text.strip()

        if not text:
            return text

        # Check if text already ends with proper punctuation
        final_char = text[-1]

        if final_char in '.!?':
            # Already has ending punctuation - good
            # But we can add a subtle pause marker to help with release
            # Adding a very short "breath" after the sentence helps Edge TTS
            # produce a more natural ending
            pass
        elif final_char in ',;:':
            # Ends with weak punctuation - convert to period for proper closure
            text = text[:-1] + '.'
        else:
            # No punctuation at end - add period for proper sentence ending
            text = text + '.'

        return text

    @staticmethod
    def add_subtle_breaks(text: str) -> str:
        """
        Add SSML-style break hints for Edge TTS.
        This gives more control over pause durations.

        Note: Edge TTS has limited SSML support, so this is optional.
        """
        # For now, we rely on punctuation normalization
        # SSML breaks could be added here if needed
        return text


# =====================================================================
# Abstract TTS Provider
# =====================================================================

class TTSProvider(ABC):
    """Abstract base class for TTS providers"""

    @property
    @abstractmethod
    def provider_type(self) -> TTSProviderType:
        """Return provider type"""
        pass

    @property
    @abstractmethod
    def available_voices(self) -> List[VoiceInfo]:
        """Return list of available voices"""
        pass

    @abstractmethod
    async def generate(
        self,
        text: str,
        output_path: str,
        config: TTSConfig,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> TTSResult:
        """Generate audio from text"""
        pass

    @abstractmethod
    def estimate_duration(self, text: str, rate: float = 0.0) -> float:
        """Estimate audio duration in seconds"""
        pass


# =====================================================================
# Edge TTS Provider
# =====================================================================

class EdgeTTSProvider(TTSProvider):
    """Edge TTS Provider - Free Microsoft Edge TTS"""

    def __init__(self):
        self._voices = list(INDONESIAN_VOICES.values()) + list(MULTILINGUAL_VOICES.values())

    @property
    def provider_type(self) -> TTSProviderType:
        return TTSProviderType.EDGE_TTS

    @property
    def available_voices(self) -> List[VoiceInfo]:
        return self._voices

    def estimate_duration(self, text: str, rate: float = 0.0) -> float:
        """
        Estimate audio duration based on word count and speech rate.

        Base rates (Indonesian):
        - Average speaking rate: ~130-150 words per minute
        - We use 140 WPM as baseline

        Rate adjustment affects duration:
        - +50% rate = faster = shorter duration
        - -50% rate = slower = longer duration
        """
        if not text.strip():
            return 0.0

        words = len(text.split())
        base_wpm = 140  # Words per minute for Indonesian

        # Adjust for rate (-50 to +50)
        rate_multiplier = 1 + (rate / 100)  # e.g., +20% rate = 1.2x speed
        effective_wpm = base_wpm * rate_multiplier

        duration = (words / effective_wpm) * 60  # Convert to seconds

        # Add small buffer for pauses and processing
        duration += 0.5

        return max(1.0, duration)

    async def generate(
        self,
        text: str,
        output_path: str,
        config: TTSConfig,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> TTSResult:
        """Generate audio using Edge TTS"""
        try:
            import edge_tts
        except ImportError:
            return TTSResult(
                success=False,
                error="edge-tts package not installed. Run: pip install edge-tts",
                provider=self.provider_type
            )

        if not text.strip():
            return TTSResult(
                success=False,
                error="Text cannot be empty",
                provider=self.provider_type
            )

        # Pre-process text to normalize punctuation and reduce long pauses
        processed_text = TextPreprocessor.normalize_for_tts(text, config)

        # Format rate/pitch/volume
        rate_str = f"+{int(config.rate)}%" if config.rate >= 0 else f"{int(config.rate)}%"
        pitch_str = f"+{int(config.pitch)}Hz" if config.pitch >= 0 else f"{int(config.pitch)}Hz"
        volume_str = f"+{int(config.volume)}%" if config.volume >= 0 else f"{int(config.volume)}%"

        if progress_callback:
            progress_callback("Initializing TTS engine...")

        max_retries = 3
        last_error = None

        for attempt in range(1, max_retries + 1):
            try:
                communicate = edge_tts.Communicate(
                    text=processed_text,  # Use pre-processed text
                    voice=config.voice_id,
                    rate=rate_str,
                    pitch=pitch_str,
                    volume=volume_str
                )

                word_timings = []

                if progress_callback:
                    progress_callback(f"Generating audio... (attempt {attempt}/{max_retries})")

                # Generate with word boundaries
                with open(output_path, "wb") as audio_file:
                    async for chunk in communicate.stream():
                        if chunk["type"] == "audio":
                            audio_file.write(chunk["data"])
                        elif chunk["type"] == "WordBoundary":
                            word_timings.append({
                                "text": chunk["text"],
                                "start": chunk["offset"] / 10000000,
                                "duration": chunk["duration"] / 10000000
                            })

                # Calculate duration
                duration = 0.0
                if word_timings:
                    last_word = word_timings[-1]
                    duration = last_word["start"] + last_word["duration"]
                else:
                    duration = self._get_audio_duration(output_path)

                if progress_callback:
                    progress_callback("Audio generated successfully!")

                return TTSResult(
                    success=True,
                    audio_path=output_path,
                    duration=duration,
                    word_timings=word_timings,
                    provider=self.provider_type
                )

            except Exception as e:
                last_error = str(e)
                is_retryable = any(code in last_error for code in ['503', '429', 'WebSocket', 'ConnectionReset'])

                if is_retryable and attempt < max_retries:
                    if progress_callback:
                        progress_callback(f"Retry {attempt}/{max_retries}...")
                    await asyncio.sleep(2 ** attempt)
                else:
                    break

        return TTSResult(
            success=False,
            error=last_error,
            provider=self.provider_type
        )

    def _get_audio_duration(self, audio_path: str) -> float:
        """Get audio duration using ffprobe"""
        try:
            from utils.helpers import get_ffmpeg_path
            ffmpeg_dir = os.path.dirname(get_ffmpeg_path())
            ffprobe = os.path.join(ffmpeg_dir, "ffprobe.exe") if os.name == "nt" else "ffprobe"

            result = subprocess.run([
                ffprobe, "-v", "quiet", "-show_entries", "format=duration",
                "-of", "json", audio_path
            ], capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)

            data = json.loads(result.stdout)
            return float(data["format"]["duration"])
        except:
            return 0.0


# =====================================================================
# Future Providers (Stubs for scalability)
# =====================================================================

class XTTSv2Provider(TTSProvider):
    """XTTS v2 Provider - Local AI voice cloning (Future Implementation)"""

    @property
    def provider_type(self) -> TTSProviderType:
        return TTSProviderType.XTTS_V2

    @property
    def available_voices(self) -> List[VoiceInfo]:
        # Would return cloned voices
        return []

    def estimate_duration(self, text: str, rate: float = 0.0) -> float:
        words = len(text.split())
        return (words / 130) * 60

    async def generate(
        self,
        text: str,
        output_path: str,
        config: TTSConfig,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> TTSResult:
        return TTSResult(
            success=False,
            error="XTTSv2 provider not yet implemented. Coming soon!",
            provider=self.provider_type
        )


class VITSProvider(TTSProvider):
    """VITS Provider - Local neural TTS (Future Implementation)"""

    @property
    def provider_type(self) -> TTSProviderType:
        return TTSProviderType.VITS

    @property
    def available_voices(self) -> List[VoiceInfo]:
        return []

    def estimate_duration(self, text: str, rate: float = 0.0) -> float:
        words = len(text.split())
        return (words / 130) * 60

    async def generate(
        self,
        text: str,
        output_path: str,
        config: TTSConfig,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> TTSResult:
        return TTSResult(
            success=False,
            error="VITS provider not yet implemented. Coming soon!",
            provider=self.provider_type
        )


# =====================================================================
# Audio Enhancer - Makes TTS sound more natural
# =====================================================================

class AudioEnhancer:
    """
    Audio post-processor to make TTS output sound more natural.
    Helps avoid detection as automated content.

    Techniques:
    1. Audio normalization - consistent volume levels
    2. Subtle pitch variation - reduces robotic monotone
    3. Voice equalization - enhance clarity
    4. Slight tempo variation - more human-like rhythm
    5. Silence reduction - reduces long pauses from punctuation
    6. Fade-out and trailing silence - fixes abrupt cutoff at end
    """

    def __init__(self, ffmpeg_path: str = "ffmpeg"):
        self.ffmpeg_path = ffmpeg_path

    def _probe_duration(self, audio_path: str) -> float:
        """Get audio duration in seconds for safe tail fade placement."""
        try:
            ffprobe = "ffprobe"
            if self.ffmpeg_path and self.ffmpeg_path != "ffmpeg":
                ffmpeg_dir = os.path.dirname(self.ffmpeg_path)
                candidate = os.path.join(ffmpeg_dir, "ffprobe.exe" if os.name == "nt" else "ffprobe")
                if os.path.exists(candidate):
                    ffprobe = candidate

            result = subprocess.run(
                [
                    ffprobe, "-v", "quiet", "-show_entries", "format=duration",
                    "-of", "json", audio_path
                ],
                capture_output=True,
                text=True,
                creationflags=SUBPROCESS_FLAGS
            )
            data = json.loads(result.stdout or "{}")
            return float(data.get("format", {}).get("duration", 0.0))
        except Exception:
            return 0.0

    def enhance(
        self,
        input_path: str,
        output_path: str,
        config: TTSConfig,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> Tuple[bool, str]:
        """
        Enhance audio to sound more natural.

        Returns:
            Tuple of (success, output_path or error)
        """
        if not config.enable_enhancement:
            # No enhancement needed, but still apply ending fix if enabled
            if config.fix_abrupt_ending:
                return self._apply_ending_fix_only(input_path, output_path, config)
            if input_path != output_path:
                import shutil
                shutil.copy2(input_path, output_path)
            return True, output_path

        if progress_callback:
            progress_callback("Enhancing audio...")

        try:
            filters = []

            # 1. Audio normalization - DO THIS FIRST!
            # Normalize audio level before other processing
            if config.normalize_audio:
                # Use simple volume normalization instead of dynaudnorm
                # volume filter is more predictable and less likely to cause issues
                # Set max volume to 0dB (prevent clipping) and apply simple gain normalization
                filters.append("volume=0dB:precision=float")

            # 2. Reduce long silences/pauses (AFTER normalization)
            # This addresses the main complaint about long pauses from punctuation
            if config.reduce_long_pauses:
                # silenceremove: detect silence and reduce it
                # We only target long pauses in the middle/end, NOT at the start
                # This preserves the natural beginning of the audio
                max_pause = config.max_pause_duration

                # SAFE APPROACH: Only remove silence that's longer than max_pause duration
                # - Don't touch the beginning (no start_periods)
                # - stop_periods=-1: scan entire audio for long pauses
                # - stop_duration: only remove silence longer than this
                # - stop_threshold=-60dB: very conservative (only true silence)
                # - Note: After loudnorm, voice is around -16dB, so -60dB is safe
                filters.append(
                    f"silenceremove=stop_periods=-1:stop_duration={max_pause}:stop_threshold=-60dB"
                )

            # 3. Voice EQ enhancement
            if config.equalize_voice:
                # Boost mid frequencies (voice clarity)
                # Reduce muddy low-mids, enhance presence
                filters.append("equalizer=f=200:t=h:w=100:g=-2")  # Reduce 200Hz
                filters.append("equalizer=f=2500:t=h:w=1000:g=2")  # Boost 2.5kHz
                filters.append("equalizer=f=6000:t=h:w=2000:g=1")  # Slight high boost

            # 4. Subtle variation - asetrate with compand
            if config.add_subtle_variation:
                # Add very subtle dynamics to avoid flat robotic sound
                filters.append("compand=attacks=0.3:decays=0.8:points=-80/-80|-45/-45|-27/-25|0/-10|20/-5:gain=3")

            # 5. Noise reduction (if enabled)
            if config.reduce_noise:
                filters.append("afftdn=nf=-25:nr=10:nt=w")

            # 6. Fix abrupt ending - add fade-out and trailing silence
            # This fixes the "pamali" cutoff issue
            if config.fix_abrupt_ending:
                source_duration = self._probe_duration(input_path)

                # Add trailing silence padding first (before fade)
                # apad adds silence at the end
                trailing_ms = int(config.add_trailing_silence * 1000)
                if trailing_ms > 0:
                    filters.append(f"apad=pad_dur={trailing_ms}ms")

                # Add fade-out at the very end for natural release
                # afade=t=out:d=X applies fade to the last X seconds
                fade_dur = config.fade_out_duration
                if fade_dur > 0:
                    # Force fade to start near EOS, not near t=0.
                    padded_duration = source_duration + max(0.0, config.add_trailing_silence)
                    fade_start = max(0.0, padded_duration - fade_dur)
                    filters.append(f"afade=t=out:st={fade_start:.3f}:d={fade_dur}:curve=tri")

            # Build filter chain
            filter_chain = ",".join(filters) if filters else None

            # Build FFmpeg command
            cmd = [
                self.ffmpeg_path, "-y",
                "-i", input_path,
            ]

            if filter_chain:
                cmd.extend(["-af", filter_chain])

            # High quality output
            cmd.extend([
                "-c:a", "libmp3lame",
                "-q:a", "2",  # High quality VBR
                output_path
            ])

            # DEBUG: Print FFmpeg command for troubleshooting
            print(f"\n[DEBUG] FFmpeg Enhancement Command:")
            print(f"  Filters: {filter_chain if filter_chain else 'None'}")
            print(f"  Command: {' '.join(cmd)}\n")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                creationflags=SUBPROCESS_FLAGS
            )

            if result.returncode != 0:
                error_msg = f"FFmpeg error: {result.stderr[:500]}"
                print(f"[ERROR] {error_msg}")
                return False, error_msg

            if progress_callback:
                progress_callback("Enhancement complete!")

            return True, output_path

        except Exception as e:
            return False, str(e)

    def _apply_ending_fix_only(
        self,
        input_path: str,
        output_path: str,
        config: TTSConfig
    ) -> Tuple[bool, str]:
        """
        Apply only the ending fix (fade-out + trailing silence) without other enhancements.
        Used when enhancement is disabled but fix_abrupt_ending is enabled.
        """
        try:
            filters = []
            source_duration = self._probe_duration(input_path)

            # Add trailing silence padding
            trailing_ms = int(config.add_trailing_silence * 1000)
            if trailing_ms > 0:
                filters.append(f"apad=pad_dur={trailing_ms}ms")

            # Add fade-out
            fade_dur = config.fade_out_duration
            if fade_dur > 0:
                padded_duration = source_duration + max(0.0, config.add_trailing_silence)
                fade_start = max(0.0, padded_duration - fade_dur)
                filters.append(f"afade=t=out:st={fade_start:.3f}:d={fade_dur}:curve=tri")

            if not filters:
                # No filters to apply, just copy
                import shutil
                shutil.copy2(input_path, output_path)
                return True, output_path

            filter_chain = ",".join(filters)

            cmd = [
                self.ffmpeg_path, "-y",
                "-i", input_path,
                "-af", filter_chain,
                "-c:a", "libmp3lame",
                "-q:a", "2",
                output_path
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                creationflags=SUBPROCESS_FLAGS
            )

            if result.returncode != 0:
                return False, f"FFmpeg error: {result.stderr[:200]}"

            return True, output_path

        except Exception as e:
            return False, str(e)


# =====================================================================
# TTS Maker Engine - Main Interface
# =====================================================================

class TTSMakerEngine:
    """
    Main TTS Maker Engine.
    Scalable architecture supporting multiple providers.
    """

    def __init__(
        self,
        provider_type: TTSProviderType = TTSProviderType.EDGE_TTS,
        ffmpeg_path: str = "ffmpeg",
        output_dir: str = "output/tts"
    ):
        self.ffmpeg_path = ffmpeg_path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize provider
        self._providers: Dict[TTSProviderType, TTSProvider] = {
            TTSProviderType.EDGE_TTS: EdgeTTSProvider(),
            TTSProviderType.XTTS_V2: XTTSv2Provider(),
            TTSProviderType.VITS: VITSProvider(),
        }
        self._current_provider = provider_type

        # Audio enhancer
        self.enhancer = AudioEnhancer(ffmpeg_path)

        # Default config
        self.config = TTSConfig()

    @property
    def provider(self) -> TTSProvider:
        return self._providers[self._current_provider]

    def set_provider(self, provider_type: TTSProviderType):
        """Switch TTS provider"""
        self._current_provider = provider_type

    def get_available_providers(self) -> List[TTSProviderType]:
        """Get list of available providers"""
        return list(self._providers.keys())

    def get_voices(self, language: str = "Indonesian") -> List[VoiceInfo]:
        """Get voices filtered by language"""
        voices = self.provider.available_voices
        if language:
            voices = [v for v in voices if v.language.lower() == language.lower()]
        return voices

    def estimate_duration(self, text: str, rate: float = None) -> float:
        """Estimate audio duration"""
        rate = rate if rate is not None else self.config.rate
        return self.provider.estimate_duration(text, rate)

    def get_word_count(self, text: str) -> int:
        """Count words in text"""
        return len(text.split())

    def get_char_count(self, text: str) -> int:
        """Count characters in text"""
        return len(text.strip())

    def generate_sync(
        self,
        text: str,
        config: Optional[TTSConfig] = None,
        output_filename: Optional[str] = None,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> TTSResult:
        """Synchronous wrapper for generate"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(
                        asyncio.run,
                        self.generate(text, config, output_filename, progress_callback)
                    )
                    return future.result(timeout=120)
            else:
                return loop.run_until_complete(
                    self.generate(text, config, output_filename, progress_callback)
                )
        except RuntimeError:
            return asyncio.run(
                self.generate(text, config, output_filename, progress_callback)
            )

    async def generate(
        self,
        text: str,
        config: Optional[TTSConfig] = None,
        output_filename: Optional[str] = None,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> TTSResult:
        """
        Generate TTS audio with optional enhancement.

        Args:
            text: Text to convert to speech
            config: TTS configuration (uses default if None)
            output_filename: Custom filename (auto-generated if None)
            progress_callback: Progress callback function

        Returns:
            TTSResult with audio path and metadata
        """
        config = config or self.config

        if not text.strip():
            return TTSResult(
                success=False,
                error="Text cannot be empty"
            )

        # Generate output filename
        if not output_filename:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"tts_{timestamp}.mp3"

        # Paths
        raw_path = self.output_dir / f"_raw_{output_filename}"
        final_path = self.output_dir / output_filename

        # Step 1: Generate raw TTS
        if progress_callback:
            progress_callback("Generating TTS...")

        result = await self.provider.generate(
            text=text,
            output_path=str(raw_path),
            config=config,
            progress_callback=progress_callback
        )

        if not result.success:
            return result

        # Step 2: Enhance audio
        if config.enable_enhancement:
            if progress_callback:
                progress_callback("Enhancing audio quality...")

            success, enhanced = self.enhancer.enhance(
                input_path=str(raw_path),
                output_path=str(final_path),
                config=config,
                progress_callback=progress_callback
            )

            if success:
                result.audio_path = enhanced
                # Clean up raw file
                try:
                    os.remove(raw_path)
                except:
                    pass
            else:
                # Enhancement failed, use raw
                result.audio_path = str(raw_path)
                import shutil
                shutil.move(str(raw_path), str(final_path))
                result.audio_path = str(final_path)
        else:
            # No enhancement
            import shutil
            shutil.move(str(raw_path), str(final_path))
            result.audio_path = str(final_path)

        # Update duration from enhanced file
        if result.success:
            result.duration = self._get_audio_duration(result.audio_path)

        if progress_callback:
            progress_callback("Complete!")

        return result

    async def generate_subtitle(
        self,
        word_timings: List[Dict],
        output_path: str,
        format: str = "srt"
    ) -> bool:
        """Generate subtitle file from word timings"""
        try:
            chunks = self._group_words_for_subtitle(word_timings)

            with open(output_path, "w", encoding="utf-8") as f:
                if format == "vtt":
                    f.write("WEBVTT\n\n")

                for i, chunk in enumerate(chunks, 1):
                    start = self._format_time(chunk["start"], format)
                    end = self._format_time(chunk["end"], format)
                    text = chunk["text"]

                    f.write(f"{i}\n{start} --> {end}\n{text}\n\n")

            return True
        except Exception:
            return False

    def _group_words_for_subtitle(
        self,
        word_timings: List[Dict],
        max_words: int = 6,
        max_duration: float = 2.5
    ) -> List[Dict]:
        """Group words into subtitle chunks"""
        chunks = []
        current_chunk = {"words": [], "start": 0, "end": 0}

        for word in word_timings:
            if not current_chunk["words"]:
                current_chunk["start"] = word["start"]

            current_chunk["words"].append(word["text"])
            current_chunk["end"] = word["start"] + word["duration"]

            chunk_duration = current_chunk["end"] - current_chunk["start"]

            if (len(current_chunk["words"]) >= max_words or
                chunk_duration >= max_duration or
                word["text"].endswith((".", "!", "?", ","))):

                chunks.append({
                    "text": " ".join(current_chunk["words"]),
                    "start": current_chunk["start"],
                    "end": current_chunk["end"]
                })
                current_chunk = {"words": [], "start": 0, "end": 0}

        if current_chunk["words"]:
            chunks.append({
                "text": " ".join(current_chunk["words"]),
                "start": current_chunk["start"],
                "end": current_chunk["end"]
            })

        return chunks

    def _format_time(self, seconds: float, format: str) -> str:
        """Format seconds to subtitle time"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)

        if format == "vtt":
            return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"
        else:  # srt
            return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def _get_audio_duration(self, audio_path: str) -> float:
        """Get audio duration using ffprobe"""
        try:
            from utils.helpers import get_ffmpeg_path
            ffmpeg_dir = os.path.dirname(get_ffmpeg_path())
            ffprobe = os.path.join(ffmpeg_dir, "ffprobe.exe") if os.name == "nt" else "ffprobe"

            result = subprocess.run([
                ffprobe, "-v", "quiet", "-show_entries", "format=duration",
                "-of", "json", audio_path
            ], capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)

            data = json.loads(result.stdout)
            return float(data["format"]["duration"])
        except:
            return 0.0


# =====================================================================
# Convenience Functions
# =====================================================================

def quick_tts(
    text: str,
    voice: str = "id-ID-ArdiNeural",
    rate: float = 0.0,
    output_path: Optional[str] = None
) -> TTSResult:
    """
    Quick function to generate TTS audio.

    Args:
        text: Text to convert
        voice: Voice ID
        rate: Speed adjustment (-50 to +50)
        output_path: Output file path

    Returns:
        TTSResult
    """
    engine = TTSMakerEngine()
    config = TTSConfig(voice_id=voice, rate=rate)

    if output_path:
        filename = os.path.basename(output_path)
        engine.output_dir = Path(os.path.dirname(output_path))
    else:
        filename = None

    return engine.generate_sync(text, config, filename)


def estimate_audio_duration(text: str, rate: float = 0.0) -> float:
    """
    Estimate audio duration for given text.

    Args:
        text: Input text
        rate: Speed adjustment (-50 to +50)

    Returns:
        Estimated duration in seconds
    """
    engine = TTSMakerEngine()
    return engine.estimate_duration(text, rate)


def get_voice_list() -> List[Dict]:
    """Get list of available voices for UI"""
    voices = []
    for voice_id, info in get_all_voices().items():
        voices.append({
            "id": voice_id,
            "name": info.name,
            "label": f"{info.name} ({info.gender})",
            "gender": info.gender,
            "language": info.language,
            "description": info.description,
            "provider": info.provider.value
        })
    return voices


# =====================================================================
# Test
# =====================================================================

if __name__ == "__main__":
    async def test():
        print("Testing TTS Maker Engine...")
        print("=" * 50)

        engine = TTSMakerEngine(output_dir="_temp/tts_test")

        # List voices
        print("\nAvailable Indonesian voices:")
        for voice in engine.get_voices("Indonesian"):
            print(f"  - {voice.name} ({voice.gender}): {voice.description}")

        # Test text
        test_text = """
        Halo semuanya! Selamat datang di channel kami.
        Hari ini kita akan membahas topik yang sangat menarik.
        Jangan lupa subscribe dan like video ini!
        """

        # Estimate duration
        estimated = engine.estimate_duration(test_text)
        print(f"\nTest text ({engine.get_word_count(test_text)} words)")
        print(f"Estimated duration: {estimated:.1f}s")

        # Generate with enhancement
        config = TTSConfig(
            voice_id="id-ID-ArdiNeural",
            rate=0,
            pitch=0,
            enable_enhancement=True,
            normalize_audio=True,
            add_subtle_variation=True,
        )

        def progress(msg):
            print(f"  [{msg}]")

        print("\nGenerating audio...")
        result = await engine.generate(test_text, config, progress_callback=progress)

        if result.success:
            print(f"\nSuccess!")
            print(f"Audio: {result.audio_path}")
            print(f"Duration: {result.duration:.2f}s")
        else:
            print(f"\nError: {result.error}")

    asyncio.run(test())
