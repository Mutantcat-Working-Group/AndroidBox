// The camera device session: configure streams, then fill them with frames.
#include "cameradevicesession.h"

#include <android/hardware_buffer.h>
#include <android/log.h>

#include <unistd.h>

#include <algorithm>
#include <cstdlib>

#include <aidl/android/hardware/camera/common/Status.h>
#include <aidl/android/hardware/camera/device/BufferRequest.h>
#include <aidl/android/hardware/camera/device/BufferRequestStatus.h>
#include <aidl/android/hardware/camera/device/BufferStatus.h>
#include <aidl/android/hardware/camera/device/CaptureResult.h>
#include <aidl/android/hardware/camera/device/ErrorCode.h>
#include <aidl/android/hardware/camera/device/ErrorMsg.h>
#include <aidl/android/hardware/camera/device/HalStream.h>
#include <aidl/android/hardware/camera/device/NotifyMsg.h>
#include <aidl/android/hardware/camera/device/ShutterMsg.h>
#include <aidl/android/hardware/camera/device/Stream.h>
#include <aidl/android/hardware/camera/device/StreamBuffer.h>
#include <aidl/android/hardware/camera/device/StreamBufferRet.h>
#include <aidl/android/hardware/camera/device/StreamBuffersVal.h>
#include <aidl/android/hardware/camera/device/StreamConfiguration.h>
#include <aidl/android/hardware/graphics/common/BufferUsage.h>
#include <aidl/android/hardware/graphics/common/Dataspace.h>
#include <aidl/android/hardware/graphics/common/PixelFormat.h>

#include "characteristics.h"
#include "jpeg.h"
#include "pixels.h"

