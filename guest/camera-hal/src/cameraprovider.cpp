// The camera provider service the Android camera framework talks to.
#include "cameraprovider.h"

#include <android/log.h>

#include "cameradevice.h"

namespace androidbox {
namespace camera {

namespace {

constexpr const char* kLogTag = "androidbox-camera";

void logInfo(const char* format, ...) {
    va_list args;
    va_start(args, format);
    __android_log_vprint(ANDROID_LOG_INFO, kLogTag, format, args);
    va_end(args);
}

}  // namespace

CameraProvider::CameraProvider(std::string videoDevice) : videoDevice_(std::move(videoDevice)) {}

::ndk::ScopedAStatus CameraProvider::setCallback(
        const std::shared_ptr<
                aidl::android::hardware::camera::provider::ICameraProviderCallback>& in_callback) {
    std::lock_guard<std::mutex> lock(mutex_);
    callback_ = in_callback;
    deviceAnnounced_ = false;
    announceDevice();
    return ::ndk::ScopedAStatus::ok();
}

void CameraProvider::announceDevice() {
    // Called with mutex_ held.
    if (callback_ == nullptr || deviceAnnounced_) {
        return;
    }
    // External cameras are not part of getCameraIdList(); the framework learns
    // about them through this callback instead.
    const auto status = callback_->cameraDeviceStatusChange(
            kDeviceName, aidl::android::hardware::camera::common::CameraDeviceStatus::PRESENT);
    if (status.isOk()) {
        deviceAnnounced_ = true;
        logInfo("announced %s as present", kDeviceName);
    } else {
        logInfo("announcing %s failed: %s", kDeviceName, status.getDescription().c_str());
    }
}

::ndk::ScopedAStatus CameraProvider::getVendorTags(
        std::vector<::aidl::android::hardware::camera::common::VendorTagSection>* _aidl_return) {
    _aidl_return->clear();
    return ::ndk::ScopedAStatus::ok();
}

::ndk::ScopedAStatus CameraProvider::getCameraIdList(std::vector<std::string>* _aidl_return) {
    // Deliberately empty: the external camera is reported through the callback.
    _aidl_return->clear();
    return ::ndk::ScopedAStatus::ok();
}

::ndk::ScopedAStatus CameraProvider::getCameraDeviceInterface(
        const std::string& in_cameraDeviceName,
        std::shared_ptr<::aidl::android::hardware::camera::device::ICameraDevice>* _aidl_return) {
    if (in_cameraDeviceName != kDeviceName) {
        logInfo("ignoring a request for unknown camera %s", in_cameraDeviceName.c_str());
        _aidl_return->reset();
        return ::ndk::ScopedAStatus::ok();
    }
    *_aidl_return = ::ndk::SharedRefBase::make<CameraDevice>(videoDevice_);
    return ::ndk::ScopedAStatus::ok();
}

::ndk::ScopedAStatus CameraProvider::notifyDeviceStateChange(int64_t /*in_deviceState*/) {
    // A folding state has no meaning for a webcam that never moves.
    return ::ndk::ScopedAStatus::ok();
}

::ndk::ScopedAStatus CameraProvider::getConcurrentCameraIds(
        std::vector<
                ::aidl::android::hardware::camera::provider::ConcurrentCameraIdCombination>*
                _aidl_return) {
    _aidl_return->clear();
    return ::ndk::ScopedAStatus::ok();
}

::ndk::ScopedAStatus CameraProvider::isConcurrentStreamCombinationSupported(
        const std::vector<
                ::aidl::android::hardware::camera::provider::CameraIdAndStreamCombination>&
        /*in_configs*/,
        bool* _aidl_return) {
    *_aidl_return = false;
    return ::ndk::ScopedAStatus::ok();
}

}  // namespace camera
}  // namespace androidbox
