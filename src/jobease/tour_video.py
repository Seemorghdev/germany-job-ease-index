"""Record the level-3 map tour (``docs/tour/index.html``) as an MP4 for LinkedIn.

The page draws any moment of the tour on request (``TOUR.render(t)``), so recording is
deterministic: a headless Chromium steps through the frames at a fixed rate and each
screenshot is piped straight into ffmpeg. Nothing plays in real time, so a slow machine
only takes longer; it never drops frames.

Needs the ``video`` extra (Playwright and a bundled ffmpeg) and, once,
``playwright install chromium``.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from jobease.config import REPO_ROOT

TOUR_PAGE = REPO_ROOT / "docs" / "tour" / "index.html"
DEFAULT_OUT = REPO_ROOT / "docs" / "tour" / "germany-job-ease-tour.mp4"
READY_TIMEOUT_MS = 60_000


class TourError(RuntimeError):
    """The tour page could not be drawn or encoded."""


@dataclass(frozen=True)
class TourRecording:
    path: Path
    frames: int
    seconds: float
    size: tuple[int, int]


def frame_times(duration: float, fps: int) -> list[float]:
    """Every frame from 0 to the end, inclusive, so the last frame shows the end card."""
    if duration <= 0 or fps <= 0:
        raise TourError(f"need a positive duration and fps, got {duration} s at {fps} fps")
    return [i / fps for i in range(round(duration * fps) + 1)]


def ffmpeg_command(ffmpeg: str, out: Path, fps: int) -> list[str]:
    # H.264 in yuv420p with the index up front: what LinkedIn, phones and browsers all play.
    # fmt: off
    return [
        ffmpeg, "-y", "-loglevel", "error",
        "-f", "image2pipe", "-framerate", str(fps), "-c:v", "png", "-i", "-",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "slow",
        "-movflags", "+faststart",
        str(out),
    ]
    # fmt: on


def record_tour(
    out: Path = DEFAULT_OUT, *, page: Path = TOUR_PAGE, fps: int | None = None
) -> TourRecording:
    import imageio_ffmpeg
    from playwright.sync_api import sync_playwright

    if not page.exists():
        raise TourError(f"{page} is missing")
    out.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            tab = browser.new_page(viewport={"width": 1080, "height": 1350})
            tab.goto(f"{page.as_uri()}?capture=1")
            tab.wait_for_function("window.TOUR && window.TOUR.ready", timeout=READY_TIMEOUT_MS)
            tab.evaluate("document.fonts.ready.then(() => true)")
            meta = tab.evaluate(
                "({width: TOUR.width, height: TOUR.height, fps: TOUR.fps,"
                " duration: TOUR.duration, error: TOUR.error})"
            )
            if meta["error"]:
                raise TourError(f"the tour page reported: {meta['error']}")
            size = (int(meta["width"]), int(meta["height"]))
            tab.set_viewport_size({"width": size[0], "height": size[1]})
            rate = fps or int(meta["fps"])
            times = frame_times(float(meta["duration"]), rate)
            frame = tab.locator("#stage svg")

            command = ffmpeg_command(imageio_ffmpeg.get_ffmpeg_exe(), out, rate)
            with subprocess.Popen(command, stdin=subprocess.PIPE) as encoder:
                if encoder.stdin is None:
                    raise TourError("ffmpeg has no input pipe")
                try:
                    for t in times:
                        tab.evaluate("t => TOUR.render(t)", t)
                        encoder.stdin.write(frame.screenshot(type="png"))
                finally:
                    encoder.stdin.close()
            if encoder.returncode != 0:
                raise TourError(f"ffmpeg exited with {encoder.returncode}")
        finally:
            browser.close()

    return TourRecording(out, len(times), times[-1], size)
