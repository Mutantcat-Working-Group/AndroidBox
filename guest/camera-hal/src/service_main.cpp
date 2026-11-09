// Entry point for the AndroidBox external camera provider.
//
// The provider is started by init from /vendor/bin/hw as a normal vendor HAL
// service, registers itself under the instance name declared in
// /vendor/etc/vintf/manifest.xml, and then serves binder calls from
// cameraservice for as long as the container lives.
#include <android/log.h>

#include <string>

#include "cameraprovider.h"

namespace {

constexpr const char* kLogTag = "androidbox-camera";

// The loopback device the guest's support layer feeds from the host webcam.
constexpr const char* kDefaultVideoDevice = "/dev/video0";

// These live in libbinder_ndk but not in the NDK headers, which only cover the
// stable client side of the binder API.
extern "C" void ABinderProcess_startThreadPool();
extern "C" bool ABinderProcess_joinThreadPool();
extern "C" binder_exception_t AServiceManager_addService(AIBinder* binder, const char* instance);

}  // namespace

int main(int argc, char** argv) {
    std::string videoDevice = kDefaultVideoDevice;
    for (int i = 1; i < argc; ++i) {
        const std::string argument = argv[i];
        const std::string prefix = "--device=";
        if (argument.rfind(prefix, 0) == 0) {
            videoDevice = argument.substr(prefix.size());
        }
    }

    __android_log_print(ANDROID_LOG_INFO, kLogTag, "starting the external camera provider on %s",
                        videoDevice.c_str());

    auto provider = ::ndk::SharedRefBase::make<androidbox::camera::CameraProvider>(videoDevice);
    const binder_exception_t registered = AServiceManager_addService(
            provider->asBinder().get(), androidbox::camera::CameraProvider::kServiceName);
    if (registered != EX_NONE) {
        __android_log_print(ANDROID_LOG_ERROR, kLogTag, "cannot register %s: %d",
                            androidbox::camera::CameraProvider::kServiceName,
                            static_cast<int>(registered));
        return 1;
    }

    ABinderProcess_startThreadPool();
    ABinderProcess_joinThreadPool();
    return 0;
}
