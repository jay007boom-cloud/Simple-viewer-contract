[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ParsedJson,

    [Parameter(Mandatory = $true)]
    [string]$OutputFolder,

    [Parameter(Mandatory = $true)]
    [string]$ContractName,

    [string]$OverridesJson,

    [switch]$Open,

    [switch]$OpenInChrome,

    [switch]$OpenInEdge
)

$ErrorActionPreference = 'Stop'

$parsedPath = (Resolve-Path -LiteralPath $ParsedJson).Path
$outputPath = [System.IO.Path]::GetFullPath($OutputFolder)
$contractLabel = $ContractName.Trim()

if ([string]::IsNullOrWhiteSpace($contractLabel)) {
    throw 'ContractName must not be empty.'
}
if ($contractLabel.IndexOfAny([System.IO.Path]::GetInvalidFileNameChars()) -ge 0) {
    throw 'ContractName contains characters that are not valid in a file name.'
}
if (-not (Test-Path -LiteralPath $parsedPath -PathType Leaf)) {
    throw "Parsed JSON not found: $parsedPath"
}

$templatePath = Join-Path $PSScriptRoot 'contract_viewer.html'
if (-not (Test-Path -LiteralPath $templatePath -PathType Leaf)) {
    throw "Viewer template not found: $templatePath"
}

$builderCandidates = @(
    (Join-Path $PSScriptRoot 'build_contract_viewer.py'),
    (Join-Path $env:USERPROFILE '.codex\skills\contract-structure-parser\scripts\build_contract_viewer.py'),
    (Join-Path $env:USERPROFILE '.gemini\config\skills\contract-structure-parser\scripts\build_contract_viewer.py')
)
$builderPath = $builderCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $builderPath) {
    throw 'build_contract_viewer.py was not found in the Codex or Antigravity skill folders.'
}

$overridePath = $null
if (-not [string]::IsNullOrWhiteSpace($OverridesJson)) {
    $overridePath = (Resolve-Path -LiteralPath $OverridesJson).Path
    if (-not (Test-Path -LiteralPath $overridePath -PathType Leaf)) {
        throw "Overrides JSON not found: $overridePath"
    }
}

New-Item -ItemType Directory -Path $outputPath -Force | Out-Null
$backupPath = Join-Path $outputPath 'Initial Draft_Backup'
New-Item -ItemType Directory -Path $backupPath -Force | Out-Null

$normalizedJson = Join-Path $outputPath ('{0}_parsed-normalized.json' -f $contractLabel)
$viewerHtml = Join-Path $outputPath ('{0}_Viewer.html' -f $contractLabel)

function Save-InitialBackup([string]$SourcePath) {
    if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
        return
    }

    $leaf = [System.IO.Path]::GetFileName($SourcePath)
    $destination = Join-Path $backupPath $leaf
    if (Test-Path -LiteralPath $destination -PathType Leaf) {
        $sourceHash = (Get-FileHash -LiteralPath $SourcePath -Algorithm SHA256).Hash
        $savedHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash
        if ($sourceHash -eq $savedHash) {
            return
        }
        $base = [System.IO.Path]::GetFileNameWithoutExtension($leaf)
        $extension = [System.IO.Path]::GetExtension($leaf)
        $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
        $destination = Join-Path $backupPath ('{0}_{1}{2}' -f $base, $stamp, $extension)
    }
    Copy-Item -LiteralPath $SourcePath -Destination $destination
}

Save-InitialBackup $parsedPath
if ($overridePath) {
    Save-InitialBackup $overridePath
}
if (Test-Path -LiteralPath $normalizedJson -PathType Leaf) {
    Save-InitialBackup $normalizedJson
}
if (Test-Path -LiteralPath $viewerHtml -PathType Leaf) {
    Save-InitialBackup $viewerHtml
}

$builderArgs = @(
    $parsedPath,
    $viewerHtml,
    '--template',
    $templatePath,
    '--normalized-json',
    $normalizedJson
)
if ($overridePath) {
    $builderArgs += @('--overrides', $overridePath)
}

 $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
 $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
if ($pythonCommand) {
    & $pythonCommand.Source $builderPath @builderArgs
} elseif ($pyLauncher) {
    & $pyLauncher.Source -3 $builderPath @builderArgs
} else {
    throw 'Python 3 was not found. Install Python 3 to build the HTML reader.'
}
if ($LASTEXITCODE -ne 0) {
    throw "Contract viewer build failed with exit code $LASTEXITCODE."
}
if (-not (Test-Path -LiteralPath $viewerHtml -PathType Leaf)) {
    throw "Viewer output was not created: $viewerHtml"
}
if (-not (Test-Path -LiteralPath $normalizedJson -PathType Leaf)) {
    throw "Normalized JSON output was not created: $normalizedJson"
}

# Standard contract workspaces get a one-click local-service launcher.
$contractsRoot = Join-Path $PSScriptRoot 'Contracts'
$contractRoot = Split-Path -Parent $outputPath
if ((Split-Path -Parent $contractRoot) -ieq $contractsRoot -and
    (Split-Path -Leaf $outputPath) -ieq 'output') {
    $launcherPath = Join-Path $outputPath 'Open-with-Google-TTS.cmd'
    $launcherText = @'
@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\..\..\Launch-Reader.ps1" -OutputFolder "%~dp0." -Browser Edge
if errorlevel 1 pause
'@
    [System.IO.File]::WriteAllText($launcherPath, ($launcherText -replace "(?<!`r)`n", "`r`n"), [System.Text.Encoding]::ASCII)
}

Write-Host ''
Write-Host "Viewer:        $viewerHtml"
Write-Host "Normalized:    $normalizedJson"
Write-Host "Initial backup: $backupPath"
if ($launcherPath) { Write-Host "Google TTS launcher: $launcherPath" }

if ($OpenInChrome -and $OpenInEdge) {
    throw 'Choose either -OpenInChrome or -OpenInEdge, not both.'
}
if ($OpenInEdge -or $OpenInChrome -or $Open) {
    $openScript = Join-Path $PSScriptRoot 'Open-ContractViewer.ps1'
    if (-not (Test-Path -LiteralPath $openScript -PathType Leaf)) {
        throw "Local reader opener was not found: $openScript"
    }
    $browser = if ($OpenInChrome) { 'Chrome' } else { 'Edge' }
    $contractRoot = Split-Path -Parent $outputPath
    & $openScript -ContractRoot $contractRoot -ViewerHtml $viewerHtml -Browser $browser
}
