# The Storyteller Suite 🎬✨

A premium, automated video generation platform that transforms scripts into cinematic videos using **Kokoro-ONNX** TTS, `faster-whisper` for synchronized captions, and MoviePy for visual composition — all wrapped in a polished **Storyteller Studio** UI and a fully automated **n8n workflow**.

---

## 🎭 Three Powerful Workspaces

1. **Studio Mode** — Classic centered layout for quick visual storytelling with a simple text script.
2. **Professional Mode** — Sidebar-driven dashboard for per-scene control over media, audio, captions, and effects.
3. **Canvas Mode** — A distraction-free writing space for "script-first" creators.

---

## 🚀 Quick Start (Docker — Recommended)

```bash
git clone https://github.com/iamadoctorforreal/video-generator-workflow.git
cd video-generator-workflow

# Place model files in root (auto-downloaded on first run if missing)
# kokoro-v1.0.onnx  +  voices-v1.0.bin

docker-compose down && docker-compose up --build
```

Then open **[http://localhost:8000](http://localhost:8000)** to start creating.

---

## 🛠️ Manual Installation (Local Machine)

### Prerequisites
- **Python 3.10+**
- **ImageMagick** (required for caption rendering)
  - **Windows:** Download from [imagemagick.org](https://imagemagick.org/script/download.php). The path `C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe` is pre-configured in `app.py`. Adjust if your version differs.
  - **Linux/Mac:** `sudo apt install imagemagick` or `brew install imagemagick`

### Install Dependencies

**CPU-only (recommended for most laptops):**
```bash
python -m venv venv
.\venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac
pip install -r requirements-cpu.txt
```

**GPU (NVIDIA CUDA):**
```bash
pip install -r requirements.txt
```

### Download AI Model Files
The Kokoro TTS models are large and excluded from the repo. They are **auto-downloaded on first run**, but you can also place them manually in the project root:
- [`kokoro-v1.0.onnx`](https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx)
- [`voices-v1.0.bin`](https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin)

### Run
```bash
python app.py
# Server starts at http://0.0.0.0:8000
```

---

## 📖 Use Cases

The API supports several distinct video creation workflows. Here is a breakdown of each one and the exact settings required.

---

### ✅ Use Case 1: Standard AI Video (Default)
> *Write a script → AI generates voice → captions sync automatically → music plays → video renders.*

This is the primary workflow. Provide a script, choose a voice, and the system does everything automatically.

**API Payload:**
```json
{
  "scenes": [
    { "text": "The sun dipped below the horizon.", "media_name": "detect" },
    { "text": "A lone traveler continued down the path.", "media_name": "detect" }
  ],
  "voice": "af_bella",
  "generate_voiceover": true,
  "add_captions": true,
  "caption_position": "bottom",
  "add_background_music": true,
  "bg_music_volume": 0.12,
  "add_effects": true,
  "orientation": "portrait"
}
```

**Notes:**
- `"media_name": "detect"` auto-assigns images from the `images/` folder in order.
- You can also pass a direct URL: `"media_name": "https://example.com/photo.jpg"`
- `voice` options: `af_bella`, `af_sarah`, `am_adam`, `bf_emma`, `bm_george`

---

### ✅ Use Case 2: Add Captions to an Existing Video (No Script Needed)
> *Upload a video that already has audio → captions are auto-transcribed from the audio → no new voiceover is added.*

This is the "captioning only" mode. The system extracts the audio from your video clip and runs it through Whisper to generate precise word-level captions.

**Step 1 — Upload your video via the UI or API:**
```
POST /upload-image
Form-data: file=<your_video.mp4>
```

**Step 2 — Trigger generation:**
```json
{
  "scenes": [
    { "text": "", "media_name": "your_video.mp4" }
  ],
  "generate_voiceover": false,
  "keep_clip_audio": true,
  "clip_audio_volume": 1.0,
  "add_captions": true,
  "caption_position": "bottom",
  "add_background_music": false,
  "add_effects": false,
  "orientation": "landscape"
}
```

**Notes:**
- `text` can be empty — captions are transcribed from the video's own audio.
- `generate_voiceover: false` disables AI TTS.
- `keep_clip_audio: true` preserves the original video sound.
- `add_effects: false` is recommended since it is a video clip, not a still image.

---

### ✅ Use Case 3: Use a Custom Voiceover Audio File
> *You have a pre-recorded or externally generated voiceover audio → attach it to a video → sync captions from that audio.*

**Step 1 — Upload your voiceover audio:**
```
POST /upload-voiceover
Form-data: file=<your_voiceover.mp3>
```
Response: `{ "filename": "vo_abc123_voiceover.mp3" }`

**Step 2 — Trigger generation with the returned filename:**
```json
{
  "scenes": [
    { "text": "", "media_name": "your_video_or_image.mp4" }
  ],
  "generate_voiceover": false,
  "uploaded_voiceover": "vo_abc123_voiceover.mp3",
  "add_captions": true,
  "caption_position": "bottom",
  "add_background_music": true,
  "bg_music_volume": 0.10,
  "add_effects": false,
  "orientation": "landscape"
}
```

**Notes:**
- The uploaded voiceover is applied across **all scenes**, split evenly by duration.
- Captions are auto-transcribed from the voiceover audio via Whisper.
- `text` can be left empty since AI TTS is disabled.

---

### ✅ Use Case 4: Custom Background Music
> *Upload your own music track to use instead of the bundled default tracks.*

**Step 1 — Upload your music:**
```
POST /upload-music
Form-data: file=<your_music.mp3>
```
Response: `{ "filename": "your_music.mp3" }`

**Step 2 — Pass the filename in the payload:**
```json
{
  "add_background_music": true,
  "bg_music_file": "your_music.mp3",
  "bg_music_volume": 0.15,
  ...
}
```

---

### ✅ Use Case 5: Mixed Audio (Voiceover + Original Video Audio + Background Music)
> *Video clip has sound effects you want to keep → overlay a voiceover → add background music — all at once.*

```json
{
  "scenes": [
    { "text": "The engine roared as they sped into the night.", "media_name": "chase_scene.mp4" }
  ],
  "voice": "am_adam",
  "generate_voiceover": true,
  "keep_clip_audio": true,
  "clip_audio_volume": 0.3,
  "add_background_music": true,
  "bg_music_volume": 0.08,
  "add_captions": true,
  "add_effects": false,
  "orientation": "landscape"
}
```

**Notes:**
- All three audio layers — AI voiceover, clip audio, and background music — are mixed together automatically.
- `clip_audio_volume` controls the level of the original clip audio in the mix.

---

### ✅ Use Case 6: Image Slideshow with Pan/Zoom Effects
> *Provide a set of still images → the ken-burns pan/zoom effect makes them feel cinematic.*

```json
{
  "scenes": [
    { "text": "Deep in the enchanted forest...", "media_name": "forest.jpg" },
    { "text": "A flickering light caught her eye.", "media_name": "light.jpg" }
  ],
  "voice": "af_bella",
  "generate_voiceover": true,
  "add_effects": true,
  "add_captions": true,
  "orientation": "portrait"
}
```

**Notes:**
- Pan/zoom effects (`add_effects: true`) are only applied to **still images**, not video clips.
- Recommended for portrait (9:16) social media content.

---

## ⚡ Asynchronous API Reference

Rendering is **fully async** with a job queue. Render time is **not fixed** — it depends on your hardware, scene count, and which features are enabled.

### Render Time Estimates

| Hardware | 3-scene video | 10-scene video |
|---|---|---|
| NVIDIA GPU (CUDA) | ~1–2 min | ~3–5 min |
| Modern laptop CPU (8+ cores) | ~3–5 min | ~10–15 min |
| Older / low-power CPU | ~8–15 min | ~25–40 min |
| GitHub Codespaces (free 2-core) | ~15–30 min | ~60+ min |

### What Slows It Down Most
| Operation | Impact |
|---|---|
| Caption rendering (ImageMagick per word) | High |
| Final video encoding (`preset="medium"`) | High |
| Whisper transcription (per scene) | Medium |
| Kokoro TTS generation (per scene) | Low–Medium |

**Tips to speed things up:**
- Use **fewer scenes** — render time scales roughly linearly with scene count.
- **Disable captions** (`add_captions: false`) — caption rendering is the single most expensive per-scene operation.
- **Use a GPU** — switch to `requirements.txt` (CUDA build) for dramatically faster Whisper and encoding.
- The final assembly uses `preset="medium"` for quality; changing it to `"fast"` or `"ultrafast"` in `app.py` line 791 will shorten the last step.



| Endpoint | Method | Description |
|---|---|---|
| `/generate-video` | POST | Submit a job. Returns `job_id` and `queue_position`. |
| `/video-status/{job_id}` | GET | Check status: `queued`, `processing`, `assembling`, `success`, `failed`. |
| `/upload-image` | POST | Upload an image or video clip for a scene. |
| `/upload-voiceover` | POST | Upload a custom voiceover audio file. |
| `/upload-music` | POST | Upload a custom background music file. |
| `/gallery` | GET | List all previously generated videos. |
| `/videos/{filename}` | GET | Directly stream or download a generated video. |

### Webhook Support
Pass `"webhook_url": "https://your-endpoint.com/hook"` in your payload. When the video finishes (or fails), the server fires a POST to your URL:
```json
{
  "job_id": "abc123",
  "status": "success",
  "filename": "Story_Final_abc123.mp4",
  "video_url": "https://your-server.com/videos/Story_Final_abc123.mp4",
  "thumbnail_url": "https://your-server.com/videos/Thumbnail_abc123.jpg"
}
```

---

## 🤖 Automating with n8n

The project ships with a fully configured n8n workflow (`n8n_workflow_updated.json`) that handles the entire pipeline end-to-end and uploads the final video to **Google Drive**.

### Setup
1. Open n8n at **[http://localhost:5678](http://localhost:5678)**
2. Go to **Workflows → Import from File** and select `n8n_workflow_updated.json`
3. Click the **Google Drive** node and connect your Google account credentials
4. Activate the workflow

### How It Works
The workflow uses a **Webhook Resume** pattern instead of polling — it is far more efficient:

```
Form Trigger
    │
    ├──► Upload Voiceover (if URL provided) ──┐
    ├──► Upload Background Music (if URL)  ──┤
    │                                         │
    └──► Format JSON Payload ◄────────────────┘
              │
              ▼
    Send to FastAPI (/generate-video)
    [includes $resumeUrl as webhook_url]
              │
              ▼
    ⏸ Wait for Video Completion (n8n suspends here)
    [FastAPI calls back when done]
              │
              ▼
    Download Video File
              │
              ▼
    Upload to Google Drive ✅
```

### n8n Use Cases

#### n8n Use Case 1: Standard AI Video
Fill the form:
- **Script**: Your multi-paragraph script (one paragraph = one scene)
- **Generate AI Voiceover?**: `true`
- **Add Captions?**: `true`
- Leave voiceover/music URL fields **blank**

#### n8n Use Case 2: Caption an Existing Video
Fill the form:
- **Script**: Leave blank (or put `(no script)`)
- **Media URLs**: The URL of your video (must be publicly accessible)
- **Generate AI Voiceover?**: `false`
- **Keep Original Video Audio?**: `true`
- **Add Captions?**: `true`

> **Note:** Your video must be hosted at a publicly accessible URL for n8n to pass it to FastAPI. Alternatively, upload it first via the `/upload-image` endpoint and use the local filename.

#### n8n Use Case 3: Custom Voiceover + Captions
Fill the form:
- **Script**: Leave blank
- **Voiceover Audio URL**: Paste a direct link to your `.mp3` or `.wav` audio file (e.g., from Google Drive, Dropbox, or S3)
- **Generate AI Voiceover?**: `false`
- **Add Captions?**: `true`

The workflow will automatically upload the audio to FastAPI, then use it as the voiceover.

#### n8n Use Case 4: Custom Background Music
Fill the form:
- **Background Music URL**: Paste a direct link to your music file
- **Add Background Music?**: `true`
- **Background Music Volume**: e.g., `0.15`

---

## 📦 Docker Hub Image
The official image is hosted at:
[okayna/video-generator-workflow](https://hub.docker.com/repository/docker/okayna/video-generator-workflow)

```bash
docker pull okayna/video-generator-workflow:v2
```

---

## 🔐 Environment Variables (`.env`)

| Variable | Description |
|---|---|
| `SENTRY_DSN` | Optional. Sentry error tracking DSN. Leave blank to disable. |

---

## 📁 Project Structure

```
video-generator-workflow/
├── app.py                      # FastAPI backend — main application
├── index.html                  # Storyteller Studio UI
├── n8n_workflow_updated.json   # Pre-built n8n workflow (import this!)
├── generate_n8n_workflow.py    # Script to regenerate the n8n workflow JSON
├── requirements.txt            # GPU dependencies
├── requirements-cpu.txt        # CPU-only dependencies
├── setup_codespace.sh          # GitHub Codespaces setup script
├── docker-compose.yml          # Docker stack (app + n8n)
├── images/                     # Default media assets (images/videos per scene)
├── temp_uploads/               # User-uploaded scene media
├── uploaded_music/             # User-uploaded background music
├── uploaded_voiceovers/        # User-uploaded voiceover audio
├── job_checkpoints/            # Scene-level render checkpoints (for resume)
├── kokoro-v1.0.onnx            # Kokoro TTS model weights (auto-downloaded)
└── voices-v1.0.bin             # Kokoro voice embeddings (auto-downloaded)
```
