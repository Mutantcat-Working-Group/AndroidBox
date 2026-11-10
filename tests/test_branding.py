import configparser
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
APP_ID = "org.mutantcat.androidbox"


def source(path):
    """Read a repository file as UTF-8, whatever the host locale decodes as."""
    return path.read_text(encoding="utf-8")


class BrandingTests(unittest.TestCase):
    def test_native_icon_assets(self):
        icons = ROOT / "packaging/icons"
        self.assertEqual((icons / "AndroidBox.ico").read_bytes()[:4], b"\x00\x00\x01\x00")
        self.assertEqual((icons / "AndroidBox.icns").read_bytes()[:4], b"icns")
        self.assertEqual((ROOT / "data/AppIcon.png").read_bytes(),
                         (ROOT / "androidbox/assets/AppIcon.png").read_bytes())

    def test_packagers_use_product_icon(self):
        spec = source(ROOT / "packaging/desktop.spec")
        self.assertIn('icon=str(root / "packaging/icons/AndroidBox.ico")', spec)
        self.assertIn('icon=str(root / "packaging/icons/AndroidBox.icns")', spec)
        installer = source(ROOT / "packaging/windows.nsi")
        self.assertIn('!define MUI_ICON "${ICON_FILE}"', installer)
        self.assertIn('!define MUI_UNICON "${ICON_FILE}"', installer)
        self.assertIn('/DICON_FILE=', source(ROOT / "scripts/package_desktop.py"))

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
            content = source(path)
            self.assertNotIn("org.mutantcat", content)
        self.assertIn('INTERFACE = "lineageos.waydroid.IPlatform"',
                      source(ROOT / "tools/interfaces/IPlatform.py"))
        self.assertIn('"/vendor/waydroid.prop"', source(ROOT / "tools/helpers/images.py"))
        self.assertIn('"/waydroid_"', source(ROOT / "tools/actions/initializer.py"))
        self.assertIn('setprop("waydroid.active_apps", "Waydroid")',
                      source(ROOT / "tools/actions/app_manager.py"))

    def test_native_paths_and_names(self):
        config = source(ROOT / "tools/config/__init__.py")
        self.assertIn('"work": "/var/lib/androidbox"', config)
        self.assertTrue((ROOT / "androidbox.py").exists())
        self.assertIn("Package: androidbox", source(ROOT / "debian/control"))
        for path in (ROOT / "tools").rglob("*.py"):
            self.assertNotIn("id.waydro.", source(path), str(path))

    def test_guest_installs_apparmor_profiles(self):
        provision = source(ROOT / "guest/provision.sh")
        self.assertIn('make -C "$source_dir" install install_apparmor', provision)

    def test_guest_builds_gbinder_from_vendored_sources(self):
        provision = source(ROOT / "guest/provision.sh")
        # noble has no gbinder packages; the stack comes from guest/vendor.
        self.assertNotIn("python3-gbinder", provision)
        self.assertIn("guest/vendor/libglibutil", provision)
        self.assertIn("guest/vendor/libgbinder", provision)
        self.assertIn("guest/vendor/python-gbinder", provision)
        self.assertIn("python3 -c 'import gbinder'", provision)

    def test_guest_persists_binder_device_names(self):
        provision = source(ROOT / "guest/provision.sh")
        # The container needs /dev/binder, but binderfs only creates the names
        # the module was given. Persisting the options keeps every reboot with
        # the same node names instead of the upstream defaults.
        self.assertIn("/etc/modprobe.d/androidbox.conf", provision)
        self.assertIn("options binder_linux devices=binder,hwbinder,vndbinder", provision)

    def test_guest_installs_preinstalled_android_images(self):
        provision = source(ROOT / "guest/provision.sh")
        self.assertIn('label="androidbox-img"', provision)
        self.assertIn('blkid -L "$label"', provision)
        self.assertIn("/usr/share/androidbox-extra/images", provision)
        self.assertIn("install_preinstalled_images", provision)

    def test_guest_installs_network_validation_helper(self):
        provision = source(ROOT / "guest/provision.sh")
        self.assertIn("/usr/local/lib/androidbox/net-portal.py", provision)
        self.assertIn("/etc/systemd/system/androidbox-net-portal.service", provision)
        self.assertIn("androidbox-net-portal.service", provision)

    def test_guest_records_why_android_may_see_no_camera(self):
        provision = source(ROOT / "guest/provision.sh")
        # The loopback node is not the Android camera: an app only gets a device
        # when a camera provider this CPU can run is installed, and upstream
        # builds its own for the 32-bit ABI only. The audit keeps the cases
        # apart in the log.
        self.assertIn("audit_camera_hal", provision)
        self.assertIn("/var/lib/androidbox/camera-hal.txt", provision)
        self.assertIn("EI_CLASS", provision)
        self.assertIn("camera\\.provider", provision)

    def test_guest_installs_the_external_camera_provider(self):
        provision = source(ROOT / "guest/provision.sh")
        # The arm64_only image ships no provider binary, so the guest has to
        # put one where Android starts it from. All three parts are required:
        # the binary, the VINTF declaration and the init service.
        self.assertIn("install_camera_hal", provision)
        self.assertIn("/var/lib/androidbox/overlay/vendor", provision)
        self.assertIn("bin/hw", provision)
        self.assertIn("etc/vintf/manifest", provision)

    def test_guest_finds_the_provider_without_an_executable_bit(self):
        # The binary rides inside the seed payload and PyInstaller stores it
        # mode 0644, so an -x test on the source would skip the install and
        # leave every Android camera app still seeing nothing.
        provision = source(ROOT / "guest/provision.sh")
        self.assertIn('[[ ! -f $camera_hal_source ]]', provision)
        self.assertNotIn('[[ ! -x $camera_hal_source ]]', provision)
        # The copy that lands in the guest does have to be executable.
        self.assertIn('install -m 0755 "$camera_hal_source"', provision)
        self.assertIn("etc/init", provision)

    def test_camera_provider_uses_the_name_the_image_labels(self):
        # The vendor image's own vendor_file_contexts only labels
        # android.hardware.camera.provider@2.x-...-service as
        # hal_camera_default_exec; a different name would get no label and init
        # would refuse to start it.
        build = source(ROOT / "guest/camera-hal/build.sh")
        self.assertIn("android.hardware.camera.provider@2.4-external-service", build)

        deploy = ROOT / "guest/camera-hal/deploy"
        manifest = source(deploy / "android.hardware.camera.provider@2.4-external-service.xml")
        self.assertIn('format="aidl"', manifest)
        self.assertIn("<instance>external/0</instance>", manifest)

        rc = source(deploy / "android.hardware.camera.provider@2.4-external-service.rc")
        self.assertIn("android.hardware.camera.provider@2.4-external-service", rc)
        self.assertIn("class hal", rc)
        # The image's /system/etc/passwd is empty, so a named account would
        # leave init unable to resolve the uid.
        self.assertIn("user system", rc)


if __name__ == "__main__":
    unittest.main()
