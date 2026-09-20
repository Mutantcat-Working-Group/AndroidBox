Unicode true
!include "MUI2.nsh"
!include "x64.nsh"
!include "LogicLib.nsh"

!ifndef VERSION
  !error "VERSION is required"
!endif
Name "AndroidBox ${VERSION}"
OutFile "${OUTPUT}"
InstallDir "$LOCALAPPDATA\Programs\AndroidBox"
InstallDirRegKey HKCU "Software\Mutantcat\AndroidBox" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
VIProductVersion "${NUMERIC_VERSION}"
VIAddVersionKey /LANG=1033 "ProductName" "AndroidBox"
VIAddVersionKey /LANG=1033 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=1033 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=1033 "FileDescription" "AndroidBox Installer"
VIAddVersionKey /LANG=1033 "LegalCopyright" "AndroidBox contributors; GPL-3.0-or-later"

!define MUI_ABORTWARNING
!define MUI_ICON "${ICON_FILE}"
!define MUI_UNICON "${ICON_FILE}"
!define MUI_FINISHPAGE_RUN "$INSTDIR\AndroidBox.exe"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${LICENSE_FILE}"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "AndroidBox requires 64-bit Windows."
    Abort
  ${EndIf}
  SetRegView 64
FunctionEnd

Section "AndroidBox" SEC_MAIN
  SetShellVarContext current
  SetOutPath "$INSTDIR"
  ClearErrors
  File /r "${PAYLOAD}\*"
  ${If} ${Errors}
    MessageBox MB_ICONSTOP "Could not install AndroidBox. Close any running AndroidBox window and retry."
    Abort
  ${EndIf}
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\AndroidBox"
  CreateShortcut "$SMPROGRAMS\AndroidBox\AndroidBox.lnk" "$INSTDIR\AndroidBox.exe"
  CreateShortcut "$SMPROGRAMS\AndroidBox\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortcut "$DESKTOP\AndroidBox.lnk" "$INSTDIR\AndroidBox.exe"
  WriteRegStr HKCU "Software\Mutantcat\AndroidBox" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AndroidBox" "DisplayName" "AndroidBox"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AndroidBox" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AndroidBox" "Publisher" "Mutantcat"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AndroidBox" "DisplayIcon" "$INSTDIR\AndroidBox.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AndroidBox" "UninstallString" '$"$INSTDIR\Uninstall.exe$"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AndroidBox" "QuietUninstallString" '$"$INSTDIR\Uninstall.exe$" /S'
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AndroidBox" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AndroidBox" "NoRepair" 1
SectionEnd

Section "Uninstall"
  SetRegView 64
  SetShellVarContext current
  Delete "$DESKTOP\AndroidBox.lnk"
  Delete "$SMPROGRAMS\AndroidBox\AndroidBox.lnk"
  Delete "$SMPROGRAMS\AndroidBox\Uninstall.lnk"
  RMDir "$SMPROGRAMS\AndroidBox"
  ; Remove only installer-owned paths; keep guest disks and user settings.
  RMDir /r "$INSTDIR\_internal"
  Delete "$INSTDIR\AndroidBox.exe"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "Software\Mutantcat\AndroidBox"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AndroidBox"
SectionEnd
