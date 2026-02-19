import os
import re
import glob
import uuid
import random
import time
import numpy as np
from faster_whisper import WhisperModel
import gc
import soundfile as sf
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from kokoro_onnx import Kokoro
from moviepy import (
    ImageClip, VideoFileClip, concatenate_videoclips, AudioFileClip,
    TextClip, CompositeVideoClip, ColorClip, vfx, CompositeAudioClip, afx
)
from fastapi.middleware.cors import CORSMiddleware

# Set the ImageMagick path for MoviePy v2.0+
os.environ["IMAGEMAGICK_BINARY"] = r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize models
whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
kokoro = Kokoro("kokoro-v0_19.onnx", "voices-v1.0.bin") 

class Scene(BaseModel):
    text: str
    media_name: str 

class VideoRequest(BaseModel):
    scenes: list[Scene]
    voice: str = "af_bella"
    add_captions: bool = True
    add_effects: bool = True
    caption_position: str = "bottom"  # "bottom", "center", "top"
    orientation: str = "portrait"    # "portrait" or "landscape"

def sanitize_text_for_tts(text):
    if not text: return "..."
    text = text.replace("[sigh]", " haaaahhh... ").replace("[pause]", " . . . ")
    text = text.encode("ascii", "ignore").decode()
    text = text.replace("...", ".").replace("—", "-").replace("–", "-")
    # Aggressive character cleaning
    text = re.sub(r'["\'`“”‘’]', '', text)
    text = re.sub(r'[^\w\s\.,!\?\-]', '', text)
    
    replacements = {
         'Aiko': 'Eye-ko', 
         'Haru': 'Ha-roo', 
         'Yuki': 'You-kee', 
         'Elara': 'Eh-lah-rah', 
         'Midasis': 'Mih-dah-sis', 
         'cicadas': 'si-kay-dahs'}
    
    for original, replacement in replacements.items():
        regEx = re.compile(re.escape(original), re.IGNORECASE)
        text = regEx.sub(replacement, text)
    return text.strip()

def get_word_timestamps(audio_path):
    segments, _ = whisper_model.transcribe(audio_path, word_timestamps=True)
    words_list = []
    for segment in segments:
        for word in segment.words:
            w = word.word.strip()
            if w:
                words_list.append({
                    "word": w,
                    "start": word.start,
                    "end": word.end
                })
    return words_list

