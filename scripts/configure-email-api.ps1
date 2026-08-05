$ErrorActionPreference = "Stop"

# Keep the script ASCII-only so Windows PowerShell 5.1 cannot decode the
# default Chinese sender name with the active ANSI code page.
$defaultSenderName = -join @(
    [char]0x8D22,
    [char]0x7ECF,
    [char]0x65E5,
    [char]0x62A5
)

$repository = "maozixf/finance-daily-bot"
$gh = "C:\Program Files\GitHub CLI\gh.exe"
if (-not (Test-Path -LiteralPath $gh)) {
    throw "GitHub CLI not found: $gh"
}

function Read-RequiredText([string]$Prompt) {
    $value = Read-Host $Prompt
    if ([string]::IsNullOrWhiteSpace($value)) { throw "$Prompt cannot be empty" }
    return $value.Trim()
}

function Read-RequiredSecret([string]$Prompt) {
    $secure = Read-Host $Prompt -AsSecureString
    $value = [System.Net.NetworkCredential]::new("", $secure).Password
    if ([string]::IsNullOrWhiteSpace($value)) { throw "$Prompt cannot be empty" }
    return $value
}

function ConvertTo-AsciiJson([string]$Json) {
    return [System.Text.RegularExpressions.Regex]::Replace(
        $Json,
        '[^\u0000-\u007F]',
        {
            param($match)
            return '\u{0:x4}' -f [int][char]$match.Value[0]
        }
    )
}

Write-Host "Configure email API for $repository"
Write-Host "Provider: Resend or Brevo"
$provider = Read-RequiredText "Provider [Resend/Brevo]"
$provider = $provider.ToLowerInvariant()
if ($provider -eq "sendinblue") { $provider = "brevo" }
if ($provider -notin @("resend", "brevo")) {
    throw "Provider must be Resend or Brevo"
}

$apiKey = (Read-RequiredSecret "API key (hidden)").Trim()
if ($provider -eq "brevo" -and $apiKey -notmatch '^xkeysib-') {
    throw "Invalid Brevo API key. Use a standard API key beginning with xkeysib-, not an SMTP key or MCP key."
}
$fromEmail = Read-RequiredText "Verified sender email"
$fromName = Read-Host "Sender display name [$defaultSenderName]"
if ([string]::IsNullOrWhiteSpace($fromName)) { $fromName = $defaultSenderName }
$recipients = Read-RequiredText "Recipient email address(es), comma-separated"

$config = @{
    channels = @(
        @{
            id = "mail-api-main"
            name = if ($provider -eq "resend") { "Resend" } else { "Brevo" }
            provider = $provider
            format = "html"
            max_length = 0
            config = @{
                api_key = $apiKey
                from_email = $fromEmail
                from_name = $fromName.Trim()
                to = $recipients -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ }
            }
        }
    )
} | ConvertTo-Json -Depth 10 -Compress
$config = ConvertTo-AsciiJson $config

try {
    Write-Host "Sender display name: $($fromName.Trim())"
    $config | & $gh secret set ALL_PUSH_CONFIG --repo $repository
    if ($LASTEXITCODE -ne 0) { throw "gh secret set failed with exit code $LASTEXITCODE" }
    Write-Host "ALL_PUSH_CONFIG updated successfully." -ForegroundColor Green
} finally {
    $apiKey = $null
    $config = $null
}
