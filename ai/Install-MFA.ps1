[CmdletBinding()]
param(
    [string] $MiniforgeRoot = "$HOME\miniforge3",
    [string] $EnvironmentName = 'aligner'
)

$ErrorActionPreference = 'Stop'
$conda = Join-Path $MiniforgeRoot 'condabin\conda.bat'
if (-not (Test-Path -LiteralPath $conda -PathType Leaf)) {
    throw "Miniforge conda not found: $conda"
}

& $conda create -n $EnvironmentName -c conda-forge montreal-forced-aligner -y
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to create the MFA conda environment.'
}

& $conda run -n $EnvironmentName python -m pip install `
    spacy-pkuseg dragonmapper hanziconv
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to install Chinese tokenization support for MFA.'
}

& $conda run -n $EnvironmentName mfa version
