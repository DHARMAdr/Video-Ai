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
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortsforge.app import assistant, localai, server

TINY = localai._model("Tiny test model", "tests only", "0.8B",
                      "6ab461498e2023f6e3c1baea90a8f0fe38ab64d0", 532517120,
                      "bd258782e35f7f458f8aced1adc053e6e92e89bc735ba3be89d38a06121dc517")


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
            started = time.time()
            ai.start_download(args.model)
            while ai.status()["download"]["state"] in ("downloading", "checking"):
                time.sleep(2)
            download = ai.status()["download"]
            if download["state"] != "done":
                print("FAIL download:", download["error"])
                return 1
            print(f"OK download + checksum ({time.time() - started:.0f} s)")

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
