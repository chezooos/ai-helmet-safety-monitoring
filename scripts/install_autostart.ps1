# Register always-on server at Windows logon
$ErrorActionPreference = "Stop"
$ProjectDir = "C:\Users\COM\Desktop\lg"
$ScriptPath = Join-Path $ProjectDir "scripts\start_server.ps1"
$TaskName = "AIHelmetSafetyServer"

if (-not (Test-Path $ScriptPath)) {
    throw "Missing $ScriptPath"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ScriptPath`""

$triggerLogon = New-ScheduledTaskTrigger -AtLogOn
$triggerStartup = New-ScheduledTaskTrigger -AtStartup

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger @($triggerLogon, $triggerStartup) `
    -Settings $settings `
    -Principal $principal `
    -Description "Keep AI helmet safety Flask server running on port 5000" | Out-Null

# Watchdog every 5 minutes in case process dies
$WatchName = "AIHelmetSafetyServerWatch"
$watchAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ScriptPath`""
$watchTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration ([TimeSpan]::MaxValue)
Unregister-ScheduledTask -TaskName $WatchName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask `
    -TaskName $WatchName `
    -Action $watchAction `
    -Trigger $watchTrigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Restart AI helmet server if port 5000 is down" | Out-Null

# Start now
& $ScriptPath

Write-Host "Installed:"
Write-Host " - $TaskName (at logon/startup)"
Write-Host " - $WatchName (every 5 min)"
Write-Host "Web app: http://127.0.0.1:5000"
