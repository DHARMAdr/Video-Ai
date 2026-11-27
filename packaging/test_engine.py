"""
test_engine.py - a REAL test of the built-in AI: real engine, real model, real answer.

WHY it exists:
    The unit tests use a pretend engine. They cannot tell us whether the real llama-server
    accepts our command line, loads a Qwen3.5 model, answers, or can use the app's tools.

HOW it works:
    1. Downloads a model with the same code the app uses (checksum included).
    2. Starts the given llama-server, asks it to reply, then asks a question that needs a tool.
    3. Prints what happened. Exit code 1 if the model cannot be downloaded, started or answered.
    Run:  python packaging/test_engine.py <path to llama-server> [--model qwen3.5-9b]
    The default "tiny" model (0.5 GB) is only for testing; the app does not offer it.

HOW TO IMPROVE:
    - Ask several tool questions and count how often the model picks the right tool.
"""

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortsforge.app import assistant, localai, posttext, server, websearch

TINY = localai._model("Tiny test model", "tests only", "0.8B",
                      "6ab461498e2023f6e3c1baea90a8f0fe38ab64d0", 532517120,
                      "bd258782e35f7f458f8aced1adc053e6e92e89bc735ba3be89d38a06121dc517")
localai._eyes(TINY, "0.8B", "6ab461498e2023f6e3c1baea90a8f0fe38ab64d0", 204987232,
              "56e4c6cfe73b0c82e3e82bc518d7591997e61d81f723fc41a586f4fa69ea2453")


def download(ai, model_id: str) -> bool:
    """Download one file the same way the app does, and say whether it worked."""
    started = time.time()
    ai.start_download(model_id)
    while ai.status()["download"]["state"] in ("downloading", "checking"):
        time.sleep(2)
    result = ai.status()["download"]
    if result["state"] != "done":
        print(f"FAIL download {model_id}:", result["error"])
        return False
    print(f"OK download + checksum of {model_id} ({time.time() - started:.0f} s)")
    return True


def check_eyes(state, ai) -> None:
    """Show the model two made-up pictures. It should see the red square in only one of them."""
    import numpy as np
    from shortsforge.find import vision

    red = np.full((360, 640, 3), 255, np.uint8)
    red[80:280, 220:420] = (0, 0, 255)                      # OpenCV order: blue, green, red
    for name, picture, expected in (("red square", red, True),
                                    ("empty", np.full((360, 640, 3), 255, np.uint8), False)):
        started = time.time()
        answer = vision.ask_frame(assistant.looker(state.settings, ai), picture,
                                  "a big red square")
        print(f"{'OK' if answer['match'] is expected else 'WARN'} picture AI, {name} "
              f"({time.time() - started:.0f} s): {answer}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("engine")
    parser.add_argument("--model", default="tiny")
    args = parser.parse_args()
    os.environ["SHORTSFORGE_LLAMA_SERVER"] = str(Path(args.engine).resolve())
    models = dict(localai.MODELS, tiny=TINY)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        ai = localai.LocalAI(Path(tmp) / "ai", models)
        try:
            has_eyes = "vision" in models[args.model]
            if not download(ai, args.model) or \
                    (has_eyes and not download(ai, args.model + localai.EYES)):
                return 1

            state = server.AppState(Path(tmp) / "out")
            state.local_ai = ai
            state.settings.local_ready = ai.installed
            state.settings.update({"provider": "builtin", "builtin": {"model": args.model}})

            started = time.time()
            ai.ensure_running(args.model)
            print(f"OK engine started and model loaded ({time.time() - started:.0f} s)")

            started = time.time()
            reply = assistant.ping(state.settings, ai)
            print(f"OK answer ({time.time() - started:.0f} s): {reply!r}")
            if not reply or reply == "(no answer)":
                print("FAIL: empty answer")
                return 1

            started = time.time()
            reply, actions = assistant.ask(
                state.settings, [], "Use the list_projects tool, then tell me how many "
                "projects I have.", assistant.ToolBox(state))
            used = "Looked at your projects" in actions
            print(f"{'OK' if used else 'WARN'} tool use ({time.time() - started:.0f} s): "
                  f"actions={actions} reply={reply[:300]!r}")
            # Upload texts for a made-up clip, and one real internet search (Wikipedia).
            started = time.time()
            folder = state.out_dir / "demo"
            folder.mkdir(parents=True)
            (folder / "shorts.json").write_text(json.dumps([{
                "file": "short_01.mp4", "title": "Saving money",
                "text": "The easiest way to save money is to move some of it the day you are paid, "
                        "before you can spend it."}]), encoding="utf-8")
            result = posttext.write_post_texts(
                folder, lambda s, p: assistant.complete(state.settings, ai, s, p))
            print(f"{'OK' if result['written'] else 'WARN'} post text "
                  f"({time.time() - started:.0f} s): {result}")

            try:
                found = websearch.search("Valorant video game")
                print(f"{'OK' if found['results'] else 'WARN'} Wikipedia search: "
                      f"{[r['title'] for r in found['results']]}")
                state.settings.update({"web": {"enabled": True}})
                started = time.time()
                reply, actions = assistant.ask(
                    state.settings, [], "Search the web: which company makes the game Valorant? "
                    "Give the link.", assistant.ToolBox(state))
                used = any(a.startswith("Searched the web") for a in actions)
                print(f"{'OK' if used else 'WARN'} web answer ({time.time() - started:.0f} s): "
                      f"actions={actions} reply={reply[:400]!r}")
            except (ValueError, assistant.AssistantError) as exc:
                print("WARN web search:", exc)
            if has_eyes:                         # an engine that cannot load it is a failure
                state.settings.update({"web": {"enabled": False}})
                check_eyes(state, ai)
            return 0
        except Exception as exc:                                   # noqa: BLE001
            print("FAIL:", exc)
            return 1
        finally:
            ai.stop()
            log = ai.dir / "engine.log"
            if log.exists():
                print("----- last lines of engine.log -----")
                print("\n".join(log.read_text("utf-8", "replace").splitlines()[-25:]))


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    sys.exit(main())