def create_dynamic_captions(words, clip_size, active_index=0, caption_position="bottom"):
    if not words: return []
    word_clips = []
    w_bg, h_bg = clip_size

    position_map = {
        "bottom": h_bg * 0.78,
        "center": h_bg * 0.50,
        "top":    h_bg * 0.15,
    }
    y_pos = position_map.get(caption_position, h_bg * 0.78)

    FONT = r'C:\Windows\Fonts\arialbd.ttf'
    FONT_SIZE = 80
    GAP = 12
    WORDS_PER_GROUP = 4
    MARGIN = (20, 20)

    # 1. Group words
    groups = []
    for i in range(0, len(words), WORDS_PER_GROUP):
        groups.append(words[i:i + WORDS_PER_GROUP])

    # 2. Timing sanitization
    for i in range(len(groups) - 1):
        if groups[i] and groups[i+1]:
            if groups[i][-1]['end'] > groups[i+1][0]['start']:
                groups[i][-1]['end'] = groups[i+1][0]['start']

    # 3. Render Groups
    for group in groups:
        measured = []
        for word_obj in group:
            txt = word_obj['word'].upper()
            try:
                # Use a small background buffer to ensure width is NEVER 0
                t = TextClip(text=txt, font=FONT, font_size=FONT_SIZE, method='label', margin=MARGIN)
                if t.w > 5 and t.h > 5:
                    measured.append({'w': int(t.w), 'h': int(t.h), 'txt': txt, 'obj': word_obj})
                t.close()
            except: continue

        if not measured: continue

        total_w = sum(m['w'] for m in measured) + GAP * (len(measured) - 1)
        start_x = (w_bg - total_w) // 2
        
        # Calculate fixed positions
        curr_x = start_x
        for m in measured:
            m['x'] = int(curr_x)
            m['y'] = int(y_pos - m['h'] // 2)
            curr_x += m['w'] + GAP

        # 4. Create highlight segments
        for i, active_item in enumerate(measured):
            s_start = active_item['obj']['start']
            s_end = active_item['obj']['end']
            s_dur = max(0.1, s_end - s_start)

            for j, m in enumerate(measured):
                is_active = (i == j)
                try:
                    # Create the basic text clip
                    t_clip = TextClip(
                        text=m['txt'],
                        font=FONT,
                        font_size=FONT_SIZE,
                        color='yellow' if is_active else 'white',
                        stroke_color='black',
                        stroke_width=4 if is_active else 2,
                        method='label',
                        margin=MARGIN
                    )
                    
                    # THE ULTIMATE STABILITY CHECK
                    if t_clip.w < 2 or t_clip.h < 2:
                        t_clip.close()
                        continue
                        
                    # Force mask correction if needed
                    if t_clip.mask and (t_clip.mask.size != t_clip.size):
                        t_clip.mask = t_clip.mask.resized(new_size=t_clip.size)
                    
                    # Pre-render a frame to catch broadcasting errors EARLY
                    try:
                        _ = t_clip.get_frame(0)
                        if t_clip.mask: _ = t_clip.mask.get_frame(0)
                    except:
                        t_clip.close()
                        continue

                    t_clip = t_clip.with_start(s_start).with_duration(s_dur).with_position((m['x'], m['y']))
                    if not is_active: t_clip = t_clip.with_opacity(0.6)
                    
                    word_clips.append(t_clip)
                except: continue
                
    return word_clips

def apply_effects(clip):
    w, h = clip.size
    d = clip.duration
    eff = random.choice(['zi', 'zo', 'pr', 'pl'])
    if eff == 'zi': return clip.resized(lambda t: 1 + 0.1 * (t / d))
    if eff == 'zo': return clip.resized(lambda t: 1.1 - 0.1 * (t / d))
    if eff == 'pr': return clip.with_position(lambda t: (-(t / d) * w * 0.05, 0))
    return clip.with_position(lambda t: ((t / d) * w * 0.05, 0))

@app.post("/generate-ghibli-video")
async def generate_video(request: VideoRequest):
    start_time = time.time()
    try:
        video_id = str(uuid.uuid4())[:8]
        final_clips = []
        BASE_MEDIA_PATH = os.path.join(os.getcwd(), "images")
        MUSIC_PATH = os.path.join(os.getcwd(), "bg_music.mp3")
        
        images = [f for f in os.listdir(BASE_MEDIA_PATH) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        images.sort(key=lambda x: [int(c) if c.isdigit() else c for c in re.split(r'(\d+)', x)])

        for i, scene in enumerate(request.scenes):
            print(f"🎬 Processing Scene {i+1}/{len(request.scenes)}")
            clean_text = sanitize_text_for_tts(scene.text)
            
            # Audio
            audio_path = f"t_{video_id}_{i}.wav"
            samples, sr = kokoro.create(clean_text, voice=request.voice, speed=1.0, lang="en-us")
            sf.write(audio_path, samples, sr)
            a_clip = AudioFileClip(audio_path)
            
            # Word Timestamps
            words = get_word_timestamps(audio_path)
            
            # Image Base
            media_file = images[i % len(images)] if scene.media_name == "detect" else scene.media_name
            media_path = os.path.join(BASE_MEDIA_PATH, media_file)
            
            tw = 720 if request.orientation == "portrait" else 1280
            th = 1280 if request.orientation == "portrait" else 720
            
            if os.path.exists(media_path):
                img = ImageClip(media_path).with_duration(a_clip.duration)
                sc = max(tw / img.w, th / img.h)
                img = img.resized(width=int(img.w * sc), height=int(img.h * sc))
                img = img.cropped(x_center=img.w/2, y_center=img.h/2, width=tw, height=th)
            else:
                img = ColorClip(size=(tw, th), color=(30,30,30)).with_duration(a_clip.duration)

            if request.add_effects: img = apply_effects(img)
            
            # Captions
            if request.add_captions:
                caps = create_dynamic_captions(words, (tw, th), caption_position=request.caption_position)
                if caps:
                    img = CompositeVideoClip([img] + caps, size=(tw, th))
            
            final_clips.append(img.with_audio(a_clip))
            gc.collect()

        # Concatenate & Music
        final_video = concatenate_videoclips(final_clips, method="compose")
        if os.path.exists(MUSIC_PATH):
            bg = AudioFileClip(MUSIC_PATH).with_effects([afx.AudioLoop(duration=final_video.duration)]).with_volume_scaled(0.12)
            final_video = final_video.with_audio(CompositeAudioClip([final_video.audio, bg]))

        output = f"Ghibli_Story_{video_id}.mp4"
        final_video.write_videofile(
            output, fps=24, codec="libx264", audio_codec="aac",
            threads=1, preset="ultrafast"
        )

        for f in glob.glob(f"t_{video_id}_*.wav"):
            try: os.remove(f)
            except: pass
            
        return {"status": "success", "video_path": os.path.abspath(output)}
    except Exception as e:
        print(f"FATAL: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
