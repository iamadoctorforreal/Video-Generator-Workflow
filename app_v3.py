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
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
#from kokoro import KPipeline
from kokoro_onnx import Kokoro
from moviepy import (
    ImageClip, VideoFileClip, concatenate_videoclips, AudioFileClip,
    TextClip, CompositeVideoClip, ColorClip, vfx, CompositeAudioClip, afx
)
from fastapi.middleware.cors import CORSMiddleware

# Set the ImageMagick path for MoviePy v2.0+
os.environ["IMAGEMAGICK_BINARY"] = r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Whisper (Tiny is fastest for CPU)
# "cpu" forced to avoid CUDA errors on your laptop
whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")


# Initialize the Kokoro Pipeline
#pipeline = KPipeline(lang_code='a')
# You will need to download these two files (see link below)
kokoro = Kokoro("kokoro-v0_19.onnx", "voices-v1.0.bin") 


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

    # Replace special markers

    text = text.replace("[sigh]", " haaaahhh... ").replace("[pause]", " . . . ")

    # Remove non-ASCII characters
    text = text.encode("ascii", "ignore").decode()


    # Fix punctuation
    text = text.replace("...", ".").replace("—", "-").replace("–", "-")

    # Replace problematic names (add MORE names that cause crashes)
    replacements = {
         'Aiko': 'Eye-ko', 
         'Haru': 'Ha-roo', 
         'Yuki': 'You-kee', 
         'Elara': 'Eh-lah-rah', 
         'Midasis': 'Mih-dah-sis', 
         'cicadas': 'si-kay-dahs'}
      

    # ADD THESE LINES to remove quotes and problematic characters
    text = text.replace('"', '').replace("'", "")
     

    # Apply all replacements
 #  for original, replacement in replacements.items():
 #      regEx = re.compile(re.escape(original), re.IGNORECASE)
 #      sanitized = regEx.sub(replacement, text)
 #  return sanitized.strip()                                                     


    # REPLACE the replacements loop with this:
    for original, replacement in replacements.items():
        regEx = re.compile(re.escape(original), re.IGNORECASE)
        text = regEx.sub(replacement, text)  # ← assign to `text`, not `sanitized`
    return text.strip()                      # ← return `text`, not `sanitized`


def get_word_timestamps(audio_path, script_text=None):
    import difflib

    # Build a vocabulary from the original script for fuzzy correction.
    # Whisper re-transcribes TTS audio and can mishear words — we snap each
    # Whisper word back to the closest word in the actual script.
    script_vocab = {}
    if script_text:
        # Preserve original casing; key by lowercase for lookup
        for word in re.findall(r"[\w']+", script_text):
            script_vocab[word.lower()] = word

    def correct_word(whisper_word):
        cleaned = whisper_word.strip(".,!?;:-\"'")
        key = cleaned.lower()
        if not script_vocab or key in script_vocab:
            return script_vocab.get(key, whisper_word)
        # Fuzzy match against script vocabulary
        matches = difflib.get_close_matches(key, script_vocab.keys(), n=1, cutoff=0.65)
        if matches:
            return script_vocab[matches[0]]
        return whisper_word  # no good match — keep Whisper's version

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




