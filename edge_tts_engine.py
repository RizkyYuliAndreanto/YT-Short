"""
Edge TTS Engine - Free Text-to-Speech with Indonesian Support
Uses Microsoft Edge's online TTS service (100% free, unlimited)
"""

import asyncio
import edge_tts
import os
import re
import json
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass


# Indonesian voices available in Edge TTS
INDONESIAN_VOICES = {
    "id-ID-ArdiNeural": {
        "name": "Ardi",
        "gender": "Male",
        "description": "Suara pria dewasa, cocok untuk narasi dan konten profesional",
        "style": "neutral"
    },
    "id-ID-GadisNeural": {
        "name": "Gadis", 
        "gender": "Female",
        "description": "Suara wanita dewasa, cocok untuk tutorial dan konten friendly",
        "style": "neutral"
    }
}

# Additional voices for multilingual content
MULTILINGUAL_VOICES = {
    "en-US-GuyNeural": {"name": "Guy", "gender": "Male", "lang": "English"},
    "en-US-JennyNeural": {"name": "Jenny", "gender": "Female", "lang": "English"},
}


@dataclass
class TTSSegment:
    """Represents a TTS segment with timing info"""
    text: str
    start_time: float  # seconds
    end_time: float    # seconds
    audio_path: str
    duration: float    # actual audio duration


