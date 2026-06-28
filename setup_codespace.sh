#!/bin/bash
# Run this script inside your GitHub Codespace to set up the environment properly

echo "1. Updating package list and installing system dependencies..."
sudo apt-get update
sudo apt-get install -y imagemagick espeak-ng ffmpeg fonts-liberation

echo "2. Fixing ImageMagick policy to allow TextClip generation in moviepy..."
# This removes the restrictive policies that prevent ImageMagick from generating text files
sudo sed -i 's/<policy domain="path" rights="none" pattern="@\*"\/>/<!-- <policy domain="path" rights="none" pattern="@*"\/> -->/g' /etc/ImageMagick-6/policy.xml

echo "3. Installing Python dependencies..."
# Use requirements-cpu.txt since Codespaces generally do not have GPUs
pip install -r requirements-cpu.txt

echo "Setup complete! You can now run the app: python app.py or uvicorn app:app"
