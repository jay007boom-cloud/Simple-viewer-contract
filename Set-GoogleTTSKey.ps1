[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

Write-Host 'Google AI Studio (Gemini) API key setup for speech and interpretation'
Write-Host 'The key is saved encrypted for this Windows user and is never written to the viewer HTML.'
$secureKey = Read-Host 'Enter the Gemini API key (input is hidden)' -AsSecureString
if ($secureKey.Length -lt 10) {
    throw 'The API key input is empty or too short. No key was saved.'
}

$storeDirectory = Join-Path $env:LOCALAPPDATA 'Parsing for Easy Reading'
New-Item -ItemType Directory -Path $storeDirectory -Force | Out-Null
$storePath = Join-Path $storeDirectory 'google-tts-key.xml'
$credential = [System.Management.Automation.PSCredential]::new('GoogleAIStudio', $secureKey)
$credential | Export-Clixml -LiteralPath $storePath -Force

$pidPath = Join-Path $storeDirectory 'google-tts-service.pid'
if (Test-Path -LiteralPath $pidPath -PathType Leaf) {
    $servicePid = 0
    $pidText = (Get-Content -LiteralPath $pidPath -Raw).Trim()
    if ([int]::TryParse($pidText, [ref]$servicePid)) {
        $serviceProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $servicePid" -ErrorAction SilentlyContinue
        if ($serviceProcess -and $serviceProcess.CommandLine -match 'google_(tts|ai)_server\.py') {
            Stop-Process -Id $servicePid -Force -ErrorAction SilentlyContinue
        }
    }
    Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
}

Write-Host ''
Write-Host 'Google AI key saved in Windows user-encrypted storage.'
Write-Host 'Reopen the contract reader to load the key for speech and interpretation.'
