param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$AccountName,

    [int]$Limit = 100,

    [string]$OutputDir = ".\wechat_articles",

    [string]$ReportPath = "verify-wechat-cache-windows.json",

    [string]$StatusPath = "status-wechat-cache-windows.json",

    [string]$WeChatFilesDir = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$CallerRoot = Get-Location

function Resolve-OutputPath {
    param([string]$PathValue)

    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return $PathValue
    }
    return [System.IO.Path]::GetFullPath((Join-Path $CallerRoot $PathValue))
}

function Test-WindowsHost {
    $isWindowsVariable = Get-Variable -Name IsWindows -ErrorAction SilentlyContinue
    if ($null -ne $isWindowsVariable) {
        return [bool]$isWindowsVariable.Value
    }
    return [System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT
}

Push-Location $RepoRoot
try {
    $OutputDirResolved = Resolve-OutputPath $OutputDir
    $ReportPathResolved = Resolve-OutputPath $ReportPath
    $StatusPathResolved = Resolve-OutputPath $StatusPath

    if (-not (Test-WindowsHost)) {
        throw "This verifier must run on Windows with PC WeChat opened and logged in."
    }

    if ($WeChatFilesDir.Trim()) {
        $env:WECHAT_FILES_DIR = $WeChatFilesDir
    }

    Write-Host "Checking local WeChat cache status..."
    uv run wx-official-cli status --save $StatusPathResolved

    Write-Host "Verifying cached official-account articles..."
    uv run wx-official-cli verify $AccountName --limit $Limit --output-dir $OutputDirResolved --strict --save $ReportPathResolved

    Write-Host "Verification report: $ReportPathResolved"
    Write-Host "Status report: $StatusPathResolved"
}
finally {
    Pop-Location
}
