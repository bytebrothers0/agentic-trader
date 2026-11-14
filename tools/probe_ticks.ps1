# Probe real-tick availability per year (2018-2023) for XAUUSDm.
# For each year: 2-day mid-July window, Model=4; verdict read from the tester log
# ("generating based on real ticks" vs M1 generation).
$years = 2018..2023
$DataDir = "$env:APPDATA\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075"
$testerLog = "$DataDir\Tester\logs\20261114.log"

foreach ($y in $years) {
    Get-Process terminal64 -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep 3
    $ini = @"
[Tester]
Expert=MSNR_Alchemist
ExpertParameters=MSNR_Alchemist.set
Symbol=XAUUSDm
Period=M30
Model=4
ExecutionMode=100
Optimization=0
FromDate=$y.07.15
ToDate=$y.07.17
Deposit=10000
Currency=USD
Leverage=1:100
Visual=0
Report=MSNR_tickprobe_$y
ReplaceReport=1
ShutdownTerminal=1
UseLocal=1
UseRemote=0
UseCloud=0
"@
    [System.IO.File]::WriteAllText("$DataDir\MQL5\Files\tester_probe.ini", $ini, [System.Text.Encoding]::ASCII)
    Start-Process -FilePath "C:\Program Files\MetaTrader 5\terminal64.exe" -ArgumentList "/config:`"$DataDir\MQL5\Files\tester_probe.ini`"" -WorkingDirectory "C:\Program Files\MetaTrader 5"
    Write-Host "probing $y ..."
    $deadline = (Get-Date).AddMinutes(12)
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-Process terminal64 -ErrorAction SilentlyContinue)) { break }
        Start-Sleep 15
    }
}

Start-Sleep 5
Write-Host "=== verdicts ==="
python -c "
import os, re
p = os.path.join(os.environ['APPDATA'], 'MetaQuotes', 'Terminal', 'D0E8209F77C8CF37AD8BF550E51FF075', 'Tester', 'logs', '20261114.log')
if not os.path.exists(p):
    import glob
    cand = glob.glob(os.path.join(os.environ['APPDATA'], 'MetaQuotes', 'Terminal', 'D0E8209F77C8CF37AD8BF550E51FF075', 'Tester', 'logs', '*.log'))
    p = max(cand, key=os.path.getmtime)
raw = open(p, 'rb').read()
text = raw.decode('utf-16', errors='ignore')
for ln in text.splitlines():
    if 'generating' in ln.lower() or 'real ticks' in ln.lower() or 'ticks data begins' in ln.lower():
        print(ln[:150])
"