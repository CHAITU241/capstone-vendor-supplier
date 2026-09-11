param(
    [string]$PrometheusExe = (Join-Path $PSScriptRoot "prometheus.exe")
)

$prometheusPath = (Resolve-Path $PrometheusExe -ErrorAction Stop).Path
$configPath = Join-Path $PSScriptRoot "prometheus.yml"
$dataPath = Join-Path $PSScriptRoot "data"

New-Item -ItemType Directory -Force -Path $dataPath | Out-Null

& $prometheusPath `
    "--config.file=$configPath" `
    "--storage.tsdb.path=$dataPath" `
    "--web.listen-address=127.0.0.1:9090"
