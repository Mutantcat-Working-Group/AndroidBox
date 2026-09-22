"""Portable QEMU configuration and lifecycle, independent of Qt and Linux tools."""

from dataclasses import asdict, dataclass, fields, replace
import ctypes
import json
import os
from pathlib import Path
import platform
import secrets
import shutil
import socket
import subprocess
import sys
import time

from .process import popen, run
from . import bundled, seed


def start_attempts(config, driver):
    """Yield the launch variants to try, richest first.

    A host can refuse one audio device while the rest of the guest boots fine:
    a sound server that is not running, a microphone another application holds,
    a screen that has been locked. When QEMU exits over such a device the next
    variant drops it, so the guest comes up without sound instead of not at all.
    """
    yield config, driver
    if not driver:
        return
    if config.microphone != "off":
        yield replace(config, microphone="off"), driver
    if config.audio != "off" or config.microphone != "off":
        yield replace(config, audio="off", microphone="off"), None


def normalize_arch(value):
    aliases = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}
    try:
        return aliases[value.lower()]
    except KeyError:
        raise ValueError(f"Unsupported architecture: {value}") from None


def state_directory():
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return base / "org.mutantcat.androidbox"


def host_memory_mb():
    try:
        if sys.platform == "win32":
            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32)] + [
                    (name, ctypes.c_uint64) for name in
                    ("physical", "available", "pagefile", "available_pagefile", "virtual", "available_virtual", "extended")]
            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return status.physical // (1024 * 1024)
        elif sys.platform == "darwin":
            size = ctypes.c_uint64()
            length = ctypes.c_size_t(ctypes.sizeof(size))
            libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
            if libc.sysctlbyname(b"hw.memsize", ctypes.byref(size), ctypes.byref(length), None, 0) == 0:
                return size.value // (1024 * 1024)
        else:
            return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") // (1024 * 1024)
    except (AttributeError, OSError, ValueError):
        pass
    return None


def disk_format(path):
    with Path(path).open("rb") as stream:
        return "qcow2" if stream.read(4) == b"QFI\xfb" else "raw"


CPU_MODES = ("auto", "host", "max", "qemu64")
DISK_CACHES = ("writeback", "none", "unsafe")
TCG_THREADS = ("auto", "multi", "single")
DISPLAY_QUALITY = ("responsive", "balanced", "sharp")
# noVNC quality levels: lower numbers trade image sharpness for less encoding
# work on both ends, which keeps mouse and touch input feeling immediate.
QUALITY_LEVELS = {"responsive": 3, "balanced": 6, "sharp": 9}
AUDIO_MODES = ("auto", "off")
MICROPHONE_MODES = ("auto", "off")
CAMERA_MODES = ("auto", "off")
CAMERA_GUEST_PORT = 7100
# Audio backends each platform offers, best first. QEMU only builds a subset of
# drivers per host, so the list is filtered against what QEMU reports.
AUDIO_DRIVERS = {"Darwin": ("coreaudio",), "Windows": ("dsound", "sdl", "pa"),
                 "Linux": ("pa", "pipewire", "sdl", "alsa")}
AUDIO_DEVICE_ID = "androidbox-audio"
# QEMU prints this when a codec device cannot take a capture voice, for
# instance when the host withholds the microphone from the application.
AUDIO_CAPTURE_DENIED = "Can not open `adc'"
DISK_LOCK_MARKERS = ('Failed to get "write" lock', "Is another process using the image")


def startup_failure_reason(log_path):
    """Name why QEMU refused to run, when the runtime log knows it.

    A guest disk another QEMU already holds (for example a second AndroidBox,
    or a terminal QEMU whose overlay backs the same image) surfaces as a bare
    exit code; this returns the sentence the user needs instead.
    """
    try:
        text = Path(log_path).read_text("utf-8", errors="replace")
    except OSError:
        return None
    if any(marker in text for marker in DISK_LOCK_MARKERS):
        return ("Another program is using the guest disk, so QEMU could not lock it "
                "for writing. Close the other virtual machine (for example a second "
                "AndroidBox or QEMU started from the terminal) and start again.")
    return None


