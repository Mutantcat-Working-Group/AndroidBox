import configparser
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
APP_ID = "org.mutantcat.androidbox"


class BrandingTests(unittest.TestCase):
    def test_native_icon_assets(self):
        icons = ROOT / "packaging/icons"
        self.assertEqual((icons / "AndroidBox.ico").read_bytes()[:4], b"\x00\x00\x01\x00")
        self.assertEqual((icons / "AndroidBox.icns").read_bytes()[:4], b"icns")
        self.assertEqual((ROOT / "data/AppIcon.png").read_bytes(),
                         (ROOT / "androidbox/assets/AppIcon.png").read_bytes())

    def test_packagers_use_product_icon(self):
        spec = (ROOT / "packaging/desktop.spec").read_text()
        self.assertIn('icon=str(root / "packaging/icons/AndroidBox.ico")', spec)
        self.assertIn('icon=str(root / "packaging/icons/AndroidBox.icns")', spec)
        installer = (ROOT / "packaging/windows.nsi").read_text()
        self.assertIn('!define MUI_ICON "${ICON_FILE}"', installer)
        self.assertIn('!define MUI_UNICON "${ICON_FILE}"', installer)
        self.assertIn('/DICON_FILE=', (ROOT / "scripts/package_desktop.py").read_text())

    def test_desktop_identity(self):
        path = ROOT / "data" / f"{APP_ID}.desktop"
        self.assertTrue(path.exists())
        entry = configparser.ConfigParser(interpolation=None)
        entry.read(path, encoding="utf-8")
        self.assertEqual(entry["Desktop Entry"]["Name"], "AndroidBox")
        self.assertEqual(entry["Desktop Entry"]["Exec"], "androidbox")
        self.assertEqual(entry["Desktop Entry"]["Icon"], APP_ID)

    def test_appstream_identity(self):
        path = ROOT / "data" / f"{APP_ID}.metainfo.xml"
        self.assertTrue(path.exists())
        root = ET.parse(path).getroot()
        self.assertEqual(root.findtext("id"), APP_ID)
        self.assertEqual(root.findtext("name"), "AndroidBox")
        self.assertEqual(root.findtext("launchable"), f"{APP_ID}.desktop")

    def test_dbus_activation_matches_systemd(self):
        path = ROOT / "dbus" / f"{APP_ID}.Container.service"
        self.assertTrue(path.exists())
        service = configparser.ConfigParser()
        service.read(path)
        entry = service["D-BUS Service"]
        self.assertEqual(entry["Name"], APP_ID + ".Container")
        self.assertEqual(entry["Exec"], "/usr/bin/androidbox container start")
        unit = configparser.ConfigParser()
        unit.read(ROOT / "systemd" / entry["SystemdService"])
        self.assertEqual(unit["Service"]["BusName"], entry["Name"])
        self.assertEqual(unit["Service"]["ExecStart"], entry["Exec"])

    def test_image_protocol_is_preserved(self):
        for path in (ROOT / "tools/interfaces").glob("*.py"):
            content = path.read_text()
            self.assertNotIn("org.mutantcat", content)
        self.assertIn('INTERFACE = "lineageos.waydroid.IPlatform"',
                      (ROOT / "tools/interfaces/IPlatform.py").read_text())
        self.assertIn('"/vendor/waydroid.prop"', (ROOT / "tools/helpers/images.py").read_text())
        self.assertIn('"/waydroid_"', (ROOT / "tools/actions/initializer.py").read_text())
        self.assertIn('setprop("waydroid.active_apps", "Waydroid")',
                      (ROOT / "tools/actions/app_manager.py").read_text())

    def test_native_paths_and_names(self):
        config = (ROOT / "tools/config/__init__.py").read_text()
        self.assertIn('"work": "/var/lib/androidbox"', config)
        self.assertTrue((ROOT / "androidbox.py").exists())
        self.assertIn("Package: androidbox", (ROOT / "debian/control").read_text())
        for path in (ROOT / "tools").rglob("*.py"):
            self.assertNotIn("id.waydro.", path.read_text(), str(path))

    def test_guest_installs_apparmor_profiles(self):
        provision = (ROOT / "guest/provision.sh").read_text()
        self.assertIn('make -C "$source_dir" install install_apparmor', provision)

    def test_guest_builds_gbinder_from_vendored_sources(self):
        provision = (ROOT / "guest/provision.sh").read_text()
        # noble has no gbinder packages; the stack comes from guest/vendor.
        self.assertNotIn("python3-gbinder", provision)
        self.assertIn("guest/vendor/libglibutil", provision)
        self.assertIn("guest/vendor/libgbinder", provision)
        self.assertIn("guest/vendor/python-gbinder", provision)
        self.assertIn("python3 -c 'import gbinder'", provision)

    def test_guest_persists_binder_device_names(self):
        provision = (ROOT / "guest/provision.sh").read_text()
        # The container needs /dev/binder, but binderfs only creates the names
        # the module was given. Persisting the options keeps every reboot with
        # the same node names instead of the upstream defaults.
        self.assertIn("/etc/modprobe.d/androidbox.conf", provision)
        self.assertIn("options binder_linux devices=binder,hwbinder,vndbinder", provision)

    def test_guest_installs_preinstalled_android_images(self):
        provision = (ROOT / "guest/provision.sh").read_text()
        self.assertIn('label="androidbox-img"', provision)
        self.assertIn('blkid -L "$label"', provision)
        self.assertIn("/usr/share/androidbox-extra/images", provision)
        self.assertIn("install_preinstalled_images", provision)


if __name__ == "__main__":
    unittest.main()
