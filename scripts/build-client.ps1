$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Adapter = Join-Path $Root 'web-ai-adapter'
$Frontend = Join-Path $Root 'frontend'
Push-Location $Adapter
try {
    npm ci --ignore-scripts
    npm run build
} finally { Pop-Location }
Push-Location $Frontend
try {
    npm install
    npm run desktop:dist
    Write-Host "Client installer: $Frontend\release"
} finally { Pop-Location }
