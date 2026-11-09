// Read frames from the loopback camera device.
#include "framesource.h"

#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>

#include <android/log.h>
#include <chrono>
#include <linux/videodev2.h>

namespace androidbox {
namespace camera {

namespace {

constexpr int kBufferCount = 2;
constexpr int kMaxFrameBytes = 32u << 20;  // Sanity cap for 8192x8192 YUV.

void logError(const char* what) {
    __android_log_print(ANDROID_LOG_ERROR, "androidbox-camera", "%s: %s", what, strerror(errno));
}

}  // namespace

FrameSource::~FrameSource() {
    stop();
}

bool FrameSource::start(const std::string& device) {
    device_ = device;
    fd_ = open(device.c_str(), O_RDWR | O_NONBLOCK | O_CLOEXEC);
    if (fd_ < 0) {
        logError("cannot open the loopback camera");
        return false;
    }
    struct v4l2_capability capability = {};
    if (ioctl(fd_, VIDIOC_QUERYCAP, &capability) < 0) {
        logError("the loopback camera has no V4L2 capabilities");
        close(fd_);
        fd_ = -1;
        return false;
    }
    if ((capability.capabilities & V4L2_CAP_VIDEO_CAPTURE) == 0) {
        __android_log_print(ANDROID_LOG_ERROR, "androidbox-camera",
                            "the loopback camera does not capture");
        close(fd_);
        fd_ = -1;
        return false;
    }
    if (!queryFormat()) {
        close(fd_);
        fd_ = -1;
        return false;
    }
    if (!setupBuffers()) {
        close(fd_);
        fd_ = -1;
        return false;
    }
    running_ = true;
    thread_ = std::thread([this] { run(); });
    __android_log_print(ANDROID_LOG_INFO, "androidbox-camera",
                        "streaming %ux%u from %s", frame_.width, frame_.height, device.c_str());
    return true;
}

void FrameSource::stop() {
    running_ = false;
    frameReady_.notify_all();
    if (thread_.joinable()) {
        thread_.join();
    }
    teardownBuffers();
    if (fd_ >= 0) {
        close(fd_);
        fd_ = -1;
    }
}

bool FrameSource::queryFormat() {
    struct v4l2_format format = {};
    format.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (ioctl(fd_, VIDIOC_G_FMT, &format) < 0) {
        logError("cannot read the loopback camera format");
        return false;
    }
    const uint32_t width = format.fmt.pix.width;
    const uint32_t height = format.fmt.pix.height;
    const uint32_t fourcc = format.fmt.pix.pixelformat;
    if (width == 0 || height == 0 || width > 8192 || height > 8192) {
        __android_log_print(ANDROID_LOG_ERROR, "androidbox-camera",
                            "the loopback camera reports an unusable size %ux%u", width, height);
        return false;
    }
    {
        std::lock_guard<std::mutex> lock(mutex_);
        frame_.width = width;
        frame_.height = height;
        frame_.fourcc = fourcc;
    }
    return true;
}

bool FrameSource::setupBuffers() {
    struct v4l2_requestbuffers request = {};
    request.count = kBufferCount;
    request.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    request.memory = V4L2_MEMORY_MMAP;
    if (ioctl(fd_, VIDIOC_REQBUFS, &request) < 0) {
        logError("cannot request loopback camera buffers");
        return false;
    }
    const int count = static_cast<int>(request.count);
    for (int index = 0; index < count; ++index) {
        struct v4l2_buffer buffer = {};
        buffer.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        buffer.memory = V4L2_MEMORY_MMAP;
        buffer.index = static_cast<uint32_t>(index);
        if (ioctl(fd_, VIDIOC_QUERYBUF, &buffer) < 0) {
            logError("cannot query a loopback camera buffer");
            teardownBuffers();
            return false;
        }
        if (buffer.length == 0 || buffer.length > kMaxFrameBytes) {
            __android_log_print(ANDROID_LOG_ERROR, "androidbox-camera",
                                "loopback camera buffer %d has an unusable size %u", index,
                                buffer.length);
            teardownBuffers();
            return false;
        }
        void* mapped = mmap(nullptr, buffer.length, PROT_READ | PROT_WRITE, MAP_SHARED, fd_,
                            buffer.m.offset);
        if (mapped == MAP_FAILED) {
            logError("cannot map a loopback camera buffer");
            teardownBuffers();
            return false;
        }
        buffers_.push_back(mapped);
        bufferLengths_.push_back(buffer.length);
        if (ioctl(fd_, VIDIOC_QBUF, &buffer) < 0) {
            logError("cannot queue a loopback camera buffer");
            teardownBuffers();
            return false;
        }
    }
    int type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (ioctl(fd_, VIDIOC_STREAMON, &type) < 0) {
        logError("cannot start the loopback camera stream");
        teardownBuffers();
        return false;
    }
    return true;
}

void FrameSource::teardownBuffers() {
    if (fd_ >= 0 && !buffers_.empty()) {
        int type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        ioctl(fd_, VIDIOC_STREAMOFF, &type);
    }
    for (void* mapped : buffers_) {
        munmap(mapped, 0);
    }
    buffers_.clear();
    bufferLengths_.clear();
    if (fd_ >= 0) {
        struct v4l2_requestbuffers release = {};
        release.count = 0;
        release.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        release.memory = V4L2_MEMORY_MMAP;
        ioctl(fd_, VIDIOC_REQBUFS, &release);
    }
}

void FrameSource::run() {
    uint32_t lastWidth = frame_.width;
    uint32_t lastHeight = frame_.height;
    uint32_t lastFourcc = frame_.fourcc;
    while (running_) {
        struct pollfd descriptor = {};
        descriptor.fd = fd_;
        descriptor.events = POLLIN;
        const int ready = poll(&descriptor, 1, 250);
        if (ready < 0) {
            if (errno == EINTR) {
                continue;
            }
            logError("polling the loopback camera failed");
            break;
        }
        if (ready == 0) {
            continue;
        }
        struct v4l2_buffer buffer = {};
        buffer.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        buffer.memory = V4L2_MEMORY_MMAP;
        if (ioctl(fd_, VIDIOC_DQBUF, &buffer) < 0) {
            if (errno == EAGAIN) {
                continue;
            }
            logError("dequeuing from the loopback camera failed");
            break;
        }
        size_t used = buffer.bytesused;
        const size_t capacity = bufferLengths_[buffer.index];
        if (used > capacity) {
            used = capacity;
        }
        Frame captured;
        // The loopback device tells us the frame size through the format it was
        // last asked for, not through the buffer itself.
        {
            std::lock_guard<std::mutex> lock(mutex_);
            captured.width = frame_.width;
            captured.height = frame_.height;
            captured.fourcc = frame_.fourcc;
        }
        captured.timestampNs = static_cast<int64_t>(buffer.timestamp.tv_sec) * 1000000000LL +
                               buffer.timestamp.tv_usec * 1000LL;
        captured.planes.assign(static_cast<const uint8_t*>(buffers_[buffer.index]),
                               static_cast<const uint8_t*>(buffers_[buffer.index]) + used);
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (captured.width != lastWidth || captured.height != lastHeight ||
                captured.fourcc != lastFourcc) {
                // The writer changed the format under us; remember it so the
                // characteristics stay honest for the next session.
                __android_log_print(ANDROID_LOG_INFO, "androidbox-camera",
                                    "loopback camera format changed to %ux%u", captured.width,
                                    captured.height);
                lastWidth = captured.width;
                lastHeight = captured.height;
                lastFourcc = captured.fourcc;
                frame_.width = captured.width;
                frame_.height = captured.height;
                frame_.fourcc = captured.fourcc;
            }
            frame_.planes = std::move(captured.planes);
            frame_.timestampNs = captured.timestampNs;
            ++frameSerial_;
        }
        frameReady_.notify_all();
        if (ioctl(fd_, VIDIOC_QBUF, &buffer) < 0) {
            logError("requeueing a loopback camera buffer failed");
            break;
        }
    }
    running_ = false;
    frameReady_.notify_all();
}

bool FrameSource::waitForFrame(Frame& out, int timeoutMs) {
    std::unique_lock<std::mutex> lock(mutex_);
    const bool arrived = frameReady_.wait_for(lock, std::chrono::milliseconds(timeoutMs),
                                              [this] { return frameSerial_ > seenSerial_; });
    if (!arrived || frameSerial_ == seenSerial_) {
        return false;
    }
    out = frame_;
    seenSerial_ = frameSerial_;
    return true;
}

uint32_t FrameSource::width() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return frame_.width;
}

uint32_t FrameSource::height() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return frame_.height;
}

}  // namespace camera
}  // namespace androidbox
