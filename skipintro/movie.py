"""Black replacement video for the publisher logo."""
import subprocess

# 0.2 s of black at 1280x720, 30 fps, with silent audio: same codecs as the original (H.264 + AAC).
_PIPELINE = (
    "videotestsrc pattern=black num-buffers=6 "
    "! video/x-raw,width=1280,height=720,framerate=30/1,format=I420 "
    "! openh264enc ! h264parse ! queue ! mux. "
    "audiotestsrc wave=silence num-buffers=10 samplesperbuffer=960 "
    "! audio/x-raw,rate=48000,channels=2 ! voaacenc ! aacparse ! queue ! mux. "
    "mp4mux name=mux faststart=true ! filesink location={out}"
)


class GStreamerMissing(RuntimeError):
    """Raised when GStreamer or one of the needed plugins is not installed."""


def black_movie(out):
    """Create the black video at ``out`` with GStreamer unless it already exists; return ``out``."""
    if out.is_file():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["gst-launch-1.0", "-q", "-e"] + _PIPELINE.format(out=out).split(), check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError) as error:
        raise GStreamerMissing("GStreamer is needed: gst-launch-1.0 with openh264enc, voaacenc, mp4mux") \
            from error
    return out
