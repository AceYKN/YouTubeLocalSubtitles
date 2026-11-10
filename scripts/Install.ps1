$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:UV_CACHE_DIR = Join-Path $projectRoot 'cache\uv'
$env:npm_config_cache = Join-Path $projectRoot 'cache\npm'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot 'runtime\python'
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Please install uv, then run Install.cmd again.' }
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'Please install Node.js LTS, then run Install.cmd again.' }
$nodeMajor = [int]((& node --version) -replace '^v(\d+).*','$1')
if ($nodeMajor -lt 22) { throw 'Node.js 22 or newer is required.' }
uv sync --frozen --no-dev
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
& (Join-Path $projectRoot '.venv\Scripts\python.exe') -X utf8 scripts\install_media_provider.py
if ($LASTEXITCODE -ne 0) { throw 'Media helper installation failed.' }
npm.cmd ci --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw 'Extension dependency installation failed.' }
npm.cmd run build
if ($LASTEXITCODE -ne 0) { throw 'Extension build failed.' }
& (Join-Path $projectRoot '.venv\Scripts\python.exe') -X utf8 scripts\download_models.py
if ($LASTEXITCODE -ne 0) { throw 'Model download failed. Run Install.cmd again to resume.' }
Write-Host 'Ready. Run Start.cmd, then load the dist folder in Chrome.'