namespace androidbox {
namespace camera {

namespace {

constexpr const char* kLogTag = "androidbox-camera";

using aidl::android::hardware::camera::common::Status;
using aidl::android::hardware::camera::device::BufferStatus;
using aidl::android::hardware::camera::device::BufferRequestStatus;
using aidl::android::hardware::camera::device::NotifyMsg;
using aidl::android::hardware::camera::device::ShutterMsg;
using aidl::android::hardware::camera::device::StreamBuffer;
using aidl::android::hardware::camera::device::StreamBuffersVal;
using aidl::android::hardware::camera::device::StreamBufferRet;
using aidl::android::hardware::graphics::common::BufferUsage;
using aidl::android::hardware::graphics::common::Dataspace;
using aidl::android::hardware::graphics::common::PixelFormat;

// The formats this camera accepts for an output stream. IMPLEMENTATION_DEFINED
// is what the framework uses for a preview surface; it is overridden with
// RGBA_8888 in configureStreams.
constexpr int32_t kHalPixelFormatRgba8888 = 1;
constexpr int32_t kHalPixelFormatBlob = 33;
constexpr int32_t kHalPixelFormatImplementationDefined = 34;

// native_handle_t is a system type that the NDK headers leave out, but the
// layout is part of the stable ABI: a version word, the fd and int counts, and
// then the fds followed by the ints.
struct native_handle_t {
    int version;
    int numFds;
    int numInts;
    int data[];
};

// AHardwareBuffer_createFromHandle is exported by libnativewindow but is not
// part of the NDK headers, so it is declared here.
extern "C" int AHardwareBuffer_createFromHandle(const native_handle_t* handle,
                                                AHardwareBuffer** outBuffer);

// How many requests may wait for a frame before the oldest is dropped. The
// framework stops handing out buffers when the HAL cannot keep up, so this only
// bounds how far behind the loopback device may fall.
constexpr size_t kMaxPendingRequests = 2;

native_handle_t* makeNativeHandle(const CachedBuffer& cached) {
    native_handle_t* handle = static_cast<native_handle_t*>(
            malloc(sizeof(native_handle_t) +
                   (cached.fds.size() + cached.ints.size()) * sizeof(int)));
    if (handle == nullptr) {
        return nullptr;
    }
    handle->version = static_cast<int>(sizeof(native_handle_t));
    handle->numFds = static_cast<int>(cached.fds.size());
    handle->numInts = static_cast<int>(cached.ints.size());
    for (size_t i = 0; i < cached.fds.size(); ++i) {
        handle->data[i] = cached.fds[i];
    }
    for (size_t i = 0; i < cached.ints.size(); ++i) {
        handle->data[cached.fds.size() + i] = cached.ints[i];
    }
    return handle;
}

CachedBuffer cacheFrom(const StreamBuffer& buffer) {
    CachedBuffer cached;
    if (buffer.buffer.fds.empty()) {
        return cached;
    }
    cached.fds.reserve(buffer.buffer.fds.size());
    for (const auto& fd : buffer.buffer.fds) {
        cached.fds.push_back(fd.get());
    }
    cached.ints = buffer.buffer.ints;
    return cached;
}

}  // namespace

CameraDeviceSession::CameraDeviceSession(std::string videoDevice, uint32_t sensorWidth,
                                         uint32_t sensorHeight)
    : videoDevice_(std::move(videoDevice)), sensorWidth_(sensorWidth),
      sensorHeight_(sensorHeight) {}

CameraDeviceSession::~CameraDeviceSession() {
    close();
}

::ndk::ScopedAStatus CameraDeviceSession::start(
        const std::shared_ptr<aidl::android::hardware::camera::device::ICameraDeviceCallback>&
                callback) {
    if (callback == nullptr) {
        return ::ndk::ScopedAStatus::fromExceptionCode(EX_ILLEGAL_ARGUMENT);
    }
    if (!frameSource_.start(videoDevice_)) {
        return ::ndk::ScopedAStatus::fromServiceSpecificError(
                static_cast<int32_t>(Status::INTERNAL_ERROR));
    }
    callback_ = callback;
    workerRunning_ = true;
    worker_ = std::thread([this] { workerLoop(); });
    return ::ndk::ScopedAStatus::ok();
}

::ndk::ScopedAStatus CameraDeviceSession::close() {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        closed_ = true;
    }
    requestReady_.notify_all();
    if (worker_.joinable()) {
        worker_.join();
    }
    workerRunning_ = false;
    frameSource_.stop();
    callback_.reset();
    return ::ndk::ScopedAStatus::ok();
}

bool CameraDeviceSession::streamIsSupported(
        const ::aidl::android::hardware::camera::device::Stream& stream) const {
    if (stream.streamType != aidl::android::hardware::camera::device::StreamType::OUTPUT) {
        return false;
    }
    if (stream.rotation != aidl::android::hardware::camera::device::StreamRotation::ROTATION_0) {
        // Rotating a frame would need a second copy of the converter.
        return false;
    }
    const int32_t format = static_cast<int32_t>(stream.format);
    if (format != kHalPixelFormatRgba8888 && format != kHalPixelFormatBlob &&
        format != kHalPixelFormatImplementationDefined) {
        return false;
    }
    for (const CameraSize& size : supportedSizes()) {
        if (size.width == static_cast<uint32_t>(stream.width) &&
            size.height == static_cast<uint32_t>(stream.height)) {
            return true;
        }
    }
    return false;
}

::ndk::ScopedAStatus CameraDeviceSession::configureStreams(
        const ::aidl::android::hardware::camera::device::StreamConfiguration&
                in_requestedConfiguration,
        std::vector<::aidl::android::hardware::camera::device::HalStream>* _aidl_return) {
    _aidl_return->clear();
    if (in_requestedConfiguration.streams.empty()) {
        return ::ndk::ScopedAStatus::fromExceptionCode(EX_ILLEGAL_ARGUMENT);
    }
    if (in_requestedConfiguration.operationMode !=
        aidl::android::hardware::camera::device::StreamConfigurationMode::NORMAL_MODE) {
        // Constrained high speed mode needs a fixed size and frame rate this
        // camera cannot promise.
        return ::ndk::ScopedAStatus::fromExceptionCode(EX_ILLEGAL_ARGUMENT);
    }

    int blobStreams = 0;
    std::vector<Stream> streams;
    streams.reserve(in_requestedConfiguration.streams.size());
    for (const auto& requested : in_requestedConfiguration.streams) {
        if (!streamIsSupported(requested)) {
            __android_log_print(ANDROID_LOG_ERROR, kLogTag,
                                "rejecting a %dx%d stream of format %d", requested.width,
                                requested.height, static_cast<int32_t>(requested.format));
            return ::ndk::ScopedAStatus::fromExceptionCode(EX_ILLEGAL_ARGUMENT);
        }
        const int32_t format = static_cast<int32_t>(requested.format);
        if (format == kHalPixelFormatBlob) {
            ++blobStreams;
        }
    }
    if (blobStreams > 1) {
        // One JPEG stream is all the encoder handles at a time.
        return ::ndk::ScopedAStatus::fromExceptionCode(EX_ILLEGAL_ARGUMENT);
    }

    for (const auto& requested : in_requestedConfiguration.streams) {
        Stream stream;
        stream.id = requested.id;
        stream.width = requested.width;
        stream.height = requested.height;
        stream.bufferSize = requested.bufferSize;
        stream.usage = requested.usage;
        stream.dataSpace = requested.dataSpace;
        const int32_t format = static_cast<int32_t>(requested.format);
        stream.isBlob = format == kHalPixelFormatBlob;
        stream.format = stream.isBlob
                ? PixelFormat::BLOB
                : (format == kHalPixelFormatImplementationDefined ? PixelFormat::RGBA_8888
                                                                  : requested.format);
        streams.push_back(stream);

        ::aidl::android::hardware::camera::device::HalStream halStream;
        halStream.id = requested.id;
        halStream.overrideFormat = stream.format;
        halStream.producerUsage = static_cast<BufferUsage>(
                static_cast<int64_t>(BufferUsage::CPU_READ_OFTEN) |
                static_cast<int64_t>(BufferUsage::CPU_WRITE_OFTEN));
        halStream.consumerUsage = BufferUsage(0);
        halStream.maxBuffers = 4;
        halStream.overrideDataSpace = stream.isBlob ? Dataspace::JFIF : Dataspace::UNKNOWN;
        halStream.supportOffline = false;
        _aidl_return->push_back(halStream);
    }

    {
        std::lock_guard<std::mutex> lock(mutex_);
        streams_ = std::move(streams);
        streamConfigCounter_ = in_requestedConfiguration.streamConfigCounter;
        configured_ = true;
    }
    return ::ndk::ScopedAStatus::ok();
}

::ndk::ScopedAStatus CameraDeviceSession::constructDefaultRequestSettings(
        ::aidl::android::hardware::camera::device::RequestTemplate in_type,
        ::aidl::android::hardware::camera::device::CameraMetadata* _aidl_return) {
    _aidl_return->metadata = buildDefaultRequestSettings(static_cast<int>(in_type));
    return ::ndk::ScopedAStatus::ok();
}

::ndk::ScopedAStatus CameraDeviceSession::flush() {
    std::lock_guard<std::mutex> lock(mutex_);
    pending_.clear();
    return ::ndk::ScopedAStatus::ok();
}

::ndk::ScopedAStatus CameraDeviceSession::getCaptureRequestMetadataQueue(
        ::aidl::android::hardware::common::fmq::MQDescriptor<
                int8_t, ::aidl::android::hardware::common::fmq::SynchronizedReadWrite>*
                _aidl_return) {
    // The session sends settings inline in the parcel, so no queue is offered.
    _aidl_return->grantors = {};
    _aidl_return->quantum = 0;
    _aidl_return->flags = 0;
    return ::ndk::ScopedAStatus::ok();
}

::ndk::ScopedAStatus CameraDeviceSession::getCaptureResultMetadataQueue(
        ::aidl::android::hardware::common::fmq::MQDescriptor<
                int8_t, ::aidl::android::hardware::common::fmq::SynchronizedReadWrite>*
                _aidl_return) {
    _aidl_return->grantors = {};
    _aidl_return->quantum = 0;
    _aidl_return->flags = 0;
    return ::ndk::ScopedAStatus::ok();
}

::ndk::ScopedAStatus CameraDeviceSession::isReconfigurationRequired(
        const ::aidl::android::hardware::camera::device::CameraMetadata& /*in_oldSessionParams*/,
        const ::aidl::android::hardware::camera::device::CameraMetadata& /*in_newSessionParams*/,
        bool* _aidl_return) {
    // Session parameters never change what this camera can do.
    *_aidl_return = false;
    return ::ndk::ScopedAStatus::ok();
}

::ndk::ScopedAStatus CameraDeviceSession::processCaptureRequest(
        const std::vector<::aidl::android::hardware::camera::device::CaptureRequest>& in_requests,
        const std::vector<::aidl::android::hardware::camera::device::BufferCache>&
        /*in_cachesToRemove*/,
        int32_t* _aidl_return) {
    if (in_requests.empty()) {
        *_aidl_return = 0;
        return ::ndk::ScopedAStatus::ok();
    }
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!configured_ || closed_ || callback_ == nullptr) {
            *_aidl_return = 0;
            return ::ndk::ScopedAStatus::fromExceptionCode(EX_ILLEGAL_STATE);
        }
        for (const auto& request : in_requests) {
            PendingRequest pending;
            pending.frameNumber = request.frameNumber;
            pending.settings = request.settings.metadata;
            pending.streamIds.reserve(request.outputBuffers.size());
            for (const auto& buffer : request.outputBuffers) {
                pending.streamIds.push_back(buffer.streamId);
            }
            // Requests may arrive without any buffers attached; the session
            // pulls the buffers itself through requestStreamBuffers.
            if (pending.streamIds.empty()) {
                for (const auto& stream : streams_) {
                    pending.streamIds.push_back(stream.id);
                }
            }
            pending_.push_back(std::move(pending));
            while (pending_.size() > kMaxPendingRequests) {
                // The loopback device cannot keep up; the framework will time
                // the dropped request out and report an error for it.
                pending_.pop_front();
            }
        }
    }
    requestReady_.notify_all();
    *_aidl_return = static_cast<int32_t>(in_requests.size());
    return ::ndk::ScopedAStatus::ok();
}

