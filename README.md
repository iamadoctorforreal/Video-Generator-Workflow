# Kokoro Video Generator

This project is a dynamic, automated landscape and portrait video generation script using the [Kokoro TTS](https://huggingface.co/hexgrad/Kokoro-82M) engine, `faster-whisper` for word-level sync, and `MoviePy` for video compositing and captions.

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
Because AI model files can be huge, they are excluded from this repository via `.gitignore` and Git LFS. You need to manually download them.

1. **Download Kokoro AI Weights:**
   Download the following files and place them inside the root `kokoro` directory:
   - `kokoro-v0_19.onnx`
   - `voices-v1.0.bin`
   *(You can generally find these on the Kokoro TTS Hugging Face repository).*

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
  "orientation": "portrait",
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

The server will automatically generate the audio, align captions with Whisper, apply pan/zoom effects, add transitions, and mix background music, saving the final file as `Ghibli_Story_XXXX.mp4`.
