@echo off
rem Fills the primary facts of TMDB persons (death and birth dates, gender).
rem Runs selenium-tmdb-deathday-v2.py through uv, from the folder of this file, wherever the
rem repository sits. Options are passed on, for instance:
rem   selenium-tmdb-deathday.bat --dry-run --max-rows 20     pages checked, nothing saved
rem   selenium-tmdb-deathday.bat --diagnostic 1265047        read-only
rem   selenium-tmdb-deathday.bat --reset-cursor
rem   selenium-tmdb-deathday.bat --help
rem uv uses the .venv of the folder when it has everything, and otherwise builds
rem the environment from requirements.txt.

setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1

uv run --with-requirements requirements.txt python selenium-tmdb-deathday-v2.py %*
set EXITCODE=%ERRORLEVEL%

echo.
echo Fin de selenium-tmdb-deathday-v2.py (code de sortie %EXITCODE%).
pause
exit /b %EXITCODE%