::ndk::ScopedAStatus CameraDeviceSession::signalStreamFlush(
        const std::vector<int32_t>& in_streamIds, int32_t /*in_streamConfigCounter*/) {
    std::lock_guard<std::mutex> lock(mutex_);
    for (int32_t streamId : in_streamIds) {
        for (auto it = pending_.begin(); it != pending_.end();) {
            if (std::find(it->streamIds.begin(), it->streamIds.end(), streamId) !=
                it->streamIds.end()) {
                it = pending_.erase(it);
            } else {
                ++it;
            }
        }
    }
    return ::ndk::ScopedAStatus::ok();
}

::ndk::ScopedAStatus CameraDeviceSession::switchToOffline(
        const std::vector<int32_t>& /*in_streamsToKeep*/,
        ::aidl::android::hardware::camera::device::CameraOfflineSessionInfo*
        /*out_offlineSessionInfo*/,
        std::shared_ptr<::aidl::android::hardware::camera::device::ICameraOfflineSession>*
                _aidl_return) {
    // Offline processing needs the HAL to keep running after the device closes.
    _aidl_return->reset();
    return ::ndk::ScopedAStatus::fromExceptionCode(EX_UNSUPPORTED_OPERATION);
}

::ndk::ScopedAStatus CameraDeviceSession::repeatingRequestEnd(
        int32_t /*in_frameNumber*/, const std::vector<int32_t>& /*in_streamIds*/) {
    return ::ndk::ScopedAStatus::ok();
}

