// Encode the loopback camera's frames as JPEG for still capture.
#include "jpeg.h"

#include <cmath>
#include <cstring>

namespace androidbox {
namespace camera {

namespace {

constexpr int kBlockSize = 8;
constexpr int kDctSize = kBlockSize * kBlockSize;

// Annex K quantisation tables, quality 50.
const uint8_t kLumaQuant[64] = {
    16, 11, 10, 16, 24,  40,  51,  61,  12, 12, 14, 19, 26,  58,  60,  55,
    14, 13, 16, 24, 40,  57,  69,  56,  14, 17, 22, 29, 51,  87,  80,  62,
    18, 22, 37, 56, 68,  109, 103, 77,  24, 35, 55, 64, 81,  104, 113, 92,
    49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99,
};

const uint8_t kChromaQuant[64] = {
    17, 18, 24, 47, 99, 99, 99, 99, 18, 21, 26, 66, 99, 99, 99, 99,
    24, 26, 56, 99, 99, 99, 99, 99, 47, 66, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99,
};

// Annex K Huffman tables.
const uint8_t kDcLumaBits[17] = {0, 0, 1, 5, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0};
const uint8_t kDcLumaValues[12] = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11};
const uint8_t kDcChromaBits[17] = {0, 0, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0};
const uint8_t kDcChromaValues[12] = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11};

const uint8_t kAcLumaBits[17] = {0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7d, 0};
const uint8_t kAcLumaValues[162] = {
    0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06, 0x13, 0x51, 0x61,
    0x07, 0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xa1, 0x08, 0x23, 0x42, 0xb1, 0xc1, 0x15, 0x52,
    0xd1, 0xf0, 0x24, 0x33, 0x62, 0x72, 0x82, 0x09, 0x0a, 0x16, 0x17, 0x18, 0x19, 0x1a, 0x25,
    0x26, 0x27, 0x28, 0x29, 0x2a, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3a, 0x43, 0x44, 0x45,
    0x46, 0x47, 0x48, 0x49, 0x4a, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59, 0x5a, 0x63, 0x64,
    0x65, 0x66, 0x67, 0x68, 0x69, 0x6a, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79, 0x7a, 0x83,
    0x84, 0x85, 0x86, 0x87, 0x88, 0x89, 0x8a, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99,
    0x9a, 0xa2, 0xa3, 0xa4, 0xa5, 0xa6, 0xa7, 0xa8, 0xa9, 0xaa, 0xb2, 0xb3, 0xb4, 0xb5, 0xb6,
    0xb7, 0xb8, 0xb9, 0xba, 0xc2, 0xc3, 0xc4, 0xc5, 0xc6, 0xc7, 0xc8, 0xc9, 0xca, 0xd2, 0xd3,
    0xd4, 0xd5, 0xd6, 0xd7, 0xd8, 0xd9, 0xda, 0xe1, 0xe2, 0xe3, 0xe4, 0xe5, 0xe6, 0xe7, 0xe8,
    0xe9, 0xea, 0xf1, 0xf2, 0xf3, 0xf4, 0xf5, 0xf6, 0xf7, 0xf8, 0xf9, 0xfa,
};

const uint8_t kAcChromaBits[17] = {0, 2, 1, 2, 4, 4, 3, 4, 7, 5, 4, 4, 0, 1, 2, 0x77, 0};
const uint8_t kAcChromaValues[162] = {
    0x00, 0x01, 0x02, 0x03, 0x11, 0x04, 0x05, 0x21, 0x31, 0x06, 0x12, 0x41, 0x51, 0x07, 0x61,
    0x71, 0x13, 0x22, 0x32, 0x81, 0x08, 0x14, 0x42, 0x91, 0xa1, 0xb1, 0xc1, 0x09, 0x23, 0x33,
    0x52, 0xf0, 0x15, 0x62, 0x72, 0xd1, 0x0a, 0x16, 0x24, 0x34, 0xe1, 0x25, 0xf1, 0x17, 0x18,
    0x19, 0x1a, 0x26, 0x27, 0x28, 0x29, 0x2a, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3a, 0x43, 0x44,
    0x45, 0x46, 0x47, 0x48, 0x49, 0x4a, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59, 0x5a, 0x63,
    0x64, 0x65, 0x66, 0x67, 0x68, 0x69, 0x6a, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79, 0x7a,
    0x82, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89, 0x8a, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97,
    0x98, 0x99, 0x9a, 0xa2, 0xa3, 0xa4, 0xa5, 0xa6, 0xa7, 0xa8, 0xa9, 0xaa, 0xb2, 0xb3, 0xb4,
    0xb5, 0xb6, 0xb7, 0xb8, 0xb9, 0xba, 0xc2, 0xc3, 0xc4, 0xc5, 0xc6, 0xc7, 0xc8, 0xc9, 0xca,
    0xd2, 0xd3, 0xd4, 0xd5, 0xd6, 0xd7, 0xd8, 0xd9, 0xda, 0xe2, 0xe3, 0xe4, 0xe5, 0xe6, 0xe7,
    0xe8, 0xe9, 0xea, 0xf2, 0xf3, 0xf4, 0xf5, 0xf6, 0xf7, 0xf8, 0xf9, 0xfa,
};

// Zigzag order of the 64 coefficients, as indices into the natural order.
const uint8_t kZigZag[64] = {
     0,  1,  8, 16,  9,  2,  3, 10,
    17, 24, 32, 25, 18, 11,  4,  5,
    12, 19, 26, 33, 40, 48, 41, 34,
    27, 20, 13,  6,  7, 14, 21, 28,
    35, 42, 49, 56, 57, 50, 43, 36,
    29, 22, 15, 23, 30, 37, 44, 51,
    58, 59, 52, 45, 38, 31, 39, 46,
    53, 60, 61, 54, 47, 55, 62, 63,
};

struct HuffmanTable {
    uint16_t code[256];
    uint8_t size[256];

