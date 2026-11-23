@echo off
REM install_windows.bat - one-time setup on Windows.
REM WHY: creates a private Python environment (.venv) so ShortsForge does not mix with other projects.
REM HOW: double-click this file. It installs the packages, then runs the system check.
REM IMPROVE: add automatic ffmpeg install (winget) if you want zero manual steps.

echo [1/4] Creating virtual environment...
python -m venv .venv
if errorlevel 1 (
  echo Python was not found. Install Python 3.11 from python.org and tick "Add to PATH".
  pause
  exit /b 1
)

echo [2/4] Activating it...
call .venv\Scripts\activate

echo [3/4] Installing packages (this can take a few minutes)...
python -m pip install --upgrade pip
pip install -r requirements.txt

echo [4/4] Checking ffmpeg and packages...
python -m shortsforge doctor

echo.
echo If ffmpeg shows MISSING, open a new terminal and run:  winget install Gyan.FFmpeg
echo Then close and reopen this window and run doctor again.
pause
