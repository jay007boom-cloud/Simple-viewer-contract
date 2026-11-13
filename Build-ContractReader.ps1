[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$launcher = Join-Path $root 'launcher.py'
$python = Get-Command python.exe -ErrorAction SilentlyContinue
$pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue

if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "Launcher source not found: $launcher"
}
if ($python) {
    $pythonCommand = $python.Source
    $pythonPrefix = @()
} elseif ($pyLauncher) {
    $pythonCommand = $pyLauncher.Source
    $pythonPrefix = @('-3')
} else {
    throw 'Python 3 was not found.'
}

$arguments = @(
    '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed',
    '--name', 'ContractViewer_Rev22',
    '--distpath', $root,
    '--workpath', (Join-Path $root '.build\pyinstaller'),
    '--specpath', $root,
    $launcher
)
& $pythonCommand @pythonPrefix @arguments
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}

$exe = Join-Path $root 'ContractViewer_Rev22.exe'
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
    throw "Executable was not created: $exe"
}
Write-Host "Executable: $exe"
