$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'build-server.ps1')
& (Join-Path $PSScriptRoot 'build-client.ps1')
