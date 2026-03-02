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
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File
import shutil
from pydantic import BaseModel
#from kokoro import KPipeline
from kokoro_onnx import Kokoro
from moviepy import (
    ImageClip, VideoFileClip, concatenate_videoclips, AudioFileClip,
    TextClip, CompositeVideoClip, ColorClip, vfx, CompositeAudioClip, afx
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import platform

# Set the ImageMagick path based on OS
if platform.system() == "Windows":
    os.environ["IMAGEMAGICK_BINARY"] = r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe"
    FONT = r'C:\Windows\Fonts\arialbd.ttf'
else:
    # Linux / Docker
    os.environ["IMAGEMAGICK_BINARY"] = "/usr/bin/convert"
    FONT = '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf'

# In-memory job storage (Resets on restart)
jobs = {}

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve generated videos statically (so the UI can play them)
app.mount("/videos", StaticFiles(directory="."), name="videos")

# Image Directories
UPLOAD_DIR = "temp_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs("images", exist_ok=True)

# Mount media folders for the UI to preview
app.mount("/static/images", StaticFiles(directory="images"), name="static_images")
app.mount("/static/uploads", StaticFiles(directory=UPLOAD_DIR), name="static_uploads")

@app.post("/upload-image")
async def upload_image(file: UploadFile = File(...)):
    # Support images and videos
    exts = ('.png', '.jpg', '.jpeg', '.mp4', '.mov', '.avi', '.webm')
    if not file.filename.lower().endswith(exts):
        raise HTTPException(status_code=400, detail="Unsupported file type")
        
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"filename": file.filename, "url": f"/static/uploads/{file.filename}"}

@app.get("/list-images")
async def list_images():
    def get_files(folder, path_prefix):
        exts = ('.png', '.jpg', '.jpeg', '.mp4', '.mov', '.avi', '.webm')
        return [{"name": f, "url": f"{path_prefix}/{f}", "type": "video" if f.lower().endswith(('.mp4', '.mov', '.avi', '.webm')) else "image"} 
                for f in os.listdir(folder) if f.lower().endswith(exts)]
    
    return {
        "default": get_files("images", "/static/images"),
        "uploads": get_files(UPLOAD_DIR, "/static/uploads")
    }

# Initialize Whisper (Tiny is fastest for CPU)
whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")

def ensure_models():
    models = {
        "kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
        "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
    }
    for name, url in models.items():
        if not os.path.exists(name):
            print(f"📥 {name} not found. Downloading...")
            import urllib.request
            try:
                urllib.request.urlretrieve(url, name)
                print(f"✅ Successfully downloaded {name}")
            except Exception as e:
                print(f"❌ Failed to download {name}: {e}")

# Initialize the Kokoro Pipeline
ensure_models()
kokoro = Kokoro("kokoro-v1.0.onnx", "voices-v1.0.bin") 

class Scene(BaseModel):
    text: str
    media_name: str 

class VideoRequest(BaseModel):
    scenes: list[Scene]
    voice: str = "af_bella"
    add_captions: bool = True
    add_effects: bool = True
    caption_position: str = "bottom"  # options: "bottom", "center", "top"
    orientation: str = "portrait"  # "portrait" or "landscape"

def sanitize_text_for_tts(text):
    if not text: return "..."
    text = text.replace("[sigh]", " haaaahhh... ").replace("[pause]", " . . . ")
    text = text.encode("ascii", "ignore").decode()
    text = text.replace("...", ".").replace("—", "-").replace("–", "-")
    
    replacements = {
         'Aiko': 'Eye-ko', 
         'Haru': 'Ha-roo', 
         'Yuki': 'You-kee', 
         'Elara': 'Eh-lah-rah', 
         'Midasis': 'Mih-dah-sis', 
         'cicadas': 'si-kay-dahs'
    }
    
    text = text.replace('"', '').replace("'", "")
    for original, replacement in replacements.items():
        regEx = re.compile(re.escape(original), re.IGNORECASE)
        text = regEx.sub(replacement, text)
    return text.strip()

def get_word_timestamps(audio_path, script_text=None):
    import difflib
    script_vocab = {}
    if script_text:
        for word in re.findall(r"[\w']+", script_text):
            script_vocab[word.lower()] = word

    def correct_word(whisper_word):
        cleaned = whisper_word.strip(".,!?;:-\"'")
        key = cleaned.lower()
        if not script_vocab or key in script_vocab:
            return script_vocab.get(key, whisper_word)
        matches = difflib.get_close_matches(key, script_vocab.keys(), n=1, cutoff=0.65)
        if matches:
            return script_vocab[matches[0]]
        return whisper_word

    segments, _ = whisper_model.transcribe(audio_path, word_timestamps=True)
    words_list = []
    for segment in segments:
        for word in segment.words:
            w = word.word.strip()
            if w:
                words_list.append({
                    "word": correct_word(w),
                    "start": word.start,
                    "end": word.end
                })
    return words_list

