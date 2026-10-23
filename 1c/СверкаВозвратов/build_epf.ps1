# Builds SverkaVozvratov.epf from the "dump" folder using 1C Designer.
# PowerShell is used (not cmd) so that a Cyrillic user name / password reach 1C intact.
# Run on a COPY of your database; close Designer on that base first. The base is NOT modified.
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot

$v8 = $null
foreach ($root in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
    if (-not $root) { continue }
    $dir = Join-Path $root '1cv8'
    if (-not (Test-Path $dir)) { continue }
    $cand = Get-ChildItem $dir -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'bin\1cv8.exe') } |
        Sort-Object { try { [version]$_.Name } catch { [version]'0.0' } } -Descending | Select-Object -First 1
    if ($cand) { $v8 = Join-Path $cand.FullName 'bin\1cv8.exe'; break }
}
if (-not $v8) { $v8 = (Read-Host '1cv8.exe not found. Enter full path to 1cv8.exe').Trim('"') }
Write-Host "Using: $v8"

Write-Host 'Build on a COPY of your database.'
Write-Host '  1 - file base'
Write-Host '  2 - server base'
$kind = Read-Host 'Enter 1 or 2'
if ($kind -eq '1') {
    $dir = (Read-Host 'Full path to the base folder').Trim().Trim('"')
    $conn = "File=$dir;"
} elseif ($kind -eq '2') {
    $srv = (Read-Host 'Server name').Trim()
    $ref = (Read-Host 'Base name on the server').Trim()
    $conn = "Srvr=$srv;Ref=$ref;"
} else { throw 'Nothing selected.' }

$usr = (Read-Host '1C user name (as in the login dialog), Enter if none').Trim()
$sec = Read-Host '1C password, Enter if none' -AsSecureString
$pwd = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))

$xml = Get-ChildItem (Join-Path $here 'dump') -Filter *.xml | Select-Object -First 1
$out = Join-Path $here 'SverkaVozvratov.epf'
$log = Join-Path $here 'build.log'
if (Test-Path $out) { Remove-Item $out -Force }
if (Test-Path $log) { Remove-Item $log -Force }

$argline = "DESIGNER /IBConnectionString `"$conn`""
if ($usr) { $argline += " /N `"$usr`" /P `"$pwd`"" }
$argline += " /DisableStartupDialogs /LoadExternalDataProcessorOrReportFromFiles `"$($xml.FullName)`" `"$out`" /Out `"$log`""

Write-Host "Connecting: $conn  user: $usr"
Start-Process -FilePath $v8 -ArgumentList $argline -Wait

if (Test-Path $out) {
    Write-Host "DONE: $out" -ForegroundColor Green
} else {
    Write-Host 'FAILED. build.log:' -ForegroundColor Red
    if (Test-Path $log) { Get-Content $log -Encoding UTF8 } else { Write-Host '(no log created)' }
}
