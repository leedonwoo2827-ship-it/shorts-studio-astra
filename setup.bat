@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"

rem ===========================================================================
rem  Shorts Studio II - setup
rem
rem  ASCII only, on purpose. A .bat saved as UTF-8 with Korean text breaks on
rem  machines whose console codepage is cp949 - the file still runs but the
rem  labels turn to garbage, and you cannot read the very instructions that
rem  tell you what went wrong.
rem
rem  This script is SELF-CONTAINED: it never reads or writes anything outside
rem  this folder, except (a) pip/npm downloads and (b) the two OAuth logins,
rem  which live in your user profile and are shared with the CLIs.
rem ===========================================================================

echo.
echo  ================================================
echo   Shorts Studio II - setup
echo  ================================================
echo.

set "FAIL=0"

rem --- 1. Python -------------------------------------------------------------
echo [1/6] Python 3.10+
where python >nul 2>&1
if errorlevel 1 (
  echo       NOT FOUND. Install Python 3.10 or newer and check
  echo       "Add Python to PATH" during install.
  echo       https://www.python.org/downloads/
  set "FAIL=1"
  goto :done
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set "PYV=%%v"
echo       found %PYV%
python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (
  echo       TOO OLD. Need 3.10 or newer.
  set "FAIL=1"
  goto :done
)

rem --- 2. Node --------------------------------------------------------------
echo [2/6] Node.js 22+
where node >nul 2>&1
if errorlevel 1 (
  echo       NOT FOUND. HyperFrames renders with headless Chrome driven by
  echo       Node. Install Node 22 or newer: https://nodejs.org/
  set "FAIL=1"
) else (
  for /f "tokens=*" %%v in ('node --version') do echo       found %%v
)

rem --- 3. ffmpeg ------------------------------------------------------------
echo [3/6] ffmpeg / ffprobe
where ffmpeg >nul 2>&1
if errorlevel 1 (
  echo       NOT FOUND. Required for audio conversion and muxing.
  echo       Install:  winget install Gyan.FFmpeg
  echo       Then open a NEW terminal so PATH is picked up.
  set "FAIL=1"
) else (
  echo       found
)

rem --- 4. Python venv -------------------------------------------------------
echo [4/6] Python venv (.venv-app) + dependencies
if not exist ".venv-app\Scripts\python.exe" (
  python -m venv .venv-app
  if errorlevel 1 (
    echo       FAILED to create venv.
    set "FAIL=1"
    goto :done
  )
)
".venv-app\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv-app\Scripts\python.exe" -m pip install --quiet -r requirements.txt
if errorlevel 1 (
  echo       FAILED to install dependencies. See the errors above.
  set "FAIL=1"
) else (
  echo       ok
)

rem --- 5. Node packages ----------------------------------------------------
echo [5/6] Node packages (HyperFrames)
if exist "node_modules\.bin\hyperframes.cmd" (
  echo       already installed
) else (
  where npm >nul 2>&1
  if errorlevel 1 (
    echo       npm NOT FOUND - skipping. Install Node, then run setup again.
    set "FAIL=1"
  ) else (
    call npm install --silent
    if errorlevel 1 (
      echo       FAILED. Try running: npm install
      set "FAIL=1"
    ) else (
      echo       ok
    )
  )
)

rem --- 5b. Machine-local config --------------------------------------------
rem  config.json is the repo default and is meant to stay untouched, so that
rem  pulling an update never conflicts. Anything specific to THIS machine goes
rem  in config.local.json, which is gitignored and wins over config.json.
if not exist "config.local.json" (
  > "config.local.json" echo {
  >>"config.local.json" echo   "_note": "This machine only. Overrides config.json. Gitignored.",
  >>"config.local.json" echo   "_example": "To use Supertonic instead of edge-tts, set tts.engine to voicewright and fill tts.voicewright_dir / tts.assets_dir / tts.python.",
  >>"config.local.json" echo   "_measure": "If you change TTS engine or voice, re-measure narration.chars_per_sec - see README section 3."
  >>"config.local.json" echo }
  echo       config.local.json created ^(machine-local overrides^)
)

rem --- 6. Logins -----------------------------------------------------------
echo [6/6] Subscription logins (no API keys are used)
echo.
echo       REQUIRED - one login:
echo.
echo         SCRIPT / MANUSCRIPT / IMAGE PROMPTS  --^>  Claude Code
echo             run:  claude
echo             (once; it opens a browser)
echo.
echo       OPTIONAL - only for the "scroll" layout:
echo.
echo         SCENE ARTWORK (Astra)   --^>  ChatGPT via Codex CLI
echo             run:  codex login
echo.
echo       The default layout is "card": the centre 16:9 picture is drawn
echo       by you with FlowGenie (a Chrome extension) and dropped into the
echo       scene folder. That path calls NO ChatGPT and costs no credits.
echo       Codex is needed only if you set compose.layout back to the
echo       scroll layout, where Astra writes an animated SVG per scene.
echo.
echo       The two providers are deliberately NOT wired together. They run
echo       in separate processes and never read each other's credentials.
echo.
echo       NOTE: "codex login status" only checks that a file exists. It says
echo       "Logged in" even when the token expired. The app checks the real
echo       expiry itself and tells you in the left rail.
echo.
if exist "%USERPROFILE%\.claude\.credentials.json" (
  echo       Claude  : credentials file present
) else (
  echo       Claude  : NOT logged in yet  --^>  run  claude
)
if exist "%USERPROFILE%\.codex\auth.json" (
  echo       ChatGPT : credentials file present ^(expiry checked at runtime^)
) else (
  echo       ChatGPT : not logged in - fine, the card layout does not use it
)

:done
echo.
if "%FAIL%"=="1" (
  echo  ================================================
  echo   Setup finished WITH PROBLEMS - see above.
  echo  ================================================
) else (
  echo  ================================================
  echo   Setup complete.  Next:  run.bat
  echo  ================================================
)
echo.
pause
endlocal
