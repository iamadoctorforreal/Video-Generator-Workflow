from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from kokoro import KPipeline
import soundfile as sf
import os
import glob
import uuid
import random
from moviepy import (
    ImageClip, VideoFileClip, concatenate_videoclips, AudioFileClip,
    TextClip, CompositeVideoClip, ColorClip, vfx
)
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

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
    add_captions: bool = True
    add_effects: bool = True  # Panning, zoom, transitions

def sanitize_text_for_tts(text):
    """Fix problematic words for Kokoro TTS"""
    # Replace Japanese names that cause issues
    replacements = {
        'Aiko': 'Eye-ko',
        'Haru': 'Ha-roo',
        'Yuki': 'You-kee',
        'Sora': 'So-rah',
        'Ren': 'Ren',
        'Kaito': 'Kai-toe',
        'Mei': 'May'
    }
    
    sanitized = text
    for original, replacement in replacements.items():
        sanitized = sanitized.replace(original, replacement)
    
    return sanitized

def create_caption(text, clip_size, duration):
    """Create simple caption overlay"""
    try:
        txt = TextClip(
            text=text,
            font='Arial-Bold',
            font_size=55,
            color='white',
            stroke_color='black',
            stroke_width=3,
            method='caption',
            size=(int(clip_size[0] * 0.9), None),
            text_align='center'
        ).with_duration(duration)
        
        txt = txt.with_position(('center', clip_size[1] * 0.75))
        return txt
    except Exception as e:
        print(f"   ⚠️  Caption creation failed: {e}")
        return None

def apply_pan_zoom_effect(clip, effect_type='random'):
    """Apply cinematic pan/zoom effects"""
    w, h = clip.size
    duration = clip.duration
    
    if effect_type == 'random':
        effect_type = random.choice(['zoom_in', 'zoom_out', 'pan_right', 'pan_left'])
    
    if effect_type == 'zoom_in':
        # Slow zoom in
        return clip.resized(lambda t: 1 + 0.15 * (t / duration))
    
    elif effect_type == 'zoom_out':
        # Slow zoom out
        return clip.resized(lambda t: 1.15 - 0.15 * (t / duration))
    
    elif effect_type == 'pan_right':
        # Pan from left to right
        return clip.with_position(lambda t: (-(t / duration) * w * 0.1, 0))
    
    elif effect_type == 'pan_left':
        # Pan from right to left
        return clip.with_position(lambda t: ((t / duration) * w * 0.1, 0))
    
    return clip

def create_crossfade_transition(clip1, clip2, duration=0.5):
    """Create crossfade transition between clips"""
    # Ensure clips have the same size
    if clip1.size != clip2.size:
        clip2 = clip2.resized(clip1.size)
    
    # Create fade out for clip1
    clip1_fade = clip1.with_effects([vfx.FadeOut(duration)])
    
    # Create fade in for clip2
    clip2_fade = clip2.with_effects([vfx.FadeIn(duration)])
    
    return clip1_fade, clip2_fade

