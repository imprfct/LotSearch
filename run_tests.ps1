# Test runner script for Windows PowerShell

Write-Host "=== LotSearch Bot Tests ===" -ForegroundColor Cyan
Write-Host ""

# Check if pytest is installed
$pytestInstalled = python -m pytest --version 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing test dependencies..." -ForegroundColor Yellow
    pip install -r requirements.txt
    Write-Host ""
}

# Run tests based on argument
$testType = $args[0]

switch ($testType) {
    "fast" {
        Write-Host "Running fast tests (without integration)..." -ForegroundColor Green
        python -m pytest -v -m "not integration"
    }
    "integration" {
        Write-Host "Running integration tests (real website check)..." -ForegroundColor Green
        python -m pytest -v -m integration
    }
    "cov" {
        Write-Host "Running tests with coverage..." -ForegroundColor Green
        python -m pytest --cov=. --cov-report=html --cov-report=term
        Write-Host ""
        Write-Host "Coverage report saved to htmlcov/index.html" -ForegroundColor Cyan
    }
    default {
        Write-Host "Running all tests..." -ForegroundColor Green
        python -m pytest -v
    }
}

Write-Host ""
Write-Host "Done!" -ForegroundColor Cyan
