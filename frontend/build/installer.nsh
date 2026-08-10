!macro preInit
  ; electron-builder resolves InstallLocation before customInit. Seed both
  ; registry views and both install modes early enough for the directory page.
  IfFileExists "D:\*.*" 0 preinit_done
    SetRegView 64
    WriteRegExpandStr HKCU "${INSTALL_REGISTRY_KEY}" InstallLocation "D:\minitext\Mintext\MintextApp"
    WriteRegExpandStr HKLM "${INSTALL_REGISTRY_KEY}" InstallLocation "D:\minitext\Mintext\MintextApp"
    SetRegView 32
    WriteRegExpandStr HKCU "${INSTALL_REGISTRY_KEY}" InstallLocation "D:\minitext\Mintext\MintextApp"
    WriteRegExpandStr HKLM "${INSTALL_REGISTRY_KEY}" InstallLocation "D:\minitext\Mintext\MintextApp"
  preinit_done:
!macroend

; The assisted installer chooses the per-user/per-machine mode after .onInit.
; Set the per-user default in that exact hook so setInstallModePerUser cannot
; restore an obsolete C: smoke-test path from the registry afterwards.
!macro customInstallMode
  IfFileExists "D:\*.*" 0 custom_install_mode_done
    StrCpy $isForceCurrentInstall "1"
    StrCpy $perUserInstallationFolder "D:\minitext\Mintext\MintextApp"
    WriteRegExpandStr HKCU "${INSTALL_REGISTRY_KEY}" InstallLocation "D:\minitext\Mintext\MintextApp"
    ; An old electron-builder upgrade may relaunch this installer with the
    ; previous temporary folder encoded as /D. Remove that stale override;
    ; the directory page remains available for an explicit new user choice.
    StrCpy $CMDLINE ""
  custom_install_mode_done:
!macroend

!macro customInit
  nsExec::ExecToLog 'taskkill /F /T /IM "Mintext.exe"'
  nsExec::ExecToLog 'taskkill /F /T /IM "MintextApp.exe"'
  nsExec::ExecToLog 'taskkill /F /T /IM "MintextDesktop.exe"'
  nsExec::ExecToLog 'taskkill /F /T /IM "mintext-server.exe"'
  Sleep 3000

  ; The established product default is always D: when that drive exists.
  ; Never inherit stale smoke-test or accidental nested paths from registry.
  IfFileExists "D:\*.*" 0 install_dir_ready
    StrCpy $INSTDIR "D:\minitext\Mintext\MintextApp"
  install_dir_ready:
!macroend

; electron-builder's default check matches every process below $INSTDIR. During
; assisted upgrades $INSTDIR can briefly be empty or stale, producing a false
; "Mintext cannot be closed" loop. Only terminate the product's exact process
; names; the installer itself has a different executable name.
!macro customCheckAppRunning
  nsExec::ExecToLog 'taskkill /F /T /IM "Mintext.exe"'
  nsExec::ExecToLog 'taskkill /F /T /IM "MintextApp.exe"'
  nsExec::ExecToLog 'taskkill /F /T /IM "MintextDesktop.exe"'
  nsExec::ExecToLog 'taskkill /F /T /IM "mintext-server.exe"'
  Sleep 2000
!macroend

!macro customInstall
  ; This is the final hook before payload extraction. electron-builder may
  ; have restored a stale InstallLocation after preInit/customInit, so enforce
  ; the established D: default one last time here.
  IfFileExists "D:\*.*" 0 custom_install_dir_ready
    StrCpy $INSTDIR "D:\minitext\Mintext\MintextApp"
  custom_install_dir_ready:
  ; Remove shortcuts left by older builds (including a historical mojibake
  ; shortcut name). The helper below recreates one canonical shortcut.
  SetShellVarContext current
  Delete "$DESKTOP\Mintext*.lnk"
  Delete "$SMPROGRAMS\Mintext*.lnk"
  ; customInstall runs after application extraction. Create links synchronously
  ; so an upgrade cannot delete them while a detached helper is still waiting.
  SetOutPath "$TEMP"
  File /oname=create-mintext-shortcuts.ps1 "${BUILD_RESOURCES_DIR}\create-shortcuts.ps1"
  ExecWait '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "$TEMP\create-mintext-shortcuts.ps1" -InstallDir "$INSTDIR"' $0
  SetOutPath "$INSTDIR"
!macroend

!macro customUnInstall
  SetShellVarContext current
  Delete "$DESKTOP\Mintext*.lnk"
  Delete "$SMPROGRAMS\Mintext*.lnk"
  Delete "$DESKTOP\Mintext.lnk"
  Delete "$DESKTOP\Mintext创作工具.lnk"
  Delete "$SMPROGRAMS\Mintext\Mintext.lnk"
  Delete "$SMPROGRAMS\Mintext创作工具.lnk"
  Delete "$SMPROGRAMS\Mintext.lnk"
  RMDir "$SMPROGRAMS\Mintext"
!macroend
