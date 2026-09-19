# Pelica bot headless start/restart (no Chinese here: PowerShell 5.1 reads BOM-less ps1 as ANSI)
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_bot.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "python.exe" -and $_.CommandLine -like "*--bridge*"
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Output ("killed " + $_.ProcessId) }
Start-Sleep -Seconds 2

if (Test-Path "$root\data\bot_live.err.log") {
    Copy-Item "$root\data\bot_live.err.log" "$root\data\bot_live.prev.log" -Force
}

$py = Join-Path $root ".venv\Scripts\python.exe"
Start-Process -FilePath $py `
    -ArgumentList @("main.py", "--bridge", "wxhook") `
    -WorkingDirectory $root -WindowStyle Hidden `
    -RedirectStandardOutput "$root\data\bot_live.out.log" `
    -RedirectStandardError "$root\data\bot_live.err.log"
Write-Output "started"
