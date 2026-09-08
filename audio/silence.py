"""Audio-level detection, not speech recognition; sample duration is the clock."""
from audio.audio_converter import levels


class ActivityDetector:
    def __init__(self, threshold_db=-55):
        self.threshold_db = threshold_db
        self.quiet_seconds = 0
        self.active_seconds = 0

    def feed(self, data):
        active = levels(data)[1] > self.threshold_db
        duration = len(data) / 32000
        if active:
            self.quiet_seconds = 0
            self.active_seconds += duration
        else:
            self.quiet_seconds += duration
            self.active_seconds = 0
        return active
