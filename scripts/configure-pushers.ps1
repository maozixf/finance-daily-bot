$ErrorActionPreference = "Stop"

$repository = "maozixf/finance-daily-bot"
$gh = "C:\Program Files\GitHub CLI\gh.exe"

if (-not (Test-Path -LiteralPath $gh)) {
    throw "GitHub CLI not found: $gh"
}

function Read-RequiredText([string]$Prompt) {
    $value = Read-Host $Prompt
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "$Prompt cannot be empty"
    }
    return $value.Trim()
}

function Read-RequiredSecret([string]$Prompt) {
    $secure = Read-Host $Prompt -AsSecureString
    $value = [System.Net.NetworkCredential]::new("", $secure).Password
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "$Prompt cannot be empty"
    }
    return $value
}

Write-Host "Configure finance bot push channels for $repository"
Write-Host "Secret values are sent directly to GitHub and are not written to disk."
Write-Host ""

$wecomWebhook = Read-RequiredSecret "Enterprise WeChat bot webhook (hidden)"
$smtpHost = Read-Host "SMTP host [smtp.qq.com]"
if ([string]::IsNullOrWhiteSpace($smtpHost)) {
    $smtpHost = "smtp.qq.com"
}
$smtpPortText = Read-Host "SMTP port [465]"
$smtpPort = if ([string]::IsNullOrWhiteSpace($smtpPortText)) {
    465
} else {
    [int]$smtpPortText
}
$smtpUser = Read-RequiredText "Sender email address"
$smtpPass = Read-RequiredSecret "SMTP authorization code (hidden)"
$recipient = Read-RequiredText "Recipient email address"

$config = @{
    channels = @(
        @{
            id = "wecom-main"
            name = "WorkWeixinBot"
            format = "markdown"
            max_length = 1000
            config = @{
                key = @{
                    webhook = $wecomWebhook
                }
            }
        },
        @{
            id = "mail-main"
            name = "Mail"
            format = "html"
            max_length = 0
            config = @{
                key = @{
                    host = $smtpHost.Trim()
                    port = $smtpPort
                    secure = $true
                    auth = @{
                        user = $smtpUser
                        pass = $smtpPass
                    }
                }
                options = @{
                    from = $smtpUser
                    to = $recipient
                }
            }
        }
    )
} | ConvertTo-Json -Depth 10 -Compress

try {
    $config | & $gh secret set ALL_PUSH_CONFIG --repo $repository
    if ($LASTEXITCODE -ne 0) {
        throw "gh secret set failed with exit code $LASTEXITCODE"
    }
    Write-Host ""
    Write-Host "ALL_PUSH_CONFIG configured successfully." -ForegroundColor Green
    Write-Host "You can close this window."
} finally {
    $wecomWebhook = $null
    $smtpPass = $null
    $config = $null
}
