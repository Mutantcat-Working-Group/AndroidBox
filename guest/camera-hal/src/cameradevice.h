// One external camera device.
//
// The framework asks for the static characteristics before it opens the device,
// and then asks the session to do the work. This class holds the characteristics
// for the single camera the loopback device provides.
#ifndef ANDROIDBOX_CAMERA_DEVICE_H
#define ANDROIDBOX_CAMERA_DEVICE_H

#include <string>
#include <vector>

#include <aidl/android/hardware/camera/device/BnCameraDevice.h>

#include "characteristics.h"

namespace androidbox {
namespace camera {

class CameraDeviceSession;

class CameraDevice : public aidl::android::hardware::camera::device::BnCameraDevice {
public:
    explicit CameraDevice(std::string videoDevice);

    ::ndk::ScopedAStatus getCameraCharacteristics(
            ::aidl::android::hardware::camera::device::CameraMetadata* _aidl_return) override;
    ::ndk::ScopedAStatus getPhysicalCameraCharacteristics(
            const std::string& in_physicalCameraId,
            ::aidl::android::hardware::camera::device::CameraMetadata* _aidl_return) override;
    ::ndk::ScopedAStatus getResourceCost(
            ::aidl::android::hardware::camera::common::CameraResourceCost* _aidl_return) override;
    ::ndk::ScopedAStatus isStreamCombinationSupported(
            const ::aidl::android::hardware::camera::device::StreamConfiguration& in_streams,
            bool* _aidl_return) override;
    ::ndk::ScopedAStatus open(
            const std::shared_ptr<
                    ::aidl::android::hardware::camera::device::ICameraDeviceCallback>& in_callback,
            std::shared_ptr<::aidl::android::hardware::camera::device::ICameraDeviceSession>*
                    _aidl_return) override;
    ::ndk::ScopedAStatus openInjectionSession(
            const std::shared_ptr<
                    ::aidl::android::hardware::camera::device::ICameraDeviceCallback>& in_callback,
            std::shared_ptr<
                    ::aidl::android::hardware::camera::device::ICameraInjectionSession>* _aidl_return)
            override;
    ::ndk::ScopedAStatus setTorchMode(bool in_on) override;
    ::ndk::ScopedAStatus turnOnTorchWithStrengthLevel(int32_t in_torchStrength) override;
    ::ndk::ScopedAStatus getTorchStrengthLevel(int32_t* _aidl_return) override;

    // The size the loopback device currently carries, used for the
    // characteristics and for the sensor's active array.
    uint32_t sensorWidth() const { return sensorWidth_; }
    uint32_t sensorHeight() const { return sensorHeight_; }

private:
    std::string videoDevice_;
    uint32_t sensorWidth_ = 640;
    uint32_t sensorHeight_ = 480;
};

}  // namespace camera
}  // namespace androidbox

#endif  // ANDROIDBOX_CAMERA_DEVICE_H
