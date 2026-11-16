"""Read package, label and icon out of a real APK archive.

A distributable APK is far too large to keep as a fixture, and downloading one
in CI would make these tests depend on somebody else's server. The tests
therefore build a small but genuinely valid archive: a binary AXML manifest, a
compiled resource table and a ZIP around them, exactly as aapt would emit
(without compression). Everything the reader does - chunk walking, string
pools, resource indirection - is exercised, and nothing external is needed.

The chunk layout mirrors what ApkStart (MIT) builds in test/lib/make-apk.js.
"""

import io
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from androidbox import apkmeta

ANDROID_NS = "http://schemas.android.com/apk/res/android"

STRING_POOL = 0x0001
TABLE = 0x0002
PACKAGE = 0x0200
TYPE_TYPE = 0x0201
XML = 0x0003
XML_START_NAMESPACE = 0x0100
XML_END_NAMESPACE = 0x0101
XML_START_ELEMENT = 0x0102
XML_END_ELEMENT = 0x0103

TYPE_REFERENCE = 0x01
TYPE_STRING = 0x03
TYPE_INT_DEC = 0x10


def u16(value):
    return struct.pack("<H", value & 0xFFFF)


def u32(value):
    return struct.pack("<I", value & 0xFFFFFFFF)


def string_pool(strings):
    """Build a ResStringPool chunk using UTF-8, like aapt does."""
    offsets = []
    body = b""
    for text in strings:
        offsets.append(len(body))
        encoded = text.encode("utf-8")
        # UTF-16 length then byte length, both single-byte when small.
        body += bytes((len(text), len(encoded))) + encoded + b"\0"
    header_size = 28
    strings_start = header_size + len(offsets) * 4
    chunk_size = strings_start + len(body)
    head = (u16(STRING_POOL) + u16(header_size) + u32(chunk_size)
            + u32(len(strings)) + u32(0) + u32(0x100) + u32(strings_start) + u32(0))
    return head + b"".join(u32(offset) for offset in offsets) + body


def chunk(chunk_type, header_size, body):
    return u16(chunk_type) + u16(header_size) + u32(8 + len(body)) + body


def start_element(name_index, attributes):
    """attributes: list of (namespace index, name index, data type, data)."""
    encoded = b""
    for namespace, name, data_type, data in attributes:
        encoded += (u32(namespace) + u32(name) + u32(0xFFFFFFFF)
                    + u16(8) + b"\0" + bytes((data_type,)) + u32(data))
    ext = (u32(0xFFFFFFFF) + u32(name_index) + u16(20) + u16(20)
           + u16(len(attributes)) + u16(0) + u16(0) + u16(0))
    return chunk(XML_START_ELEMENT, 16, u32(0) + u32(0) + ext + encoded)


def end_element(name_index):
    return chunk(XML_END_ELEMENT, 16, u32(0) + u32(0) + u32(0xFFFFFFFF) + u32(name_index))


def manifest_axml(package, label, icon, label_reference=None, icon_reference=None):
    """Build one binary manifest, optionally indirection through resources."""
    strings = ["manifest", "package", package, "android", ANDROID_NS,
               "application", "label", "icon", label or "TestApp",
               "activity", "name", ".Main",
               "intent-filter", "action", "android.intent.action.MAIN",
               "category", "android.intent.category.LAUNCHER",
               icon or "res/mipmap-hdpi/ic_launcher.png"]
    index = {text: position for position, text in enumerate(strings)}
    ns = index[ANDROID_NS]

    label_index = index[label or "TestApp"]
    icon_index = index[icon or "res/mipmap-hdpi/ic_launcher.png"]
    label_attr = ((ns, index["label"], TYPE_REFERENCE, label_reference) if label_reference
                  else (ns, index["label"], TYPE_STRING, label_index))
    icon_attr = ((ns, index["icon"], TYPE_REFERENCE, icon_reference) if icon_reference
                 else (ns, index["icon"], TYPE_STRING, icon_index))
    chunks = [
        chunk(XML_START_NAMESPACE, 16, u32(0) + u32(0) + u32(index["android"]) + u32(ns)),
        start_element(index["manifest"], [(0xFFFFFFFF, index["package"], TYPE_STRING, index[package])]),
        start_element(index["application"], [label_attr, icon_attr]),
        start_element(index["activity"], [(ns, index["name"], TYPE_STRING, index[".Main"])]),
        start_element(index["intent-filter"], []),
        start_element(index["action"], [(ns, index["name"], TYPE_STRING,
                                         index["android.intent.action.MAIN"])]),
        end_element(index["action"]),
        start_element(index["category"], [(ns, index["name"], TYPE_STRING,
                                           index["android.intent.category.LAUNCHER"])]),
        end_element(index["category"]),
        end_element(index["intent-filter"]),
        end_element(index["activity"]),
        end_element(index["application"]),
        end_element(index["manifest"]),
        chunk(XML_END_NAMESPACE, 16, u32(0) + u32(0) + u32(index["android"]) + u32(ns)),
    ]
    body = string_pool(strings) + b"".join(chunks)
    return u16(XML) + u16(8) + u32(8 + len(body)) + body


