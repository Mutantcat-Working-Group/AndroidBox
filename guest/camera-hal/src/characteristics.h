// The static camera characteristics this provider reports.
//
// Camera apps read the static characteristics before they open a device to
// decide what resolutions and controls exist, so an external camera has to
// describe itself even though there is no real sensor behind it. The tag set
// mirrors what AOSP's own external camera HAL reports, which keeps the
// framework's validation happy and keeps apps from asking for capabilities
// this camera cannot have.
#ifndef ANDROIDBOX_CAMERA_CHARACTERISTICS_H
#define ANDROIDBOX_CAMERA_CHARACTERISTICS_H

#include <cstdint>
#include <vector>

#include "metadata.h"

namespace androidbox {
namespace camera {

// Sizes this camera reports it can produce, widest first. The loopback device
// carries whatever the host webcam streams, and the HAL scales anything else,
// so the list is a menu rather than a truth table.
struct CameraSize {
    uint32_t width;
    uint32_t height;
};

const std::vector<CameraSize>& supportedSizes();

// Builds the static characteristics blob for the given sensor size.
std::vector<uint8_t> buildCharacteristics(uint32_t sensorWidth, uint32_t sensorHeight);

// Builds the default request settings for a template, which the framework uses
// as the base of every capture request.
std::vector<uint8_t> buildDefaultRequestSettings(int templateType);

}  // namespace camera
}  // namespace androidbox

#endif  // ANDROIDBOX_CAMERA_CHARACTERISTICS_H
