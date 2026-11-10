param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run Install.cmd first.' }
$port = 18765
$configPath = Join-Path $projectRoot 'config.local.json'
if (Test-Path -LiteralPath $configPath) { $port = (Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json).port }
$setupUrl = "http://127.0.0.1:$port/setup"
$healthy = $false
try { $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 2; $healthy = $health.version -eq '0.1.0' -and $null -ne $health.models_present } catch {}
if (-not $healthy) {
    New-Item -ItemType Directory -Path (Join-Path $projectRoot 'logs') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $projectRoot 'runtime') -Force | Out-Null
    $service = Start-Process -FilePath $pythonPath -ArgumentList @('-X','utf8','-m','server.main') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $projectRoot 'logs\service.stdout.log') -RedirectStandardError (Join-Path $projectRoot 'logs\service.stderr.log')
    [pscustomobject]@{pid=$service.Id;root=$projectRoot;started=(Get-Date).ToUniversalTime().ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $projectRoot 'runtime\service.json') -Encoding UTF8
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 500
        if ($service.HasExited) { throw 'Service stopped unexpectedly. See logs/service.stderr.log.' }
        try { $health=Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 1; if ($health.version -eq '0.1.0') { $healthy=$true;break } } catch {}
    }
}
if (-not $healthy) { throw 'Service did not become ready. Check logs.' }
Write-Host "Local subtitle service: $setupUrl"
if (-not $NoBrowser) { Start-Process $setupUrl -WindowStyle Hidden }
