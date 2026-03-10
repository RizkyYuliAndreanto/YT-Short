"""
Script Generator - AI-powered script generation for video dubbing
Supports multiple content types: dubbing, shopping, narration
Uses GROQ/OpenRouter/OpenAI with fallback
"""

import json
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from enum import Enum

from config.config_manager import get_api_key_from_env, detect_provider_from_url


class ContentType(Enum):
    """Types of content for script generation"""
    DUBBING = "dubbing"           # Voiceover for existing video
    NARRATION = "narration"       # Educational/informative narration
    SHOPPING = "shopping"         # Product selling script
    ENTERTAINMENT = "entertainment"  # Fun/viral content
    TUTORIAL = "tutorial"         # How-to guide


@dataclass
class ScriptSegment:
    """A segment of the script with timing hints"""
    text: str
    target_start: float  # Target start time in video (seconds)
    target_end: float    # Target end time
    emphasis: Optional[str] = None  # Words to emphasize
    tone: Optional[str] = None  # Tone hint (excited, calm, urgent)


@dataclass 
class GeneratedScript:
    """Complete generated script"""
    full_script: str
    segments: List[ScriptSegment]
    word_count: int
    estimated_duration: float  # seconds
    content_type: ContentType
    metadata: Dict


# Prompt templates for different content types
SCRIPT_PROMPTS = {
    ContentType.DUBBING: """Kamu adalah script writer profesional untuk dubbing video Bahasa Indonesia.

KONTEKS VIDEO:
{context}

DURASI VIDEO: {duration:.0f} detik

TRANSCRIPT ASLI (jika ada):
{transcript}

TUGAS:
Buatkan script voiceover dalam Bahasa Indonesia yang:
1. Natural dan engaging
2. Sesuai dengan durasi video
3. Pace yang nyaman (130-150 kata per menit)
4. Tidak ada jeda panjang antar kalimat
5. Mengalir smooth tanpa repetisi

FORMAT OUTPUT (JSON):
{{
    "full_script": "Script lengkap di sini...",
    "segments": [
        {{"text": "Kalimat pertama...", "target_start": 0, "target_end": 5, "tone": "engaging"}},
        {{"text": "Kalimat kedua...", "target_start": 5, "target_end": 10, "tone": "informative"}}
    ],
    "word_count": 150,
    "estimated_duration": 60
}}

OUTPUT HANYA JSON VALID.""",

    ContentType.SHOPPING: """Kamu adalah copywriter profesional untuk konten jualan/shopping video.

PRODUK/KONTEKS:
{context}

DURASI VIDEO: {duration:.0f} detik

INFO TAMBAHAN:
{transcript}

TUGAS:
Buatkan script jualan dalam Bahasa Indonesia yang:
1. Hook yang kuat di awal (3 detik pertama)
2. Highlight benefit produk
3. Urgency dan scarcity
4. CTA yang jelas
5. Tone: antusias tapi tidak lebay

STRUKTUR:
- Hook (0-3 detik): Attention grabber
- Problem (3-8 detik): Pain point
- Solution (8-20 detik): Produk sebagai solusi
- Benefits (20-35 detik): Keunggulan
- Social Proof (35-45 detik): Testimoni singkat
- CTA (45-{duration:.0f} detik): Call to action

FORMAT OUTPUT (JSON):
{{
    "full_script": "Script lengkap...",
    "segments": [
        {{"text": "Hook kuat!", "target_start": 0, "target_end": 3, "tone": "excited"}},
        {{"text": "Masalahnya adalah...", "target_start": 3, "target_end": 8, "tone": "empathetic"}}
    ],
    "word_count": 180,
    "estimated_duration": {duration:.0f},
    "cta_text": "Link di bio!",
    "hashtags": ["#PromoHariIni", "#DiskonBesar"]
}}

OUTPUT HANYA JSON VALID.""",

    ContentType.NARRATION: """Kamu adalah narrator profesional untuk konten edukatif Bahasa Indonesia.

TOPIK:
{context}

DURASI VIDEO: {duration:.0f} detik

MATERI:
{transcript}

TUGAS:
Buatkan script narasi edukatif yang:
1. Pembukaan yang menarik
2. Penjelasan yang jelas dan terstruktur
3. Contoh atau analogi yang relatable
4. Kesimpulan yang memorable
5. Tone: authoritative tapi friendly

FORMAT OUTPUT (JSON):
{{
    "full_script": "Script narasi lengkap...",
    "segments": [
        {{"text": "Intro menarik...", "target_start": 0, "target_end": 8, "tone": "engaging"}},
        {{"text": "Penjelasan utama...", "target_start": 8, "target_end": 40, "tone": "informative"}}
    ],
    "word_count": 200,
    "estimated_duration": {duration:.0f},
    "key_points": ["Point 1", "Point 2", "Point 3"]
}}

OUTPUT HANYA JSON VALID.""",

    ContentType.ENTERTAINMENT: """Kamu adalah content creator untuk konten viral/hiburan Bahasa Indonesia.

KONTEKS:
{context}

DURASI VIDEO: {duration:.0f} detik

REFERENSI:
{transcript}

TUGAS:
Buatkan script yang entertaining:
1. Hook yang bikin penasaran
2. Storytelling yang engaging
3. Twist atau punchline
4. Relatable untuk audience
5. Tone: playful dan energetic

FORMAT OUTPUT (JSON):
{{
    "full_script": "Script lengkap...",
    "segments": [
        {{"text": "Hook penasaran...", "target_start": 0, "target_end": 3, "tone": "mysterious"}},
        {{"text": "Build up...", "target_start": 3, "target_end": 20, "tone": "building"}}
    ],
    "word_count": 150,
    "estimated_duration": {duration:.0f}
}}

OUTPUT HANYA JSON VALID.""",

    ContentType.TUTORIAL: """Kamu adalah instruktur untuk tutorial video Bahasa Indonesia.

TOPIK TUTORIAL:
{context}

DURASI VIDEO: {duration:.0f} detik

LANGKAH-LANGKAH (jika ada):
{transcript}

TUGAS:
Buatkan script tutorial yang:
1. Introduction yang jelas tentang apa yang akan dipelajari
2. Step-by-step yang mudah diikuti
3. Tips atau catatan penting
4. Recap di akhir
5. Tone: helpful dan patient

FORMAT OUTPUT (JSON):
{{
    "full_script": "Script tutorial lengkap...",
    "segments": [
        {{"text": "Hai! Hari ini kita akan belajar...", "target_start": 0, "target_end": 5, "tone": "friendly"}},
        {{"text": "Langkah pertama...", "target_start": 5, "target_end": 15, "tone": "instructive"}}
    ],
    "word_count": 180,
    "estimated_duration": {duration:.0f},
    "steps": ["Step 1", "Step 2", "Step 3"]
}}

OUTPUT HANYA JSON VALID."""
}


