# TODO

## Timeline precision

Currently the timeline loads a sampled subset of frames (every ~Nth frame) for performance. This means arrow keys, play, and step buttons jump by ~30 seconds instead of the actual 2-second capture interval.

To fix: load full-density frames for a small window around the current position (e.g. ±100 frames) for stepping/play, while keeping the sampled overview for the slider's full-day range.

## Camera focus controls

AF mode, lens position, and AF window changes cause MediaMTX to restart the entire camera pipeline, which crashes the stream. These controls are disabled. A future MediaMTX version with a proper PATCH API for rpiCamera settings (that doesn't restart the pipeline for focus changes) would fix this.

## MediaMTX version

Stuck on v1.12.0 because v1.16.3 has H.264 encoder issues (`ioctl(VIDIOC_QBUF) failed`) on Pi Zero 2 W. The newer version has a proper `PATCH /v3/config/paths/patch/cam` API that allows hot-reloading camera settings without pipeline restart. Periodically check if newer versions fix the encoder issue.

## Image flip controls

Flip vertical / mirror horizontal (rpiCameraVFlip, rpiCameraHFlip) are not in the hot-reloadable settings list — changing them restarts the camera pipeline. Could add them with a restart warning.

## ffmpeg strftime

ffmpeg's `-strftime` flag doesn't work with RTSP input on Pi's ffmpeg version. Worked around by using `-update 1` (overwrite `latest.jpg`) and Python-side timestamping. If a future ffmpeg version fixes this, the capture could be simplified.