const CameraDeviceSession::Stream* CameraDeviceSession::findStream(int32_t id) const {
    for (const auto& stream : streams_) {
        if (stream.id == id) {
            return &stream;
        }
    }
    return nullptr;
}

bool CameraDeviceSession::requestStreamBuffer(int32_t streamId, StreamBuffer* out) {
    if (callback_ == nullptr) {
        return false;
    }
    std::vector<aidl::android::hardware::camera::device::BufferRequest> requests = {
            {streamId, 1}};
    std::vector<StreamBufferRet> rets;
    BufferRequestStatus status = BufferRequestStatus::FAILED_UNKNOWN;
    const auto result = callback_->requestStreamBuffers(requests, &rets, &status);
    if (!result.isOk() || status != BufferRequestStatus::OK || rets.empty()) {
        __android_log_print(ANDROID_LOG_WARN, kLogTag,
                            "stream %d could not be filled: reply=%s status=%d replies=%zu",
                            streamId, result.getDescription().c_str(),
                            static_cast<int32_t>(status), rets.size());
        return false;
    }
    if (rets[0].streamId != streamId ||
        rets[0].val.getTag() != StreamBuffersVal::Tag::buffers) {
        return false;
    }
    // The handles are moved out of the framework's reply: ndk::ScopedFileDescriptor
    // owns the descriptors it carries, so the reply cannot be copied.
    auto& buffers = rets[0].val.get<StreamBuffersVal::Tag::buffers>();
    if (buffers.empty()) {
        return false;
    }
    *out = std::move(buffers[0]);
    return true;
}