def create_dynamic_captions(words, clip_size, active_index=0, caption_position="bottom"):
    if not words:
        return []

    word_clips = []
    w, h = clip_size

    position_map = {
        "bottom": h * 0.78,
        "center": h * 0.50,
        "top":    h * 0.15,
    }
    y_pos = position_map.get(caption_position, h * 0.78)

    FONT = r'C:\Windows\Fonts\arialbd.ttf'
    GAP = 10
    GROUP_SIZE = 4
    MAX_WIDTH = int(w * 0.92)  # never let group exceed 92% of canvas

    # Build groups of 4 words
    groups = []
    i = 0
    while i < len(words):
        groups.append(words[i:i + GROUP_SIZE])
        i += GROUP_SIZE

    for group_idx, group in enumerate(groups):
        try:
            # Step 1: find a font size that fits all words in this group
            font_size = 72
            margin = (20, 20)
            measured = []
            for attempt in range(5):  # shrink up to 5 times
                measured = []
                for word_obj in group:
                    txt = word_obj['word'].upper()
                    m = TextClip(text=txt, font=FONT, font_size=font_size,
                                 method='label', margin=margin)
                    measured.append({'txt': txt, 'obj': word_obj,
                                     'w': int(m.w), 'h': int(m.h)})
                    m.close()

                total_w = sum(m['w'] for m in measured) + GAP * (len(measured) - 1)
                if total_w <= MAX_WIDTH:
                    break  # fits — done
                # Too wide: shrink font by 10% and try again
                font_size = max(36, int(font_size * 0.88))
                margin = (15, 15)

            # Step 2: compute horizontal positions (centered, guaranteed to fit)
            total_w = sum(m['w'] for m in measured) + GAP * (len(measured) - 1)
            curr_x = (w - total_w) // 2
            for m in measured:
                m['x'] = int(curr_x)
                m['y'] = int(y_pos - m['h'] // 2)
                curr_x += m['w'] + GAP

            # Step 3: safety clamp — no clip should start fully off-screen
            measured = [m for m in measured if m['x'] + m['w'] > 0 and m['x'] < w]
            if not measured:
                continue

            # Compute the "group end" — the point where this group disappears.
            # It should be the moment the NEXT group's first word starts speaking,
            # so captions never vanish during pauses (only at group boundaries).
            if group_idx + 1 < len(groups):
                group_end = groups[group_idx + 1][0]['start']
            else:
                group_end = measured[-1]['obj']['end']  # last group: end of last word

            # Step 4: for each word's time slot, render whole group.
            # seg_end extends to the NEXT word's start (not this word's end),
            # so the highlighted word stays visible during pauses between words.
            for active_idx, active_item in enumerate(measured):
                seg_start = active_item['obj']['start']
                # Stay highlighted until the next word starts, or until group_end
                if active_idx + 1 < len(measured):
                    seg_end = measured[active_idx + 1]['obj']['start']
                else:
                    seg_end = group_end
                seg_dur = max(0.05, seg_end - seg_start)

                for j, m in enumerate(measured):
                    is_active = (j == active_idx)
                    try:
                        t = TextClip(
                            text=m['txt'],
                            font=FONT,
                            font_size=font_size,
                            color='yellow' if is_active else '#AAAAAA',
                            stroke_color='black',
                            stroke_width=4 if is_active else 2,
                            method='label',
                            margin=margin
                        )
                        # Guard: skip any clip whose actual rendered width
                        # would still place it completely off-screen
                        if m['x'] + int(t.w) <= 0 or m['x'] >= w:
                            t.close()
                            continue
                        word_clips.append(
                            t.with_position((m['x'], m['y']))
                             .with_start(seg_start)
                             .with_duration(seg_dur)
                        )
                    except Exception as clip_err:
                        print(f"⚠️ Skipping clip '{m['txt']}': {clip_err}")
                        continue

        except Exception as e:
            print(f"⚠️ Caption group error: {e}")
            continue

    return word_clips










#def create_caption(text, clip_size, duration):
#    try:
#        txt_clip = TextClip(
#            text=text.strip(),
#            font=r'C:\Windows\Fonts\arialbd.ttf',
#            font_size=60,
#            color='yellow',
#            stroke_color='black',
#            stroke_width=2,
#            method='caption',
#            size=(int(clip_size[0] * 0.8), int(clip_size[1] * 0.3)), 
#            text_align='center'
#        ).with_duration(duration).with_position(('center', clip_size[1] * 0.65))
#        return txt_clip
#    except: return None



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

@app.post("/generate-ghibli-video")
async def generate_video(request: VideoRequest):
    start_time = time.time()
    try:
        video_id = str(uuid.uuid4())[:8]
        final_clips = []
       #BASE_MEDIA_PATH = r"C:\Users\RUKAYYAH IBRAHIM\Desktop\kokoro\images"
        MUSIC_PATH = r"C:\Users\RUKAYYAH IBRAHIM\Desktop\kokoro\bg_music.mp3"
        BASE_MEDIA_PATH = os.path.join(os.getcwd(), "images")
       #MUSIC_PATH = os.path.join(os.getcwd(), "bg_music.mp3")
         
        
        print(f"\n{'='*20} 🎬 STARTING GENERATION: {video_id} {'='*20}")
        
        auto_detected_images = auto_detect_images(BASE_MEDIA_PATH, len(request.scenes))

        for i, scene in enumerate(request.scenes, 1):
            scene_start = time.time()
            print(f"🔄 Step 1/3: Processing Scene {i}/{len(request.scenes)}...", end="\r")
            
            clean_text = sanitize_text_for_tts(scene.text)
            media_file = auto_detected_images[i-1] if (scene.media_name == "detect" and i-1 < len(auto_detected_images)) else scene.media_name

            # TTS
            #audio_path = f"temp_{video_id}_{i}.wav"
            #generator = pipeline(clean_text, voice=request.voice, speed=1.0)
            #audio_data = None
            #for _, _, audio in generator:
            #    if audio is not None: audio_data = audio; break
            
            #if audio_data is not None:
            #    sf.write(audio_path, audio_data, 24000)
            #    audio_clip = AudioFileClip(audio_path)
            #else:
            #    audio_clip = ColorClip(size=(1,1), color=(0,0,0)).with_duration(3).with_audio(None) # Fallback


            # TTS
            # TTS (Fixed for Kokoro-ONNX)
            audio_path = f"temp_{video_id}_{i}.wav"
            try:
                # Use 'kokoro.create' instead of the broken 'pipeline'
                samples, sample_rate = kokoro.create(
                    clean_text, 
                    voice=request.voice, 
                    speed=1.0, 
                    lang="en-us"
                )
                sf.write(audio_path, samples, sample_rate)
                audio_clip = AudioFileClip(audio_path)
            #except Exception as e:
            #    print(f"⚠️ TTS Failed for scene {i}: {e}")
                # Fallback: 3 seconds of silence
            #    audio_clip = ColorClip(size=(1,1), color=(0,0,0)).with_duration(3).with_audio(None)



            except Exception as e:
                print(f"⚠️ TTS Failed for scene {i}: {e}")
                # Create a 3-second real SILENT audio file
                audio_path = f"temp_{video_id}_{i}_silence.wav"
                silence = np.zeros(int(24000 * 3)) 
                sf.write(audio_path, silence, 24000)
                audio_clip = AudioFileClip(audio_path)

             
            # V2.0 Word Sync — pass script text so Whisper mishearings are
            # corrected against the actual words in this scene
            word_data = get_word_timestamps(audio_path, script_text=scene.text)


            # Image
            media_path = os.path.join(BASE_MEDIA_PATH, media_file) if media_file else None

            TARGET_W = 720 if request.orientation == "portrait" else 1280
            TARGET_H = 1280 if request.orientation == "portrait" else 720

            if not media_path or not os.path.exists(media_path):
                clip = ColorClip(size=(TARGET_W, TARGET_H), color=(30,30,30)).with_duration(audio_clip.duration)
            else:
         #      clip = ImageClip(media_path).with_duration(audio_clip.duration)
         #      clip = clip.resized(height=TARGET_H)
         #      clip = clip.cropped(x_center=clip.w / 2, y_center=clip.h / 2, width=TARGET_W, height=TARGET_H)

                clip = ImageClip(media_path).with_duration(audio_clip.duration)
                
                # Scale so both dimensions are AT LEAST as large as target
                scale_w = TARGET_W / clip.w
                scale_h = TARGET_H / clip.h
                scale = max(scale_w, scale_h)  # use the larger scale to cover fully
                
                clip = clip.resized(width=int(clip.w * scale), height=int(clip.h * scale))
                clip = clip.cropped(x_center=clip.w / 2, y_center=clip.h / 2, width=TARGET_W, height=TARGET_H)

           #if request.add_effects: clip = apply_pan_zoom_effect(clip)

            if request.add_effects: 
                            clip = apply_pan_zoom_effect(clip)
                            # Lock size after effects — panning can cause size mismatch during render
                            clip = clip.cropped(x_center=clip.w / 2, y_center=clip.h / 2, width=TARGET_W, height=TARGET_H)

            if request.add_captions:
                word_clips = create_dynamic_captions(
                    word_data,
                    (clip.w, clip.h),
                    active_index=0,
                    caption_position=request.caption_position
                )
                if word_clips:
                    clip = CompositeVideoClip([clip] + word_clips)

            final_clips.append(clip.with_audio(audio_clip))
            gc.collect()
            
        print(f"\n✅ Step 1 Complete: Audio and Frames ready. ({time.time()-start_time:.2f}s)")
        
        #print("🔄 Step 2/3: Applying Transitions...")
        #if request.add_effects and len(final_clips) > 1:
        #    transitioned = [final_clips[0]]
        #    for i in range(1, len(final_clips)):
        #        transitioned.append(final_clips[i].with_effects([vfx.FadeIn(0.6)]))
        #    final_clips = transitioned

        print("🔄 Step 2/3: Applying Transitions...")
        if request.add_effects and len(final_clips) > 1:
            transitioned = [final_clips[0]]
            for i in range(1, len(final_clips)):
                # MoviePy 2.0 uses 'vfx.fadein' (lowercase) or the effect object
                transitioned.append(final_clips[i].with_effects([vfx.FadeIn(duration=0.6)]))
            final_clips = transitioned




        print("🔄 Step 3/3: FINAL RENDERING (Stitching + Music)... This usually takes 2-4 minutes.")
        final_video = concatenate_videoclips(final_clips, method="compose")
        
        if os.path.exists(MUSIC_PATH):
            print("   🎵 Mixing background music...")
            bg_music = AudioFileClip(MUSIC_PATH).with_effects([afx.AudioLoop(duration=final_video.duration)])
            bg_music = bg_music.with_volume_scaled(0.12)
            final_video = final_video.with_audio(CompositeAudioClip([final_video.audio, bg_music]))

        output_name = f"Ghibli_Story_{video_id}.mp4"
        
        # This will show a progress bar in the console
        final_video.write_videofile(
            output_name, 
            fps=24, 
            codec="libx264", 
            audio_codec="aac", 
            threads=1,                                       # Limit threads to save RAM
            temp_audiofile=f"temp-audio-{video_id}.m4a",     # Forces a clean filename
            remove_temp=True,                                # Cleans up automatically
            preset="ultrafast", 
            logger='bar' # This enables the MoviePy progress bar!
        )

        # Cleanup
        for f in glob.glob(f"temp_{video_id}_*.wav"):
            try: os.remove(f)
            except: pass
        
        total_duration = time.time() - start_time
        print(f"\n{'='*60}")
        print(f"🎉 SUCCESS! Video Created: {output_name}")
        print(f"⏱️  Total Time Taken: {total_duration/60:.2f} minutes")
        print(f"📂 Location: {os.path.abspath(output_name)}")
        print(f"{'='*60}\n")
        
        return {"status": "success", "video_path": os.path.abspath(output_name)}
        
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)