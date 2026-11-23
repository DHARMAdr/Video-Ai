@echo off
REM make_shorts.bat - drag a video file onto this file (or run: make_shorts.bat video.mp4)
REM WHY: lets you create shorts without typing the long command.
REM HOW: activates the environment, then runs the "make" command on the first argument.
REM IMPROVE: add a menu asking how many shorts and which reframe style.

if "%~1"=="" (
  echo Drag a video file onto this file, or run:  make_shorts.bat "C:\path\video.mp4"
  pause
  exit /b 1
)
call .venv\Scripts\activate
python -m shortsforge make "%~1" --count 5
echo.
echo Finished. Look inside the "output" folder.
pause
