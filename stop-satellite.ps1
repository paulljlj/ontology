$ErrorActionPreference = 'Stop'
$satelliteStateFile = Join-Path $PSScriptRoot '.satellite-runtime\preview-processes.json'
if (-not (Test-Path -LiteralPath $satelliteStateFile)) { Write-Output 'No saved satellite preview process IDs.'; exit 0 }
$satelliteState = Get-Content -LiteralPath $satelliteStateFile -Raw | ConvertFrom-Json
if ([IO.Path]::GetFullPath($satelliteState.workspace) -ne [IO.Path]::GetFullPath($PSScriptRoot)) { throw 'Saved process state belongs to another workspace.' }
foreach ($satelliteRole in @('backend','frontend')) {
  $satellitePid = [int]$satelliteState."$($satelliteRole)_pid"
  $satelliteProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $satellitePid"
  if (-not $satelliteProcess) { continue }
  $satelliteCreated = $satelliteState."$($satelliteRole)_created_utc"
  $satelliteExecutable = $satelliteState."$($satelliteRole)_executable"
  if (-not $satelliteCreated -or -not $satelliteExecutable) { throw 'Legacy process state has no creation-time identity. Inspect the process manually; no process was stopped.' }
  # PowerShell 7 may deserialize ISO JSON strings as DateTime; compare precise
  # instants rather than locale-dependent string formatting (also works in 5.1).
  $satelliteCreatedTicks = ([DateTimeOffset]$satelliteCreated).UtcDateTime.Ticks
  if ($satelliteProcess.CreationDate.ToUniversalTime().Ticks -ne $satelliteCreatedTicks -or $satelliteProcess.ExecutablePath -ne $satelliteExecutable) { throw "PID $satellitePid was reused or changed; it was not stopped." }
  $satelliteCommand = [string]$satelliteProcess.CommandLine
  if ($satelliteRole -eq 'backend') {
    $satelliteBackendPath = Join-Path $PSScriptRoot 'backend'
    if ($satelliteProcess.Name -ne 'python.exe' -or $satelliteCommand -notlike '*uvicorn app.main:app*' -or $satelliteCommand -notlike "*$satelliteBackendPath*" -or $satelliteCommand -notmatch ('--port\s+' + $satelliteState.backend_port + '(\s|$)')) { throw "PID $satellitePid is not the saved preview backend; it was not stopped." }
  } else {
    $satelliteVite = Join-Path $PSScriptRoot 'frontend\node_modules\vite\bin\vite.js'
    if ($satelliteProcess.Name -ne 'node.exe' -or $satelliteCommand -notlike "*$satelliteVite*" -or $satelliteCommand -notmatch ('--port\s+' + $satelliteState.frontend_port + '(\s|$)')) { throw "PID $satellitePid is not the saved preview frontend; it was not stopped." }
  }
  Stop-Process -Id $satellitePid
  Write-Output "Stopped satellite preview $satelliteRole (PID $satellitePid). Database and report files were preserved."
}
