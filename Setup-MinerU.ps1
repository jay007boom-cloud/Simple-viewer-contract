[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$runtimeRoot = Join-Path (Split-Path -Parent $PSScriptRoot) 'Runtime\MinerU'
$venvPath = Join-Path $runtimeRoot 'venv'
$dataPath = Join-Path $runtimeRoot 'data'
$tempPath = Join-Path $runtimeRoot 'temp'
$pythonPath = Join-Path $venvPath 'Scripts\python.exe'
$cliPath = Join-Path $venvPath 'Scripts\mineru-kit.exe'
$requirementsPath = Join-Path $PSScriptRoot 'requirements-mineru.txt'

New-Item -ItemType Directory -Path $runtimeRoot, $dataPath, $tempPath -Force | Out-Null

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if (-not $pyLauncher) { throw 'Python launcher py.exe was not found. Install Python 3.12 and retry.' }
    & $pyLauncher.Source -3.12 -m venv $venvPath
    if ($LASTEXITCODE -ne 0) { throw "Creating the Rev.03 MinerU environment failed with exit code $LASTEXITCODE." }
}

$oldTemp = $env:TEMP
$oldTmp = $env:TMP
$env:TEMP = $tempPath
$env:TMP = $tempPath
try {
    & $pythonPath -m pip install --upgrade pip --no-cache-dir
    if ($LASTEXITCODE -ne 0) { throw "Updating pip failed with exit code $LASTEXITCODE." }
    & $pythonPath -m pip install --no-cache-dir -r $requirementsPath
    if ($LASTEXITCODE -ne 0) { throw "Installing MinerU failed with exit code $LASTEXITCODE." }
} finally {
    $env:TEMP = $oldTemp
    $env:TMP = $oldTmp
}

# Keep the runtime configuration, model weights, and model-provider caches under Rev.03 on D:.
$dataYamlPath = $dataPath.Replace('\', '/')
$configPath = Join-Path $dataPath 'config.yaml'
if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
    $config = @"
model:
  source: auto
  base_dir: "$dataYamlPath/models"
  small_backend: onnx
  onnx_device: cpu
  vlm:
    engine: llama-cpp
"@
    Set-Content -LiteralPath $configPath -Value $config -Encoding UTF8
}

Write-Host "MinerU runtime: $venvPath"
Write-Host "MinerU data:    $dataPath"
if (-not (Test-Path -LiteralPath $cliPath -PathType Leaf)) { throw "MinerU CLI was not created: $cliPath" }
& $cliPath --version
if ($LASTEXITCODE -ne 0) { throw "MinerU version check failed with exit code $LASTEXITCODE." }

$env:MINERU_HOME = $dataPath
$env:HF_HOME = Join-Path $dataPath 'hf-cache'
$env:MODELSCOPE_CACHE = Join-Path $dataPath 'modelscope-cache'
$env:MINERU_MODEL_ONNX_DEVICE = 'cpu'
New-Item -ItemType Directory -Path $env:HF_HOME, $env:MODELSCOPE_CACHE -Force | Out-Null
Write-Host 'Preparing and verifying MinerU Basic OCR models under Runtime\MinerU\data.'
& $cliPath models download --tier basic --small-backend onnx --source auto
if ($LASTEXITCODE -ne 0) { throw "Downloading MinerU Basic OCR models failed with exit code $LASTEXITCODE." }
& $cliPath models verify --tier basic --small-backend onnx
if ($LASTEXITCODE -ne 0) { throw "Verifying MinerU Basic OCR models failed with exit code $LASTEXITCODE." }
Write-Host 'MinerU 4.1.2 setup and Basic OCR model verification complete.'
