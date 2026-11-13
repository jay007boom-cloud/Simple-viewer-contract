[CmdletBinding()]
param(
    [string]$SourceFile,
    [string]$ContractFolder,
    [ValidateSet('Auto', 'MarkItDown', 'MinerU')]
    [string]$Converter = 'Auto',
    [switch]$OpenInChrome,
    [switch]$OpenInEdge
)

$ErrorActionPreference = 'Stop'
$operationRoot = $PSScriptRoot
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom


if ([string]::IsNullOrWhiteSpace($SourceFile) -eq [string]::IsNullOrWhiteSpace($ContractFolder)) {
    throw 'Provide exactly one of -SourceFile (prepare a contract) or -ContractFolder (build its viewer).'
}

if (-not [string]::IsNullOrWhiteSpace($SourceFile)) {
    $sourcePath = (Resolve-Path -LiteralPath $SourceFile).Path
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) { throw "Source file not found: $sourcePath" }
    $extension = [System.IO.Path]::GetExtension($sourcePath).ToLowerInvariant()
    if ($extension -notin @('.pdf', '.docx', '.pptx', '.xlsx', '.xls', '.csv', '.txt', '.md', '.html', '.htm', '.xml', '.json')) {
        throw "Supported source types: PDF, DOCX, PPTX, XLS/XLSX, CSV, TXT, MD, HTML/HTM, XML, and JSON. Save legacy DOC or PPT files as DOCX/PPTX first. Received: $extension"
    }

    $baseName = [System.IO.Path]::GetFileNameWithoutExtension($sourcePath)
    $safeName = $baseName -replace '[<>:"/\\|?*]', '_'
    $contractsRoot = Join-Path $operationRoot 'Contracts'
    New-Item -ItemType Directory -Path $contractsRoot -Force | Out-Null
    $contractRoot = Join-Path $contractsRoot $safeName
    if (Test-Path -LiteralPath $contractRoot) {
        $existingSource = Join-Path (Join-Path $contractRoot 'source') ([System.IO.Path]::GetFileName($sourcePath))
        $existingMarkdowns = @(Get-ChildItem -LiteralPath (Join-Path $contractRoot 'extraction') -Filter '*.md' -File -ErrorAction SilentlyContinue)
        $existingJson = Join-Path (Join-Path $contractRoot 'parsed') 'contract.json'
        $canResume = (Test-Path -LiteralPath $existingSource -PathType Leaf) -and
                     ($existingMarkdowns.Count -eq 0) -and
                     (-not (Test-Path -LiteralPath $existingJson -PathType Leaf))
        if ($canResume) {
            $sourceHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash
            $existingHash = (Get-FileHash -LiteralPath $existingSource -Algorithm SHA256).Hash
            $canResume = ($sourceHash -eq $existingHash)
        }
        if (-not $canResume) {
            $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
            $contractRoot = Join-Path $contractsRoot ('{0}_{1}' -f $safeName, $stamp)
            $suffix = 1
            while (Test-Path -LiteralPath $contractRoot) {
                $contractRoot = Join-Path $contractsRoot ('{0}_{1}_{2}' -f $safeName, $stamp, $suffix)
                $suffix++
            }
        }
    }

    $sourceDir = Join-Path $contractRoot 'source'
    $extractDir = Join-Path $contractRoot 'extraction'
    $parsedDir = Join-Path $contractRoot 'parsed'
    $outputDir = Join-Path $contractRoot 'output'
    $backupDir = Join-Path $outputDir 'Initial Draft_Backup'
    foreach ($dir in @($sourceDir, $extractDir, $parsedDir, $outputDir, $backupDir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }

    $sourceCopy = Join-Path $sourceDir ([System.IO.Path]::GetFileName($sourcePath))
    if ([System.IO.Path]::GetFullPath($sourcePath) -ine [System.IO.Path]::GetFullPath($sourceCopy)) {
        Copy-Item -LiteralPath $sourcePath -Destination $sourceCopy
    }
    $markdownPath = Join-Path $extractDir ($baseName + '.md')
    $converterUsed = $Converter
    $pdfProfile = $null
    $converterDetails = $null

    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if (-not $python -and -not $pyLauncher -and $extension -ne '.md') {
        throw 'Python 3 was not found. Install Python 3 and MarkItDown, then retry.'
    }

    if ($extension -eq '.pdf' -and ($python -or $pyLauncher)) {
        $probeScript = Join-Path $operationRoot 'inspect_pdf.py'
        try {
            if (-not (Test-Path -LiteralPath $probeScript -PathType Leaf)) { throw "PDF inspection script not found: $probeScript" }
            if ($python) { $probeOutput = & $python.Source $probeScript $sourceCopy 2>$null }
            else { $probeOutput = & $pyLauncher.Source -3 $probeScript $sourceCopy 2>$null }
            if ($LASTEXITCODE -eq 0 -and $probeOutput) { $pdfProfile = ($probeOutput | Out-String).Trim() | ConvertFrom-Json }
        } catch {
            $pdfProfile = $null
        }
        if (-not $pdfProfile -and $Converter -eq 'Auto') {
            throw 'Auto could not inspect this PDF. Install pypdf in the selected Python environment or explicitly choose MarkItDown.'
        }
        if ($pdfProfile -and $pdfProfile.encrypted) {
            throw 'The PDF is encrypted. Unlock it and save an authorized working copy before Markdown extraction.'
        }
    }

    if ($extension -eq '.md') {
        if ([System.IO.Path]::GetFullPath($sourceCopy) -ine [System.IO.Path]::GetFullPath($markdownPath)) {
            Copy-Item -LiteralPath $sourceCopy -Destination $markdownPath
        }
        $converterUsed = 'Existing Markdown'
    } else {
        $engine = $Converter
        if ($engine -eq 'Auto') {
            if ($extension -eq '.pdf' -and $pdfProfile -and $pdfProfile.pages -gt 0 -and
                ($pdfProfile.characters / [Math]::Min(5, $pdfProfile.pages)) -lt 20) {
                $engine = 'MinerU'
            } else {
                $engine = 'MarkItDown'
            }
        }

        if ($engine -eq 'MinerU') {
            if ($extension -ne '.pdf') { throw 'MinerU is available for PDF files only. Choose MarkItDown for this document type.' }
            $mineruRuntime = Join-Path $operationRoot 'Runtime\MinerU'
            $mineruCli = Join-Path $mineruRuntime 'venv\Scripts\mineru-kit.exe'
            if (-not (Test-Path -LiteralPath $mineruCli -PathType Leaf)) {
                # Revision snapshots share the installed local runtime in Rev.03.
                $sharedRuntime = Join-Path (Split-Path -Parent $operationRoot) 'Runtime\MinerU'
                $sharedCli = Join-Path $sharedRuntime 'venv\Scripts\mineru-kit.exe'
                if (Test-Path -LiteralPath $sharedCli -PathType Leaf) {
                    $mineruRuntime = $sharedRuntime
                    $mineruCli = $sharedCli
                }
            }
            if (-not (Test-Path -LiteralPath $mineruCli -PathType Leaf)) {
                throw "MinerU is not set up. Run '$operationRoot\Setup-MinerU.ps1' once, then retry."
            }

            $mineruData = Join-Path $mineruRuntime 'data'
            $mineruTemp = Join-Path $mineruRuntime 'temp'
            $mineruOutputDir = Join-Path $extractDir 'mineru_raw'
            $mineruHfCache = Join-Path $mineruData 'hf-cache'
            $mineruModelScopeCache = Join-Path $mineruData 'modelscope-cache'
            foreach ($dir in @($mineruData, $mineruTemp, $mineruOutputDir, $mineruHfCache, $mineruModelScopeCache)) {
                New-Item -ItemType Directory -Path $dir -Force | Out-Null
            }

            $oldMineruHome = $env:MINERU_HOME
            $oldHfHome = $env:HF_HOME
            $oldModelScopeCache = $env:MODELSCOPE_CACHE
            $oldOnnxDevice = $env:MINERU_MODEL_ONNX_DEVICE
            $oldTemp = $env:TEMP
            $oldTmp = $env:TMP
            $mineruExitCode = -1
            try {
                $env:MINERU_HOME = $mineruData
                $env:HF_HOME = $mineruHfCache
                $env:MODELSCOPE_CACHE = $mineruModelScopeCache
                $env:MINERU_MODEL_ONNX_DEVICE = 'cpu'
                $env:TEMP = $mineruTemp
                $env:TMP = $mineruTemp
                $mineruArgs = @('parse', $sourceCopy, '-o', $mineruOutputDir, '--tier', 'basic', '--ocr-mode', 'auto')
                $oldPreference = $ErrorActionPreference
                try {
                    $ErrorActionPreference = 'Continue'
                    & $mineruCli @mineruArgs
                    $mineruExitCode = $LASTEXITCODE
                } finally {
                    $ErrorActionPreference = $oldPreference
                }
            } finally {
                $env:MINERU_HOME = $oldMineruHome
                $env:HF_HOME = $oldHfHome
                $env:MODELSCOPE_CACHE = $oldModelScopeCache
                $env:MINERU_MODEL_ONNX_DEVICE = $oldOnnxDevice
                $env:TEMP = $oldTemp
                $env:TMP = $oldTmp
            }
            if ($mineruExitCode -ne 0) { throw "MinerU conversion failed with exit code $mineruExitCode." }
            $mineruMarkdown = Join-Path $mineruOutputDir ($baseName + '.md')
            if (-not (Test-Path -LiteralPath $mineruMarkdown -PathType Leaf)) {
                $candidate = Get-ChildItem -LiteralPath $mineruOutputDir -Filter '*.md' -File | Select-Object -First 1
                if (-not $candidate) { throw "MinerU completed without Markdown output in $mineruOutputDir" }
                $mineruMarkdown = $candidate.FullName
            }
            Copy-Item -LiteralPath $mineruMarkdown -Destination $markdownPath -Force
            $converterUsed = 'MinerU 4.1.2 (Basic OCR, CPU)'
            $converterDetails = [ordered]@{
                runtime = 'MinerU 4.1.2'
                tier = 'basic'
                ocr_mode = 'auto'
                onnx_device = 'cpu'
                remote_parse = $false
                raw_markdown = $mineruMarkdown
            }
        } else {
            $oldPreference = $ErrorActionPreference
            try {
                $ErrorActionPreference = 'Continue'
                if ($python) { & $python.Source -m markitdown $sourceCopy -o $markdownPath }
                else { & $pyLauncher.Source -3 -m markitdown $sourceCopy -o $markdownPath }
                $conversionExitCode = $LASTEXITCODE
            } finally {
                $ErrorActionPreference = $oldPreference
            }
            if ($conversionExitCode -ne 0) { throw "MarkItDown conversion failed with exit code $conversionExitCode." }
            $converterUsed = 'MarkItDown'
        }
    }
    if (-not (Test-Path -LiteralPath $markdownPath -PathType Leaf) -or (Get-Item -LiteralPath $markdownPath).Length -eq 0) {
        throw "Markdown extraction did not create a non-empty file: $markdownPath"
    }

    $conversionInfo = [ordered]@{
        source_file = [System.IO.Path]::GetFileName($sourceCopy)
        source_extension = $extension
        source_sha256 = (Get-FileHash -LiteralPath $sourceCopy -Algorithm SHA256).Hash
        converter_requested = $Converter
        converter_used = $converterUsed
        converter_details = $converterDetails
        pdf_profile = $pdfProfile
        markdown_file = [System.IO.Path]::GetFileName($markdownPath)
        converted_at = (Get-Date).ToString('o')
    }
    $conversionInfoPath = Join-Path $extractDir 'conversion-info.json'
    $conversionInfo | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $conversionInfoPath -Encoding UTF8

    $promptPath = Join-Path $parsedDir 'JSON-PARSING-PROMPT.md'
    $prompt = @(
        '# Create the structured contract JSON',
        '',
        'Read the source contract and its Markdown extraction before generating JSON.',
        '',
        "Source file: $sourceCopy",
        "Markdown extraction: $markdownPath",
        "Conversion record: $conversionInfoPath",
        "Converter used: $converterUsed",
        "Save the parsed JSON to: $(Join-Path $parsedDir 'contract.json')",
        "Set JSON source_file to: ../source/$([System.IO.Path]::GetFileName($sourceCopy))",
        "Operation guide: $(Join-Path $operationRoot 'README.md')",
        "Reusable parsing guide: $(Join-Path $operationRoot 'REUSABLE_WORKFLOW_GUIDE.md')",
        '',
        'Preserve exact clause numbers, titles, text, subparagraphs, tables, and source-page references when present. Use Markdown to locate text, then check uncertain or merged rows against the source document, including the original DOCX/PDF table structure where relevant. Keep a global definitions table only under an actual glossary section; do not invent a glossary when the source has none. Keep every numbered clause and its body as a separate entry, including clauses presented inside tables.',
        'For lettered subparagraphs such as a), b), or d) through h), keep every marker and put a single line break before each item in the JSON content. Do not flatten a lettered list into one run-on sentence. Use a blank line only when the source starts a new paragraph; use one line break for same-paragraph subitems.',
        'Treat every printed clause number as a separate clause entry, including numbers shown inside tables or inline in a Markdown row, even if a number repeats or is out of sequence. Never absorb the next numbered clause and its text into the preceding clause. Preserve duplicate printed numbers with unique internal keys such as 10.3.1~2, keep display_nc equal to the printed number, and record all occurrences in _duplicate_refs. Do not split ordinary cross-references; confirm clause boundaries from Markdown and the source document.',
        'Do not invent missing wording. Do not transmit the contract to an external API unless I explicitly approve it.',
        'Create the initial parsed JSON from the source and Markdown first. If the contract-structure-parser skill is available, use it afterward to repair structure and build the viewer; that skill does not create a complete contract JSON from arbitrary source files by itself.',
        '',
        'After creating parsed\contract.json, build and open the viewer in Edge or Chrome with one of these commands:',
        '',
        'powershell -NoProfile -File Process-Contract.ps1 -ContractFolder CONTRACT_FOLDER -OpenInEdge',
        'powershell -NoProfile -File Process-Contract.ps1 -ContractFolder CONTRACT_FOLDER -OpenInChrome'
    ) -join [Environment]::NewLine
    Set-Content -LiteralPath $promptPath -Value $prompt -Encoding UTF8

    Write-Host "WORKSPACE=$contractRoot"
    Write-Host "SOURCE=$sourceCopy"
    Write-Host "MARKDOWN=$markdownPath"
    Write-Host "CONVERTER=$converterUsed"
    Write-Host "CONVERSION_INFO=$conversionInfoPath"
    Write-Host "NEXT_PROMPT=$promptPath"
    Write-Host 'STATUS=Markdown prepared. Create parsed\contract.json from the source and Markdown, then rerun this script with -ContractFolder.'
    exit 0
}

