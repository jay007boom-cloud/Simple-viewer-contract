[CmdletBinding()]
param(
    [string]$SourceFile,
    [string]$ContractFolder,
    [ValidateSet('Auto', 'MarkItDown', 'MinerU')]
    [string]$Converter = 'Auto',
    [string]$SupplementMarkdown,
    [switch]$Reparse,
    [switch]$MergeSupplementOnly,
    [switch]$ForceNewWorkspace,
    [switch]$OpenInChrome,
    [switch]$NoOpen
)

$ErrorActionPreference = 'Stop'
$operationRoot = $PSScriptRoot
$utf8 = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
if ([string]::IsNullOrWhiteSpace($SourceFile) -eq [string]::IsNullOrWhiteSpace($ContractFolder)) {
    throw 'Provide exactly one of -SourceFile or -ContractFolder.'
}
$started = Get-Date
$watch = [Diagnostics.Stopwatch]::StartNew()
$stageSeconds = [ordered]@{}
$originalSource = $null
$temporaryFolder = $null
$preprocessedFile = $null
$cacheHit = $false

function Convert-LegacyDoc([string]$Path) {
    $script:temporaryFolder = Join-Path (Join-Path $env:TEMP 'ParsingEasyReading-Rev2.2') ([guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $script:temporaryFolder -Force | Out-Null
    $output = Join-Path $script:temporaryFolder ([IO.Path]::GetFileNameWithoutExtension($Path) + '.docx')
    $stdout = Join-Path $script:temporaryFolder 'word-output.log'
    $stderr = Join-Path $script:temporaryFolder 'word-error.log'
    $existingWordIds = @(Get-Process WINWORD -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
    $startedWord = Get-Date
    $helper = Join-Path $operationRoot 'Convert-LegacyDoc.ps1'
    $arguments = @('-STA', '-NoProfile', '-File', ('"' + $helper + '"'),
        '-Source', ('"' + $Path + '"'), '-Destination', ('"' + $output + '"'))
    $child = Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    if (-not $child.WaitForExit(45000)) {
        Stop-Process -Id $child.Id -Force -ErrorAction SilentlyContinue
        Get-Process WINWORD -ErrorAction SilentlyContinue | Where-Object {
            $_.Id -notin $existingWordIds -and $_.MainWindowHandle -eq 0 -and $_.StartTime -ge $startedWord
        } | Stop-Process -Force -ErrorAction SilentlyContinue
        throw 'Legacy DOC conversion timed out after 45 seconds. Open the DOC in Word and save an authorized DOCX copy, then retry.'
    }
    if ($child.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $output -PathType Leaf)) {
        $detail = if (Test-Path -LiteralPath $stderr) { (Get-Content -LiteralPath $stderr -Raw -ErrorAction SilentlyContinue).Trim() } else { '' }
        throw "Legacy DOC conversion failed. Microsoft Word must open the document successfully. $detail"
    }
    return $output
}

try {
    if ($SourceFile) {
        $originalSource = (Resolve-Path -LiteralPath $SourceFile).Path
        $inputPath = $originalSource
        if (-not $ForceNewWorkspace -and [IO.Path]::GetExtension($inputPath).ToLowerInvariant() -ne '.doc') {
            $inputHash = (Get-FileHash -LiteralPath $inputPath -Algorithm SHA256).Hash
            $contractsRoot = Join-Path $operationRoot 'Contracts'
            $candidates = Get-ChildItem -LiteralPath $contractsRoot -Directory -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
            foreach ($candidate in $candidates) {
                $candidateInfoPath = Join-Path $candidate.FullName 'extraction\conversion-info.json'
                if (-not (Test-Path -LiteralPath $candidateInfoPath -PathType Leaf)) { continue }
                try { $candidateInfo = Get-Content -LiteralPath $candidateInfoPath -Encoding UTF8 -Raw | ConvertFrom-Json } catch { continue }
                if ($candidateInfo.source_sha256 -eq $inputHash -and
                    ($Converter -eq 'Auto' -or $candidateInfo.converter_requested -eq $Converter) -and
                    (Test-Path -LiteralPath (Join-Path $candidate.FullName ('extraction\' + $candidateInfo.markdown_file)))) {
                    $workspace = $candidate.FullName
                    $cacheHit = $true
                    break
                }
            }
        }
        if (-not $cacheHit) {
            if ([IO.Path]::GetExtension($inputPath).ToLowerInvariant() -eq '.doc') {
                $inputPath = Convert-LegacyDoc $inputPath
                $preprocessedFile = $inputPath
            }
            $processor = Join-Path $operationRoot 'Process-Contract.ps1'
            # Third-party converters may write non-fatal warnings to stderr.
            $oldPreference = $ErrorActionPreference
            try {
                $ErrorActionPreference = 'Continue'
                $prepareOutput = & powershell.exe -NoProfile -File $processor -SourceFile $inputPath -Converter $Converter 2>&1
                $prepareExit = $LASTEXITCODE
            } finally {
                $ErrorActionPreference = $oldPreference
            }
            if ($prepareExit -ne 0) { throw "Document preparation failed: $($prepareOutput | Out-String)" }
            $workspaceLine = @($prepareOutput | ForEach-Object { "$_" } | Where-Object { $_ -like 'WORKSPACE=*' } | Select-Object -Last 1)
            if (-not $workspaceLine) { throw "Preparation did not report a workspace: $($prepareOutput | Out-String)" }
            $workspace = $workspaceLine[0].Substring('WORKSPACE='.Length)
            if ($preprocessedFile) {
                Copy-Item -LiteralPath $originalSource -Destination (Join-Path $workspace 'source')
                $preprocessInfo = [ordered]@{original_file=[IO.Path]::GetFileName($originalSource);
                    working_copy=[IO.Path]::GetFileName($preprocessedFile);method='Microsoft Word SaveAs2 DOCX';
                    converted_at=(Get-Date).ToString('o')}
                $preprocessInfo | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $workspace 'extraction\preprocessing-info.json') -Encoding UTF8
            }
        }
        $stageSeconds['preprocess_and_extract'] = [Math]::Round($watch.Elapsed.TotalSeconds, 2)
    } else {
        $workspace = (Resolve-Path -LiteralPath $ContractFolder).Path
        $stageSeconds['preprocess_and_extract'] = 0
    }

    $extractDir = Join-Path $workspace 'extraction'
    $parsedDir = Join-Path $workspace 'parsed'
    $outputDir = Join-Path $workspace 'output'
    $infoPath = Join-Path $extractDir 'conversion-info.json'
    if (-not (Test-Path -LiteralPath $infoPath -PathType Leaf)) { throw "Conversion record missing: $infoPath" }
    $info = Get-Content -LiteralPath $infoPath -Encoding UTF8 -Raw | ConvertFrom-Json
    $sourceCopy = Join-Path (Join-Path $workspace 'source') $info.source_file
    $markdownPath = Join-Path $extractDir $info.markdown_file
    if (-not (Test-Path -LiteralPath $sourceCopy -PathType Leaf)) { throw "Prepared source missing: $sourceCopy" }
    if (-not (Test-Path -LiteralPath $markdownPath -PathType Leaf)) { throw "Markdown missing: $markdownPath" }
    $parsedJson = Join-Path $parsedDir 'contract.json'
    $supplementPath = $null
    if ($SupplementMarkdown) {
        $supplementPath = (Resolve-Path -LiteralPath $SupplementMarkdown).Path
    } else {
        $candidate = Get-ChildItem -LiteralPath $extractDir -Filter '*_Schedules_MinerU.md' -Recurse -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($candidate) { $supplementPath = $candidate.FullName }
    }

    $parseStart = $watch.Elapsed.TotalSeconds
    $parsedThisRun = $false
    if (-not (Test-Path -LiteralPath $parsedJson -PathType Leaf) -or $Reparse -or $MergeSupplementOnly) {
        if ($MergeSupplementOnly -and -not (Test-Path -LiteralPath $parsedJson -PathType Leaf)) {
            throw 'MergeSupplementOnly requires an existing parsed\contract.json.'
        }
        if ($MergeSupplementOnly -and -not $supplementPath) {
            throw 'MergeSupplementOnly requires a reviewed Schedule Markdown in extraction/ or -SupplementMarkdown.'
        }
        if (Test-Path -LiteralPath $parsedJson -PathType Leaf) {
            $backupDir = Join-Path $outputDir 'Initial Draft_Backup'
            New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
            Copy-Item -LiteralPath $parsedJson -Destination (Join-Path $backupDir ('contract_before_reparse_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.json'))
        }
        $python = Get-Command python.exe -ErrorAction SilentlyContinue
        if (-not $python) { throw 'Python 3 is required for local JSON parsing.' }
        if ($MergeSupplementOnly) {
            $parser = Join-Path $operationRoot 'merge_reviewed_schedules.py'
            $arguments = @($parser, '--parsed', $parsedJson, '--supplement', $supplementPath)
        } else {
            $parser = Join-Path $operationRoot 'parse_contract_md.py'
            $arguments = @($parser, '--markdown', $markdownPath, '--output', $parsedJson,
                '--source-file', ('../source/' + [IO.Path]::GetFileName($sourceCopy)), '--source-path', $sourceCopy)
            if ($supplementPath) { $arguments += @('--supplement', $supplementPath) }
        }
        & $python.Source @arguments
        if ($LASTEXITCODE -ne 0) { throw 'Local Markdown-to-JSON parsing failed.' }
        $parsedThisRun = $true
    }
    $stageSeconds['json_parse'] = [Math]::Round($watch.Elapsed.TotalSeconds - $parseStart, 2)

    $buildStart = $watch.Elapsed.TotalSeconds
    $builder = Join-Path $operationRoot 'Build-ContractViewer.ps1'
    $contractName = Split-Path -Leaf $workspace
    $viewer = Join-Path $outputDir ($contractName + '_Viewer.html')
    if ((Test-Path -LiteralPath $viewer -PathType Leaf) -and -not $Reparse -and -not $parsedThisRun) {
        if (-not $NoOpen) {
            $browser = if ($OpenInChrome) { 'Chrome' } else { 'Edge' }
            & (Join-Path $operationRoot 'Open-ContractViewer.ps1') -ContractRoot $workspace -ViewerHtml $viewer -Browser $browser
        }
    } else {
        if ($NoOpen) { & $builder -ParsedJson $parsedJson -OutputFolder $outputDir -ContractName $contractName }
        elseif ($OpenInChrome) { & $builder -ParsedJson $parsedJson -OutputFolder $outputDir -ContractName $contractName -OpenInChrome }
        else { & $builder -ParsedJson $parsedJson -OutputFolder $outputDir -ContractName $contractName -OpenInEdge }
        if ($LASTEXITCODE -ne 0) { throw 'Viewer build failed.' }
    }
    $stageSeconds['viewer_build_and_open'] = [Math]::Round($watch.Elapsed.TotalSeconds - $buildStart, 2)
    if (-not (Test-Path -LiteralPath $viewer -PathType Leaf)) { throw "Viewer missing: $viewer" }
    $parsedData = Get-Content -LiteralPath $parsedJson -Encoding UTF8 -Raw | ConvertFrom-Json
    $report = [ordered]@{
        revision = '_Rev2.2'; input = $originalSource; workspace = $workspace; cache_hit = $cacheHit;
        source_file = $sourceCopy; markdown_file = $markdownPath; supplement_markdown = $supplementPath;
        parsed_json = $parsedJson; viewer_html = $viewer; converter = $info.converter_used;
        started_at = $started.ToString('o'); completed_at = (Get-Date).ToString('o');
        elapsed_seconds = [Math]::Round($watch.Elapsed.TotalSeconds, 2); stage_seconds = $stageSeconds;
        clauses = @($parsedData.clauses).Count; parse_warnings = @($parsedData._parse_warnings);
        browser = $(if ($NoOpen) { 'none' } elseif ($OpenInChrome) { 'Chrome' } else { 'Edge' })
    }
    $reportPath = Join-Path $workspace 'operation-report.json'
    $report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $reportPath -Encoding UTF8
    Write-Host "WORKSPACE=$workspace"
    Write-Host "JSON=$parsedJson"
    Write-Host "VIEWER=$viewer"
    Write-Host "REPORT=$reportPath"
} finally {
    if ($temporaryFolder -and (Test-Path -LiteralPath $temporaryFolder)) {
        $resolved = [IO.Path]::GetFullPath($temporaryFolder)
        $safeRoot = [IO.Path]::GetFullPath((Join-Path $env:TEMP 'ParsingEasyReading-Rev2.2')).TrimEnd('\') + '\'
        if ($resolved.StartsWith($safeRoot, [StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $resolved -Recurse -Force
        }
    }
}
