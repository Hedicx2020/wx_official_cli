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

if (-not $IsWindows) {
    throw "This verifier must run on Windows with PC WeChat opened and logged in."
}

if ($WeChatFilesDir.Trim()) {
    $env:WECHAT_FILES_DIR = $WeChatFilesDir
}

Write-Host "Checking local WeChat cache status..."
uv run wx-official-cli status --save $StatusPath

Write-Host "Verifying cached official-account articles..."
uv run wx-official-cli verify $AccountName --limit $Limit --output-dir $OutputDir --strict --save $ReportPath

Write-Host "Verification report: $ReportPath"
Write-Host "Status report: $StatusPath"
