"""
tts.py - text to speech: turns your words into a voice track, on your PC.

WHY it exists:
    A voice-over without recording yourself, like CapCut's "text to speech". Nothing is sent
    to the internet.

HOW it works:
    - Windows: the voices already built into Windows (System.Speech), driven by PowerShell.
      Your text is handed over in a FILE, never as part of the command, so words in it can
      never be run as commands.
    - Linux (used for testing): espeak-ng, if installed.

HONEST LIMITS: Windows' built-in voices sound clearly like a computer, and only the languages
    installed in Windows work (Settings > Time & language > Speech > Add voices).

HOW TO IMPROVE: add a natural neural voice engine (check the licence of each voice first).
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

MAX_LETTERS = 3000

# Reads settings from environment variables, so nothing typed by you appears in the script.
_SPEAK = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
if ($env:SF_VOICE) { $voice.SelectVoice($env:SF_VOICE) }
$voice.Rate = [int]$env:SF_RATE
$voice.SetOutputToWaveFile($env:SF_OUT)
$voice.Speak([IO.File]::ReadAllText($env:SF_TEXT, [Text.Encoding]::UTF8))
$voice.Dispose()
"""
_LIST = r"""
Add-Type -AssemblyName System.Speech
[Console]::OutputEncoding = [Text.Encoding]::UTF8
(New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices() |
  Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo.Name }
"""


def _powershell(script: str, env=None) -> str:
    done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=120, env={**os.environ, **(env or {})})
    if done.returncode != 0:
        raise RuntimeError("Windows could not speak the text: " + done.stderr.strip()[-200:])
    return done.stdout


def _espeak():
    return shutil.which("espeak-ng") or shutil.which("espeak")


def voices() -> list:
    """Names of the voices you can choose. Empty = text to speech is not available."""
    try:
        if os.name == "nt":
            return [v.strip() for v in _powershell(_LIST).splitlines() if v.strip()]
        return ["en", "en-us", "hi", "es"] if _espeak() else []
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        return []


def speak(text: str, out: Path, voice: str = "", rate: int = 0) -> Path:
    """Write the spoken text to a .wav file. rate: -5 (slow) to 5 (fast)."""
    text = " ".join(str(text or "").split())[:MAX_LETTERS]
    if not text:
        raise ValueError("Type the words to speak.")
    available = voices()
    if not available:
        raise ValueError("No speech voice is available on this computer.")
    voice = voice if voice in available else ""
    try:
        rate = max(-5, min(5, int(rate)))
    except (TypeError, ValueError):
        rate = 0
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as work:
        words = Path(work) / "words.txt"
        words.write_text(text, encoding="utf-8")
        if os.name == "nt":
            _powershell(_SPEAK, {"SF_TEXT": str(words), "SF_OUT": str(out), "SF_VOICE": voice,
                                 "SF_RATE": str(rate)})
        else:
            subprocess.run([_espeak(), "-v", voice or "en", "-s", str(170 + rate * 20),
                            "-w", str(out), "-f", str(words)], check=True, timeout=120)
    if not out.is_file() or out.stat().st_size < 100:
        raise RuntimeError("The voice file was not written.")
    return out
