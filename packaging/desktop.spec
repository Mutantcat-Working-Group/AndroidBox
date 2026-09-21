# Build on each target OS: python -m PyInstaller packaging/desktop.spec --noconfirm
import os
import platform
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


root = Path(SPECPATH).parent
sys.path.insert(0, str(root))
from scripts.release_metadata import validate_versions, windows_version
from scripts.runtime_payload import collect_qemu, collect_adb

version = validate_versions(root)
version_resource = None
if sys.platform == "win32":
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable,
        VarFileInfo, VarStruct, VSVersionInfo,
    )
    version_resource = VSVersionInfo(
        ffi=FixedFileInfo(filevers=windows_version(version), prodvers=windows_version(version),
                          mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
        kids=[StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "Mutantcat"),
            StringStruct("FileDescription", "AndroidBox"),
            StringStruct("FileVersion", version),
            StringStruct("ProductName", "AndroidBox"),
            StringStruct("ProductVersion", version),
            StringStruct("OriginalFilename", "AndroidBox.exe"),
        ])]), VarFileInfo([VarStruct("Translation", [1033, 1200])])],
    )
if not (root / "androidbox/web/novnc/core/rfb.js").is_file():
    raise SystemExit("Run python scripts/fetch_novnc.py before building the desktop application")

runtime_binaries, runtime_data = [], []
if os.environ.get("ANDROIDBOX_QEMU_PREFIX"):
    runtime_arch = {"arm64": "aarch64", "amd64": "x86_64"}.get(platform.machine().lower(), platform.machine().lower())
    runtime_binaries, runtime_data = collect_qemu(os.environ["ANDROIDBOX_QEMU_PREFIX"], runtime_arch)
if os.environ.get("ANDROIDBOX_ADB_DIRECTORY"):
    adb_binaries, adb_data = collect_adb(os.environ["ANDROIDBOX_ADB_DIRECTORY"])
    runtime_binaries += adb_binaries
    runtime_data += adb_data

analysis = Analysis(
    [str(root / "scripts/desktop_entry.py")],
    pathex=[str(root)],
    binaries=runtime_binaries,
    # certifi ships the CA bundle the guest disk download verifies against: the
    # QEMU payload pulls in an OpenSSL whose compiled-in CA directory does not
    # exist on the user's machine.
    datas=collect_data_files("androidbox") + collect_data_files("certifi")
    + [(str(root / "LICENSE"), "licenses/androidbox")] + runtime_data,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tools", "tkinter"],
    noarchive=False,
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="AndroidBox",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    version=version_resource,
    icon=str(root / "packaging/icons/AndroidBox.ico") if sys.platform == "win32" else None,
)
distribution = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="AndroidBox",
)
if sys.platform == "darwin":
    application = BUNDLE(
        distribution,
        name="AndroidBox.app",
        icon=str(root / "packaging/icons/AndroidBox.icns"),
        bundle_identifier="org.mutantcat.androidbox",
        version=version,
        info_plist={"NSHighResolutionCapable": True,
                    "CFBundleShortVersionString": version,
                    "CFBundleVersion": ".".join(str(int(part)) for part in
                                               (version[-8:-4], version[-4:-2], version[-2:]))},
    )
