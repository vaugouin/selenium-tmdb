@echo off
rem Writes Wikidata QIDs into the wikidata_id of TMDB movies, series and persons.
rem Runs selenium-tmdb-wikidata_id-v2.py through uv, from the folder of this file, wherever the
rem repository sits. Options are passed on, for instance:
rem   selenium-tmdb-wikidata_id.bat --datasets 3 4 5            the three replace datasets
rem   selenium-tmdb-wikidata_id.bat --diagnostic movie 300115   read-only
rem   selenium-tmdb-wikidata_id.bat --reset-cursors
rem   selenium-tmdb-wikidata_id.bat --help
rem uv uses the .venv of the folder when it has everything, and otherwise builds
rem the environment from requirements.txt.

setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1

uv run --with-requirements requirements.txt python selenium-tmdb-wikidata_id-v2.py %*
set EXITCODE=%ERRORLEVEL%

echo.
echo Fin de selenium-tmdb-wikidata_id-v2.py (code de sortie %EXITCODE%).
pause
exit /b %EXITCODE%