    void build(const uint8_t* bits, const uint8_t* values) {
        memset(code, 0, sizeof(code));
        memset(size, 0, sizeof(size));
        uint16_t huffmanCode = 0;
        int valueIndex = 0;
        for (int length = 1; length <= 16; ++length) {
            for (int i = 0; i < bits[length]; ++i) {
                code[values[valueIndex]] = huffmanCode;
                size[values[valueIndex]] = static_cast<uint8_t>(length);
                ++huffmanCode;
                ++valueIndex;
            }
            huffmanCode <<= 1;
        }
    }
};

class BitWriter {
public:
    void putBits(uint16_t bits, uint8_t count) {
        for (int i = count - 1; i >= 0; --i) {
            buffer_ = (buffer_ << 1) | ((bits >> i) & 1);
            ++bitCount_;
            if (bitCount_ == 8) {
                flushByte();
            }
        }
    }

    void flush() {
        // Pad the final partial byte with ones, the convention decoders expect.
        while (bitCount_ != 0) {
            putBits(1, 1);
        }
    }

    std::vector<uint8_t> take() {
        flush();
        return std::move(bytes_);
    }

private:
    void flushByte() {
        bytes_.push_back(static_cast<uint8_t>(buffer_ & 0xff));
        bitCount_ = 0;
        buffer_ = 0;
        // A zero byte follows every 0xff so the entropy coded data cannot be
        // mistaken for a marker.
        if (bytes_.back() == 0xff) {
            bytes_.push_back(0x00);
        }
    }

