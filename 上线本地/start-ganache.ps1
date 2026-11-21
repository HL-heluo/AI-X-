param([int]$Port = 8545)

$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$chainDir = Join-Path $project '双链存证'
$demoRoot = Join-Path $project 'backend/.chain-demo'
New-Item -ItemType Directory -Force -Path $demoRoot | Out-Null
$entryPoint = Join-Path $chainDir 'node_modules/ganache/dist/node/cli.js'
if (-not (Test-Path -LiteralPath $entryPoint)) {
    throw 'Ganache 依赖未安装。请先在双链存证目录执行 npm ci。'
}

$stateDir = Join-Path $demoRoot 'ganache'
& node $entryPoint --server.host 127.0.0.1 --server.port $Port --chain.chainId 1337 `
    --wallet.deterministic --database.dbPath $stateDir --logging.quiet
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
