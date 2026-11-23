@echo off
REM make_valorant.bat - drag a Valorant gameplay recording onto this file.
REM WHY: one click to get kill-highlight shorts (kill detection + popups + vertical layout).
REM HOW: activates the environment, then runs the "valorant" command with 5 shorts.
REM      First time? Run calibrate once (see PROJECT.md section "Game mode") to check detection.
REM IMPROVE: add a menu to choose layout (center / blur / stack) and number of shorts.

if "%~1"=="" (
  echo Drag a gameplay video onto this file, or run:  make_valorant.bat "C:\path\game.mp4"
  pause
  exit /b 1
)
call .venv\Scripts\activate
python -m shortsforge valorant "%~1" --count 5
echo.
echo Finished. Look inside the "output" folder (report.md lists every kill found).
pause
