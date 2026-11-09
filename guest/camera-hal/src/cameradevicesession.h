// The camera device session: configure streams, then fill them with frames.
//
// Android 13's AIDL camera HAL uses the buffer manager model: configureStreams
// only describes the streams, and the buffers themselves are pulled from the
// framework on demand through ICameraDeviceCallback::requestStreamBuffers. The
// session therefore runs a worker thread that waits for a frame from the
// loopback device, asks the framework for one buffer per output stream, fills
// each of them, and hands them back in processCaptureResult.
#ifndef ANDROIDBOX_CAMERA_DEVICE_SESSION_H
#define ANDROIDBOX_CAMERA_DEVICE_SESSION_H

#include <condition_variable>
#include <deque>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include <aidl/android/hardware/camera/device/BnCameraDeviceSession.h>

#include "framesource.h"
#include "metadata.h"

namespace androidbox {
namespace camera {

// A graphics buffer handle plus the file descriptors that keep it alive. The
// framework only attaches the handle the first time it hands a buffer over, so
// the session has to remember it for every later frame.
struct CachedBuffer {
    std::vector<int> fds;
    std::vector<int> ints;
};

class CameraDeviceSession
    : public aidl::android::hardware::camera::device::BnCameraDeviceSession {
public:
    CameraDeviceSession(std::string videoDevice, uint32_t sensorWidth, uint32_t sensorHeight);
    ~CameraDeviceSession() override;

    CameraDeviceSession(const CameraDeviceSession&) = delete;
    CameraDeviceSession& operator=(const CameraDeviceSession&) = delete;

    // Opens the loopback device and starts the frame worker.
    ::ndk::ScopedAStatus start(
            const std::shared_ptr<aidl::android::hardware::camera::device::ICameraDeviceCallback>&
                    callback);

    ::ndk::ScopedAStatus close() override;
    ::ndk::ScopedAStatus configureStreams(
            const ::aidl::android::hardware::camera::device::StreamConfiguration&
                    in_requestedConfiguration,
            std::vector<::aidl::android::hardware::camera::device::HalStream>* _aidl_return)
            override;
    ::ndk::ScopedAStatus constructDefaultRequestSettings(
            ::aidl::android::hardware::camera::device::RequestTemplate in_type,
            ::aidl::android::hardware::camera::device::CameraMetadata* _aidl_return) override;
    ::ndk::ScopedAStatus flush() override;
    ::ndk::ScopedAStatus getCaptureRequestMetadataQueue(
            ::aidl::android::hardware::common::fmq::MQDescriptor<
                    int8_t, ::aidl::android::hardware::common::fmq::SynchronizedReadWrite>*
                    _aidl_return) override;
    ::ndk::ScopedAStatus getCaptureResultMetadataQueue(
            ::aidl::android::hardware::common::fmq::MQDescriptor<
                    int8_t, ::aidl::android::hardware::common::fmq::SynchronizedReadWrite>*
                    _aidl_return) override;
    ::ndk::ScopedAStatus isReconfigurationRequired(
            const ::aidl::android::hardware::camera::device::CameraMetadata& in_oldSessionParams,
            const ::aidl::android::hardware::camera::device::CameraMetadata& in_newSessionParams,
            bool* _aidl_return) override;
    ::ndk::ScopedAStatus processCaptureRequest(
            const std::vector<::aidl::android::hardware::camera::device::CaptureRequest>&
                    in_requests,
            const std::vector<::aidl::android::hardware::camera::device::BufferCache>&
                    in_cachesToRemove,
            int32_t* _aidl_return) override;
    ::ndk::ScopedAStatus signalStreamFlush(const std::vector<int32_t>& in_streamIds,
                                           int32_t in_streamConfigCounter) override;
    ::ndk::ScopedAStatus switchToOffline(
            const std::vector<int32_t>& in_streamsToKeep,
            ::aidl::android::hardware::camera::device::CameraOfflineSessionInfo*
                    out_offlineSessionInfo,
            std::shared_ptr<::aidl::android::hardware::camera::device::ICameraOfflineSession>*
                    _aidl_return) override;
    ::ndk::ScopedAStatus repeatingRequestEnd(int32_t in_frameNumber,
                                             const std::vector<int32_t>& in_streamIds) override;

private:
    struct Stream {
        int32_t id = 0;
        int32_t width = 0;
        int32_t height = 0;
        int32_t bufferSize = 0;  // Only meaningful for BLOB streams.
        ::aidl::android::hardware::graphics::common::PixelFormat format =
                ::aidl::android::hardware::graphics::common::PixelFormat::BLOB;
        ::aidl::android::hardware::graphics::common::Dataspace dataSpace =
                ::aidl::android::hardware::graphics::common::Dataspace::UNKNOWN;
        ::aidl::android::hardware::graphics::common::BufferUsage usage =
                ::aidl::android::hardware::graphics::common::BufferUsage(0);
        bool isBlob = false;
    };

    struct PendingRequest {
        int32_t frameNumber = 0;
        std::vector<int32_t> streamIds;
        std::vector<uint8_t> settings;
    };

    // Frame delivery.
    void workerLoop();
    void deliverFrame(const FrameSource::Frame& frame, PendingRequest& request);
    bool requestStreamBuffer(int32_t streamId,
                             ::aidl::android::hardware::camera::device::StreamBuffer* out);
    bool fillStreamBuffer(const Stream& stream,
                          const ::aidl::android::hardware::camera::device::StreamBuffer& buffer,
                          const FrameSource::Frame& frame, size_t* bytesWritten);
    void reportBufferError(const PendingRequest& request, int32_t streamId);

    // Stream bookkeeping.
    const Stream* findStream(int32_t id) const;
    bool streamIsSupported(const ::aidl::android::hardware::camera::device::Stream& stream) const;

    std::string videoDevice_;
    uint32_t sensorWidth_;
    uint32_t sensorHeight_;

    std::shared_ptr<aidl::android::hardware::camera::device::ICameraDeviceCallback> callback_;
    std::mutex mutex_;
    std::condition_variable requestReady_;
    std::deque<PendingRequest> pending_;
    bool closed_ = false;
    bool configured_ = false;
    int32_t streamConfigCounter_ = 0;

    std::vector<Stream> streams_;
    FrameSource frameSource_;
    std::thread worker_;
    bool workerRunning_ = false;

    // Buffers the framework has handed out, keyed by stream then buffer id: the
    // framework only attaches the handle the first time it sends a buffer.
    std::mutex bufferCacheMutex_;
    std::map<int32_t, std::map<int64_t, CachedBuffer>> bufferCache_;
};

}  // namespace camera
}  // namespace androidbox

#endif  // ANDROIDBOX_CAMERA_DEVICE_SESSION_H
