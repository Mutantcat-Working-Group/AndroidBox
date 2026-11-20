// One external camera device.
#include "cameradevice.h"

#include <errno.h>
#include <fcntl.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

#include <android/log.h>
#include <linux/videodev2.h>

#include "cameradevicesession.h"

namespace androidbox {
namespace camera {

namespace {

constexpr const char* kLogTag = "androidbox-camera";
constexpr uint32_t kDefaultSensorWidth = 640;
constexpr uint32_t kDefaultSensorHeight = 480;

// Reads the size the loopback device currently carries. Only opens the node and
// reads its format: requesting buffers or starting the stream here would fight
// the writer on the other side of the loopback device, which is the session's
// job and only once the framework really wants frames.
bool querySensorFormat(const std::string& device, uint32_t* width, uint32_t* height) {
    const int fd = open(device.c_str(), O_RDWR | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) {
        __android_log_print(ANDROID_LOG_WARN, kLogTag, "cannot open %s: %s", device.c_str(),
                            strerror(errno));
        return false;
    }
    bool ok = false;
    struct v4l2_capability capability = {};
    if (ioctl(fd, VIDIOC_QUERYCAP, &capability) == 0 &&
        (capability.capabilities & V4L2_CAP_VIDEO_CAPTURE) != 0) {
        struct v4l2_format format = {};
        format.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        // Before the writer has picked a format the node answers EINVAL; that is
        // not an error, it just means there is nothing to read yet.
        if (ioctl(fd, VIDIOC_G_FMT, &format) == 0) {
            const uint32_t w = format.fmt.pix.width;
            const uint32_t h = format.fmt.pix.height;
            if (w != 0 && h != 0 && w <= 8192 && h <= 8192) {
                *width = w;
                *height = h;
                ok = true;
            }
        }
    }
    close(fd);
    return ok;
}

}  // namespace

CameraDevice::CameraDevice(std::string videoDevice) : videoDevice_(std::move(videoDevice)) {
    // The characteristics describe the sensor, and the only sensor is whatever
    // the loopback device happens to carry right now. Reading it once here keeps
    // the characteristics stable for the lifetime of the device object.
    if (querySensorFormat(videoDevice_, &sensorWidth_, &sensorHeight_)) {
        __android_log_print(ANDROID_LOG_INFO, kLogTag, "%s carries %ux%u", videoDevice_.c_str(),
                            sensorWidth_, sensorHeight_);
    } else {
        sensorWidth_ = kDefaultSensorWidth;
        sensorHeight_ = kDefaultSensorHeight;
        __android_log_print(ANDROID_LOG_INFO, kLogTag,
                            "%s carries no format yet; assuming %ux%u", videoDevice_.c_str(),
                            sensorWidth_, sensorHeight_);
    }
}

::ndk::ScopedAStatus CameraDevice::getCameraCharacteristics(
        ::aidl::android::hardware::camera::device::CameraMetadata* _aidl_return) {
    _aidl_return->metadata = buildCharacteristics(sensorWidth_, sensorHeight_);
    return ::ndk::ScopedAStatus::ok();
}

::ndk::ScopedAStatus CameraDevice::getPhysicalCameraCharacteristics(
        const std::string& /*in_physicalCameraId*/,
        ::aidl::android::hardware::camera::device::CameraMetadata* _aidl_return) {
    // There is no logical camera behind this device, so there are no physical
    // cameras to describe.
    _aidl_return->metadata.clear();
    return ::ndk::ScopedAStatus::fromExceptionCode(EX_ILLEGAL_ARGUMENT);
}

::ndk::ScopedAStatus CameraDevice::getResourceCost(
        ::aidl::android::hardware::camera::common::CameraResourceCost* _aidl_return) {
    _aidl_return->resourceCost = 0;
    _aidl_return->conflictingDevices = {};
    return ::ndk::ScopedAStatus::ok();
}

::ndk::ScopedAStatus CameraDevice::isStreamCombinationSupported(
        const ::aidl::android::hardware::camera::device::StreamConfiguration& /*in_streams*/,
        bool* _aidl_return) {
    // Every combination we advertise in the characteristics is supported, and
    // anything else is rejected later by configureStreams anyway.
    *_aidl_return = true;
    return ::ndk::ScopedAStatus::ok();
}

::ndk::ScopedAStatus CameraDevice::open(
        const std::shared_ptr<::aidl::android::hardware::camera::device::ICameraDeviceCallback>&
                in_callback,
        std::shared_ptr<::aidl::android::hardware::camera::device::ICameraDeviceSession>*
                _aidl_return) {
    std::lock_guard<std::mutex> lock(sessionMutex_);
    // Only one session may own the loopback device at a time. A second open
    // without a close in between (the framework retries, an app restarts) would
    // otherwise leave two frame sources streaming the same node.
    if (auto previous = session_.lock()) {
        __android_log_print(ANDROID_LOG_INFO, kLogTag, "closing the previous session");
        previous->close();
    }
    session_.reset();
    auto session = ::ndk::SharedRefBase::make<CameraDeviceSession>(videoDevice_, sensorWidth_,
                                                                  sensorHeight_);
    ::ndk::ScopedAStatus status = session->start(in_callback);
    if (!status.isOk()) {
        __android_log_print(ANDROID_LOG_ERROR, kLogTag, "cannot start a session: %s",
                            status.getDescription().c_str());
        _aidl_return->reset();
        return status;
    }
    session_ = session;
    *_aidl_return = session;
    return ::ndk::ScopedAStatus::ok();
}

::ndk::ScopedAStatus CameraDevice::openInjectionSession(
        const std::shared_ptr<::aidl::android::hardware::camera::device::ICameraDeviceCallback>&
        /*in_callback*/,
        std::shared_ptr<::aidl::android::hardware::camera::device::ICameraInjectionSession>*
                _aidl_return) {
    // Injection is for testing the framework itself; there is nothing to inject.
    _aidl_return->reset();
    return ::ndk::ScopedAStatus::fromExceptionCode(EX_UNSUPPORTED_OPERATION);
}

::ndk::ScopedAStatus CameraDevice::setTorchMode(bool /*in_on*/) {
    // A webcam has no torch.
    return ::ndk::ScopedAStatus::fromExceptionCode(EX_UNSUPPORTED_OPERATION);
}

::ndk::ScopedAStatus CameraDevice::turnOnTorchWithStrengthLevel(int32_t /*in_torchStrength*/) {
    return ::ndk::ScopedAStatus::fromExceptionCode(EX_UNSUPPORTED_OPERATION);
}

::ndk::ScopedAStatus CameraDevice::getTorchStrengthLevel(int32_t* _aidl_return) {
    *_aidl_return = 0;
    return ::ndk::ScopedAStatus::fromExceptionCode(EX_UNSUPPORTED_OPERATION);
}

}  // namespace camera
}  // namespace androidbox
