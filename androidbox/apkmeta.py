"""Read an app's name and icon out of an APK without any Android tooling.

The installed client has no aapt2 and no SDK, and the guest is busy booting
when a user drags an APK in. The manifest inside an APK is binary XML (AXML)
and its string resources live in a compiled table (resources.arsc); both are
documented Android file formats, so a few hundred lines of parsing read the
label and icon directly from the archive.

The format layout follows the same one ApkStart (MIT) implements in
src/core/axml.js and src/core/arsc.js.
"""

import struct
import zipfile

RES_STRING_POOL_TYPE = 0x0001
RES_XML_TYPE = 0x0003
RES_TABLE_TYPE = 0x0002
RES_TABLE_PACKAGE_TYPE = 0x0200
RES_TABLE_TYPE_TYPE = 0x0201

RES_XML_START_ELEMENT = 0x0102
RES_XML_END_ELEMENT = 0x0103
RES_XML_START_NAMESPACE = 0x0100
RES_XML_END_NAMESPACE = 0x0101

TYPE_REFERENCE = 0x01
TYPE_STRING = 0x03
TYPE_INT_DEC = 0x10
TYPE_INT_HEX = 0x11
TYPE_INT_BOOLEAN = 0x12

ANDROID_NAMESPACE = "http://schemas.android.com/apk/res/android"
NO_INDEX = 0xFFFFFFFF


class ApkReadError(ValueError):
    """The archive is not an APK this reader can understand."""


def _u16(data, offset):
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def _string_pool(data, start):
    """Decode a ResStringPool chunk into a list of strings."""
    if _u16(data, start) != RES_STRING_POOL_TYPE:
        raise ApkReadError("expected a string pool")
    header_size = _u16(data, start + 2)
    count = _u32(data, start + 8)
    flags = _u32(data, start + 16)
    strings_start = _u32(data, start + 20)
    base = start + strings_start
    utf8 = bool(flags & 0x100)
    strings = []
    for index in range(count):
        position = base + _u32(data, start + header_size + index * 4)
        if utf8:
            # Two lengths precede the bytes: UTF-16 unit count, then byte count.
            first = data[position]
            position += 1
            if first & 0x80:
                position += 1
            length = data[position]
            position += 1
            if length & 0x80:
                length = ((length & 0x7F) << 8) | data[position]
                position += 1
            strings.append(data[position:position + length].decode("utf-8", "replace"))
        else:
            length = _u16(data, position)
            position += 2
            if length & 0x8000:
                length = ((length & 0x7FFF) << 16) | _u16(data, position)
                position += 2
            strings.append(data[position:position + length * 2].decode("utf-16-le", "replace"))
    return strings


class Attribute:
    """One attribute of a binary-XML element."""

    __slots__ = ("namespace", "name", "value", "reference", "data_type")

    def __init__(self, namespace, name, value, reference, data_type):
        self.namespace = namespace
        self.name = name
        self.value = value
        self.reference = reference
        self.data_type = data_type

    def __repr__(self):
        return f"Attribute({self.name!r}, value={self.value!r}, reference={self.reference!r})"


class Element:
    """One element of a binary-XML document."""

    __slots__ = ("name", "attributes", "children")

    def __init__(self, name):
        self.name = name
        self.attributes = []
        self.children = []

    def attribute(self, name, namespace=ANDROID_NAMESPACE):
        for attribute in self.attributes:
            if attribute.name == name and (namespace is None or attribute.namespace == namespace):
                return attribute
        return None

    def text(self, name, namespace=ANDROID_NAMESPACE):
        attribute = self.attribute(name, namespace)
        return None if attribute is None else attribute.value

    def find_all(self, name):
        return [child for child in self.children if child.name == name]


