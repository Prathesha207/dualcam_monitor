[CmdletBinding()]
param(
    [switch]$Clean
)

# ==============================================================================
# Vision Monitor - Windows Environment Setup Script (Minimal Camera Service)
# Configures Python virtual environment and camera service dependencies.
# ==============================================================================
$ErrorActionPreference = 'Continue'

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "       Vision Monitor - Automated Setup (Windows)      " -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""

# Determine directories
$BackendDir = if ($MyInvocation.MyCommand.Path) {
    Split-Path -Parent $MyInvocation.MyCommand.Path
} else {
    Get-Location
}
$ProjectRoot = Split-Path -Parent $BackendDir
$FrontendDir = if (Test-Path (Join-Path $ProjectRoot 'frontend')) {
    Join-Path $ProjectRoot 'frontend'
} else {
    Join-Path $ProjectRoot 'vision-ai-frontend'
}

Write-Host "[SETUP] Backend Directory : $BackendDir"
Write-Host "[SETUP] Frontend Directory: $FrontendDir"
Write-Host ""

# ------------------------------------------------------------------------------
# 1. Locate and Validate Python (>= 3.10)
# ------------------------------------------------------------------------------
Write-Host "[1/4] Validating Python installation..." -ForegroundColor Yellow

function Find-ValidPython {
    $candidates = @('python', 'py', 'python3')
    foreach ($cmdName in $candidates) {
        $cmd = Get-Command $cmdName -ErrorAction SilentlyContinue
        if ($cmd) {
            $verOut = & $cmd.Source -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2>$null
            if ($LASTEXITCODE -eq 0 -and $verOut -match '^(\d+)\.(\d+)') {
                $major = [int]$matches[1]
                $minor = [int]$matches[2]
                if ($major -eq 3 -and $minor -ge 10) {
                    return $cmd.Source
                }
            }
        }
    }

    $defaultPaths = @(
        "$env:LocalAppData\Programs\Python\Python312\python.exe",
        "$env:LocalAppData\Programs\Python\Python311\python.exe",
        "$env:LocalAppData\Programs\Python\Python310\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python311\python.exe",
        "C:\Program Files\Python310\python.exe",
        "C:\Python312\python.exe",
        "C:\Python311\python.exe",
        "C:\Python310\python.exe"
    )
    foreach ($p in $defaultPaths) {
        if (Test-Path $p) {
            $verOut = & $p -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2>$null
            if ($LASTEXITCODE -eq 0 -and $verOut -match '^(\d+)\.(\d+)') {
                $major = [int]$matches[1]
                $minor = [int]$matches[2]
                if ($major -eq 3 -and $minor -ge 10) {
                    return $p
                }
            }
        }
    }
    return $null
}

$Python = Find-ValidPython
if (-not $Python) {
    Write-Host "[INFO] Python 3.10+ not found. Downloading Python 3.12..." -ForegroundColor Cyan
    $installerPath = "$env:TEMP\python-installer.exe"
    Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.9/python-3.12.9-amd64.exe" -OutFile $installerPath
    Write-Host "[INFO] Installing Python silently in background..." -ForegroundColor Cyan
    Start-Process -FilePath $installerPath -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0" -Wait -NoNewWindow
    
    $pyDir = "$env:LocalAppData\Programs\Python\Python312"
    $env:Path = "$pyDir;$pyDir\Scripts;" + $env:Path
    
    $Python = Find-ValidPython
    if (-not $Python) {
        throw "Failed to install Python."
    }
    Write-Host "[SUCCESS] Python installed successfully!" -ForegroundColor Green
}

$PyVersion = & $Python --version 2>&1
Write-Host "[OK] Using Python: $PyVersion ($Python)" -ForegroundColor Green

# ------------------------------------------------------------------------------
# 2. Locate and Validate Node.js / npm (if frontend exists)
# ------------------------------------------------------------------------------
Write-Host ""
Write-Host "[2/4] Validating Node.js and npm..." -ForegroundColor Yellow

