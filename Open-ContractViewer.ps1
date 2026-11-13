[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ContractRoot,

    [Parameter(Mandatory = $true)]
    [string]$ViewerHtml,

    [Parameter(Mandatory = $true)]
    [ValidateSet('Edge', 'Chrome')]
    [string]$Browser
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $ContractRoot).Path
$viewer = (Resolve-Path -LiteralPath $ViewerHtml).Path
$contractPrefix = $root.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
if (-not $viewer.StartsWith($contractPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Viewer HTML must be inside the selected contract folder: $root"
}
$projectRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$projectPrefix = $projectRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
if (-not $viewer.StartsWith($projectPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Viewer must be under the Rev.03 project folder: $projectRoot"
}

$serverScript = Join-Path $PSScriptRoot 'Runtime\google_ai_server.py'
if (-not (Test-Path -LiteralPath $serverScript -PathType Leaf)) {
    throw "Local Google TTS service was not found: $serverScript"
}
$python = Get-Command python.exe -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command py.exe -ErrorAction SilentlyContinue }
if (-not $python) { throw 'Python 3 was not found. Install Python 3 to enable the local Google TTS service.' }
$pythonPath = $python.Source
$pythonPrefix = if ([System.IO.Path]::GetFileName($pythonPath) -ieq 'py.exe') { '-3 ' } else { '' }

$storeDirectory = Join-Path $env:LOCALAPPDATA 'Parsing for Easy Reading'
$credentialPath = Join-Path $storeDirectory 'google-tts-key.xml'
$pidPath = Join-Path $storeDirectory 'google-tts-service.pid'
$logDirectory = Join-Path $storeDirectory 'Logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$port = 8765
$healthUri = "http://127.0.0.1:$port/health"
$desiredTtsConfigured = Test-Path -LiteralPath $credentialPath -PathType Leaf
$health = $null
try { $health = Invoke-RestMethod -Uri $healthUri -TimeoutSec 1 } catch { }
$reuseServer = $false

if ($health -and $health.service -eq 'ContractReaderGoogleTTS' -and $health.status -eq 'ready') {
    if ($health.serverVersion -eq 'gemini-ai-v4' -and $health.root -ieq $projectRoot -and
        [bool]$health.aiConfigured -eq [bool]$desiredTtsConfigured) {
        $reuseServer = $true
    } else {
        if (-not (Test-Path -LiteralPath $pidPath -PathType Leaf)) {
            throw 'The local reader service points to another revision or TTS setup and cannot be restarted safely. Close that service and reopen the reader.'
        }
        $oldPidText = (Get-Content -LiteralPath $pidPath -Raw).Trim()
        $oldPid = 0
        if (-not [int]::TryParse($oldPidText, [ref]$oldPid)) { throw 'The local reader service PID record is invalid.' }
        $oldProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $oldPid" -ErrorAction SilentlyContinue
        if (-not $oldProcess -or $oldProcess.CommandLine -notmatch 'google_(tts|ai)_server\.py') {
            throw 'The existing service process does not match the local Google AI reader.'
        }
        Stop-Process -Id $oldPid -Force
        Remove-Item -LiteralPath $pidPath -Force
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            try { Invoke-RestMethod -Uri $healthUri -TimeoutSec 1 | Out-Null; Start-Sleep -Milliseconds 200 }
            catch { break }
        }
    }
} elseif ($health) {
    throw "Port $port is used by another local service. Close it, then reopen the contract viewer."
}

if (-not $reuseServer) {
    $sessionToken = [Guid]::NewGuid().ToString('N') + [Guid]::NewGuid().ToString('N')
    $serverArgs = @(
        ($pythonPrefix + '-u'),
        ('"{0}"' -f $serverScript),
        '--root', ('"{0}"' -f $projectRoot),
        '--port', [string]$port,
        '--token', $sessionToken
    ) -join ' '
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $stdoutLog = Join-Path $logDirectory "google-tts-$stamp.log"
    $stderrLog = Join-Path $logDirectory "google-tts-$stamp-error.log"
    $previousApiKey = [Environment]::GetEnvironmentVariable('GOOGLE_AI_API_KEY', 'Process')
    $childProcess = $null
    try {
        [Environment]::SetEnvironmentVariable('GOOGLE_AI_API_KEY', $null, 'Process')
        if ($desiredTtsConfigured) {
            $credential = Import-Clixml -LiteralPath $credentialPath
            $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($credential.Password)
            try {
                $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
                [Environment]::SetEnvironmentVariable('GOOGLE_AI_API_KEY', $plainKey, 'Process')
            } finally {
                [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
                $plainKey = $null
                $credential = $null
            }
        }
        $childProcess = Start-Process -FilePath $pythonPath -ArgumentList $serverArgs -WorkingDirectory $projectRoot `
            -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog
    } finally {
        [Environment]::SetEnvironmentVariable('GOOGLE_AI_API_KEY', $previousApiKey, 'Process')
    }
    Set-Content -LiteralPath $pidPath -Value ([string]$childProcess.Id) -Encoding ascii

    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri $healthUri -TimeoutSec 1
            if ($health.service -eq 'ContractReaderGoogleTTS' -and $health.status -eq 'ready') { $ready = $true; break }
        } catch {
            if ($childProcess.HasExited) { break }
            Start-Sleep -Milliseconds 300
        }
    }
    if (-not $ready) {
        $detail = if (Test-Path -LiteralPath $stderrLog) { (Get-Content -LiteralPath $stderrLog -Tail 8 -ErrorAction SilentlyContinue) -join [Environment]::NewLine } else { '' }
        throw "Local reader service did not start. $detail"
    }
}

$relative = $viewer.Substring($projectPrefix.Length).Replace('\', '/')
$encodedRelative = (($relative -split '/') | ForEach-Object { [Uri]::EscapeDataString($_) }) -join '/'
$viewerUrl = "http://127.0.0.1:$port/files/$encodedRelative"

if ($Browser -eq 'Edge') {
    $candidates = @()
    $command = Get-Command msedge.exe -ErrorAction SilentlyContinue
    if ($command) { $candidates += $command.Source }
    $candidates += @(
        (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
        (Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\Application\msedge.exe')
    )
} else {
    $candidates = @()
    $command = Get-Command chrome.exe -ErrorAction SilentlyContinue
    if ($command) { $candidates += $command.Source }
    $candidates += @(
        (Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Google\Chrome\Application\chrome.exe'),
        (Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe')
    )
}
$browserPath = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
if (-not $browserPath) { throw "$Browser executable was not found." }
Start-Process -FilePath $browserPath -ArgumentList @('--new-window', $viewerUrl)

Write-Host "Viewer: $viewerUrl"
if (-not $desiredTtsConfigured) {
    Write-Host 'Google TTS is ready to configure. Run Set-GoogleTTSKey.ps1 locally, then reopen the viewer.'
}
