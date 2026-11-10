#!/usr/bin/env bash
#
# Build the AndroidBox external camera provider.
#
# The provider is a stable AIDL HAL, which means the interface stubs are
# generated from the AIDL sources checked into guest/camera-hal/aidl with the
# NDK backend, then compiled against the Android NDK's clang for aarch64. There
# is deliberately no AOSP build system involved: everything the HAL needs comes
# from the NDK and the system libraries that are already inside the Android
# image.
#
# The build needs two host tools, both downloaded on demand and cached under
# guest/camera-hal/.deps:
#   * the Android NDK (for clang and the bionic/libc++ headers)
#   * the AIDL compiler from the Android build-tools (for the interface stubs)
#
# Set ANDROIDBOX_HAL_SKIP_DOWNLOADS=1 to fail fast instead of downloading, and
# ANDROID_NDK_HOME / AIDL_COMPILER to point at tools you already have.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AIDL_ROOT="${HERE}/aidl"
SRC_DIR="${HERE}/src"
BUILD_DIR="${HERE}/build"
DEPS_DIR="${HERE}/.deps"
GEN_DIR="${BUILD_DIR}/gen"

NDK_VERSION="r26c"
BUILD_TOOLS_VERSION="33.0.2"
API_LEVEL="33"
TRIPLE="aarch64-linux-android33"

log() { printf '[camera-hal] %s\n' "$*"; }
die() { printf '[camera-hal] %s\n' "$*" >&2; exit 1; }

HOST_OS="$(uname -s)"
case "${HOST_OS}" in
    Darwin) HOST_TAG="darwin-x86_64" ;;
    Linux) HOST_TAG="linux-x86_64" ;;
    *) die "unsupported build host ${HOST_OS}" ;;
esac
LLVM_DIR="${NDK_HOME_CACHE:-}"

# ---------------------------------------------------------------- NDK location
ndk_clang() { echo "$1/toolchains/llvm/prebuilt/${HOST_TAG}/bin/clang++"; }

