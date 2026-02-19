import os
import re
import glob
import uuid
import random
import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from kokoro import KPipeline
from moviepy import (
    ImageClip, VideoFileClip, concatenate_videoclips, AudioFileClip,
    TextClip, CompositeVideoClip, ColorClip, vfx
)
from fastapi.middleware.cors import CORSMiddleware

# Set the ImageMagick path for MoviePy v2.0+ BEFORE other imports
os.environ["IMAGEMAGICK_BINARY"] = r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize the Kokoro Pipeline
pipeline = KPipeline(lang_code='a')

class Scene(BaseModel):
    text: str
    media_name: str 

class VideoRequest(BaseModel):
    scenes: list[Scene]
    voice: str = "af_bella"
    add_captions: bool = True
    add_effects: bool = True

def sanitize_text_for_tts(text):
    """Aggressive fix for Kokoro TTS name crashes and special characters"""
    if not text:
        return "..."
    
    # 1. Remove non-ASCII (emojis, etc.) and handle ellipses/dashes
    text = text.encode("ascii", "ignore").decode()
    text = text.replace("...", ".").replace("—", "-").replace("–", "-")
    
    # 2. Phonetic replacements for consistency
    replacements = {
        'Aiko': 'Eye-ko',
        'Haru': 'Ha-roo',
        'Yuki': 'You-kee',
        'Sora': 'So-rah',
        'Ren': 'Ren',
        'Kaito': 'Kai-toe',
        'Mei': 'May',
        'cicadas': 'si-kay-dahs'
    }
    
    sanitized = text
    for original, replacement in replacements.items():
        # Case-insensitive replacement using regex
        regEx = re.compile(re.escape(original), re.IGNORECASE)
        sanitized = regEx.sub(replacement, sanitized)
    
    return sanitized.strip()

def create_caption(text, clip_size, duration):
    """Create simple caption overlay"""
    try:
        font_options = [
            r'C:\Windows\Fonts\arial.ttf',
            r'C:\Windows\Fonts\arialbd.ttf',
            'Arial', 'Impact'
        ]
        
        txt = None
        for font in font_options:
            try:
                txt = TextClip(
                    text=text,
                    font=font,
                    font_size=55,
                    color='white',
                    stroke_color='black',
                    stroke_width=3,
                    method='caption',
                    size=(int(clip_size[0] * 0.9), None),
                    text_align='center'
                ).with_duration(duration)
                break
            except:
                continue
        
        if txt:
            txt = txt.with_position(('center', clip_size[1] * 0.75))
        return txt
    except Exception:
        return None

def apply_pan_zoom_effect(clip, effect_type='random'):
    """Apply cinematic pan/zoom effects"""
    w, h = clip.size
    duration = clip.duration
    
    if effect_type == 'random':
        effect_type = random.choice(['zoom_in', 'zoom_out', 'pan_right', 'pan_left'])
    
    if effect_type == 'zoom_in':
        return clip.resized(lambda t: 1 + 0.15 * (t / duration))
    elif effect_type == 'zoom_out':
        return clip.resized(lambda t: 1.15 - 0.15 * (t / duration))
    elif effect_type == 'pan_right':
        return clip.with_position(lambda t: (-(t / duration) * w * 0.1, 0))
    elif effect_type == 'pan_left':
        return clip.with_position(lambda t: ((t / duration) * w * 0.1, 0))
    return clip

def create_crossfade_transition(clip1, clip2, duration=0.5):
    """Create crossfade transition between clips"""
    if clip1.size != clip2.size:
        clip2 = clip2.resized(clip1.size)
    clip1_fade = clip1.with_effects([vfx.FadeOut(duration)])
    clip2_fade = clip2.with_effects([vfx.FadeIn(duration)])
    return clip1_fade, clip2_fade

