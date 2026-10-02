param([string]$Python = (Get-Command python).Source)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$output = Join-Path $projectRoot 'installer/verification'
New-Item -ItemType Directory -Path $output -Force | Out-Null
$compiler = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
$sources = @('InstallModel.cs','PathValidation.cs','AlignmentPaths.cs','Configuration.cs','OutlineButton.cs','FilePathField.cs','AlignmentPathFields.cs','PythonSetup.cs','PythonSetupGuide.cs','PathSettings.cs','PathSettingsForm.cs') | ForEach-Object { Join-Path $projectRoot ('installer/src/' + $_) } | Where-Object { Test-Path -LiteralPath $_ }
$test = Join-Path $output 'PathSettingsTests.exe'
& $compiler /nologo /optimize+ /platform:x64 /target:exe /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll "/out:$test" @sources (Join-Path $PSScriptRoot 'PathSettingsTests.cs')
if ($LASTEXITCODE -ne 0) { throw 'Path test compilation failed.' }
& $test $Python
if ($LASTEXITCODE -ne 0) { throw 'Path configuration tests failed.' }
