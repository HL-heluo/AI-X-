param([switch]$Fabric, [int]$Port = 8000, [int]$GanachePort = 8545)

$ErrorActionPreference = 'Stop'
Set-Location (Join-Path (Split-Path -Parent $PSScriptRoot) 'backend')
$python = '.\.venv\Scripts\python.exe'
$demo = Join-Path (Get-Location) '.chain-demo'
New-Item -ItemType Directory -Path $demo -Force | Out-Null
$db = Join-Path $demo 'demo.db'
$newDb = -not (Test-Path -LiteralPath $db)
$keyFile = Join-Path $demo 'jwt.key'
if (-not (Test-Path -LiteralPath $keyFile)) {
    $secretBytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($secretBytes) } finally { $rng.Dispose() }
    [IO.File]::WriteAllText($keyFile, [Convert]::ToBase64String($secretBytes))
}

$env:PYTHONIOENCODING = 'utf-8'
$env:APP_ENV = 'dev'
$env:TEST_MODE = '0'
$env:WORKER_ENABLED = '1'
$env:JWT_SECRET = [IO.File]::ReadAllText($keyFile).Trim()
$env:PROVIDER = 'fake'
$env:VIDEO_PROVIDER = 'fake'
$env:STORAGE = 'local'
$env:DATABASE_URL = 'sqlite:///' + $db.Replace('\', '/')
$env:MEDIA_ROOT = Join-Path $demo 'media'
$env:PROVIDER_SPOOL_ROOT = Join-Path $demo 'spool'
$env:PUBLIC_BASE_URL = "http://127.0.0.1:$Port"
$env:CHAIN_ENABLED = '1'
$env:CHAIN_SYNC_PAUSED = '0'
$env:CHAIN_ID = '1337'
$env:CHAIN_CONTRACT_ADDRESS = ''
$env:CHAIN_PLATFORM_PRIVATE_KEY = ''
$env:CHAIN_RPC_URL = "http://127.0.0.1:$GanachePort"
$env:FABRIC_ENABLED = if ($Fabric) { '1' } else { '0' }
if ($Fabric -and ([string]$env:FABRIC_BRIDGE_TOKEN).Length -lt 24) {
    throw '请先配置与本机 Fabric 网关相同的 FABRIC_BRIDGE_TOKEN。'
}

& $python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($newDb) {
    & $python scripts/create_invite.py --code AIVIDEO-DEMO --uses 0 --note '本地双链演示'
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
& $python scripts/setup_chain.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "后端 http://127.0.0.1:$Port | 本地邀请码 AIVIDEO-DEMO" -ForegroundColor Cyan
& $python -m uvicorn app.main:app --host 127.0.0.1 --port $Port
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
