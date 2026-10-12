$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$pythonExe = "J:\environment\Anaconda\envs\agent_env\python.exe"
$activateScript = "J:\environment\Anaconda\envs\agent_env\Scripts\Activate.ps1"

if (-not (Test-Path $pythonExe)) {
    Write-Error "找不到指定的 Python 环境：$pythonExe"
    exit 1
}

# 如果 .env 不存在，自动创建（默认使用项目自带的 SQLite 数据库）
$envFile = "$root\backend\.env"
if (-not (Test-Path $envFile)) {
    Write-Host '正在创建后端配置文件 .env（使用 SQLite）...'
@"
DATABASE_URL=sqlite:///./ontology_demo.db
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
"@ | Out-File -FilePath $envFile -Encoding utf8
}

Write-Host '正在安装后端依赖到已存在的 Anaconda 环境...'
& $pythonExe -m pip install --upgrade pip
& $pythonExe -m pip install -r "$root\backend\requirements.txt"

Write-Host '正在安装前端依赖...'
Set-Location "$root\frontend"
npm install
Set-Location $root

$backendCommand = "& '$pythonExe' -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
$frontendCommand = "Set-Location '$root\frontend'; npm run dev -- --host 0.0.0.0"

Write-Host '正在启动后端和前端服务...'
Start-Process powershell -ArgumentList '-NoExit', '-Command', $backendCommand -WorkingDirectory "$root\backend"
Start-Process powershell -ArgumentList '-NoExit', '-Command', $frontendCommand -WorkingDirectory "$root\frontend"

Write-Host '启动完成。'
Write-Host '后端: http://localhost:8000'
Write-Host '前端: http://localhost:5173'
