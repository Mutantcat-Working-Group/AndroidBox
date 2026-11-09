// One external camera device.
#include "cameradevice.h"

#include <android/log.h>

#include "cameradevicesession.h"
#include "framesource.h"

namespace androidbox {
namespace camera {

namespace {

constexpr const char* kLogTag = "androidbox-camera";

}  // namespace

CameraDevice::CameraDevice(std::string videoDevice) : videoDevice_(std::move(videoDevice)) {
    // The characteristics describe the sensor, and the only sensor is whatever
    // the loopback device happens to carry right now. Reading it once here keeps
    // the characteristics stable for the lifetime of the device object.
    FrameSource probe;
    if (probe.start(videoDevice_)) {
        sensorWidth_ = probe.width();
        sensorHeight_ = probe.height();
        probe.stop();
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
    auto session = ::ndk::SharedRefBase::make<CameraDeviceSession>(videoDevice_, sensorWidth_,
                                                                  sensorHeight_);
    ::ndk::ScopedAStatus status = session->start(in_callback);
    if (!status.isOk()) {
        __android_log_print(ANDROID_LOG_ERROR, kLogTag, "cannot start a session: %s",
                            status.getDescription().c_str());
        _aidl_return->reset();
        return status;
    }
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