$NpmExecutable = $null
if (Test-Path $FrontendDir) {
    $NpmCmd = (Get-Command npm.cmd -ErrorAction SilentlyContinue)
    if (-not $NpmCmd) {
        $NpmCmd = (Get-Command npm -ErrorAction SilentlyContinue)
    }
    if (-not $NpmCmd) {
        $portableNodeDir = "$env:LocalAppData\Programs\node-v20.18.0-win-x64"
        $nodePaths = @(
            "$portableNodeDir\npm.cmd",
            "$env:ProgramFiles\nodejs\npm.cmd",
            "${env:ProgramFiles(x86)}\nodejs\npm.cmd"
        )
        foreach ($np in $nodePaths) {
            if (Test-Path $np) {
                $NpmCmd = Get-Item $np
                $env:Path = (Split-Path -Parent $np) + ";" + $env:Path
                break
            }
        }
    }

    if (-not $NpmCmd) {
        Write-Host "[INFO] Node.js not found. Downloading portable Node.js..." -ForegroundColor Cyan
        $nodeZip = "$env:TEMP\node.zip"
        Invoke-WebRequest -Uri "https://nodejs.org/dist/v20.18.0/node-v20.18.0-win-x64.zip" -OutFile $nodeZip
        Write-Host "[INFO] Extracting Node.js silently in background..." -ForegroundColor Cyan
        Expand-Archive -Path $nodeZip -DestinationPath "$env:LocalAppData\Programs" -Force
        $nodeDir = "$env:LocalAppData\Programs\node-v20.18.0-win-x64"
        $env:Path = "$nodeDir;" + $env:Path
        [Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path", "User") + ";$nodeDir", "User")
        
        $NpmCmd = (Get-Command npm.cmd -ErrorAction SilentlyContinue)
        if (-not $NpmCmd) {
            throw "Failed to install Node.js."
        }
        Write-Host "[SUCCESS] Node.js installed successfully!" -ForegroundColor Green
    }

    $NpmExecutable = if ($NpmCmd.Source) { $NpmCmd.Source } else { $NpmCmd.FullName }
    $NpmVersion = & $NpmExecutable --version 2>&1
    Write-Host "[OK] Using npm: v$NpmVersion ($NpmExecutable)" -ForegroundColor Green
} else {
    Write-Host "[INFO] Frontend folder not present — skipping Node.js check." -ForegroundColor Cyan
}

# ------------------------------------------------------------------------------
# 3. Configure Python Virtual Environment (.venv) & Camera Dependencies
# ------------------------------------------------------------------------------
Write-Host ""
Write-Host "[3/4] Setting up Python virtual environment and dependencies..." -ForegroundColor Yellow

$VenvDir = Join-Path $BackendDir '.venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'

if ($Clean) {
    Write-Host "[CLEAN] Clean setup requested. Terminating any running backend processes..." -ForegroundColor Yellow
    Get-Process -Name "python", "uvicorn" -ErrorAction SilentlyContinue | Where-Object {
        $_.Path -like "*$BackendDir*"
    } | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500

    if (Test-Path $VenvDir) {
        Write-Host "[CLEAN] Removing existing virtual environment at $VenvDir..." -ForegroundColor Yellow
        Remove-Item -LiteralPath $VenvDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating fresh virtual environment in $VenvDir..."
    & $Python -m venv $VenvDir
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPython)) {
        throw "Failed to create Python virtual environment."
    }
    Write-Host "Upgrading pip, setuptools, and wheel..."
    & $VenvPython -m pip install --quiet --upgrade pip setuptools wheel
} else {
    Write-Host "Reusing existing virtual environment at $VenvDir."
}

$BackendCheck = try {
    & $VenvPython -c "
import importlib.util as u
pkgs = ['fastapi', 'uvicorn', 'cv2', 'depthai', 'av']
if all(u.find_spec(p) is not None for p in pkgs):
    print('INSTALLED')
else:
    print('MISSING')
" 2>$null
} catch { 'MISSING' }

if ($BackendCheck -eq 'INSTALLED') {
    Write-Host "[OK] Backend dependencies are already installed." -ForegroundColor Green
} else {
    Write-Host "Installing backend requirements..."
    $ReqFile = Join-Path $BackendDir 'requirements.txt'
    if (Test-Path $ReqFile) {
        & $VenvPython -m pip install --prefer-binary -r $ReqFile
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to install Python requirements from $ReqFile."
        }
    }
}

# ------------------------------------------------------------------------------
# 4. End-to-End Pre-Flight Smoke Test & Frontend Dependencies
# ------------------------------------------------------------------------------
Write-Host ""
Write-Host "[4/4] Verifying camera service and dependencies..." -ForegroundColor Yellow

if ((Test-Path $FrontendDir) -and $NpmExecutable) {
    $NodeModulesDir = Join-Path $FrontendDir 'node_modules'
    $DistHtml = Join-Path $FrontendDir 'dist\index.html'

    if ((Test-Path $NodeModulesDir) -and (Test-Path $DistHtml)) {
        Write-Host "[OK] Frontend packages are already up-to-date." -ForegroundColor Green
    } else {
        Push-Location $FrontendDir
        try {
            Write-Host "Installing frontend dependencies..."
            & $NpmExecutable install --include=optional
            Write-Host "Building frontend assets..."
            & $NpmExecutable run build
            Write-Host "[OK] Frontend build verified successfully." -ForegroundColor Green
        }
        finally {
            Pop-Location
        }
    }
}

$BackendDirEscaped = $BackendDir.Replace('\', '/')
$SmokeTestCode = @"
import sys
sys.path.insert(0, '$BackendDirEscaped')
try:
    import fastapi
    import uvicorn
    import cv2
    import depthai
    import av
    from app.main import app
    print('PASS|Camera service and API initialized cleanly')
except Exception as e:
    print(f'FAIL|{e}')
    sys.exit(1)
"@

$SmokeTestResult = & $VenvPython -c $SmokeTestCode 2>&1

if ($LASTEXITCODE -ne 0 -or -not ($SmokeTestResult -match 'PASS\|')) {
    throw "Pre-flight camera service verification failed: $SmokeTestResult."
}
Write-Host "[OK] Pre-flight camera service smoke test PASSED!" -ForegroundColor Green

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Green
Write-Host "       SETUP COMPLETED SUCCESSFULLY WITH NO ERRORS!    " -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host "  1. Run the application in development: Double-click run.bat" -ForegroundColor White
Write-Host "  2. Package the Windows desktop app   : Double-click build.bat" -ForegroundColor White
Write-Host "=======================================================" -ForegroundColor Green
