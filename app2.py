from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from kokoro import KPipeline
import soundfile as sf
import os
import glob
import uuid
from moviepy import ImageClip, VideoFileClip, concatenate_videoclips, AudioFileClip

app = FastAPI()
pipeline = KPipeline(lang_code='a')

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
        
        BASE_MEDIA_PATH = "C:/Users/RUKAYYAH IBRAHIM/Desktop/kokoro/images"
        
        for i, scene in enumerate(request.scenes):
            print(f"🎬 Processing Scene {i+1}: {scene.text[:50]}...")
            
            # 1. Generate Voice
            audio_path = f"temp_{video_id}_{i}.wav"
            generator = pipeline(scene.text, voice=request.voice, speed=1)
            
            # FIX: Properly extract audio from generator
            audio_data = None
            for _, _, audio in generator:
                audio_data = audio
                break  # Only need first chunk
            
            if audio_data is None:
                raise Exception(f"Failed to generate audio for scene {i+1}")
            
            sf.write(audio_path, audio_data, 24000)
            audio_clip = AudioFileClip(audio_path)
            
            # 2. Load Media
            media_path = os.path.join(BASE_MEDIA_PATH, scene.media_name)
            
            if not os.path.exists(media_path):
                print(f"⚠️ Missing: {media_path}")
                # Create a black placeholder
                from moviepy import ColorClip
                clip = ColorClip(size=(768, 1024), color=(0,0,0)).with_duration(audio_clip.duration)
            else:
                if media_path.lower().endswith(('.mp4', '.mov')):
                    clip = VideoFileClip(media_path)
                    if clip.duration > audio_clip.duration:
                        clip = clip.subclipped(0, audio_clip.duration)
                    else:
                        clip = clip.with_duration(audio_clip.duration)
                else:
                    clip = ImageClip(media_path).with_duration(audio_clip.duration)
            
            clip = clip.with_audio(audio_clip)
            final_clips.append(clip)
            
            print(f"✅ Scene {i+1} complete ({audio_clip.duration:.2f}s)")
        
        # 3. Final Render
        output_name = f"Ghibli_Story_{video_id}.mp4"
        final_video = concatenate_videoclips(final_clips, method="compose")
        final_video.write_videofile(
            output_name, 
            fps=24, 
            codec="libx264",
            audio_codec="aac",
            temp_audiofile=f"temp_audio_{video_id}.m4a",
            remove_temp=True
        )
        
        # Cleanup temp audio files
        for f in glob.glob(f"temp_{video_id}_*.wav"):
            os.remove(f)
        
        return {
            "status": "success", 
            "video_path": os.path.abspath(output_name),
            "duration": final_video.duration
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)