// Encode the loopback camera's frames as JPEG for still capture.
//
// Camera apps ask for a BLOB output stream when the user takes a picture, and
// the loopback device carries planar YUV 4:2:0, so the HAL has to produce a
// baseline JPEG itself. Android does ship libjpeg, but only inside /system, and
// a vendor HAL may not link it, so this is a small self contained encoder using
// the standard Annex K tables. It only supports what the camera path needs:
// sequential baseline, 4:2:0, no restart markers, one scan.
#ifndef ANDROIDBOX_CAMERA_JPEG_H
#define ANDROIDBOX_CAMERA_JPEG_H

#include <cstddef>
#include <cstdint>
#include <vector>

namespace androidbox {
namespace camera {

// Encodes a planar YU12 frame as a baseline JPEG. quality is 1..100. Returns an
// empty vector when the frame is too small for its own dimensions.
std::vector<uint8_t> encodeJpegYu12(const uint8_t* yu12, uint32_t width, uint32_t height,
                                    uint32_t stride, int quality);

}  // namespace camera
}  // namespace androidbox

#endif  // ANDROIDBOX_CAMERA_JPEG_H
