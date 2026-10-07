$ErrorActionPreference = 'Stop'
$taskIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$taskPrincipal = New-Object Security.Principal.WindowsPrincipal($taskIdentity)
if (-not $taskPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'Right-click open_firewall.bat and choose Run as administrator.'
    exit 1
}
$taskRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONUTF8 = '1'
$taskResolvedPython = & py -3 (Join-Path $PSScriptRoot 'run.py') --python
if ($LASTEXITCODE -ne 0) { throw 'First run install.bat to install the project environment.' }
$taskPython = (Resolve-Path -LiteralPath ([string]$taskResolvedPython)).Path
$taskPort = 8000
$taskConfig = Join-Path $taskRoot 'server_config.json'
if (Test-Path $taskConfig) { $taskSettings = Get-Content -Raw -Encoding UTF8 $taskConfig | ConvertFrom-Json; $taskPort = $taskSettings.port }
Get-NetFirewallRule -DisplayName 'NaryadAI LAN test','NaryadAI VPN test' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName 'NaryadAI LAN test' -Direction Inbound -Action Allow -Protocol TCP -LocalPort $taskPort -Program $taskPython -Profile Private -RemoteAddress LocalSubnet | Out-Null
New-NetFirewallRule -DisplayName 'NaryadAI VPN test' -Direction Inbound -Action Allow -Protocol TCP -LocalPort $taskPort -Program $taskPython -Profile Any -RemoteAddress '100.64.0.0/10' | Out-Null
Write-Host "Ready. Port $taskPort is allowed for the private LAN and Tailscale IPv4 addresses."
