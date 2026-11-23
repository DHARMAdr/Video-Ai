# ShortsForge - Complete Project File

> One file with everything: vision, plan, install steps, how it works, history, and next steps.
> To continue improving later, give this file (and the `shortsforge/` folder) to Claude and say:
> "Read PROJECT.md, then do roadmap item X."

Current version: **0.3.0** (standalone app + window) | Last updated: **2026-11-22**

---

## 1. What this is

ShortsForge is an **independent, offline tool that runs on your own PC**. You give it a long video
(a file, or a link to a video you have rights to). It:

1. listens to the video (speech -> text with word timing),
2. measures loudness and scene cuts,
3. finds every sentence-aligned clip between 20 and 59 seconds,
4. scores each clip 0-100 with a "viral profile" (hook, energy, pace, emotion, completeness, visuals),
5. picks the best non-overlapping clips,
6. renders vertical 1080x1920 MP4 shorts with bold word-by-word captions and a hook title,
7. writes a report explaining WHY each clip was chosen, plus title and hashtag ideas.

No paid API, no cloud, no subscription. An optional local LLM (Ollama) can give a second opinion.

## 2. Honest limits (read this once)

- **It cannot scrape Instagram/YouTube to see "what is viral right now".** Their rules forbid it and the
  data is not public. Instead we encode known viral patterns (strong hook in 3 seconds, fast pace,
  captions, 20-45 s length) in `viral_profile.json`, and the `learn` command measures reference shorts
  that **you** collect and tunes the numbers.
- **No tool can guarantee virality.** The score is a smart heuristic. Real results depend on topic,
  audience, thumbnail/title and luck. Improve it over time with your own analytics.
- **Copyright:** only use videos you own or have permission to reuse. Re-uploading other people's
  videos can get your channel struck.
- It works best on **speech-driven videos** (podcasts, interviews, tutorials, vlogs, talks).
  Music-only or gameplay-without-talking needs the visual/audio upgrades in the roadmap.

## 3. Architecture (data flow)

```
video file / link
      |
  ingest.py ------> download (yt-dlp) + probe size/length (ffprobe)
      |
  transcribe.py --> faster-whisper -> words with timestamps   (cached: work/transcript.json)
      |
  analyze.py -----> loudness per 0.5 s + scene cuts           (cached: work/signals.json)
      |
  segments.py ----> sentences -> candidate clips (20-59 s, cut on sentence ends)
      |
  scoring.py -----> 6 sub-scores -> total 0-100 (uses viral_profile.json)
      |
  llm.py (optional) -> local Ollama re-rates the best candidates
      |
  segments.pick_top -> best N clips that do not overlap
      |
  reframe.py -----> 9:16 plan: face-crop / center / blurred background
  captions.py ----> .ass subtitles (word highlight + hook title)
  render.py ------> ffmpeg: cut + reframe + captions + loudness -> short_XX.mp4
      |
  metadata.py ----> title + hashtags;   pipeline.py writes report.md + shorts.json
```

`pipeline.py` is the conductor. `cli.py` is the command-line front door.

## 4. File map

