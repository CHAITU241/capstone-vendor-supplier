$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$headers = @{ "User-Agent" = "VendorLens-local-monitoring" }
$release = Invoke-RestMethod `
    -Uri "https://api.github.com/repos/prometheus/prometheus/releases/latest" `
    -Headers $headers
$asset = $release.assets |
    Where-Object { $_.name -match "windows-amd64\.zip$" } |
    Select-Object -First 1

if ($null -eq $asset) {
    throw "No Windows amd64 Prometheus release asset was found."
}

$archivePath = Join-Path $scriptRoot $asset.name
$extractPath = Join-Path ([IO.Path]::GetTempPath()) ("vendorlens-prometheus-" + [guid]::NewGuid())

Write-Host "Downloading $($asset.name)..."
Invoke-WebRequest -Uri $asset.browser_download_url -Headers $headers -OutFile $archivePath
Expand-Archive -LiteralPath $archivePath -DestinationPath $extractPath -Force

$releaseDirectory = Get-ChildItem -LiteralPath $extractPath -Directory | Select-Object -First 1
if ($null -eq $releaseDirectory) {
    throw "The Prometheus archive did not contain an expected release directory."
}

Copy-Item (Join-Path $releaseDirectory.FullName "prometheus.exe") (Join-Path $scriptRoot "prometheus.exe") -Force
Copy-Item (Join-Path $releaseDirectory.FullName "promtool.exe") (Join-Path $scriptRoot "promtool.exe") -Force
Remove-Item -LiteralPath $extractPath -Recurse -Force
Remove-Item -LiteralPath $archivePath -Force

Write-Host "Prometheus is ready. Start it with .\start-prometheus.ps1"
