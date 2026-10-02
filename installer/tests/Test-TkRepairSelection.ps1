$ErrorActionPreference='Stop'
$taskScript=Join-Path (Split-Path -Parent $PSScriptRoot) 'src/ConfigurePython.ps1'
$taskTokens=$null;$taskErrors=$null
$taskAst=[Management.Automation.Language.Parser]::ParseFile($taskScript,[ref]$taskTokens,[ref]$taskErrors)
if($taskErrors.Count){throw 'PowerShell script parse failed'}
$taskFunction=$taskAst.Find({param($ast) $ast -is [Management.Automation.Language.FunctionDefinitionAst] -and $ast.Name -eq 'Get-TkRegistration'},$true)
if(-not $taskFunction){throw 'FAIL Tk repair must select an unambiguous registration and scope'}
. ([scriptblock]::Create($taskFunction.Extent.Text))
$script:taskPaths=@{'HKCU'='C:\Other Python';'HKLM'='C:\Selected Python'}
function Get-ChildItem {param($LiteralPath,$ErrorAction)
    if($LiteralPath -like '*WOW6432Node*'){return}
    $hive=if($LiteralPath.StartsWith('HKCU:')){'HKCU'}else{'HKLM'}
    [pscustomobject]@{PSPath=($hive+':\Software\Python\PythonCore\3.12');PSChildName='3.12'}
}
function Get-Item {param($LiteralPath,$ErrorAction)
    $hive=if($LiteralPath.StartsWith('HKCU:')){'HKCU'}else{'HKLM'}
    $item=[pscustomobject]@{Value=$script:taskPaths[$hive]}
    $item | Add-Member -MemberType ScriptMethod -Name GetValue -Value {param($name) $this.Value}
    $item
}
$taskRejected=$false
try{Get-TkRegistration ([pscustomobject]@{base='C:\Selected Python';implementation='cpython'})}catch{$taskRejected=$true}
if(-not $taskRejected){throw 'FAIL ambiguous user/system Python repaired automatically'}
Write-Output 'PASS conflicting user/system registrations stop Tk automatic repair'
$script:taskPaths['HKCU']=''
$taskSelected=Get-TkRegistration ([pscustomobject]@{base='C:\Selected Python';implementation='cpython'})
if($taskSelected.AllUsers -ne 1 -or $taskSelected.Hive -ne 'HKLM:' -or $taskSelected.Path -ne 'C:\Selected Python'){throw 'FAIL selected system Python scope/path not preserved'}
Write-Output 'PASS selected registration preserves system scope and exact target'
$script:taskPaths['HKCU']='C:\Selected Python';$script:taskPaths['HKLM']=''
$taskSelected=Get-TkRegistration ([pscustomobject]@{base='C:\Selected Python';implementation='cpython'})
if($taskSelected.AllUsers -ne 0 -or $taskSelected.Hive -ne 'HKCU:'){throw 'FAIL selected user Python scope not preserved'}
Write-Output 'PASS selected registration preserves user scope'
