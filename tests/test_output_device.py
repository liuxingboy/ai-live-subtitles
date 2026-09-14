import threading
import unittest
from unittest.mock import Mock, patch
from audio.output_device import OutputDeviceWatcher, OutputDeviceChanged
from tools.reconnect import run_with_reconnect


class OutputDeviceTests(unittest.TestCase):
    def test_throttled_check_and_change(self):
        reader = Mock(side_effect=['headphones', 'headphones', 'speakers'])
        now = [0]
        watcher = OutputDeviceWatcher(reader, clock=lambda: now[0])
        watcher.check()
        now[0] = .2
        watcher.check()
        self.assertEqual(reader.call_count, 2)
        now[0] = .5
        with self.assertRaises(OutputDeviceChanged):
            watcher.check()

    def test_missing_endpoint_and_forced_check(self):
        with self.assertRaises(OutputDeviceChanged):
            OutputDeviceWatcher(lambda: None)
        watcher = OutputDeviceWatcher(Mock(side_effect=['a', 'a', None]), clock=lambda: 0)
        watcher.check()
        with self.assertRaises(OutputDeviceChanged):
            watcher.check(force=True)

    def test_detection_error_not_reclassified(self):
        watcher = OutputDeviceWatcher(Mock(side_effect=['a', OSError('probe failed')]))
        with self.assertRaises(OSError):
            watcher.check()

    def test_restarts_without_network_failure_count(self):
        stop = Mock()
        stop.is_set.return_value = False
        stop.wait.return_value = False
        operation = Mock(side_effect=[OutputDeviceChanged(), None])
        report = {}
        run_with_reconnect(operation, stop, report)
        self.assertEqual(operation.call_count, 2)
        self.assertEqual(report['output_device_recovery_attempts'], 1)
        self.assertNotIn('disconnects', report)

    def test_repeated_unavailable_device_is_bounded(self):
        stop = Mock()
        stop.is_set.return_value = False
        stop.wait.return_value = False
        operation = Mock(side_effect=OutputDeviceChanged())
        report = {}
        with self.assertRaisesRegex(RuntimeError, 'Windows'):
            run_with_reconnect(operation, stop, report)
        self.assertEqual(operation.call_count, 6)
        self.assertEqual(report['output_device_recovery_attempts'], 5)

    def test_stop_cancels_restart(self):
        stop = Mock()
        stop.is_set.return_value = False
        stop.wait.return_value = True
        operation = Mock(side_effect=OutputDeviceChanged())
        report = {}
        run_with_reconnect(operation, stop, report)
        self.assertEqual(operation.call_count, 1)
        self.assertNotIn('output_device_recovery_attempts', report)

    def test_native_system_releases_on_change_and_can_reopen(self):
        from audio.endpoint_capture import capture_endpoint
        from audio.output_device import default_output_id
        if default_output_id() is None:
            self.skipTest('No default render endpoint')
        with patch.object(OutputDeviceWatcher, 'check', side_effect=OutputDeviceChanged()):
            with self.assertRaises(OutputDeviceChanged):
                capture_endpoint('system', .1, threading.Event(), lambda chunk: None)
        result = capture_endpoint('system', .1, threading.Event(), lambda chunk: None)
        self.assertEqual(result.sample_rate, 16000)


if __name__ == '__main__':
    unittest.main()
