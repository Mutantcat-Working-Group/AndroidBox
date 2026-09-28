Unicode true
!include "MUI2.nsh"
!include "x64.nsh"
!include "LogicLib.nsh"

!ifndef VERSION
  !error "VERSION is required"
!endif
!ifndef APP_NAME
  !define APP_NAME "AndroidBox"
!endif
!ifndef APP_PUBLISHER
  !define APP_PUBLISHER "Mutantcat Working Group"
!endif
Name "${APP_NAME} ${VERSION}"
OutFile "${OUTPUT}"
InstallDir "$PROGRAMFILES\${APP_NAME}"
InstallDirRegKey HKLM "Software\Mutantcat\AndroidBox" "InstallDir"
RequestExecutionLevel admin
SetCompressor /SOLID lzma
VIProductVersion "${NUMERIC_VERSION}"
VIAddVersionKey /LANG=1033 "ProductName" "AndroidBox"
VIAddVersionKey /LANG=1033 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=1033 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=1033 "FileDescription" "AndroidBox Installer"
VIAddVersionKey /LANG=1033 "LegalCopyright" "AndroidBox contributors; GPL-3.0-or-later"
BrandingText "${APP_NAME} v${VERSION} - ${APP_PUBLISHER}"

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
!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"
; The toolkit translates its own strings once SimpChinese leads, but the two
; dialogs above are ours, so they carry a translation of their own.
LangString ARCH_UNSUPPORTED ${LANG_SIMPCHINESE} "${APP_NAME} 需要 64 位 Windows。"
LangString ARCH_UNSUPPORTED ${LANG_ENGLISH} "${APP_NAME} requires 64-bit Windows."
LangString INSTALL_BLOCKED ${LANG_SIMPCHINESE} "无法安装 ${APP_NAME}。请关闭正在运行的 ${APP_NAME} 窗口后重试。"
LangString INSTALL_BLOCKED ${LANG_ENGLISH} "Could not install ${APP_NAME}. Close any running ${APP_NAME} window and retry."
LangString IMAGE_INSTALL_BLOCKED ${LANG_SIMPCHINESE} "无法安装内置的 Android 系统镜像。请清理磁盘空间后重试。"
LangString IMAGE_INSTALL_BLOCKED ${LANG_ENGLISH} "Could not install the bundled Android system image. Free some disk space and retry."

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "$(ARCH_UNSUPPORTED)"
    Abort
  ${EndIf}
  SetRegView 64
  SetShellVarContext all
FunctionEnd

Section "${APP_NAME}" SEC_MAIN
  SetOutPath "$INSTDIR"
  ClearErrors
  File /r "${PAYLOAD}\*"
  ${If} ${Errors}
    MessageBox MB_ICONSTOP "$(INSTALL_BLOCKED)"
    Abort
  ${EndIf}
!ifdef IMAGES_PKG
  ; The Android system image rides appended to this installer; place it where
  ; the client looks for it and expands it on first boot.
  CreateDirectory "$INSTDIR\_internal\runtime\images\x86_64"
  ClearErrors
  CopyFiles /SILENT "$EXEPATH" "$INSTDIR\_internal\runtime\images\x86_64\androidbox-images.pkg"
  ${If} ${Errors}
    MessageBox MB_ICONSTOP "$(IMAGE_INSTALL_BLOCKED)"
    Abort
  ${EndIf}
!endif
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\AndroidBox"
  CreateShortcut "$SMPROGRAMS\AndroidBox\AndroidBox.lnk" "$INSTDIR\AndroidBox.exe"
  CreateShortcut "$SMPROGRAMS\AndroidBox\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortcut "$DESKTOP\AndroidBox.lnk" "$INSTDIR\AndroidBox.exe"
  WriteRegStr HKLM "Software\Mutantcat\AndroidBox" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\AndroidBox" "DisplayName" "${APP_NAME}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\AndroidBox" "DisplayVersion" "${VERSION}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\AndroidBox" "Publisher" "${APP_PUBLISHER}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\AndroidBox" "DisplayIcon" "$INSTDIR\AndroidBox.exe"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\AndroidBox" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\AndroidBox" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\AndroidBox" "NoModify" 1
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\AndroidBox" "NoRepair" 1
SectionEnd

Section "Uninstall"
  SetRegView 64
  SetShellVarContext all
  Delete "$DESKTOP\AndroidBox.lnk"
  Delete "$SMPROGRAMS\AndroidBox\AndroidBox.lnk"
  Delete "$SMPROGRAMS\AndroidBox\Uninstall.lnk"
  RMDir "$SMPROGRAMS\AndroidBox"
  ; Remove only installer-owned paths; keep guest disks and user settings.
  RMDir /r "$INSTDIR\_internal"
  Delete "$INSTDIR\AndroidBox.exe"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKLM "Software\Mutantcat\AndroidBox"
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\AndroidBox"
SectionEnd
