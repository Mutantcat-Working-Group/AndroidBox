// Read frames from the loopback camera device.
//
// The guest's Ubuntu support layer feeds /dev/video0 (a v4l2loopback device)
// from the webcam the host streams over TCP, so the Android camera stack only
// ever has to read one V4L2 capture device. The frame source deliberately never
// calls VIDIOC_S_FMT: the writer on the other side of the loopback device owns
// the format, and asking it to change would drop the frames in flight. Whatever
// format the writer picked is what the HAL converts into the output buffers the
// camera framework asks for.
#ifndef ANDROIDBOX_CAMERA_FRAMESOURCE_H
#define ANDROIDBOX_CAMERA_FRAMESOURCE_H

#include <cstdint>
#include <condition_variable>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace androidbox {
namespace camera {

class FrameSource {
public:
    struct Frame {
        uint32_t width = 0;
        uint32_t height = 0;
        uint32_t fourcc = 0;  // V4L2 fourcc of the pixel data.
        int64_t timestampNs = 0;
        std::vector<uint8_t> planes;
    };

    FrameSource() = default;
    ~FrameSource();

    FrameSource(const FrameSource&) = delete;
    FrameSource& operator=(const FrameSource&) = delete;

    // Opens the device and starts a background thread that keeps one buffer
    // dequeued. Returns false with a message logged when the device is absent
    // or does not support capture.
    bool start(const std::string& device);
    void stop();

    // Waits up to timeoutMs for a frame newer than the last one returned.
    // Returns false when the device stops producing frames.
    bool waitForFrame(Frame& out, int timeoutMs);

    // The format the device currently carries, for the static characteristics.
    uint32_t width() const;
    uint32_t height() const;

    bool running() const { return running_; }

private:
    void run();
    bool setupBuffers();
    void teardownBuffers();
    bool queryFormat();

    int fd_ = -1;
    bool running_ = false;
    std::string device_;

    // Mutable so the size accessors can stay const.
    mutable std::mutex mutex_;
    std::condition_variable frameReady_;
    uint64_t frameSerial_ = 0;   // Increments for every frame captured.
    uint64_t seenSerial_ = 0;    // Last serial handed to a caller.
    Frame frame_;

    std::vector<void*> buffers_;
    std::vector<size_t> bufferLengths_;
    std::thread thread_;
};

}  // namespace camera
}  // namespace androidbox

#endif  // ANDROIDBOX_CAMERA_FRAMESOURCE_H