def auto_detect_images(images_folder, num_scenes):
    """Auto-detect images sorted by creation time"""
    import os
    
    try:
        files = []
        for file in os.listdir(images_folder):
            if file.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.mp4', '.mov')):
                filepath = os.path.join(images_folder, file)
                files.append({
                    'name': file,
                    'time': os.path.getctime(filepath)
                })
        
        # Sort by creation time (oldest first)
        files.sort(key=lambda x: x['time'])
        
        # Return only the filenames
        return [f['name'] for f in files[:num_scenes]]
    
    except Exception as e:
        print(f"   ⚠️  Auto-detection failed: {e}")
        return []

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
        print(f"📝 Captions: {'Enabled' if request.add_captions else 'Disabled'}")
        print(f"🎨 Effects: {'Enabled' if request.add_effects else 'Disabled'}")
        print(f"{'='*60}\n")
        
        # Auto-detect images if needed
        auto_detected_images = []
        if any(scene.media_name == "detect" for scene in request.scenes):
            print(f"🔍 Auto-detecting images...")
            auto_detected_images = auto_detect_images(BASE_MEDIA_PATH, len(request.scenes))
            if auto_detected_images:
                print(f"   ✅ Found {len(auto_detected_images)} images")
                for i, img in enumerate(auto_detected_images[:5]):
                    print(f"      {i+1}. {img}")
            else:
                print(f"   ⚠️  No images found, will use black placeholders")
        
        for i, scene in enumerate(request.scenes, 1):
            print(f"\n🎬 Processing Scene {i}/{len(request.scenes)}")
            print(f"   Text: {scene.text[:60]}...")
            
            # Determine media file
            if scene.media_name == "detect" and auto_detected_images:
                media_file = auto_detected_images[i-1] if i-1 < len(auto_detected_images) else None
            else:
                media_file = scene.media_name
            
            print(f"   Media: {media_file or 'black placeholder'}")
            
            # 1. Generate Voice with sanitized text
            sanitized_text = sanitize_text_for_tts(scene.text)
            if sanitized_text != scene.text:
                print(f"   📝 Sanitized: {sanitized_text[:60]}...")
            
            audio_path = f"temp_{video_id}_{i}.wav"
            
            try:
                generator = pipeline(sanitized_text, voice=request.voice, speed=1.0)
                
                audio_data = None
                for _, _, audio in generator:
                    audio_data = audio
                    break
                
                if audio_data is None:
                    raise Exception(f"Failed to generate audio for scene {i}")
                
                sf.write(audio_path, audio_data, 24000)
                audio_clip = AudioFileClip(audio_path)
                print(f"   ✅ Audio: {audio_clip.duration:.2f}s")
                
            except Exception as e:
                print(f"   ❌ TTS Error: {e}")
                print(f"   Creating silent audio placeholder...")
                # Create 3 seconds of silence as fallback
                import numpy as np
                silence = np.zeros(int(3 * 24000))
                sf.write(audio_path, silence, 24000)
                audio_clip = AudioFileClip(audio_path)
            
            # 2. Load Media
            if media_file:
                media_path = os.path.join(BASE_MEDIA_PATH, media_file)
            else:
                media_path = None
            
            if not media_path or not os.path.exists(media_path):
                if media_path:
                    print(f"   ⚠️  Missing file: {media_path}")
                print(f"   Creating black placeholder...")
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
            
            # 3. Apply Pan/Zoom Effects
            if request.add_effects:
                effect = random.choice(['zoom_in', 'zoom_out', 'pan_right', 'pan_left', None])
                if effect:
                    print(f"   🎨 Applying {effect} effect...")
                    clip = apply_pan_zoom_effect(clip, effect)
            
            # 4. Add Captions
            if request.add_captions:
                print(f"   📝 Adding captions...")
                caption = create_caption(scene.text, (clip.w, clip.h), audio_clip.duration)
                if caption:
                    clip = CompositeVideoClip([clip, caption])
                    print(f"   ✅ Captions added")
            
            # 5. Add Audio
            clip = clip.with_audio(audio_clip)
            final_clips.append(clip)
            print(f"   ✅ Scene {i} complete!")
        
        # 6. Add Crossfade Transitions
        if request.add_effects and len(final_clips) > 1:
            print(f"\n🎨 Adding crossfade transitions...")
            transitioned_clips = [final_clips[0]]
            
            for i in range(1, len(final_clips)):
                # Add crossfade between clips
                prev_clip, curr_clip = create_crossfade_transition(
                    final_clips[i-1], 
                    final_clips[i],
                    duration=0.5
                )
                transitioned_clips.append(curr_clip)
            
            final_clips = transitioned_clips
        
        # 7. Final Render
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
            logger=None
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
            "total_scenes": len(request.scenes),
            "captions_added": request.add_captions,
            "effects_added": request.add_effects
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