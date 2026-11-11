@echo off
rem Everything the robot writes on TMDB (v3): wikidata_id and external ids (IMDb, TheTVDB,
rem Facebook, Instagram, X, TikTok) of movies, series and persons, then the primary facts
rem of persons. Runs selenium-tmdb-v3.py through uv, from the folder of this file.
rem Options are passed on, for instance:
rem   selenium-tmdb.bat --dry-run --max-rows 20                pages checked, nothing saved
rem   selenium-tmdb.bat --phases person --fields facebook_id instagram_id
rem   selenium-tmdb.bat --diagnostic movie 550                 read-only
rem   selenium-tmdb.bat --reset-cursors
rem   selenium-tmdb.bat --help
rem uv uses the .venv of the folder when it has everything, and otherwise builds
rem the environment from requirements.txt.

setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1

uv run --with-requirements requirements.txt python selenium-tmdb-v3.py %*
set EXITCODE=%ERRORLEVEL%

echo.
echo Fin de selenium-tmdb-v3.py (code de sortie %EXITCODE%).
pause
exit /b %EXITCODE%