bool CameraDeviceSession::fillStreamBuffer(const Stream& stream, const StreamBuffer& buffer,
                                           const FrameSource::Frame& frame,
                                           size_t* bytesWritten) {
    *bytesWritten = 0;
    CachedBuffer cached = cacheFrom(buffer);
    {
        std::lock_guard<std::mutex> lock(bufferCacheMutex_);
        if (cached.fds.empty()) {
            // The framework only sends the handle the first time; look the buffer
            // up by its id for every later request.
            auto streamEntry = bufferCache_.find(buffer.streamId);
            if (streamEntry == bufferCache_.end()) {
                return false;
            }
            auto entry = streamEntry->second.find(buffer.bufferId);
            if (entry == streamEntry->second.end()) {
                return false;
            }
            cached = entry->second;
        } else {
            bufferCache_[buffer.streamId][buffer.bufferId] = cached;
        }
    }

    native_handle_t* handle = makeNativeHandle(cached);
    if (handle == nullptr) {
        return false;
    }
    AHardwareBuffer* hardwareBuffer = nullptr;
    const int created = AHardwareBuffer_createFromHandle(handle, &hardwareBuffer);
    if (created != 0 || hardwareBuffer == nullptr) {
        __android_log_print(ANDROID_LOG_ERROR, kLogTag,
                            "cannot adopt a graphics buffer for stream %d: %d", buffer.streamId,
                            created);
        free(handle);
        return false;
    }

    bool ok = false;
    AHardwareBuffer_Desc description = {};
    AHardwareBuffer_describe(hardwareBuffer, &description);
    const uint64_t lockUsage = AHARDWAREBUFFER_USAGE_CPU_WRITE_OFTEN;
    void* mapped = nullptr;
    const int locked = AHardwareBuffer_lock(hardwareBuffer, lockUsage, -1, nullptr, &mapped);
    if (locked != 0 || mapped == nullptr) {
        __android_log_print(ANDROID_LOG_ERROR, kLogTag, "cannot lock a graphics buffer: %d",
                            locked);
        free(handle);
        return false;
    }

    if (stream.isBlob) {
        std::vector<uint8_t> jpeg =
                encodeJpegYu12(frame.planes.data(), frame.width, frame.height, frame.width, 90);
        // The framework sizes BLOB buffers from ANDROID_JPEG_MAX_SIZE, so there
        // is always room; the check is only a guard against a broken image.
        const size_t capacity = stream.bufferSize > 0
                ? static_cast<size_t>(stream.bufferSize)
                : static_cast<size_t>(description.height) * description.stride;
        if (!jpeg.empty() && jpeg.size() <= capacity) {
            memcpy(mapped, jpeg.data(), jpeg.size());
            *bytesWritten = jpeg.size();
            ok = true;
        } else {
            __android_log_print(ANDROID_LOG_ERROR, kLogTag,
                                "the encoded frame (%zu bytes) does not fit the %zu byte buffer",
                                jpeg.size(), capacity);
        }
    } else {
        const uint32_t width = static_cast<uint32_t>(stream.width);
        const uint32_t height = static_cast<uint32_t>(stream.height);
        std::vector<uint8_t> rgba(rgbaSize(width, height));
        if (convertYu12ToRgba(frame.planes.data(), frame.width, frame.height, frame.width,
                                      width, height, rgba.data())) {
            // Gralloc rows are padded; copy row by row.
            const uint32_t rowBytes = width * 4;
            auto* destination = static_cast<uint8_t*>(mapped);
            for (uint32_t row = 0; row < height; ++row) {
                memcpy(destination + static_cast<size_t>(row) * description.stride,
                       rgba.data() + static_cast<size_t>(row) * rowBytes, rowBytes);
            }
            *bytesWritten = description.stride * height;
            ok = true;
        }
    }

    AHardwareBuffer_unlock(hardwareBuffer, nullptr);
    free(handle);
    return ok;
}

