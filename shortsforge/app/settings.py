"""
settings.py - remembers the assistant's settings (which AI to use, API key, model).

WHY it exists:
    The assistant needs to know WHICH AI to talk to. You choose that once in the app's Settings
    window; this file stores it so you do not have to type it again.

HOW it works:
    - Saved as a small JSON file: Documents/ShortsForge/_settings.json (only on this PC).
    - The API key is stored as plain text in that file. That is normal for desktop apps, but it
      means: do not share that file or the whole ShortsForge folder with other people.
    - public() gives the window a copy where the key is hidden (shows only dots + last 4 letters),
      so the key is never sent back to the browser or to your phone.
    - Three providers are supported:
        "builtin"   = the model inside ShortsForge (free, offline; downloaded once, see localai.py)
        "anthropic" = Claude through Anthropic's API (needs your own API key, billed by use)
        "openai"    = anything that speaks the OpenAI chat format: Ollama or LM Studio running on
                      this PC (free, offline), OpenRouter, and many others

HOW TO IMPROVE:
    - Encrypt the key with the Windows Credential Manager (the `keyring` package).
    - Add more providers or one profile per provider so you can switch quickly.
"""

import copy
import json
import os
import threading
from pathlib import Path

DEFAULTS = {
    "provider": "anthropic",
    "name": "Forge",                       # the assistant's name in the chat
    "anthropic": {"api_key": "", "model": "claude-sonnet-5-5", "base_url": ""},
    "openai": {"base_url": "http://localhost:11434/v1", "api_key": "", "model": "llama3.1"},
    "builtin": {"model": "qwen3.5-9b"},    # which downloaded model to use
    "web": {"enabled": False, "api_key": ""},   # web search is OFF until you switch it on
    "video_folders": [],                   # extra folders where your recordings are
}
MASK = "•"                            # the dot character used to hide keys


def _merge(base: dict, extra: dict) -> dict:
    """Copy of base with the values of extra written over it (one level of nesting)."""
    out = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key].update(value)
        else:
            out[key] = value
    return out


def _mask(key: str) -> str:
    return "" if not key else MASK * 8 + key[-4:]


class Settings:
    """Loads, shows and saves the settings file."""

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self.local_ready = lambda model: False   # server.py plugs in "is this model downloaded?"
        self.data = copy.deepcopy(DEFAULTS)
        if self.path.exists():
            try:
                self.data = _merge(DEFAULTS, json.loads(self.path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass                                   # a damaged file -> start from defaults

    def public(self) -> dict:
        """Settings for the window: keys hidden, plus a 'configured' flag."""
        shown = copy.deepcopy(self.data)
        shown["anthropic"]["api_key"] = _mask(self.data["anthropic"]["api_key"])
        shown["openai"]["api_key"] = _mask(self.data["openai"]["api_key"])
        shown["web"]["api_key"] = _mask(self.data["web"]["api_key"])
        shown["configured"] = self.configured()
        return shown

    def update(self, patch: dict) -> None:
        """Apply changes from the window and save. Hidden keys (dots) mean 'unchanged'."""
        with self._lock:
            clean = copy.deepcopy(patch)
            if isinstance(clean.get("web"), dict) and "enabled" in clean["web"]:
                clean["web"]["enabled"] = bool(clean["web"]["enabled"])
            for provider in ("anthropic", "openai", "web"):
                block = clean.get(provider)
                if isinstance(block, dict):
                    key = str(block.get("api_key", ""))
                    if key.startswith(MASK):
                        block.pop("api_key", None)     # unchanged
                    else:
                        block["api_key"] = key.strip()
                    for field in ("model", "base_url"):
                        if field in block:
                            block[field] = str(block[field]).strip()
            if "provider" in clean and clean["provider"] not in ("anthropic", "openai", "builtin"):
                raise ValueError("Unknown provider.")
            if "video_folders" in clean:
                folders = clean["video_folders"]
                if isinstance(folders, str):
                    folders = folders.splitlines()
                clean["video_folders"] = [str(f).strip().strip('"') for f in folders
                                          if str(f).strip()][:10]
            if "name" in clean:
                clean["name"] = (str(clean["name"]).strip() or "Forge")[:30]
            clean.pop("configured", None)
            self.data = _merge(self.data, clean)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
            try:
                os.chmod(self.path, 0o600)             # only you can read it (ignored on Windows)
            except OSError:
                pass

    def provider_config(self):
        """(provider name, its settings dict)."""
        provider = self.data["provider"]
        return provider, self.data[provider]

    def configured(self) -> bool:
        """True when the assistant has everything it needs to talk to an AI."""
        provider, cfg = self.provider_config()
        if provider == "builtin":
            return bool(self.local_ready(cfg["model"]))
        if provider == "anthropic":
            return bool(cfg["api_key"] and cfg["model"])
        return bool(cfg["base_url"] and cfg["model"])
