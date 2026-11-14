$term = "C:\Program Files\MetaTrader 5\terminal64.exe"
$base = "$env:APPDATA\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075"

$runs = @(
    @{ set = "MSNR_Alchemist_mgmt.set"; from = "2025.11.01"; to = "2026.11.10"; rep = "MSNR_mgmt_is_v25" },
    @{ set = "MSNR_Alchemist_mgmt.set"; from = "2025.05.01"; to = "2025.10.31"; rep = "MSNR_mgmt_ho_v25" }
)

foreach ($r in $runs) {
    Get-Process terminal64 -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep 3
    $f = "$base\MQL5\Files\tester_mgmt_v25.ini"
    $ini = @"
[Tester]
Expert=MSNR_Alchemist
ExpertParameters=$($r.set)
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
    [System.IO.File]::WriteAllText($f, $ini, [System.Text.Encoding]::ASCII)
    Write-Host "run $($r.rep) ..."
    Start-Process -FilePath $term -ArgumentList "/config:`"$f`"" -WorkingDirectory "C:\Program Files\MetaTrader 5"
    $deadline = (Get-Date).AddMinutes(20)
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-Process terminal64 -ErrorAction SilentlyContinue)) { break }
        Start-Sleep 15
    }
}
Write-Host "batch done"
