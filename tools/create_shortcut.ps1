param([string]$Destination = [Environment]::GetFolderPath('Desktop'))
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$launcherPath = Join-Path $projectDirectory 'LiveSubtitles.exe'
if (-not (Test-Path -LiteralPath $launcherPath)) { throw "Launcher missing: $launcherPath" }
$shortcutPath = Join-Path $Destination '实时双语字幕.lnk'
$shortcutShell = New-Object -ComObject WScript.Shell
$temporaryShortcut = Join-Path $projectDirectory 'LiveSubtitles.lnk'
$shortcut = $shortcutShell.CreateShortcut($temporaryShortcut)
$shortcut.TargetPath = $launcherPath
$shortcut.WorkingDirectory = $projectDirectory
$shortcut.Description = 'Chrome 实时双语字幕'
$iconPath = Join-Path $projectDirectory 'assets\subtitle-avatar.ico'
$shortcut.IconLocation = "$iconPath,0"
$shortcut.Save()
Copy-Item -LiteralPath $temporaryShortcut -Destination $shortcutPath -Force
Write-Output $shortcutPath