def select_cpu(accelerator, cpu_mode):
    if cpu_mode == "auto":
        # TCG and WHPX expose no usable host-passthrough CPU model.
        return "max" if accelerator in ("tcg", "whpx") else "host"
    if cpu_mode == "host" and accelerator == "whpx":
        return "max"
    return cpu_mode


def block_cache(disk_cache):
    if disk_cache == "unsafe":
        return {"no-flush": True}
    if disk_cache == "none":
        return {"direct": True}
    return None


def display_quality_level(quality):
    """Return the noVNC quality level a display quality name maps to."""
    try:
        return QUALITY_LEVELS[quality]
    except KeyError:
        raise ValueError(f"Invalid display quality: {quality}") from None


def available_audio_drivers(binary):
    """Return the audio drivers this QEMU build supports."""
    result = run([binary, "-audiodev", "help"], timeout=10, check=True)
    return {line.strip() for line in result.stdout.splitlines()[1:] if line.strip()}


def audio_driver(binary, system=None):
    """Return the best audio backend for this host, or empty when none works."""
    supported = available_audio_drivers(binary)
    for name in AUDIO_DRIVERS.get(system or platform.system(), ()):
        if name in supported:
            return name
    return ""


def audio_arguments(config, driver):
    """Return the QEMU audio devices for the requested output and microphone."""
    if not driver or (config.audio == "off" and config.microphone == "off"):
        return []
    arguments = ["-audiodev", f"{driver},id={AUDIO_DEVICE_ID}", "-device", "intel-hda"]
    if config.audio != "off":
        arguments += ["-device", f"hda-output,audiodev={AUDIO_DEVICE_ID}"]
    if config.microphone != "off":
        arguments += ["-device", f"hda-micro,audiodev={AUDIO_DEVICE_ID}"]
    return arguments


