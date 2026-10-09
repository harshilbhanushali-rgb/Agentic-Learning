# Noise-floor control run for Layer D: run the SAME 19 transcripts with NOTHING changed,
# so the variance between two identical runs can be measured. Compare afterwards with:
#     python calibration/measure_scoring_noise.py --a arm3_run1_20260810 --b public
#
# Opens in its own window and stays open (-NoExit from the launcher) so the run is visible
# and its final summary readable.
#
# WHY THE GUARD BELOW EXISTS (learned the hard way, 2026-08-10):
# A previous attempt was silently corrupted because an EARLIER run was still alive as an OS
# process. Claude Code had reported that background task as "stopped", but that is the
# harness's own bookkeeping -- it does not kill the process. Two runs then shared one
# database and one checkpoint store: the old one marked transcripts done, the new one
# skipped 10 of 19 as "already done", and the log still printed "Ego Trap batch complete".
# The result was 28 duplicated gap_events and a measurement that meant nothing.
# NEVER clear Layer D data while another run might be alive.

$ErrorActionPreference = "Stop"
Set-Location "C:\PF\Joveo\CS-platform\Brain"

$py  = "..\.venv\Scripts\python.exe"
$log = "logs\run_ego_trap_noisefloor3.log"
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"

Write-Host "=== Layer D noise-floor control run ===" -ForegroundColor Cyan

# --- Guard 1: no OTHER Ego Trap run may be alive -----------------------------
# Matches on the command line rather than on "any python process": a blanket check trips on
# transient one-second diagnostic queries and would make this script unusable. What actually
# corrupts a clear is a concurrent LONG run holding the same DB and checkpoint store.
$running = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
             Where-Object { $_.CommandLine -match 'run_ego_trap|response_taxonomy|run_v2|main\.py' })
if ($running.Count -gt 0) {
    Write-Host "ABORTING: a pipeline run is already alive - clearing now would corrupt both:" -ForegroundColor Red
    $running | ForEach-Object { "  PID $($_.ProcessId): $($_.CommandLine)" }
    Write-Host "Wait for it, or kill it, then re-run this script." -ForegroundColor Red
    exit 1
}
Write-Host "[guard] no competing pipeline run detected - safe to clear" -ForegroundColor Green

# --- Guard 2: the comparison baseline must exist before we wipe anything -----
# Uses a real script file, not an inline `python -c`: PowerShell mangles the quoting of any
# -c snippet containing SQL string literals (a documented CLAUDE.md gotcha, and it broke
# this guard on the first attempt -- the SQL arrived at Python with its quotes stripped).
& $py ops\_check_baseline_schema.py arm3_run1_20260810
if ($LASTEXITCODE -ne 0) {
    Write-Host "ABORTING: baseline schema arm3_run1_20260810 not found - nothing to compare against." -ForegroundColor Red
    exit 1
}
Write-Host "[guard] baseline present" -ForegroundColor Green

# --- Clear and run ----------------------------------------------------------
Write-Host "`n[1/2] Clearing Layer D tables and ego_trap checkpoints..." -ForegroundColor Yellow
& $py ops\clear_ego_trap_data.py
if ($LASTEXITCODE -ne 0) { Write-Host "clear failed" -ForegroundColor Red; exit 1 }

Write-Host "`n[2/2] Running Layer D on 20 most recent transcripts (~40 min)." -ForegroundColor Yellow
Write-Host "      ~35s per Gemma call, ~4 calls per transcript. Output-token bound." -ForegroundColor DarkGray
$started = Get-Date
& $py ops\run_ego_trap.py --limit 20 2>&1 | Tee-Object -FilePath $log
$elapsed = (Get-Date) - $started

Write-Host "`n=== finished in $([int]$elapsed.TotalMinutes) min $([int]$elapsed.Seconds) s ===" -ForegroundColor Cyan
Write-Host "Now compare the two runs:" -ForegroundColor Cyan
Write-Host "  $py calibration\measure_scoring_noise.py --a arm3_run1_20260810 --b public" -ForegroundColor White