    uint32_t buffer_ = 0;
    int bitCount_ = 0;
    std::vector<uint8_t> bytes_;
};

float gCosineTable[kBlockSize][kBlockSize];
bool gCosineReady = false;

void buildCosineTable() {
    for (int u = 0; u < kBlockSize; ++u) {
        for (int x = 0; x < kBlockSize; ++x) {
            const double angle = (2 * x + 1) * u * M_PI / 16.0;
            const double scale = (u == 0) ? (1.0 / std::sqrt(2.0)) : 1.0;
            gCosineTable[u][x] = static_cast<float>(std::cos(angle) * scale * 0.5);
        }
    }
}

// Separable forward DCT: rows first, then columns, both with the same table.
void forwardDct(float block[kDctSize]) {
    float intermediate[kDctSize];
    for (int y = 0; y < kBlockSize; ++y) {
        for (int u = 0; u < kBlockSize; ++u) {
            float sum = 0.0f;
            for (int x = 0; x < kBlockSize; ++x) {
                sum += block[y * kBlockSize + x] * gCosineTable[u][x];
            }
            intermediate[y * kBlockSize + u] = sum;
        }
    }
    for (int u = 0; u < kBlockSize; ++u) {
        for (int v = 0; v < kBlockSize; ++v) {
            float sum = 0.0f;
            for (int y = 0; y < kBlockSize; ++y) {
                sum += intermediate[y * kBlockSize + u] * gCosineTable[v][y];
            }
            block[v * kBlockSize + u] = sum;
        }
    }
}

int magnitudeCategory(int value) {
    int category = 0;
    int magnitude = value < 0 ? -value : value;
    while (magnitude > 0) {
        magnitude >>= 1;
        ++category;
    }
    return category;
}

void writeMagnitude(BitWriter& writer, int value) {
    const int category = magnitudeCategory(value);
    if (category == 0) {
        return;
    }
    // Negative values are stored as the one's complement of their magnitude.
    const uint16_t bits =
            value > 0 ? static_cast<uint16_t>(value)
                      : static_cast<uint16_t>(value - 1) & static_cast<uint16_t>((1 << category) - 1);
    writer.putBits(bits, static_cast<uint8_t>(category));
}

struct Encoder {
    BitWriter entropy;
    HuffmanTable dcLuma;
    HuffmanTable acLuma;
    HuffmanTable dcChroma;
    HuffmanTable acChroma;
    uint16_t quantLuma[64];
    uint16_t quantChroma[64];
    int dcPredictor[3] = {0, 0, 0};

    void scaleQuantTables(int quality) {
        int clamped = quality < 1 ? 1 : (quality > 100 ? 100 : quality);
        const int scale = clamped < 50 ? 5000 / clamped : 200 - clamped * 2;
        for (int i = 0; i < 64; ++i) {
            long value = (kLumaQuant[i] * scale + 50) / 100;
            quantLuma[i] = static_cast<uint16_t>(value < 1 ? 1 : (value > 255 ? 255 : value));
            value = (kChromaQuant[i] * scale + 50) / 100;
            quantChroma[i] = static_cast<uint16_t>(value < 1 ? 1 : (value > 255 ? 255 : value));
        }
    }

