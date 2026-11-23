"""
app/ - the desktop window of ShortsForge (added in v0.3.0).

WHY it exists:
    So you can use ShortsForge like a normal program: click, pick a video, see the clips, trim
    them. No terminal needed.

HOW it works (3 small parts):
    jobs.py     runs the heavy work (detect, cut, render) in a background thread and keeps a log
    server.py   a tiny web server that only talks to THIS computer; the window is a web page
                (static/index.html) that calls it
    desktop.py  starts the server and opens the window (or your browser as a fallback)

HOW TO IMPROVE:
    Add more API routes in server.py and more screens in static/index.html (for example an
    "AI chat" panel that sends requests to an online model).
"""
