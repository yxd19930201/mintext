$ErrorActionPreference = 'Stop'
$Frontend = Join-Path (Split-Path -Parent $PSScriptRoot) 'frontend'
Push-Location $Frontend
try {
    npm install
    npm run desktop:dist
    Write-Host "Client installer: $Frontend\release"
} finally { Pop-Location }