find_ndk() {
    local candidate
    for candidate in "${ANDROID_NDK_HOME:-}" "${ANDROID_NDK_ROOT:-}" "${NDK_DIR:-}"; do
        if [[ -n "${candidate}" && -x "$(ndk_clang "${candidate}")" ]]; then
            echo "${candidate}"
            return 0
        fi
    done
    for candidate in "${HOME}/Library/Android/sdk/ndk"/* "${HOME}/Android/Sdk/ndk"/* \
                      /opt/android-sdk/ndk/* /usr/local/lib/android/sdk/ndk/*; do
        if [[ -x "$(ndk_clang "${candidate}")" ]]; then
            echo "${candidate}"
            return 0
        fi
    done
    for candidate in "${DEPS_DIR}"/android-ndk-*; do
        if [[ -x "$(ndk_clang "${candidate}")" ]]; then
            echo "${candidate}"
            return 0
        fi
    done
    return 1
}

download_ndk() {
    log "downloading the Android NDK ${NDK_VERSION} for ${HOST_TAG%%-*}"
    mkdir -p "${DEPS_DIR}"
    local archive="${DEPS_DIR}/android-ndk-${NDK_VERSION}-${HOST_TAG%%-*}.zip"
    curl -fSL --retry 3 -o "${archive}" \
        "https://dl.google.com/android/repository/android-ndk-${NDK_VERSION}-${HOST_TAG%%-*}.zip" \
        || die "could not download the NDK"
    (cd "${DEPS_DIR}" && unzip -q -o "${archive}")
    find_ndk
}

NDK_HOME="$(find_ndk || true)"
if [[ -z "${NDK_HOME}" ]]; then
    if [[ "${ANDROIDBOX_HAL_SKIP_DOWNLOADS:-0}" == "1" ]]; then
        die "the Android NDK is required; set ANDROID_NDK_HOME"
    fi
    NDK_HOME="$(download_ndk)" || die "could not obtain the Android NDK"
fi
CLANGXX="${NDK_HOME}/toolchains/llvm/prebuilt/${HOST_TAG}/bin/clang++"
[[ -x "${CLANGXX}" ]] || die "no clang++ in ${NDK_HOME}"
log "using NDK ${NDK_HOME}"

# ------------------------------------------------------------- AIDL compiler
find_aidl() {
    local candidate
    if [[ -n "${AIDL_COMPILER:-}" && -x "${AIDL_COMPILER}" ]]; then
        echo "${AIDL_COMPILER}"
        return 0
    fi
    # The build-tools archive unpacks to android-<API>/, not to a host name, so
    # the cached copy is found by searching rather than by a fixed path.
    if [[ -d "${DEPS_DIR}/build-tools" ]]; then
        candidate="$(find "${DEPS_DIR}/build-tools" -maxdepth 2 -type f -name aidl -perm -u+x 2>/dev/null | head -1)"
        if [[ -n "${candidate}" ]]; then
            echo "${candidate}"
            return 0
        fi
    fi
    for candidate in "${HOME}/Library/Android/sdk/build-tools"/* "${HOME}/Android/Sdk/build-tools"/* \
                     /opt/android-sdk/build-tools/*; do
        if [[ -x "${candidate}/aidl" ]]; then
            echo "${candidate}/aidl"
            return 0
        fi
    done
    return 1
}

AIDL="$(find_aidl || true)"
if [[ -z "${AIDL}" ]]; then
    if [[ "${ANDROIDBOX_HAL_SKIP_DOWNLOADS:-0}" == "1" ]]; then
        die "the AIDL compiler is required; set AIDL_COMPILER"
    fi
    log "downloading Android build-tools ${BUILD_TOOLS_VERSION} for ${HOST_TAG%%-*}"
    mkdir -p "${DEPS_DIR}"
    archive="${DEPS_DIR}/build-tools-${BUILD_TOOLS_VERSION}-${HOST_TAG%%-*}.zip"
    curl -fSL --retry 3 -o "${archive}" \
        "https://dl.google.com/android/repository/build-tools_r${BUILD_TOOLS_VERSION}-${HOST_TAG%%-*}.zip" \
        || die "could not download build-tools"
    # Match the archive's own android-<API>/ prefix explicitly: Linux unzip
    # does not let "*" cross a "/", so a bare '*/aidl' silently matches nothing
    # there even though it works on macOS.
    (cd "${DEPS_DIR}" && unzip -q -o "${archive}" 'android-*/aidl')
    AIDL="$(find_aidl || true)"
    [[ -n "${AIDL}" ]] || die "the build-tools archive has no aidl binary"
fi
log "using AIDL ${AIDL}"

# ------------------------------------------------------------------ generation
# aidl writes the NDK backend output under a leading "aidl" path and the plain
# C++ output under the bare package path; only the NDK output is needed here.
# Every AIDL file is passed in at once: aidl only emits headers for the files it
# is asked to compile, and the interfaces depend on the parcelables that live
# next to them. android.os.ParcelFileDescriptor is a built-in AIDL type that
# maps onto ndk::ScopedFileDescriptor, so it must not be declared here.
rm -rf "${GEN_DIR}"
mkdir -p "${GEN_DIR}/aidl"

# Word splitting is safe here: every path under aidl/ is ASCII without spaces.
set -- $(find "${AIDL_ROOT}" -name '*.aidl' | sort)
[[ $# -gt 0 ]] || die "no AIDL sources under ${AIDL_ROOT}"

log "generating stable AIDL stubs for $# AIDL files"
"${AIDL}" \
    --lang=ndk \
    --structured \
    --stability=vintf \
    --version=1 \
    -I "${AIDL_ROOT}" \
    -o "${GEN_DIR}/aidl" \
    -h "${GEN_DIR}/aidl" \
    "$@" \
    || die "aidl failed"
find "${GEN_DIR}/aidl" -name '*.cpp' > "${GEN_DIR}/sources.txt"
[[ -s "${GEN_DIR}/sources.txt" ]] || die "no stub sources were generated"

# -------------------------------------------------------------------- compile
CXXFLAGS=(
    "--target=${TRIPLE}"
    "-fPIC"
    "-fno-rtti"
    "-std=c++17"
    "-Wall"
    "-Wextra"
    "-Wno-unused-parameter"
    "-O2"
    "-g0"
    "-isystem" "${GEN_DIR}/aidl"
    "-I" "${SRC_DIR}"
)

# The HAL is a standalone /vendor binary, so libc++ is linked statically and the
# only shared dependencies are the system libraries it really calls into. The
# NDK's stub libraries carry only the stable client side of the binder and
# native window APIs, so a handful of symbols the HAL needs (the service
# registration entry points, and AHardwareBuffer_createFromHandle) stay
# undefined at link time and are resolved by the dynamic linker against the
# real /system/lib64 libraries the binary depends on.
LDFLAGS=(
    "--target=${TRIPLE}"
    "-static-libstdc++"
    "-Wl,--gc-sections"
    "-Wl,--unresolved-symbols=ignore-all"
    "-lbinder_ndk"
    "-lnativewindow"
    "-llog"
)

OBJ_DIR="${BUILD_DIR}/obj"
rm -rf "${OBJ_DIR}"
mkdir -p "${OBJ_DIR}"

SOURCES=()
while IFS= read -r source; do
    SOURCES+=("${source}")
done < "${GEN_DIR}/sources.txt"
for source in "${SRC_DIR}"/*.cpp; do
    SOURCES+=("${source}")
done

log "compiling ${#SOURCES[@]} translation units"
for source in "${SOURCES[@]}"; do
    object="${OBJ_DIR}/$(echo "${source}" | sed "s|${BUILD_DIR}/||; s|/|_|g").o"
    "${CLANGXX}" "${CXXFLAGS[@]}" -c "${source}" -o "${object}" \
        || die "compiling ${source} failed"
done

OUTPUT="${BUILD_DIR}/android.hardware.camera.provider@2.4-external-service"
log "linking ${OUTPUT##*/}"
"${CLANGXX}" "${LDFLAGS[@]}" "${OBJ_DIR}"/*.o -o "${OUTPUT}" || die "linking failed"

log "built ${OUTPUT}"
