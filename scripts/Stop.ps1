$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$recordPath = Join-Path $projectRoot 'runtime\service.json'
if (-not (Test-Path -LiteralPath $recordPath)) { Write-Host 'No managed service record.'; exit 0 }
$record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
$serviceProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($record.pid)" -ErrorAction SilentlyContinue
if ($serviceProcess) {
    $expectedPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if ($serviceProcess.ExecutablePath -ne $expectedPython -or $serviceProcess.CommandLine -notmatch 'server\.main') { throw 'PID no longer belongs to this project. No process was stopped.' }
    # Windows venv python.exe is a launcher; the actual interpreter and its
    # llama process can be grandchildren. Walk only this validated process tree.
    $processSnapshot = @(Get-CimInstance Win32_Process)
    $frontier = @([int]$record.pid)
    $descendants = @()
    while ($frontier.Count -gt 0) {
        $children = @($processSnapshot | Where-Object { $_.ParentProcessId -in $frontier -and (($_.Name -eq 'python.exe' -and $_.CommandLine -match 'server\.main') -or $_.ExecutablePath -like "$projectRoot\runtime\llama\*") })
        $descendants += $children
        $frontier = @($children | ForEach-Object { [int]$_.ProcessId })
    }
    [array]::Reverse($descendants)
    foreach ($child in $descendants) { Stop-Process -Id $child.ProcessId -ErrorAction SilentlyContinue }
    Stop-Process -Id $record.pid -ErrorAction SilentlyContinue
}
Remove-Item -LiteralPath $recordPath
Write-Host 'Local subtitle service stopped.'
