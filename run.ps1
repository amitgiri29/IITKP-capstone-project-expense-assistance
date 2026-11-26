# Start the API and the UI together on Windows, wait until both are healthy, open the browser.
# Close this window or press Ctrl+C to stop both. Logs: runtime\logs\api.log and ui.log
#   powershell -ExecutionPolicy Bypass -File run.ps1
#   $env:EA_API_PORT = 8100; $env:EA_UI_PORT = 8601; .\run.ps1
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$ApiPort = if ($env:EA_API_PORT) { [int]$env:EA_API_PORT } else { 8000 }
$UiPort = if ($env:EA_UI_PORT) { [int]$env:EA_UI_PORT } else { 8501 }
$Vpy = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Vpy)) { Write-Host 'No .venv found. Double-click setup.bat first.'; exit 1 }

foreach ($port in @($ApiPort, $UiPort)) {
    $client = New-Object Net.Sockets.TcpClient
    try { $client.Connect('127.0.0.1', $port); $busy = $true } catch { $busy = $false } finally { $client.Close() }
    if ($busy) { Write-Host "Port $port is already in use (is the app already running?). Set EA_API_PORT / EA_UI_PORT to use other ports."; exit 1 }
}

function Wait-Healthy($url, $seconds, $process, $name) {
    for ($i = 0; $i -lt $seconds; $i++) {
        try { Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 2 | Out-Null; return } catch { }
        if ($process.HasExited) { Write-Host "$name exited during startup. Last log lines:"; Get-Content "runtime\logs\$name.err.log" -Tail 20; throw "$name failed" }
        Start-Sleep -Seconds 1
    }
    throw "$name did not become healthy within $seconds s. See runtime\logs\$name.err.log"
}

New-Item -ItemType Directory -Force 'runtime\logs' | Out-Null
$api = $null; $ui = $null
try {
    Write-Host "Starting API on http://127.0.0.1:$ApiPort (first start may download the embedding model)..."
    $api = Start-Process -FilePath $Vpy -ArgumentList '-m', 'uvicorn', 'api.main:app', '--host', '127.0.0.1', '--port', $ApiPort `
        -RedirectStandardOutput 'runtime\logs\api.log' -RedirectStandardError 'runtime\logs\api.err.log' -NoNewWindow -PassThru
    Wait-Healthy "http://127.0.0.1:$ApiPort/health" 240 $api 'api'

    Write-Host "Starting UI on http://127.0.0.1:$UiPort ..."
    $env:EXPENSE_API_BASE_URL = "http://127.0.0.1:$ApiPort"
    $ui = Start-Process -FilePath $Vpy -ArgumentList '-m', 'streamlit', 'run', 'ui/app.py', '--server.port', $UiPort, `
        '--server.address', '127.0.0.1', '--server.headless', 'true', '--browser.gatherUsageStats', 'false' `
        -RedirectStandardOutput 'runtime\logs\ui.log' -RedirectStandardError 'runtime\logs\ui.err.log' -NoNewWindow -PassThru
    Wait-Healthy "http://127.0.0.1:$UiPort/_stcore/health" 60 $ui 'ui'

    Write-Host ''
    Write-Host '  SPARKS AI Lab - Expense Policy Assistant is running' -ForegroundColor Green
    Write-Host "  Open:  http://127.0.0.1:$UiPort"
    Write-Host "  API:   http://127.0.0.1:$ApiPort   (health: /health, /ready)"
    Write-Host '  Logs:  runtime\logs\'
    Write-Host '  Stop:  press Ctrl+C or close this window'
    Write-Host ''
    if (-not $env:EA_NO_BROWSER) { Start-Process "http://127.0.0.1:$UiPort" }
    while (-not $api.HasExited -and -not $ui.HasExited) { Start-Sleep -Seconds 2 }
    Write-Host 'A server stopped unexpectedly. See runtime\logs\.'
}
finally {
    Write-Host 'Stopping...'
    foreach ($p in @($ui, $api)) { if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } }
}
