param([ValidateSet('install','build','test','test:ui','dev','preview','check')][string]$Action = 'check')
$ErrorActionPreference = 'Stop'
$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
$node = if ($nodeCommand) { $nodeCommand.Source } else { 'C:\Users\f2468\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' }
if (!(Test-Path $node)) { throw '请安装 Node.js 22.12+，或提供 node 到 PATH。' }
$env:PATH = (Split-Path $node) + ';' + $env:PATH
Push-Location $PSScriptRoot
try {
  $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
  if ($npmCommand) { $npm = $npmCommand.Source; $npmArgs = @() }
  else {
    $scratch = if ($env:PI_SCRATCH_DIR) { $env:PI_SCRATCH_DIR } else { [IO.Path]::GetTempPath() }
    $tools = Join-Path $scratch 'praat-frontend-npm-12.2.0'
    $cli = Join-Path $tools 'package\bin\npm-cli.js'
    if (!(Test-Path $cli)) {
      python -c "import os,sys,urllib.request,tarfile; p=sys.argv[1]; os.makedirs(p,exist_ok=True); f=os.path.join(p,'npm.tgz'); urllib.request.urlretrieve('https://registry.npmjs.org/npm/-/npm-12.2.0.tgz',f); tarfile.open(f).extractall(p,filter='data')" $tools
      if ($LASTEXITCODE -ne 0) { throw 'npm 工具下载失败。可手动安装 npm 12.2.0；不需要 Pi 内核。' }
    }
    $npm = $node; $npmArgs = @($cli)
  }
  if ($Action -eq 'install') { & $npm @npmArgs ci --no-audit --no-fund }
  elseif ($Action -eq 'check') {
    & $npm @npmArgs run test
    if ($LASTEXITCODE -ne 0) { throw '测试失败' }
    & $npm @npmArgs run build
  } else { & $npm @npmArgs run $Action }
  if ($LASTEXITCODE -ne 0) { throw "前端命令失败：$Action" }
} finally { Pop-Location }
