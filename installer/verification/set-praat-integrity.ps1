param([string[]]$Executable)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $Executable) {
    $Executable = @('Praat.exe','Praat-model-settings.exe','Praat-menu-fixed.exe') | ForEach-Object { Join-Path $projectRoot $_ }
}
# New/copy-created executables inherit this workspace's Low label. Restore the
# per-file Medium label after the final copy; leave folder and IPC ACLs intact.
foreach ($path in $Executable) {
    $resolved = (Get-Item -LiteralPath $path).FullName
    & icacls $resolved /setintegritylevel Medium
    if ($LASTEXITCODE -ne 0) { throw "Cannot restore executable integrity: $resolved" }
}
