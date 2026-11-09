// Turn the loopback camera's frames into the pixels an output stream wants.
//
// The loopback device carries the host webcam as planar YUV 4:2:0 (V4L2
// V4L2_PIX_FMT_YU12) at whatever resolution the host chose. Camera apps,
// however, ask for RGBA or implementation defined surfaces at a size of their
// own, so every frame has to be scaled and converted on the way through. The
// conversion is deliberately simple - box sampling for the luma plane and
// nearest neighbour for chroma - because the frames are small and a dropped
// frame is worse than a slightly soft one.
#ifndef ANDROIDBOX_CAMERA_PIXELS_H
#define ANDROIDBOX_CAMERA_PIXELS_H

#include <cstddef>
#include <cstdint>

namespace androidbox {
namespace camera {

// Copies a YU12 frame into a tightly packed RGBA8888 buffer of outWidth by
// outHeight pixels, scaling when the sizes differ. Returns false when the input
// is too small for its own dimensions.
bool convertYu12ToRgba(const uint8_t* yu12, uint32_t width, uint32_t height, uint32_t stride,
                       uint32_t outWidth, uint32_t outHeight, uint8_t* rgba);

// Bytes one RGBA frame of the given size needs.
inline size_t rgbaSize(uint32_t width, uint32_t height) {
    return static_cast<size_t>(width) * height * 4;
}

}  // namespace camera
}  // namespace androidbox

#endif  // ANDROIDBOX_CAMERA_PIXELS_H
