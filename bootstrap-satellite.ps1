param(
  [string]$Python = 'python.exe',
  [string]$Node = 'node.exe',
  [string]$Npm = 'npm.cmd'
)
$ErrorActionPreference = 'Stop'
$satelliteRoot = $PSScriptRoot
$satelliteRuntime = Join-Path $satelliteRoot '.satellite-runtime'

function Invoke-SatelliteChecked {
  param([string]$Executable, [string[]]$Arguments)
  & $Executable @Arguments
  if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Executable. See the output above." }
}

# Check prerequisite versions before installing anything. No global pip/npm writes.
$satellitePythonExe = (Get-Command $Python -ErrorAction Stop).Source
$satelliteNodeExe = (Get-Command $Node -ErrorAction Stop).Source
$satelliteNpmExe = (Get-Command $Npm -ErrorAction Stop).Source
$satelliteNpmCli = Join-Path (Split-Path -Parent $satelliteNpmExe) 'node_modules\npm\bin\npm-cli.js'
if (-not (Test-Path -LiteralPath $satelliteNpmCli -PathType Leaf)) { throw 'Cannot locate npm-cli.js next to npm.cmd. Pass -Npm pointing to the real npm installation, not a package-manager shim.' }
$satellitePythonVersion = & $satellitePythonExe -c 'import sys; print(str(sys.version_info.major) + "." + str(sys.version_info.minor))'
if ($LASTEXITCODE -ne 0 -or $satellitePythonVersion.Trim() -ne '3.12') { throw 'Use Python 3.12 (the tested backend and MCP version).' }
$satelliteNodeVersion = & $satelliteNodeExe --version
if ($LASTEXITCODE -ne 0 -or [int]($satelliteNodeVersion.Trim().TrimStart('v').Split('.')[0]) -lt 24) { throw 'Use Node.js >=24. Pass -Node with its executable path if the PATH version is older.' }
New-Item -ItemType Directory -Path $satelliteRuntime -Force | Out-Null
$satelliteAppPython = Join-Path $satelliteRuntime 'app\Scripts\python.exe'
$satelliteMcpPython = Join-Path $satelliteRuntime 'python\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $satelliteAppPython)) {
  Invoke-SatelliteChecked $satellitePythonExe @('-m','venv',(Join-Path $satelliteRuntime 'app'))
}
if (-not (Test-Path -LiteralPath $satelliteMcpPython)) {
  Invoke-SatelliteChecked $satellitePythonExe @('-m','venv',(Join-Path $satelliteRuntime 'python'))
}
Invoke-SatelliteChecked $satelliteAppPython @('-m','ensurepip','--upgrade')
Invoke-SatelliteChecked $satelliteMcpPython @('-m','ensurepip','--upgrade')
Invoke-SatelliteChecked $satelliteAppPython @('-m','pip','install','-r',(Join-Path $satelliteRoot 'backend\requirements-satellite.txt'))
Invoke-SatelliteChecked $satelliteMcpPython @('-m','pip','install','-r',(Join-Path $satelliteRoot 'backend\mcp\python-runtime.lock'))
Invoke-SatelliteChecked $satelliteMcpPython @('-m','pip','install','-r',(Join-Path $satelliteRoot 'backend\requirements-satellite-mcp.txt'))
$satellitePreviousPath = $env:PATH
try {
  # Run npm itself and its lifecycle scripts with the explicitly selected Node.
  $env:PATH = (Split-Path -Parent $satelliteNodeExe) + [IO.Path]::PathSeparator + $satellitePreviousPath
  Invoke-SatelliteChecked $satelliteNodeExe @($satelliteNpmCli,'--prefix',(Join-Path $satelliteRoot 'backend\mcp'),'ci')
  Invoke-SatelliteChecked $satelliteNodeExe @($satelliteNpmCli,'--prefix',(Join-Path $satelliteRoot 'frontend'),'ci')
} finally { $env:PATH = $satellitePreviousPath }
Invoke-SatelliteChecked $satelliteAppPython @((Join-Path $satelliteRoot 'backend\scripts\verify_satellite_dataset.py'))
Invoke-SatelliteChecked $satelliteMcpPython @((Join-Path $satelliteRoot 'backend\scripts\prepare_satellite_mcp.py'),'--node',$satelliteNodeExe)
Write-Output 'Prepared two isolated Python environments, local dependencies, observed DuckDB and MCP config.'
Write-Output 'No API credentials are required. No real satellite control is connected.'
Write-Output 'Next: .\start-satellite.ps1 (or pass -Node explicitly for frontend too). See HANDOFF.md for tests and boundaries.'
