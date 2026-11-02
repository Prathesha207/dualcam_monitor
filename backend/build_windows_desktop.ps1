[CmdletBinding()]
param(
  [switch]$SkipPyInstaller
)

# Produces a self-contained 64-bit Windows NSIS installer for Vision Monitor.
$ErrorActionPreference = 'Stop'
$BackendDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $BackendDir
$FrontendDir = if (Test-Path (Join-Path $ProjectRoot 'frontend')) {
  Join-Path $ProjectRoot 'frontend'
} else {
  Join-Path $ProjectRoot 'vision-ai-frontend'
}
$ReleaseVenv = if (Test-Path (Join-Path $BackendDir '.venv')) {
  Join-Path $BackendDir '.venv'
} else {
  Join-Path $BackendDir '.venv-release'
}
$PythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $PythonCmd) {
  $PythonCmd = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $PythonCmd) { throw 'Python was not found in PATH. Please install Python 3.10+ and add it to PATH.' }
$Python = $PythonCmd.Source

if (-not [Environment]::Is64BitOperatingSystem) { throw 'A 64-bit Windows host is required.' }
if (-not (Test-Path (Join-Path $FrontendDir 'package.json'))) { throw 'frontend directory with package.json must be beside backend.' }

if (-not (Test-Path $ReleaseVenv)) {
  & $Python -m venv $ReleaseVenv
}
$VenvPython = Join-Path $ReleaseVenv 'Scripts\python.exe'

Write-Host 'Installing backend dependencies...'
& $VenvPython -m pip install --prefer-binary -r (Join-Path $BackendDir 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Failed to install backend requirements.' }

if (-not $SkipPyInstaller -or -not (Test-Path (Join-Path $BackendDir 'dist\backend\backend.exe'))) {
  Push-Location $BackendDir
  try {
    Remove-Item -LiteralPath (Join-Path $BackendDir 'build') -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $BackendDir 'dist') -Recurse -Force -ErrorAction SilentlyContinue

    $PyInstallerArgs = @(
      '--noconfirm', '--clean', '--onedir', '--name', 'backend', 'run.py',
      '--add-data', 'alembic;alembic',
      '--exclude-module', 'torch',
      '--exclude-module', 'torchvision',
      '--exclude-module', 'ultralytics',
      '--exclude-module', 'head_tail_analyzer',
      '--collect-all', 'app',
      '--collect-all', 'fastapi',
      '--collect-all', 'starlette',
      '--collect-all', 'uvicorn',
      '--collect-all', 'sqlalchemy',
      '--collect-all', 'cv2',
      '--collect-all', 'depthai',
      '--collect-all', 'av',
      '--collect-all', 'imageio_ffmpeg'
    )
    & $VenvPython -m PyInstaller @PyInstallerArgs
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
  } finally { Pop-Location }
} else {
  Write-Host 'Reusing existing dist\backend...'
}

$IconIco = Join-Path $FrontendDir 'public\icon.ico'
if (-not (Test-Path $IconIco)) {
  if (Test-Path (Join-Path $FrontendDir 'public\generate_icons.py')) {
    & $VenvPython (Join-Path $FrontendDir 'public\generate_icons.py')
  }
}

$BackendDist = Join-Path $BackendDir 'dist\backend'
if (Test-Path $BackendDist) {
  Write-Host 'Optimizing dist\backend by removing non-runtime development files...'
  Get-ChildItem -Path $BackendDist -Recurse -Include *.lib, *.pdb, *.exp, *.a -File | Remove-Item -Force -ErrorAction SilentlyContinue
}

Push-Location $FrontendDir
try {
  Remove-Item -LiteralPath (Join-Path $FrontendDir 'dist_app\win-unpacked') -Recurse -Force -ErrorAction SilentlyContinue
  Remove-Item -Path (Join-Path $FrontendDir 'dist_app\*.nsis.7z*') -Force -ErrorAction SilentlyContinue
  Remove-Item -Path (Join-Path $FrontendDir 'dist_app\Vision-Monitor*') -Recurse -Force -ErrorAction SilentlyContinue

  if (-not (Test-Path (Join-Path $FrontendDir 'node_modules'))) {
    & npm.cmd ci --include=optional
    if ($LASTEXITCODE -ne 0) {
      Write-Host 'npm ci failed, falling back to npm install...'
      & npm.cmd install --include=optional
    }
  }
  & npm.cmd run package:win:x64
  if ($LASTEXITCODE -ne 0) { throw 'electron-builder NSIS packaging failed.' }
} finally { Pop-Location }

Write-Host "Installer ready in $FrontendDir\dist_app"
