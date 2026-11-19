; Tiny launcher exe: starts a target with the bundled Python (or opens a .bat) without a console.
Unicode true
Name "${APPNAME}"
OutFile "${OUTFILE}"
Icon "${ICON}"
RequestExecutionLevel user
SilentInstall silent
VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${APPNAME}"
VIAddVersionKey "FileDescription" "${APPNAME}"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "CompanyName" "Sasanka Boruah -VU3INI"
VIAddVersionKey "LegalCopyright" "Sasanka Boruah -VU3INI"

Section
  SetOutPath "$EXEDIR"
!if ${WINDOWED} == 1
  IfFileExists "$EXEDIR\python\pythonw.exe" +3
    MessageBox MB_ICONSTOP "The app files are incomplete. Please reinstall ${APPNAME}."
    Quit
  Exec '"$EXEDIR\python\pythonw.exe" "$EXEDIR\${TARGET}"'
!else
  ExecShell "open" "$EXEDIR\${TARGET}"
!endif
SectionEnd