def parse_binary_xml(data):
    """Return the root element of an Android binary XML document."""
    if len(data) < 8 or _u16(data, 0) != RES_XML_TYPE:
        raise ApkReadError("not Android binary XML")
    header_size = _u16(data, 2)
    total = _u32(data, 4)
    position = header_size
    pool = []
    prefix_by_uri = {}
    root = Element("#document")
    stack = [root]

    while position + 8 <= total and position + 8 <= len(data):
        chunk_type = _u16(data, position)
        chunk_size = _u32(data, position + 4)
        if chunk_size <= 0:
            break
        if chunk_type == RES_STRING_POOL_TYPE:
            pool = _string_pool(data, position)
        elif chunk_type in (RES_XML_START_NAMESPACE, RES_XML_END_NAMESPACE):
            if chunk_type == RES_XML_START_NAMESPACE:
                prefix_index = _u32(data, position + 16)
                uri_index = _u32(data, position + 20)
                if uri_index < len(pool) and prefix_index < len(pool):
                    prefix_by_uri[pool[uri_index]] = pool[prefix_index]
        elif chunk_type == RES_XML_START_ELEMENT:
            name_index = _u32(data, position + 20)
            attr_start = _u16(data, position + 24)
            attr_size = _u16(data, position + 26)
            attr_count = _u16(data, position + 28)
            element = Element(pool[name_index] if name_index < len(pool) else "")
            attr_base = position + 16 + attr_start
            for index in range(attr_count):
                offset = attr_base + index * attr_size
                ns_index = _u32(data, offset)
                name = _u32(data, offset + 4)
                raw_index = _u32(data, offset + 8)
                data_type = data[offset + 15]
                value = _u32(data, offset + 16)
                namespace = "" if ns_index == NO_INDEX or ns_index >= len(pool) else pool[ns_index]
                attribute_name = pool[name] if name < len(pool) else ""
                resolved = None
                reference = None
                if raw_index != NO_INDEX and raw_index < len(pool):
                    resolved = pool[raw_index]
                elif data_type == TYPE_STRING and value < len(pool):
                    resolved = pool[value]
                elif data_type == TYPE_REFERENCE:
                    reference = value
                elif data_type == TYPE_INT_BOOLEAN:
                    resolved = bool(value)
                elif data_type in (TYPE_INT_DEC, TYPE_INT_HEX):
                    resolved = value
                element.attributes.append(Attribute(namespace, attribute_name,
                                                     resolved, reference, data_type))
            stack[-1].children.append(element)
            stack.append(element)
        elif chunk_type == RES_XML_END_ELEMENT:
            if len(stack) > 1:
                stack.pop()
        position += chunk_size

    document = root.find_all("manifest")
    if not document:
        if not root.children:
            raise ApkReadError("empty manifest")
        return root.children[0]
    return document[0]


class ResourceTable:
    """The string and file layout of a compiled resources.arsc."""

    def __init__(self, data):
        if len(data) < 12 or _u16(data, 0) != RES_TABLE_TYPE:
            raise ApkReadError("not a resource table")
        self.data = data
        self.global_strings = []
        # {resource id: [(config, value, data_type)]}
        self.values = {}
        self._parse()

    def _parse(self):
        data = self.data
        header_size = _u16(data, 2)
        total = _u32(data, 4)
        position = header_size
        while position + 8 <= total and position + 8 <= len(data):
            chunk_type = _u16(data, position)
            chunk_size = _u32(data, position + 4)
            if chunk_size <= 0:
                break
            if chunk_type == RES_STRING_POOL_TYPE and not self.global_strings:
                self.global_strings = _string_pool(data, position)
            elif chunk_type == RES_TABLE_PACKAGE_TYPE:
                self._parse_package(position, chunk_size)
            position += chunk_size

    def _parse_package(self, start, size):
        data = self.data
        package_id = _u32(data, start + 8)
        type_strings_offset = _u32(data, start + 268)
        try:
            type_strings = _string_pool(data, start + type_strings_offset) if type_strings_offset else []
        except ApkReadError:
            type_strings = []
        position = start + _u16(data, start + 2)
        end = start + size
        while position + 8 <= end:
            chunk_type = _u16(data, position)
            chunk_size = _u32(data, position + 4)
            if chunk_size <= 0:
                break
            if chunk_type == RES_TABLE_TYPE_TYPE:
                self._parse_type(position, chunk_size, package_id, type_strings)
            position += chunk_size

    def _parse_type(self, start, size, package_id, type_strings):
        data = self.data
        type_id = data[start + 8]
        entry_count = _u32(data, start + 12)
        entries_start = _u32(data, start + 16)
        config_size = _u32(data, start + 20)
        config = self._config(start + 20, config_size)
        offsets = start + _u16(data, start + 2)
        base = start + entries_start
        for index in range(entry_count):
            if offsets + index * 4 + 4 > start + size:
                break
            entry_offset = _u32(data, offsets + index * 4)
            if entry_offset == 0xFFFFFFFF:
                continue
            entry = base + entry_offset
            if entry + 8 > len(data):
                continue
            entry_size = _u16(data, entry)
            flags = _u16(data, entry + 2)
            if flags & 0x0001:  # compact entry: value is inline
                value_type = data[entry + 7]
                value = _u32(data, entry + 4)
            else:
                value_type = data[entry + entry_size + 3]
                value = _u32(data, entry + entry_size + 4)
            resource_id = (package_id << 24) | (type_id << 16) | index
            self.values.setdefault(resource_id, []).append((config, value, value_type))

    def _config(self, offset, size):
        data = self.data
        config = {"density": 0, "language": "", "country": "", "default": True}
        if size >= 16:
            config["language"] = data[offset + 8:offset + 10].replace(b"\0", b"").decode("latin-1", "replace")
            config["country"] = data[offset + 10:offset + 12].replace(b"\0", b"").decode("latin-1", "replace")
            config["density"] = _u16(data, offset + 14)
        config["default"] = not config["language"] and not config["country"] and not config["density"]
        return config

    def string(self, resource_id):
        """Return the string a resource id points at, preferring default config."""
        for config, value, value_type in self._ranked(resource_id, prefer_dense=False):
            if value_type == TYPE_STRING and value < len(self.global_strings):
                return self.global_strings[value]
            if value_type == TYPE_REFERENCE and value in self.values:
                return self.string(value)
        return None

    def file(self, resource_id):
        """Return the file path a resource id points at, preferring dense assets."""
        for config, value, value_type in self._ranked(resource_id, prefer_dense=True):
            if value_type == TYPE_STRING and value < len(self.global_strings):
                return self.global_strings[value]
        return None

    def _ranked(self, resource_id, prefer_dense):
        entries = self.values.get(resource_id)
        if not entries:
            return []

        def score(item):
            config = item[0]
            if prefer_dense:
                return 0 if config["density"] == 0 else config["density"]
            penalty = 0 if config["default"] else 100
            if config["density"]:
                penalty += 10
            return -penalty

        return sorted(entries, key=score, reverse=True)




