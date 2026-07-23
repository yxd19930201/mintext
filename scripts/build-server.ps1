$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root 'backend'
Push-Location $Backend
try {
    python -m pip install -r requirements-build.txt
    python -m PyInstaller --noconfirm --clean --onefile --name mintext-server `
        --collect-all uvicorn --collect-all sqlalchemy --collect-all aiosqlite --collect-all passlib `
        --hidden-import app.models.user --hidden-import app.models.project `
        --hidden-import app.models.episode --hidden-import app.models.script `
        --hidden-import app.models.novel --hidden-import app.models.chapter `
        --hidden-import app.models.chapter_content --hidden-import app.models.ai_config `
        --hidden-import app.models.ai_prompt_preset server.py
    Write-Host "Server package: $Backend\dist\mintext-server.exe"
} finally { Pop-Location }