def auto_detect_images(images_folder, num_scenes):
    """Auto-detect images sorted by creation time"""
    try:
        files = []
        for file in os.listdir(images_folder):
            if file.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.mp4', '.mov')):
                filepath = os.path.join(images_folder, file)
                files.append({'name': file, 'time': os.path.getctime(filepath)})
        files.sort(key=lambda x: x['time'])
        return [f['name'] for f in files[:num_scenes]]
    except Exception:
        return []

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "ghibli-video-generator"}

@app.post("/generate-ghibli-video")
async def generate_video(request: VideoRequest):
    try:
        video_id = str(uuid.uuid4())[:8]
        final_clips = []
        BASE_MEDIA_PATH = r"C:\Users\RUKAYYAH IBRAHIM\Desktop\kokoro\images"
        
        print(f"\n🎬 Starting Video Generation - ID: {video_id}")
        
        auto_detected_images = []
        if any(scene.media_name == "detect" for scene in request.scenes):
            auto_detected_images = auto_detect_images(BASE_MEDIA_PATH, len(request.scenes))

        for i, scene in enumerate(request.scenes, 1):
            print(f"🎬 Processing Scene {i}/{len(request.scenes)}")
            
            clean_text = sanitize_text_for_tts(scene.text)
            
            if scene.media_name == "detect" and auto_detected_images:
                media_file = auto_detected_images[i-1] if i-1 < len(auto_detected_images) else None
            else:
                media_file = scene.media_name

            # 1. Generate Voice with explicit None-check
            audio_path = f"temp_{video_id}_{i}.wav"
            try:
                generator = pipeline(clean_text, voice=request.voice, speed=1.0)
                audio_data = None
                for _, _, audio in generator:
                    if audio is not None:
                        audio_data = audio
                        break
                
                if audio_data is None:
                    raise ValueError("Phonemizer returned NoneType")
                
                sf.write(audio_path, audio_data, 24000)
                audio_clip = AudioFileClip(audio_path)
            except Exception as e:
                print(f"   ❌ TTS Error on scene {i}: {e}")
                # Fallback to 3 seconds of silence
                silence = np.zeros(int(3 * 24000))
                sf.write(audio_path, silence, 24000)
                audio_clip = AudioFileClip(audio_path)

            # 2. Load Media
            media_path = os.path.join(BASE_MEDIA_PATH, media_file) if media_file else None
            if not media_path or not os.path.exists(media_path):
                clip = ColorClip(size=(768, 1024), color=(0,0,0)).with_duration(audio_clip.duration)
            else:
                if media_path.lower().endswith(('.mp4', '.mov')):
                    clip = VideoFileClip(media_path)
                    clip = clip.subclipped(0, min(clip.duration, audio_clip.duration)).with_duration(audio_clip.duration)
                else:
                    clip = ImageClip(media_path).with_duration(audio_clip.duration)

            # 3. Effects & Captions
            if request.add_effects:
                clip = apply_pan_zoom_effect(clip)
            
            if request.add_captions:
                caption = create_caption(scene.text, (clip.w, clip.h), audio_clip.duration)
                if caption:
                    clip = CompositeVideoClip([clip, caption])
            
            clip = clip.with_audio(audio_clip)
            final_clips.append(clip)

        # 4. Transitions
        if request.add_effects and len(final_clips) > 1:
            transitioned_clips = [final_clips[0]]
            for i in range(1, len(final_clips)):
                prev, curr = create_crossfade_transition(final_clips[i-1], final_clips[i])
                transitioned_clips.append(curr)
            final_clips = transitioned_clips

        # 5. Render
        output_name = f"Ghibli_Story_{video_id}.mp4"
        final_video = concatenate_videoclips(final_clips, method="compose")
        final_video.write_videofile(
            output_name, fps=24, codec="libx264", audio_codec="aac",
            temp_audiofile=f"temp_audio_{video_id}.m4a", remove_temp=True, logger=None
        )

        # Cleanup
        for f in glob.glob(f"temp_{video_id}_*.wav"):
            try: os.remove(f)
            except: pass
            
        return {"status": "success", "video_path": os.path.abspath(output_name)}
        
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)