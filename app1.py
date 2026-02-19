from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from kokoro import KPipeline
import soundfile as sf
import os
import glob
import uuid
from moviepy import ImageClip, VideoFileClip, concatenate_videoclips, AudioFileClip

app = FastAPI()
pipeline = KPipeline(lang_code='a') # 'a' for American English, 'b' for British

class Scene(BaseModel):
    text: str
    media_name: str 

class VideoRequest(BaseModel):
    scenes: list[Scene]
    voice: str = "af_bella"

@app.post("/generate-ghibli-video")
async def generate_video(request: VideoRequest):
    try:
        video_id = str(uuid.uuid4())[:8]
        final_clips = []
        
        # Folder where you save your Whisk images/videos
        # Make sure this matches your folder name!
        BASE_MEDIA_PATH = "C:/Users/RUKAYYAH IBRAHIM/Desktop/kokoro/images"

        for i, scene in enumerate(request.scenes):
            # 1. Generate Voice for this scene
            audio_path = f"temp_{video_id}_{i}.wav"
            # Note: Kokoro handles '...' as natural pauses automatically
            generator = pipeline(scene.text, voice=request.voice, speed=1)
            for _, _, audio in generator:
                sf.write(audio_path, audio, 24000)
            
            audio_clip = AudioFileClip(audio_path)
            media_path = os.path.join(BASE_MEDIA_PATH, scene.media_name)
            
            if not os.path.exists(media_path):
                print(f"⚠️ Missing file: {media_path}")
                continue

            # 2. Build Clip
            if media_path.lower().endswith(('.mp4', '.mov')):
                clip = VideoFileClip(media_path).subclipped(0, audio_clip.duration)
            else:
                clip = ImageClip(media_path).with_duration(audio_clip.duration)

            clip = clip.with_audio(audio_clip)
            final_clips.append(clip)

        # 3. Final Render
        output_name = f"Ghibli_Story_{video_id}.mp4"
        final_video = concatenate_videoclips(final_clips, method="compose")
        final_video.write_videofile(output_name, fps=24, codec="libx264")

        return {"status": "success", "video_path": os.path.abspath(output_name)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)