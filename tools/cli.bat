@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0.."

rem ===========================================================================
rem  Shorts Studio II - command line menu
rem
rem  ASCII only, on purpose - see the note at the top of setup.bat.
rem
rem  This is NOT the normal way in. run.bat opens the web console, and that is
rem  the app. This menu is here for scripted work, for a machine with no
rem  browser, and for poking at one stage without the console running.
rem
rem  It calls the SAME code the console calls (pipeline/runner.py), so results
rem  are identical either way.
rem ===========================================================================

set "PY=.venv-app\Scripts\python.exe"
if not exist "%PY%" (
  echo.
  echo  Virtual environment not found. Run setup.bat first.
  echo.
  pause
  exit /b 1
)

:menu
cls
echo.
echo  ================================================
echo   Shorts Studio II - command line
echo  ================================================
echo.
echo    1.  New project from a file
echo    2.  List projects
echo    3.  Run every stage for a project
echo    4.  Run one stage
echo    5.  Show project state
echo    6.  Fill placeholder artwork      (free, no credits)
echo.
echo    D.  Doctor  (check the renderer)
echo    Q.  Quit
echo.
set "CH="
set /p "CH=  Choose: "

if /i "%CH%"=="1" goto new
if /i "%CH%"=="2" goto list
if /i "%CH%"=="3" goto all
if /i "%CH%"=="4" goto one
if /i "%CH%"=="5" goto state
if /i "%CH%"=="6" goto placeholder
if /i "%CH%"=="D" goto doctor
if /i "%CH%"=="Q" goto end
goto menu

:new
echo.
set "SRC="
set /p "SRC=  Path to the chapter file (pdf/docx/md/txt/html): "
if "%SRC%"=="" goto menu
set "TITLE="
set /p "TITLE=  Title (blank = file name): "
set "CUTS="
set /p "CUTS=  Cuts / scenes (blank = config default): "
if "%CUTS%"=="" (
  "%PY%" scripts\make.py new "%SRC%" --title "%TITLE%"
) else (
  "%PY%" scripts\make.py new "%SRC%" --title "%TITLE%" --cuts %CUTS%
)
echo.
pause
goto menu

:list
echo.
"%PY%" scripts\make.py list
echo.
pause
goto menu

:all
echo.
"%PY%" scripts\make.py list
echo.
set "SLUG="
set /p "SLUG=  Project name: "
if "%SLUG%"=="" goto menu
echo.
echo  This spends credits on: script, image prompts, artwork.
set "YN="
set /p "YN=  Continue? (y/N): "
if /i not "%YN%"=="y" goto menu
"%PY%" scripts\make.py all "%SLUG%"
echo.
pause
goto menu

:one
echo.
echo   Stages:  source  script  speech  tts  subs
echo            imgprompt  images  compose  build  result
echo.
set "SLUG="
set /p "SLUG=  Project name: "
if "%SLUG%"=="" goto menu
set "STAGE="
set /p "STAGE=  Stage: "
if "%STAGE%"=="" goto menu
"%PY%" scripts\make.py run "%SLUG%" %STAGE%
echo.
pause
goto menu

:state
echo.
set "SLUG="
set /p "SLUG=  Project name: "
if "%SLUG%"=="" goto menu
"%PY%" scripts\make.py state "%SLUG%"
echo.
pause
goto menu

:placeholder
echo.
echo  Makes ivory 2:3 stand-in artwork so you can test compose + build
echo  without spending image credits. Real artwork overwrites it later.
echo.
set "SLUG="
set /p "SLUG=  Project name: "
if "%SLUG%"=="" goto menu
"%PY%" tools\placeholder_art.py "%SLUG%" --force
echo.
pause
goto menu

:doctor
echo.
if exist "node_modules\.bin\hyperframes.cmd" (
  call "node_modules\.bin\hyperframes.cmd" doctor
) else (
  echo  node_modules not installed. Run setup.bat first.
)
echo.
echo  Ignore the whisper / Kokoro / Docker lines - all optional.
echo  What matters: Chrome, FFmpeg, FFprobe, Node.
echo.
pause
goto menu

:end
endlocal
