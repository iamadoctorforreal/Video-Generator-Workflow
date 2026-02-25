# Kokoro Video Generator

This project is a dynamic, automated landscape and portrait video generation script using the **Kokoro-ONNX** TTS engine (which avoids the dependency nightmare and `numpy` incompatibility issues of the standard Kokoro library), `faster-whisper` for word-level sync, and `MoviePy` for video compositing and captions.

The script supports both **Landscape** and **Portrait** orientations, with smart caption wrapping that automatically adjusts based on the canvas width to ensure text never overflows.

This project uses **Docker Compose** to run both the Video API and n8n. You can either build it yourselves or use our official pre-built image for the fastest setup.

### 💨 Easy Setup (Docker Hub)
The fastest way to get started without building anything:

1. **Download this repo** (specifically the `docker-compose.yml` and `media` folders).
2. **Download Models**: Place `kokoro-v1.0.onnx` and `voices-v1.0.bin` in the root folder.
3. **Run**:
   ```bash
   docker-compose up
   ```

### 🐳 Build from Source (Local)
If you want to modify the code or build it yourself:
- **Docker Desktop** installed and running.
- **Model Files**: DOWNLOAD `kokoro-v1.0.onnx` and `voices-v1.0.bin` (links below) and place them in the root folder.
- **Media**: Ensure you have some images in the `images/` folder and a `bg_music.mp3` file.

### 2. Start the Services
```bash
docker-compose up --build
```

### 3. Access your Tools
Once the containers are running:
- **🎨 Web Studio (GUI):** Go to [http://localhost:8000](http://localhost:8000) (Use this for manual video creation).
- **🤖 n8n Automation:** Go to [http://localhost:5678](http://localhost:5678) (Use this for automated workflows).

> [!TIP]
> **GitHub Codespaces Users**: If you are in a Codespace, GitHub will automatically "forward" these ports. Click the **Ports** tab in the bottom panel to find your public URLs. Remember to set Port 8000 to **Public**!


---

## 🛠️ Manual Installation (Local)

If you prefer to run it directly on your machine:

## Prerequisites
Before you start, make sure you have the following installed on your machine:

1. **Python 3.10+**
2. **ImageMagick**: Required by MoviePy for rendering text captions.
   - For Windows users, install ImageMagick from [here](https://imagemagick.org/script/download.php). 
   - *Note:* Make sure to check "Install legacy utilities (e.g. convert)" during installation if prompted. You might need to adjust the `IMAGEMAGICK_BINARY` path inside `app_v3.py` if you install it in a different location than `C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe`.

## Installation

Choose the installation path that matches your hardware:

### Path A: Standard Install (Supports GPU)
Recommended if you have an **NVIDIA GPU** and want the fastest possible rendering speeds.
```bash
pip install -r requirements.txt
```
*Note: This will download several gigabytes of data (PyTorch with CUDA).*

### Path B: Lightweight Install (CPU Only)
Recommended for most laptops, or if you don't have a dedicated NVIDIA GPU.
```bash
pip install -r requirements-cpu.txt
```
*Note: This is much smaller (~200MB) and faster to download.*

## Missing Files (Model Weights & Media)
Because AI model files can be huge, they are excluded from this repository via `.gitignore`. You need to manually download them.

1. **Download Kokoro-ONNX AI Weights:**
   Download the following files and place them inside the root `kokoro` directory:
   - [`kokoro-v1.0.onnx`](https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx)
   - [`voices-v1.0.bin`](https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin)

2. **Add Background Music:**
   Ensure you have a background music file named `bg_music.mp3` in the root directory. This is used by the script for audio mixing.

3. **Add Images:**
   Create an `images` folder in the root directory and place your `.png` or `.jpg` assets inside it. By default, the script loads these sequentially for each scene.

## Running the Application

The main application file is `app_v3.py`. It runs a FastAPI backend server.

To start the server:
```bash
python app_v3.py
```
*(This starts the Uvicorn server on `http://0.0.0.0:8000`)*

### API Usage
Once the server is running, you can hit the `/generate-ghibli-video` endpoint with a POST request containing JSON data to generate a video.

**Example Request:**
```json
{
  "voice": "af_bella",
  "add_captions": true,
  "add_effects": true,
  "caption_position": "bottom",
  "orientation": "landscape",
  "scenes": [
    {
      "text": "Hello world, this is the first scene.",
      "media_name": "detect"
    },
    {
      "text": "This is the second scene.",
      "media_name": "detect"
    }
  ]
}
```

The server will automatically generate the audio via Kokoro-ONNX, align captions with Whisper, apply pan/zoom effects, add transitions, and mix background music, saving the final file as `Ghibli_Story_XXXX.mp4`.

## 🤖 Automating with n8n

The project now includes **n8n out-of-the-box** in the Docker container!

1.  **Open n8n:** Go to [http://localhost:5678](http://localhost:5678).
2.  **Import Workflow:** Import the `n8n_workflow.json` file from the root directory.
3.  **Internal Connection:** For the **HTTP Request** node, use this internal URL:
    `http://video-generator:8000/generate-ghibli-video`
    *(No need for host.docker.internal or local IPs!)*

## ⚡ Asynchronous API (Polling)

Since video rendering takes 4–8 minutes, the API is **Asynchronous** to prevent timeouts.

1.  **POST `/generate-ghibli-video`**: Starts the job and immediately returns a `job_id`.
2.  **GET `/video-status/{job_id}`**: Returns the current status (`pending`, `processing`, `success`, or `failed`).
3.  **Static Serving**: Once successful, videos can be accessed at `http://localhost:8000/videos/{filename}`.

## 📦 Docker Hub Image
The official image is hosted at:
[okayna/video-generator-workflow](https://hub.docker.com/repository/docker/okayna/video-generator-workflow)

To pull it manually:
```bash
docker pull okayna/video-generator-workflow
```

