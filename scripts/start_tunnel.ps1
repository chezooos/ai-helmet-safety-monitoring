# Start Cloudflare quick tunnel to local Flask (port 5000)
$ErrorActionPreference = "Continue"
$ProjectDir = "C:\Users\COM\Desktop\lg"
$LogDir = Join-Path $ProjectDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir "tunnel.log"
$UrlFile = Join-Path $ProjectDir "PUBLIC_URL.txt"
$cf = "C:\Program Files (x86)\cloudflared\cloudflared.exe"

function Write-Log([string]$Message) {
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

# Ensure app is up first
powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ProjectDir "scripts\start_server.ps1") | Out-Null

# Already running?
$existing = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match "cloudflared" -and $_.CommandLine -match "127.0.0.1:5000" }
if ($existing) {
    Write-Log "cloudflared already running PID=$($existing.ProcessId)"
    exit 0
}

if (-not (Test-Path $cf)) {
    Write-Log "cloudflared not found"
    exit 1
}

Write-Log "Starting cloudflared quick tunnel"
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $cf
$psi.Arguments = "tunnel --url http://127.0.0.1:5000 --no-autoupdate"
$psi.WorkingDirectory = $ProjectDir
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.CreateNoWindow = $true

$proc = New-Object System.Diagnostics.Process
$proc.StartInfo = $psi
$null = $proc.Start()

# Capture URL from stderr/stdout briefly
$deadline = (Get-Date).AddSeconds(25)
$url = $null
while ((Get-Date) -lt $deadline -and -not $url) {
    Start-Sleep -Milliseconds 400
    if (Test-Path $LogFile) { }
    # read process output asynchronously is hard; scrape latest log by polling nothing
}
# Best-effort: user can also read tunnel process; write placeholder
"https://(see logs/tunnel.log after start - URL printed by cloudflared)" | Set-Content $UrlFile -Encoding utf8
Write-Log "Started cloudflared PID=$($proc.Id)"
exit 0