class EdgeTTSEngine:
    """
    Edge TTS wrapper optimized for video dubbing
    - Supports Indonesian voices
    - Word timing for subtitle sync
    - Speed/pitch control
    - Segment-based generation for video sync
    """
    
    def __init__(self, 
                 voice: str = "id-ID-ArdiNeural",
                 rate: str = "+0%",
                 pitch: str = "+0Hz",
                 volume: str = "+0%"):
        """
        Initialize Edge TTS Engine
        
        Args:
            voice: Voice ID (e.g., "id-ID-ArdiNeural")
            rate: Speed adjustment (e.g., "+10%", "-5%")
            pitch: Pitch adjustment (e.g., "+5Hz", "-10Hz")
            volume: Volume adjustment (e.g., "+20%")
        """
        self.voice = voice
        self.rate = rate
        self.pitch = pitch
        self.volume = volume
        
    @staticmethod
    def get_indonesian_voices() -> Dict:
        """Get list of available Indonesian voices"""
        return INDONESIAN_VOICES
    
    @staticmethod
    def get_all_voices() -> Dict:
        """Get all available voices (Indonesian + multilingual)"""
        return {**INDONESIAN_VOICES, **MULTILINGUAL_VOICES}
    
    @staticmethod
    async def list_voices() -> List[Dict]:
        """List all available voices from Edge TTS"""
        voices = await edge_tts.list_voices()
        return voices
    
    @staticmethod
    async def get_voices_by_language(language_code: str = "id-ID") -> List[Dict]:
        """Get voices filtered by language"""
        voices = await edge_tts.list_voices()
        return [v for v in voices if v["Locale"].startswith(language_code)]
    
    def set_voice(self, voice: str):
        """Change voice"""
        self.voice = voice
        
    def set_rate(self, rate: str):
        """Change rate (e.g., '+10%', '-5%')"""
        self.rate = rate
        
    def set_pitch(self, pitch: str):
        """Change pitch (e.g., '+5Hz', '-10Hz')"""
        self.pitch = pitch
        
    def set_volume(self, volume: str):
        """Change volume (e.g., '+20%')"""
        self.volume = volume
    
    async def generate_audio(self, 
                            text: str, 
                            output_path: str,
                            subtitle_path: Optional[str] = None,
                            max_retries: int = 3) -> Tuple[str, float, Optional[List[Dict]]]:
        """
        Generate audio from text with automatic retry on 503/connection errors.
        
        Args:
            text: Text to convert to speech
            output_path: Path to save audio file (.mp3)
            subtitle_path: Optional path to save subtitle (.srt or .vtt)
            max_retries: Max retry attempts on transient errors
            
        Returns:
            Tuple of (audio_path, duration_seconds, word_timings)
        """
        import time as _time
        
        last_error = None
        
        for attempt in range(1, max_retries + 1):
            try:
                communicate = edge_tts.Communicate(
                    text=text,
                    voice=self.voice,
                    rate=self.rate,
                    pitch=self.pitch,
                    volume=self.volume
                )
                
                word_timings = []
                
                # Generate with word boundaries for subtitle sync
                with open(output_path, "wb") as audio_file:
                    async for chunk in communicate.stream():
                        if chunk["type"] == "audio":
                            audio_file.write(chunk["data"])
                        elif chunk["type"] == "WordBoundary":
                            word_timings.append({
                                "text": chunk["text"],
                                "start": chunk["offset"] / 10000000,  # Convert to seconds
                                "duration": chunk["duration"] / 10000000
                            })
                
                # Calculate total duration
                duration = 0.0
                if word_timings:
                    last_word = word_timings[-1]
                    duration = last_word["start"] + last_word["duration"]
                else:
                    # Fallback: get duration from file
                    duration = self._get_audio_duration(output_path)
                
                # Generate subtitle if requested
                if subtitle_path:
                    self._generate_subtitle(word_timings, subtitle_path)
                
                return output_path, duration, word_timings
                
            except Exception as e:
                last_error = e
                error_str = str(e)
                # Retry on 503, connection reset, WebSocket errors
                is_retryable = any(code in error_str for code in ['503', '429', 'WebSocket', 'ConnectionReset', 'Invalid response', 'wss://'])
                
                if is_retryable and attempt < max_retries:
                    wait = 2 ** attempt  # 2s, 4s, 8s
                    print(f"[EDGE_TTS] ⚠️ Attempt {attempt}/{max_retries} failed ({error_str[:80]}), retrying in {wait}s...")
                    await asyncio.sleep(wait)
                else:
                    raise
        
        raise last_error
    
    async def generate_segments(self,
                               segments: List[Dict],
                               output_dir: str,
                               gap_between: float = 0.3) -> List[TTSSegment]:
        """
        Generate multiple audio segments with timing for video sync
        
        Args:
            segments: List of dicts with 'text', 'target_start', 'target_end' (optional)
            output_dir: Directory to save audio files
            gap_between: Gap between segments in seconds
            
        Returns:
            List of TTSSegment with actual timing
        """
        os.makedirs(output_dir, exist_ok=True)
        
        results = []
        current_time = 0.0
        
        for i, seg in enumerate(segments):
            text = seg.get("text", "")
            if not text.strip():
                continue
                
            output_path = os.path.join(output_dir, f"segment_{i:03d}.mp3")
            
            # Generate audio
            _, duration, timings = await self.generate_audio(text, output_path)
            
            # Calculate timing
            target_start = seg.get("target_start", current_time)
            target_end = seg.get("target_end", target_start + duration)
            
            # If audio is longer than target, we may need to adjust rate
            if duration > (target_end - target_start) and seg.get("fit_to_duration", False):
                # Recalculate with faster rate
                speed_factor = duration / (target_end - target_start)
                adjusted_rate = f"+{int((speed_factor - 1) * 100)}%"
                
                old_rate = self.rate
                self.rate = adjusted_rate
                _, duration, timings = await self.generate_audio(text, output_path)
                self.rate = old_rate
            
            results.append(TTSSegment(
                text=text,
                start_time=target_start,
                end_time=target_start + duration,
                audio_path=output_path,
                duration=duration
            ))
            
            current_time = target_start + duration + gap_between
        
        return results
    
    def _generate_subtitle(self, word_timings: List[Dict], output_path: str):
        """Generate SRT subtitle from word timings"""
        if output_path.endswith(".vtt"):
            self._generate_vtt(word_timings, output_path)
        else:
            self._generate_srt(word_timings, output_path)
    
    def _generate_srt(self, word_timings: List[Dict], output_path: str):
        """Generate SRT format subtitle"""
        # Group words into subtitle chunks (max 8 words or 3 seconds)
        chunks = self._group_words_for_subtitle(word_timings)
        
        with open(output_path, "w", encoding="utf-8") as f:
            for i, chunk in enumerate(chunks, 1):
                start = self._format_srt_time(chunk["start"])
                end = self._format_srt_time(chunk["end"])
                text = chunk["text"]
                f.write(f"{i}\n{start} --> {end}\n{text}\n\n")
    
    def _generate_vtt(self, word_timings: List[Dict], output_path: str):
        """Generate WebVTT format subtitle"""
        chunks = self._group_words_for_subtitle(word_timings)
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("WEBVTT\n\n")
            for i, chunk in enumerate(chunks, 1):
                start = self._format_vtt_time(chunk["start"])
                end = self._format_vtt_time(chunk["end"])
                text = chunk["text"]
                f.write(f"{i}\n{start} --> {end}\n{text}\n\n")
    
    def _group_words_for_subtitle(self, 
                                  word_timings: List[Dict], 
                                  max_words: int = 6,
                                  max_duration: float = 2.5) -> List[Dict]:
        """Group words into subtitle-friendly chunks"""
        chunks = []
        current_chunk = {"words": [], "start": 0, "end": 0}
        
        for word in word_timings:
            if not current_chunk["words"]:
                current_chunk["start"] = word["start"]
            
            current_chunk["words"].append(word["text"])
            current_chunk["end"] = word["start"] + word["duration"]
            
            chunk_duration = current_chunk["end"] - current_chunk["start"]
            
            # Check if should create new chunk
            if (len(current_chunk["words"]) >= max_words or 
                chunk_duration >= max_duration or
                word["text"].endswith((".", "!", "?", ","))):
                
                chunks.append({
                    "text": " ".join(current_chunk["words"]),
                    "start": current_chunk["start"],
                    "end": current_chunk["end"]
                })
                current_chunk = {"words": [], "start": 0, "end": 0}
        
        # Add remaining words
        if current_chunk["words"]:
            chunks.append({
                "text": " ".join(current_chunk["words"]),
                "start": current_chunk["start"],
                "end": current_chunk["end"]
            })
        
        return chunks
    
    @staticmethod
    def _format_srt_time(seconds: float) -> str:
        """Format seconds to SRT time format (HH:MM:SS,mmm)"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
    
    @staticmethod
    def _format_vtt_time(seconds: float) -> str:
        """Format seconds to VTT time format (HH:MM:SS.mmm)"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"
    
    def _get_audio_duration(self, audio_path: str) -> float:
        """Get audio duration using ffprobe"""
        try:
            import subprocess
            from utils.helpers import get_ffmpeg_path
            
            ffmpeg_dir = os.path.dirname(get_ffmpeg_path())
            ffprobe = os.path.join(ffmpeg_dir, "ffprobe.exe") if os.name == "nt" else "ffprobe"
            
            result = subprocess.run([
                ffprobe, "-v", "quiet", "-show_entries", "format=duration",
                "-of", "json", audio_path
            ], capture_output=True, text=True)
            
            data = json.loads(result.stdout)
            return float(data["format"]["duration"])
        except:
            return 0.0


