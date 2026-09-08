@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"

rem ===========================================================================
rem  Shorts Studio II - lan-run (share the pipeline, READ ONLY)
rem
rem  ASCII only, on purpose - see the note at the top of setup.bat.
rem
rem  Binds 0.0.0.0 so co-workers can WATCH the pipeline: stage states, the
rem  script, subtitles, artwork, the rendered mp4, the progress log.
rem
rem  WHY READ ONLY, AND WHY IT IS NOT NEGOTIABLE
rem  -------------------------------------------
rem  Every stage that builds something runs on THIS machine's subscription
rem  logins - Claude Code for the script, ChatGPT for the artwork. Letting a
rem  visitor press those buttons would be running someone else's requests
rem  through your personal subscription. Anthropic's terms forbid that, and
rem  the ChatGPT side has the same problem. So the server refuses every
rem  non-GET request that does not come from loopback, and refuses GETs
rem  outside a small allowlist (core/access.py).
rem
rem  The refusal is enforced SERVER SIDE, not by hiding buttons. A visitor who
rem  crafts the request by hand still gets a 403.
rem
rem  A visitor who wants to build their own: clone this repo, run setup.bat,
rem  log in once with `claude` and `codex login`. Then it is their own quota.
rem ===========================================================================

set "PY=.venv-app\Scripts\python.exe"
if not exist "%PY%" (
  echo.
  echo  Virtual environment not found. Run setup.bat first.
  echo.
  pause
  exit /b 1
)

rem This is the switch core/access.py reads. Without it the server stays on
rem loopback and this script would do nothing different from run.bat.
set "SHORTS_LAN=1"

for /f "tokens=2 delims=:," %%p in ('findstr /c:"\"port\"" config.json') do set "PORT=%%~p"
set "PORT=%PORT: =%"
if "%PORT%"=="" set "PORT=8899"

echo.
echo  ================================================
echo   Shorts Studio II - LAN share (read only)
echo  ================================================
echo.
echo   This machine    : http://127.0.0.1:%PORT%    (full access)
echo.
echo   Other machines  : read only
for /f "tokens=1,2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
  set "IP=%%b"
  set "IP=!IP: =!"
  echo                     http://!IP!:%PORT%
)
echo.
echo   Visitors can see stages, script, subtitles, artwork and the mp4.
echo   Visitors cannot run any stage - the server returns 403.
echo.
echo   Ctrl+C to stop.
echo.

start "" "http://127.0.0.1:%PORT%"
"%PY%" server.py

endlocal
