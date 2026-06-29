import os
from dotenv import load_dotenv

load_dotenv()

# OPTIMIZATION: Limit MKL/OMP threads to prevent memory fragmentation/failures on Windows
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

import re
import urllib.request
import glob
import uuid
import random
import time
import json
import numpy as np
import requests
from faster_whisper import WhisperModel
import gc
import soundfile as sf
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
import sentry_sdk
import shutil
from pydantic import BaseModel
from typing import Optional
from kokoro_onnx import Kokoro
from moviepy import (
    ImageClip, VideoFileClip, concatenate_videoclips, AudioFileClip,
    TextClip, CompositeVideoClip, ColorClip, vfx, CompositeAudioClip, afx
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import platform

# Set the ImageMagick path based on OS
if platform.system() == "Windows":
    os.environ["IMAGEMAGICK_BINARY"] = r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe"
    FONT = r'C:\Windows\Fonts\arialbd.ttf'
else:
    os.environ["IMAGEMAGICK_BINARY"] = "/usr/bin/convert"
    FONT = '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf'

# Job persistence storage
JOBS_FILE = "jobs.json"

def load_jobs():
    if os.path.exists(JOBS_FILE):
        try:
            with open(JOBS_FILE, "r") as f:
                return json.load(f)
        except: return {}
    return {}

def save_jobs():
    try:
        with open(JOBS_FILE, "w") as f:
            json.dump(jobs, f, indent=4)
    except: pass

jobs = load_jobs()

# ---------------------------------------------------------------------------
# Job Queue — controls how many renders run simultaneously
# ---------------------------------------------------------------------------
# ✏️  Change this number to allow more concurrent renders.
# Rule of thumb: start at 1, raise to 2 only if Task Manager shows < 70% RAM usage.
MAX_CONCURRENT_RENDERS: int = 1
# Maximum active/queued jobs allowed per user IP address to prevent spam
MAX_JOBS_PER_IP: int = 3

import queue as _queue
import threading as _threading

_job_queue: _queue.Queue = _queue.Queue()   # holds (job_id, VideoRequest) tuples
_active_jobs: list = []                      # job_ids currently being rendered
_queue_lock = _threading.Lock()


def _worker_loop():
    """Worker thread: pull jobs from queue and render them one at a time."""
    while True:
        job_id, request = _job_queue.get()   # blocks until a job is available
        try:
            with _queue_lock:
                _active_jobs.append(job_id)
            jobs[job_id]["status"] = "processing"
            save_jobs()
            generate_video_task(job_id, request)
        finally:
            with _queue_lock:
                if job_id in _active_jobs:
                    _active_jobs.remove(job_id)
            _job_queue.task_done()


# Start exactly MAX_CONCURRENT_RENDERS worker threads
for _ in range(MAX_CONCURRENT_RENDERS):
    _t = _threading.Thread(target=_worker_loop, daemon=True)
    _t.start()


def _enqueue_job(job_id: str, request) -> int:
    """Add a job to the queue and return its queue position (1-indexed)."""
    _job_queue.put((job_id, request))
    return _job_queue.qsize()   # items still waiting (not yet picked up by a worker)


def _queue_position(job_id: str) -> int | None:
    """Return 1-indexed queue position for a queued job, or None if not queued."""
    with _job_queue.mutex:
        items = list(_job_queue.queue)
    for idx, (jid, _) in enumerate(items):
        if jid == job_id:
            return idx + 1   # 1 = next to be picked up
    return None


sentry_dsn = os.getenv("SENTRY_DSN")
if sentry_dsn:
   # pass
     sentry_sdk.init(
         dsn=sentry_dsn,
         traces_sample_rate=1.0,
         profiles_sample_rate=1.0,
     )

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve generated videos statically
# app.mount("/videos", #StaticFiles(directory="."), name="videos")

# Directories
#UPLOAD_DIR = "temp_uploads"


# Directories

UPLOAD_DIR = "temp_uploads"

os.makedirs(UPLOAD_DIR, exist_ok=True)



# Serve generated videos statically

app.mount("/videos", StaticFiles(directory=UPLOAD_DIR), name="videos")



MUSIC_UPLOAD_DIR = "uploaded_music"
VOICEOVER_UPLOAD_DIR = "uploaded_voiceovers"
CHECKPOINT_DIR = "job_checkpoints"

for d in [UPLOAD_DIR, MUSIC_UPLOAD_DIR, VOICEOVER_UPLOAD_DIR, "images", CHECKPOINT_DIR]:
    os.makedirs(d, exist_ok=True)

# Mount media folders
app.mount("/static/images", StaticFiles(directory="images"), name="static_images")
app.mount("/static/uploads", StaticFiles(directory=UPLOAD_DIR), name="static_uploads")
app.mount("/static/music", StaticFiles(directory=MUSIC_UPLOAD_DIR), name="static_music")


@app.post("/upload-image")
async def upload_image(file: UploadFile = File(...)):
    exts = ('.png', '.jpg', '.jpeg', '.mp4', '.mov', '.avi', '.webm')
    if not file.filename.lower().endswith(exts):
        raise HTTPException(status_code=400, detail="Unsupported file type")
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"filename": file.filename, "url": f"/static/uploads/{file.filename}"}


