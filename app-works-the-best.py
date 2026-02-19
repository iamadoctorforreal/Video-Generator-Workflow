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
    TextClip, CompositeVideoClip, ColorClip, vfx, CompositeAudioClip, afx
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
    """Aggressive fix for Kokoro TTS name crashes and emotional markers"""
    if not text:
        return "..."
    
    # 1. Handle Emotional Markers and Pauses
    text = text.replace("[sigh]", " haaaahhh... ")
    text = text.replace("[pause]", " . . . ")
    
    # 2. Remove non-ASCII and handle punctuation
    text = text.encode("ascii", "ignore").decode()
    text = text.replace("...", ".").replace("—", "-").replace("–", "-")
    
    # 3. Phonetic replacements
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
        regEx = re.compile(re.escape(original), re.IGNORECASE)
        sanitized = regEx.sub(replacement, sanitized)
    
    return sanitized.strip()

def create_caption(text, clip_size, duration):
    """Ghibli-style yellow captions with word wrapping and safe margins"""
    try:
        font_options = [r'C:\Windows\Fonts\arialbd.ttf', 'Arial', 'Impact']
        
        txt_clip = None
        for font in font_options:
            try:
                # size constraint forces 3-5 words per line
                txt_clip = TextClip(
                    text=text.strip(),
                    font=font,
                    font_size=60,
                    color='yellow',
                    stroke_color='black',
                    stroke_width=2,
                    method='caption',
                    size=(int(clip_size[0] * 0.8), int(clip_size[1] * 0.3)), 
                    text_align='center'
                ).with_duration(duration)
                break
            except:
                continue
        
        if txt_clip:
            # Positioned higher (65%) to prevent bottom letters being cut off
            txt_clip = txt_clip.with_position(('center', clip_size[1] * 0.65))
        return txt_clip
    except Exception:
        return None

def apply_pan_zoom_effect(clip, effect_type='random'):
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

def apply_random_transition(clip1, clip2, duration=0.6):
    """Alternates between crossfade and slide transitions"""
    effect = random.choice(['crossfade', 'slide'])
    if clip1.size != clip2.size:
        clip2 = clip2.resized(clip1.size)
        
    if effect == 'slide':
        return clip1, clip2.with_effects([vfx.SlideIn(duration, side='right')])
    else:
        return clip1.with_effects([vfx.FadeOut(duration)]), clip2.with_effects([vfx.FadeIn(duration)])

def auto_detect_images(images_folder, num_scenes):
    """Natural sorting for images (1, 2, 3... instead of 1, 10, 11)"""
    def natural_keys(text):
        return [int(c) if c.isdigit() else c for c in re.split(r'(\d+)', text)]
    try:
        files = [f for f in os.listdir(images_folder) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
        files.sort(key=natural_keys)
        return files[:num_scenes]
    except Exception:
        return []

@app.post("/generate-ghibli-video")
async def generate_video(request: VideoRequest):
    try:
        video_id = str(uuid.uuid4())[:8]
        final_clips = []
        BASE_MEDIA_PATH = r"C:\Users\RUKAYYAH IBRAHIM\Desktop\kokoro\images"
        MUSIC_PATH = r"C:\Users\RUKAYYAH IBRAHIM\Desktop\kokoro\bg_music.mp3"
        
        print(f"\n🎬 Starting Video Generation - ID: {video_id}")
        
        auto_detected_images = auto_detect_images(BASE_MEDIA_PATH, len(request.scenes))

        for i, scene in enumerate(request.scenes, 1):
            print(f"🎬 Processing Scene {i}/{len(request.scenes)}")
            clean_text = sanitize_text_for_tts(scene.text)
            
            media_file = auto_detected_images[i-1] if (scene.media_name == "detect" and i-1 < len(auto_detected_images)) else scene.media_name

            # 1. Voice
            audio_path = f"temp_{video_id}_{i}.wav"
            try:
                generator = pipeline(clean_text, voice=request.voice, speed=1.0)
                audio_data = None
                for _, _, audio in generator:
                    if audio is not None: audio_data = audio; break
                
                if audio_data is None: raise ValueError("NoneType Audio")
                sf.write(audio_path, audio_data, 24000)
                audio_clip = AudioFileClip(audio_path)
            except Exception:
                silence = np.zeros(int(3 * 24000))
                sf.write(audio_path, silence, 24000)
                audio_clip = AudioFileClip(audio_path)

            # 2. Media
            media_path = os.path.join(BASE_MEDIA_PATH, media_file) if media_file else None
            if not media_path or not os.path.exists(media_path):
                clip = ColorClip(size=(768, 1024), color=(30,30,30)).with_duration(audio_clip.duration)
            else:
                clip = ImageClip(media_path).with_duration(audio_clip.duration)

            # 3. Effects & Captions
            if request.add_effects: clip = apply_pan_zoom_effect(clip)
            if request.add_captions:
                caption = create_caption(scene.text, (clip.w, clip.h), audio_clip.duration)
                if caption: clip = CompositeVideoClip([clip, caption])
            
            final_clips.append(clip.with_audio(audio_clip))

        # 4. Transitions
        if request.add_effects and len(final_clips) > 1:
            transitioned = [final_clips[0]]
            for i in range(1, len(final_clips)):
                _, next_clip = apply_random_transition(final_clips[i-1], final_clips[i])
                transitioned.append(next_clip)
            final_clips = transitioned

        # 5. Background Music & Render
        final_video = concatenate_videoclips(final_clips, method="compose")
        
        if os.path.exists(MUSIC_PATH):
            bg_music = AudioFileClip(MUSIC_PATH).with_effects([afx.AudioLoop(duration=final_video.duration)])
            bg_music = bg_music.with_volume_scaled(0.12)
            final_video = final_video.with_audio(CompositeAudioClip([final_video.audio, bg_music]))

        output_name = f"Ghibli_Story_{video_id}.mp4"
        final_video.write_videofile(output_name, fps=24, codec="libx264", audio_codec="aac", preset="ultrafast", logger=None)

        # Cleanup & Log Success
        for f in glob.glob(f"temp_{video_id}_*.wav"):
            try: os.remove(f)
            except: pass
        
        print(f"\n✅ SUCCESS: Video generated as {output_name}")
        return {"status": "success", "video_path": os.path.abspath(output_name)}
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)