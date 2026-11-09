// The camera provider service the Android camera framework talks to.
//
// cameraservice finds this service by the instance name registered in
// /vendor/etc/vintf/manifest.xml and asks it for the list of cameras. Internal
// cameras live in that list; external cameras do not - they are announced
// separately through the provider callback, which is what this class does for
// the single external camera the loopback device provides.
#ifndef ANDROIDBOX_CAMERA_PROVIDER_H
#define ANDROIDBOX_CAMERA_PROVIDER_H

#include <memory>
#include <mutex>
#include <string>

#include <aidl/android/hardware/camera/provider/BnCameraProvider.h>

namespace androidbox {
namespace camera {

class CameraDevice;

class CameraProvider : public aidl::android::hardware::camera::provider::BnCameraProvider {
public:
    // The device name the framework expects, in the form
    // "device@<interface major>.<minor>/<type>/<id>".
    static constexpr const char* kDeviceName = "device@1.0/external/0";
    // The instance name this service registers as, matching the manifest.
    static constexpr const char* kServiceName =
            "android.hardware.camera.provider.ICameraProvider/external/0";

    explicit CameraProvider(std::string videoDevice);

    ::ndk::ScopedAStatus setCallback(
            const std::shared_ptr<aidl::android::hardware::camera::provider::ICameraProviderCallback>&
                    in_callback) override;
    ::ndk::ScopedAStatus getVendorTags(
            std::vector<::aidl::android::hardware::camera::common::VendorTagSection>* _aidl_return)
            override;
    ::ndk::ScopedAStatus getCameraIdList(std::vector<std::string>* _aidl_return) override;
    ::ndk::ScopedAStatus getCameraDeviceInterface(
            const std::string& in_cameraDeviceName,
            std::shared_ptr<::aidl::android::hardware::camera::device::ICameraDevice>* _aidl_return)
            override;
    ::ndk::ScopedAStatus notifyDeviceStateChange(int64_t in_deviceState) override;
    ::ndk::ScopedAStatus getConcurrentCameraIds(
            std::vector<::aidl::android::hardware::camera::provider::ConcurrentCameraIdCombination>*
                    _aidl_return) override;
    ::ndk::ScopedAStatus isConcurrentStreamCombinationSupported(
            const std::vector<
                    ::aidl::android::hardware::camera::provider::CameraIdAndStreamCombination>&
                    in_configs,
            bool* _aidl_return) override;

    const std::string& videoDevice() const { return videoDevice_; }

private:
    void announceDevice();

    std::string videoDevice_;
    std::mutex mutex_;
    std::shared_ptr<aidl::android::hardware::camera::provider::ICameraProviderCallback> callback_;
    bool deviceAnnounced_ = false;
};

}  // namespace camera
}  // namespace androidbox

#endif  // ANDROIDBOX_CAMERA_PROVIDER_H
