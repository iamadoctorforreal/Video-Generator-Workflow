# Kokoro Video Generator

This project is a dynamic, automated landscape and portrait video generation script using the **Kokoro-ONNX** TTS engine (which avoids the dependency nightmare and `numpy` incompatibility issues of the standard Kokoro library), `faster-whisper` for word-level sync, and `MoviePy` for video compositing and captions.

**⚠️ Important Note on Orientation:** It's highly recommended to use `"orientation": "landscape"` for your videos. Generating videos in `"portrait"` mode is still being tuned—currently, captions generated on a portrait canvas can occasionally be cut off at the edges of the screen because the text wrapping width isn't fully constrained to the narrower view yet.

## Prerequisites
Before you start, make sure you have the following installed on your machine:

1. **Python 3.10+**
2. **ImageMagick**: Required by MoviePy for rendering text captions.
   - For Windows users, install ImageMagick from [here](https://imagemagick.org/script/download.php). 
   - *Note:* Make sure to check "Install legacy utilities (e.g. convert)" during installation if prompted. You might need to adjust the `IMAGEMAGICK_BINARY` path inside `app_v3.py` if you install it in a different location than `C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe`.

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/iamadoctorforreal/kokoro.git
   cd kokoro
   ```

2. **Create and activate a virtual environment (Recommended):**
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```

3. **Install the dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

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

You can automate video generation by connecting an **n8n** workflow to this FastAPI backend. An example workflow file (`n8n_workflow.json`) is included in this repository.

### 1. Installing & Running n8n
If you don't have n8n installed, you can run it easily using Docker or npm:

**Option A: Using npm (Node.js)**
```bash
npx n8n
```

**Option B: Using Docker**
```bash
docker run -it --rm --name n8n -p 5678:5678 -v ~/.n8n:/home/node/.n8n docker.n8n.io/n8n/n8n
```
n8n will be available at [http://localhost:5678](http://localhost:5678).

### 2. Importing the Workflow
1. Open n8n in your browser.
2. Go to **Workflows** -> **Add Workflow**.
3. Click the menu in the top right and select **Import from File**.
4. Select the `n8n_workflow.json` file from this repository.

### 3. Connecting n8n to FastAPI
The workflow uses an **HTTP Request** node to send the script to your FastAPI server (`app_v3.py`). Depending on how you run n8n, you might need to adjust the URL in the HTTP Request node:

- **If running n8n via npm:** The default `http://localhost:8000/generate-ghibli-video` or `http://127.0.0.1:8000/generate-ghibli-video` will work perfectly.
- **If running n8n via Docker (Windows/Mac):** Docker containers have their own isolated network. You must change the URL in the HTTP node to:
  ```text
  http://host.docker.internal:8000/generate-ghibli-video
  ```
- **If `host.docker.internal` fails (or you are on Linux without extra config):** You will need to use your machine's actual local IP address (e.g., `192.168.1.171`).
  1. Find your IP address:
     - Windows: Open Command Prompt/PowerShell and type `ipconfig` (look for IPv4 Address).
     - Mac/Linux: Open Terminal and type `ifconfig` or `hostname -I`.
  2. Update the HTTP Request node URL to use that IP:
     ```text
     http://YOUR_IP_ADDRESS:8000/generate-ghibli-video
     ```

Once configured, simply trigger the workflow, fill out the form with your script (using double spacing `\n\n` between scenes), select a voice, and n8n will automatically formulate the JSON and send it to your video generator!
