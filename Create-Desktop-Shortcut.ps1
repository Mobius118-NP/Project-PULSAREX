$ErrorActionPreference = 'Stop'
try {
    $repoPath = $PSScriptRoot
    $desktopPath = [Environment]::GetFolderPath('Desktop')
    if ([string]::IsNullOrWhiteSpace($desktopPath)) {
        $desktopSetting = Get-ItemPropertyValue -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders' -Name Desktop
        $desktopPath = [Environment]::ExpandEnvironmentVariables($desktopSetting)
    }
    if (-not (Test-Path -LiteralPath $desktopPath -PathType Container)) {
        throw 'Windows Desktop folder is unavailable.'
    }
    $shortcutPath = Join-Path $desktopPath 'PULSAR Mk. II.lnk'
    if (Test-Path -LiteralPath $shortcutPath) {
        throw "A shortcut already exists: $shortcutPath. No changes were made."
    }
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $repoPath
    $shortcut.WorkingDirectory = $repoPath
    $shortcut.Description = 'Open the PULSAR Mk. II Git repository'
    $shortcut.Save()
    Write-Host "Created: $shortcutPath"
    exit 0
} catch {
    Write-Error $_
    exit 1
}