@app.post("/upload-music")
async def upload_music(file: UploadFile = File(...)):
    """Upload a custom background music file."""
    exts = ('.mp3', '.wav', '.ogg', '.m4a', '.aac')
    if not file.filename.lower().endswith(exts):
        raise HTTPException(status_code=400, detail="Unsupported audio type. Use mp3, wav, ogg, m4a, or aac.")
    file_path = os.path.join(MUSIC_UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"filename": file.filename, "url": f"/static/music/{file.filename}"}


@app.post("/upload-voiceover")
async def upload_voiceover(file: UploadFile = File(...)):
    """Upload a custom voiceover audio file."""
    exts = ('.mp3', '.wav', '.ogg', '.m4a', '.aac')
    if not file.filename.lower().endswith(exts):
        raise HTTPException(status_code=400, detail="Unsupported audio type.")
    # Use a unique name to avoid collisions
    unique_name = f"vo_{uuid.uuid4().hex[:8]}_{file.filename}"
    file_path = os.path.join(VOICEOVER_UPLOAD_DIR, unique_name)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"filename": unique_name, "url": f"/uploaded_voiceovers/{unique_name}"}

# Mount voiceover dir too
app.mount("/uploaded_voiceovers", StaticFiles(directory=VOICEOVER_UPLOAD_DIR), name="uploaded_voiceovers")


@app.get("/list-images")
async def list_images():
    def get_files(folder, path_prefix):
        exts = ('.png', '.jpg', '.jpeg', '.mp4', '.mov', '.avi', '.webm')
        files = []
        for f in sorted(os.listdir(folder)):
            if f.lower().endswith(exts):
                files.append({
                    "name": f,
                    "url": f"{path_prefix}/{f}",
                    "type": "video" if f.lower().endswith(('.mp4', '.mov', '.avi', '.webm')) else "image"
                })
        return files

    return {
        "default": get_files("images", "/static/images"),
        "uploads": get_files(UPLOAD_DIR, "/static/uploads")
    }


@app.get("/list-music")
async def list_music():
    """List all available background music files."""
    exts = ('.mp3', '.wav', '.ogg', '.m4a', '.aac')
    files = []
    # Include bundled default music
    for f in ["bg_music.mp3", "bg_music2.mp3"]:
        if os.path.exists(f):
            files.append({"name": f, "url": f"/static_root/{f}", "source": "default"})
    # Include uploaded music
    for f in sorted(os.listdir(MUSIC_UPLOAD_DIR)):
        if f.lower().endswith(exts):
            files.append({"name": f, "url": f"/static/music/{f}", "source": "uploaded"})
    return {"music": files}

# Serve root directory files (for default bg_music.mp3 access)
app.mount("/static_root", StaticFiles(directory="."), name="static_root")


# Initialize Whisper
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


ensure_models()
kokoro = Kokoro("kokoro-v1.0.onnx", "voices-v1.0.bin")


class Scene(BaseModel):
    text: str
    media_name: str


class VideoRequest(BaseModel):
    scenes: list[Scene]
    voice: str = "af_bella"

    # Voiceover settings
    generate_voiceover: bool = True        # If False, no TTS is generated
    uploaded_voiceover: Optional[str] = None  # filename of an already-uploaded voiceover in uploaded_voiceovers/
    voiceover_url: Optional[str] = None       # Remote URL to a voiceover audio file — auto-downloaded on job start

    # Caption settings
    add_captions: bool = True
    caption_position: str = "bottom"       # "bottom", "center", "top"

    # Background music settings
    add_background_music: bool = True
    bg_music_file: Optional[str] = None    # filename from uploaded_music dir, or "bg_music.mp3" / "bg_music2.mp3"
    bg_music_url: Optional[str] = None     # Remote URL to a music file — auto-downloaded on job start
    bg_music_volume: float = 0.12          # 0.0 to 1.0

    # Video clip settings
    clip_duration_mode: str = "full"       # "full" = use video's original duration, "fixed" = 4 seconds per scene
    keep_clip_audio: bool = False          # Whether to preserve original video clip audio
    clip_audio_volume: float = 0.4         # Volume of the original clip audio (0.0 to 1.0)

    # Visual settings
    add_effects: bool = True
    orientation: str = "portrait"          # "portrait" or "landscape"
    job_id: Optional[str] = None           # For resuming a completed job

    # Webhook integration
    webhook_url: Optional[str] = None      # URL to ping when job completes (or fails)
    progress_webhook_url: Optional[str] = None # URL to ping with progress updates


