import ctypes
import unittest
import struct
from audio.audio_converter import to_pcm16_mono, levels
from audio.chrome_detector import ChromeProcess, choose_chrome
from audio.wasapi_capture import ActivationParams, PropVariant, WaveFormat


class AudioTests(unittest.TestCase):
    def test_abi_layout(self):
        self.assertEqual(ctypes.sizeof(ActivationParams), 12)
        self.assertEqual(ctypes.sizeof(WaveFormat), 18)
        self.assertEqual(PropVariant.blob.offset, 8)
        self.assertEqual(ctypes.sizeof(PropVariant), 24 if ctypes.sizeof(ctypes.c_void_p) == 8 else 16)

    def test_format_mismatch_is_rejected(self):
        for rate, channels in ((48000, 1), (16000, 2)):
            with self.assertRaises(ValueError):
                to_pcm16_mono(bytes(8), rate, channels)

    def test_pcm_preserved_and_levels_do_not_overflow(self):
        data = struct.pack('<hhh', 32767, -32768, 0)
        self.assertEqual(to_pcm16_mono(data), data)
        peak, rms = levels(data)
        self.assertEqual(peak, 1)
        self.assertAlmostEqual(rms, -1.761, places=2)

    def test_invalid_and_silent_audio(self):
        with self.assertRaises(ValueError):
            to_pcm16_mono(b'\x00')
        self.assertEqual(to_pcm16_mono(b''), b'')
        self.assertEqual(levels(bytes(320)), (0, float('-inf')))

    def test_browser_selection_and_ambiguity(self):
        root = ChromeProcess(10, 1, 1, True)
        child = ChromeProcess(11, 10, 2, False)
        self.assertEqual(choose_chrome([root, child]), root)
        self.assertEqual(choose_chrome([root, child], 11), child)
        with self.assertRaises(RuntimeError):
            choose_chrome([])
        with self.assertRaises(RuntimeError):
            choose_chrome([root, ChromeProcess(20, 1, 3, True)])


if __name__ == '__main__':
    unittest.main()
