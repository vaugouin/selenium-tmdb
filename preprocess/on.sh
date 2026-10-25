#!/bin/bash
# Switch selenium-tmdb.sh back on: removes the flag file CRON_OFF that off.sh wrote.
cd "$(dirname "$(readlink -f "$0")")" || exit 1
# A launcher renamed by the old off.sh (<name>-off.sh, before 2026-10-25) is put back,
# or dropped when git has already restored the tracked one.
[ -f selenium-tmdb-off.sh ] && { [ -f selenium-tmdb.sh ] && rm -f selenium-tmdb-off.sh || mv selenium-tmdb-off.sh selenium-tmdb.sh; }
rm -f CRON_OFF && echo "selenium-tmdb: on (CRON_OFF removed)"
