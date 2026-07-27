!macro customInit
  nsExec::ExecToLog 'taskkill /F /T /IM "Mintext.exe"'
  nsExec::ExecToLog 'taskkill /F /T /IM "MintextApp.exe"'
  nsExec::ExecToLog 'taskkill /F /T /IM "mintext-server.exe"'
  Sleep 3000
!macroend

!macro customInstall
  Delete "$INSTDIR\d3dcompiler_47.dll"
  Rename "$INSTDIR\d3dcompiler_47.dll.install" "$INSTDIR\d3dcompiler_47.dll"
  Delete "$INSTDIR\ffmpeg.dll"
  Rename "$INSTDIR\ffmpeg.dll.install" "$INSTDIR\ffmpeg.dll"
  Delete "$INSTDIR\libEGL.dll"
  Rename "$INSTDIR\libEGL.dll.install" "$INSTDIR\libEGL.dll"
  Delete "$INSTDIR\libGLESv2.dll"
  Rename "$INSTDIR\libGLESv2.dll.install" "$INSTDIR\libGLESv2.dll"
  Delete "$INSTDIR\vk_swiftshader.dll"
  Rename "$INSTDIR\vk_swiftshader.dll.install" "$INSTDIR\vk_swiftshader.dll"
  Delete "$INSTDIR\vulkan-1.dll"
  Rename "$INSTDIR\vulkan-1.dll.install" "$INSTDIR\vulkan-1.dll"
  Delete "$INSTDIR\MintextApp.exe"
  Rename "$INSTDIR\MintextApp.exe.install" "$INSTDIR\MintextApp.exe"
  Delete "$INSTDIR\resources\server\mintext-server.exe"
  Rename "$INSTDIR\resources\server\mintext-server.exe.install" "$INSTDIR\resources\server\mintext-server.exe"

  File /oname=$PLUGINSDIR\create-shortcuts.ps1 "${BUILD_RESOURCES_DIR}\create-shortcuts.ps1"
  nsExec::ExecToLog '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\create-shortcuts.ps1" -InstallDir "$INSTDIR"'
  Pop $R0
  ${if} $R0 != 0
    MessageBox MB_OK|MB_ICONSTOP "Installation failed: application files could not be finalized."
    Abort
  ${endIf}

  IfFileExists "$INSTDIR\MintextApp.exe" app_files_ready
    MessageBox MB_OK|MB_ICONSTOP "Installation failed: MintextApp.exe was not written correctly. Please close Mintext and run the installer again."
    Abort

  app_files_ready:
  IfFileExists "$INSTDIR\d3dcompiler_47.dll" d3d_ready
    MessageBox MB_OK|MB_ICONSTOP "Installation failed: d3dcompiler_47.dll was not finalized."
    Abort

  d3d_ready:
  IfFileExists "$INSTDIR\resources\server\mintext-server.exe" server_ready
    MessageBox MB_OK|MB_ICONSTOP "Installation failed: mintext-server.exe was not finalized."
    Abort

  server_ready:
!macroend

!macro customUnInstall
  SetShellVarContext all
  Delete "$DESKTOP\Mintext.lnk"
  Delete "$SMPROGRAMS\Mintext\Mintext.lnk"
  RMDir "$SMPROGRAMS\Mintext"
!macroend
