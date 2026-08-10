# Establish the Layer D CEILING: score Naren's own responses against his own rubrics, to
# find out whether the CSM's 3.1% full-hit rate is a real coaching gap or a broken
# measurement. Design: docs/superpowers/specs/2026-08-11-naren-ceiling-measurement-design.md
#
# Opens in its own window and stays open (-NoExit from the launcher) so the run is visible
# and its final tables readable.
#
# THIS SCRIPT WRITES NOTHING TO POSTGRES. It deliberately does NOT call
# clear_ego_trap_data.py and never touches Layer D's tables -- the harness opens its
# connection with SET SESSION default_transaction_read_only = on, imports neither
# ego_trap.gap_output nor shared.checkpoint, and persists its results to
# artifacts/naren_ceiling.json instead. So unlike run_noisefloor.ps1 there is no clear step
# to protect; the guard below exists for a different reason -- see it.
#
# It runs the DRY PASS FIRST, every time, and only scores if that pass is clean. The dry
# pass costs zero Gemma calls and checks the two things that would otherwise waste ~95 of
# them on a meaningless result: that every text is already in the embed cache, and that the
# hoisted benchmark ranking still agrees with production's rank_benchmark_responses.

$ErrorActionPreference = "Stop"
Set-Location "C:\PF\Joveo\CS-platform\Brain"

$py    = "..\.venv\Scripts\python.exe"
$stamp = Get-Date -Format "yyyyMMdd_HHmm"
# Fixed name while running, so a watcher can tail a known path; archived to a timestamped
# copy at the end so successive runs are kept for reference rather than overwritten.
$log     = "logs\naren_ceiling.log"
$archive = "logs\naren_ceiling_$stamp.log"
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"

Write-Host "=== Layer D ceiling measurement (Naren vs his own rubrics) ===" -ForegroundColor Cyan
Write-Host "log: $log" -ForegroundColor DarkGray

# --- Guard: no competing pipeline run may be alive ---------------------------
# NOT to protect a clear -- this script clears nothing. Two reasons that are specific to
# this run:
#   1. GEMMA QUOTA. A concurrent Layer D run is also spending calls. Contention triggers
#      429 backoff and gemma.py's silent model downgrade, and an arm scored partly by
#      gemma-4-31b-it instead of flash-lite is not comparable to the arms beside it -- which
#      is the whole measurement.
#   2. embed_cache.db is SQLite. A concurrent Step 0 in similarity mode is writing to it.
# Matches on the command line rather than "any python process", so a one-second diagnostic
# query does not block the run (same reasoning as run_noisefloor.ps1's guard).
$running = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
             Where-Object { $_.CommandLine -match 'run_ego_trap|response_taxonomy|run_v2|main\.py|score_naren_ceiling' })
if ($running.Count -gt 0) {
    Write-Host "ABORTING: a pipeline run is already alive - it shares this run's Gemma quota:" -ForegroundColor Red
    $running | ForEach-Object { "  PID $($_.ProcessId): $($_.CommandLine)" }
    Write-Host "Remember: two python.exe PIDs in a parent/child pair are ONE run (the venv" -ForegroundColor DarkGray
    Write-Host "shim re-execs the base interpreter). Two with DIFFERENT parents are two runs." -ForegroundColor DarkGray
    Write-Host "Wait for it, or 'taskkill /PID <pid> /T /F', then re-run this script." -ForegroundColor Red
    exit 1
}
Write-Host "[guard] no competing pipeline run detected" -ForegroundColor Green

# --- 1/2: dry pass, zero Gemma calls ----------------------------------------
Write-Host "`n[1/2] DRY PASS - zero Gemma calls. Checks embed-cache coverage, the arm B" -ForegroundColor Yellow
Write-Host "      pairings, benchmark holdout, and ranking equivalence." -ForegroundColor Yellow
& $py calibration\score_naren_ceiling.py 2>&1 | Tee-Object -FilePath $log
if ($LASTEXITCODE -ne 0) {
    Write-Host "`nABORTING: the dry pass failed, so nothing was scored and no quota spent." -ForegroundColor Red
    Write-Host "Read $log - the harness aborts deliberately on an uncached text or a" -ForegroundColor Red
    Write-Host "benchmark-ranking mismatch rather than producing a number it cannot defend." -ForegroundColor Red
    exit 1
}
Write-Host "`n[guard] dry pass clean" -ForegroundColor Green

# --- 2/2: the scored run ----------------------------------------------------
Write-Host "`n[2/2] SCORING - ~95 Gemma calls across 3 arms (~19% of one key's 500/day)." -ForegroundColor Yellow
Write-Host "      A failed batch is reported and SKIPPED, never retried, to protect quota." -ForegroundColor DarkGray
$started = Get-Date
& $py calibration\score_naren_ceiling.py --run 2>&1 | Tee-Object -FilePath $log -Append
$code = $LASTEXITCODE
$elapsed = (Get-Date) - $started

Copy-Item $log $archive -Force
Write-Host "`n=== finished in $([int]$elapsed.TotalMinutes) min $([int]$elapsed.Seconds) s ===" -ForegroundColor Cyan
Write-Host "log      : $log  (archived: $archive)" -ForegroundColor White
Write-Host "artifact : artifacts\naren_ceiling.json" -ForegroundColor White
Write-Host "`nRe-read the result at zero cost with:" -ForegroundColor Cyan
Write-Host "  $py calibration\score_naren_ceiling.py --load artifacts\naren_ceiling.json" -ForegroundColor White
if ($code -ne 0) {
    Write-Host "`nNOTE: the scored run exited $code - treat the tables above as partial." -ForegroundColor Red
}