    // component: 0 luma, 1 and 2 chroma.
    // Encodes one 8x8 block. samples points at the block's top left pixel,
    // stride is the plane stride, and validWidth/validHeight say how much of
    // the block is inside the image; anything beyond is filled by repeating the
    // last real pixel, the padding baseline JPEG expects.
    void encodeBlock(const uint8_t* samples, uint32_t stride, uint32_t validWidth,
                     uint32_t validHeight, int component) {
        float block[kDctSize];
        for (int y = 0; y < kBlockSize; ++y) {
            const uint32_t sy = y < validHeight ? y : validHeight - 1;
            for (int x = 0; x < kBlockSize; ++x) {
                const uint32_t sx = x < validWidth ? x : validWidth - 1;
                block[y * kBlockSize + x] =
                        static_cast<float>(samples[static_cast<size_t>(sy) * stride + sx]) - 128.0f;
            }
        }
        forwardDct(block);
        const uint16_t* quant = component == 0 ? quantLuma : quantChroma;
        int16_t coefficients[64];
        for (int i = 0; i < 64; ++i) {
            const float value = block[i] / static_cast<float>(quant[i]);
            coefficients[i] = static_cast<int16_t>(value < 0 ? value - 0.5f : value + 0.5f);
        }

        const HuffmanTable& dcTable = component == 0 ? dcLuma : dcChroma;
        const HuffmanTable& acTable = component == 0 ? acLuma : acChroma;

        const int difference = coefficients[0] - dcPredictor[component];
        dcPredictor[component] = coefficients[0];
        const int dcCategory = magnitudeCategory(difference);
        entropy.putBits(dcTable.code[dcCategory], dcTable.size[dcCategory]);
        writeMagnitude(entropy, difference);

        int runLength = 0;
        for (int zigZag = 1; zigZag < 64; ++zigZag) {
            const int coefficient = coefficients[kZigZag[zigZag]];
            if (coefficient == 0) {
                ++runLength;
                continue;
            }
            while (runLength > 15) {
                entropy.putBits(acTable.code[0xf0], acTable.size[0xf0]);
                runLength -= 16;
            }
            const int category = magnitudeCategory(coefficient);
            const uint8_t symbol = static_cast<uint8_t>((runLength << 4) | category);
            entropy.putBits(acTable.code[symbol], acTable.size[symbol]);
            writeMagnitude(entropy, coefficient);
            runLength = 0;
        }
        if (runLength > 0) {
            entropy.putBits(acTable.code[0x00], acTable.size[0x00]);
        }
    }
};

void put16(std::vector<uint8_t>& out, uint16_t value) {
    out.push_back(static_cast<uint8_t>(value >> 8));
    out.push_back(static_cast<uint8_t>(value & 0xff));
}

void putMarker(std::vector<uint8_t>& out, uint8_t marker) {
    out.push_back(0xff);
    out.push_back(marker);
}

void putQuantTable(std::vector<uint8_t>& out, uint8_t tableId, const uint16_t* table) {
    putMarker(out, 0xdb);  // DQT
    put16(out, 2 + 64);
    out.push_back(tableId);
    for (int i = 0; i < 64; ++i) {
        out.push_back(static_cast<uint8_t>(table[kZigZag[i]]));
    }
}

void putHuffmanTable(std::vector<uint8_t>& out, uint8_t tableClass, uint8_t tableId,
                     const uint8_t* bits, const uint8_t* values, size_t valueCount) {
    putMarker(out, 0xc4);  // DHT
    put16(out, static_cast<uint16_t>(2 + 1 + 16 + valueCount));
    out.push_back(static_cast<uint8_t>((tableClass << 4) | tableId));
    for (int i = 1; i <= 16; ++i) {
        out.push_back(bits[i]);
    }
    for (size_t i = 0; i < valueCount; ++i) {
        out.push_back(values[i]);
    }
}

}  // namespace

