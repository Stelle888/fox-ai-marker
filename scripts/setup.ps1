#Requires -Version 5.1
<#
.SYNOPSIS
    Download the KataGo engine and a neural network weight into this project.

.DESCRIPTION
    Puts katago.exe + DLLs into .\katago\ and the .bin.gz weight into .\weights\.
    The program then finds them automatically.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

.EXAMPLE
    # a smaller/faster weight instead of the latest tf3
    powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 `
        -WeightUrl https://github.com/lightvector/KataGo/releases/download/v1.12.4/b18c384nbt-uec.bin.gz
#>
param(
    [string]$EngineUrl = "https://github.com/lightvector/KataGo/releases/download/v1.16.5/katago-v1.16.5-opencl-windows-x64.zip",
    [string]$WeightUrl = "https://github.com/lightvector/KataGo/releases/download/v1.12.4/b18c384nbt-uec.bin.gz"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$root = Split-Path -Parent $PSScriptRoot
if (-not $root) { $root = (Get-Location).Path }
$katagoDir = Join-Path $root "katago"
$weightsDir = Join-Path $root "weights"
New-Item -ItemType Directory -Force -Path $katagoDir, $weightsDir | Out-Null

function Get-File($url, $dest) {
    $name = Split-Path $url -Leaf
    if (Test-Path $dest) {
        Write-Host "  already there: $name"
        return
    }
    Write-Host "  downloading $name ..."
    $tmp = "$dest.part"
    Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing -TimeoutSec 1800
    Move-Item -LiteralPath $tmp -Destination $dest -Force
    $mb = [math]::Round((Get-Item $dest).Length / 1MB, 1)
    Write-Host "  done: $name ($mb MB)"
}

# ---- 1. engine ----
Write-Host "[1/2] KataGo engine"
if (Test-Path (Join-Path $katagoDir "katago.exe")) {
    Write-Host "  already there: katago.exe"
} else {
    $zip = Join-Path $env:TEMP (Split-Path $EngineUrl -Leaf)
    Get-File $EngineUrl $zip
    $extract = Join-Path $env:TEMP "katago_extract"
    if (Test-Path $extract) { Remove-Item -Recurse -Force $extract }
    Expand-Archive -LiteralPath $zip -DestinationPath $extract -Force
    # the zip has a single top folder; flatten it
    Get-ChildItem $extract -Recurse -File |
        Where-Object { $_.Extension -in @(".exe", ".dll") } |
        ForEach-Object { Copy-Item $_.FullName -Destination $katagoDir -Force }
    Remove-Item -Recurse -Force $extract
    Write-Host "  engine ready: $(Join-Path $katagoDir 'katago.exe')"
}

# ---- 2. weight ----
Write-Host "[2/2] neural network weight"
$wName = Split-Path $WeightUrl -Leaf
Get-File $WeightUrl (Join-Path $weightsDir $wName)

# ---- 3. sanity check ----
Write-Host ""
$exe = Join-Path $katagoDir "katago.exe"
$ver = & $exe version 2>&1 | Select-Object -First 1
Write-Host "engine : $ver"
Write-Host "weight : $wName"
Write-Host ""
Write-Host "Done. Next steps:"
Write-Host "  1. open the Fox Weiqi client and enter a game (board visible)"
Write-Host "  2. python run.py     (or double-click 启动.bat)"
Write-Host "  3. if points land in the wrong place: python tools\calibrate.py"
