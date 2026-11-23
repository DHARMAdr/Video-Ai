#!/usr/bin/env bash
# install_mac_linux.sh - one-time setup on macOS / Linux.
# WHY: creates a private Python environment so ShortsForge does not mix with other projects.
# HOW: run   bash install_mac_linux.sh
# IMPROVE: auto-install ffmpeg with brew/apt when missing.
set -e
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m shortsforge doctor
echo "If ffmpeg is MISSING:  brew install ffmpeg   (mac)   or   sudo apt install ffmpeg   (linux)"
