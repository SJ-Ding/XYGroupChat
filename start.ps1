param([int]$Port = 8000, [string]$Bind = "127.0.0.1", [switch]$Demo)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        uv --cache-dir .cache venv .venv --python 3.12
    } else {
        python -c "import sys; assert sys.version_info >= (3, 10), 'Python 3.10+ required'"
        if ($LASTEXITCODE -ne 0) { throw "Please install Python 3.12 or uv." }
        python -m venv .venv
    }
    if ($LASTEXITCODE -ne 0) { throw "Python 3.10+ is required." }
}
if (Get-Command uv -ErrorAction SilentlyContinue) {
    uv --cache-dir .cache pip install --python .venv\Scripts\python.exe -r requirements-lock.txt
} else {
    & .\.venv\Scripts\python.exe -m ensurepip
    & .\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
}
if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed." }
if (-not (Test-Path -LiteralPath ".env")) { Copy-Item -LiteralPath ".env.example" -Destination ".env" }
Push-Location frontend
try {
    npm ci --cache .npm-cache
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed." }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
} finally { Pop-Location }
Push-Location hospital
try {
    npm ci --cache .npm-cache
    if ($LASTEXITCODE -ne 0) { throw "Hospital npm ci failed." }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "Hospital frontend build failed." }
} finally { Pop-Location }
if ($Demo) { & .\.venv\Scripts\python.exe -m backend.demo }
$env:HOSPITAL_BASE = "http://127.0.0.1:$Port/hospital/"
Write-Host "Xiaoyi: http://localhost:$Port (dad / mom / child)"
Write-Host "Hospital simulator: http://localhost:$Port/hospital/"
& .\.venv\Scripts\python.exe -m uvicorn backend.app:app --host $Bind --port $Port