def create_dynamic_captions(words, clip_size, caption_position="bottom"):
    if not words:
        return []

    word_clips = []
    w, h = clip_size
    position_map = {"bottom": h * 0.78, "center": h * 0.50, "top": h * 0.15}
    y_pos = position_map.get(caption_position, h * 0.78)

    GAP = 10
    GROUP_SIZE = 4 if w > 1000 else 2
    MAX_WIDTH = int(w * 0.90)

    groups = []
    i = 0
    while i < len(words):
        groups.append(words[i:i + GROUP_SIZE])
        i += GROUP_SIZE

    for group_idx, group in enumerate(groups):
        try:
            font_size = 72
            margin = (20, 20)
            measured = []
            for attempt in range(5):
                measured = []
                for word_obj in group:
                    txt = word_obj['word'].upper()
                    m = TextClip(text=txt, font=FONT, font_size=font_size, stroke_color='black', stroke_width=4, method='label', margin=margin)
                    measured.append({'txt': txt, 'obj': word_obj, 'w': int(m.w), 'h': int(m.h)})
                    m.close()

                total_w = sum(m['w'] for m in measured) + GAP * (len(measured) - 1)
                if total_w <= MAX_WIDTH: break
                font_size = max(36, int(font_size * 0.88))
                margin = (15, 15)

            total_w = sum(m['w'] for m in measured) + GAP * (len(measured) - 1)
            curr_x = (w - total_w) // 2
            for m in measured:
                m['x'] = int(curr_x)
                m['y'] = int(y_pos - m['h'] // 2)
                curr_x += m['w'] + GAP

            measured = [m for m in measured if m['x'] + m['w'] > 0 and m['x'] < w]
            if not measured: continue

            if group_idx + 1 < len(groups): group_end = groups[group_idx + 1][0]['start']
            else: group_end = measured[-1]['obj']['end']

            for active_idx, active_item in enumerate(measured):
                seg_start = active_item['obj']['start']
                if active_idx + 1 < len(measured): seg_end = measured[active_idx + 1]['obj']['start']
                else: seg_end = group_end
                seg_dur = max(0.05, seg_end - seg_start)

                for j, m in enumerate(measured):
                    is_active = (j == active_idx)
                    try:
                        t = TextClip(
                            text=m['txt'], font=FONT, font_size=font_size,
                            color='yellow' if is_active else '#AAAAAA',
                            stroke_color='black', stroke_width=4 if is_active else 2,
                            method='label', margin=margin
                        )
                        if m['x'] + int(t.w) <= 0 or m['x'] >= w:
                            t.close()
                            continue
                        word_clips.append(t.with_position((m['x'], m['y'])).with_start(seg_start).with_duration(seg_dur))
                    except: continue
        except: continue
    return word_clips

def apply_pan_zoom_effect(clip):
    w, h = clip.size
    duration = clip.duration
    effect = random.choice(['zoom_in', 'zoom_out', 'pan_right', 'pan_left'])
    if effect == 'zoom_in': return clip.resized(lambda t: 1 + 0.15 * (t / duration))
    if effect == 'zoom_out': return clip.resized(lambda t: 1.15 - 0.15 * (t / duration))
    if effect == 'pan_right': return clip.with_position(lambda t: (-(t / duration) * w * 0.1, 0))
    return clip.with_position(lambda t: ((t / duration) * w * 0.1, 0))

def auto_detect_images(images_folder, num_scenes):
    def natural_keys(text): return [int(c) if c.isdigit() else c for c in re.split(r'(\d+)', text)]
    try:
        files = [f for f in os.listdir(images_folder) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        files.sort(key=natural_keys)
        return files[:num_scenes]
    except: return []

def generate_video_task(job_id: str, request: VideoRequest):
    try:
        jobs[job_id]["status"] = "processing"
        final_clips = []
        MUSIC_PATH = os.path.join(os.getcwd(), "bg_music.mp3")
        BASE_MEDIA_PATH = os.path.join(os.getcwd(), "images")
        
        print(f"\n🎬 Job {job_id}: Generation Started.")
        auto_detected_images = auto_detect_images(BASE_MEDIA_PATH, len(request.scenes))

        for i, scene in enumerate(request.scenes, 1):
            clean_text = sanitize_text_for_tts(scene.text)
            media_file = auto_detected_images[i-1] if (scene.media_name == "detect" and i-1 < len(auto_detected_images)) else scene.media_name

            audio_path = f"temp_{job_id}_{i}.wav"
            try:
                samples, sample_rate = kokoro.create(clean_text, voice=request.voice, speed=1.0, lang="en-us")
                sf.write(audio_path, samples, sample_rate)
                audio_clip = AudioFileClip(audio_path)
            except Exception as e:
                audio_path = f"temp_{job_id}_{i}_silence.wav"
                sf.write(audio_path, np.zeros(int(24000 * 3)), 24000)
                audio_clip = AudioFileClip(audio_path)
             
            word_data = get_word_timestamps(audio_path, script_text=scene.text)
            
            # Find the media file in either 'images' or 'temp_uploads'
            media_path = None
            if media_file:
                # Check default images folder
                p1 = os.path.join(BASE_MEDIA_PATH, media_file)
                # Check temp uploads folder
                p2 = os.path.join(UPLOAD_DIR, media_file)
                
                if os.path.exists(p1):
                    media_path = p1
                elif os.path.exists(p2):
                    media_path = p2

            TARGET_W = 720 if request.orientation == "portrait" else 1280
            TARGET_H = 1280 if request.orientation == "portrait" else 720

            if not media_path or not os.path.exists(media_path):
                clip = ColorClip(size=(TARGET_W, TARGET_H), color=(30, 30, 30)).with_duration(audio_clip.duration)
            else:
                is_video = media_file.lower().endswith(('.mp4', '.mov', '.avi', '.webm'))
                if is_video:
                    clip = VideoFileClip(media_path).without_audio()
                    # Loop video if shorter than audio
                    if clip.duration < audio_clip.duration:
                        clip = clip.with_effects([vfx.Loop(duration=audio_clip.duration)])
                    else:
                        clip = clip.with_duration(audio_clip.duration)
                else:
                    clip = ImageClip(media_path).with_duration(audio_clip.duration)
                
                scale = max(TARGET_W / clip.w, TARGET_H / clip.h)
                clip = clip.resized(width=int(clip.w * scale), height=int(clip.h * scale))
                clip = clip.cropped(x_center=clip.w / 2, y_center=clip.h / 2, width=TARGET_W, height=TARGET_H)

            # Only apply pan/zoom to images, not videos
            if request.add_effects and not media_file.lower().endswith(('.mp4', '.mov', '.avi', '.webm')):
                clip = apply_pan_zoom_effect(clip).cropped(x_center=TARGET_W/2, y_center=TARGET_H/2, width=TARGET_W, height=TARGET_H)

            if request.add_captions:
                word_clips = create_dynamic_captions(word_data, (clip.w, clip.h), caption_position=request.caption_position)
                if word_clips: clip = CompositeVideoClip([clip] + word_clips)

            final_clips.append(clip.with_audio(audio_clip))
            gc.collect()
            
        if request.add_effects and len(final_clips) > 1:
            transitioned = [final_clips[0]]
            for i in range(1, len(final_clips)):
                transitioned.append(final_clips[i].with_effects([vfx.FadeIn(duration=0.6)]))
            final_clips = transitioned

        final_video = concatenate_videoclips(final_clips, method="compose")
        if os.path.exists(MUSIC_PATH):
            bg_music = AudioFileClip(MUSIC_PATH).with_effects([afx.AudioLoop(duration=final_video.duration)])
            bg_music = bg_music.with_volume_scaled(0.12)
            final_video = final_video.with_audio(CompositeAudioClip([final_video.audio, bg_music]))

        output_name = f"Ghibli_Story_{job_id}.mp4"
        final_video.write_videofile(
            output_name, fps=24, codec="libx264", audio_codec="aac", 
            threads=1, temp_audiofile=f"temp-audio-{job_id}.m4a",
            remove_temp=True, preset="ultrafast", logger=None
        )

        for f in glob.glob(f"temp_{job_id}_*.wav"):
            try: os.remove(f)
            except: pass
        
        jobs[job_id]["status"] = "success"
        jobs[job_id]["video_path"] = os.path.abspath(output_name)
        jobs[job_id]["filename"] = output_name
        print(f"✅ Job {job_id} Complete!")
        
    except Exception as e:
        print(f"❌ ERROR in Job {job_id}: {e}")
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)

@app.post("/generate-ghibli-video")
async def generate_video(request: VideoRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {"status": "pending", "started_at": time.time()}
    background_tasks.add_task(generate_video_task, job_id, request)
    return {"status": "accepted", "job_id": job_id, "message": "Video generation started in background"}

@app.get("/video-status/{job_id}")
async def get_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    response = jobs[job_id].copy()
    if response["status"] in ["processing", "pending"]:
        response["elapsed_seconds"] = round(time.time() - response["started_at"], 2)
    return response

@app.get("/")
async def serve_ui():
    return FileResponse("index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)