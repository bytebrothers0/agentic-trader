# Sequential MT5 tester runs: (setfile, from, to, report)
$runs = @(
    @{ set = "MSNR_Alchemist_dst";  from = "2025.11.01"; to = "2026.11.10"; rep = "MSNR_dst_in_report" },
    @{ set = "MSNR_Alchemist_dst";  from = "2025.05.01"; to = "2025.10.31"; rep = "MSNR_dst_ho_report" },
    @{ set = "MSNR_Alchemist_wu12"; from = "2025.11.01"; to = "2026.11.10"; rep = "MSNR_wu12_in_report" },
    @{ set = "MSNR_Alchemist_wu12"; from = "2025.05.01"; to = "2025.10.31"; rep = "MSNR_wu12_ho_report" }
)
$DataDir = "$env:APPDATA\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075"
foreach ($r in $runs) {
    Get-Process terminal64 -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep 3
    Copy-Item "mql5\tester\$($r.set).set" "$DataDir\MQL5\Profiles\Tester\$($r.set).set" -Force
    $ini = @"
[Tester]
Expert=MSNR_Alchemist
ExpertParameters=$($r.set).set
Symbol=XAUUSDm
Period=M30
Model=4
ExecutionMode=100
Optimization=0
FromDate=$($r.from)
ToDate=$($r.to)
Deposit=10000
Currency=USD
Leverage=1:100
Visual=0
Report=$($r.rep)
ReplaceReport=1
ShutdownTerminal=1
UseLocal=1
UseRemote=0
UseCloud=0
"@
    [System.IO.File]::WriteAllText("$DataDir\MQL5\Files\tester_seq.ini", $ini, [System.Text.Encoding]::ASCII)
    Start-Process -FilePath "C:\Program Files\MetaTrader 5\terminal64.exe" -ArgumentList "/config:`"$DataDir\MQL5\Files\tester_seq.ini`"" -WorkingDirectory "C:\Program Files\MetaTrader 5"
    Write-Host "launched $($r.set) $($r.from)->$($r.to)"
    $deadline = (Get-Date).AddMinutes(12)
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-Process terminal64 -ErrorAction SilentlyContinue)) { break }
        Start-Sleep 20
    }
    python research\parse_mt5_report.py "$DataDir\$($r.rep).htm"
}
Write-Host "ALL RUNS DONE"