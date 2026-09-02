# Запуск приложения учёта в виртуальном окружении (PowerShell).
# Использование:
#   .\run.ps1          - обычный запуск
#   .\run.ps1 --dev    - режим отладки Flask

Set-Location -Path $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Создаю виртуальное окружение .venv ..."
    python -m venv .venv
    & $python -m pip install --upgrade pip
    & $python -m pip install -r requirements.txt
}

Write-Host "Запуск приложения на http://127.0.0.1:5000"
& $python app.py @args
