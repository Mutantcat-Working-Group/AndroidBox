// The static camera characteristics this provider reports.
#include "characteristics.h"

namespace androidbox {
namespace camera {

namespace {

// The pixel formats the framework may ask an output stream for. HAL_PIXEL_FORMAT_*
// values are the graphics HAL's, not Android's public constants.
constexpr int32_t kHalPixelFormatBlob = 33;
constexpr int32_t kHalPixelFormatImplementationDefined = 34;
constexpr int32_t kHalPixelFormatYcrcb420888 = 35;
constexpr int32_t kHalPixelFormatRgba8888 = 1;

const std::vector<CameraSize>& sizeList() {
    static const std::vector<CameraSize> sizes = {
        {640, 480},
        {1280, 720},
        {1920, 1080},
        {320, 240},
    };
    return sizes;
}

const std::vector<int32_t>& halFormats() {
    static const std::vector<int32_t> formats = {
        kHalPixelFormatImplementationDefined,
        kHalPixelFormatYcrcb420888,
        kHalPixelFormatRgba8888,
        kHalPixelFormatBlob,
    };
    return formats;
}

void addStreamConfigurations(MetadataBuilder& builder, uint32_t sensorWidth,
                             uint32_t sensorHeight) {
    // One entry per (format, size) pair the app may configure, plus the output
    // direction flag the framework expects as the fourth value.
    std::vector<int32_t> configurations;
    std::vector<int64_t> minDurations;
    std::vector<int64_t> stallDurations;
    for (const CameraSize& size : sizeList()) {
        for (int32_t format : halFormats()) {
            configurations.push_back(format);
            configurations.push_back(static_cast<int32_t>(size.width));
            configurations.push_back(static_cast<int32_t>(size.height));
            configurations.push_back(ANDROID_SCALER_AVAILABLE_STREAM_CONFIGURATIONS_OUTPUT);
            minDurations.push_back(format);
            minDurations.push_back(static_cast<int64_t>(size.width));
            minDurations.push_back(static_cast<int64_t>(size.height));
            minDurations.push_back(33333333);  // 30 fps.
            stallDurations.push_back(format);
            stallDurations.push_back(static_cast<int64_t>(size.width));
            stallDurations.push_back(static_cast<int64_t>(size.height));
            // A JPEG stream stalls the pipeline for as long as encoding takes.
            stallDurations.push_back(format == kHalPixelFormatBlob ? 1000000000 : 0);
        }
    }
    builder.addInt32(ANDROID_SCALER_AVAILABLE_STREAM_CONFIGURATIONS, configurations.data(),
                     configurations.size());
    builder.addInt64(ANDROID_SCALER_AVAILABLE_MIN_FRAME_DURATIONS, minDurations.data(),
                     minDurations.size());
    builder.addInt64(ANDROID_SCALER_AVAILABLE_STALL_DURATIONS, stallDurations.data(),
                    stallDurations.size());

    const int32_t activeArray[4] = {0, 0, static_cast<int32_t>(sensorWidth),
                                    static_cast<int32_t>(sensorHeight)};
    builder.addInt32(ANDROID_SENSOR_INFO_PRE_CORRECTION_ACTIVE_ARRAY_SIZE, activeArray, 4);
    builder.addInt32(ANDROID_SENSOR_INFO_ACTIVE_ARRAY_SIZE, activeArray, 4);
    const int32_t pixelArray[2] = {static_cast<int32_t>(sensorWidth),
                                   static_cast<int32_t>(sensorHeight)};
    builder.addInt32(ANDROID_SENSOR_INFO_PIXEL_ARRAY_SIZE, pixelArray, 2);
}

}  // namespace

const std::vector<CameraSize>& supportedSizes() {
    return sizeList();
}

std::vector<uint8_t> buildCharacteristics(uint32_t sensorWidth, uint32_t sensorHeight) {
    if (sensorWidth == 0 || sensorHeight == 0) {
        sensorWidth = 640;
        sensorHeight = 480;
    }
    MetadataBuilder builder;

    // android.colorCorrection
    const uint8_t aberrationMode = ANDROID_COLOR_CORRECTION_ABERRATION_MODE_OFF;
    builder.addByte(ANDROID_COLOR_CORRECTION_AVAILABLE_ABERRATION_MODES, &aberrationMode, 1);

    // android.control
    const uint8_t antibandingMode = ANDROID_CONTROL_AE_ANTIBANDING_MODE_AUTO;
    builder.addByte(ANDROID_CONTROL_AE_AVAILABLE_ANTIBANDING_MODES, &antibandingMode, 1);
    const int32_t compensationRange[2] = {0, 0};
    builder.addInt32(ANDROID_CONTROL_AE_COMPENSATION_RANGE, compensationRange, 2);
    const MetadataRational compensationStep = {0, 1};
    builder.addRational(ANDROID_CONTROL_AE_COMPENSATION_STEP, &compensationStep, 1);
    const uint8_t aeLockAvailable = ANDROID_CONTROL_AE_LOCK_AVAILABLE_FALSE;
    builder.addByte(ANDROID_CONTROL_AE_LOCK_AVAILABLE, &aeLockAvailable, 1);
    const uint8_t awbLockAvailable = ANDROID_CONTROL_AWB_LOCK_AVAILABLE_FALSE;
    builder.addByte(ANDROID_CONTROL_AWB_LOCK_AVAILABLE, &awbLockAvailable, 1);
    const uint8_t afModes[] = {ANDROID_CONTROL_AF_MODE_OFF, ANDROID_CONTROL_AF_MODE_AUTO};
    builder.addByte(ANDROID_CONTROL_AF_AVAILABLE_MODES, afModes, 2);
    const int32_t maxRegions[3] = {0, 0, 0};
    builder.addInt32(ANDROID_CONTROL_MAX_REGIONS, maxRegions, 3);
    const uint8_t videoStabilization = ANDROID_CONTROL_VIDEO_STABILIZATION_MODE_OFF;
    builder.addByte(ANDROID_CONTROL_AVAILABLE_VIDEO_STABILIZATION_MODES, &videoStabilization, 1);
    const uint8_t awbMode = ANDROID_CONTROL_AWB_MODE_AUTO;
    builder.addByte(ANDROID_CONTROL_AWB_AVAILABLE_MODES, &awbMode, 1);
    const uint8_t aeMode = ANDROID_CONTROL_AE_MODE_ON;
    builder.addByte(ANDROID_CONTROL_AE_AVAILABLE_MODES, &aeMode, 1);
    const uint8_t effectMode = ANDROID_CONTROL_EFFECT_MODE_OFF;
    builder.addByte(ANDROID_CONTROL_AVAILABLE_EFFECTS, &effectMode, 1);
    const uint8_t controlModes[] = {ANDROID_CONTROL_MODE_OFF, ANDROID_CONTROL_MODE_AUTO};
    builder.addByte(ANDROID_CONTROL_AVAILABLE_MODES, controlModes, 2);
    const uint8_t sceneMode = ANDROID_CONTROL_SCENE_MODE_DISABLED;
    builder.addByte(ANDROID_CONTROL_AVAILABLE_SCENE_MODES, &sceneMode, 1);
    const int32_t fpsRanges[] = {5, 30, 15, 30};
    builder.addInt32(ANDROID_CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES, fpsRanges, 4);

    // android.edge
    const uint8_t edgeMode = ANDROID_EDGE_MODE_OFF;
    builder.addByte(ANDROID_EDGE_AVAILABLE_EDGE_MODES, &edgeMode, 1);

    // android.flash
    const uint8_t flashAvailable = ANDROID_FLASH_INFO_AVAILABLE_FALSE;
    builder.addByte(ANDROID_FLASH_INFO_AVAILABLE, &flashAvailable, 1);

    // android.hotPixel
    const uint8_t hotPixelMode = ANDROID_HOT_PIXEL_MODE_OFF;
    builder.addByte(ANDROID_HOT_PIXEL_AVAILABLE_HOT_PIXEL_MODES, &hotPixelMode, 1);

    // android.info
    const uint8_t hardwareLevel = ANDROID_INFO_SUPPORTED_HARDWARE_LEVEL_EXTERNAL;
    builder.addByte(ANDROID_INFO_SUPPORTED_HARDWARE_LEVEL, &hardwareLevel, 1);
    // Declaring HAL buffer management tells the framework to leave the output
    // buffers with the HAL: requests then arrive without handles attached and
    // the session pulls them through requestStreamBuffers instead. Without this
    // entry the framework attaches the buffers to every request and rejects
    // requestStreamBuffers outright.
    const uint8_t bufferManagement =
            ANDROID_INFO_SUPPORTED_BUFFER_MANAGEMENT_VERSION_HIDL_DEVICE_3_5;
    builder.addByte(ANDROID_INFO_SUPPORTED_BUFFER_MANAGEMENT_VERSION, &bufferManagement, 1);

    // android.jpeg
    const int32_t thumbnailSizes[] = {0, 0, 176, 144, 240, 144, 256, 144};
    builder.addInt32(ANDROID_JPEG_AVAILABLE_THUMBNAIL_SIZES, thumbnailSizes, 8);
    // The framework allocates the BLOB buffers from this number, so it has to
    // cover the worst case encoder output for the largest advertised size.
    const int32_t jpegMaxSize = static_cast<int32_t>(sensorWidth * sensorHeight * 3 / 2) + (128 << 10);
    builder.addInt32(ANDROID_JPEG_MAX_SIZE, &jpegMaxSize, 1);

    // android.lens
    const uint8_t focusCalibration = ANDROID_LENS_INFO_FOCUS_DISTANCE_CALIBRATION_UNCALIBRATED;
    builder.addByte(ANDROID_LENS_INFO_FOCUS_DISTANCE_CALIBRATION, &focusCalibration, 1);
    const uint8_t opticalStabilization = ANDROID_LENS_OPTICAL_STABILIZATION_MODE_OFF;
    builder.addByte(ANDROID_LENS_INFO_AVAILABLE_OPTICAL_STABILIZATION, &opticalStabilization, 1);
    const uint8_t facing = ANDROID_LENS_FACING_EXTERNAL;
    builder.addByte(ANDROID_LENS_FACING, &facing, 1);

    // android.noiseReduction
    const uint8_t noiseReduction = ANDROID_NOISE_REDUCTION_MODE_OFF;
    builder.addByte(ANDROID_NOISE_REDUCTION_AVAILABLE_NOISE_REDUCTION_MODES, &noiseReduction, 1);

    // android.request
    const int32_t partialResultCount = 1;
    builder.addInt32(ANDROID_REQUEST_PARTIAL_RESULT_COUNT, &partialResultCount, 1);
    const uint8_t pipelineDepth = 4;
    builder.addByte(ANDROID_REQUEST_PIPELINE_MAX_DEPTH, &pipelineDepth, 1);
    const int32_t maxOutputStreams[3] = {0, 3, 1};
    builder.addInt32(ANDROID_REQUEST_MAX_NUM_OUTPUT_STREAMS, maxOutputStreams, 3);
    const int32_t maxInputStreams = 0;
    builder.addInt32(ANDROID_REQUEST_MAX_NUM_INPUT_STREAMS, &maxInputStreams, 1);

    // android.scaler
    const float maxDigitalZoom = 1.0f;
    builder.addFloat(ANDROID_SCALER_AVAILABLE_MAX_DIGITAL_ZOOM, &maxDigitalZoom, 1);
    const uint8_t croppingType = ANDROID_SCALER_CROPPING_TYPE_CENTER_ONLY;
    builder.addByte(ANDROID_SCALER_CROPPING_TYPE, &croppingType, 1);

    // android.sensor
    const int32_t testPatternModes[] = {ANDROID_SENSOR_TEST_PATTERN_MODE_OFF,
                                        ANDROID_SENSOR_TEST_PATTERN_MODE_SOLID_COLOR};
    builder.addInt32(ANDROID_SENSOR_AVAILABLE_TEST_PATTERN_MODES, testPatternModes, 2);
    const uint8_t timestampSource = ANDROID_SENSOR_INFO_TIMESTAMP_SOURCE_UNKNOWN;
    builder.addByte(ANDROID_SENSOR_INFO_TIMESTAMP_SOURCE, &timestampSource, 1);
    const int32_t orientation = 0;
    builder.addInt32(ANDROID_SENSOR_ORIENTATION, &orientation, 1);
    const int64_t maxFrameDuration = 200000000LL;  // 5 fps floor.
    builder.addInt64(ANDROID_SENSOR_INFO_MAX_FRAME_DURATION, &maxFrameDuration, 1);

    // android.shading
    const uint8_t shadingMode = ANDROID_SHADING_MODE_OFF;
    builder.addByte(ANDROID_SHADING_AVAILABLE_MODES, &shadingMode, 1);

    // android.statistics
    const uint8_t faceDetectMode = ANDROID_STATISTICS_FACE_DETECT_MODE_OFF;
    builder.addByte(ANDROID_STATISTICS_INFO_AVAILABLE_FACE_DETECT_MODES, &faceDetectMode, 1);
    const int32_t maxFaceCount = 0;
    builder.addInt32(ANDROID_STATISTICS_INFO_MAX_FACE_COUNT, &maxFaceCount, 1);
    const uint8_t hotPixelMapMode = ANDROID_STATISTICS_HOT_PIXEL_MAP_MODE_OFF;
    builder.addByte(ANDROID_STATISTICS_INFO_AVAILABLE_HOT_PIXEL_MAP_MODES, &hotPixelMapMode, 1);
    const uint8_t lensShadingMapMode = ANDROID_STATISTICS_LENS_SHADING_MAP_MODE_OFF;
    builder.addByte(ANDROID_STATISTICS_INFO_AVAILABLE_LENS_SHADING_MAP_MODES, &lensShadingMapMode, 1);

    // android.sync
    const int32_t maxLatency = ANDROID_SYNC_MAX_LATENCY_UNKNOWN;
    builder.addInt32(ANDROID_SYNC_MAX_LATENCY, &maxLatency, 1);

    addStreamConfigurations(builder, sensorWidth, sensorHeight);

    // The camera announces one capability: it is backward compatible with the
    // old camera API, which is what most camera apps still use.
    const uint8_t capabilities[] = {ANDROID_REQUEST_AVAILABLE_CAPABILITIES_BACKWARD_COMPATIBLE};
    builder.addByte(ANDROID_REQUEST_AVAILABLE_CAPABILITIES, capabilities, 1);

    const int32_t requestKeys[] = {
        ANDROID_CONTROL_AE_MODE,
        ANDROID_CONTROL_AF_MODE,
        ANDROID_CONTROL_AWB_MODE,
        ANDROID_CONTROL_CAPTURE_INTENT,
        ANDROID_CONTROL_EFFECT_MODE,
        ANDROID_CONTROL_MODE,
        ANDROID_CONTROL_SCENE_MODE,
        ANDROID_CONTROL_VIDEO_STABILIZATION_MODE,
        ANDROID_JPEG_ORIENTATION,
        ANDROID_JPEG_QUALITY,
        ANDROID_JPEG_THUMBNAIL_QUALITY,
        ANDROID_JPEG_THUMBNAIL_SIZE,
        ANDROID_SCALER_CROP_REGION,
        ANDROID_STATISTICS_FACE_DETECT_MODE,
        ANDROID_NOISE_REDUCTION_MODE,
        ANDROID_EDGE_MODE,
        ANDROID_COLOR_CORRECTION_ABERRATION_MODE,
    };
    builder.addInt32(ANDROID_REQUEST_AVAILABLE_REQUEST_KEYS, requestKeys,
                     sizeof(requestKeys) / sizeof(requestKeys[0]));

    const int32_t resultKeys[] = {
        ANDROID_CONTROL_AE_MODE,
        ANDROID_CONTROL_AF_MODE,
        ANDROID_CONTROL_AF_STATE,
        ANDROID_CONTROL_AWB_MODE,
        ANDROID_CONTROL_CAPTURE_INTENT,
        ANDROID_CONTROL_EFFECT_MODE,
        ANDROID_CONTROL_MODE,
        ANDROID_CONTROL_SCENE_MODE,
        ANDROID_CONTROL_VIDEO_STABILIZATION_MODE,
        ANDROID_JPEG_ORIENTATION,
        ANDROID_JPEG_QUALITY,
        ANDROID_JPEG_THUMBNAIL_QUALITY,
        ANDROID_JPEG_THUMBNAIL_SIZE,
        ANDROID_SCALER_CROP_REGION,
        ANDROID_STATISTICS_FACE_DETECT_MODE,
        ANDROID_NOISE_REDUCTION_MODE,
        ANDROID_EDGE_MODE,
        ANDROID_COLOR_CORRECTION_ABERRATION_MODE,
        ANDROID_SENSOR_TIMESTAMP,
        ANDROID_REQUEST_PIPELINE_DEPTH,
        ANDROID_FLASH_STATE,
    };
    builder.addInt32(ANDROID_REQUEST_AVAILABLE_RESULT_KEYS, resultKeys,
                     sizeof(resultKeys) / sizeof(resultKeys[0]));

    const int32_t characteristicsKeys[] = {
        ANDROID_COLOR_CORRECTION_AVAILABLE_ABERRATION_MODES,
        ANDROID_CONTROL_AE_AVAILABLE_ANTIBANDING_MODES,
        ANDROID_CONTROL_AE_AVAILABLE_MODES,
        ANDROID_CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES,
        ANDROID_CONTROL_AE_COMPENSATION_RANGE,
        ANDROID_CONTROL_AE_COMPENSATION_STEP,
        ANDROID_CONTROL_AE_LOCK_AVAILABLE,
        ANDROID_CONTROL_AF_AVAILABLE_MODES,
        ANDROID_CONTROL_AVAILABLE_EFFECTS,
        ANDROID_CONTROL_AVAILABLE_MODES,
        ANDROID_CONTROL_AVAILABLE_SCENE_MODES,
        ANDROID_CONTROL_AVAILABLE_VIDEO_STABILIZATION_MODES,
        ANDROID_CONTROL_AWB_AVAILABLE_MODES,
        ANDROID_CONTROL_AWB_LOCK_AVAILABLE,
        ANDROID_CONTROL_MAX_REGIONS,
        ANDROID_EDGE_AVAILABLE_EDGE_MODES,
        ANDROID_FLASH_INFO_AVAILABLE,
        ANDROID_HOT_PIXEL_AVAILABLE_HOT_PIXEL_MODES,
        ANDROID_INFO_SUPPORTED_BUFFER_MANAGEMENT_VERSION,
        ANDROID_INFO_SUPPORTED_HARDWARE_LEVEL,
        ANDROID_JPEG_AVAILABLE_THUMBNAIL_SIZES,
        ANDROID_JPEG_MAX_SIZE,
        ANDROID_LENS_FACING,
        ANDROID_LENS_INFO_AVAILABLE_OPTICAL_STABILIZATION,
        ANDROID_LENS_INFO_FOCUS_DISTANCE_CALIBRATION,
        ANDROID_NOISE_REDUCTION_AVAILABLE_NOISE_REDUCTION_MODES,
        ANDROID_REQUEST_AVAILABLE_CAPABILITIES,
        ANDROID_REQUEST_AVAILABLE_CHARACTERISTICS_KEYS,
        ANDROID_REQUEST_AVAILABLE_REQUEST_KEYS,
        ANDROID_REQUEST_AVAILABLE_RESULT_KEYS,
        ANDROID_REQUEST_MAX_NUM_INPUT_STREAMS,
        ANDROID_REQUEST_MAX_NUM_OUTPUT_STREAMS,
        ANDROID_REQUEST_PARTIAL_RESULT_COUNT,
        ANDROID_REQUEST_PIPELINE_MAX_DEPTH,
        ANDROID_SCALER_AVAILABLE_MAX_DIGITAL_ZOOM,
        ANDROID_SCALER_AVAILABLE_MIN_FRAME_DURATIONS,
        ANDROID_SCALER_AVAILABLE_STALL_DURATIONS,
        ANDROID_SCALER_AVAILABLE_STREAM_CONFIGURATIONS,
        ANDROID_SCALER_CROPPING_TYPE,
        ANDROID_SENSOR_AVAILABLE_TEST_PATTERN_MODES,
        ANDROID_SENSOR_INFO_ACTIVE_ARRAY_SIZE,
        ANDROID_SENSOR_INFO_MAX_FRAME_DURATION,
        ANDROID_SENSOR_INFO_PIXEL_ARRAY_SIZE,
        ANDROID_SENSOR_INFO_PRE_CORRECTION_ACTIVE_ARRAY_SIZE,
        ANDROID_SENSOR_INFO_TIMESTAMP_SOURCE,
        ANDROID_SENSOR_ORIENTATION,
        ANDROID_SHADING_AVAILABLE_MODES,
        ANDROID_STATISTICS_FACE_DETECT_MODE,
        ANDROID_STATISTICS_INFO_AVAILABLE_FACE_DETECT_MODES,
        ANDROID_STATISTICS_INFO_AVAILABLE_HOT_PIXEL_MAP_MODES,
        ANDROID_STATISTICS_INFO_AVAILABLE_LENS_SHADING_MAP_MODES,
        ANDROID_STATISTICS_INFO_MAX_FACE_COUNT,
        ANDROID_SYNC_MAX_LATENCY,
    };
    builder.addInt32(ANDROID_REQUEST_AVAILABLE_CHARACTERISTICS_KEYS, characteristicsKeys,
                     sizeof(characteristicsKeys) / sizeof(characteristicsKeys[0]));

    return builder.build();
}

std::vector<uint8_t> buildDefaultRequestSettings(int templateType) {
    MetadataBuilder builder;
    const uint8_t aeMode = ANDROID_CONTROL_AE_MODE_ON;
    builder.addByte(ANDROID_CONTROL_AE_MODE, &aeMode, 1);
    const uint8_t awbMode = ANDROID_CONTROL_AWB_MODE_AUTO;
    builder.addByte(ANDROID_CONTROL_AWB_MODE, &awbMode, 1);
    const uint8_t afMode = ANDROID_CONTROL_AF_MODE_OFF;
    builder.addByte(ANDROID_CONTROL_AF_MODE, &afMode, 1);
    const uint8_t controlMode = ANDROID_CONTROL_MODE_AUTO;
    builder.addByte(ANDROID_CONTROL_MODE, &controlMode, 1);
    const uint8_t aberrationMode = ANDROID_COLOR_CORRECTION_ABERRATION_MODE_OFF;
    builder.addByte(ANDROID_COLOR_CORRECTION_ABERRATION_MODE, &aberrationMode, 1);
    const uint8_t edgeMode = ANDROID_EDGE_MODE_OFF;
    builder.addByte(ANDROID_EDGE_MODE, &edgeMode, 1);
    const uint8_t noiseReduction = ANDROID_NOISE_REDUCTION_MODE_OFF;
    builder.addByte(ANDROID_NOISE_REDUCTION_MODE, &noiseReduction, 1);
    const uint8_t faceDetect = ANDROID_STATISTICS_FACE_DETECT_MODE_OFF;
    builder.addByte(ANDROID_STATISTICS_FACE_DETECT_MODE, &faceDetect, 1);
    const uint8_t videoStabilization = ANDROID_CONTROL_VIDEO_STABILIZATION_MODE_OFF;
    builder.addByte(ANDROID_CONTROL_VIDEO_STABILIZATION_MODE, &videoStabilization, 1);
    const uint8_t intent = templateType == 2 ? ANDROID_CONTROL_CAPTURE_INTENT_STILL_CAPTURE
                                             : ANDROID_CONTROL_CAPTURE_INTENT_PREVIEW;
    builder.addByte(ANDROID_CONTROL_CAPTURE_INTENT, &intent, 1);
    const uint8_t jpegQuality = 90;
    builder.addByte(ANDROID_JPEG_QUALITY, &jpegQuality, 1);
    const int32_t jpegOrientation = 0;
    builder.addInt32(ANDROID_JPEG_ORIENTATION, &jpegOrientation, 1);
    const int32_t thumbnailSize[2] = {0, 0};
    builder.addInt32(ANDROID_JPEG_THUMBNAIL_SIZE, thumbnailSize, 2);
    const uint8_t thumbnailQuality = 85;
    builder.addByte(ANDROID_JPEG_THUMBNAIL_QUALITY, &thumbnailQuality, 1);
    const int32_t fpsRange[2] = {15, 30};
    builder.addInt32(ANDROID_CONTROL_AE_TARGET_FPS_RANGE, fpsRange, 2);
    return builder.build();
}

}  // namespace camera
}  // namespace androidbox
