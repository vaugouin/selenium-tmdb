@echo off
rem Corrects the Places of Birth the robot wrote with today's country (2026-11-11 to 11-13),
rem see the docstring of selenium-tmdb-place-correction.py. Options are passed on:
rem   selenium-tmdb-place-correction.bat --build                    read-only: the list to correct
rem   selenium-tmdb-place-correction.bat --dry-run --max-rows 20    pages checked, nothing saved
rem   selenium-tmdb-place-correction.bat --max-rows 20              real corrections, watch them
rem   selenium-tmdb-place-correction.bat --help

setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1

uv run --with-requirements requirements.txt python selenium-tmdb-place-correction.py %*
set EXITCODE=%ERRORLEVEL%

echo.
echo Fin de selenium-tmdb-place-correction.py (code de sortie %EXITCODE%).
pause
exit /b %EXITCODE%