class ScriptGenerator:
    """
    AI-powered script generator with multiple content types
    Uses GROQ as primary, with OpenRouter/OpenAI fallback
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """Initialize with config"""
        self.config = config or {}
        self.providers = self._setup_providers()
    
    def _setup_providers(self) -> List[Dict]:
        """Setup provider fallback chain"""
        ai_providers = self.config.get("ai_providers", {})
        
        # Order: script_generator -> highlight_finder -> default GROQ
        providers = []
        
        # Check script_generator config
        if "script_generator" in ai_providers:
            cfg = ai_providers["script_generator"]
            if cfg.get("api_key") or cfg.get("base_url"):
                providers.append(cfg)
        
        # Check highlight_finder as fallback
        if "highlight_finder" in ai_providers:
            cfg = ai_providers["highlight_finder"]
            if cfg.get("api_key") or cfg.get("base_url"):
                providers.append(cfg)
        
        # Default GROQ
        if not providers:
            providers.append({
                "base_url": "https://api.groq.com/openai/v1",
                "api_key": "",
                "model": "llama-3.3-70b-versatile"
            })
        
        return providers
    
    def _call_llm(self, 
                  prompt: str, 
                  system_prompt: str = "",
                  progress_callback: Optional[Callable] = None) -> str:
        """Call LLM with fallback"""
        from openai import OpenAI
        
        last_error = None
        
        for provider_config in self.providers:
            try:
                base_url = provider_config.get("base_url", "https://api.groq.com/openai/v1")
                config_key = provider_config.get("api_key", "")
                model = provider_config.get("model", "llama-3.3-70b-versatile")
                
                provider = detect_provider_from_url(base_url)
                api_key = get_api_key_from_env(provider, config_key)
                
                if not api_key:
                    continue
                
                if progress_callback:
                    progress_callback(f"Using {provider} for script generation...")
                
                client = OpenAI(api_key=api_key, base_url=base_url)
                
                messages = []
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": prompt})
                
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=2500
                )
                
                return response.choices[0].message.content.strip()
                
            except Exception as e:
                last_error = e
                if progress_callback:
                    progress_callback(f"Provider failed, trying next... ({str(e)[:50]})")
                continue
        
        raise Exception(f"All providers failed. Last error: {last_error}")
    
    def generate_script(self,
                       context: str,
                       duration: float,
                       content_type: ContentType = ContentType.DUBBING,
                       transcript: str = "",
                       custom_instructions: str = "",
                       progress_callback: Optional[Callable] = None) -> GeneratedScript:
        """
        Generate script for video
        
        Args:
            context: Context or topic description
            duration: Target video duration in seconds
            content_type: Type of content
            transcript: Original transcript if available
            custom_instructions: Additional instructions
            progress_callback: Progress callback
            
        Returns:
            GeneratedScript object
        """
        if progress_callback:
            progress_callback("Preparing script generation...")
        
        # Get prompt template
        template = SCRIPT_PROMPTS.get(content_type, SCRIPT_PROMPTS[ContentType.DUBBING])
        
        # Fill template
        prompt = template.format(
            context=context or "Video content",
            duration=duration,
            transcript=transcript[:3000] if transcript else "Tidak tersedia"
        )
        
        # Add custom instructions
        if custom_instructions:
            prompt += f"\n\nINSTRUKSI TAMBAHAN:\n{custom_instructions}"
        
        # Call LLM
        if progress_callback:
            progress_callback("Generating script with AI...")
        
        system_prompt = "Kamu adalah script writer profesional untuk konten video Bahasa Indonesia. Selalu output dalam format JSON yang valid."
        result_text = self._call_llm(prompt, system_prompt, progress_callback)
        
        # Parse result
        try:
            # Clean markdown if present
            if "```" in result_text:
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
            result_text = result_text.strip()
            
            data = json.loads(result_text)
        except json.JSONDecodeError:
            # Fallback: use text as script
            data = {
                "full_script": result_text,
                "segments": [{"text": result_text, "target_start": 0, "target_end": duration}],
                "word_count": len(result_text.split()),
                "estimated_duration": duration
            }
        
        # Build segments
        segments = []
        for seg_data in data.get("segments", []):
            segments.append(ScriptSegment(
                text=seg_data.get("text", ""),
                target_start=seg_data.get("target_start", 0),
                target_end=seg_data.get("target_end", 0),
                emphasis=seg_data.get("emphasis"),
                tone=seg_data.get("tone")
            ))
        
        return GeneratedScript(
            full_script=data.get("full_script", result_text),
            segments=segments,
            word_count=data.get("word_count", len(data.get("full_script", "").split())),
            estimated_duration=data.get("estimated_duration", duration),
            content_type=content_type,
            metadata={
                k: v for k, v in data.items() 
                if k not in ["full_script", "segments", "word_count", "estimated_duration"]
            }
        )
    
    def refine_script(self,
                     original_script: str,
                     feedback: str,
                     duration: float,
                     progress_callback: Optional[Callable] = None) -> str:
        """
        Refine script based on user feedback
        
        Args:
            original_script: Original generated script
            feedback: User's feedback/changes requested
            duration: Target duration
            progress_callback: Progress callback
            
        Returns:
            Refined script text
        """
        prompt = f"""Script asli:
{original_script}

