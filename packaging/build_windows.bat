@echo off
REM build_windows.bat - builds the standalone app on YOUR Windows PC (the alternative to GitHub).
REM WHY: produces dist\ShortsForge\ShortsForge.exe that runs on any Windows PC with nothing installed.
REM HOW: run it from the project folder:   packaging\build_windows.bat
REM      Needs Python 3.11 + internet on the BUILD PC only (not on the PCs that use the app).
REM      Takes 10-25 minutes the first time (downloads ~1 GB).
REM IMPROVE: add code signing (signtool) after the build so Windows trusts the .exe.

cd /d "%~dp0\.."

echo [1/6] Creating build environment...
python -m venv .venv-build || goto :fail
call .venv-build\Scripts\activate

echo [2/6] Installing packages...
python -m pip install --upgrade pip
pip install -r requirements-app.txt -r requirements-build.txt || goto :fail

echo [3/6] Downloading ffmpeg and the speech model...
python packaging\fetch_assets.py --model small || goto :fail

echo [4/6] Packing the app (PyInstaller)...
pyinstaller packaging\ShortsForge.spec --noconfirm --distpath dist --workpath build_pyi || goto :fail

echo [5/6] Adding ffmpeg and the model next to the .exe...
xcopy /E /I /Y packaging\assets\bin dist\ShortsForge\bin >nul
if exist packaging\assets\models xcopy /E /I /Y packaging\assets\models dist\ShortsForge\models >nul

echo [6/6] Self-test...
dist\ShortsForge\ShortsForge.exe --selftest
type "%USERPROFILE%\Documents\ShortsForge\selftest.txt"

echo.
echo DONE. Your app is in:  dist\ShortsForge\ShortsForge.exe
echo Zip the whole dist\ShortsForge folder to share it (or build the installer with installer.iss).
pause
exit /b 0

:fail
echo.
echo BUILD FAILED. Copy the text above and send it to Claude together with PROJECT.md.
pause
exit /b 1
