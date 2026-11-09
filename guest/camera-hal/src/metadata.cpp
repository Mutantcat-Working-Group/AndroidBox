// Build and read camera_metadata_t blobs for the external camera provider.
#include "metadata.h"

#include <algorithm>

namespace androidbox {
namespace camera {

namespace {

size_t typeSize(uint8_t type) {
    switch (type) {
        case TYPE_BYTE: return 1;
        case TYPE_INT32: return 4;
        case TYPE_FLOAT: return 4;
        case TYPE_INT64: return 8;
        case TYPE_DOUBLE: return 8;
        case TYPE_RATIONAL: return 8;
        default: return 0;
    }
}

// libcamera_metadata keeps values of four bytes or fewer inside the entry's own
// data word and only spills larger values into the data region, where each one
// starts on an eight byte boundary.
size_t dataBytesFor(uint8_t type, size_t count) {
    const size_t payload = count * typeSize(type);
    return payload <= 4 ? 0 : ((payload + kMetadataDataAlignment - 1) /
                               kMetadataDataAlignment) * kMetadataDataAlignment;
}

size_t alignUp(size_t value, size_t alignment) {
    return ((value + alignment - 1) / alignment) * alignment;
}

// One entry, with the payload either stored inline in the entry's data word or
// appended to the builder's data region at the returned offset.
MetadataEntry makeEntry(uint32_t tag, uint8_t type, size_t count, const void* payload,
                        size_t bytes, std::vector<uint8_t>* data) {
    MetadataEntry entry = {};
    entry.tag = tag;
    entry.count = static_cast<uint32_t>(count);
    entry.type = type;
    const size_t stored = dataBytesFor(type, count);
    if (stored == 0) {
        // Inline: the union at offset 8 holds the value itself.
        if (bytes > 0) {
            memcpy(&entry.offset, payload, bytes);
        }
    } else {
        entry.offset = static_cast<uint32_t>(data->size());
        const size_t start = data->size();
        data->resize(start + stored);
        memcpy(data->data() + start, payload, bytes);
    }
    return entry;
}

}  // namespace

void MetadataBuilder::addEntry(uint32_t tag, uint8_t type, size_t count, const void* payload,
                               size_t payloadBytes) {
    if (payloadBytes == 0 || payload == nullptr) {
        return;
    }
    entries_.push_back(makeEntry(tag, type, count, payload, payloadBytes, &data_));
}

void MetadataBuilder::addByte(uint32_t tag, const uint8_t* values, size_t count) {
    addEntry(tag, TYPE_BYTE, count, values, count * sizeof(uint8_t));
}

void MetadataBuilder::addInt32(uint32_t tag, const int32_t* values, size_t count) {
    addEntry(tag, TYPE_INT32, count, values, count * sizeof(int32_t));
}

void MetadataBuilder::addInt64(uint32_t tag, const int64_t* values, size_t count) {
    addEntry(tag, TYPE_INT64, count, values, count * sizeof(int64_t));
}

void MetadataBuilder::addFloat(uint32_t tag, const float* values, size_t count) {
    addEntry(tag, TYPE_FLOAT, count, values, count * sizeof(float));
}

void MetadataBuilder::addRational(uint32_t tag, const MetadataRational* values, size_t count) {
    addEntry(tag, TYPE_RATIONAL, count, values, count * sizeof(MetadataRational));
}

std::vector<uint8_t> MetadataBuilder::build() const {
    std::vector<MetadataEntry> entries = entries_;
    // libcamera_metadata accepts unsorted entries, but the framework's lookup
    // helpers assume sorted ones, so hand it a sorted table.
    std::sort(entries.begin(), entries.end(),
              [](const MetadataEntry& a, const MetadataEntry& b) { return a.tag < b.tag; });

    const size_t entry_count = entries.size();
    const size_t entries_start = kMetadataHeaderSize;  // Already 4 byte aligned.
    const size_t entries_end = entries_start + entry_count * kMetadataEntrySize;
    const size_t data_start = alignUp(entries_end, kMetadataDataAlignment);
    const size_t data_capacity = alignUp(data_.size(), kMetadataDataAlignment);
    const size_t total = data_start + data_capacity;

    std::vector<uint8_t> blob(total, 0);
    MetadataHeader header = {};
    header.size = static_cast<uint32_t>(total);
    header.version = kMetadataVersion;
    header.flags = kMetadataSorted;
    header.entry_count = static_cast<uint32_t>(entry_count);
    header.entry_capacity = static_cast<uint32_t>(entry_count);
    header.entries_start = static_cast<uint32_t>(entries_start);
    header.data_count = static_cast<uint32_t>(data_.size());
    header.data_capacity = static_cast<uint32_t>(data_capacity);
    header.data_start = static_cast<uint32_t>(data_start);
    header.vendor_id = 0;  // CAMERA_METADATA_INVALID_VENDOR_ID
    memcpy(blob.data(), &header, sizeof(header));

    if (entry_count > 0) {
        memcpy(blob.data() + entries_start, entries.data(),
               entry_count * sizeof(MetadataEntry));
    }
    if (!data_.empty()) {
        memcpy(blob.data() + data_start, data_.data(), data_.size());
    }
    return blob;
}

MetadataView::MetadataView(const std::vector<uint8_t>& blob) : blob_(blob) {
    valid_ = false;
    if (blob_.size() < kMetadataHeaderSize) {
        return;
    }
    MetadataHeader header = {};
    memcpy(&header, blob_.data(), sizeof(header));
    if (header.version != kMetadataVersion) {
        return;
    }
    if (header.entries_start < kMetadataHeaderSize ||
        header.entries_start + static_cast<size_t>(header.entry_count) * kMetadataEntrySize >
                blob_.size()) {
        return;
    }
    if (header.data_start > blob_.size()) {
        return;
    }
    valid_ = true;
}

const MetadataEntry* MetadataView::find(uint32_t tag) const {
    if (!valid_) {
        return nullptr;
    }
    MetadataHeader header = {};
    memcpy(&header, blob_.data(), sizeof(header));
    const MetadataEntry* entries =
            reinterpret_cast<const MetadataEntry*>(blob_.data() + header.entries_start);
    // Entries are normally sorted, but a blob that is not sorted still has to
    // work, so fall back to a linear scan when the binary search comes up empty.
    auto begin = entries;
    auto end = entries + header.entry_count;
    auto found = std::lower_bound(begin, end, tag,
                                  [](const MetadataEntry& entry, uint32_t value) {
                                      return entry.tag < value;
                                  });
    if (found != end && found->tag == tag) {
        return found;
    }
    for (const MetadataEntry* entry = begin; entry != end; ++entry) {
        if (entry->tag == tag) {
            return entry;
        }
    }
    return nullptr;
}

const uint8_t* MetadataView::payloadOf(const MetadataEntry& entry) const {
    if (dataBytesFor(entry.type, entry.count) == 0) {
        return reinterpret_cast<const uint8_t*>(&entry.offset);
    }
    MetadataHeader header = {};
    memcpy(&header, blob_.data(), sizeof(header));
    const size_t offset = header.data_start + entry.offset;
    if (offset > blob_.size()) {
        return nullptr;
    }
    return blob_.data() + offset;
}

bool MetadataView::has(uint32_t tag) const {
    return find(tag) != nullptr;
}

bool MetadataView::copyTo(MetadataBuilder& builder, uint32_t tag) const {
    const MetadataEntry* entry = find(tag);
    if (entry == nullptr) {
        return false;
    }
    const uint8_t* payload = payloadOf(*entry);
    if (payload == nullptr && entry->count != 0) {
        return false;
    }
    builder.addEntry(entry->tag, entry->type, entry->count, payload,
                     static_cast<size_t>(entry->count) * typeSize(entry->type));
    return true;
}

int32_t MetadataView::int32Value(uint32_t tag, int32_t fallback) const {
    const MetadataEntry* entry = find(tag);
    if (entry == nullptr || entry->type != TYPE_INT32 || entry->count == 0) {
        return fallback;
    }
    const uint8_t* payload = payloadOf(*entry);
    if (payload == nullptr) {
        return fallback;
    }
    int32_t value = 0;
    memcpy(&value, payload, sizeof(value));
    return value;
}

uint8_t MetadataView::byteValue(uint32_t tag, uint8_t fallback) const {
    const MetadataEntry* entry = find(tag);
    if (entry == nullptr || entry->type != TYPE_BYTE || entry->count == 0) {
        return fallback;
    }
    const uint8_t* payload = payloadOf(*entry);
    if (payload == nullptr) {
        return fallback;
    }
    return payload[0];
}

int64_t MetadataView::int64Value(uint32_t tag, int64_t fallback) const {
    const MetadataEntry* entry = find(tag);
    if (entry == nullptr || entry->type != TYPE_INT64 || entry->count == 0) {
        return fallback;
    }
    const uint8_t* payload = payloadOf(*entry);
    if (payload == nullptr) {
        return fallback;
    }
    int64_t value = 0;
    memcpy(&value, payload, sizeof(value));
    return value;
}

bool MetadataView::rectValue(uint32_t tag, int32_t out[4]) const {
    const MetadataEntry* entry = find(tag);
    if (entry == nullptr || entry->type != TYPE_INT32 || entry->count != 4) {
        return false;
    }
    const uint8_t* payload = payloadOf(*entry);
    if (payload == nullptr) {
        return false;
    }
    memcpy(out, payload, 4 * sizeof(int32_t));
    return true;
}

}  // namespace camera
}  // namespace androidbox
