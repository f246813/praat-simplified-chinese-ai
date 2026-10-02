param([Parameter(Mandatory=$true)][string]$PythonPath,[switch]$NoPause)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$env:PYTHONIOENCODING='utf-8'
$exitStatus=1
$downloadDirectory=$null

function Test-Tk {
    # Python single quotes survive PowerShell 5.1's legacy native argument passing.
    # Catch Python errors so missing Tk is a repairable result, not PowerShell stderr.
    $code=@'
try:
 import tkinter
 r=tkinter.Tk(); r.withdraw(); r.destroy()
except Exception as error:
 print('Tk unavailable: '+str(error))
 raise SystemExit(1)
'@
    & $PythonPath -I -c $code | Out-Host
    return $LASTEXITCODE -eq 0
}

function Get-TkRegistration($metadata) {
    $registrations=@()
    foreach($registry in @('HKCU:\Software\Python\PythonCore','HKLM:\Software\Python\PythonCore','HKLM:\Software\WOW6432Node\Python\PythonCore')) {
        foreach($key in @(Get-ChildItem -LiteralPath $registry -ErrorAction SilentlyContinue)) {
            $install=Get-Item -LiteralPath (Join-Path $key.PSPath 'InstallPath') -ErrorAction SilentlyContinue
            if($install) {
                $installedPath=([string]$install.GetValue('')).TrimEnd('\')
                if($installedPath) {
                    $registrations+= [pscustomobject]@{Path=$installedPath;Family=$key.PSChildName;Hive=$registry.Substring(0,5);AllUsers=[int]$registry.StartsWith('HKLM:')}
                }
            }
        }
    }
    $selected=@($registrations | Where-Object {$_.Path -eq ([string]$metadata.base).TrimEnd('\')})
    if($selected.Count -ne 1 -or $metadata.implementation -ne 'cpython') {
        throw '此 Python 缺少 Tcl/Tk，且未找到唯一的官方 Python 注册项。请用该环境的安装器补装 Tcl/Tk，或选择包含 Tk 的 Python 环境；NumPy/Pillow 已处理。'
    }
    # python.org's bootstrapper prefers HKCU feature state. Avoid repairing any
    # same-family user/system installation when a second registration exists.
    $family=@($registrations | Where-Object {$_.Family -eq $selected[0].Family})
    if($family.Count -ne 1){throw '检测到同版本 Python 的多个用户/系统安装目录。请用所选 Python 的安装器补装 Tcl/Tk 后重试。'}
    return $selected[0]
}

function Install-Tk($metadata) {
    # Conda owns Tcl/Tk in its prefix; do not modify a different active environment.
    if(Test-Path -LiteralPath (Join-Path $metadata.base 'conda-meta')) {
        $candidates=@((Join-Path $metadata.base 'Scripts/conda.exe'))
        $baseParent=Split-Path -Parent $metadata.base
        if((Split-Path -Leaf $baseParent) -eq 'envs') {$candidates+=(Join-Path (Split-Path -Parent $baseParent) 'Scripts/conda.exe')}
        if($env:CONDA_EXE){$candidates+=$env:CONDA_EXE}
        $conda=$candidates | Where-Object {Test-Path -LiteralPath $_ -PathType Leaf} | Select-Object -First 1
        if(-not $conda){throw '没有找到 Conda 管理器。请通过该环境的 Conda 安装 tk 组件后重试。'}
        & $conda install --yes --prefix $metadata.base tk
        if($LASTEXITCODE -ne 0){throw 'Conda 安装 Tk 失败，请查看上方信息后重试。'}
        return
    }

    # Only repair a registered python.org runtime at this exact base path.
    # A venv shares Tk with its base runtime, rather than a pip package named tk.
    $registration=Get-TkRegistration $metadata
    $version=[string]$metadata.version
    $architecture=[string]$metadata.machine
    $label=switch($architecture){'win-amd64'{'64-bit'};'win-arm64'{'ARM64'};'win32'{'32-bit'};default{throw '不支持自动修复此 Python 架构。'}}
    $bundle=$null
    $uninstallRoots=@($registration.Hive+'\Software\Microsoft\Windows\CurrentVersion\Uninstall')
    if($registration.AllUsers){$uninstallRoots+= 'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'}
    foreach($registry in $uninstallRoots) {
        foreach($key in @(Get-ChildItem -LiteralPath $registry -ErrorAction SilentlyContinue)) {
            $entry=Get-ItemProperty -LiteralPath $key.PSPath
            if($entry.DisplayName -eq "Python $version ($label)" -and $entry.ModifyPath -match '^"([^"]+\.exe)"') {
                if(Test-Path -LiteralPath $matches[1]) {$bundle=$matches[1]}
            }
        }
    }
    if(-not $bundle) {
        $suffix=switch($architecture){'win-amd64'{'-amd64'};'win-arm64'{'-arm64'};'win32'{''}}
        $script:downloadDirectory=Join-Path ([IO.Path]::GetTempPath()) ('AIPraat-tk-'+[guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $script:downloadDirectory | Out-Null
        $bundle=Join-Path $script:downloadDirectory "python-$version$suffix.exe"
        [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
        Write-Host "正在获取 Python $version 的官方安装组件…"
        Invoke-WebRequest -UseBasicParsing -Uri "https://www.python.org/ftp/python/$version/python-$version$suffix.exe" -OutFile $bundle
    }
    $signature=Get-AuthenticodeSignature -LiteralPath $bundle
    if($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') {throw 'Python 安装器签名验证失败，已停止修复。'}
    Write-Host '正在补装 Tcl/Tk 组件；系统级 Python 可能显示管理员权限提示…'
    $targetArguments=@(('InstallAllUsers='+$registration.AllUsers),('TargetDir="'+$registration.Path+'"'))
    $process=Start-Process -FilePath $bundle -ArgumentList (@('/modify','/passive','/norestart','Include_tcltk=1','Include_pip=1')+$targetArguments) -WindowStyle Hidden -PassThru -Wait
    if($process.ExitCode -notin @(0,3010)){throw "Python Tcl/Tk 组件安装失败，退出码：$($process.ExitCode)。"}
    if(-not (Test-Tk)) {
        $process=Start-Process -FilePath $bundle -ArgumentList (@('/repair','/passive','/norestart')+$targetArguments) -WindowStyle Hidden -PassThru -Wait
        if($process.ExitCode -notin @(0,3010)){throw "Python 修复失败，退出码：$($process.ExitCode)。"}
    }
}

try {
    if(-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)){throw '所选 python.exe 不存在，请返回重新选择。'}
    Write-Host "配置所选 Python：$PythonPath"
    $metadataJson=& $PythonPath -I -c 'import sys,json,platform,sysconfig; print(json.dumps(dict(base=sys.base_prefix,version=platform.python_version(),machine=sysconfig.get_platform(),implementation=sys.implementation.name,version_info=list(sys.version_info[:2]))))'
    if($LASTEXITCODE -ne 0){throw '无法运行所选 Python。'}
    $metadata=$metadataJson | ConvertFrom-Json
    if($metadata.version_info[0] -ne 3 -or $metadata.version_info[1] -lt 10){throw '需要 Python 3.10 或更高版本。'}
    & $PythonPath -I -c 'import importlib.util; raise SystemExit(0 if importlib.util.find_spec(''pip'') else 1)'
    if($LASTEXITCODE -ne 0) {
        Write-Host '正在配置 pip…'
        & $PythonPath -I -m ensurepip --upgrade
        if($LASTEXITCODE -ne 0){throw 'pip 配置失败，请修复所选 Python 的 pip 组件后重试。'}
    }
    Write-Host '正在安装 Pillow >= 10、NumPy >= 2…'
    & $PythonPath -I -m pip install --disable-pip-version-check --only-binary=:all: 'Pillow>=10' 'numpy>=2'
    if($LASTEXITCODE -ne 0){throw '依赖安装失败，请检查网络或该 Python 目录的写入权限，查看上方信息后重试。'}
    if(-not (Test-Tk)){Install-Tk $metadata}
    Write-Host '正在复检 Tk、Pillow、NumPy…'
    & $PythonPath -I -c 'import tkinter,numpy,PIL; assert int(numpy.__version__.split(''.'')[0])>=2; assert int(PIL.__version__.split(''.'')[0])>=10; r=tkinter.Tk(); r.withdraw(); r.destroy(); print(''Tk / Pillow / NumPy OK'')'
    if($LASTEXITCODE -ne 0){throw '复检未通过，请查看上方信息，补齐 Tcl/Tk 或其他依赖后重试。'}
    Write-Host '运行环境配置完成。返回配置界面后将自动检查。' -ForegroundColor Green
    $exitStatus=0
} catch {
    Write-Host ("配置未完成："+$_.Exception.Message) -ForegroundColor Red
} finally {
    # Remove only the specific installer downloaded by this invocation.
    if($downloadDirectory) {
        Get-ChildItem -LiteralPath $downloadDirectory -File | Remove-Item
        Remove-Item -LiteralPath $downloadDirectory
    }
}
if(-not $NoPause){[void](Read-Host '按 Enter 关闭 PowerShell 并返回配置界面')}
exit $exitStatus
