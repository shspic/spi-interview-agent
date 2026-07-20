Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$backendDir = Split-Path -Parent $PSScriptRoot
$python = Join-Path $backendDir ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Backend virtual environment not found. Create .venv and install requirements.txt."
}

Push-Location $backendDir
try {
    & $python -m scripts.bootstrap_local_env
    if ($LASTEXITCODE -ne 0) { throw "Local environment bootstrap failed." }
    & $python -m scripts.prepare_database
    if ($LASTEXITCODE -ne 0) { throw "Database migration failed." }
    & $python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --no-server-header
    if ($LASTEXITCODE -ne 0) { throw "Backend startup failed." }
}
finally {
    Pop-Location
}
