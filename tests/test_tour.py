from __future__ import annotations

import re
from pathlib import Path

import pytest

from jobease import tour_video


def test_frame_times_cover_start_to_end_inclusive() -> None:
    times = tour_video.frame_times(2.0, 30)
    assert len(times) == 61
    assert times[0] == 0.0
    assert times[-1] == pytest.approx(2.0)


@pytest.mark.parametrize(("duration", "fps"), [(0.0, 30), (10.0, 0)])
def test_frame_times_reject_empty_tours(duration: float, fps: int) -> None:
    with pytest.raises(tour_video.TourError):
        tour_video.frame_times(duration, fps)


def test_ffmpeg_writes_h264_that_linkedin_plays(tmp_path: Path) -> None:
    out = tmp_path / "tour.mp4"
    command = tour_video.ffmpeg_command("ffmpeg", out, 30)
    joined = " ".join(command)
    assert "-i -" in joined  # frames arrive on stdin
    assert "-c:v libx264" in joined
    assert "-pix_fmt yuv420p" in joined
    assert "+faststart" in joined
    assert command[-1] == str(out)


def test_tour_page_reads_only_the_published_map_data() -> None:
    html = tour_video.TOUR_PAGE.read_text(encoding="utf-8")
    local_scripts = [s for s in re.findall(r'<script src="([^"]+)"', html) if "://" not in s]
    assert local_scripts == ["../map/data.js"]
    assert "window.TOUR" in html
    assert "render" in html
    for private in ("referenznummer", "employer", "arbeitgeber", "titel"):
        assert private not in html.lower()
