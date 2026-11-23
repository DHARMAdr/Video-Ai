"""
llm.py - OPTIONAL local AI judge using Ollama (free, runs on your PC, no internet needed).

WHY it exists:
    Rules can't understand meaning ("is this joke actually funny?"). A local language model can
    give a second opinion on the best candidates and write nicer titles. It is optional: if
    Ollama is not running, the tool silently keeps using the rule-based scores.

HOW it works:
    Talks to Ollama's local web address (http://localhost:11434) using only Python's standard
    library, so there is nothing extra to install. Install Ollama from ollama.com and run
    `ollama pull llama3.1:8b` once, then use the option  --llm llama3.1:8b

HOW TO IMPROVE:
    - Ask the model for structured JSON (score + reason + title + hashtags) in a single call.
    - Give the model examples of your own best-performing shorts (few-shot prompting).
    - Add a vision model to judge frames, not just words.
"""

import json
import re
import urllib.request

OLLAMA_URL = "http://localhost:11434/api/generate"


def ask(prompt: str, model: str, timeout: int = 120):
    """Send a prompt to Ollama. Returns the reply text, or None if Ollama is unavailable."""
    body = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
    request = urllib.request.Request(OLLAMA_URL, data=body,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())["response"]
    except Exception:
        return None   # not running / model missing -> caller just skips the LLM


def rate_clip(text: str, model: str):
    """Ask for a 1-10 virality rating. Returns a float, or None if unavailable."""
    prompt = (
        "You are an expert in viral short-form video (YouTube Shorts, Instagram Reels).\n"
        "Rate how likely this transcript is to hold viewers, from 1 (boring) to 10 (viral).\n"
        "Consider: a strong hook in the first sentence, emotion, a clear payoff, and whether "
        "it makes sense without extra context.\n"
        "Reply with ONLY the number.\n\nTRANSCRIPT:\n" + text[:2500]
    )
    reply = ask(prompt, model)
    if not reply:
        return None
    match = re.search(r"\d+(\.\d+)?", reply)
    return min(10.0, float(match.group())) if match else None


def make_title(text: str, model: str):
    """Ask for a catchy title (max 8 words). Returns text or None."""
    prompt = ("Write ONE catchy title (max 8 words, no quotes, no hashtags) for a short video "
              "with this transcript. Reply with only the title.\n\n" + text[:1500])
    reply = ask(prompt, model)
    return reply.strip().strip('"') if reply else None
