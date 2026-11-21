param([switch]$Rebuild, [int]$Port = 8080, [int]$ApiPort = 8000)

$ErrorActionPreference = 'Stop'
Set-Location (Join-Path (Split-Path -Parent $PSScriptRoot) 'flutter_application_1')

if ($Rebuild -or -not (Test-Path 'build\web\index.html')) {
    flutter build web --dart-define=USE_MOCK=false "--dart-define=API_BASE_URL=http://127.0.0.1:$ApiPort"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Set-Location "build\web"
Write-Host "前端地址 http://127.0.0.1:$Port" -ForegroundColor Cyan
python -m http.server $Port --bind 127.0.0.1
