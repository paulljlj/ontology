param(
  [string]$Python = "",
  [string]$Node = "",
  [int]$BackendPort = 8001,
  [int]$FrontendPort = 5174
)
$ErrorActionPreference = 'Stop'
$satelliteRoot = $PSScriptRoot
$satelliteRuntime = Join-Path $satelliteRoot '.satellite-runtime'
New-Item -ItemType Directory -Path $satelliteRuntime -Force | Out-Null
if (-not $Python) {
  $satelliteLocalPython = Join-Path $satelliteRuntime 'app\Scripts\python.exe'
  $satelliteConda = 'J:\environment\Anaconda\envs\agent_env\python.exe'
  $Python = if (Test-Path -LiteralPath $satelliteLocalPython) { $satelliteLocalPython } elseif (Test-Path -LiteralPath $satelliteConda) { $satelliteConda } else { (Get-Command python.exe).Source }
}
if (-not $Node) {
  # bootstrap may use a portable Node that is deliberately not installed on PATH.
  $satelliteSavedConfig = Join-Path $satelliteRuntime 'mcp-servers.local.json'
  if (Test-Path -LiteralPath $satelliteSavedConfig) {
    $satelliteSavedNode = (Get-Content -LiteralPath $satelliteSavedConfig -Raw | ConvertFrom-Json).servers.filesystem.command
    if ($satelliteSavedNode -and (Test-Path -LiteralPath $satelliteSavedNode -PathType Leaf)) { $Node = [string]$satelliteSavedNode }
  }
  if (-not $Node) { $Node = (Get-Command node.exe).Source }
}
foreach ($satellitePort in @($BackendPort, $FrontendPort)) {
  $satelliteListener = Get-NetTCPConnection -LocalPort $satellitePort -State Listen -ErrorAction SilentlyContinue
  if ($satelliteListener) { throw "Port $satellitePort is already in use. Existing services were not stopped." }
}
$satelliteVite = Join-Path $satelliteRoot 'frontend\node_modules\vite\bin\vite.js'
if (-not (Test-Path -LiteralPath $satelliteVite)) { throw 'Install frontend dependencies in frontend first. This script does not modify any shared environment.' }
$satelliteOverrides = @{
  DATABASE_URL = ('sqlite:///' + (Join-Path $satelliteRuntime 'preview.db').Replace('\','/'))
  FEISHU_EVENT_ENABLED = 'false'
  LLM_PROVIDER = 'rule-based'
  CORS_ORIGINS = "http://127.0.0.1:$FrontendPort,http://localhost:$FrontendPort"
  VITE_API_BASE = "http://127.0.0.1:$BackendPort/api"
  PYTHONIOENCODING = 'utf-8'
}
$satellitePrevious = @{}
try {
  foreach ($satelliteKey in $satelliteOverrides.Keys) {
    $satellitePrevious[$satelliteKey] = [Environment]::GetEnvironmentVariable($satelliteKey, 'Process')
    [Environment]::SetEnvironmentVariable($satelliteKey, $satelliteOverrides[$satelliteKey], 'Process')
  }
  $satelliteBackendPath = Join-Path $satelliteRoot 'backend'
  $satelliteBackend = Start-Process -FilePath $Python -ArgumentList @('-m','uvicorn','app.main:app','--app-dir',('"' + $satelliteBackendPath + '"'),'--host','127.0.0.1','--port',"$BackendPort") -WorkingDirectory $satelliteBackendPath -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $satelliteRuntime 'backend.stdout.log') -RedirectStandardError (Join-Path $satelliteRuntime 'backend.stderr.log')
  $satelliteFrontend = Start-Process -FilePath $Node -ArgumentList @('"' + $satelliteVite + '"','--host','127.0.0.1','--port',"$FrontendPort",'--strictPort') -WorkingDirectory (Join-Path $satelliteRoot 'frontend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $satelliteRuntime 'frontend.stdout.log') -RedirectStandardError (Join-Path $satelliteRuntime 'frontend.stderr.log')
  $satelliteBackendInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($satelliteBackend.Id)"
  $satelliteFrontendInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($satelliteFrontend.Id)"
  if (-not $satelliteBackendInfo -or -not $satelliteFrontendInfo) { throw 'A preview process exited during startup. Check .satellite-runtime logs.' }
  [PSCustomObject]@{ backend_pid=$satelliteBackend.Id; frontend_pid=$satelliteFrontend.Id; backend_port=$BackendPort; frontend_port=$FrontendPort; workspace=$satelliteRoot; backend_created_utc=$satelliteBackendInfo.CreationDate.ToUniversalTime().ToString('o'); frontend_created_utc=$satelliteFrontendInfo.CreationDate.ToUniversalTime().ToString('o'); backend_executable=$satelliteBackendInfo.ExecutablePath; frontend_executable=$satelliteFrontendInfo.ExecutablePath } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $satelliteRuntime 'preview-processes.json') -Encoding utf8
  Write-Output "Satellite preview: http://127.0.0.1:$FrontendPort"
  Write-Output "API docs: http://127.0.0.1:$BackendPort/docs"
  Write-Output 'Isolated SQLite database; Feishu disabled; existing .env and databases unchanged.'
} finally {
  foreach ($satelliteKey in $satellitePrevious.Keys) { [Environment]::SetEnvironmentVariable($satelliteKey, $satellitePrevious[$satelliteKey], 'Process') }
}
