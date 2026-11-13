[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$OutputFolder,

    [ValidateSet('Edge', 'Chrome')]
    [string]$Browser = 'Edge'
)

$ErrorActionPreference = 'Stop'
$outputPath = (Resolve-Path -LiteralPath $OutputFolder).Path
$viewers = @(Get-ChildItem -LiteralPath $outputPath -Filter '*_Viewer.html' -File)
if ($viewers.Count -ne 1) {
    throw "Expected one contract viewer HTML in $outputPath; found $($viewers.Count)."
}

$contractRoot = Split-Path -Parent $outputPath
& (Join-Path $PSScriptRoot 'Open-ContractViewer.ps1') `
    -ContractRoot $contractRoot -ViewerHtml $viewers[0].FullName -Browser $Browser
