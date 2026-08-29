# start-stack-win.ps1 - AeroLift stack launcher / guardian for the Windows browser.
#
#   Sin privilegios de administrador: usa la socket-activation de WSL/symstemd
#   para despertar docker.service y levantar el stack. Diseñado para soportar
#   que WSL2 suspenda la VM periodicamente (snapd/standby -> systemd detiene
#   docker.service): en modo guardian relanza el stack automaticamente en ~5s.
#
# Uso:
#   & scripts\start-stack-win.ps1                  # Once: arranca y verifica
#   & scripts\start-stack-win.ps1 -OpenBrowser     # ... y abre el navegador
#   & scripts\start-stack-win.ps1 -Watch [3600]    # guardian por N segundos
#   Ctrl+C para salir del guardian.
param(
    [long]$WatchSeconds = 0,
    [int]$ProbeInterval = 5,
    [switch]$OpenBrowser
)

$RepoWsl  = "/mnt/d/Gas_E/aerolift-analytics"
$Urls     = @("http://localhost:3000/", "http://localhost:8000/health", "http://localhost:8501/")

function Test-Port($port, $timeoutMs = 1200) {
    try {
        $cli = [System.Net.Sockets.TcpClient]::new()
        $task = $cli.ConnectAsync("127.0.0.1", $port)
        if (-not $task.Wait($timeoutMs)) { $cli.Dispose(); return $false }
        if (-not $cli.Connected)          { $cli.Dispose(); return $false }
        $cli.Dispose(); return $true
    } catch { return $false }
}

function Get-Health {
    $ok = foreach ($u in $Urls) { Test-Port ([uri]$u).Port }
    return @($ok)
}

function Start-Stack {
    wsl -e bash -c "cd $RepoWsl && docker compose up -d" 2>$null | Out-Null
}

function Show-Health($ok) {
    for ($i = 0; $i -lt $Urls.Count; $i++) {
        Write-Output ("{0}  {1}" -f ($(if ($ok[$i]) { "OK " } else { "-- " })), $Urls[$i])
    }
}

Write-Host "[start-stack] levantando el stack ..."
Start-Stack

$deadline = (Get-Date).AddSeconds(150)
$ok = @($false, $false, $false)
while ((Get-Date) -lt $deadline) {
    $ok = Get-Health
    if (@($ok | Where-Object {$_ -eq $false}).Count -eq 0) { break }
    Start-Sleep -Seconds $ProbeInterval
}

$ok = Get-Health
Write-Host "[start-stack] estado:"
Show-Health $ok
$allOk = @($ok | Where-Object {$_ -eq $false}).Count -eq 0

if ($allOk -and $OpenBrowser) {
    Start-Process "http://localhost:3000/"
    Write-Host "[start-stack] abriendo http://localhost:3000/"
}

if ($WatchSeconds -le 0) {
    Write-Host "(para mantenerlo vivo: vuelva a ejecutarlo con -Watch 3600)"
    exit $(if ($allOk) { 0 } else { 1 })
}

Write-Host "[guardian] vigiando por $WatchSeconds segundos (Ctrl+C para salir) ..."
$until = (Get-Date).AddSeconds($WatchSeconds)
while ((Get-Date) -lt $until) {
    Start-Sleep -Seconds $ProbeInterval
    $ok = Get-Health
    if (@($ok | Where-Object {$_ -eq $false}).Count -eq 0) { continue }
    Write-Host ("[{0}] puerto caido -> relanzando docker compose ..." -f (Get-Date -Format HH:mm:ss))
    Start-Stack
}
Write-Host "[guardian] finalizado."