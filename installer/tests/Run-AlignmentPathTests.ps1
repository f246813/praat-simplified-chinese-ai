param([string]$Python=(Get-Command python).Source)
$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$taskOutput=Join-Path $taskRoot 'installer/verification'
$taskCompiler=Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
$taskSources=@('InstallModel.cs','PathValidation.cs','Configuration.cs','InstallEngine.cs','AlignmentPaths.cs','AlignmentPathFields.cs','OutlineButton.cs','FilePathField.cs','PythonSetup.cs','PythonSetupGuide.cs','PathSettings.cs','PathSettingsForm.cs','WizardForm.cs') | ForEach-Object {Join-Path $taskRoot ('installer/src/'+$_)} | Where-Object {Test-Path -LiteralPath $_}
$taskResource='/resource:'+(Join-Path $taskRoot 'installer/src/ConfigurePython.ps1')+',AIPraat.ConfigurePython.ps1'
$taskExe=Join-Path $taskOutput 'AlignmentPathTests.exe'
& $taskCompiler /nologo /platform:x64 /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll /target:exe "/out:$taskExe" $taskResource @taskSources (Join-Path $PSScriptRoot 'AlignmentPathTests.cs')
if($LASTEXITCODE -ne 0){throw 'Alignment path compilation failed'}
& $taskExe $Python
if($LASTEXITCODE -ne 0){throw 'Alignment path tests failed'}
