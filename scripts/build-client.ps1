$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Adapter = Join-Path $Root 'web-ai-adapter'
$Frontend = Join-Path $Root 'frontend'
$Stage = Join-Path $Frontend '.packaging-app'
Push-Location $Adapter
try {
    npm ci --ignore-scripts
    if ($LASTEXITCODE -ne 0) { throw "Web AI dependency restore failed (exit $LASTEXITCODE)" }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "Web AI adapter build failed (exit $LASTEXITCODE)" }
} finally { Pop-Location }
Push-Location $Frontend
try {
    npm install
    if ($LASTEXITCODE -ne 0) { throw "Frontend dependency restore failed (exit $LASTEXITCODE)" }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend production build failed (exit $LASTEXITCODE)" }
    node scripts/enable-nsis-built-in-compressor.cjs
    if ($LASTEXITCODE -ne 0) { throw "NSIS configuration step failed (exit $LASTEXITCODE)" }

    # Package from a narrow staging app so electron-builder never traverses
    # unrelated test caches or historical artifacts in the frontend tree.
    if (Test-Path -LiteralPath $Stage) { Remove-Item -LiteralPath $Stage -Recurse -Force }
    New-Item -ItemType Directory -Path $Stage | Out-Null
    Copy-Item -LiteralPath (Join-Path $Frontend 'dist') -Destination (Join-Path $Stage 'dist') -Recurse
    Copy-Item -LiteralPath (Join-Path $Frontend 'desktop') -Destination (Join-Path $Stage 'desktop') -Recurse
    Copy-Item -LiteralPath (Join-Path $Frontend 'package.json') -Destination (Join-Path $Stage 'package.json')
    node -e "const fs=require('fs');const p=process.argv[1];const x=JSON.parse(fs.readFileSync(p,'utf8'));delete x.build;fs.writeFileSync(p,JSON.stringify(x,null,2),'utf8')" (Join-Path $Stage 'package.json')
    if ($LASTEXITCODE -ne 0) { throw "Packaging manifest preparation failed (exit $LASTEXITCODE)" }
    npx electron-builder --win nsis --config.directories.app=.packaging-app
    if ($LASTEXITCODE -ne 0) { throw "Desktop installer build failed (exit $LASTEXITCODE)" }
    Write-Host "Client installer: $Frontend\release"
} finally { Pop-Location }
