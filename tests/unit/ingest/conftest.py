from collections.abc import Callable
from pathlib import Path

import pytest

from tests.unit.ingest.fakes import FakeDetector


@pytest.fixture
def fake_detector() -> FakeDetector:
    return FakeDetector()


@pytest.fixture
def frame_factory() -> Callable[[tuple[int, int], tuple[int, int, int]], object]:
    from PIL import Image

    def create_frame(
        size: tuple[int, int] = (32, 24),
        color: tuple[int, int, int] = (40, 120, 210),
    ) -> object:
        return Image.new("RGB", size, color)

    return create_frame


@pytest.fixture
def tiny_video(tmp_path: Path) -> Path:
    av = pytest.importorskip("av")
    from PIL import Image

    path = tmp_path / "tiny.mp4"
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("mpeg4", rate=2)
        stream.width = 32
        stream.height = 24
        stream.pix_fmt = "yuv420p"
        for color in ((40, 120, 210), (210, 80, 30), (30, 180, 90)):
            frame = av.VideoFrame.from_image(Image.new("RGB", (32, 24), color))
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return path
