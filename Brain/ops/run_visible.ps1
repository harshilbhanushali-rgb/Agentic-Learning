<#
.SYNOPSIS
  Run a Brain script in a NEW, VISIBLE console window that stays open.

.DESCRIPTION
  Long Gemma runs used to be launched detached, so the only way to follow one was to ask
  an agent to tail a log. This opens a real window: progress is visible live, and -NoExit
  keeps it open afterwards so a traceback cannot vanish.

  Also bypasses the DNS block on neon.tech. Measured 2026-08-12: the system resolver
  returns "DNS operation REFUSED" for *.neon.tech while google.com resolves normally,
  8.8.8.8 resolves the neon host fine, and TCP 5432 to every resolved address succeeds --
  so the block is DNS-only and the database itself is reachable. libpq's hostaddr supplies
  the address and skips resolution while `host` stays in the URL, which Neon REQUIRES: it
  routes by TLS SNI and binds SCRAM to the hostname, so dropping `host` would fail
  authentication, not merely routing.

  Nothing on the machine is modified -- no hosts file, no .env, no DNS settings. The
  rewritten URL lives in the launched process only. Omit -HostAddr on a network where
  neon.tech resolves normally and the URL is passed through untouched.

.NOTES
  Two bugs worth not reintroducing:
    * The parameter must NOT be called -Args. $Args is a PowerShell automatic variable,
      and declaring it makes the script fail before its first line runs.
    * The inner script must call the venv python by full path. A bare `python` picks up
      whatever is on PATH, which has neither the dependencies nor Brain's config.

.EXAMPLE
  .\ops\run_visible.ps1 -Script calibration/validate_rubrics.py -HostAddr 18.138.49.39
  .\ops\run_visible.ps1 -Script calibration/validate_rubrics.py -ScriptArgs '--scope','all','--run'
#>
param(
  [Parameter(Mandatory = $true)][string]$Script,
  [string[]]$ScriptArgs = @(),
  [string]$HostAddr = "",
  [string]$Log = ""
)

$ErrorActionPreference = "Stop"
$brain = Split-Path -Parent $PSScriptRoot
$py = Join-Path (Split-Path -Parent $brain) ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) { throw "python not found at $py" }
if (-not (Test-Path (Join-Path $brain $Script))) { throw "script not found under Brain/: $Script" }

if (-not $Log) {
  $name = [System.IO.Path]::GetFileNameWithoutExtension($Script)
  $Log = "logs\$name.log"
}
$logDir = Join-Path $brain (Split-Path -Parent $Log)
if ($logDir -and -not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }

$argLine = ($ScriptArgs | ForEach-Object { '"' + $_ + '"' }) -join ' '

# Written to a temp .ps1 and launched with -File. A multi-line -Command string is fragile
# about quoting and newlines; a file is not.
$lines = @(
  "Set-Location '$brain'",
  '$env:PYTHONUNBUFFERED = "1"',
  '$env:PYTHONIOENCODING = "utf-8"'
)
if ($HostAddr) {
  $lines += @(
    "`$u = & '$py' -c `"from config import load_config; print(load_config().database_url)`"",
    'if ($u -and $u -notmatch "hostaddr=") {',
    '  $sep = if ($u -match "\?") { "&" } else { "?" }',
    "  `$env:DATABASE_URL = `$u + `$sep + 'hostaddr=$HostAddr'",
    '  Write-Host "[hostaddr] DNS bypassed; host kept in the URL for SNI/SCRAM." -ForegroundColor DarkCyan',
    '}'
  )
}
$lines += @(
  "Write-Host '[run] $Script $argLine' -ForegroundColor Cyan",
  "Write-Host '[log] $Log' -ForegroundColor DarkGray",
  "Write-Host ''",
  # cmd /c with 2>&1 rather than PowerShell redirection: under ErrorActionPreference=Stop,
  # `& $py ... 2>&1 | Tee-Object` wraps each stderr line in an ErrorRecord and turns a clean
  # exit into a fatal pipeline error, so Python tracebacks never reach the log.
  "cmd /c `"`"$py`" $Script $argLine 2>&1`" | Tee-Object -FilePath '$Log'",
  "Write-Host ''",
  "Write-Host '[done] this window stays open; close it when finished.' -ForegroundColor Cyan"
)

$runner = Join-Path $env:TEMP ("brain_run_" + [guid]::NewGuid().ToString("N").Substring(0, 8) + ".ps1")
[System.IO.File]::WriteAllLines($runner, $lines, [System.Text.UTF8Encoding]::new($false))

Start-Process powershell -ArgumentList @(
  "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $runner
)
Write-Host "Launched in a new window. Log: $Log"
