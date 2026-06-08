$ErrorActionPreference = "Stop"

Set-Location -Path $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$port = if ($env:PORT) { [int]$env:PORT } else { 7860 }
$hostName = if ($env:HOST) { $env:HOST } else { "127.0.0.1" }
$appUrl = "http://${hostName}:${port}"
$serverScript = Join-Path $PSScriptRoot "server.py"

if (-not (Test-Path -LiteralPath $venvPython)) {
  python -m venv .venv
}

& $venvPython -m pip install -r requirements.txt

if (-not $env:OLLAMA_MODEL) {
  $env:OLLAMA_MODEL = "llama3.1"
}

if (-not $env:OLLAMA_URL) {
  $env:OLLAMA_URL = "http://localhost:11434/api/generate"
}

function Get-ProjectServerProcesses {
  Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object {
    $_.CommandLine -like "*$serverScript*" -or
    $_.CommandLine -like "*$venvPython* server.py*" -or
    $_.CommandLine -match [regex]::Escape($PSScriptRoot) + '.*server\.py'
  }
}

function Wait-ForServerStop {
  param([int]$TargetPort)

  for ($i = 0; $i -lt 20; $i++) {
    $listener = Get-NetTCPConnection -LocalPort $TargetPort -State Listen -ErrorAction SilentlyContinue
    if (-not $listener) {
      return
    }
    Start-Sleep -Milliseconds 300
  }
}

$projectProcesses = @(Get-ProjectServerProcesses)
if ($projectProcesses.Count -gt 0) {
  $projectProcesses | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }
  Wait-ForServerStop -TargetPort $port
}

$listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
  $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener[0].OwningProcess)" |
    Select-Object -First 1 ProcessId, Name, ExecutablePath, CommandLine
  throw "Port $port is already in use by process $($owner.ProcessId): $($owner.CommandLine)"
}

Start-Process `
  -FilePath $venvPython `
  -ArgumentList "server.py" `
  -WorkingDirectory $PSScriptRoot `
  -WindowStyle Hidden | Out-Null

$ready = $false
for ($i = 0; $i -lt 30; $i++) {
  try {
    Invoke-RestMethod "$appUrl/health" -TimeoutSec 1 | Out-Null
    $ready = $true
    break
  } catch {
    Start-Sleep -Milliseconds 500
  }
}

if (-not $ready) {
  throw "Server did not become ready at $appUrl"
}

Start-Process $appUrl
Write-Host "AI Roleplay Engine is running at $appUrl"
