param([string]$ProjectDirectory = "")
$ErrorActionPreference = 'Stop'
if (-not $ProjectDirectory) { $ProjectDirectory = Split-Path -Parent $PSScriptRoot }
$projectRoot = (Resolve-Path -LiteralPath $ProjectDirectory).Path
$buildRoot = Join-Path $projectRoot 'installer\build'
New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'The Windows .NET Framework C# compiler is missing.' }
$sourceRoot = Join-Path $projectRoot 'installer\src'
$references = @('System.Windows.Forms.dll','System.Drawing.dll','System.Web.Extensions.dll','System.IO.Compression.dll','System.IO.Compression.FileSystem.dll')
$common = @('InstallModel.cs','PathValidation.cs','AlignmentPaths.cs','Configuration.cs','InstallEngine.cs') | ForEach-Object { Join-Path $sourceRoot $_ }
$options = @('/nologo','/optimize+','/platform:x64')
$options += $references | ForEach-Object { '/reference:' + $_ }
$options += '/win32manifest:' + (Join-Path $projectRoot 'installer\app.manifest')
$options += '/win32icon:' + (Join-Path $projectRoot 'favicon.ico')
$launcher = Join-Path $buildRoot 'AIPraat.exe'
& $compiler @options '/target:winexe' "/out:$launcher" @common (Join-Path $sourceRoot 'Launcher.cs')
if ($LASTEXITCODE -ne 0) { throw "Launcher compilation failed: $LASTEXITCODE" }
$setupResource = '/resource:' + (Join-Path $sourceRoot 'ConfigurePython.ps1') + ',AIPraat.ConfigurePython.ps1'
$pathSources = @('OutlineButton.cs','FilePathField.cs','AlignmentPathFields.cs','PythonSetup.cs','PythonSetupGuide.cs','PathSettings.cs','PathSettingsForm.cs','PathSettingsProgram.cs') | ForEach-Object { Join-Path $sourceRoot $_ }
$pathDialog = Join-Path $projectRoot 'AIPraat-paths.exe'
& $compiler @options '/target:winexe' "/out:$pathDialog" $setupResource @common @pathSources
if ($LASTEXITCODE -ne 0) { throw "Path dialog compilation failed: $LASTEXITCODE" }

$files = [ordered]@{}
$files['Praat.exe'] = Join-Path $projectRoot 'Praat.exe'
$files['AIPraat.exe'] = $launcher
$files['AIPraat-paths.exe'] = $pathDialog
$files['LICENSE'] = Join-Path $projectRoot 'LICENSE'
$files['CREDITS.zh-CN.md'] = Join-Path $projectRoot 'CREDITS.zh-CN.md'
$files['AIPraat-使用说明.md'] = Join-Path $projectRoot 'installer\README.zh-CN.md'
$aiRoot = Join-Path $projectRoot 'ai'
Get-ChildItem -LiteralPath $aiRoot -File | Where-Object {
    $_.Extension -eq '.py' -or $_.Name -match '^requirements.*\.txt$' -or
    $_.Name -match '^(Download.*|Install.*)\.ps1$' -or $_.Name -eq 'README.zh-CN.md' -or $_.Name -eq 'request.example.json'
} | ForEach-Object { $files['ai/' + $_.Name] = $_.FullName }
foreach ($relative in @('praat_ai','plugin','tools')) {
    $base = Join-Path $aiRoot $relative
    Get-ChildItem -LiteralPath $base -Recurse -File | Where-Object {
        $_.Extension -in @('.py','.tsv','.praat','.in','.ps1','.md') -and $_.FullName -notmatch '\\__pycache__\\'
    } | ForEach-Object {
        $name = $_.FullName.Substring($projectRoot.Length+1).Replace('\','/')
        $files[$name] = $_.FullName
    }
}
$template = '{"qwen":{"base_url":"http://127.0.0.1:8000/v1","model":"local-model","api_key":"EMPTY","enable_thinking":false,"limit_tokens":true,"max_context_tokens":32768,"plan_max_tokens":4096},"api":{"enabled":false,"locked":false,"limit_tokens":false,"api_key":""},"server":{"llama_server":"","model_path":"","mmproj_path":"","host":"127.0.0.1","port":8000,"n_gpu_layers":-1,"threads":8,"parallel":1,"auto_start":false,"presets":[],"active_preset":"","mmproj_by_model":{}},"alignment":{"backend":"auto","mfa":{"enabled":false},"wav2vec2":{"enabled":false}}}'
$templateFile = Join-Path $buildRoot 'ai_config.example.json'
[IO.File]::WriteAllText($templateFile,$template,[Text.UTF8Encoding]::new($false))
$files['ai/ai_config.example.json'] = $templateFile
foreach ($name in $files.Keys) {
    if ($name -match '(^|/)(ai_config\.json|runtime|logs|tests|__pycache__)(/|$)' -or $name -match '\.pyc$') {
        throw "Forbidden development file in payload: $name"
    }
}
$hashes = [ordered]@{}
foreach ($name in $files.Keys) { $hashes[$name] = (Get-FileHash -LiteralPath $files[$name] -Algorithm SHA256).Hash.ToLowerInvariant() }
$manifest = Join-Path $buildRoot 'payload-manifest.json'
[IO.File]::WriteAllText($manifest,($hashes | ConvertTo-Json -Depth 5),[Text.UTF8Encoding]::new($false))
$files['payload-manifest.json'] = $manifest
Add-Type -AssemblyName System.IO.Compression
$zipPath = Join-Path $buildRoot 'payload.zip'
$stream = [IO.FileStream]::new($zipPath,[IO.FileMode]::Create,[IO.FileAccess]::Write)
try {
    $archive = [IO.Compression.ZipArchive]::new($stream,[IO.Compression.ZipArchiveMode]::Create,$true)
    try {
        foreach ($name in $files.Keys) {
            $entry = $archive.CreateEntry($name,[IO.Compression.CompressionLevel]::Optimal)
            $input = [IO.File]::OpenRead($files[$name])
            $output = $entry.Open()
            try { $input.CopyTo($output) } finally { $input.Dispose(); $output.Dispose() }
        }
    } finally { $archive.Dispose() }
} finally { $stream.Dispose() }
$installer = Join-Path $projectRoot 'AIPraat-install.exe'
$wizard = @('OutlineButton.cs','FilePathField.cs','AlignmentPathFields.cs','PythonSetup.cs','PythonSetupGuide.cs','WizardForm.cs','Program.cs') | ForEach-Object { Join-Path $sourceRoot $_ }
& $compiler @options '/target:winexe' "/out:$installer" "/resource:$zipPath,AIPraat.Payload.zip" $setupResource @common @wizard
if ($LASTEXITCODE -ne 0) { throw "Installer compilation failed: $LASTEXITCODE" }
$report = [ordered]@{
    installer = $installer
    size = (Get-Item -LiteralPath $installer).Length
    sha256 = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash
    praat_sha256 = $hashes['Praat.exe']
    payload_files = $files.Count
    built_at = [DateTime]::UtcNow.ToString('o')
}
[IO.File]::WriteAllText((Join-Path $buildRoot 'build-report.json'),($report | ConvertTo-Json),[Text.UTF8Encoding]::new($false))
$report | ConvertTo-Json
