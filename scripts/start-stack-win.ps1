# start-stack-win.ps1 - AeroLift stack launcher / guardian for the Windows browser.
#
#   Sin privilegios de administrador: usa la socket-activation de WSL/systemd
#   para despertar docker.service y levantar el stack.
#
#   Por que se cae el stack: WSL termina la instancia cuando queda ~15 s sin
#   procesos "cliente" WSL activos (una sesion wsl.exe). Docker/containers
#   DENTRO de la VM NO cuentan como actividad -> al terminar la ultima
#   invocacion wsl.exe, la instancia se apaga y todo se reinicia. Las sondas
#   TCP de este script tampoco cuentan. Por eso este script mantiene una
#   sesion WSL persistente (`wsl -e /usr/bin/sleep` por horas): mientras esa
#   sesion este viva la instancia no se considera idle y el stack no se cae.
#   (Tambien se deja `vmIdleTimeout=-1` en ~/.wslconfig para que ni la VM se
#   apague por idle.)
#
# Uso:
#   & scripts\start-stack-win.ps1                  # Once: arranca y verifica
#   & scripts\start-stack-win.ps1 -OpenBrowser     # ... y abre el navegador
#   & scripts\start-stack-win.ps1 -Watch [3600]    # guardian por N segundos
#   Ctrl+C para salir del guardian (la sesion keepalive sigue ~6 h mas).
param(
    [long]$WatchSeconds = 0,
    [int]$ProbeInterval = 5,
    [switch]$OpenBrowser
)

$RepoWsl  = "/mnt/d/Gas_E/aerolift-analytics"
$Urls     = @("http://localhost:3000/", "http://localhost:8000/health", "http://localhost:8501/")

$keepalive = $null
function Start-KeepAlive {
    if ($script:keepalive -and -not $script:keepalive.HasExited) { return }
    $script:keepalive = Start-Process -WindowStyle Hidden -FilePath "wsl.exe" `
        -ArgumentList "-e", "/usr/bin/sleep", "21600" -PassThru
    Write-Host ("[keepalive] sesion WSL persistente activa (PID {0}) - la instancia ya no se apaga por idle" -f $script:keepalive.Id)
}

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
Start-KeepAlive

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
    Write-Host "(la sesion keepalive mantiene el stack vivo ~6 h; si vuelve a caer, re-ejecute con -Watch 3600)"
    exit $(if ($allOk) { 0 } else { 1 })
}

Write-Host "[guardian] vigiando por $WatchSeconds segundos (Ctrl+C para salir) ..."
$until = (Get-Date).AddSeconds($WatchSeconds)
while ((Get-Date) -lt $until) {
    Start-KeepAlive
    Start-Sleep -Seconds $ProbeInterval
    $ok = Get-Health
    if (@($ok | Where-Object {$_ -eq $false}).Count -eq 0) { continue }
    Write-Host ("[{0}] puerto caido -> relanzando docker compose ..." -f (Get-Date -Format HH:mm:ss))
    Start-Stack
}
if ($keepalive -and -not $keepalive.HasExited) { Stop-Process -Id $keepalive.Id -Force -ErrorAction SilentlyContinue }
Write-Host "[guardian] finalizado."