def default_config(discover_disk=True):
    memory = host_memory_mb() or 4096
    config = VMConfig(arch=normalize_arch(platform.machine()),
                      cpus=max(1, min(6, (os.cpu_count() or 4) // 2)),
                      memory_mb=max(1024, min(6144, (memory // 2 // 1024) * 1024)))
    if not discover_disk:
        return config
    # Only use explicitly named managed guest disks, never arbitrary user images.
    for extension in ("qcow2", "raw"):
        path = state_directory() / "guests" / f"androidbox-{config.arch}.{extension}"
        try:
            if not path.is_file():
                continue
            detected_format = disk_format(path)
        except OSError:
            continue
        config.disk = str(path)
        config.disk_format = detected_format
        break
    return config


@dataclass
class VMConfig:
    disk: str = ""
    arch: str = "x86_64"
    memory_mb: int = 4096
    cpus: int = 4
    firmware: str = ""
    qemu: str = ""
    accelerator: str = "auto"
    disk_format: str = "qcow2"
    cpu_mode: str = "auto"
    disk_cache: str = "writeback"
    tcg_threads: str = "auto"
    display_quality: str = "balanced"
    audio: str = "auto"
    microphone: str = "auto"
    camera: str = "auto"

    def resolved_firmware(self):
        if self.firmware:
            return self.firmware
        if normalize_arch(self.arch) != "aarch64":
            return ""
        if not self.qemu or bundled.contains_binary(self.qemu):
            firmware = bundled.arm_firmware()
            if firmware:
                return firmware
        try:
            binary = Path(self.qemu or executable(self))
        except ValueError:
            return ""
        prefixes = (binary.parent, binary.parent.parent)
        for prefix in prefixes:
            for relative in ("share/qemu/edk2-aarch64-code.fd", "share/qemu/QEMU_EFI.fd",
                             "share/qemu/AAVMF_CODE.fd", "share/edk2-aarch64-code.fd",
                             "share/AAVMF/AAVMF_CODE.fd", "share/edk2/aarch64/QEMU_EFI.fd",
                             "share/qemu-efi-aarch64/QEMU_EFI.fd"):
                path = prefix / relative
                if path.is_file():
                    return str(path)
        return ""

    def validate(self, check_files=True):
        for name in ("disk", "arch", "firmware", "qemu", "accelerator", "disk_format",
                     "audio", "microphone", "camera"):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"{name} must be a string")
        normalize_arch(self.arch)
        if type(self.memory_mb) is not int or not 1024 <= self.memory_mb <= 262144:
            raise ValueError("Memory must be between 1024 and 262144 MiB")
        if type(self.cpus) is not int or not 1 <= self.cpus <= 128:
            raise ValueError("CPU count must be between 1 and 128")
        if self.accelerator not in {"auto", "tcg", "kvm", "hvf", "whpx"}:
            raise ValueError("Invalid accelerator")
        if self.cpu_mode not in CPU_MODES:
            raise ValueError("Invalid CPU model")
        if self.cpu_mode == "qemu64" and normalize_arch(self.arch) != "x86_64":
            raise ValueError("qemu64 is an x86_64 CPU model")
        if self.disk_cache not in DISK_CACHES:
            raise ValueError("Invalid disk cache mode")
        if self.tcg_threads not in TCG_THREADS:
            raise ValueError("Invalid TCG thread mode")
        if self.display_quality not in DISPLAY_QUALITY:
            raise ValueError("Invalid display quality")
        if self.audio not in AUDIO_MODES:
            raise ValueError("Invalid audio mode")
        if self.microphone not in MICROPHONE_MODES:
            raise ValueError("Invalid microphone mode")
        if self.camera not in CAMERA_MODES:
            raise ValueError("Invalid camera mode")
        if self.disk_format not in {"qcow2", "raw"}:
            raise ValueError("Disk format must be qcow2 or raw")
        if check_files:
            if not self.disk or not Path(self.disk).is_file():
                raise ValueError("Select a prepared Linux guest disk, not an Android system.img partition")
            if normalize_arch(self.arch) == "aarch64" and not self.resolved_firmware():
                raise ValueError("ARM64 guests require an AAVMF/QEMU_EFI firmware file")
            if self.firmware and not Path(self.firmware).is_file():
                raise ValueError("The selected firmware file does not exist")


def load_config(path=None):
    path = path or state_directory() / "settings.json"
    if not path.exists():
        return default_config()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object")
        names = {field.name for field in fields(VMConfig)}
        defaults = asdict(default_config(discover_disk=False))
        defaults.update({key: value for key, value in data.items() if key in names})
        config = VMConfig(**defaults)
        config.validate(check_files=False)
        return config
    except (TypeError, AttributeError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid settings in {path}: {error}") from error


def save_config(config, path=None):
    config.validate(check_files=False)
    path = path or state_directory() / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(config), indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def choose_accelerator(system, host_arch, guest_arch, available):
    if normalize_arch(host_arch) == normalize_arch(guest_arch):
        preferred = {"Linux": "kvm", "Darwin": "hvf", "Windows": "whpx"}.get(system)
        if preferred in available:
            return preferred
    if "tcg" in available:
        return "tcg"
    raise ValueError("No supported QEMU accelerator is available")


def executable(config):
    name = config.qemu or f"qemu-system-{normalize_arch(config.arch)}"
    if not config.qemu:
        packaged = bundled.binary(name)
        if packaged:
            return packaged
    candidates = [name]
    if not config.qemu:
        if platform.system() == "Darwin":
            candidates += [f"{directory}/{name}" for directory in ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin")]
        elif platform.system() == "Windows":
            program_files = os.environ.get("ProgramFiles", "C:/Program Files").replace("\\", "/")
            candidates.append(f"{program_files}/qemu/{name}.exe")
    for candidate in candidates:
        result = shutil.which(candidate)
        if result:
            return result
    raise ValueError(f"QEMU not found: {name}. Install QEMU or select its executable in Settings.")


def probe(config):
    binary = executable(config)
    result = run([binary, "-accel", "help"], timeout=10, check=True)
    available = set(result.stdout.split()) & {"kvm", "hvf", "whpx", "tcg"}
    if platform.system() == "Linux" and not os.access("/dev/kvm", os.R_OK | os.W_OK):
        available.discard("kvm")
    chosen = choose_accelerator(platform.system(), platform.machine(), config.arch, available)
    if config.accelerator != "auto":
        if config.accelerator not in available:
            raise ValueError(f"QEMU does not offer {config.accelerator} on this host")
        if config.accelerator != "tcg" and chosen != config.accelerator:
            raise ValueError("Hardware acceleration requires a matching host/guest architecture and platform")
        chosen = config.accelerator
    return binary, chosen


def build_command(config, binary, accelerator, vnc_port, qmp_port, websocket_port, adb_port=None,
                  camera_port=None, audio_driver=None):
    config.validate()
    if not 5900 <= vnc_port <= 65535:
        raise ValueError("VNC port must be at least 5900")
    arch = normalize_arch(config.arch)
    machine = "virt" if arch == "aarch64" else "q35"
    display = "virtio-gpu-pci" if arch == "aarch64" else "virtio-vga"
    cpu = select_cpu(accelerator, config.cpu_mode)
    accel = accelerator
    if accelerator == "tcg" and config.tcg_threads != "auto":
        accel = f"tcg,thread={config.tcg_threads}"
    # Both ADB and the camera ride the same user-mode network: the host side is
    # a reserved local port, the guest side a port the guest listens on.
    forwards = ""
    if adb_port:
        forwards += f",hostfwd=tcp:127.0.0.1:{adb_port}-:5555"
    if camera_port:
        forwards += f",hostfwd=tcp:127.0.0.1:{camera_port}-:{CAMERA_GUEST_PORT}"
    block = {"driver": config.disk_format, "node-name": "os",
             "file": {"driver": "file", "filename": str(Path(config.disk).resolve())}}
    cache = block_cache(config.disk_cache)
    if cache:
        block["cache"] = cache
    command = [binary, "-name", "AndroidBox", "-machine", machine, "-accel", accel,
               "-cpu", cpu, "-m", str(config.memory_mb), "-smp", str(config.cpus),
               "-blockdev", json.dumps(block), "-device", "virtio-blk-pci,drive=os,bootindex=0",
               "-vga", "none", "-device", display, "-device", "qemu-xhci", "-device", "usb-tablet",
               "-device", "usb-kbd", "-netdev",
               "user,id=net0" + forwards,
               "-device", "virtio-net-pci,netdev=net0",
               "-display", "none", "-vnc", f"127.0.0.1:{vnc_port - 5900},websocket=127.0.0.1:{websocket_port},password=on",
               "-qmp", f"tcp:127.0.0.1:{qmp_port},server=on,wait=off", "-monitor", "none", "-serial", "none"]
    command += audio_arguments(config, audio_driver)
    seed_iso = seed.seed_path_for(config.disk)
    if seed_iso.is_file():
        command += ["-blockdev", json.dumps({"driver": "raw", "read-only": True,
                                             "node-name": "cidata",
                                             "file": {"driver": "file",
                                                      "filename": str(seed_iso.resolve())}}),
                    "-device", "virtio-blk-pci,drive=cidata,bootindex=1"]
    images_disk = bundled.images_disk(arch)
    if images_disk:
        command += ["-blockdev", json.dumps({"driver": "raw", "read-only": True,
                                             "node-name": "androidbox-images",
                                             "file": {"driver": "file",
                                                      "filename": str(Path(images_disk).resolve())}}),
                    "-device", "virtio-blk-pci,drive=androidbox-images,bootindex=2"]
    data = bundled.qemu_data(binary)
    if data:
        command += ["-L", str(data)]
    firmware = config.resolved_firmware()
    if firmware:
        command += ["-bios", str(Path(firmware).resolve())]
    return command


def qmp_execute(port, command, arguments=None, timeout=2):
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as connection:
        with connection.makefile("rwb") as stream:
            greeting = json.loads(stream.readline())
            if "QMP" not in greeting:
                raise RuntimeError("Invalid QMP greeting")
            for index, (name, params) in enumerate([("qmp_capabilities", {}), (command, arguments or {})]):
                stream.write((json.dumps({"execute": name, "arguments": params, "id": index}) + "\n").encode())
                stream.flush()
                while True:
                    line = stream.readline()
                    if not line:
                        raise RuntimeError("QEMU closed the management connection")
                    reply = json.loads(line)
                    if reply.get("id") != index:
                        continue
                    if "error" in reply:
                        raise RuntimeError(reply["error"].get("desc", str(reply["error"])))
                    break
            return reply.get("return")


def reserve_ports(count):
    sockets = []
    try:
        while len(sockets) < count:
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            if listener.getsockname()[1] < 5900:
                listener.close()
                continue
            sockets.append(listener)
        return [listener.getsockname()[1] for listener in sockets]
    finally:
        for listener in sockets:
            listener.close()


class VirtualMachine:
    def __init__(self):
        self.process = None
        self.log = None
        self.qmp_port = None
        self.websocket_port = None
        self.password = None
        self.adb_port = None
        self.camera_port = None
        self.audio_driver = None
        self.audio_settings = None
        self.microphone_denied = False

    @property
    def running(self):
        return self.process is not None and self.process.poll() is None

    def start(self, config, binary, accelerator, log_path, audio_driver=None):
        if self.running:
            raise RuntimeError("AndroidBox is already running")
        (vnc_port, self.qmp_port, self.websocket_port, self.adb_port, self.camera_port) = reserve_ports(5)
        self.password = secrets.token_hex(4)  # VNC authentication uses eight characters.
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        attempts = list(start_attempts(config, audio_driver))
        for index, (settings, driver) in enumerate(attempts):
            command = build_command(settings, binary, accelerator, vnc_port, self.qmp_port,
                                    self.websocket_port, self.adb_port, self.camera_port,
                                    audio_driver=driver)
            self.log = log_path.open("wb")
            try:
                self.process = popen(command, stdin=subprocess.DEVNULL, stdout=self.log,
                                     stderr=subprocess.STDOUT)
            except Exception:
                self.close_log()
                raise
            if self.survives_startup():
                self.audio_settings = settings
                self.audio_driver = driver
                self.microphone_denied = (settings.microphone != "off"
                                          and self.log_mentions(AUDIO_CAPTURE_DENIED))
                return
            code = self.process.returncode if self.process is not None else None
            self.terminate()
            if index == len(attempts) - 1:
                raise RuntimeError(startup_failure_reason(log_path)
                                   or f"QEMU exited during startup ({code}); see the runtime log")

    def survives_startup(self, seconds=2.0):
        """True when QEMU stays alive for a moment after it was launched."""
        deadline = time.monotonic() + seconds
        while self.running:
            if time.monotonic() >= deadline:
                return True
            time.sleep(0.05)
        return False

    def describe_audio(self):
        """A short line naming the sound devices the guest actually received."""
        if not self.audio_driver:
            return "guest audio off"
        settings = self.audio_settings or VMConfig()
        devices = []
        if settings.audio != "off":
            devices.append("speakers")
        if settings.microphone != "off" and not self.microphone_denied:
            devices.append("microphone")
        line = f"{self.audio_driver}: " + (" and ".join(devices) if devices else "no device attached")
        if self.microphone_denied:
            line += "; the host withholds its microphone, so Android cannot hear it"
        return line

    def log_mentions(self, marker):
        """True when QEMU already wrote marker into the runtime log."""
        path = getattr(self.log, "name", None)
        if path is None:
            return False
        try:
            self.log.flush()
            return marker.encode("ascii") in Path(path).read_bytes()
        except OSError:
            return False

    def connect_display(self):
        qmp_execute(self.qmp_port, "set_password", {"protocol": "vnc", "password": self.password})

    def shutdown(self):
        if self.running:
            qmp_execute(self.qmp_port, "system_powerdown")

    def terminate(self):
        if self.running:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.close_log()

    def close_log(self):
        if self.log:
            self.log.close()
            self.log = None