class ApkInfo:
    """What a launcher needs to show an app: its package, label and icon."""

    __slots__ = ("package", "label", "icon_path", "launcher_activity")

    def __init__(self, package, label, icon_path, launcher_activity):
        self.package = package
        self.label = label
        self.icon_path = icon_path
        self.launcher_activity = launcher_activity

    def __repr__(self):
        return (f"ApkInfo(package={self.package!r}, label={self.label!r}, "
                f"icon={self.icon_path!r})")


def read_apk(path):
    """Return the package name, display label and icon path inside an APK."""
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as error:
        raise ApkReadError(f"{path} is not a readable APK: {error}") from error
    with archive:
        names = set(archive.namelist())
        if "AndroidManifest.xml" not in names:
            raise ApkReadError("the archive has no AndroidManifest.xml")
        manifest = parse_binary_xml(archive.read("AndroidManifest.xml"))
        package = manifest.text("package", namespace=None) or ""
        if not package:
            raise ApkReadError("the manifest declares no package")

        # android:label and android:icon live on <application>, not on
        # <manifest>; reading them from the manifest root finds nothing.
        application = next(iter(manifest.find_all("application")), None)
        label_attribute = application.attribute("label") if application else None
        icon_attribute = application.attribute("icon") if application else None
        label = label_attribute.value if label_attribute else ""
        icon = icon_attribute.value if icon_attribute else ""

        launcher = ""
        for application_element in manifest.find_all("application"):
            activities = application_element.find_all("activity")
            for activity in activities:
                for intent in activity.find_all("intent-filter"):
                    for action in intent.find_all("action"):
                        if action.text("name") == "android.intent.action.MAIN":
                            launcher = activity.text("name") or launcher
            if not launcher and activities:
                launcher = activities[0].text("name") or ""

        table = None
        if "resources.arsc" in names:
            try:
                table = ResourceTable(archive.read("resources.arsc"))
            except ApkReadError:
                table = None

        if table is not None:
            if label_attribute is not None and label_attribute.reference is not None:
                label = table.string(label_attribute.reference) or label
            if icon_attribute is not None and icon_attribute.reference is not None:
                icon = table.file(icon_attribute.reference) or icon
            # An activity may name its own label; the launcher shows that one.
            for activity in (application.find_all("activity") if application else []):
                own = activity.attribute("label")
                if own is not None:
                    label = (table.string(own.reference) if own.reference is not None
                             else own.value) or label
                    break

    if isinstance(label, str) and label.startswith("@"):
        label = ""
    if isinstance(icon, str) and icon.startswith("@"):
        icon = ""
    return ApkInfo(package, label or package, icon or "", launcher or "")


def extract_icon(path, icon_path):
    """Return the icon bytes named by an APK's resource table, or b""."""
    if not icon_path:
        return b""
    try:
        with zipfile.ZipFile(path) as archive:
            try:
                return archive.read(icon_path)
            except KeyError:
                return b""
    except (OSError, zipfile.BadZipFile):
        return b""
