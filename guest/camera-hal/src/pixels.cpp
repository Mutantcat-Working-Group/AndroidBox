// Turn the loopback camera's frames into the pixels an output stream wants.
#include "pixels.h"

#include <algorithm>

namespace androidbox {
namespace camera {

namespace {

// Full range BT.601 YUV to RGB, the conversion the host's webcam frames use.
inline void yuvToRgba(uint8_t y, uint8_t u, uint8_t v, uint8_t* out) {
    const int c = static_cast<int>(y) - 16;
    const int d = static_cast<int>(u) - 128;
    const int e = static_cast<int>(v) - 128;
    int r = (298 * c + 409 * e + 128) >> 8;
    int g = (298 * c - 100 * d - 208 * e + 128) >> 8;
    int b = (298 * c + 516 * d + 128) >> 8;
    out[0] = static_cast<uint8_t>(std::min(255, std::max(0, r)));
    out[1] = static_cast<uint8_t>(std::min(255, std::max(0, g)));
    out[2] = static_cast<uint8_t>(std::min(255, std::max(0, b)));
    out[3] = 0xff;
}

}  // namespace

bool convertYu12ToRgba(const uint8_t* yu12, uint32_t width, uint32_t height, uint32_t stride,
                       uint32_t outWidth, uint32_t outHeight, uint8_t* rgba) {
    if (width == 0 || height == 0 || outWidth == 0 || outHeight == 0) {
        return false;
    }
    const size_t plane = static_cast<size_t>(stride) * height;
    const uint8_t* yPlane = yu12;
    const uint8_t* uPlane = yu12 + plane;
    const uint8_t* vPlane = uPlane + plane / 4;
    const uint32_t chromaStride = stride / 2;
    const uint32_t chromaHeight = height / 2;

    for (uint32_t row = 0; row < outHeight; ++row) {
        // Box sampling over the source rows that map onto this output row keeps
        // a downscaled frame from dropping most of the detail.
        const uint32_t firstRow = row * height / outHeight;
        const uint32_t lastRow = (row + 1) * height / outHeight;
        uint8_t* out = rgba + static_cast<size_t>(row) * outWidth * 4;
        for (uint32_t column = 0; column < outWidth; ++column) {
            const uint32_t firstColumn = column * width / outWidth;
            const uint32_t lastColumn = (column + 1) * width / outWidth;
            uint32_t ySum = 0;
            uint32_t yCount = 0;
            for (uint32_t sourceRow = firstRow; sourceRow < lastRow; ++sourceRow) {
                const uint8_t* line = yPlane + static_cast<size_t>(sourceRow) * stride;
                for (uint32_t sourceColumn = firstColumn; sourceColumn < lastColumn;
                     ++sourceColumn) {
                    ySum += line[sourceColumn];
                    ++yCount;
                }
            }
            const uint32_t chromaRow =
                    std::min(chromaHeight - 1, (firstRow + lastRow) / 2 / 2);
            const uint32_t chromaColumn =
                    std::min(chromaStride - 1, (firstColumn + lastColumn) / 2 / 2);
            const uint8_t u = uPlane[static_cast<size_t>(chromaRow) * chromaStride + chromaColumn];
            const uint8_t v = vPlane[static_cast<size_t>(chromaRow) * chromaStride + chromaColumn];
            yuvToRgba(static_cast<uint8_t>(yCount ? ySum / yCount : 0), u, v, out);
            out += 4;
        }
    }
    return true;
}

}  // namespace camera
}  // namespace androidbox