class EdgeTTSManager:
    """
    High-level manager for Edge TTS operations
    Handles configuration and provides sync interface
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize manager with config
        
        Config format:
        {
            "voice": "id-ID-ArdiNeural",
            "rate": "+0%",
            "pitch": "+0Hz",
            "volume": "+0%"
        }
        """
        config = config or {}
        self.engine = EdgeTTSEngine(
            voice=config.get("voice", "id-ID-ArdiNeural"),
            rate=config.get("rate", "+0%"),
            pitch=config.get("pitch", "+0Hz"),
            volume=config.get("volume", "+0%")
        )
    
    def generate_audio_sync(self, 
                           text: str, 
                           output_path: str,
                           subtitle_path: Optional[str] = None) -> Tuple[str, float, Optional[List[Dict]]]:
        """Synchronous wrapper for generate_audio with retry on 503 errors"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Already in an async context — create new loop in thread
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, self.engine.generate_audio(text, output_path, subtitle_path, max_retries=3))
                    return future.result(timeout=60)
            else:
                return loop.run_until_complete(self.engine.generate_audio(text, output_path, subtitle_path, max_retries=3))
        except RuntimeError:
            return asyncio.run(self.engine.generate_audio(text, output_path, subtitle_path, max_retries=3))
    
    def generate_segments_sync(self,
                              segments: List[Dict],
                              output_dir: str,
                              gap_between: float = 0.3) -> List[TTSSegment]:
        """Synchronous wrapper for generate_segments"""
        return asyncio.run(self.engine.generate_segments(segments, output_dir, gap_between))
    
    def update_config(self, config: Dict):
        """Update TTS configuration"""
        if "voice" in config:
            self.engine.set_voice(config["voice"])
        if "rate" in config:
            self.engine.set_rate(config["rate"])
        if "pitch" in config:
            self.engine.set_pitch(config["pitch"])
        if "volume" in config:
            self.engine.set_volume(config["volume"])
    
    @staticmethod
    def get_voice_options() -> List[Dict]:
        """Get voice options for UI dropdown"""
        options = []
        for voice_id, info in INDONESIAN_VOICES.items():
            options.append({
                "id": voice_id,
                "name": f"{info['name']} ({info['gender']})",
                "description": info["description"],
                "language": "Indonesian"
            })
        return options


# Convenience function for quick TTS
def text_to_speech(text: str, 
                  output_path: str,
                  voice: str = "id-ID-ArdiNeural",
                  rate: str = "+0%") -> Tuple[str, float]:
    """
    Quick function to convert text to speech
    
    Args:
        text: Text to convert
        output_path: Output audio file path
        voice: Voice ID
        rate: Speed adjustment
        
    Returns:
        Tuple of (output_path, duration_seconds)
    """
    async def _generate():
        engine = EdgeTTSEngine(voice=voice, rate=rate)
        path, duration, _ = await engine.generate_audio(text, output_path)
        return path, duration
    
    return asyncio.run(_generate())


if __name__ == "__main__":
    # Test the engine
    import asyncio
    
    async def test():
        print("Testing Edge TTS Engine...")
        
        # List Indonesian voices
        voices = await EdgeTTSEngine.get_voices_by_language("id-ID")
        print(f"\nIndonesian voices found: {len(voices)}")
        for v in voices:
            print(f"  - {v['ShortName']}: {v['Gender']}")
        
        # Generate sample audio
        engine = EdgeTTSEngine(voice="id-ID-ArdiNeural", rate="+0%")
        
        test_text = "Halo semuanya! Selamat datang di channel kami. Hari ini kita akan membahas topik yang sangat menarik."
        
        output_path = "_temp/test_tts.mp3"
        subtitle_path = "_temp/test_tts.srt"
        os.makedirs("_temp", exist_ok=True)
        
        path, duration, timings = await engine.generate_audio(
            test_text, output_path, subtitle_path
        )
        
        print(f"\nGenerated audio: {path}")
        print(f"Duration: {duration:.2f} seconds")
        print(f"Word timings: {len(timings)} words")
        
        if timings:
            print("\nFirst 5 word timings:")
            for w in timings[:5]:
                print(f"  '{w['text']}' at {w['start']:.2f}s")
    
    asyncio.run(test())
