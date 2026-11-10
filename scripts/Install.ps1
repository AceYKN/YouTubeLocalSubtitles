$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:UV_CACHE_DIR = Join-Path $projectRoot 'cache\uv'
$env:npm_config_cache = Join-Path $projectRoot 'cache\npm'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot 'runtime\python'
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Please install uv, then run Install.cmd again.' }
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'Please install Node.js LTS, then run Install.cmd again.' }
uv sync --frozen --no-dev
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
npm.cmd ci --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw 'Extension dependency installation failed.' }
npm.cmd run build
if ($LASTEXITCODE -ne 0) { throw 'Extension build failed.' }
& (Join-Path $projectRoot '.venv\Scripts\python.exe') -X utf8 scripts\download_models.py
if ($LASTEXITCODE -ne 0) { throw 'Model download failed. Run Install.cmd again to resume.' }
Write-Host 'Ready. Run Start.cmd, then load the dist folder in Chrome.'