Feedback/permintaan perubahan:
{feedback}

Durasi target: {duration:.0f} detik

Buatkan versi script yang sudah direvisi sesuai feedback. 
Output langsung script yang sudah diperbaiki tanpa penjelasan tambahan."""

        system_prompt = "Kamu adalah editor script profesional. Perbaiki script sesuai feedback dengan mempertahankan durasi target."
        
        return self._call_llm(prompt, system_prompt, progress_callback)
    
    def estimate_reading_time(self, text: str, wpm: int = 140) -> float:
        """Estimate reading time in seconds"""
        words = len(text.split())
        return (words / wpm) * 60


# Convenience functions
def generate_dubbing_script(context: str, duration: float, config: Dict) -> GeneratedScript:
    """Quick function for dubbing script"""
    generator = ScriptGenerator(config)
    return generator.generate_script(context, duration, ContentType.DUBBING)


def generate_shopping_script(product_info: str, duration: float, config: Dict) -> GeneratedScript:
    """Quick function for shopping script"""
    generator = ScriptGenerator(config)
    return generator.generate_script(product_info, duration, ContentType.SHOPPING)


if __name__ == "__main__":
    print("Script Generator Test")
    print("=" * 50)
    
    # Test script generation
    generator = ScriptGenerator()
    
    # Show available content types
    print("Available content types:")
    for ct in ContentType:
        print(f"  - {ct.value}")
    
    print("\nTo test, configure API keys in config.json or .env")
