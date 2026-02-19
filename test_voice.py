from kokoro import KPipeline
import soundfile as sf
import os

print("⏳ Initializing Kokoro (Downloading models if first time)...")
generator = KPipeline(lang_code='a') 

text = "Hello! Your TikTok automation agent is now officially online and ready to create content."

# Generate the audio
results = generator(text, voice='af_bella', speed=1)

# Save the result
for i, (gs, ps, audio) in enumerate(results):
    filename = f'voice_test_{i}.wav'
    sf.write(filename, audio, 24000)
    print(f"✅ Success! Audio saved as: {os.path.abspath(filename)}")
