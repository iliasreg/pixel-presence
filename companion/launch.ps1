# Start the PixelPresence companion if it is not already running.
#
# The Hermes hook runs this at every session start, so it is safe to call often:
# it exits immediately when a companion is already alive. It is also the way to
# start the companion by hand on Windows.

$ErrorActionPreference = 'SilentlyContinue'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$entry = Join-Path $here 'pixel_presence.py'
if (-not (Test-Path $entry)) { Write-Error "pixelpresence: $entry not found"; exit 1 }

$state = if ($env:PIXELPRESENCE_DIR) { $env:PIXELPRESENCE_DIR } else { Join-Path $env:USERPROFILE '.pixelpresence' }
$beat = Join-Path $state 'companion.json'

# The companion refreshes this while it runs, so a fresh one means "leave it".
if (Test-Path $beat) {
    $age = (New-TimeSpan -Start (Get-Item $beat).LastWriteTime -End (Get-Date)).TotalSeconds
    if ($age -lt 30) { Write-Output 'pixelpresence: already running'; exit 0 }
}

# tkinter is the one hard requirement and not every Windows python has it, so
# candidates are tested rather than assumed. pythonw runs without a console.
$candidates = @()
foreach ($name in 'pythonw.exe', 'python.exe') {
    $found = (Get-Command $name -ErrorAction SilentlyContinue).Source
    if ($found) { $candidates += $found }
}
$candidates += (Join-Path $env:USERPROFILE 'miniforge3\pythonw.exe')
$candidates += (Join-Path $env:USERPROFILE 'miniforge3\python.exe')
$candidates += (Join-Path $env:USERPROFILE 'miniconda3\pythonw.exe')
$candidates += (Join-Path $env:USERPROFILE 'miniconda3\python.exe')

foreach ($py in $candidates) {
    if (-not (Test-Path $py)) { continue }
    & $py -c 'import tkinter' 2>$null
    if ($LASTEXITCODE -ne 0) { continue }
    Start-Process -FilePath $py -ArgumentList "`"$entry`""
    Write-Output "pixelpresence: started with $py"
    exit 0
}

Write-Error 'pixelpresence: no Windows python with tkinter found; install one and rerun'
exit 1
