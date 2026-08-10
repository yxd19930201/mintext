param(
    [Parameter(Mandatory = $true)]
    [string]$InstallDir
)

$ErrorActionPreference = "Stop"
$LogDir = Join-Path $env:LOCALAPPDATA "Mintext"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$LogPath = Join-Path $LogDir "installer-shortcuts.log"
$Target = Join-Path $InstallDir "MintextApp.exe"

"$(Get-Date -Format o) WaitingFor=$Target" | Set-Content -LiteralPath $LogPath -Encoding UTF8
foreach ($attempt in 1..120) {
    if ((Test-Path -LiteralPath $Target) -and ((Get-Item -LiteralPath $Target).Length -gt 0)) {
        break
    }
    Start-Sleep -Seconds 1
}
if (-not (Test-Path -LiteralPath $Target)) {
    "TargetMissing=True" | Add-Content -LiteralPath $LogPath -Encoding UTF8
    exit 2
}

$Shell = New-Object -ComObject WScript.Shell
$ShortcutBase = 'Mintext' + [string][char]0x521B + [string][char]0x4F5C + [string][char]0x5DE5 + [string][char]0x5177
$ShortcutFile = $ShortcutBase + '.lnk'
$DesktopLink = Join-Path ([Environment]::GetFolderPath('Desktop')) $ShortcutFile
$ProgramsLink = Join-Path ([Environment]::GetFolderPath('Programs')) $ShortcutFile
foreach ($LinkPath in @($DesktopLink, $ProgramsLink)) {
    $Shortcut = $Shell.CreateShortcut($LinkPath)
    $Shortcut.TargetPath = $Target
    $Shortcut.WorkingDirectory = $InstallDir
    $Shortcut.IconLocation = (Join-Path $InstallDir 'resources\icon.ico')
    $Shortcut.Save()
}
"ShortcutSuccess=True Desktop=$DesktopLink Programs=$ProgramsLink" | Add-Content -LiteralPath $LogPath -Encoding UTF8
