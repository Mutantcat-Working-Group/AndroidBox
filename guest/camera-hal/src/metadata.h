// Build and read camera_metadata_t blobs for the external camera provider.
//
// The camera framework reads the static characteristics and every capture
// result as an opaque byte blob that it hands to libcamera_metadata. That blob
// has a fixed wire layout, mirrored here from AOSP
// system/media/camera/src/camera_metadata.c: a 48 byte header, a table of 16
// byte entries and a data region, with values of four bytes or fewer stored
// inline inside the entry itself. Getting this layout wrong is not detected by
// the compiler - the framework simply rejects the camera - so the builder is
// deliberately explicit about every offset instead of relying on a struct
// definition that could drift.
#ifndef ANDROIDBOX_CAMERA_METADATA_H
#define ANDROIDBOX_CAMERA_METADATA_H

#include <cstdint>
#include <cstring>
#include <vector>

#include "tags.h"

namespace androidbox {
namespace camera {

enum MetadataType : uint8_t {
    TYPE_BYTE = 0,
    TYPE_INT32 = 1,
    TYPE_FLOAT = 2,
    TYPE_INT64 = 3,
    TYPE_DOUBLE = 4,
    TYPE_RATIONAL = 5,
};

struct MetadataRational {
    int32_t numerator;
    int32_t denominator;
};

// Mirrors camera_metadata_t (48 bytes) in libcamera_metadata.
struct MetadataHeader {
    uint32_t size;
    uint32_t version;
    uint32_t flags;
    uint32_t entry_count;
    uint32_t entry_capacity;
    uint32_t entries_start;
    uint32_t data_count;
    uint32_t data_capacity;
    uint32_t data_start;
    uint32_t padding;
    uint64_t vendor_id;
};

// Mirrors camera_metadata_buffer_entry_t (16 bytes) in libcamera_metadata.
struct MetadataEntry {
    uint32_t tag;
    uint32_t count;
    uint32_t offset;  // Offset into the data region; unused when the value is inline.
    uint8_t type;
    uint8_t reserved[3];
};

constexpr uint32_t kMetadataVersion = 1;  // CURRENT_METADATA_VERSION
constexpr uint32_t kMetadataSorted = 1;   // FLAG_SORTED
constexpr size_t kMetadataHeaderSize = 48;
constexpr size_t kMetadataEntrySize = 16;
constexpr size_t kMetadataDataAlignment = 8;

// Collects entries and serialises them into a blob the framework accepts.
class MetadataBuilder {
public:
    // Adds an entry from raw payload bytes; payloadBytes must equal count times
    // the size of type. Used by the typed helpers below and by MetadataView
    // when it copies an entry across.
    void addEntry(uint32_t tag, uint8_t type, size_t count, const void* payload,
                  size_t payloadBytes);

    void addByte(uint32_t tag, const uint8_t* values, size_t count);
    void addInt32(uint32_t tag, const int32_t* values, size_t count);
    void addInt64(uint32_t tag, const int64_t* values, size_t count);
    void addFloat(uint32_t tag, const float* values, size_t count);
    void addRational(uint32_t tag, const MetadataRational* values, size_t count);

    void addByte(uint32_t tag, uint8_t value) { addByte(tag, &value, 1); }
    void addInt32(uint32_t tag, int32_t value) { addInt32(tag, &value, 1); }
    void addInt64(uint32_t tag, int64_t value) { addInt64(tag, &value, 1); }
    void addFloat(uint32_t tag, float value) { addFloat(tag, &value, 1); }

    // Serialises the entries, sorted by tag, into the compact blob the
    // framework expects. The result is what goes into CameraMetadata::metadata.
    std::vector<uint8_t> build() const;

    bool empty() const { return entries_.empty(); }

private:
    std::vector<MetadataEntry> entries_;
    std::vector<uint8_t> data_;
};

// A read only view over a blob the framework sent us, used to copy the request
// settings into a capture result.
class MetadataView {
public:
    MetadataView() = default;
    explicit MetadataView(const std::vector<uint8_t>& blob);

    bool valid() const { return valid_; }
    bool has(uint32_t tag) const;

    // Copies the entry verbatim into the builder when the tag is present.
    bool copyTo(MetadataBuilder& builder, uint32_t tag) const;

    int32_t int32Value(uint32_t tag, int32_t fallback) const;
    uint8_t byteValue(uint32_t tag, uint8_t fallback) const;
    int64_t int64Value(uint32_t tag, int64_t fallback) const;
    // Returns false when the tag is absent or is not a rectangle.
    bool rectValue(uint32_t tag, int32_t out[4]) const;

private:
    const MetadataEntry* find(uint32_t tag) const;
    const uint8_t* payloadOf(const MetadataEntry& entry) const;

    std::vector<uint8_t> blob_;
    bool valid_ = false;
};

}  // namespace camera
}  // namespace androidbox

#endif  // ANDROIDBOX_CAMERA_METADATA_H