void CameraDeviceSession::reportBufferError(const PendingRequest& request, int32_t streamId) {
    if (callback_ == nullptr) {
        return;
    }
    NotifyMsg error;
    ::aidl::android::hardware::camera::device::ErrorMsg message;
    message.frameNumber = request.frameNumber;
    message.errorStreamId = streamId;
    message.errorCode = aidl::android::hardware::camera::device::ErrorCode::ERROR_BUFFER;
    error.set<NotifyMsg::Tag::error>(message);
    callback_->notify({error});
}

void CameraDeviceSession::workerLoop() {
    while (true) {
        PendingRequest request;
        {
            std::unique_lock<std::mutex> lock(mutex_);
            requestReady_.wait(lock, [this] { return closed_ || !pending_.empty(); });
            if (closed_) {
                return;
            }
            request = pending_.front();
            pending_.pop_front();
        }
        if (callback_ == nullptr) {
            continue;
        }

        FrameSource::Frame frame;
        if (!frameSource_.waitForFrame(frame, 1000)) {
            // Nothing has arrived from the host; report a buffer error so the
            // framework can recover instead of waiting forever.
            __android_log_print(ANDROID_LOG_WARN, kLogTag,
                                "no frame arrived from %s for request %d", videoDevice_.c_str(),
                                request.frameNumber);
            reportBufferError(request, -1);
            continue;
        }
        __android_log_print(ANDROID_LOG_DEBUG, kLogTag, "request %d got a %dx%d frame",
                            request.frameNumber, frame.width, frame.height);

        // The shutter comes first: the framework times the request from here.
        ShutterMsg shutter;
        shutter.frameNumber = request.frameNumber;
        shutter.timestamp = frame.timestampNs;
        shutter.readoutTimestamp = frame.timestampNs;
        NotifyMsg message;
        message.set<NotifyMsg::Tag::shutter>(shutter);
        std::vector<NotifyMsg> notifications;
        notifications.push_back(std::move(message));
        const auto notified = callback_->notify(notifications);
        if (!notified.isOk()) {
            continue;
        }

        ::aidl::android::hardware::camera::device::CaptureResult result;
        result.frameNumber = request.frameNumber;
        result.partialResult = 1;
        int32_t jpegStreamId = -1;
        size_t jpegBytes = 0;
        for (int32_t streamId : request.streamIds) {
            const Stream* stream = findStream(streamId);
            if (stream == nullptr) {
                reportBufferError(request, streamId);
                continue;
            }
            StreamBuffer buffer;
            if (!requestStreamBuffer(streamId, &buffer)) {
                reportBufferError(request, streamId);
                continue;
            }
            size_t bytes = 0;
            const bool filled = fillStreamBuffer(*stream, buffer, frame, &bytes);
            // The framework matches a returned buffer by its id, and the handle
            // must not travel back with it.
            buffer.buffer.fds.clear();
            buffer.buffer.ints.clear();
            buffer.status = filled ? BufferStatus::OK : BufferStatus::ERROR;
            if (filled && stream->isBlob) {
                jpegStreamId = streamId;
                jpegBytes = bytes;
            }
            result.outputBuffers.push_back(std::move(buffer));
        }

        // No reprocessing: the input buffer is unused.
        result.inputBuffer.streamId = -1;

        MetadataView requestSettings(request.settings);
        MetadataBuilder metadata;
        // The framework expects the result to echo the settings it sent.
        static const int32_t echoKeys[] = {
                ANDROID_CONTROL_AE_MODE,
                ANDROID_CONTROL_AF_MODE,
                ANDROID_CONTROL_AWB_MODE,
                ANDROID_CONTROL_CAPTURE_INTENT,
                ANDROID_CONTROL_EFFECT_MODE,
                ANDROID_CONTROL_MODE,
                ANDROID_CONTROL_SCENE_MODE,
                ANDROID_CONTROL_VIDEO_STABILIZATION_MODE,
                ANDROID_COLOR_CORRECTION_ABERRATION_MODE,
                ANDROID_EDGE_MODE,
                ANDROID_NOISE_REDUCTION_MODE,
                ANDROID_STATISTICS_FACE_DETECT_MODE,
        };
        for (int32_t key : echoKeys) {
            requestSettings.copyTo(metadata, static_cast<uint32_t>(key));
        }
        const int64_t timestamp = frame.timestampNs;
        metadata.addInt64(ANDROID_SENSOR_TIMESTAMP, &timestamp, 1);
        const uint8_t aeState = ANDROID_CONTROL_AE_STATE_CONVERGED;
        metadata.addByte(ANDROID_CONTROL_AE_STATE, &aeState, 1);
        const uint8_t afState = ANDROID_CONTROL_AF_STATE_INACTIVE;
        metadata.addByte(ANDROID_CONTROL_AF_STATE, &afState, 1);
        const uint8_t awbState = ANDROID_CONTROL_AWB_STATE_CONVERGED;
        metadata.addByte(ANDROID_CONTROL_AWB_STATE, &awbState, 1);
        const uint8_t pipelineDepth = 4;
        metadata.addByte(ANDROID_REQUEST_PIPELINE_DEPTH, &pipelineDepth, 1);
        const int32_t jpegOrientation = 0;
        metadata.addInt32(ANDROID_JPEG_ORIENTATION, &jpegOrientation, 1);
        if (jpegStreamId >= 0) {
            const int32_t size = static_cast<int32_t>(jpegBytes);
            metadata.addInt32(ANDROID_JPEG_SIZE, &size, 1);
        }
        result.result.metadata = metadata.build();

        // The reply is built as a vector and the result moved into it: the
        // buffers it carries own file descriptors and cannot be copied.
        const size_t bufferCount = result.outputBuffers.size();
        std::vector<aidl::android::hardware::camera::device::CaptureResult> results;
        results.push_back(std::move(result));
        const auto returned = callback_->processCaptureResult(results);
        if (!returned.isOk()) {
            __android_log_print(ANDROID_LOG_ERROR, kLogTag, "returning a frame failed: %s",
                                returned.getDescription().c_str());
        } else {
            __android_log_print(ANDROID_LOG_DEBUG, kLogTag, "request %d returned %zu buffers",
                                request.frameNumber, bufferCount);
        }
    }
}

}  // namespace camera
}  // namespace androidbox
