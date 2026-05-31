#!/bin/bash

# This script runs after the container is created.
# The 'set -e' command ensures that the script will exit immediately if a command fails.
set -e

echo "--- Running post-create script ---"
sudo apt update -y
sudo apt upgrade -y
sudo apt install -y ripgrep vim

# Activating the virtual environment
echo "Creating virtual environment..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
.venv/bin/pip install --upgrade pip

# Install Python dependencies from requirements.txt
echo "Installing requirements..."
find . -name "requirements.txt" -exec ./.venv/bin/pip install -r {} \;

echo "Installing project in editable mode..."
./.venv/bin/pip install -e .


# Google cloud
echo "Installing Google Cloud CLI..."
if ! command -v gcloud &> /dev/null; then
    echo "Google Cloud CLI not found, installing..."
    curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
    echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | sudo tee -a /etc/apt/sources.list.d/google-cloud-sdk.list
    sudo apt-get update -y && sudo apt-get install -y google-cloud-cli
else
    echo "Google Cloud CLI already installed."
fi