| File | Job |
|---|---|
| `shortsforge/cli.py` | Commands: `make`, `learn`, `doctor` |
| `shortsforge/pipeline.py` | Runs all steps in order |
| `shortsforge/ingest.py` | Download + read video info |
| `shortsforge/transcribe.py` | Speech to text with word times |
| `shortsforge/analyze.py` | Loudness + scene-cut measurements |
| `shortsforge/segments.py` | Sentences, candidates, picking |
| `shortsforge/scoring.py` | The virality score |
| `shortsforge/viral_profile.json` | The tunable rulebook (weights, hook phrases, ideal ranges) |
| `shortsforge/config.py` | Loads/merges profiles |
| `shortsforge/reframe.py` | 16:9 -> 9:16 |
| `shortsforge/captions.py` | Styled captions |
| `shortsforge/render.py` | Final ffmpeg render |
| `shortsforge/metadata.py` | Title + hashtags |
| `shortsforge/llm.py` | Optional Ollama judge |
| `shortsforge/learn_profile.py` | Learn the profile from reference shorts |
| `shortsforge/killfeed.py` | NEW: finds kills by reading the kill-feed rows |
| `shortsforge/highlights.py` | NEW: groups kills into plays, scores and picks them |
| `shortsforge/calibrate.py` | NEW: tune kill detection on one frame of your footage |
| `shortsforge/imgio.py` | NEW: saves debug PNG pictures (no extra library) |
| `shortsforge/games/valorant.json` | NEW: Valorant settings (area, colours, timings, scores) |
| `tests/test_game.py` | NEW: fake-gameplay tests for detection + rendering |
| `make_valorant.bat` | drag-and-drop for gameplay videos |
| `shortsforge_app.py` | NEW v0.3.0: start button of the standalone app |
| `shortsforge/app/desktop.py` | NEW: opens the window (or browser), self-test |
| `shortsforge/app/server.py` | NEW: local server behind the buttons (secure, localhost only) |
| `shortsforge/app/jobs.py` | NEW: background tasks + progress log |
| `shortsforge/app/static/index.html` | NEW: the window (layout, style, behaviour) |
| `shortsforge/paths.py` | NEW: finds bundled ffmpeg / speech model, output folder |
| `packaging/ShortsForge.spec` | NEW: PyInstaller recipe for the app folder |
| `packaging/fetch_assets.py` | NEW: downloads ffmpeg + speech model for the bundle |
| `packaging/build_windows.bat` | NEW: build the app on your own PC |
| `packaging/installer.iss` | NEW: Inno Setup script for Setup.exe |
| `.github/workflows/build-windows.yml` | NEW: GitHub builds the Windows app for you |
| `requirements-app.txt`, `requirements-build.txt` | NEW: packages inside / tools for building |
| `tests/test_app.py` | NEW: tests for the window's server |
| `tests/test_core.py` | Automatic tests |
| `install_windows.bat`, `install_mac_linux.sh` | One-time setup |
| `make_shorts.bat` | Drag-and-drop a video to make shorts |

Every code file starts with a comment block in simple English: **WHY** it exists, **HOW** it works,
**HOW TO IMPROVE** it.

## 5. Install (Windows, one time)

1. Install **Python 3.11** from python.org. Tick **"Add Python to PATH"**. (3.10-3.12 are safest.)
2. Install **ffmpeg**: open PowerShell and run `winget install Gyan.FFmpeg`. Close and reopen the terminal.
3. Unzip `ShortsForge.zip` somewhere, e.g. `C:\ShortsForge`.
4. Double-click **`install_windows.bat`**. Wait a few minutes. At the end the "doctor" check should
   show `[OK]` for everything (yt_dlp / cv2 may show optional).
5. (Optional) install **Ollama** from ollama.com, then run `ollama pull llama3.1:8b` for the LLM judge.

macOS/Linux: `bash install_mac_linux.sh` (install ffmpeg with brew / apt first).

## 5b. STANDALONE APP (new in v0.3.0): nothing to install on the PC that uses it

The app is a normal Windows program: **unzip (or run Setup.exe) and double-click `ShortsForge.exe`**.
Python, ffmpeg, the AI libraries and the speech model are all INSIDE the app folder (~1 GB).
No Python, no Node, no ffmpeg install. Works offline for local video files. (Links need internet.)

**What you see:** a window. Left: pick a video, choose "Someone talking" or "Valorant gameplay",
settings, **Make shorts**. Right: a timeline of your source video (yellow bars = clips, red ticks =
kills found) and one row per clip with a preview, title, Start/End boxes and **Export again** (trim and
re-render), **Copy hashtags**, **Show in folder**. Valorant mode has **Check kill detection** (the
calibrate tool with pictures). Finished shorts are saved in `Documents\ShortsForge\`.

**How you get the app (you do not need to install anything to build it):** GitHub builds it for you.
1. Create a new repository on github.com (private is fine), e.g. `ShortsForge`.
2. Upload the whole project folder to it (including the hidden `.github` folder). Easiest with the free
   **GitHub Desktop** app: File > Add local repository > Publish. Or in a terminal inside the folder:
   `git init`, `git add .`, `git commit -m "ShortsForge"`, `git branch -M main`,
   `git remote add origin https://github.com/YOURNAME/ShortsForge.git`, `git push -u origin main`.
