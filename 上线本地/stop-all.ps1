# 停止本机后端(8000)与前端(8080)。
foreach ($port in 8000, 8080) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conns) {
        foreach ($conn in $conns) {
            try {
                Stop-Process -Id $conn.OwningProcess -Force -ErrorAction Stop
                Write-Host "已停止端口 $port 的进程（PID $($conn.OwningProcess)）" -ForegroundColor Yellow
            } catch {
                Write-Host "停止端口 $port 失败：$($_.Exception.Message)" -ForegroundColor Red
            }
        }
    } else {
        Write-Host "端口 $port 没有在监听" -ForegroundColor DarkGray
    }
}
