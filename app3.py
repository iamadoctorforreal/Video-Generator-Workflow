from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from kokoro import KPipeline
import soundfile as sf
import os
import glob
import uuid
from moviepy import ImageClip, VideoFileClip, concatenate_videoclips, AudioFileClip
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Add CORS middleware for n8n
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pipeline = KPipeline(lang_code='a')

class Scene(BaseModel):
    text: str
    media_name: str 

class VideoRequest(BaseModel):
    scenes: list[Scene]
    voice: str = "af_bella"

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "ghibli-video-generator"}

@app.post("/generate-ghibli-video")
async def generate_video(request: VideoRequest):
    try:
        video_id = str(uuid.uuid4())[:8]
        final_clips = []
        
        BASE_MEDIA_PATH = r"C:\Users\RUKAYYAH IBRAHIM\Desktop\kokoro\images"
        
        print(f"\n{'='*60}")
        print(f"🎬 Starting Video Generation - ID: {video_id}")
        print(f"📂 Media Folder: {BASE_MEDIA_PATH}")
        print(f"🎭 Total Scenes: {len(request.scenes)}")
        print(f"🎤 Voice: {request.voice}")
        print(f"{'='*60}\n")
        
        for i, scene in enumerate(request.scenes, 1):
            print(f"\n🎬 Processing Scene {i}/{len(request.scenes)}")
            print(f"   Text: {scene.text[:60]}...")
            print(f"   Media: {scene.media_name}")
            
            # 1. Generate Voice
            audio_path = f"temp_{video_id}_{i}.wav"
            generator = pipeline(scene.text, voice=request.voice, speed=1.0)
            
            audio_data = None
            for _, _, audio in generator:
                audio_data = audio
                break
            
            if audio_data is None:
                raise Exception(f"Failed to generate audio for scene {i}")
            
            sf.write(audio_path, audio_data, 24000)
            audio_clip = AudioFileClip(audio_path)
            print(f"   ✅ Audio: {audio_clip.duration:.2f}s")
            
            # 2. Load Media
            media_path = os.path.join(BASE_MEDIA_PATH, scene.media_name)
            
            if not os.path.exists(media_path):
                print(f"   ⚠️  Missing file: {media_path}")
                print(f"   Creating black placeholder...")
                from moviepy import ColorClip
                clip = ColorClip(size=(768, 1024), color=(0,0,0)).with_duration(audio_clip.duration)
            else:
                if media_path.lower().endswith(('.mp4', '.mov')):
                    clip = VideoFileClip(media_path)
                    if clip.duration > audio_clip.duration:
                        clip = clip.subclipped(0, audio_clip.duration)
                    else:
                        clip = clip.with_duration(audio_clip.duration)
                    print(f"   ✅ Video loaded: {clip.duration:.2f}s")
                else:
                    clip = ImageClip(media_path).with_duration(audio_clip.duration)
                    print(f"   ✅ Image loaded as {audio_clip.duration:.2f}s clip")
            
            clip = clip.with_audio(audio_clip)
            final_clips.append(clip)
            print(f"   ✅ Scene {i} complete!")
        
        # 3. Final Render
        output_name = f"Ghibli_Story_{video_id}.mp4"
        print(f"\n🎞️  Concatenating {len(final_clips)} clips...")
        
        final_video = concatenate_videoclips(final_clips, method="compose")
        
        print(f"🎞️  Rendering final video: {output_name}")
        print(f"   Duration: {final_video.duration:.2f}s ({final_video.duration/60:.1f} minutes)")
        
        final_video.write_videofile(
            output_name, 
            fps=24, 
            codec="libx264",
            audio_codec="aac",
            preset="medium",
            temp_audiofile=f"temp_audio_{video_id}.m4a",
            remove_temp=True,
            logger=None  # Suppress moviepy logs
        )
        
        # Cleanup
        for f in glob.glob(f"temp_{video_id}_*.wav"):
            try:
                os.remove(f)
            except:
                pass
        
        output_path = os.path.abspath(output_name)
        print(f"\n{'='*60}")
        print(f"✅ SUCCESS! Video saved to:")
        print(f"   {output_path}")
        print(f"{'='*60}\n")
        
        return {
            "status": "success", 
            "video_path": output_path,
            "video_id": video_id,
            "duration_seconds": final_video.duration,
            "total_scenes": len(request.scenes)
        }
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"\n❌ ERROR:\n{error_details}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    print(f"\n🚀 Starting Ghibli Video Generator API...")
    print(f"📂 Media folder: C:\\Users\\RUKAYYAH IBRAHIM\\Desktop\\kokoro\\images")
    print(f"🌐 API will be available at: http://localhost:8000")
    print(f"📖 Docs available at: http://localhost:8000/docs\n")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)