3. On GitHub open the **Actions** tab > **Build Windows app** > **Run workflow**. Wait ~20-30 minutes.
4. Open the finished run and download **ShortsForge-Windows** (a zip, ~1 GB). Unzip, double-click
   `ShortsForge.exe`. (If **ShortsForge-Setup** also appears, that is a normal installer.)
5. Windows may show a blue "Windows protected your PC" screen because the app is not signed:
   click **More info > Run anyway**. (Signing needs a paid certificate; see roadmap.)
Alternative: build on your own PC with `packaging\build_windows.bat` (needs Python 3.11 on that PC only).
Each new version: upload the new files, run the workflow again. Tag `v0.3.1` to publish on "Releases".

Where things live inside the app folder: `ShortsForge.exe`, `bin\` (ffmpeg), `models\small\` (speech
model), `_internal\` (libraries). Errors are logged to `Documents\ShortsForge\app.log`.
To use another speech model, put its folder in `models\<name>\`.

Developer way (no packaging): `pip install -r requirements-app.txt`, then `python shortsforge_app.py`
(add `--browser` to use your browser instead of the window). The old command-line tool still works.

Safety design of the window: it talks to a tiny server on 127.0.0.1 only, protected by a secret token that
changes at every start; it only serves files from the output folder.

**Honest status of the standalone build:** the app code, window and server are tested (see section 9). The
bundle was built and self-tested on **Linux** here, including a full game job running inside the packed
program. The **Windows** build itself could not be run here, so the first GitHub build may need a fix: if
the workflow fails, open the failed step, copy the red text and send it to Claude with this file.
FFmpeg (GPL build) is shipped inside; if you share the app, keep a link to ffmpeg.org (see fetch_assets.py).

## 6. How to use

Easiest: **drag a video onto `make_shorts.bat`**.

Or in a terminal inside the project folder (after `.venv\Scripts\activate`):

```
python -m shortsforge make "C:\videos\podcast.mp4" --count 5
python -m shortsforge make "https://youtube.com/watch?v=..." --count 3 --reframe blur
python -m shortsforge make video.mp4 --dry-run          (analyse only, no rendering: fast preview)
python -m shortsforge make video.mp4 --llm llama3.1:8b  (use the local LLM second opinion)
python -m shortsforge make video.mp4 --model medium     (more accurate speech recognition)
python -m shortsforge make video.mp4 --language hi      (force a language, e.g. Hindi)
python -m shortsforge learn "C:\reference_shorts"       (tune the profile from 3+ reference shorts)
python -m shortsforge doctor
```

Results appear in `output\<video-name>\`:
`clips\short_01.mp4 ...`, `report.md` (why each was chosen + title/hashtags), `shorts.json`.

Tip: run with `--dry-run` first, read `report.md`, then render. The first run downloads the Whisper
model once. Re-running on the same video reuses the cached transcript.

## 6b. GAME MODE: Valorant kill highlights (new in v0.2.0)

Like paid tools (Opus Clip etc.) but local and free: it watches the **kill feed** (top-right) of your
gameplay recording, finds every kill, groups fast kills into plays (double / triple / quadra / ace),
ranks them and renders vertical shorts with **DOUBLE KILL / TRIPLE KILL popups**.

Quick start: drag a recording onto **`make_valorant.bat`**. Results: `output\<name>\clips\`, and
`report.md` lists every kill time found.

**Do this ONCE first (2 minutes) - calibrate on your own footage.** Kill-feed position/colour depends on
your resolution, HUD and colour settings, and I could not test on real Valorant footage here.
1. Find a moment just after you got a kill (kill feed showing your row). Note the second, e.g. 123.
2. `python -m shortsforge calibrate "game.mp4" --time 123`
3. Open `output\_calibrate\full_frame.png` (red box must sit on the kill feed), `mask.png` (white = what the
   detector thinks is a "my kill" row) and read the printed "rows detected" number.
4. Red box wrong? add `--roi x0,y0,x1,y1` (fractions, e.g. `0.60,0.03,1.0,0.45`) and repeat.
   Mask empty/wrong? copy the printed suggested `highlight` JSON into `my_valorant.json` and add
   `--game-profile my_valorant.json` to all commands.
5. Check the whole video: `python -m shortsforge kills "game.mp4" --debug` lists every kill and saves a
   picture per kill in `output\<name>\debug\` (green lines = rows found). Compare with what really happened.

Commands:
```
python -m shortsforge valorant game.mp4                         (5 best plays, center layout)
python -m shortsforge valorant game.mp4 --count 10 --min-kills 2   (only doubles or better)
python -m shortsforge valorant game.mp4 --layout stack --facecam 0,0.7,0.25,0.3
        (gameplay on top + facecam below; facecam area = x,y,width,height as fractions of the frame)
