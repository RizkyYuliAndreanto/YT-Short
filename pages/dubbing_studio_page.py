"""
AI Dubbing Studio Page
Upload video → AI analyzes → Generate script → TTS dubbing → Export
"""

import os
import json
import threading
import tempfile
import customtkinter as ctk
from tkinter import filedialog, messagebox
from pathlib import Path
from PIL import Image
import cv2

from components.page_layout import PageHeader, PageFooter


class DubbingStudioPage(ctk.CTkFrame):
    """AI Dubbing Studio - Full dubbing workflow"""
    
    def __init__(self, parent, app, config):
        super().__init__(parent)
        self.app = app
        self.config = config
        
        # State
        self.current_video_path = None
        self.video_info = None
        self.transcript = None
        self.generated_script = None
        self.word_timings = None
        self.is_processing = False
        
        self.create_ui()
    
    def create_ui(self):
        """Create the dubbing studio UI"""
        self.configure(fg_color=("#1a1a1a", "#0a0a0a"))
        
        # Header
        header = PageHeader(self, self, show_nav_buttons=False, show_back_button=True, page_title="AI Dubbing Studio")
        header.pack(fill="x", padx=20, pady=(15, 10))
        
        # Main content - scrollable
        self.main_content = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.main_content.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        
        # Step 1: Video Upload Section
        self.create_upload_section()
        
        # Step 2: Video Info & Preview
        self.create_preview_section()
        
        # Step 3: Script Section
        self.create_script_section()
        
        # Step 4: Voice Settings
        self.create_voice_section()
        
        # Step 5: Output Settings
        self.create_output_section()
        
        # Bottom action buttons
        self.create_action_buttons()
        
        # Footer
        footer = PageFooter(self, self)
        footer.pack(fill="x", padx=20, pady=(0, 15))
    
    def create_upload_section(self):
        """Create video upload section"""
        section = ctk.CTkFrame(self.main_content, fg_color=("gray90", "gray17"), corner_radius=10)
        section.pack(fill="x", pady=(0, 10))
        
        # Header
        header = ctk.CTkFrame(section, fg_color="transparent")
        header.pack(fill="x", padx=15, pady=(12, 5))
        
        ctk.CTkLabel(header, text="📹 Step 1: Upload Video", 
            font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")
        
        self.upload_status = ctk.CTkLabel(header, text="No video selected", 
            font=ctk.CTkFont(size=10), text_color="gray")
        self.upload_status.pack(side="right")
        
        # Upload area
        upload_frame = ctk.CTkFrame(section, fg_color=("gray85", "gray20"), corner_radius=8, height=100)
        upload_frame.pack(fill="x", padx=15, pady=(5, 15))
        upload_frame.pack_propagate(False)
        
        upload_content = ctk.CTkFrame(upload_frame, fg_color="transparent")
        upload_content.place(relx=0.5, rely=0.5, anchor="center")
        
        self.upload_label = ctk.CTkLabel(upload_content, 
            text="🎬 Click to select video file\nor drag & drop here",
            font=ctk.CTkFont(size=12), text_color="gray", justify="center")
        self.upload_label.pack()
        
        # Make clickable
        upload_frame.bind("<Button-1>", lambda e: self.select_video())
        self.upload_label.bind("<Button-1>", lambda e: self.select_video())
        
        # Browse button
        ctk.CTkButton(section, text="📁 Browse Files", height=36,
            command=self.select_video).pack(fill="x", padx=15, pady=(0, 15))
    
    def create_preview_section(self):
        """Create video preview section"""
        self.preview_section = ctk.CTkFrame(self.main_content, fg_color=("gray90", "gray17"), corner_radius=10)
        self.preview_section.pack(fill="x", pady=(0, 10))
        self.preview_section.pack_forget()  # Hidden initially
        
        # Header
        ctk.CTkLabel(self.preview_section, text="🎥 Video Info", 
            font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=15, pady=(12, 5))
        
        # Info grid
        info_frame = ctk.CTkFrame(self.preview_section, fg_color="transparent")
        info_frame.pack(fill="x", padx=15, pady=(0, 10))
        
        # Left: Thumbnail
        thumb_frame = ctk.CTkFrame(info_frame, width=160, height=90, 
            fg_color=("gray75", "gray30"), corner_radius=8)
        thumb_frame.pack(side="left", padx=(0, 15))
        thumb_frame.pack_propagate(False)
        
        self.thumb_label = ctk.CTkLabel(thumb_frame, text="📹", font=ctk.CTkFont(size=24))
        self.thumb_label.place(relx=0.5, rely=0.5, anchor="center")
        
        # Right: Info
        info_content = ctk.CTkFrame(info_frame, fg_color="transparent")
        info_content.pack(side="left", fill="both", expand=True)
        
        self.video_name_label = ctk.CTkLabel(info_content, text="Video Name", 
            font=ctk.CTkFont(size=12, weight="bold"), anchor="w")
        self.video_name_label.pack(anchor="w")
        
        self.video_info_label = ctk.CTkLabel(info_content, text="Duration: --  |  Resolution: --", 
            font=ctk.CTkFont(size=10), text_color="gray", anchor="w")
        self.video_info_label.pack(anchor="w", pady=(2, 0))
        
        self.transcript_label = ctk.CTkLabel(info_content, text="Transcript: Not analyzed", 
            font=ctk.CTkFont(size=10), text_color="gray", anchor="w")
        self.transcript_label.pack(anchor="w", pady=(2, 0))
        
        # Analyze button
        self.analyze_btn = ctk.CTkButton(self.preview_section, text="🔍 Analyze Video (Extract Audio & Transcribe)", 
            height=40, command=self.analyze_video)
        self.analyze_btn.pack(fill="x", padx=15, pady=(5, 15))
    
    def create_script_section(self):
        """Create script editing section"""
        self.script_section = ctk.CTkFrame(self.main_content, fg_color=("gray90", "gray17"), corner_radius=10)
        self.script_section.pack(fill="x", pady=(0, 10))
        self.script_section.pack_forget()  # Hidden initially
        
        # Header with word count
        header = ctk.CTkFrame(self.script_section, fg_color="transparent")
        header.pack(fill="x", padx=15, pady=(12, 5))
        
        ctk.CTkLabel(header, text="📝 Step 2: Edit Script", 
            font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")
        
        self.word_count_label = ctk.CTkLabel(header, text="0 words | ~0s", 
            font=ctk.CTkFont(size=10), text_color="gray")
        self.word_count_label.pack(side="right")
        
        # Script type selector
        type_frame = ctk.CTkFrame(self.script_section, fg_color="transparent")
        type_frame.pack(fill="x", padx=15, pady=(0, 5))
        
        ctk.CTkLabel(type_frame, text="Script Type:", font=ctk.CTkFont(size=11)).pack(side="left")
        
        self.script_type_var = ctk.StringVar(value="dubbing")
        types = ["dubbing", "narration", "shopping", "tutorial", "entertainment"]
        self.script_type_menu = ctk.CTkOptionMenu(type_frame, values=types, 
            variable=self.script_type_var, height=30)
        self.script_type_menu.pack(side="left", padx=(10, 0))
        
        self.regenerate_btn = ctk.CTkButton(type_frame, text="🔄 Regenerate", height=30, width=100,
            fg_color=("gray70", "gray30"), command=self.regenerate_script)
        self.regenerate_btn.pack(side="right")
        
        # Script textbox
        self.script_textbox = ctk.CTkTextbox(self.script_section, height=200, wrap="word")
        self.script_textbox.pack(fill="x", padx=15, pady=(5, 10))
        self.script_textbox.bind("<KeyRelease>", self.update_word_count)
        
        # Tips
        tips = ctk.CTkLabel(self.script_section, 
            text="💡 Tips: Edit script untuk menyesuaikan dengan video. Target 130-150 kata per menit untuk pace natural.",
            font=ctk.CTkFont(size=10), text_color="gray", wraplength=500, justify="left")
        tips.pack(anchor="w", padx=15, pady=(0, 15))
    
    def create_voice_section(self):
        """Create voice settings section"""
        self.voice_section = ctk.CTkFrame(self.main_content, fg_color=("gray90", "gray17"), corner_radius=10)
        self.voice_section.pack(fill="x", pady=(0, 10))
        self.voice_section.pack_forget()  # Hidden initially
        
        # Header
        ctk.CTkLabel(self.voice_section, text="🎤 Step 3: Voice Settings", 
            font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=15, pady=(12, 10))
        
        # Voice selector
        voice_frame = ctk.CTkFrame(self.voice_section, fg_color="transparent")
        voice_frame.pack(fill="x", padx=15, pady=(0, 10))
        
        ctk.CTkLabel(voice_frame, text="Voice:", font=ctk.CTkFont(size=11)).pack(side="left")
        
        # Get voice options from config or default
        self.voice_var = ctk.StringVar(value="id-ID-ArdiNeural")
        voice_options = [
            "id-ID-ArdiNeural (Pria)",
            "id-ID-GadisNeural (Wanita)"
        ]
        self.voice_menu = ctk.CTkOptionMenu(voice_frame, values=voice_options,
            variable=self.voice_var, height=32, width=200)
        self.voice_menu.pack(side="left", padx=(10, 20))
        
        # Preview voice button
        self.preview_voice_btn = ctk.CTkButton(voice_frame, text="🔊 Preview", height=32, width=80,
            fg_color=("gray70", "gray30"), command=self.preview_voice)
        self.preview_voice_btn.pack(side="left")
        
        # Speed & Pitch
        settings_frame = ctk.CTkFrame(self.voice_section, fg_color="transparent")
        settings_frame.pack(fill="x", padx=15, pady=(0, 10))
        
        # Speed
        speed_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        speed_frame.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        ctk.CTkLabel(speed_frame, text="Speed:", font=ctk.CTkFont(size=11)).pack(anchor="w")
        self.speed_var = ctk.DoubleVar(value=0)
        self.speed_slider = ctk.CTkSlider(speed_frame, from_=-50, to=50, 
            variable=self.speed_var, command=self.on_speed_change)
        self.speed_slider.pack(fill="x", pady=(5, 0))
        self.speed_label = ctk.CTkLabel(speed_frame, text="+0%", font=ctk.CTkFont(size=10), text_color="gray")
        self.speed_label.pack(anchor="e")
        
        # Pitch
        pitch_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        pitch_frame.pack(side="left", fill="x", expand=True)
        
        ctk.CTkLabel(pitch_frame, text="Pitch:", font=ctk.CTkFont(size=11)).pack(anchor="w")
        self.pitch_var = ctk.DoubleVar(value=0)
        self.pitch_slider = ctk.CTkSlider(pitch_frame, from_=-20, to=20,
            variable=self.pitch_var, command=self.on_pitch_change)
        self.pitch_slider.pack(fill="x", pady=(5, 0))
        self.pitch_label = ctk.CTkLabel(pitch_frame, text="+0Hz", font=ctk.CTkFont(size=10), text_color="gray")
        self.pitch_label.pack(anchor="e")
        
        # Audio mix settings
        mix_frame = ctk.CTkFrame(self.voice_section, fg_color="transparent")
        mix_frame.pack(fill="x", padx=15, pady=(0, 15))
        
        self.keep_audio_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(mix_frame, text="Keep original audio (background)", 
            variable=self.keep_audio_var).pack(anchor="w")
        
        bg_volume_frame = ctk.CTkFrame(mix_frame, fg_color="transparent")
        bg_volume_frame.pack(fill="x", pady=(5, 0))
        
        ctk.CTkLabel(bg_volume_frame, text="Background Volume:", font=ctk.CTkFont(size=10)).pack(side="left")
        self.bg_volume_var = ctk.DoubleVar(value=20)
        self.bg_volume_slider = ctk.CTkSlider(bg_volume_frame, from_=0, to=100, width=150,
            variable=self.bg_volume_var, command=self.on_bg_volume_change)
        self.bg_volume_slider.pack(side="left", padx=(10, 5))
        self.bg_volume_label = ctk.CTkLabel(bg_volume_frame, text="20%", font=ctk.CTkFont(size=10), text_color="gray")
        self.bg_volume_label.pack(side="left")
    
    def create_output_section(self):
        """Create output settings section"""
        self.output_section = ctk.CTkFrame(self.main_content, fg_color=("gray90", "gray17"), corner_radius=10)
        self.output_section.pack(fill="x", pady=(0, 10))
        self.output_section.pack_forget()  # Hidden initially
        
        # Header
        ctk.CTkLabel(self.output_section, text="💾 Step 4: Output Settings", 
            font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=15, pady=(12, 10))
        
        settings_frame = ctk.CTkFrame(self.output_section, fg_color="transparent")
        settings_frame.pack(fill="x", padx=15, pady=(0, 15))
        
        # Subtitle option
        self.subtitle_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(settings_frame, text="Burn subtitles into video", 
            variable=self.subtitle_var).pack(anchor="w", pady=(0, 5))
        
        # Output folder
        folder_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        folder_frame.pack(fill="x", pady=(5, 0))
        
        ctk.CTkLabel(folder_frame, text="Output folder:", font=ctk.CTkFont(size=11)).pack(side="left")
        
        output_dir = self.config.get("output_dir", "output")
        self.output_path_label = ctk.CTkLabel(folder_frame, text=output_dir[:50] + "..." if len(output_dir) > 50 else output_dir,
            font=ctk.CTkFont(size=10), text_color="gray")
        self.output_path_label.pack(side="left", padx=(10, 0))
    
    def create_action_buttons(self):
        """Create bottom action buttons"""
        self.action_frame = ctk.CTkFrame(self.main_content, fg_color="transparent")
        self.action_frame.pack(fill="x", pady=(10, 0))
        self.action_frame.pack_forget()  # Hidden initially
        
        # Progress bar
        self.progress_frame = ctk.CTkFrame(self.action_frame, fg_color="transparent")
        self.progress_frame.pack(fill="x", pady=(0, 10))
        self.progress_frame.pack_forget()
        
        self.progress_bar = ctk.CTkProgressBar(self.progress_frame)
        self.progress_bar.pack(fill="x")
        self.progress_bar.set(0)
        
        self.progress_label = ctk.CTkLabel(self.progress_frame, text="", 
            font=ctk.CTkFont(size=10), text_color="gray")
        self.progress_label.pack(pady=(5, 0))
        
        # Generate button
        self.generate_btn = ctk.CTkButton(self.action_frame, text="🎬 Generate Dubbed Video", 
            height=50, font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=("#2ecc71", "#27ae60"), hover_color=("#27ae60", "#1e8449"),
            command=self.generate_video)
        self.generate_btn.pack(fill="x")
    
    # ============ Event Handlers ============
    
    def select_video(self):
        """Open file dialog to select video"""
        file_path = filedialog.askopenfilename(
            title="Select Video File",
            filetypes=[
                ("Video files", "*.mp4 *.avi *.mkv *.mov *.webm"),
                ("All files", "*.*")
            ]
        )
        
        if file_path:
            self.load_video(file_path)
    
    def load_video(self, video_path: str):
        """Load selected video"""
        self.current_video_path = video_path
        
        # Update UI
        filename = os.path.basename(video_path)
        self.upload_status.configure(text=f"✓ {filename[:30]}...")
        self.upload_label.configure(text=f"🎬 {filename}")
        
        # Show preview section
        self.preview_section.pack(fill="x", pady=(0, 10), after=self.main_content.winfo_children()[0])
        
        # Get video info
        self.load_video_info(video_path)
    
    def load_video_info(self, video_path: str):
        """Load video metadata"""
        def load():
            try:
                from video_analyzer import VideoAnalyzer
                analyzer = VideoAnalyzer(self.config)
                self.video_info = analyzer.get_video_info(video_path)
                
                # Update UI
                self.after(0, self.update_video_info_ui)
                
                # Try to get thumbnail
                self.extract_thumbnail(video_path)
                
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", f"Failed to load video: {e}"))
        
        threading.Thread(target=load, daemon=True).start()
    
    def update_video_info_ui(self):
        """Update video info in UI"""
        if self.video_info:
            filename = os.path.basename(self.video_info.path)
            self.video_name_label.configure(text=filename[:40])
            
            duration = self.video_info.duration
            minutes = int(duration // 60)
            seconds = int(duration % 60)
            duration_str = f"{minutes}:{seconds:02d}" if minutes > 0 else f"{seconds}s"
            
            self.video_info_label.configure(
                text=f"Duration: {duration_str}  |  {self.video_info.width}x{self.video_info.height}  |  {self.video_info.fps:.0f}fps"
            )
    
    def extract_thumbnail(self, video_path: str):
        """Extract thumbnail from video"""
        try:
            cap = cv2.VideoCapture(video_path)
            cap.set(cv2.CAP_PROP_POS_FRAMES, 30)  # Frame 30
            ret, frame = cap.read()
            cap.release()
            
            if ret:
                # Convert to PIL
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(frame_rgb)
                img.thumbnail((160, 90), Image.Resampling.LANCZOS)
                
                # Update UI
                self.after(0, lambda: self.set_thumbnail(img))
        except Exception as e:
            print(f"Thumbnail error: {e}")
    
    def set_thumbnail(self, img: Image.Image):
        """Set thumbnail in UI"""
        try:
            thumb = ctk.CTkImage(light_image=img, dark_image=img, size=(160, 90))
            self.thumb_label.configure(image=thumb, text="")
            self._thumb_ref = thumb  # Keep reference
        except:
            pass
    
    def analyze_video(self):
        """Analyze video - extract audio and transcribe"""
        if not self.current_video_path:
            messagebox.showwarning("Warning", "Please select a video first")
            return
        
        if self.is_processing:
            return
        
        self.is_processing = True
        self.analyze_btn.configure(state="disabled", text="🔄 Analyzing...")
        
        def analyze():
            try:
                from video_analyzer import VideoAnalyzer
                
                analyzer = VideoAnalyzer(self.config)
                
                def progress(msg):
                    self.after(0, lambda: self.analyze_btn.configure(text=f"🔄 {msg}"))
                
                analysis = analyzer.analyze_video(
                    self.current_video_path, 
                    language="id",
                    progress_callback=progress
                )
                
                self.transcript = analysis.full_text
                self.generated_script = analysis.suggested_script
                
                # Update UI
                self.after(0, lambda: self.on_analysis_complete(analysis))
                
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", f"Analysis failed: {e}"))
            finally:
                self.is_processing = False
                self.after(0, lambda: self.analyze_btn.configure(
                    state="normal", text="🔍 Analyze Video (Extract Audio & Transcribe)"
                ))
        
        threading.Thread(target=analyze, daemon=True).start()
    
    def on_analysis_complete(self, analysis):
        """Handle analysis completion"""
        self.transcript_label.configure(
            text=f"Transcript: ✓ {len(analysis.full_text.split())} words detected"
        )
        
        # Show script section
        self.script_section.pack(fill="x", pady=(0, 10))
        
        # Fill script
        self.script_textbox.delete("1.0", "end")
        self.script_textbox.insert("1.0", analysis.suggested_script)
        self.update_word_count()
        
        # Show voice section
        self.voice_section.pack(fill="x", pady=(0, 10))
        
        # Show output section
        self.output_section.pack(fill="x", pady=(0, 10))
        
        # Show action buttons
        self.action_frame.pack(fill="x", pady=(10, 0))
        
        messagebox.showinfo("Analysis Complete", 
            f"Video analyzed successfully!\n\n"
            f"Context: {analysis.context[:100]}...\n\n"
            f"Script generated with {len(analysis.suggested_script.split())} words.\n"
            f"Edit the script if needed, then click Generate.")
    
    def regenerate_script(self):
        """Regenerate script with current type"""
        if not self.transcript:
            messagebox.showwarning("Warning", "Please analyze video first")
            return
        
        if self.is_processing:
            return
        
        self.is_processing = True
        self.regenerate_btn.configure(state="disabled", text="🔄...")
        
        def regenerate():
            try:
                from script_generator import ScriptGenerator, ContentType
                
                generator = ScriptGenerator(self.config)
                content_type = ContentType(self.script_type_var.get())
                
                result = generator.generate_script(
                    context=self.transcript[:1000],
                    duration=self.video_info.duration if self.video_info else 60,
                    content_type=content_type,
                    transcript=self.transcript
                )
                
                self.generated_script = result.full_script
                
                # Update UI
                self.after(0, lambda: self.script_textbox.delete("1.0", "end"))
                self.after(0, lambda: self.script_textbox.insert("1.0", result.full_script))
                self.after(0, self.update_word_count)
                
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", f"Regeneration failed: {e}"))
            finally:
                self.is_processing = False
                self.after(0, lambda: self.regenerate_btn.configure(state="normal", text="🔄 Regenerate"))
        
        threading.Thread(target=regenerate, daemon=True).start()
    
    def update_word_count(self, event=None):
        """Update word count display"""
        text = self.script_textbox.get("1.0", "end-1c")
        words = len(text.split())
        estimated_seconds = (words / 140) * 60  # 140 WPM
        self.word_count_label.configure(text=f"{words} words | ~{int(estimated_seconds)}s")
    
    def on_speed_change(self, value):
        """Handle speed slider change"""
        val = int(float(value))
        sign = "+" if val >= 0 else ""
        self.speed_label.configure(text=f"{sign}{val}%")
    
    def on_pitch_change(self, value):
        """Handle pitch slider change"""
        val = int(float(value))
        sign = "+" if val >= 0 else ""
        self.pitch_label.configure(text=f"{sign}{val}Hz")
    
    def on_bg_volume_change(self, value):
        """Handle background volume change"""
        val = int(float(value))
        self.bg_volume_label.configure(text=f"{val}%")
    
    def preview_voice(self):
        """Preview selected voice with sample text"""
        if self.is_processing:
            return
        
        self.is_processing = True
        self.preview_voice_btn.configure(state="disabled", text="🔊...")
        
        def preview():
            try:
                from edge_tts_engine import EdgeTTSManager
                import tempfile
                import subprocess
                
                # Get voice ID from selection
                voice_selection = self.voice_var.get()
                voice_id = "id-ID-ArdiNeural"
                if "Gadis" in voice_selection:
                    voice_id = "id-ID-GadisNeural"
                
                # Get speed/pitch
                speed = int(float(self.speed_var.get()))
                pitch = int(float(self.pitch_var.get()))
                
                manager = EdgeTTSManager({
                    "voice": voice_id,
                    "rate": f"+{speed}%" if speed >= 0 else f"{speed}%",
                    "pitch": f"+{pitch}Hz" if pitch >= 0 else f"{pitch}Hz"
                })
                
                # Generate preview
                temp_file = tempfile.mktemp(suffix=".mp3")
                sample_text = "Halo semuanya! Ini adalah contoh suara yang akan digunakan untuk dubbing video Anda."
                
                manager.generate_audio_sync(sample_text, temp_file)
                
                # Play audio (using system default player)
                if os.name == "nt":
                    os.startfile(temp_file)
                else:
                    subprocess.run(["xdg-open", temp_file])
                
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", f"Preview failed: {e}"))
            finally:
                self.is_processing = False
                self.after(0, lambda: self.preview_voice_btn.configure(state="normal", text="🔊 Preview"))
        
        threading.Thread(target=preview, daemon=True).start()
    
    def generate_video(self):
        """Generate dubbed video"""
        if not self.current_video_path:
            messagebox.showwarning("Warning", "Please select a video first")
            return
        
        script = self.script_textbox.get("1.0", "end-1c").strip()
        if not script:
            messagebox.showwarning("Warning", "Please enter a script")
            return
        
        if self.is_processing:
            return
        
        self.is_processing = True
        self.generate_btn.configure(state="disabled", text="🔄 Processing...")
        self.progress_frame.pack(fill="x", pady=(0, 10))
        
        def generate():
            try:
                from tts_sync import TTSVideoSync
                
                # Get voice settings
                voice_selection = self.voice_var.get()
                voice_id = "id-ID-ArdiNeural"
                if "Gadis" in voice_selection:
                    voice_id = "id-ID-GadisNeural"
                
                speed = int(float(self.speed_var.get()))
                pitch = int(float(self.pitch_var.get()))
                bg_volume = int(float(self.bg_volume_var.get())) / 100
                
                syncer = TTSVideoSync({
                    "edge_tts": {
                        "voice": voice_id,
                        "rate": f"+{speed}%" if speed >= 0 else f"{speed}%",
                        "pitch": f"+{pitch}Hz" if pitch >= 0 else f"{pitch}Hz"
                    },
                    "mix_config": {
                        "voice_volume": 1.0,
                        "background_volume": bg_volume,
                        "keep_original_audio": self.keep_audio_var.get()
                    }
                })
                
                # Setup output path
                output_dir = self.config.get("output_dir", "output")
                os.makedirs(output_dir, exist_ok=True)
                
                input_name = os.path.splitext(os.path.basename(self.current_video_path))[0]
                output_path = os.path.join(output_dir, f"{input_name}_dubbed.mp4")
                
                # Counter for unique filename
                counter = 1
                while os.path.exists(output_path):
                    output_path = os.path.join(output_dir, f"{input_name}_dubbed_{counter}.mp4")
                    counter += 1
                
                def progress(msg):
                    self.after(0, lambda: self.progress_label.configure(text=msg))
                    self.after(0, lambda: self.progress_bar.set(0.5))  # Indeterminate style
                
                result = syncer.process_video_with_tts(
                    video_path=self.current_video_path,
                    script=script,
                    output_path=output_path,
                    include_subtitle=self.subtitle_var.get(),
                    progress_callback=progress
                )
                
                if result["success"]:
                    self.after(0, lambda: self.on_generation_complete(result["output_path"]))
                else:
                    raise Exception(result.get("error", "Unknown error"))
                
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", f"Generation failed: {e}"))
            finally:
                self.is_processing = False
                self.after(0, lambda: self.generate_btn.configure(state="normal", text="🎬 Generate Dubbed Video"))
                self.after(0, lambda: self.progress_bar.set(0))
        
        threading.Thread(target=generate, daemon=True).start()
    
    def on_generation_complete(self, output_path: str):
        """Handle generation completion"""
        self.progress_bar.set(1)
        self.progress_label.configure(text="✓ Complete!")
        
        result = messagebox.askyesno("Success!", 
            f"Video generated successfully!\n\n"
            f"Saved to:\n{output_path}\n\n"
            f"Open output folder?")
        
        if result:
            import subprocess
            folder = os.path.dirname(output_path)
            if os.name == "nt":
                os.startfile(folder)
            else:
                subprocess.run(["xdg-open", folder])
    
    # Navigation helpers
    def show_page(self, page_name):
        """Delegate to parent app"""
        try:
            parent = self.master
            while parent and not hasattr(parent, 'show_page'):
                parent = parent.master
            if parent and hasattr(parent, 'show_page'):
                parent.show_page(page_name)
        except:
            pass
    
    def open_discord(self):
        """Open Discord"""
        import webbrowser
        webbrowser.open("https://s.id/ytsdiscord")
    
    def open_github(self):
        """Open GitHub"""
        import webbrowser
        webbrowser.open("https://github.com/jipraks/yt-short-clipper")
