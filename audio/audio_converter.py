"""PCM validation and level reporting; WASAPI owns stateful resampling."""
from array import array
import math
import sys


def to_pcm16_mono(data, sample_rate=16000, channels=1):
    """Validate the negotiated format, avoiding accidental mislabelled WAVs."""
    if sample_rate != 16000 or channels != 1:
        raise ValueError("需要 WASAPI 输出 16000 Hz 单声道 PCM16。")
    if len(data) % 2:
        raise ValueError("PCM 数据没有对齐完整音频帧。")
    return bytes(data)


def levels(data):
    samples = array('h')
    samples.frombytes(data)
    if sys.byteorder != 'little':
        samples.byteswap()
    if not samples:
        return 0.0, float('-inf')
    peak = max(abs(value) for value in samples) / 32768
    rms = math.sqrt(sum(value * value for value in samples) / len(samples)) / 32768
    return peak, 20 * math.log10(rms) if rms else float('-inf')
