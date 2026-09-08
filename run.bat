@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"

rem ===========================================================================
rem  Shorts Studio II - run (this machine, full access)
rem
rem  ASCII only, on purpose - see the note at the top of setup.bat.
rem
rem  Opens the web console straight away. No menu: the console IS the app, and
rem  a menu in front of it is one more thing to explain to anyone you show it
rem  to. The command-line menu still lives at  tools\cli.bat  for scripted or
rem  headless work.
rem
rem  Binds 127.0.0.1 only. To let other machines LOOK at the pipeline, use
rem  lan-run.bat instead - that one is read-only for everyone else.
rem
rem  Keep this window open while you work; closing it stops the server.
rem  Do NOT try to hide it. If node has no console to inherit, Windows gives
rem  every Chrome render worker its own - measured 11 black windows for a
rem  single render. This window is what prevents that.
rem ===========================================================================

set "PY=.venv-app\Scripts\python.exe"
if not exist "%PY%" (
  echo.
  echo  Virtual environment not found. Run setup.bat first.
  echo.
  pause
  exit /b 1
)

for /f "tokens=2 delims=:," %%p in ('findstr /c:"\"port\"" config.json') do set "PORT=%%~p"
set "PORT=%PORT: =%"
if "%PORT%"=="" set "PORT=8899"

echo.
echo  ================================================
echo   Shorts Studio II
echo   book chapter  --^>  9:16  30s motion short
echo  ================================================
echo.
echo   Console : http://127.0.0.1:%PORT%
echo   Stop    : Ctrl+C, or just close this window
echo.
echo   Command line instead : tools\cli.bat
echo   Show to co-workers   : lan-run.bat   ^(read only^)
echo.

start "" "http://127.0.0.1:%PORT%"
"%PY%" server.py

echo.
echo  Server stopped.
echo.
pause
endlocal