def sanitize_text_for_tts(text):
    if not text: return "..."
    text = text.replace("[sigh]", " haaaahhh... ").replace("[pause]", " . . . ")
    text = text.encode("ascii", "ignore").decode()
    text = text.replace("...", ".").replace("—", "-").replace("–", "-")
    replacements = {
        'Aiko': 'Eye-ko', 'Haru': 'Ha-roo', 'Yuki': 'You-kee',
        'Elara': 'Eh-lah-rah', 'Midasis': 'Mih-dah-sis', 'cicadas': 'si-kay-dahs'
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
                words_list.append({"word": correct_word(w), "start": word.start, "end": word.end})
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
        files = [f for f in os.listdir(images_folder) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.mp4', '.mov', '.avi', '.webm'))]
        files.sort(key=natural_keys)
        return files[:num_scenes]
    except: return []


# ---------------------------------------------------------------------------
# Temp-file cleanup helpers
# ---------------------------------------------------------------------------

def cleanup_job_wavs(job_id: str):
    """Delete all temporary WAV files for a given job."""
    patterns = [
        f"temp_{job_id}_*.wav",
    ]
    deleted = []
    for pattern in patterns:
        for f in glob.glob(pattern):
            try:
                os.remove(f)
                deleted.append(f)
            except Exception as e:
                print(f"⚠️ Could not delete {f}: {e}")
    if deleted:
        print(f"🧹 Cleaned {len(deleted)} WAV file(s) for job {job_id}")
    return deleted


def _background_cleanup_loop():
    """Daemon thread: every 30 min, delete WAVs for failed/old jobs."""
    FAILED_JOB_WAV_MAX_AGE_HOURS = 4
    SUCCESS_CHECKPOINT_MAX_AGE_DAYS = 7
    while True:
        time.sleep(30 * 60)  # wait 30 minutes between sweeps
        try:
            now = time.time()
            for job_id, info in list(jobs.items()):
                status = info.get("status", "")
                started_at = info.get("started_at", now)
                age_hours = (now - started_at) / 3600

                # Clean WAVs for failed jobs older than 4 hours
                if status == "failed" and age_hours > FAILED_JOB_WAV_MAX_AGE_HOURS:
                    print(f"🕐 Auto-cleanup: WAVs for failed job {job_id} ({age_hours:.1f}h old)")
                    cleanup_job_wavs(job_id)

                # Clean WAVs for successful jobs (audio already baked into checkpoints)
                if status == "success":
                    cleanup_job_wavs(job_id)

                # Clean checkpoint files for jobs older than 7 days
                age_days = age_hours / 24
                if age_days > SUCCESS_CHECKPOINT_MAX_AGE_DAYS:
                    for cp in glob.glob(os.path.join(CHECKPOINT_DIR, f"cp_{job_id}_scene_*.mp4")):
                        try:
                            os.remove(cp)
                            print(f"🗑️ Removed old checkpoint: {cp}")
                        except: pass
        except Exception as e:
            print(f"⚠️ Background cleanup error: {e}")


def _send_webhook(job_id: str, status: str, message: str, filename: str = None, thumbnail_name: str = None):
    """Sends a fire-and-forget webhook to the user's provided URL."""
    webhook_url = jobs[job_id].get("webhook_url")
    if not webhook_url:
        return

    payload = {
        "job_id": job_id,
        "status": status,
        "message": message,
        "filename": filename
    }
    
    # If we know the server's base URL, provide a fully-qualified direct download link
    base_url = jobs[job_id].get("base_url")
    if base_url and filename:
        # e.g., https://my-app.railway.app/videos/Story_Final_abc123.mp4
        payload["video_url"] = f"{base_url.rstrip('/')}/videos/{filename}"
        if thumbnail_name:
            payload["thumbnail_url"] = f"{base_url.rstrip('/')}/videos/{thumbnail_name}"
    
    # Run in a separate thread so it doesn't block cleanup
    def fire():
        try:
            print(f"🔔 Sending webhook for job {job_id} to {webhook_url}")
            requests.post(webhook_url, json=payload, timeout=5)
        except Exception as e:
            print(f"⚠️ Webhook failed for job {job_id}: {e}")
            
    _threading.Thread(target=fire, daemon=True).start()


def _send_progress_webhook(job_id: str, status: str, progress_percent: int, progress_message: str):
    """Sends a fire-and-forget progress webhook to the user's provided URL."""
    progress_webhook_url = jobs[job_id].get("progress_webhook_url")
    if not progress_webhook_url:
        return

    payload = {
        "job_id": job_id,
        "status": status,
        "progress_percent": progress_percent,
        "progress_message": progress_message,
        "elapsed_seconds": round(time.time() - jobs[job_id].get("started_at", time.time()), 2)
    }
    
    def fire():
        try:
            print(f"🔔 Sending progress webhook for job {job_id} to {progress_webhook_url} ({progress_percent}%)")
            requests.post(progress_webhook_url, json=payload, timeout=5)
        except Exception as e:
            print(f"⚠️ Progress webhook failed for job {job_id}: {e}")
            
    _threading.Thread(target=fire, daemon=True).start()


def _update_job_progress(job_id: str, status: str, progress_percent: int, progress_message: str, save: bool = True):
    if job_id not in jobs:
        return
    jobs[job_id]["status"] = status
    jobs[job_id]["progress_percent"] = progress_percent
    jobs[job_id]["progress_message"] = progress_message
    if save:
        save_jobs()
    _send_progress_webhook(job_id, status, progress_percent, progress_message)


# Start background cleanup daemon
import threading
_cleanup_thread = threading.Thread(target=_background_cleanup_loop, daemon=True)
_cleanup_thread.start()


def resolve_music_path(bg_music_file):
    """Find the actual path for a music file."""
    if not bg_music_file:
        # Default fallback
        for default in ["bg_music.mp3", "bg_music2.mp3"]:
            if os.path.exists(default):
                return os.path.join(os.getcwd(), default)
        return None
    # Check uploaded music dir first
    uploaded_path = os.path.join(MUSIC_UPLOAD_DIR, bg_music_file)
    if os.path.exists(uploaded_path):
        return uploaded_path
    # Check root dir for defaults
    root_path = os.path.join(os.getcwd(), bg_music_file)
    if os.path.exists(root_path):
        return root_path
    return None


# --- URL media downloader ---
URL_MEDIA_DIR = "url_media_cache"
os.makedirs(URL_MEDIA_DIR, exist_ok=True)

def download_url_media(url: str) -> str | None:
    """
    Download a remote URL to a local temp file and return the local path.
    Returns None if the download fails.
    """
    try:
        # Infer extension from URL path (default to .mp4 for videos, .jpg for images)
        from urllib.parse import urlparse
        parsed = urlparse(url)
        url_path = parsed.path
        ext = os.path.splitext(url_path)[-1].lower()
        if ext not in ('.jpg', '.jpeg', '.png', '.mp4', '.mov', '.avi', '.webm'):
            ext = '.jpg'  # safe default for unknown types
        local_name = f"url_{uuid.uuid4().hex[:10]}{ext}"
        local_path = os.path.join(URL_MEDIA_DIR, local_name)
        print(f"🌐 Downloading media from URL: {url}")
        urllib.request.urlretrieve(url, local_path)
        print(f"✅ Downloaded to: {local_path}")
        return local_path
    except Exception as e:
        print(f"⚠️ Failed to download URL media: {url} — {e}")
        return None


def generate_video_task(job_id: str, request: VideoRequest):
    try:
        jobs[job_id]["total_scenes"] = len(request.scenes)
        _update_job_progress(job_id, "processing", 5, f"Starting render of {len(request.scenes)} scenes...")

        BASE_MEDIA_PATH = os.path.join(os.getcwd(), "images")
        print(f"\n Job {job_id}: Generation Started. Total Scenes: {len(request.scenes)}")

        # --- Auto-download voiceover from URL if provided ---
        if not request.generate_voiceover and request.voiceover_url and not request.uploaded_voiceover:
            print(f"Downloading voiceover from URL: {request.voiceover_url}")
            downloaded = download_url_media(request.voiceover_url)
            if downloaded:
                # Move into uploaded_voiceovers dir so the rest of the pipeline finds it
                ext = os.path.splitext(downloaded)[-1] or ".mp3"
                unique_name = f"vo_{uuid.uuid4().hex[:8]}_remote{ext}"
                dest = os.path.join(VOICEOVER_UPLOAD_DIR, unique_name)
                shutil.move(downloaded, dest)
                # Patch the request object so downstream logic sees it as a normal upload
                request = request.model_copy(update={"uploaded_voiceover": unique_name})
                print(f"Voiceover downloaded and saved as: {unique_name}")
            else:
                print("Failed to download voiceover URL — continuing without custom voiceover.")

        # --- Auto-download background music from URL if provided ---
        if request.add_background_music and request.bg_music_url and not request.bg_music_file:
            print(f"Downloading background music from URL: {request.bg_music_url}")
            downloaded = download_url_media(request.bg_music_url)
            if downloaded:
                ext = os.path.splitext(downloaded)[-1] or ".mp3"
                unique_name = f"music_{uuid.uuid4().hex[:8]}_remote{ext}"
                dest = os.path.join(MUSIC_UPLOAD_DIR, unique_name)
                shutil.move(downloaded, dest)
                request = request.model_copy(update={"bg_music_file": unique_name})
                print(f"Music downloaded and saved as: {unique_name}")
            else:
                print("Failed to download music URL — will use default music.")

        # --- Handle single uploaded voiceover for ALL scenes ---
        single_voiceover_clip = None
        single_voiceover_duration = None
        if not request.generate_voiceover and request.uploaded_voiceover:
            vo_path = os.path.join(VOICEOVER_UPLOAD_DIR, request.uploaded_voiceover)
            if os.path.exists(vo_path):
                single_voiceover_clip = AudioFileClip(vo_path)
                single_voiceover_duration = single_voiceover_clip.duration

        auto_detected_images = auto_detect_images(BASE_MEDIA_PATH, len(request.scenes))
        scene_durations = None
        if single_voiceover_clip and single_voiceover_duration:
            per_scene = single_voiceover_duration / len(request.scenes)
            scene_durations = [per_scene] * len(request.scenes)

        # Pre-compute captions for uploaded voiceover if needed
        uploaded_vo_words_by_scene = {}
        if not request.generate_voiceover and single_voiceover_clip and request.add_captions and scene_durations:
            vo_path = os.path.join(VOICEOVER_UPLOAD_DIR, request.uploaded_voiceover)
            try:
                all_words = get_word_timestamps(vo_path)
                scene_start = 0.0
                for si, dur in enumerate(scene_durations):
                    scene_end = scene_start + dur
                    scene_words = [
                        {**w, "start": w["start"] - scene_start, "end": w["end"] - scene_start}
                        for w in all_words if scene_start <= w["start"] < scene_end
                    ]
                    uploaded_vo_words_by_scene[si] = scene_words
                    scene_start = scene_end
            except Exception as e:
                print(f"⚠️ Caption transcription failed: {e}")

        checkpoint_files = []

        for i, scene in enumerate(request.scenes, 1):
            jobs[job_id]["current_scene"] = i
            percent = int(5 + ((i - 1) / len(request.scenes)) * 80)
            _update_job_progress(job_id, "processing", percent, f"Rendering scene {i} of {len(request.scenes)}...")
            
            cp_path = os.path.join(CHECKPOINT_DIR, f"cp_{job_id}_scene_{i}.mp4")
            
            if os.path.exists(cp_path):
                print(f"⏭️ Skipping Scene {i}/{len(request.scenes)} - Checkpoint found.")
                checkpoint_files.append(cp_path)
                continue

            print(f"🎥 Processing Scene {i}/{len(request.scenes)}")
            
            # --- Determine audio duration for this scene ---
            audio_clip = None
            word_data = []

            if request.generate_voiceover:
                clean_text = sanitize_text_for_tts(scene.text)
                audio_path = f"temp_{job_id}_{i}.wav"
                try:
                    samples, sample_rate = kokoro.create(clean_text, voice=request.voice, speed=1.0, lang="en-us")
                    sf.write(audio_path, samples, sample_rate)
                    audio_clip = AudioFileClip(audio_path)
                except Exception as e:
                    print(f"⚠️ TTS failed for scene {i}: {e}")
                    audio_path = f"temp_{job_id}_{i}_silence.wav"
                    sf.write(audio_path, np.zeros(int(24000 * 3)), 24000)
                    audio_clip = AudioFileClip(audio_path)

                if request.add_captions:
                    word_data = get_word_timestamps(audio_path, script_text=scene.text)
            # --- Build visual clip (determine path and type early to influence duration) ---
            media_file = auto_detected_images[i-1] if (scene.media_name == "detect" and i-1 < len(auto_detected_images)) else scene.media_name
            media_path = None
            if media_file:
                # URL support: download remote media on-the-fly
                if media_file.startswith("http://") or media_file.startswith("https://"):
                    downloaded = download_url_media(media_file)
                    if downloaded:
                        media_path = downloaded
                        media_file = os.path.basename(downloaded)
                else:
                    p1 = os.path.join(BASE_MEDIA_PATH, media_file)
                    p2 = os.path.join(UPLOAD_DIR, media_file)
                    if os.path.exists(p1): media_path = p1
                    elif os.path.exists(p2): media_path = p2

            is_video_clip = media_file and media_file.lower().endswith(('.mp4', '.mov', '.avi', '.webm')) if media_file else False
            raw_clip = None
            if is_video_clip and media_path and os.path.exists(media_path):
                try:
                    raw_clip = VideoFileClip(media_path)
                except Exception as e:
                    print(f"⚠️ Failed to load VideoFileClip for {media_path}: {e}")
                    is_video_clip = False

            # --- Determine audio duration for this scene ---
            audio_clip = None
            word_data = []

            if request.generate_voiceover:
                clean_text = sanitize_text_for_tts(scene.text)
                audio_path = f"temp_{job_id}_{i}.wav"
                try:
                    samples, sample_rate = kokoro.create(clean_text, voice=request.voice, speed=1.0, lang="en-us")
                    sf.write(audio_path, samples, sample_rate)
                    audio_clip = AudioFileClip(audio_path)
                except Exception as e:
                    print(f"⚠️ TTS failed for scene {i}: {e}")
                    audio_path = f"temp_{job_id}_{i}_silence.wav"
                    sf.write(audio_path, np.zeros(int(24000 * 3)), 24000)
                    audio_clip = AudioFileClip(audio_path)

                if request.add_captions:
                    word_data = get_word_timestamps(audio_path, script_text=scene.text)
            elif single_voiceover_clip and scene_durations:
                if request.add_captions:
                    word_data = uploaded_vo_words_by_scene.get(i - 1, [])

            # Override/determine scene duration
            if audio_clip:
                scene_dur = audio_clip.duration
            elif single_voiceover_clip and scene_durations:
                scene_dur = scene_durations[i-1]
            elif is_video_clip and raw_clip:
                # "full" = use the video's real length; "fixed" = cap at 4s
                if request.clip_duration_mode == "full":
                    scene_dur = raw_clip.duration
                else:
                    scene_dur = 4.0
            else:
                scene_dur = 4.0

            # Determine whether to preserve clip audio
            keep_clip_audio = request.keep_clip_audio
            if not request.generate_voiceover and not request.uploaded_voiceover and not request.voiceover_url:
                keep_clip_audio = True

            TARGET_W = 720 if request.orientation == "portrait" else 1280
            TARGET_H = 1280 if request.orientation == "portrait" else 720

            scene_clip = None
            if not media_path or not os.path.exists(media_path):
                scene_clip = ColorClip(size=(TARGET_W, TARGET_H), color=(30, 30, 30)).with_duration(scene_dur)
            else:
                if is_video_clip and raw_clip:
                    clip_audio_orig = raw_clip.audio if (keep_clip_audio and raw_clip.audio) else None
                    scene_clip = raw_clip.without_audio()
                    if scene_clip.duration < scene_dur:
                        scene_clip = scene_clip.with_effects([vfx.Loop(duration=scene_dur)])
                    else:
                        scene_clip = scene_clip.with_duration(scene_dur)
                        
                    if clip_audio_orig:
                        if clip_audio_orig.duration < scene_dur:
                            clip_audio_orig = clip_audio_orig.with_effects([afx.AudioLoop(duration=scene_dur)])
                        else:
                            clip_audio_orig = clip_audio_orig.with_duration(scene_dur)

                    if (request.add_captions and not word_data and not request.generate_voiceover and not single_voiceover_clip and raw_clip.audio):
                        try:
                            cap_audio_path = f"temp_{job_id}_{i}_caps.wav"
                            raw_clip.audio.write_audiofile(cap_audio_path, logger=None)
                            word_data = get_word_timestamps(cap_audio_path)
                            os.remove(cap_audio_path)
                        except: pass
                else:
                    scene_clip = ImageClip(media_path).with_duration(scene_dur)
                    clip_audio_orig = None

                scale = max(TARGET_W / scene_clip.w, TARGET_H / scene_clip.h)
                scene_clip = scene_clip.resized(width=int(scene_clip.w * scale), height=int(scene_clip.h * scale))
                scene_clip = scene_clip.cropped(x_center=scene_clip.w / 2, y_center=scene_clip.h / 2, width=TARGET_W, height=TARGET_H)

            if request.add_effects and not is_video_clip:
                scene_clip = apply_pan_zoom_effect(scene_clip).cropped(x_center=TARGET_W/2, y_center=TARGET_H/2, width=TARGET_W, height=TARGET_H)

            if request.add_captions and word_data:
                word_clips = create_dynamic_captions(word_data, (scene_clip.w, scene_clip.h), caption_position=request.caption_position)
                if word_clips:
                    scene_clip = CompositeVideoClip([scene_clip] + word_clips)

            if audio_clip:
                if is_video_clip and request.keep_clip_audio and clip_audio_orig:
                    mixed = CompositeAudioClip([audio_clip, clip_audio_orig.with_volume_scaled(request.clip_audio_volume)])
                    scene_clip = scene_clip.with_audio(mixed)
                else:
                    scene_clip = scene_clip.with_audio(audio_clip)
            elif is_video_clip and request.keep_clip_audio and clip_audio_orig:
                scene_clip = scene_clip.with_audio(clip_audio_orig.with_volume_scaled(request.clip_audio_volume))

            # RENDER SCENE CHECKPOINT
            scene_clip.write_videofile(
                cp_path, fps=24, codec="libx264", audio_codec="aac",
                threads=1, logger=None, preset="ultrafast" # Threads=1 for memory stability
            )
            
            # Explicit cleanup
            scene_clip.close()
            if audio_clip: audio_clip.close()
            if 'clip_audio_orig' in locals() and clip_audio_orig: clip_audio_orig.close()
            if raw_clip: raw_clip.close()

            checkpoint_files.append(cp_path)

            # ✅ Immediately delete this scene's WAV — audio is now baked into the checkpoint
            for wav_candidate in [
                f"temp_{job_id}_{i}.wav",
                f"temp_{job_id}_{i}_silence.wav",
            ]:
                if os.path.exists(wav_candidate):
                    try:
                        os.remove(wav_candidate)
                        print(f"🧹 Deleted temp WAV: {wav_candidate}")
                    except Exception as e:
                        print(f"⚠️ Could not delete {wav_candidate}: {e}")

            gc.collect()

        # --- FINAL ASSEMBLY ---
        _update_job_progress(job_id, "assembling", 90, "Assembling scenes and baking audio...")
        print(f"🔗 Assembling Scenes for Job {job_id}...")
        
        # Small delay to ensure all file handles are released by the OS
        time.sleep(2)
        
        final_clips = [VideoFileClip(f) for f in checkpoint_files]
        if request.add_effects and len(final_clips) > 1:
            for k in range(1, len(final_clips)):
                # Only fade in if it's not the first clip
                final_clips[k] = final_clips[k].with_effects([vfx.FadeIn(duration=0.6)])
        
        # Use method="compose" which is more robust for heterogeneous audio/video clips
        final_video = concatenate_videoclips(final_clips, method="compose")

        # Handle globally uploaded voiceover if present
        if single_voiceover_clip and not request.generate_voiceover:
            vo = single_voiceover_clip
            vo = vo.with_duration(min(vo.duration, final_video.duration))
            final_video = final_video.with_duration(vo.duration)
            layers = [vo]
            if final_video.audio and request.keep_clip_audio:
                layers.append(final_video.audio.with_volume_scaled(request.clip_audio_volume))
            final_video = final_video.with_audio(CompositeAudioClip(layers))

        if request.add_background_music:
            m_path = resolve_music_path(request.bg_music_file)
            if m_path:
                bgm = AudioFileClip(m_path).with_effects([afx.AudioLoop(duration=final_video.duration)])
                bgm = bgm.with_volume_scaled(request.bg_music_volume)
                final_video = final_video.with_audio(CompositeAudioClip([final_video.audio, bgm]) if final_video.audio else bgm)

        output_name = f"Story_Final_{job_id}.mp4"
        thumbnail_name = f"Thumbnail_{job_id}.jpg"
        output_path = os.path.join(UPLOAD_DIR, output_name)
        
        final_video.write_videofile(
            output_path, fps=24, codec="libx264", audio_codec="aac",
            threads=max(1, os.cpu_count() // 2), preset="fast", logger="bar"
        )

        try:
            # Extract a frame as a thumbnail (at 2 seconds or middle of video)
            t_thumb = min(2.0, final_video.duration / 2)
            final_video.save_frame(os.path.join(UPLOAD_DIR, thumbnail_name), t=t_thumb)
        except Exception as e:
            print(f"⚠️ Thumbnail generation failed: {e}")
            thumbnail_name = None

        # Cleanup
        final_video.close()
        for c in final_clips: c.close()
        if single_voiceover_clip: single_voiceover_clip.close()
        
        # Keep checkpoints for a bit, or move to successful jobs
        jobs[job_id]["filename"] = output_name
        jobs[job_id]["thumbnail"] = thumbnail_name
        _update_job_progress(job_id, "success", 100, "Complete!")
        print(f"✅ Job {job_id} Complete!")
        
        # Fire webhook!
        _send_webhook(job_id, "success", "Video rendered successfully.", output_name, thumbnail_name)

    except Exception as e:
        import traceback
        traceback.print_exc()
        jobs[job_id]["error"] = str(e)
        _update_job_progress(job_id, "failed", -1, f"Failed: {str(e)}")
        
        # Fire webhook!
        _send_webhook(job_id, "failed", f"Render failed: {str(e)}")


@app.post("/generate-video")
async def generate_video(request: VideoRequest, req: Request):
    client_ip = req.client.host if req.client else "unknown"
    
    # 1. Rate Limiting Check
    active_count = sum(
        1 for j in jobs.values() 
        if j.get("client_ip") == client_ip 
        and j.get("status") in ("queued", "processing", "assembling", "pending")
    )
    
    if active_count >= MAX_JOBS_PER_IP:
        raise HTTPException(
            status_code=429, 
            detail=f"Rate limit exceeded. You already have {active_count} jobs running or queued. Please wait for them to finish."
        )

    # 2. Add to Queue
    job_id = request.job_id
    if not job_id or job_id not in jobs:
        job_id = str(uuid.uuid4())[:8]
        jobs[job_id] = {
            "status": "queued", 
            "started_at": time.time(), 
            "client_ip": client_ip,
            "webhook_url": request.webhook_url,
            "progress_webhook_url": request.progress_webhook_url,
            "base_url": str(req.base_url),
            "progress_percent": 0,
            "progress_message": "Queued"
        }
    else:
        # Resuming existing job — re-queue it
        jobs[job_id]["status"] = "queued"
        jobs[job_id]["error"] = None
        jobs[job_id]["webhook_url"] = request.webhook_url
        jobs[job_id]["progress_webhook_url"] = request.progress_webhook_url
        jobs[job_id]["base_url"] = str(req.base_url)
        jobs[job_id]["progress_percent"] = 0
        jobs[job_id]["progress_message"] = "Queued"

    save_jobs()
    position = _enqueue_job(job_id, request)
    return {
        "status": "queued",
        "job_id": job_id,
        "queue_position": position,
        "message": f"Job queued. Position in queue: {position}. Max concurrent renders: {MAX_CONCURRENT_RENDERS}."
    }


@app.get("/video-status/{job_id}")
async def get_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    response = jobs[job_id].copy()
    status = response.get("status")
    
    # Calculate queue position dynamically if queued
    if status == "queued":
        pos = _queue_position(job_id)
        response["queue_position"] = pos if pos is not None else 1
        response["progress_percent"] = 0
        response["progress_message"] = f"Queued (position {response['queue_position']})"
    else:
        # Fallback to stored progress fields if not set
        response["progress_percent"] = response.get("progress_percent", 0)
        response["progress_message"] = response.get("progress_message", "Unknown status")

    if status in ["processing", "queued", "pending", "assembling"]:
        response["elapsed_seconds"] = round(time.time() - response["started_at"], 2)
        
    return response


@app.get("/queue-status")
async def queue_status():
    """Returns an overview of the current queue and active renders."""
    with _job_queue.mutex:
        queued_ids = [jid for jid, _ in list(_job_queue.queue)]
    with _queue_lock:
        active = list(_active_jobs)
    return {
        "max_concurrent_renders": MAX_CONCURRENT_RENDERS,
        "active_renders": len(active),
        "active_job_ids": active,
        "queued_count": len(queued_ids),
        "queued_job_ids": queued_ids,
    }


@app.get("/gallery")
async def get_gallery():
    """Returns a list of all successful jobs for the UI gallery, newest first."""
    succ_jobs = []
    for jid, data in jobs.items():
        if data.get("status") == "success":
            succ_jobs.append({
                "job_id": jid,
                "filename": data.get("filename"),
                "thumbnail": data.get("thumbnail"),
                "started_at": data.get("started_at", 0)
            })
    succ_jobs.sort(key=lambda x: x["started_at"], reverse=True)
    return {"videos": succ_jobs}


@app.delete("/cleanup-job/{job_id}")
async def manual_cleanup_job(job_id: str):
    """Manually delete all temporary WAV files for a completed job."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    deleted = cleanup_job_wavs(job_id)
    # Also remove checkpoint files if caller wants a full wipe
    return {
        "job_id": job_id,
        "deleted_files": deleted,
        "message": f"Cleaned up {len(deleted)} temp file(s)."
    }


@app.get("/favicon.png")
async def get_favicon():
    return FileResponse("favicon.png")


@app.get("/")
async def serve_ui():
    return FileResponse("index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)