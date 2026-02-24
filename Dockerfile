# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install system dependencies
# - ffmpeg: For video/audio processing
# - imagemagick: For MoviePy text rendering
# - libespeak-ng1: For phonemizer (Kokoro TTS)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    imagemagick \
    libespeak-ng1 \
    git \
    build-essential \
    cmake \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# MoviePy/ImageMagick Security Policy Fix
# This allows ImageMagick to process the text labels used for captions
RUN sed -i 's/rights="none" pattern="@\*"/rights="read|write" pattern="@\*"/g' /etc/ImageMagick-6/policy.xml || true

# Set the working directory
WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose the FastAPI port
EXPOSE 8000

# Start the application
CMD ["uvicorn", "app_v3:app", "--host", "0.0.0.0", "--port", "8000"]
