# Arranca el bot de GeoAid para la demo (Windows PowerShell).
# Uso, desde la carpeta backend:   .\run_demo.ps1
# En OTRA terminal, el túnel:      ngrok http --url=<tu-dominio>.ngrok-free.app 8000
# Si PowerShell bloquea el script: powershell -ExecutionPolicy Bypass -File .\run_demo.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    Write-Host "Creando entorno virtual e instalando dependencias..."
    python -m venv .venv
    .\.venv\Scripts\python -m pip install -r requirements.txt
}

Write-Host "Aplicando migraciones de la base de datos..."
.\.venv\Scripts\alembic upgrade head

New-Item -ItemType Directory -Force logs | Out-Null
$log = "logs\bot-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"
Write-Host "Bot escuchando en http://localhost:8000  (log: $log)"
Write-Host "Ctrl+C para detener."

# uvicorn escribe sus logs por stderr. Se redirige dentro de cmd para que PowerShell 5.1
# no los muestre como errores rojos (NativeCommandError).
$ErrorActionPreference = "Continue"
# Sin --reload: más estable durante el evento.
cmd /c ".venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 2>&1" | Tee-Object -FilePath $log
