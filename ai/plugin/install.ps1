# Install the Praat plugin (B2): copy ai/plugin/praat_ai into
# %APPDATA%\Praat\plugin_praat_ai so that Praat picks it up at start-up.
#
# Usage (from the repository root):
#     powershell -ExecutionPolicy Bypass -File ai\plugin\install.ps1
#     powershell -ExecutionPolicy Bypass -File ai\plugin\install.ps1 -Python D:\Praat-work\venv-ai\Scripts\pythonw.exe
#
# It does two things:
#   1. regenerates praatAiMeasure.praat from ai/praat_ai/measures.tsv;
#   2. copies the plugin folder and writes praatAiChat.praat for this machine.
# To uninstall, delete the %APPDATA%\Praat\plugin_praat_ai folder.
#
# This file is intentionally ASCII-only: Windows PowerShell reads BOM-less
# script files with the ANSI codepage, so non-ASCII text here breaks parsing.
# Chinese documentation lives in ai/plugin/README.zh-CN.md.

param(
    [string]$Python = "",
    [string]$Destination = ""
)

$ErrorActionPreference = 'Stop'

# Resolve to absolute paths first: this script may be invoked with a relative
# name (e.g. "ai\plugin\install.ps1"), and Split-Path -Parent of that gives "".
$pluginDir = Split-Path -Parent (Resolve-Path -LiteralPath $MyInvocation.MyCommand.Path).Path
$projectDir = Split-Path -Parent (Split-Path -Parent $pluginDir)

function Find-Python {
    param([string]$Explicit)
    $candidates = @()
    if ($Explicit) { $candidates += $Explicit }
    if ($env:PRAAT_AI_PYTHON) { $candidates += $env:PRAAT_AI_PYTHON }
    # The layout used on this machine: a venv-ai folder next to the repository
    # (see guide.md section 8.1).
    $parent = Split-Path -Parent $projectDir
    $candidates += (Join-Path $parent 'venv-ai\Scripts\pythonw.exe')
    $candidates += (Join-Path $parent 'venv-ai\Scripts\python.exe')
    $candidates += 'pythonw.exe'
    $candidates += 'python.exe'
    foreach ($candidate in $candidates) {
        if (-not $candidate) { continue }
        if (Test-Path -LiteralPath $candidate) { return (Resolve-Path -LiteralPath $candidate).Path }
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($command) { return $command.Source }
    }
    throw 'Python not found; pass -Python <path to python.exe>.'
}

$pythonExe = Find-Python -Explicit $Python
$runner = Join-Path $projectDir 'ai\tools\build_plugin.py'
$arguments = @($runner, '--install', '--project', $projectDir, '--python', $pythonExe)
if ($Destination) { $arguments += @('--destination', $Destination) }

& $pythonExe @arguments
if ($LASTEXITCODE -ne 0) { throw "Plugin install failed with exit code $LASTEXITCODE" }