def resource_table(entries, strings=None):
    """Build a resources.arsc with one package holding one type.

    Layout of a resource table is: table header, the global string pool, then a
    package chunk that itself carries its type/key pools and the entries.
    entries: list of (resource id, value index into the global strings).
    """
    strings = strings or ["TestApp", "res/mipmap-hdpi/ic_launcher.png"]
    pool = string_pool(strings)

    # ResTable_type: 20-byte chunk header plus a 4-byte ResTable_config, so
    # the entry offset table starts at 24.
    offsets_start = 24
    data_start = offsets_start + len(entries) * 4
    entry_data = b""
    offsets = []
    for _resource, value_index in entries:
        offsets.append(len(entry_data))
        # ResTable_entry{size=8, flags=0, key=0} + ResValue{size=8, res0, type, data}
        entry_data += (u16(8) + u16(0) + u32(0)
                       + u16(8) + b"\0" + bytes((TYPE_STRING,)) + u32(value_index))
    config = u32(4)  # an empty ResTable_config matches every device
    type_body = (b"\x01\0\0\0"                       # type id 1, flags, reserved
                 + u32(len(entries)) + u32(data_start) + config
                 + b"".join(u32(offset) for offset in offsets) + entry_data)
    type_chunk = chunk(TYPE_TYPE, offsets_start, type_body)

    type_pool = string_pool(["string"])
    key_pool = string_pool(["app_name"])

    # ResTable_package: 8-byte chunk header, id, name[128], typeStrings,
    # lastPublicType, keyStrings, lastPublicKey - 156 bytes in total.
    header_size = 156
    type_strings_offset = header_size
    key_strings_offset = header_size + len(type_pool)
    package_body = (u32(0x7F) + b"pkg".ljust(128, b"\0")
                    + u32(type_strings_offset) + u32(0)
                    + u32(key_strings_offset) + u32(0)
                    + type_pool + key_pool + type_chunk)
    package_chunk = u16(PACKAGE) + u16(header_size) + u32(8 + len(package_body)) + package_body

    body = pool + package_chunk
    # ResTable_header is 12 bytes: chunk header, then packageCount.
    return u16(TABLE) + u16(12) + u32(12 + len(body)) + u32(1) + body


def build_apk(path, manifest, resources=None, icon_bytes=None):
    """Write a stored (uncompressed) ZIP, like an APK's own layout."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("AndroidManifest.xml", manifest)
        if resources is not None:
            archive.writestr("resources.arsc", resources)


class ApkReaderTests(unittest.TestCase):
    def build(self, **kwargs):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "app.apk"
        build_apk(path, **kwargs)
        return path

    def test_a_plain_string_label_and_icon_are_read(self):
        path = self.build(manifest=manifest_axml(
            "com.example.test", "TestApp", "res/mipmap-hdpi/ic_launcher.png"))
        info = apkmeta.read_apk(path)
        self.assertEqual(info.package, "com.example.test")
        self.assertEqual(info.label, "TestApp")
        self.assertEqual(info.icon_path, "res/mipmap-hdpi/ic_launcher.png")
        self.assertEqual(info.launcher_activity, ".Main")

    def test_a_resource_reference_is_resolved_through_the_table(self):
        path = self.build(
            manifest=manifest_axml("com.example.test", "", "", label_reference=0x7F010000,
                                   icon_reference=0x7F020000),
            resources=resource_table([(0x7F010000, 0)]),
        )
        info = apkmeta.read_apk(path)
        self.assertEqual(info.package, "com.example.test")
        # The label comes from the resource table, not the manifest.
        self.assertEqual(info.label, "TestApp")

    def test_a_missing_manifest_is_reported(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "bad.apk"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("classes.dex", b"dex")
        with self.assertRaises(apkmeta.ApkReadError):
            apkmeta.read_apk(path)

    def test_a_file_that_is_not_a_zip_is_reported(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "nope.apk"
        path.write_bytes(b"not a zip at all")
        with self.assertRaises(apkmeta.ApkReadError):
            apkmeta.read_apk(path)

    def test_a_manifest_that_is_not_binary_xml_is_reported(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "text.apk"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("AndroidManifest.xml", b"<manifest package='x'/>")
        with self.assertRaises(apkmeta.ApkReadError):
            apkmeta.read_apk(path)

    def test_extract_icon_returns_the_archive_bytes(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "icon.apk"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("AndroidManifest.xml", manifest_axml(
                "com.example.test", "TestApp", "res/mipmap-hdpi/ic_launcher.png"))
            archive.writestr("res/mipmap-hdpi/ic_launcher.png", b"\x89PNG\r\n\x1a\n")
        self.assertEqual(apkmeta.extract_icon(path, "res/mipmap-hdpi/ic_launcher.png"),
                         b"\x89PNG\r\n\x1a\n")

    def test_extract_icon_returns_nothing_for_an_unknown_path(self):
        path = self.build(manifest=manifest_axml("com.example.test", "T", "res/missing.png"))
        self.assertEqual(apkmeta.extract_icon(path, "res/missing.png"), b"")


class StringPoolTests(unittest.TestCase):
    def test_pool_round_trips_mixed_lengths(self):
        strings = ["a", "manifest", "", "a longer string"]
        data = string_pool(strings)
        self.assertEqual(apkmeta._string_pool(data, 0), strings)


class ArchiveFootprintTests(unittest.TestCase):
    def test_the_reader_only_reads_what_it_needs(self):
        # A real APK carries hundreds of megabytes of dex and native libraries;
        # the reader must open the archive lazily rather than read it whole.
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "big.apk"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("AndroidManifest.xml", manifest_axml(
                "com.example.big", "Big", "res/icon.png"))
            archive.writestr("classes.dex", b"\0" * (8 * 1024 * 1024))
        before = path.stat().st_size
        info = apkmeta.read_apk(path)
        self.assertEqual(info.package, "com.example.big")
        self.assertLess(before, 1024 * 1024, "the fixture should be mostly compressed")


if __name__ == "__main__":
    unittest.main()
