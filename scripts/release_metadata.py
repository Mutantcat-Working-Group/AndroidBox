"""Validate release identity and the complete installer set (Python 3.11+)."""

import argparse
import ast
from datetime import datetime
import hashlib
from pathlib import Path
import re
import tomllib


def windows_version(version):
    match = re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.([0-9]{8})", version)
    if not match:
        raise ValueError("Version must be MAJOR.MINOR.YYYYMMDD")
    major, minor, date = match.groups()
    datetime.strptime(date, "%Y%m%d")
    fields = (int(major), int(minor), int(date[:4]), int(date[4:]))
    if any(value > 65535 for value in fields):
        raise ValueError("Windows numeric version fields must fit 16 bits")
    return fields


def assignment(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(f"Missing {name} in {path}")


def validate_versions(root, tag=None):
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    windows_version(version)
    for relative, name in (("androidbox/__init__.py", "__version__"), ("tools/config/__init__.py", "version")):
        if assignment(root / relative, name) != version:
            raise ValueError(f"Version mismatch in {relative}")
    if not (root / "debian/changelog").read_text(encoding="utf-8").startswith(f"androidbox ({version})"):
        raise ValueError("Version mismatch in Debian changelog")
    if tag is not None and tag != f"v{version}":
        raise ValueError(f"Tag must equal v{version}")
    return version


def artifact_names(version):
    windows_version(version)
    names = [f"AndroidBox-{version}-Windows-x86_64-Setup.exe",
             f"AndroidBox-{version}-macOS-arm64.dmg",
             f"AndroidBox-{version}-macOS-x86_64.dmg",
             f"AndroidBox-{version}-Linux-x86_64.AppImage",
             f"AndroidBox-{version}-Linux-aarch64.AppImage"]
    names += [f"AndroidBox-{version}-{platform}-{arch}.tar.gz"
              for platform, arch in (("Windows", "x86_64"), ("macOS", "arm64"),
                                     ("macOS", "x86_64"), ("Linux", "x86_64"),
                                     ("Linux", "aarch64"))]
    return names


def collect_checksums(directory, version, algorithm="sha256"):
    expected = set(artifact_names(version))
    actual = {path.name for path in directory.iterdir() if path.name != "SHA256SUMS" and not path.name.startswith("checksums-")}
    if actual != expected:
        raise ValueError(f"Incorrect release payload: missing={expected - actual}, unexpected={actual - expected}")
    lines = []
    for name in sorted(expected):
        path = directory / name
        if not path.is_file() or path.is_symlink() or not 0 < path.stat().st_size < 2 * 1024**3:
            raise ValueError(f"Invalid or oversized GitHub release artifact: {name}")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, algorithm).hexdigest()
        lines.append(f"{digest}  {name}\n")
    return "".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag")
    parser.add_argument("--checksums", type=Path)
    args = parser.parse_args()
    version = validate_versions(Path(__file__).resolve().parents[1], args.tag)
    if args.checksums:
        (args.checksums / "SHA256SUMS").write_text(collect_checksums(args.checksums, version, "sha256"), encoding="utf-8")
        (args.checksums / "checksums-md5.txt").write_text(collect_checksums(args.checksums, version, "md5"), encoding="utf-8")
        (args.checksums / "checksums-sha1.txt").write_text(collect_checksums(args.checksums, version, "sha1"), encoding="utf-8")
    print(version)


if __name__ == "__main__":
    main()
