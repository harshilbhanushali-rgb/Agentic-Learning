Set-Location "C:\PF\Joveo\CS-platform\Brain"
Write-Host "=== Step 1/3: clear_data.py (wiping public schema -- already snapshotted to subset150_nested_20260731) ===" -ForegroundColor Cyan
..\.venv\Scripts\python.exe clear_data.py
if (-not $?) { Write-Host "clear_data.py failed -- stopping." -ForegroundColor Red; return }

Write-Host "`n=== Step 2/3: run_v2_subset.py recordings_subset150 (real Gemma calls, this is the long part) ===" -ForegroundColor Cyan
$env:PYTHONUNBUFFERED = "1"
..\.venv\Scripts\python.exe run_v2_subset.py recordings_subset150 | Tee-Object -FilePath logs\run_subset150_postfix_20260731.log
if (-not $?) { Write-Host "run_v2_subset.py failed -- stopping." -ForegroundColor Red; return }

Write-Host "`n=== Step 3/3: calibration\compare_matching_subset.py --sweep-floor (fresh primary_topics, zero Gemma) ===" -ForegroundColor Cyan
..\.venv\Scripts\python.exe calibration\compare_matching_subset.py --sweep-floor | Tee-Object -FilePath logs\compare_matching_postfix_20260731.log

Write-Host "`n=== Done. Logs: logs\run_subset150_postfix_20260731.log, logs\compare_matching_postfix_20260731.log ===" -ForegroundColor Green
