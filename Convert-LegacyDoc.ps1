[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$Destination
)

$ErrorActionPreference = 'Stop'
$word = $null
$document = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $document = $word.Documents.Open($Source, $false, $true)
    $document.SaveAs2($Destination, 16)
    $document.Close($false)
    $document = $null
    $word.Quit()
    $word = $null
    if (-not (Test-Path -LiteralPath $Destination -PathType Leaf)) { throw 'Word did not save the DOCX working copy.' }
    exit 0
} catch {
    Write-Error $_.Exception.Message
    exit 1
} finally {
    if ($document) { try { $document.Close($false) } catch {} }
    if ($word) { try { $word.Quit() } catch {} }
}