$contractRoot = (Resolve-Path -LiteralPath $ContractFolder).Path
$parsedJson = Join-Path $contractRoot 'parsed\contract.json'
if (-not (Test-Path -LiteralPath $parsedJson -PathType Leaf)) {
    throw "Parsed JSON not found: $parsedJson. Create it using parsed\JSON-PARSING-PROMPT.md first."
}
$contractName = Split-Path -Leaf $contractRoot
$buildScript = Join-Path $operationRoot 'Build-ContractViewer.ps1'
if (-not (Test-Path -LiteralPath $buildScript -PathType Leaf)) { throw "Build script not found: $buildScript" }
$outputDir = Join-Path $contractRoot 'output'
if ($OpenInChrome -and $OpenInEdge) { throw 'Choose either -OpenInChrome or -OpenInEdge, not both.' }
if ($OpenInChrome) {
    & $buildScript -ParsedJson $parsedJson -OutputFolder $outputDir -ContractName $contractName -OpenInChrome
} elseif ($OpenInEdge) {
    & $buildScript -ParsedJson $parsedJson -OutputFolder $outputDir -ContractName $contractName -OpenInEdge
} else {
    & $buildScript -ParsedJson $parsedJson -OutputFolder $outputDir -ContractName $contractName
}
if ($LASTEXITCODE -ne 0) { throw "Viewer build failed with exit code $LASTEXITCODE." }
