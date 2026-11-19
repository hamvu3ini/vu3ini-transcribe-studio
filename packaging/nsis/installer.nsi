; VU3INI Transcribe Studio — per-user installer (no admin rights needed)
Unicode true
!include "MUI2.nsh"
!include "FileFunc.nsh"

Name "${APPNAME} ${VERSION}"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\${APPNAME}"
InstallDirRegKey HKCU "Software\${APPNAME}" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 64
BrandingText "${APPNAME} ${VERSION} - By Sasanka Boruah -VU3INI"
VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${APPNAME}"
VIAddVersionKey "FileDescription" "${APPNAME} Setup"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "CompanyName" "Sasanka Boruah -VU3INI"
VIAddVersionKey "LegalCopyright" "Sasanka Boruah -VU3INI"

!define MUI_ICON "${ICON}"
!define MUI_UNICON "${ICON}"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "Welcome to ${APPNAME} ${VERSION}"
!define MUI_WELCOMEPAGE_TEXT "This installs ${APPNAME} for your Windows account only. No administrator rights and no internet connection are needed.$\r$\n$\r$\nSpeech models are installed afterwards from model pack files (see README_FIRST.txt).$\r$\n$\r$\nBy Sasanka Boruah -VU3INI"
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APPNAME}.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Start ${APPNAME} now"
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\README_FIRST.txt"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "Show README_FIRST.txt"
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${DIST}\TERMS.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\VU3INI-Transcribe-Studio"

; Close any running copy of the app (server, launcher, Make model packs) that lives in $INSTDIR.
; Uses 64-bit PowerShell (Sysnative) and CIM, because a 32-bit process cannot read 64-bit process paths.
!macro StopRunningAppFn PREFIX
Function ${PREFIX}StopRunningApp
  StrCpy $R9 "$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
  IfFileExists "$R9" +2
    StrCpy $R9 "$SYSDIR\WindowsPowerShell\v1.0\powershell.exe"
  StrCpy $R8 `Get-CimInstance Win32_Process | Where-Object { $$_.ExecutablePath -and $$_.ExecutablePath.StartsWith('$INSTDIR\', [StringComparison]::OrdinalIgnoreCase) }`
  nsExec::ExecToStack `"$R9" -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "@($R8).Count"`
  Pop $0
  Pop $1
  IntOp $1 $1 + 0
  IntCmp $1 0 check_files
    IfSilent +3
    MessageBox MB_OKCANCEL|MB_ICONINFORMATION "${APPNAME} is still running (it may be downloading a model pack).$\r$\n$\r$\nSetup will close it now. Click Cancel to stop and close it yourself." IDOK +2
    Abort
    nsExec::ExecToStack `"$R9" -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$R8 | Invoke-CimMethod -MethodName Terminate | Out-Null"`
    Pop $0
    Pop $1
  check_files:
  ; wait until the runtime files can really be replaced (up to ~15 s)
  StrCpy $R7 0
  loop:
    IfFileExists "$INSTDIR\python\python312.dll" 0 done
    Delete "$INSTDIR\python\python312.dll"
    Delete "$INSTDIR\python\libssl-3-x64.dll"
    IfFileExists "$INSTDIR\python\python312.dll" 0 done
    IntOp $R7 $R7 + 1
    IntCmp $R7 30 locked
    Sleep 500
    Goto loop
  locked:
    IfSilent +3
    MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "Some files of ${APPNAME} are still in use.$\r$\n$\r$\nRight-click the VU3INI icon near the clock and choose Stop / Exit or end pythonw.exe and python.exe in Task Manager. Then click Retry." IDRETRY check_files
    Abort
  done:
FunctionEnd
!macroend
!insertmacro StopRunningAppFn ""
!insertmacro StopRunningAppFn "un."

Section "Install"
  SetShellVarContext current
  Call StopRunningApp
  ; remove files of an older version so nothing stale is left behind
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\python"
  RMDir /r "$INSTDIR\ffmpeg"
  RMDir /r "$INSTDIR\licences"
  SetOutPath "$INSTDIR"
  File /r "${DIST}\*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" "$INSTDIR\${APPNAME}.exe" "" "$INSTDIR\app.ico" 0
  ; older versions had a separate pack maker; it now lives inside the app
  Delete "$SMPROGRAMS\${APPNAME}\Make model packs.lnk"
  Delete "$INSTDIR\Make model packs.exe"
  Delete "$INSTDIR\Make-Packs.bat"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\README_FIRST.lnk" "$INSTDIR\README_FIRST.txt"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\Uninstall ${APPNAME}.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortCut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\${APPNAME}.exe" "" "$INSTDIR\app.ico" 0

  WriteRegStr HKCU "Software\${APPNAME}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "Sasanka Boruah -VU3INI"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\app.ico"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegStr HKCU "${UNINST_KEY}" "HelpLink" "mailto:hamvu3ini@gmail.com"
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${UNINST_KEY}" "EstimatedSize" "$0"
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  Call un.StopRunningApp
  Delete "$DESKTOP\${APPNAME}.lnk"
  RMDir /r "$SMPROGRAMS\${APPNAME}"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "${UNINST_KEY}"
  DeleteRegKey HKCU "Software\${APPNAME}"
  IfSilent done
  MessageBox MB_YESNO|MB_ICONQUESTION "Also delete your projects, settings and installed model packs?$\r$\n($LOCALAPPDATA\${APPNAME})$\r$\n$\r$\nChoose No to keep them for a future installation." IDNO done
  RMDir /r "$LOCALAPPDATA\${APPNAME}"
  done:
SectionEnd
