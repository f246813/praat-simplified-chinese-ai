param([string]$Python=(Get-Command python).Source)
$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$taskOutput=Join-Path $taskRoot 'installer/verification'
$taskCompiler=Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
$taskSources=@('InstallModel.cs','PathValidation.cs','AlignmentPaths.cs','Configuration.cs','InstallEngine.cs','OutlineButton.cs','FilePathField.cs','AlignmentPathFields.cs','PythonSetup.cs','PythonSetupGuide.cs','PathSettings.cs','PathSettingsForm.cs','WizardForm.cs') | ForEach-Object {Join-Path $taskRoot ('installer/src/'+$_)} | Where-Object {Test-Path -LiteralPath $_}
$taskOptions=@('/nologo','/platform:x64','/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll','/reference:System.Web.Extensions.dll','/reference:System.IO.Compression.dll','/reference:System.IO.Compression.FileSystem.dll')
$taskScript=Join-Path $taskRoot 'installer/src/ConfigurePython.ps1'
if(Test-Path -LiteralPath $taskScript){$taskOptions+="/resource:$taskScript,AIPraat.ConfigurePython.ps1"}
$taskExe=Join-Path $taskOutput 'PythonSetupTests.exe'
& $taskCompiler @taskOptions /target:exe "/out:$taskExe" @taskSources (Join-Path $PSScriptRoot 'PythonSetupTests.cs')
if($LASTEXITCODE -ne 0){throw 'Compile failed'}
$taskMissing=Join-Path $taskOutput 'python_setup_probe_missing'
if(-not (Test-Path -LiteralPath (Join-Path $taskMissing 'Scripts/python.exe'))){& $Python -m venv --without-pip $taskMissing;if($LASTEXITCODE -ne 0){throw 'Venv creation failed'}}
& $taskExe $Python (Join-Path $taskMissing 'Scripts/python.exe')
if($LASTEXITCODE -ne 0){throw 'Python setup tests failed'}
