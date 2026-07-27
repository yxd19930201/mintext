param(
    [Parameter(Mandatory = $true)]
    [string]$InstallDir
)

$ErrorActionPreference = "Stop"

$Target = Join-Path $InstallDir "MintextApp.exe"
if (-not (Test-Path -LiteralPath $Target)) {
    throw "Shortcut target does not exist: $Target"
}

$shell = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath([Environment+SpecialFolder]::CommonDesktopDirectory)
$programs = [Environment]::GetFolderPath([Environment+SpecialFolder]::CommonPrograms)
$menuDirectory = Join-Path $programs "Mintext"

New-Item -ItemType Directory -Path $desktop -Force | Out-Null
New-Item -ItemType Directory -Path $menuDirectory -Force | Out-Null

foreach ($shortcutPath in @(
    (Join-Path $desktop "Mintext.lnk"),
    (Join-Path $menuDirectory "Mintext.lnk")
)) {
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $Target
    $shortcut.WorkingDirectory = Split-Path -Parent $Target
    $shortcut.IconLocation = "$Target,0"
    $shortcut.Description = "Mintext"
    $shortcut.Save()
}
