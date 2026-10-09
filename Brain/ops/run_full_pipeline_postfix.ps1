Set-Location "C:\PF\Joveo\CS-platform\Brain"
Write-Host "=== Full V2 pipeline run: 416 real transcripts from recordings/ (post-fix: topic_grouping split + gemma retry) ===" -ForegroundColor Cyan
Write-Host "Postgres public schema was already cleared; prior 150-call run is snapshotted at subset150_postfix_20260731." -ForegroundColor Cyan
$env:PYTHONUNBUFFERED = "1"
..\.venv\Scripts\python.exe run_v2_subset.py recordings | Tee-Object -FilePath logs\run_full_pipeline_postfix_20260731.log
if (-not $?) { Write-Host "run_v2_subset.py failed." -ForegroundColor Red } else { Write-Host "`n=== Full pipeline run complete. Log: logs\run_full_pipeline_postfix_20260731.log ===" -ForegroundColor Green }
