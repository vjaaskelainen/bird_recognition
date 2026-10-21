from bird_recognition.ingest.models import Detection


class FakeDetector:
    def __init__(self, detections: list[Detection] | None = None) -> None:
        self.detections = detections or []
        self.calls = 0

    def detect(self, image: object) -> list[Detection]:
        self.calls += 1
        return self.detections


class ScriptedDetector:
    def __init__(self, results: list[list[Detection] | Exception]) -> None:
        self.results = results
        self.calls = 0

    def detect(self, image: object) -> list[Detection]:
        del image
        result = self.results[self.calls]
        self.calls += 1
        if isinstance(result, Exception):
            raise result
        return result
