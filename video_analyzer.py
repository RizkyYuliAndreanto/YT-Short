"""
Video Analyzer - Extract audio and analyze video content using AI
Uses GROQ Whisper for transcription (free) with fallback options
"""

import os
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass
from datetime import timedelta

from utils.helpers import get_ffmpeg_path
from config.config_manager import get_api_key_from_env, detect_provider_from_url


@dataclass
class VideoInfo:
    """Video metadata"""
    path: str
    duration: float  # seconds
    width: int
    height: int
    fps: float
    has_audio: bool
    audio_duration: float
    format: str


@dataclass
class TranscriptSegment:
    """A segment of transcribed text with timing"""
    text: str
    start: float  # seconds
    end: float    # seconds
    words: Optional[List[Dict]] = None  # word-level timing if available


@dataclass
class VideoAnalysis:
    """Complete video analysis result"""
    video_info: VideoInfo
    transcript: List[TranscriptSegment]
    full_text: str
    context: str  # AI-detected context/topic
    suggested_script: str  # AI-generated voiceover script
    language: str
    keywords: List[str]


class VideoAnalyzer:
    """
    Analyzes video content:
    1. Extract video metadata
    2. Extract audio
    3. Transcribe audio (GROQ Whisper / local fallback)
    4. Analyze context and generate script
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize analyzer
        
        Config:
        {
            "ai_providers": {
                "caption_maker": {"base_url": "...", "api_key": "...", "model": "..."},
                "script_generator": {"base_url": "...", "api_key": "...", "model": "..."}
            },
            "stt_provider": {
                "type": "api",  # "api" or "local"
                "model": "whisper-large-v3"  # for GROQ
            }
        }
        """
        self.config = config or {}
        self.ffmpeg_path = get_ffmpeg_path()
        self.ffprobe_path = self._get_ffprobe_path()
        
    def _get_ffprobe_path(self) -> str:
        """Get ffprobe path"""
        ffmpeg_dir = os.path.dirname(self.ffmpeg_path)
        if os.name == "nt":
            return os.path.join(ffmpeg_dir, "ffprobe.exe")
        return "ffprobe"
    
    def get_video_info(self, video_path: str) -> VideoInfo:
        """Extract video metadata using ffprobe"""
        cmd = [
            self.ffprobe_path,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            video_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(result.stdout)
        
        # Find video stream
        video_stream = None
        audio_stream = None
        for stream in data.get("streams", []):
            if stream["codec_type"] == "video" and not video_stream:
                video_stream = stream
            elif stream["codec_type"] == "audio" and not audio_stream:
                audio_stream = stream
        
        format_info = data.get("format", {})
        
        # Parse video info
        width = int(video_stream.get("width", 0)) if video_stream else 0
        height = int(video_stream.get("height", 0)) if video_stream else 0
        
        # Parse FPS
        fps = 30.0
        if video_stream:
            fps_str = video_stream.get("r_frame_rate", "30/1")
            if "/" in fps_str:
                num, den = fps_str.split("/")
                fps = float(num) / float(den) if float(den) > 0 else 30.0
        
        duration = float(format_info.get("duration", 0))
        audio_duration = float(audio_stream.get("duration", 0)) if audio_stream else 0
        
        return VideoInfo(
            path=video_path,
            duration=duration,
            width=width,
            height=height,
            fps=fps,
            has_audio=audio_stream is not None,
            audio_duration=audio_duration,
            format=format_info.get("format_name", "unknown")
        )
    
    def extract_audio(self, video_path: str, output_path: Optional[str] = None) -> str:
        """Extract audio from video as WAV/MP3"""
        if not output_path:
            output_dir = os.path.dirname(video_path)
            base_name = os.path.splitext(os.path.basename(video_path))[0]
            output_path = os.path.join(output_dir, f"{base_name}_audio.mp3")
        
        cmd = [
            self.ffmpeg_path,
            "-i", video_path,
            "-vn",  # No video
            "-acodec", "libmp3lame",
            "-ar", "16000",  # 16kHz for Whisper
            "-ac", "1",  # Mono
            "-y",  # Overwrite
            output_path
        ]
        
        subprocess.run(cmd, capture_output=True)
        return output_path
    
    def transcribe_audio(self, 
                        audio_path: str,
                        language: str = "id",
                        progress_callback: Optional[Callable] = None) -> Tuple[List[TranscriptSegment], str]:
        """
        Transcribe audio using AI
        
        Args:
            audio_path: Path to audio file
            language: Language code (id, en, etc.)
            progress_callback: Optional callback for progress updates
            
        Returns:
            Tuple of (segments, full_text)
        """
        stt_config = self.config.get("stt_provider", {"type": "api"})
        
        if stt_config.get("type") == "local":
            return self._transcribe_local(audio_path, language, progress_callback)
        else:
            return self._transcribe_api(audio_path, language, progress_callback)
    
    def _transcribe_api(self,
                       audio_path: str,
                       language: str,
                       progress_callback: Optional[Callable] = None) -> Tuple[List[TranscriptSegment], str]:
        """Transcribe using GROQ Whisper API"""
        from openai import OpenAI
        
        # Get caption_maker config (uses Whisper)
        ai_providers = self.config.get("ai_providers", {})
        caption_config = ai_providers.get("caption_maker", {})
        
        base_url = caption_config.get("base_url", "https://api.groq.com/openai/v1")
        config_key = caption_config.get("api_key", "")
        model = caption_config.get("model", "whisper-large-v3")
        
        # Get API key from env if not in config
        provider = detect_provider_from_url(base_url)
        api_key = get_api_key_from_env(provider, config_key)
        
        if not api_key:
            raise ValueError(f"No API key found for {provider}")
        
        if progress_callback:
            progress_callback("Connecting to transcription API...")
        
        client = OpenAI(api_key=api_key, base_url=base_url)
        
        # Transcribe
        if progress_callback:
            progress_callback("Transcribing audio...")
        
        with open(audio_path, "rb") as audio_file:
            # Try verbose JSON for word-level timestamps
            try:
                # Build params — omit language if None to let Whisper auto-detect
                transcribe_params = {
                    "model": model,
                    "file": audio_file,
                    "response_format": "verbose_json",
                    "timestamp_granularities": ["word", "segment"]
                }
                if language:
                    transcribe_params["language"] = language
                
                response = client.audio.transcriptions.create(**transcribe_params)
                
                segments = []
                for seg in response.segments:
                    words = None
                    if hasattr(response, 'words') and response.words:
                        # Filter words for this segment
                        words = [
                            {"text": w.word, "start": w.start, "end": w.end}
                            for w in response.words
                            if w.start >= seg.start and w.end <= seg.end
                        ]
                    
                    segments.append(TranscriptSegment(
                        text=seg.text.strip(),
                        start=seg.start,
                        end=seg.end,
                        words=words
                    ))
                
                return segments, response.text
                
            except Exception as e:
                # Fallback to simple transcription
                audio_file.seek(0)
                fallback_params = {"model": model, "file": audio_file}
                if language:
                    fallback_params["language"] = language
                response = client.audio.transcriptions.create(**fallback_params)
                
                # Create single segment
                segments = [TranscriptSegment(
                    text=response.text.strip() if hasattr(response, 'text') else str(response),
                    start=0,
                    end=0
                )]
                
                full_text = response.text if hasattr(response, 'text') else str(response)
                return segments, full_text
    
    def _transcribe_local(self,
                         audio_path: str,
                         language: str,
                         progress_callback: Optional[Callable] = None) -> Tuple[List[TranscriptSegment], str]:
        """Transcribe using local Faster-Whisper (fallback)"""
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ImportError("faster-whisper not installed. Run: pip install faster-whisper")
        
        if progress_callback:
            progress_callback("Loading local Whisper model...")
        
        # Use tiny or base model for low RAM
        model_size = self.config.get("stt_provider", {}).get("model", "base")
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        
        if progress_callback:
            progress_callback("Transcribing locally...")
        
        segments_gen, info = model.transcribe(
            audio_path,
            language=language,
            beam_size=5,
            word_timestamps=True
        )
        
        segments = []
        full_text_parts = []
        
        for seg in segments_gen:
            words = []
            if seg.words:
                words = [
                    {"text": w.word, "start": w.start, "end": w.end}
                    for w in seg.words
                ]
            
            segments.append(TranscriptSegment(
                text=seg.text.strip(),
                start=seg.start,
                end=seg.end,
                words=words if words else None
            ))
            full_text_parts.append(seg.text.strip())
        
        return segments, " ".join(full_text_parts)
    
    def analyze_context(self,
                       transcript: str,
                       video_info: VideoInfo,
                       progress_callback: Optional[Callable] = None) -> Dict:
        """
        Analyze video context and generate script using AI
        
        Returns:
        {
            "context": "Penjelasan konteks video",
            "keywords": ["keyword1", "keyword2"],
            "suggested_script": "Script voiceover yang natural",
            "tone": "educational/entertaining/selling"
        }
        """
        from openai import OpenAI
        
        # Get script_generator config (or use highlight_finder as fallback)
        ai_providers = self.config.get("ai_providers", {})
        llm_config = ai_providers.get("script_generator", ai_providers.get("highlight_finder", {}))
        
        base_url = llm_config.get("base_url", "https://api.groq.com/openai/v1")
        config_key = llm_config.get("api_key", "")
        model = llm_config.get("model", "llama-3.3-70b-versatile")
        
        provider = detect_provider_from_url(base_url)
        api_key = get_api_key_from_env(provider, config_key)
        
        if not api_key:
            raise ValueError(f"No API key found for {provider}")
        
        if progress_callback:
            progress_callback("Analyzing video context...")
        
        client = OpenAI(api_key=api_key, base_url=base_url)
        
        # Determine video type from duration
        video_type = "short" if video_info.duration < 120 else "long"
        
        prompt = f"""Analisis transcript video berikut dan buatkan script voiceover dalam Bahasa Indonesia.

VIDEO INFO:
- Durasi: {video_info.duration:.1f} detik ({video_type} video)
- Resolusi: {video_info.width}x{video_info.height}

TRANSCRIPT:
{transcript[:4000]}

TUGAS:
1. Identifikasi konteks/topik utama video
2. Ekstrak 3-5 keyword penting
3. Buatkan script voiceover yang:
   - Natural dan engaging
   - Sesuai durasi video ({video_info.duration:.0f} detik)
   - Tidak terlalu cepat (target 130-150 kata per menit)
   - Menggunakan Bahasa Indonesia yang baik

FORMAT OUTPUT (JSON):
{{
    "context": "Penjelasan singkat konteks video (1-2 kalimat)",
    "keywords": ["keyword1", "keyword2", "keyword3"],
    "tone": "educational/entertaining/selling/informative",
    "suggested_script": "Script voiceover lengkap di sini...",
    "estimated_duration_seconds": 60
}}

PENTING: Output HANYA JSON, tanpa markdown atau penjelasan lain."""

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Kamu adalah script writer profesional untuk konten video berbahasa Indonesia. Output selalu dalam format JSON yang valid."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=2000
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # Parse JSON
        try:
            # Clean up potential markdown
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
            result_text = result_text.strip()
            
            return json.loads(result_text)
        except json.JSONDecodeError:
            # Fallback structure
            return {
                "context": "Tidak dapat menganalisis konteks",
                "keywords": [],
                "tone": "informative",
                "suggested_script": transcript,
                "estimated_duration_seconds": video_info.duration
            }
    
    def analyze_video(self,
                     video_path: str,
                     language: str = "id",
                     progress_callback: Optional[Callable] = None) -> VideoAnalysis:
        """
        Complete video analysis pipeline
        
        Args:
            video_path: Path to video file
            language: Language code
            progress_callback: Optional callback for progress
            
        Returns:
            VideoAnalysis object with all results
        """
        # 1. Get video info
        if progress_callback:
            progress_callback("Analyzing video metadata...")
        video_info = self.get_video_info(video_path)
        
        # 2. Extract audio
        if progress_callback:
            progress_callback("Extracting audio...")
        
        temp_dir = tempfile.mkdtemp()
        audio_path = os.path.join(temp_dir, "audio.mp3")
        self.extract_audio(video_path, audio_path)
        
        # 3. Transcribe
        if progress_callback:
            progress_callback("Transcribing audio...")
        
        transcript_segments, full_text = self.transcribe_audio(
            audio_path, language, progress_callback
        )
        
        # 4. Analyze context
        if progress_callback:
            progress_callback("Analyzing context and generating script...")
        
        analysis = self.analyze_context(full_text, video_info, progress_callback)
        
        # Cleanup temp audio
        try:
            os.remove(audio_path)
            os.rmdir(temp_dir)
        except:
            pass
        
        return VideoAnalysis(
            video_info=video_info,
            transcript=transcript_segments,
            full_text=full_text,
            context=analysis.get("context", ""),
            suggested_script=analysis.get("suggested_script", full_text),
            language=language,
            keywords=analysis.get("keywords", [])
        )


def analyze_video_quick(video_path: str, config: Dict) -> VideoAnalysis:
    """Quick function to analyze a video"""
    analyzer = VideoAnalyzer(config)
    return analyzer.analyze_video(video_path)


if __name__ == "__main__":
    # Test
    print("Video Analyzer Test")
    print("=" * 50)
    
    # Test with a sample video
    test_video = "_temp/test_video.mp4"
    
    if os.path.exists(test_video):
        analyzer = VideoAnalyzer()
        info = analyzer.get_video_info(test_video)
        print(f"Video: {info.path}")
        print(f"Duration: {info.duration:.2f}s")
        print(f"Resolution: {info.width}x{info.height}")
        print(f"Has audio: {info.has_audio}")
    else:
        print(f"Test video not found: {test_video}")
        print("Create a test video to run full analysis")