python -m shortsforge valorant game.mp4 --layout blur           (whole picture, nothing cropped)
python -m shortsforge valorant game.mp4 --speech-captions       (also caption your voice comms)
python -m shortsforge valorant game.mp4 --pre 5 --post 3 --chain-gap 10   (longer lead-in/out)
python -m shortsforge valorant game.mp4 --dry-run               (detect + plan only)
```
Layouts: `center` zooms on the crosshair area (loses the sides/kill feed), `blur` shows everything,
`stack` = gameplay + facecam. Settings live in `shortsforge/games/valorant.json` (area, colours,
timings, score table). Scoring: base by kills (1K=30, 2K=55, 3K=72, 4K=88, ACE=100) + up to +10 for a fast
chain + up to +10 for loud audio.

How detection works: ffmpeg samples only the kill-feed area 8x per second; pixels with the highlight
colour are found; wide bars touching the right edge = kill-feed rows; every time the row count goes up =
one kill. Fake red flashes, left-side boxes and teammate rows are rejected (covered by tests).

Known limits of game mode: colours/area are best guesses until calibrated; a feed row vanishing in the same
1/8 s that another appears can hide one kill; deaths/assists may be highlighted too in some HUD settings
(check `--debug` pictures); scanning an hour of 1080p60 takes roughly 5-20 minutes (ffmpeg decoding).

## 7. Tuning (no coding needed)

Open `shortsforge/viral_profile.json`:
- `weights` - how much hook / energy / pace / emotion / completeness / visual matter.
- `hook_patterns` - phrases that make a strong opening. Add the ones common in YOUR niche.
- `emotion_words` - words that raise emotion score.
- `min_seconds`, `max_seconds`, `ideal_seconds` - clip length rules.
- `caption` - font, size, highlight colour (BGR hex), position, uppercase on/off.

## 8. Roadmap (steps ahead)

| Phase | Goal | Status |
|---|---|---|
| 0 | Plan + architecture | Done |
| 1 | Core pipeline: transcript, scoring, cut, 9:16, captions, report | **Done (v0.1.0, tested)** |
| 1b | **Valorant kill-highlight mode (v0.2.0)** | **Done, logic tested on fake footage; needs your calibration** |
| 2 | Window: pick video, preview clips, trim + export again, timeline, kill check | **Done (v0.3.0)** |
| 2b | Standalone Windows app via GitHub build (no installs) | **Done, first Windows build still to be run by you** |
| 2c | More editing in the window: caption style, crop position, music, drag handles on the timeline, cancel button, progress bar | Next |
| 2d | Online AI mode: type a request ("find the funniest 30 s") answered by a cloud model with your API key; optional, offline stays default | Planned |
| 2e | Icon, code signing, auto-update, Mac build | Planned |
| 3 | Moving face-follow crop, two-speaker split screen, screen-recording zoom | Planned |
| 4 | Better "viral brain": LLM JSON judge, topic diversity, learn hooks from references, train on your analytics | Planned |
| 5 | More games (Apex, CS2, Fortnite profiles), kill-synced zoom punch, round/clutch/headshot detection, OCR of names, kill-sound confirmation. Other non-speech content: laughter/applause detection, motion + emotion, gameplay highlights | Planned |
| 6 | GPU encoding (NVENC), parallel renders, batch folders, progress bar | Planned |
| 7 | Extras: background music with ducking, emoji captions, intro/outro, auto-upload via official APIs | Planned |

## 9. Test status

Run `python -m unittest discover tests -v` (about 2 minutes, mostly the end-to-end render).
Verified in the build environment (15 tests: `python -m unittest discover tests -v`): scoring logic, candidate cutting, caption generation, and a full
end-to-end run on a synthetic video (output verified as 1080x1920 MP4 with captions).
Game mode was verified only on a FAKE kill feed (4 real kills found, 3 look-alike distractors rejected, all 3 layouts render 1080x1920 with popups). Window/server (v0.3.0): security rules, job progress, clip streaming with seeking, trim + export again, kill check, and the real page driven in a headless browser (no script errors). Packaged bundle: built and self-tested on Linux, and a full game job ran inside the packed program. **Not verified here (needs your PC):** the Windows build/installer/native window (pywebview), file-picker dialog, GitHub workflow run, real Valorant colours/position (use `calibrate`), real speech recognition with faster-whisper (the model must be
downloaded), yt-dlp downloads, the Ollama LLM step, and face-crop on real faces. If any of these fail
on your PC, send the error text to Claude together with this file.

## 10. History / changelog (oldest to latest)

- **2026-11-22, v0.1.0** - Project planned and built from scratch in chat.
  - Chose a fully local stack: ffmpeg + faster-whisper + numpy + OpenCV (+ optional Ollama).
  - Chose sentence-aligned candidate clips so shorts never start/end mid-sentence.
  - Built the 6-part heuristic virality score driven by an editable JSON profile.
  - Decided NOT to scrape Instagram/YouTube; added `learn` to tune from reference videos instead.
  - Built reframing (auto/face/center/blur), word-highlight captions with hook title, loudness
    normalisation, report.md with reasons, title and hashtag ideas.
  - Added Windows installer, drag-and-drop launcher, and tests (5 passing).

- **2026-11-22, v0.2.0** - Valorant kill-highlight mode.
  - New: `killfeed.py` (kill-feed row detection with ffmpeg + numpy, no AI model needed),
    `highlights.py` (multi-kill grouping, scoring, selection), `calibrate.py` + `kills --debug`
    (tuning tools), `games/valorant.json`, kill popups (captions.py), gameplay layouts center / blur /
    stack-with-facecam (reframe.py), `valorant`, `kills`, `calibrate` commands, `make_valorant.bat`.
  - Refactor: pipeline `_open_source()` shared by both modes. Added 6 tests (`tests/test_game.py`).
  - Decision: detect kills visually from the feed (works offline, no GPU); defaults are best guesses,
    so calibration is part of the workflow instead of pretending they are exact.

- **2026-11-23, v0.3.0** - Standalone app.
  - New: desktop window (local server + web page, pywebview shell with browser fallback), background
    jobs with live log, clip preview, trim + "Export again" (project.json remembers settings),
    timeline strip with clips and kills, kill-detection check with pictures.
  - Bundle-ready code: `paths.py` (bundled ffmpeg/model lookup, hides console windows on Windows),
    yt-dlp used as a library (the old `python -m yt_dlp` cannot work inside an .exe), speech model loaded
    from the app folder, shared `_render_short()` used by first render and re-export.
  - Packaging: PyInstaller spec, asset fetcher, local build script, Inno Setup installer, GitHub Actions
    workflow that builds + self-tests the Windows app. `--selftest` and `--no-open` options added.
  - Decision: offline-first. An online AI chat mode is planned as optional (needs API key + internet).

*(Add a new line here every time something changes. Keep this file as the single source of truth.)*

## 11. Prompt to resume with Claude

> I'm continuing the ShortsForge project. Here is PROJECT.md and the `shortsforge/` folder.
> Please read PROJECT.md first. Then implement: **[roadmap item / bug + error text]**.
> Keep the simple-English WHY / HOW / HOW TO IMPROVE comments in every code file, run the tests,
> update the changelog and give me the updated files plus the steps to install them.