std::vector<uint8_t> encodeJpegYu12(const uint8_t* yu12, uint32_t width, uint32_t height,
                                    uint32_t stride, int quality) {
    if (width == 0 || height == 0) {
        return {};
    }
    if (!gCosineReady) {
        buildCosineTable();
        gCosineReady = true;
    }

    Encoder encoder;
    encoder.scaleQuantTables(quality);
    encoder.dcLuma.build(kDcLumaBits, kDcLumaValues);
    encoder.acLuma.build(kAcLumaBits, kAcLumaValues);
    encoder.dcChroma.build(kDcChromaBits, kDcChromaValues);
    encoder.acChroma.build(kAcChromaBits, kAcChromaValues);

    const size_t plane = static_cast<size_t>(stride) * height;
    const uint8_t* yPlane = yu12;
    const uint8_t* uPlane = yu12 + plane;
    const uint8_t* vPlane = uPlane + plane / 4;

    // One MCU covers 16 by 16 source pixels: four luma blocks then one of each
    // chroma plane, subsampled two to one in both directions.
    const uint32_t mcuColumns = (width + 15) / 16;
    const uint32_t mcuRows = (height + 15) / 16;
    for (uint32_t mcuRow = 0; mcuRow < mcuRows; ++mcuRow) {
        for (uint32_t mcuColumn = 0; mcuColumn < mcuColumns; ++mcuColumn) {
            for (int index = 0; index < 4; ++index) {
                const uint32_t blockColumn = mcuColumn * 2 + (index % 2);
                const uint32_t blockRow = mcuRow * 2 + (index / 2);
                const uint32_t originX = blockColumn * kBlockSize;
                const uint32_t originY = blockRow * kBlockSize;
                const uint32_t validWidth = originX < width ? (width - originX < 8 ? width - originX : 8) : 1;
                const uint32_t validHeight =
                        originY < height ? (height - originY < 8 ? height - originY : 8) : 1;
                encoder.encodeBlock(yPlane + static_cast<size_t>(originY) * stride + originX, stride,
                                    validWidth, validHeight, 0);
            }
            const uint32_t chromaStride = stride / 2;
            const uint32_t chromaWidth = width / 2;
            const uint32_t chromaHeight = height / 2;
            const uint32_t chromaOriginX = mcuColumn * kBlockSize;
            const uint32_t chromaOriginY = mcuRow * kBlockSize;
            const uint32_t chromaValidWidth =
                    chromaOriginX < chromaWidth
                            ? (chromaWidth - chromaOriginX < 8 ? chromaWidth - chromaOriginX : 8)
                            : 1;
            const uint32_t chromaValidHeight =
                    chromaOriginY < chromaHeight
                            ? (chromaHeight - chromaOriginY < 8 ? chromaHeight - chromaOriginY : 8)
                            : 1;
            const size_t chromaOffset =
                    static_cast<size_t>(chromaOriginY) * chromaStride + chromaOriginX;
            encoder.encodeBlock(uPlane + chromaOffset, chromaStride, chromaValidWidth,
                                chromaValidHeight, 1);
            encoder.encodeBlock(vPlane + chromaOffset, chromaStride, chromaValidWidth,
                                chromaValidHeight, 2);
        }
    }

    std::vector<uint8_t> entropyCoded = encoder.entropy.take();

    std::vector<uint8_t> out;
    out.reserve(entropyCoded.size() + 1024);
    putMarker(out, 0xd8);  // SOI
    putMarker(out, 0xe0);  // APP0, the JFIF marker decoders look for.
    put16(out, 16);
    out.push_back('J');
    out.push_back('F');
    out.push_back('I');
    out.push_back('F');
    out.push_back(0);
    out.push_back(1);
    out.push_back(1);
    out.push_back(0);
    put16(out, 1);
    put16(out, 1);
    out.push_back(0);
    out.push_back(0);

    putQuantTable(out, 0, encoder.quantLuma);
    putQuantTable(out, 1, encoder.quantChroma);

    putMarker(out, 0xc0);  // SOF0, baseline sequential.
    put16(out, 17);
    out.push_back(8);  // Sample precision.
    put16(out, static_cast<uint16_t>(height));
    put16(out, static_cast<uint16_t>(width));
    out.push_back(3);  // Three components.
    out.push_back(1);  // Y
    out.push_back(0x22);  // 2x2 sampling.
    out.push_back(0);
    out.push_back(2);  // Cb
    out.push_back(0x11);  // 1x1 sampling.
    out.push_back(1);
    out.push_back(3);  // Cr
    out.push_back(0x11);
    out.push_back(1);

    putHuffmanTable(out, 0, 0, kDcLumaBits, kDcLumaValues, sizeof(kDcLumaValues));
    putHuffmanTable(out, 1, 0, kAcLumaBits, kAcLumaValues, sizeof(kAcLumaValues));
    putHuffmanTable(out, 0, 1, kDcChromaBits, kDcChromaValues, sizeof(kDcChromaValues));
    putHuffmanTable(out, 1, 1, kAcChromaBits, kAcChromaValues, sizeof(kAcChromaValues));

    putMarker(out, 0xda);  // SOS
    put16(out, 12);
    out.push_back(3);
    out.push_back(1);
    out.push_back(0x00);  // DC table 0, AC table 0.
    out.push_back(2);
    out.push_back(0x11);  // DC table 1, AC table 1.
    out.push_back(3);
    out.push_back(0x11);
    out.push_back(0);   // Spectral selection start.
    out.push_back(63);  // Spectral selection end.
    out.push_back(0);   // Successive approximation.

    out.insert(out.end(), entropyCoded.begin(), entropyCoded.end());
    putMarker(out, 0xd9);  // EOI
    return out;
}

}  // namespace camera
}  // namespace androidbox
