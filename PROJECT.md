# ShortsForge - Complete Project File

> One file with everything: plan, guide, how it works, tests and history.
> To continue later, give this file and the repo https://github.com/DHARMAdr/Video-Ai to Claude (see Part 7).

Current version: **0.11.0** (background removal, tracking, text to speech, more editor tools, keyless search) | Last updated: **2026-11-28**

**Contents:** 1 Overview - 2 Project plan - 3 User guide - 4 How it is built - 5 Test status - 6 History - 7 Resume prompt

---

## Part 1. Overview

ShortsForge is an **independent, offline tool that runs on your own PC**. You give it a long video
(a file, or a link to a video you have rights to). It:

1. listens to the video (speech -> text with word timing),
2. measures loudness and scene cuts,
3. finds every sentence-aligned clip between 20 and 59 seconds,
4. scores each clip 0-100 with a "viral profile" (hook, energy, pace, emotion, completeness, visuals),
5. picks the best non-overlapping clips,
6. renders vertical 1080x1920 MP4 shorts with bold word-by-word captions and a hook title,
7. writes a report explaining WHY each clip was chosen, plus title and hashtag ideas.

No paid API, no cloud, no subscription needed. The assistant has a built-in offline AI (v0.6.0); an optional
local LLM (Ollama) can give a second opinion on clips.

### Honest limits (read this once)
- **It cannot scrape Instagram/YouTube to see "what is viral right now".** Their rules forbid it and the
  data is not public. Instead we encode known viral patterns (strong hook in 3 seconds, fast pace,
  captions, 20-45 s length) in `viral_profile.json`, and the `learn` command measures reference shorts
  that **you** collect and tunes the numbers.
- **No tool can guarantee virality.** The score is a smart heuristic. Real results depend on topic,
  audience, thumbnail/title and luck. Improve it over time with your own analytics.
- **Copyright:** only use videos you own or have permission to reuse. Re-uploading other people's
  videos can get your channel struck.
- It works best on **speech-driven videos** (podcasts, interviews, tutorials, vlogs, talks).
  For games use Valorant mode or Find.

---

## Part 2. Project plan (beginning to end)

### Goal
A free, private Windows app that turns your long videos into good vertical shorts, finds the moment you ask for,
lets you finish the edit by hand, and has an assistant that can do the same by chat or voice.

### How we know it works (targets, **none measured on your footage yet**)
| Area | Target |
|---|---|
| Kill finding | at least 9 of 10 of your kills found, at most 1 wrong in 10 |
| "Find a kill of agent X" | the right clip is among the first 3 results |
| Talking videos | the speaker stays in frame; clips start and end on one topic |
| Editor | a 60-second short can be finished without opening another program |
| Stability | no crash or silent failure in a week of use |

### Phases
| Phase | What | State |
|---|---|---|
| 0 | Plan and design | Done |
| 1 | Core: speech to text, scoring, cut, 9:16, captions, report | Done (v0.1.0) |
| 2 | Valorant kill highlights; teach your name and kills | Done (v0.2.0, v0.8.0) |
| 3 | Standalone Windows app built by GitHub; window; phone access | Done (v0.3.0, v0.4.0) |
| 4 | Assistant: commands, memory, offline AI, post texts, web search, voice | Done (v0.4.0 - v0.8.0) |
| 5 | Manual editor, then timeline with layers, keyframes, shortcuts | Done (v0.8.0, v0.9.0) |
| 6 | Find a described moment | Done (v0.9.0) |
| 7 | Topic-aware clips, speaker-following crop, film strips, waveforms, multi-select | Done (v0.10.0) |
| **8** | **Try on your real videos and tune** (started: one real PUBG feed) | **Next, most important** |
| 9 | Speed: graphics card for speech and video export; progress bar; cancel button | Planned |
| 10 | Editor depth: groups, compound clips, curve speed, match cut, masks, blend modes, ready-made looks | Done (v0.11.0); music ducking still planned |
| 11 | Smarter vision: better face detector, two-person split screen, headshot/clutch/ace detection, more games | Planned |
| 12 | Background removal, motion tracking, text to speech, search without a key | Done (v0.11.0), basic quality |
| 13 | Release: icon, code signing, auto-update, upload through official YouTube/Instagram APIs, learning from your analytics | Planned |

**Done when:** phase 8: the targets above are measured on your videos and the misses fixed. Phase 9: a 1-hour match
is processed measurably faster on your RTX 5060 Ti. Phase 10: no editing step forces you into another editor.
Phases 11-13: chosen by what you miss most after using phases 8-10.

