!macro customInstall
  CreateShortCut "$DESKTOP\Mintext.lnk" "$INSTDIR\Mintext.exe" "" "$INSTDIR\Mintext.exe" 0
!macroend

!macro customUnInstall
  Delete "$DESKTOP\Mintext.lnk"
!macroend
