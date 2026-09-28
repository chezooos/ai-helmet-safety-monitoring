# AI Helmet Safety Monitoring - always-on server starter
$ErrorActionPreference = "Continue"
$ProjectDir = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $ProjectDir "app.py"))) {
    $ProjectDir = "C:\Users\COM\Desktop\lg"
}

$LogDir = Join-Path $ProjectDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir "server.log"

function Write-Log([string]$Message) {
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Test-PortOpen([int]$Port) {
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        return $null -ne $conn
    } catch {
        return $false
    }
}

if (Test-PortOpen 5000) {
    Write-Log "Server already listening on port 5000"
    exit 0
}

$pyCmd = Get-Command py -ErrorAction SilentlyContinue
if ($pyCmd) {
    $exe = $pyCmd.Source
    $args = "-3 `"$ProjectDir\app.py`""
} else {
    $exe = "$env:LocalAppData\Programs\Python\Python312\python.exe"
    $args = "`"$ProjectDir\app.py`""
}

Write-Log "Starting: $exe $args"
$proc = Start-Process -FilePath $exe -ArgumentList $args -WorkingDirectory $ProjectDir -WindowStyle Hidden -PassThru
Write-Log ("Started PID {0}" -f $proc.Id)
exit 0