### Still not like CapCut, and what each needs
| Missing or weaker than CapCut | What it needs |
|---|---|
| The live preview does not show masks, removed backgrounds, curve ramps or exact blends (Quick preview does) | A new preview engine: large rewrite |
| Background removal knows only people near the camera; hair edges are rough | A larger matting model, graphics card support |
| Tracking can lose a target that turns, hides or leaves | A learned tracker |
| Text to speech sounds like a computer (Windows' own voices) | A neural voice whose licence allows your use |
| Masks cannot move; speed curves are chosen from a list | Only more programming |
| Music ducking, noise removal, auto beat marks | Only more programming |
| CapCut's templates, effects, stickers and music | Content you have the rights to. Theirs cannot be copied |
| No Windows warning on install | A paid code-signing certificate |

### What is needed from you (no extra access to your accounts or PC is needed)
1. **A gameplay recording of a few minutes**, or full-size screenshots of the kill feed, with the times and agents
   of the real kills. This limits accuracy the most.
2. **A short talking video with two people**, to check the speaker-following crop.
3. **Run the app and report:** Settings > Troubleshoot > Make a report, plus screenshots of anything wrong.
4. Optional: a free Tavily key (below). Type it only into the app, never into a chat.
5. Optional: your own fonts, music, stickers; later a signing certificate.

### Web search: built in, and Tavily (optional)
**Built in (v0.11.0, no key):** asks Bing and Wikipedia (also DuckDuckGo, Yahoo, Mojeek, news, Stack Overflow, GitHub
and game wikis when they suit and answer), mixes the lists, opens the best pages and keeps the paragraphs that
answer. Code: `shortsforge/app/localsearch/`.
**Measured** with `packaging/test_search.py` on GitHub's computers: the answer was in the results for **18 of 20**
easy fixed questions in the latest run (earlier runs while it was being fixed: 15 and 12). DuckDuckGo, Yahoo and
Mojeek refused those computers, so it mostly relied on Bing and Wikipedia. This is **not** a comparison with Tavily,
and it has not been run from your home connection. These services can change their pages or refuse programs at any
time (their terms may also limit automated use), so keep it to normal personal use.
**Tavily (optional, free plan):** usually steadier. If it fails, the built-in search takes over.
1. Open https://app.tavily.com and sign up: 1,000 credits a month, no card, a basic search costs 1 credit
   (Tavily's docs, checked 2026-11-27). Nothing needs to be bought.
2. Copy your API key.
3. ShortsForge > **Settings** > tick **Let the assistant search the internet** > paste into **Tavily key** > **Save**.

Search does not make the AI think better; for that choose a stronger model (Settings > Claude, paid by use).

### What came from ClipsAI
From https://github.com/DHARMAdr/clipsai (MIT licence): finding topic changes, and cropping by camera cuts, faces
and mouth movement. ShortsForge uses **its own lighter code** for both: ClipsAI's PyTorch models would add
gigabytes, and its speaker separation needs a Hugging Face token. See `THIRD_PARTY_NOTICES.md`.

### Risks
| Risk | What we do |
|---|---|
| Detection tuned on drawn test videos fails on real footage | Phase 8 before adding more features |
| A downloaded tool changes and breaks the app (happened with FFmpeg and OpenCV) | Versions held (FFmpeg 8.1, OpenCV 4); real face-detector test added |
| Small offline AI states wrong things | Actions are listed under answers; invented links are removed |
| Copyright | Only use videos and music you have the rights to |

### Working rules
Simple-English WHY / HOW / HOW TO IMPROVE comments in every code file; test before pushing; tests for new things;
keep this file current; push to main, build the Windows app, report honestly what was not tested.

---

## Part 3. User guide

### Install or update
1. Close ShortsForge. Open https://github.com/DHARMAdr/Video-Ai/actions and click the newest green **Build Windows app**.
2. Under **Artifacts** download **ShortsForge-Setup**, unzip, run it. It installs over the old version; videos,
   settings and the downloaded AI model stay. The top left shows the version number.
3. If Windows says "Windows protected your PC": **More info** > **Run anyway** (the app is not signed).

### First 5 minutes
- Create tab: Browse (choose a video) or paste a link > pick "Someone talking" or "Valorant gameplay" > **Make shorts**.
  A yellow progress strip shows the work. Long videos take minutes (it is all done on your PC).
- Clips tab: watch each short, change Start/End and press **Export again**, **Download**, or **Add clip** for a new
  time range. **Show in folder** opens `Documents\ShortsForge\<project>\clips\`.
- Ask Forge tab: the AI assistant (see below). It needs one setup step first.
- Errors are written to `Documents\ShortsForge\app.log`.
- Talking videos with **auto** or **face** framing move the crop to the person whose mouth is moving.

### Make Valorant kills work (once)
**If it says no kills (do this once)**
1. **Teach** tab > Browse your gameplay video > Load.
2. Pause where YOUR kill is in the kill feed > **Draw my name box** around your name only.
3. Go to 4 or more of your kills and press **Mark a kill here** each time.
4. **Learn from my kills**. Read the answer: it says how many of your marks it found.
5. Create tab > Valorant gameplay > Make shorts.
Without teaching, you still get "ACTION MOMENT" clips (picked by sound and movement, not confirmed kills).

**Forge cannot find a video?** It searches Videos, Desktop, Downloads, Documents and Pictures (also OneDrive).
Add other drives or folders in Settings > Video folders. Try: "find my valorant video".

**Voice:** Ask Forge tab > 🎤 > press Allow the first time > speak. It stops after a short silence.
**Commands:** "open the editor", "dark mode", "make clip 2 black and white", "join clips 1 and 3",
"add text \"WOW\" to clip 1", "delete clip 2", "restore the clip". With the AI connected you can say it in your own words.

### Find a moment, and the Editor
**Find a moment (Find tab)**
1. Choose the video.
2. Do this once per character: **Load the video above**, pause where that character's icon shows in the kill feed,
   type the name (for example Jett), pick **kill-feed icon**, press **Draw box** and box the icon tightly.
   Also teach your own name on the **Teach** tab if you have not.
3. Type what you want and press **Search**. Examples: `find where I kill Jett`, `when Raze kills me`,
   `top 3 triple kills in the last 10 minutes`, `where I say "nice shot"`, `my first kill, 20 second clip`.
4. Check each picture (Play), untick wrong ones, press the button to make clips.
- Other things on screen ("victory"): teach a picture of kind **on screen**, then search its name.
- Describe in your own words ("the spike being planted"): Settings > Built-in AI > download a model, then
  **Download picture reader**. Frames never leave your PC. This is slow and can be wrong.
- You can also ask Forge: "find when Raze kills me".

**Editor (Editor tab)**
Add video, then work on the timeline: drag a piece to move it, drag its ends to trim. Add pictures, videos on top,
stickers, text, sounds and **Auto captions**. Click an item to change it (filters, speed, green screen, fades,
animation). **Add keyframe**: save zoom/position at one time, move, change, save again. Quick preview shows the
real result; the small window above the timeline is only a close guess. Export > Clips > **Edits**.

| Keys | Does |
|---|---|
| Space; Left/Right; Shift+Left/Right | play; one frame; ten frames |
| Up/Down; Home/End | previous/next cut; start/end |
| Ctrl+B; Ctrl+Shift+B | split; split every track |
| Q; W; Delete | cut left of the red line; cut right; delete |
| V; A; B | switch a piece off/on; select mode; split mode |
| Ctrl+click; Ctrl+A; [ / ]; Esc | select several; all; left/right of the red line; none |
| I; O; Alt+X | mark in; mark out (only that part is exported); clear |
| Ctrl+C/X/V; Ctrl+Z; Ctrl+Shift+Z | copy/cut/paste; undo; redo |
| Ctrl+Shift+S; Ctrl+R; Ctrl+. / Ctrl+, | extract/restore sound; speed box; volume up/down |
| Alt+K; N | add keyframe; snapping |
| Ctrl+= / Ctrl+-; Shift+Z; Ctrl+scroll | zoom timeline; fit; zoom |
| Ctrl+Shift+F; Ctrl+I; Ctrl+N; Ctrl+E | full screen; add video; clear; export |
| Ctrl+G; Ctrl+Shift+G; Alt+G; Alt+Shift+G | group; ungroup; compound clip; break it apart |

The keys follow CapCut's usual Windows keys, from a public list (CapCut's can differ per install).
Ctrl+E for export is this app's own.

The editor timeline shows film strips and sound waves.

**Newer tools (v0.11.0).** Click an item to find them. Use **Quick preview** to see the real result.
- **Background behind people** (video piece): blur, black, white or green. **Remove the background** (picture or video
  on top) keeps only the people. Best with one person close to the camera. Pieces up to 3 minutes.
- **Motion tracking:** add a sticker or picture, drag it over the thing to follow, press **Follow what is under it**.
  Put the box on a detailed spot. The piece under it must be plain (no reverse, curve, rotate, mirror or keyframes).
- **Text to speech:** button at the top. Uses Windows' voices; for more, Windows Settings > Time & language >
  Speech > Add voices.
- **Curve speed, masks, blend modes, ready-made looks and text styles:** in the settings of the selected item.
- **Match cut:** moves the cut between this piece and the next to the two most alike moments.
- **Group / Compound clip:** select several with Ctrl+click first.

### Assistant
**Setting up the assistant (Settings, bottom-left on PC, gear icon on phone)**
- **Option 0, built in (new in v0.6.0), free and offline:** choose **Built-in**, keep **Qwen3.5 9B** (for an
  8 GB graphics card like an RTX 5060 Ti with 16 GB RAM), press **Download** (5.7 GB, once; it can be cancelled
  and resumed), wait for "Ready", press **Save and test**. The first answer is slower while the model loads.
  After 10 minutes without a question it is unloaded to free graphics memory. Close games while chatting.
  If it is slow or fails, pick **Qwen3.5 4B** (2.7 GB). Models are kept in `%LOCALAPPDATA%\ShortsForge\ai`
  (paste that into Explorer); **Delete model** frees the space (uninstalling the app does not).
  Engine messages are in `engine.log` in that folder.
- **Titles and hashtags (v0.7.0):** open a project in **Clips**, press **Write titles & hashtags (AI)**, then
  **Copy post text** on a clip. Or ask in chat: "write titles and hashtags for my last project, in Hindi".
  Saved to `post_texts.txt` in the project. The title written on the video is not changed. The AI only knows
  what was said (talking videos) or the kill label (game videos); it cannot see the video.
- **Web search (v0.7.0), off by default:** Settings > tick **Let the assistant search the internet** > Save.
  Works without a key (built-in search); with a free Tavily key it asks Tavily first (Part 2).
  Search words leave your PC, and opened websites see your internet address. After searching, the assistant will not change clips or memory in that message.
- Option A, closest to Claude: choose **Claude**, paste an API key from console.anthropic.com (you add a few
  dollars of credit there; it is billed by use and is separate from a claude.ai subscription). Press **Save and test**.
- Option B, free and offline: install **Ollama** (ollama.com) on the PC, run `ollama pull llama3.1` once, then in
  Settings choose **Other AI > Ollama**, model `llama3.1`. Smaller local models are less clever than Claude.
- Option C: **LM Studio** or **OpenRouter** work the same way through "Other AI".
- Then in Ask Forge you can chat about anything, and say things like "make 5 shorts from my last video",
  "find where I talk about pricing and make a short from it", "trim clip 2 to 0:40-1:10".
- **Voice:** Ask Forge > microphone button > Allow > speak.

**Commands, search and memory**
- Commands work with NO AI and no internet: "make 5 shorts from my last video", "make valorant shorts with at
  least 2 kills", "trim clip 2 to 0:40-1:10", "add a clip from 1:05 to 1:40 called Big moment", "find where I
  talk about pricing", "search all my videos for budget", "show my projects", "status", "help". Answers marked
  "Instant, no AI used". Anything else goes to the connected AI.
- Better search (BM25) across one or all projects. Memory ("remember that I prefer blur"), view/clear in Settings.
- Thumbs up/down under answers are saved to `Documents\ShortsForge\_feedback.jsonl`: this is your future
  training / test data (see roadmap "fine-tuning"). Do not share that file if chats are private.
- Drag a video file onto the window to add it (it is copied into `_uploads`). Quick-action buttons in the chat.
- How to teach it a new phrasing: add a row to `CASES` in `tests/test_router.py`, then fix `router.py` until the
  test passes. Real phrases that failed are in the thumbs-down feedback file.

**Honest limits**
- The assistant is only as smart as the AI you choose. The built-in 9B/4B models are much less capable than
  Claude: they can misunderstand requests, pick the wrong tool or state wrong facts. Check what they did
  (the actions are listed under each answer). It has no internet unless you switch on web search. With a Claude API key it is Claude, with tools to operate this app.
- Chat is not streamed word by word yet; you see a typing indicator, then the answer.
- Not verified here: the real Windows window (pywebview), the Browse dialog, a real Anthropic API call (tested
  against a fake server only), real Valorant colours (use Check kill detection once).

### Phone (same Wi-Fi)
Settings > **Turn on phone access** > scan the QR code with the phone camera. The phone page is the same app:
tabs at the bottom, **Upload** to send a video from the phone, then Make shorts; the PC does the work.
Windows asks about the firewall once: choose **Private networks**. Turn it off when done. The phone cannot change
settings, open folders, or read PC files outside what it uploaded. Traffic is not encrypted: trusted Wi-Fi only.
The PC must stay on, awake and running ShortsForge.

### Problems
Settings > Troubleshoot > Make a report > Copy. Send it with a screenshot. Errors are also in `Documents\ShortsForge\app.log`.

### Tuning (no coding needed)
Open `shortsforge/viral_profile.json`:
- `weights` - how much hook / energy / pace / emotion / completeness / visual matter.
- `hook_patterns` - phrases that make a strong opening. Add the ones common in YOUR niche.
- `emotion_words` - words that raise emotion score.
- `min_seconds`, `max_seconds`, `ideal_seconds` - clip length rules.
- `caption` - font, size, highlight colour (BGR hex), position, uppercase on/off.

### Command-line use (developers)
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

### Valorant mode from the command line
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

---

## Part 4. How it is built

### How a video flows through it
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

Newer parts: `topics.py` (topic changes), `follow.py` (moving crop), `find/` (find a moment), `editor.py` +
`editor_layers.py` (timeline rendering), `app/` (window, server, assistant, built-in AI).

### File map
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
| `shortsforge/app/static/index.html` | v0.4.0 REWRITTEN: Create / Clips / Ask Forge screens, phone layout, dark mode, settings |
| `shortsforge/app/assistant.py` | NEW v0.4.0: the AI assistant (Claude API + OpenAI-compatible AIs, tool loop, 9 tools) |
| `shortsforge/app/settings.py` | NEW v0.4.0: saves which AI to use + API key (key hidden from the page) |
| `shortsforge/app/lan.py` | NEW v0.4.0: phone access helpers (PC address, private-network check, QR code) |
| `shortsforge/app/localai.py` | NEW v0.6.0: built-in offline AI: model list, checked + resumable download, starts/stops llama-server |
| `packaging/test_engine.py` | NEW v0.6.0: real test of the engine with a real model (run by the build) |
| `.github/workflows/test-ai-model.yml` | NEW v0.6.0: run by hand to try the real 9B / 4B model |
| `tests/test_localai.py` | NEW v0.6.0: download, engine lifecycle (pretend engine), routes, speech CPU fallback |
| `shortsforge/app/posttext.py` | NEW v0.7.0: AI writes title, description, hashtags per clip |
| `shortsforge/app/websearch.py` | Opt-in search (built in, or Tavily with a key) and safe page reading |
| `tests/test_post_and_web.py` | NEW v0.7.0: tests for the two files above |
| `shortsforge/app/router.py` | NEW v0.5.0: understands everyday commands with rules, NO AI needed (make, trim, add clip, find, show, status, remember) |
| `shortsforge/app/retrieval.py` | NEW v0.5.0: BM25 search over transcripts (rare words count more, light stemming) |
| `shortsforge/app/memory.py` | NEW v0.5.0: assistant notebook ("remember that ...") saved in `_memory.json` |
| `tests/test_router.py` | NEW v0.5.0: the "exam": ~30 command sentences + 8 must-go-to-AI sentences + end-to-end chat tests |
| `tests/test_assistant.py` | NEW v0.4.0: fake-AI tests (both providers, tools, security, upload, phone door) |
| `shortsforge/teach.py` | NEW v0.8.0: learns from your example video (area, your name, marked kills) and reports how many it finds |
| `shortsforge/namefeed.py` | NEW v0.8.0: finds your kills by your name in the feed (ignores lines where you are the victim) |
| `shortsforge/smart.py` | NEW v0.8.0: "action moments" from sound and movement when no kill is confirmed |
| `shortsforge/editor.py` | NEW v0.8.0: manual editor engine (cut, join, speed, filters, effects, transitions, text, music) |
| `shortsforge/app/library.py` | NEW v0.8.0: finds your videos (Videos, Desktop, Downloads, Documents, Pictures + your folders) |
| `shortsforge/app/edits.py` | NEW v0.8.0: editor drafts and export, delete/restore clips |
| `shortsforge/app/voice.py` | NEW v0.8.0: microphone recording to text, on your PC |
| `shortsforge/app/report.py` | NEW v0.8.0: troubleshooting report |
| `shortsforge/app/static/teach.js`, `editor.js`, `voice.js` | NEW v0.8.0: the Teach screen, Editor screen and microphone |
| `tests/test_teach.py`, `tests/test_editor.py` | NEW v0.8.0 |
| `shortsforge/find/query.py` | NEW v0.9.0: turns your sentence into a search plan (who killed whom, time range, how many, words said) |
| `shortsforge/find/feed.py` | NEW v0.9.0: reads kill-feed lines and character icons: killer or victim |
| `shortsforge/find/pictures.py` | NEW v0.9.0: example pictures you teach (icons, on-screen things) and where they appear |
| `shortsforge/find/speech.py`, `video.py`, `vision.py` | NEW v0.9.0: fuzzy word search; frames and shot changes; asking the local picture AI |
| `shortsforge/find/moments.py`, `engine.py` | NEW v0.9.0: combines clues into moments, picks start/end, makes the clips |
| `shortsforge/games/valorant_agents.json` | NEW v0.9.0: agent names and spellings |
| `shortsforge/app/findapi.py`, `app/static/find.js` | NEW v0.9.0: the Find screen |
| `shortsforge/editor_layers.py` | NEW v0.9.0: overlays, stickers, green screen, keyframes, extra sounds |
| `tests/test_find.py` | NEW v0.9.0: finder tests on a drawn game video, safety tests |
| `shortsforge/matting.py`, `tracking.py`, `tts.py` | NEW v0.11.0: background removal, motion tracking, text to speech |
| `shortsforge/editor_extras.py`, `app/editortools.py` | NEW v0.11.0: curve speed, masks, blend modes, match cut, compound clips |
| `shortsforge/app/localsearch/` | NEW v0.11.0: built-in web search (query, sources, rank, engine) |
| `tests/test_extras.py`, `test_localsearch.py`, `test_feedlines.py` | NEW v0.11.0: tests for the above |
| `packaging/test_search.py`, `.github/workflows/test-search.yml` | NEW v0.11.0: measures search on the real internet (run by hand) |
| `shortsforge/topics.py`, `follow.py` | NEW v0.10.0: topic changes in speech; crop that follows the speaker |
| `shortsforge/app/strips.py` | NEW v0.10.0: film strips and sound waves for the timeline |
| `tests/test_clipping.py`, `THIRD_PARTY_NOTICES.md` | NEW v0.10.0: tests for the two above and the face detector; ClipsAI credit |
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

### Building the app
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
model), `llama\` (AI engine), `_internal\` (libraries). Errors are logged to `Documents\ShortsForge\app.log`.
To use another speech model, put its folder in `models\<name>\`.

Developer way (no packaging): `pip install -r requirements-app.txt`, then `python shortsforge_app.py`
(add `--browser` to use your browser instead of the window). The old command-line tool still works.

Safety design of the window: it talks to a tiny server on 127.0.0.1 only, protected by a secret token that
changes at every start; it only serves files from the output folder.

### Command-line version (developers only; the app needs none of this)
1. Install **Python 3.11** from python.org. Tick **"Add Python to PATH"**. (3.10-3.12 are safest.)
2. Install **ffmpeg**: open PowerShell and run `winget install Gyan.FFmpeg`. Close and reopen the terminal.
3. Unzip `ShortsForge.zip` somewhere, e.g. `C:\ShortsForge`.
4. Double-click **`install_windows.bat`**. Wait a few minutes. At the end the "doctor" check should
   show `[OK]` for everything (yt_dlp / cv2 may show optional).
5. (Optional) install **Ollama** from ollama.com, then run `ollama pull llama3.1:8b` for the LLM judge.

macOS/Linux: `bash install_mac_linux.sh` (install ffmpeg with brew / apt first).

---

## Part 5. Test status

v0.11.0 (Linux, FFmpeg 8.1, OpenCV 4.14): all 136 automatic tests pass; a simulated browser session passed 68 checks including the new
editor tools, with no script errors. Background removal was checked on one sample photo and in render tests; tracking
on drawn moving squares; text to speech with a Linux voice. **Kill finding on a real PUBG feed** (41 s from the
public repo JNDWI/pubg-killfeed, labelled by eye, not stored here): the new line-following method found 13 of 13
kills of two players with no false ones; the old counting method found 12 of 13. One short clip, with the name box
cut from that same clip: **not** proof of general accuracy, and no real Valorant footage yet.
**Not tested:** your PC, graphics card and microphone, the real Windows window, Windows voices by ear, background
removal and tracking on your videos, Tavily, search from your connection.
Windows build run 46112215047 is green: 136 tests ran, OK with 3 skipped; the packed app passed its self-test (including the background-removal model and Windows voices), voice typing test and AI engine test.

v0.10.0 (Linux, FFmpeg 8.1, OpenCV 4.14): all 106 automatic tests pass; a simulated browser session passed 51 checks (editor including film strips
and multi-select, Find, teaching, Forge commands, phone width) with no script errors; the clipping pipeline ran end
to end on a 2-minute generated video with a made-up transcript. **Not tested:** real faces (so speaker following is
unproven), real speech topics, real Valorant footage, your graphics card and microphone, the real Windows window,
the Tavily service.
Windows build run 45998204226 is green: 106 tests ran, OK with 3 skipped; the packed app passed its self-test (now
including the face detector), voice test and engine test.

v0.9.0 (Linux): the finder is tested on a DRAWN game video with made-up icons; every new editor render path uses
real ffmpeg; a headless browser session used every screen (editor keys and dragging, Find, teaching a picture,
Forge commands, phone width) with no script errors. NOT tested: real Valorant footage (finder accuracy is
unknown), your microphone, your graphics card, the Windows window (including whether it passes every shortcut
through), auto captions with the real speech model inside the editor.

The first v0.9.0 build (run 45952037052) had 1 failing test: the app's Windows FFmpeg is a newer "latest" build, and
it stopped exports that mixed an animated (keyframed) layer with later filters. Fixed by changing a layer's size
last; all 98 tests then passed on Linux with that same FFmpeg version. In that first build the packed app passed
its self-test, voice test, and a real engine test where the tiny picture model saw a red square and saw none in a
blank picture. The rebuilt Windows app (run 45956682204) is green: 98 tests ran on Windows, OK with 3 skipped, and the self-test,
voice test and engine test (including the picture check) passed.
Improve later: pin one FFmpeg version in `packaging/fetch_assets.py` so builds cannot change under you.

v0.8.0 Windows build run 45813526675: 78 tests ran, OK with 3 skipped; the packed app passed its self-test (including the editor filters); the packed app wrote down a computer-spoken sentence correctly ("Please make five shorts from my last video." - a robot voice, not yours); the real AI engine with a tiny test model loaded, answered, used a tool and searched the web. That tiny model also misspelled a web address in one answer, so check links the assistant gives you.

v0.8.0: automatic tests on Linux cover name-based kill finding on a DRAWN kill feed, the fallback, video search, every editor filter/effect/transition (real ffmpeg renders), delete/restore, command words, Forge's tools and the new routes; screens were clicked in a headless browser. NOT tested: your real Valorant footage (so kill accuracy is unknown), your microphone, the Windows window's microphone permission, your graphics card.

v0.7.0: 64 automatic tests pass on Linux (9 new, with a pretend AI and pretend internet). The new buttons and settings were clicked through in a headless browser at phone width. Windows build run 45574933324: 64 tests ran, OK with 3 skipped. Real Qwen3.5 9B (run 45574937232, processor only): wrote usable post text for a made-up transcript (37 s) and answered a web question with a Wikipedia link (177 s). NOT tested: your PC, the Tavily service (no key here), quality of the written texts on your videos.

v0.6.0: 55 automatic tests pass on Linux (13 new: checked and resumable download, bad checksum rejected, engine start/reuse/idle stop/crash message with a PRETEND engine, phone cannot manage models, speech CPU fallback). The Settings screen was rendered in a headless browser at desktop and narrow widths with no script errors. On GitHub's Windows machine (build run 45536052159): 55 tests ran, OK with 3 skipped (the pretend-engine tests); the packed app passed its self-test; the real llama.cpp engine ran a 0.8B test model and used a tool. Run 45537572806: the real Qwen3.5 9B downloaded, passed its checksum, loaded, answered and used a tool correctly (on the processor, 81 s for the tool question; there is no graphics card there). NOT tested: your RTX 5060 Ti, graphics-card speed or memory use, the download button against the real site from the window.

v0.5.0: 27 new tests (router exam, search, chat without AI, memory, feedback, privacy) pass together with the v0.4.0 set. v0.4.0: 31 automatic tests pass (core 5, game 5, app 15 incl. window server, assistant 16 incl. fake Claude + fake OpenAI servers, tool safety, upload, phone-door rules). The new page was rendered in a headless browser at desktop and phone sizes with no script errors and no sideways scrolling.

Run `python -m unittest discover tests -v` (about 2 minutes, mostly the end-to-end render).
Verified in the build environment (15 tests: `python -m unittest discover tests -v`): scoring logic, candidate cutting, caption generation, and a full
end-to-end run on a synthetic video (output verified as 1080x1920 MP4 with captions).
Game mode was verified only on a FAKE kill feed (4 real kills found, 3 look-alike distractors rejected, all 3 layouts render 1080x1920 with popups). Window/server (v0.3.0): security rules, job progress, clip streaming with seeking, trim + export again, kill check, and the real page driven in a headless browser (no script errors). Packaged bundle: built and self-tested on Linux, and a full game job ran inside the packed program. **Not verified here (needs your PC):** the Windows build/installer/native window (pywebview), file-picker dialog, GitHub workflow run, real Valorant colours/position (use `calibrate`), real speech recognition with faster-whisper (the model must be
downloaded), yt-dlp downloads, the Ollama LLM step, and face-crop on real faces. If any of these fail
on your PC, send the error text to Claude together with this file.

---

## Part 6. History (oldest to latest)

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

- **2026-11-24, v0.4.0** - AI assistant + phone access + new interface.
  - New: `assistant.py` (chat with Claude via Anthropic Messages API tool use, or any OpenAI-compatible server;
    falls back to chat-only when a model has no tools; 9 tools: list/get projects, list videos, make shorts,
    job status, trim clip, add clip, search/read transcript), `settings.py` (key hidden from the page),
    `lan.py` + second "phone door" server (private-network Host check, token, upload, restricted actions),
    `add_clip` in pipeline, upload endpoint, chat history file, rewritten `index.html` (3 tabs, bottom tab bar
    on phones, dark mode, settings dialog, QR code, progress strip, voice typing where supported).
  - Safety decisions: AI may only use videos the app knows or links; no delete/shell/web tools; transcript text
    is treated as data; settings and chat files cannot be downloaded through /files.
  - Decision: the assistant uses an external AI (honest: no built-in chat model); offline built-in model is a
    possible later download-on-demand.

- **2026-11-25, v0.5.0** - Assistant improvements that do not depend on model size.
  - New: `router.py` (rule-based command understanding, works offline with no AI), `retrieval.py` (BM25),
    `memory.py`, tools `search_all_transcripts` + `remember_note` for the AI, memory notes in the AI prompt as data,
    `/api/feedback` thumbs log, `/api/memory`, quick-action buttons, drag-and-drop upload, instant-answer badge.
  - Chat flow now: command rules first, then the AI (if connected), else a friendly "connect an AI" note.
  - Decision: the quality of free chat still comes from the connected AI model; code cannot replace model
    training. Fine-tuning and a built-in offline model are the next roadmap items.

- **2026-11-25, v0.6.0** - Built-in offline AI (roadmap 2f). Target PC: 16 GB RAM, RTX 5060 Ti 8 GB.
  - New: `app/localai.py`, provider `builtin` in settings/assistant, Settings screen "Built-in" with download,
    cancel, delete; `/api/localai` (PC only); engine llama.cpp b12600 (Vulkan) added to the build with a pinned
    checksum; models Qwen3.5 9B and 4B (Q4_K_M, Apache-2.0) pinned by revision and SHA-256.
  - Fix: speech recognition now falls back to the processor if the graphics card cannot be used (the app does
    not carry NVIDIA's CUDA libraries, so NVIDIA PCs were at risk of failing; found by reading the code, not
    reported from your PC).
  - Decisions: model is downloaded on request, not bundled (keeps the app about the same size); Vulkan engine
    because it is small and works on any maker's card; engine listens on 127.0.0.1 with a random password,
    stops after 10 idle minutes and closes with the app.

- **2026-11-25, v0.7.0** - Requested after v0.6.0: upload title/description/hashtags for every clip (button,
  chat tool, `post_texts.txt`) and web search for the assistant (off by default; Wikipedia without a key,
  Tavily with a key; at most 3 searches per message; changing tools blocked after a search).

- **2026-11-26, v0.8.0** - User report after installing: "no kills found", Forge could not find the video,
  no voice typing; asked for learning from an example video, full control by the assistant, a CapCut-like
  editor and ideas from their ClipCutter site. Root causes: (1) detection relied on one guessed red-colour rule;
  (2) Forge only knew uploads and finished projects, so a failed first video was forgotten; (3) voice used a
  browser service the Windows window lacks. Fixed with the Teach screen, action-moment fallback, video search,
  offline voice, 8 new assistant tools, the editor, a troubleshooting report. Engine flag updated to
  `--reasoning off`; Settings shows which graphics card the AI engine sees. Taken from ClipCutter: teach my
  name, draw the kill-feed box, "never empty" fallback, montage (join), troubleshoot report. Not taken:
  Cloudflare cloud storage and profiles (not needed in a desktop app).
  Also fixed a security hole present before: the settings file (API key) could be read through a differently
  spelled file address.

- **2026-11-27, v0.9.0** - Requested: CapCut-like editor and shortcuts, better assistant with internet answers,
  and an algorithm of 1,000+ lines that locates a described scene (a kill of a given character) and crops it.
  New: `find/` package and Find screen; editor timeline with layers, keyframes, green screen, stickers, auto
  captions, freeze, marks, shortcuts, 720p/1080p, 30/60 fps; picture reader download for the built-in AI;
  Forge tools `find_scene` and `read_page` (only searched pages, public addresses), invented links removed.
  Fixed during the simulated session: overlapping timeline items hid each other, the timeline was below the
  screen edge, overlay videos previewed with black bars, endless sounds stretched the timeline, the teaching
  video on Find was tiny.

- **2026-11-27, v0.10.0** - Requested: use the ClipsAI repo, get closer to CapCut, a full project plan, debugging.
  New: topic-change scoring; crop that follows the speaker and camera cuts; editor film strips, sound waves,
  multi-select, [ and ] keys; this file restructured around a project plan. Fixed: OpenCV 5 (which the Windows
  build installed) has no face detector, so **auto** and **face** framing of talking videos would fail; OpenCV is
  now held below 5. FFmpeg held at the 8.1 release branch.
- **2026-11-28, v0.11.0** - Requested: more of CapCut, real PUBG/Valorant shots, background removal, tracking, text to
  speech, and our own search in place of Tavily. New: those tools; curve speed, masks, blend modes, match cut, groups,
  compound clips, new effects, ready-made looks; built-in web search; kill-feed lines followed by their contents.
  Fixed: a kill was missed when one feed line replaced another; Wikipedia refused searches that posed as a browser.

*(Add a new line here every time something changes.)*

---

## Part 7. Prompt to resume with Claude

> I'm continuing the ShortsForge project (repo https://github.com/DHARMAdr/Video-Ai). Read PROJECT.md first.
> Then implement: **[phase / bug + error text]**. Keep the simple-English WHY / HOW / HOW TO IMPROVE comments,
> run the tests and add tests for new things, update PROJECT.md, push to main, run "Build Windows app", tell me
> when it is green and where to download it, and say honestly what was not tested.
