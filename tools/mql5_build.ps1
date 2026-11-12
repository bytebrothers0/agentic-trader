# mql5_build.ps1 — compile + deploy + backtest loop for the MSNR Alchemist EA.
# Usage:
#   .\tools\mql5_build.ps1              # compile + deploy
#   .\tools\mql5_build.ps1 -RunTest     # compile + deploy + run strategy tester
#
# Tester settings (per operator request): Model=4 (every tick based on real
# ticks), ExecutionMode=100 (fixed 100 ms order-execution delay).

param(
    [switch]$RunTest,
    [string]$Symbol = "XAUUSDm",
    [string]$Period = "M30",
    [string]$FromDate = "2025.11.01",
    [string]$ToDate = "2026.11.10",
    [double]$Deposit = 10000,
    [string]$Leverage = "1:100",
    [string]$Report = "MSNR_Alchemist_report",
    [string]$SetFile = ""
)

$ErrorActionPreference = "Stop"

# --- paths
$TerminalExe  = "C:\Program Files\MetaTrader 5\terminal64.exe"
$MetaEditor   = "C:\Program Files\MetaTrader 5\metaeditor64.exe"
$DataDir      = "$env:APPDATA\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075"
$RepoEA       = "$PSScriptRoot\..\mql5\Experts\MSNR_Alchemist.mq5"
$DeployEA     = "$DataDir\MQL5\Experts\MSNR_Alchemist.mq5"
$IniPath      = "$DataDir\MQL5\Files\tester_msnr.ini"
$ProfilesDir  = "$DataDir\MQL5\Profiles\Tester"

Write-Host "=== [1/4] Deploy EA source ==="
Copy-Item $RepoEA $DeployEA -Force
Write-Host "  $RepoEA -> $DeployEA"

Write-Host "=== [2/4] Compile (MetaEditor /compile) ==="
& $MetaEditor /compile:"$DeployEA" /log:"$DataDir\MQL5\compile_msnr.log"
Start-Sleep -Seconds 2
$compileLog = Get-Content "$DataDir\MQL5\compile_msnr.log" -ErrorAction SilentlyContinue
if ($compileLog) { $compileLog | Select-Object -Last 8 | ForEach-Object { Write-Host "  $_" } }
if (-not (Test-Path "$DataDir\MQL5\Experts\MSNR_Alchemist.ex5")) {
    throw "COMPILATION FAILED - no .ex5 produced. See $DataDir\MQL5\compile_msnr.log"
}
Write-Host "  Compiled OK: MSNR_Alchemist.ex5"

if (-not $RunTest) { exit 0 }

Write-Host "=== [3/4] Build tester config ==="
# .set file must live in MQL5\Profiles\Tester
if ($SetFile) {
    $srcSet = if (Test-Path $SetFile) { $SetFile } else { "$PSScriptRoot\..\mql5\tester\$SetFile" }
    Copy-Item $srcSet "$ProfilesDir\MSNR_Alchemist.set" -Force
    Write-Host "  Set file -> $ProfilesDir\MSNR_Alchemist.set"
}

# ASCII, no BOM (a BOM silently breaks the parser)
$ini = @"
[Tester]
Expert=MSNR_Alchemist
Symbol=$Symbol
Period=$Period
Model=4
;0 "Every tick" 1 "1 min OHLC" 2 "Open prices" 3 "Math" 4 "Real ticks"
ExecutionMode=100
;100 = fixed 100 ms order execution delay
Optimization=0
FromDate=$FromDate
ToDate=$ToDate
Deposit=$Deposit
Currency=USD
Leverage=$Leverage
Visual=0
Report=$Report
ReplaceReport=1
ShutdownTerminal=1
UseLocal=1
UseRemote=0
UseCloud=0
"@
[System.IO.File]::WriteAllText($IniPath, $ini, [System.Text.Encoding]::ASCII)
Write-Host "  $IniPath"

Write-Host "=== [4/4] Run strategy tester (headless) ==="
Start-Process -FilePath $TerminalExe -ArgumentList "/config:`"$IniPath`"" -WorkingDirectory "C:\Program Files\MetaTrader 5"
Write-Host "  Terminal launched with config. Tester runs headless and shuts down when done."
Write-Host "  Report lands in: $DataDir\$Report.html (+ .png charts) or MQL5\Files\"
