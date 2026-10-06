@echo off
rem Double-click to paste YouTube links one at a time, or run: yt2flac.bat URL [URL ...]
where /q uv || (
  echo uv is not installed. Install it by running this in Command Prompt, then open a new window:
  echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  pause
  exit /b 1
)
rem Always pull the newest yt-dlp: YouTube changes often and old versions stop working.
uv run --upgrade-package yt-dlp --upgrade-package yt-dlp-ejs "%~dp0yt2flac.py" %*
pause
