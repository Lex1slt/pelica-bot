# Pelica bot stopper (ASCII only: PS 5.1 reads BOM-less ps1 as ANSI)
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stop_bot.ps1
$bot = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "python.exe" -and $_.CommandLine -like "*--bridge*"
}
if ($bot) {
    $bot | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Output ("stopped " + $_.ProcessId)
    }
} else {
    Write-Output "bot is not running"
}
Write-Output "(WeChat itself is still running; close it manually if needed)"
