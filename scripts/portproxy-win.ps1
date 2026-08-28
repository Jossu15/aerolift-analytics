param(
    [int[]]$Ports = @(3000, 8000, 8501)
)

$isElevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isElevated) {
    $args = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    if ($PSBoundParameters.Count -gt 0) { $args += " -Ports $($Ports -join ',')" }
    Start-Process -FilePath "powershell.exe" -ArgumentList $args -Verb RunAs
    exit
}

$vmIp = ((wsl -e bash -c "hostname -I") -split '\s+' | Where-Object { $_ } | Select-Object -First 1).Trim()
if (-not $vmIp) { Write-Error "No se pudo obtener la IP de la VM WSL"; exit 1 }
Write-Output "WSL VM IP: $vmIp"

foreach ($port in $Ports) {
    netsh interface portproxy delete v4tov4 listenaddress=127.0.0.1 listenport=$port 2>$null | Out-Null
    netsh interface portproxy add v4tov4 listenaddress=127.0.0.1 listenport=$port connectaddress=$vmIp connectport=$port
    if ($LASTEXITCODE -ne 0) { Write-Output "add $port -> FAILED (puerto ocupado?)" } else { Write-Output "add localhost:$port -> $vmIp`:$port OK" }
}

netsh interface portproxy show all

foreach ($port in $Ports) {
    $code = curl.exe -sS -o NUL -w "%{http_code}" --max-time 8 "http://localhost:$port/" 2>$null
    Write-Output "verify localhost:$port -> $code"
}