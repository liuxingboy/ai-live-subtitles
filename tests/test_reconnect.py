import threading
import json
import unittest
from unittest.mock import Mock
import websocket
from tools.api_debug import Session
from tools.reconnect import ConnectionLost, UnspecifiedASRError, ServiceError, network_error, service_error, run_with_reconnect


class FakeStop:
    def __init__(self):
        self.now = 0
        self.delays = []
        self.stopped = False

    def is_set(self):
        return self.stopped

    def wait(self, delay):
        self.delays.append(delay)
        self.now += delay
        return self.stopped


class ReconnectTests(unittest.TestCase):
    def test_paused_playback_asr_timeout_reconnects(self):
        detail = {
            'type': 'transcription_error', 'code': 'UNEXPECTED_ASR_ERROR',
            'message': 'grpc error: statusCode=504, message=Response stream timeout (timeout_seconds=300, elapsed_ms=362734)',
        }
        for event_type in ('error', 'conversation.item.input_audio_transcription.failed'):
            with self.subTest(event_type=event_type):
                ws = Mock()
                ws.recv_data.return_value = (websocket.ABNF.OPCODE_TEXT, json.dumps({'type': event_type, 'error': detail}))
                session = Session(ws, '')
                session.receive()
                self.assertTrue(session.failed.is_set())
                self.assertIsInstance(session.failure, ConnectionLost)
                stop = FakeStop()
                report = {}
                calls = []
                def attempt(_):
                    calls.append(1)
                    if len(calls) == 1:
                        session.raise_failure()
                run_with_reconnect(attempt, stop, report, clock=lambda: stop.now)
                self.assertEqual(len(calls), 2)
                self.assertEqual(stop.delays, [1])
                self.assertEqual(report['disconnects'], 1)

    def test_model_repetition_event_reconnects(self):
        detail = {'code': 'COMMON_ERROR', 'message': 'model repeat output happened'}
        ws = Mock()
        ws.recv_data.return_value = (
            websocket.ABNF.OPCODE_TEXT,
            json.dumps({'type': 'error', 'error': detail}),
        )
        session = Session(ws, '')
        session.receive()
        self.assertTrue(session.failed.is_set())
        self.assertIsInstance(session.failure, ConnectionLost)
        stop = FakeStop()
        report = {}
        calls = []
        def attempt(_):
            calls.append(1)
            if len(calls) == 1:
                session.raise_failure()
        run_with_reconnect(attempt, stop, report, clock=lambda: stop.now)
        self.assertEqual(len(calls), 2)
        self.assertEqual(stop.delays, [1])
        self.assertEqual(report['reconnect_attempts'], 1)

    def test_unknown_common_error_remains_terminal(self):
        for code, message in (
            ('COMMON_ERROR', 'unknown service failure'),
            ('invalid_api_key', 'model repeat output happened'),
        ):
            with self.subTest(code=code):
                error = service_error({'code': code, 'message': message})
                self.assertIsInstance(error, ServiceError)
                stop = FakeStop()
                with self.assertRaises(ServiceError):
                    run_with_reconnect(Mock(side_effect=error), stop, {})
                self.assertEqual(stop.delays, [])

    def test_unspecified_asr_event_recovers(self):
        detail = {'type': 'transcription_error', 'code': 'UNEXPECTED_ASR_ERROR'}
        for kind in ('error', 'conversation.item.input_audio_transcription.failed'):
            with self.subTest(kind=kind):
                ws = Mock()
                ws.recv_data.return_value = (websocket.ABNF.OPCODE_TEXT, json.dumps({'type': kind, 'error': detail}))
                session = Session(ws, '')
                session.receive()
                self.assertIsInstance(session.failure, UnspecifiedASRError)
                stop, report = FakeStop(), {}
                operation = Mock(side_effect=[session.failure, None])
                run_with_reconnect(operation, stop, report, clock=lambda: stop.now)
                self.assertEqual(operation.call_count, 2)
                self.assertEqual(report['asr_recovery_attempts'], 1)

    def test_unspecified_asr_budget_does_not_reset_after_long_attempt(self):
        stop, report = FakeStop(), {}
        def fail(_):
            stop.now += 31
            raise UnspecifiedASRError('no details')
        operation = Mock(side_effect=fail)
        with self.assertRaisesRegex(ServiceError, '两次'):
            run_with_reconnect(operation, stop, report, clock=lambda: stop.now)
        self.assertEqual(operation.call_count, 3)
        self.assertEqual(report['asr_recovery_attempts'], 2)
        self.assertEqual(len(stop.delays), 2)

    def test_unspecified_asr_requires_exact_diagnostic_shape(self):
        for detail in (
            {'code': 'UNEXPECTED_ASR_ERROR'},
            {'type': 'transcription_error', 'code': 'UNEXPECTED_ASR_ERROR', 'message': 'Unauthorized'},
            {'type': 'transcription_error', 'code': 'UNEXPECTED_ASR_ERROR', 'status': 401},
            {'type': 'transcription_error', 'code': 'invalid_api_key'},
        ):
            with self.subTest(detail=detail):
                self.assertIsInstance(service_error(detail), ServiceError)

    def test_other_asr_failures_are_not_blindly_retried(self):
        for code, message in (
            ('UNEXPECTED_ASR_ERROR', 'grpc error: statusCode=401, message=Unauthorized'),
            ('UNEXPECTED_ASR_ERROR', 'unrecognized backend failure'),
            ('invalid_api_key', 'statusCode=504 Response stream timeout'),
        ):
            with self.subTest(code=code, message=message):
                self.assertIsInstance(service_error({'code': code, 'message': message}), ServiceError)

    def test_backoff_then_recovery(self):
        stop = FakeStop()
        report = {}
        calls = []
        def attempt(remaining):
            calls.append(remaining)
            if len(calls) <= 6:
                raise ConnectionLost('offline')
        run_with_reconnect(attempt, stop, report, clock=lambda: stop.now)
        self.assertEqual(stop.delays, [1, 2, 4, 8, 15, 15])
        self.assertEqual(report['reconnect_attempts'], 6)
        self.assertEqual(len(calls), 7)

    def test_deadline_includes_backoff(self):
        stop = FakeStop()
        operation = Mock(side_effect=ConnectionLost('offline'))
        run_with_reconnect(operation, stop, {}, seconds=2, clock=lambda: stop.now)
        self.assertEqual(stop.delays, [1, 1])
        self.assertEqual(operation.call_count, 2)

    def test_cancel_while_disconnected(self):
        stop = FakeStop()
        def attempt(_):
            stop.stopped = True
            raise ConnectionLost('offline')
        run_with_reconnect(attempt, stop, {}, clock=lambda: stop.now)
        self.assertEqual(stop.delays, [])

    def test_local_and_service_errors_do_not_retry(self):
        for error in (RuntimeError('Chrome exited'), ServiceError('bad key')):
            stop = FakeStop()
            with self.assertRaises(type(error)):
                run_with_reconnect(Mock(side_effect=error), stop, {}, clock=lambda: stop.now)
            self.assertEqual(stop.delays, [])

    def test_http_error_classification(self):
        for status in (401, 403, 404):
            self.assertIsInstance(network_error(websocket.WebSocketBadStatusException('bad', status_code=status)), ServiceError)
        for status in (429, 500, 503):
            self.assertIsInstance(network_error(websocket.WebSocketBadStatusException('bad', status_code=status)), ConnectionLost)

    def test_heartbeat_timeout(self):
        ws = Mock()
        session = Session(ws, '')
        session.heartbeat(now=100)
        ws.ping.assert_called_once()
        with self.assertRaises(ConnectionLost):
            session.heartbeat(now=115)
        session.last_pong = 116
        session.heartbeat(now=116)
        self.assertEqual(ws.ping.call_count, 2)

    def test_close_code_and_pong_are_read(self):
        ws = Mock()
        ws.recv_data.side_effect = [(websocket.ABNF.OPCODE_PONG, b'live-subtitle'),
                                   (websocket.ABNF.OPCODE_CLOSE, (1001).to_bytes(2, 'big') + b'going away')]
        session = Session(ws, '')
        session.receive()
        self.assertGreater(session.last_pong, 0)
        self.assertEqual(session.close_code, 1001)
        self.assertIsInstance(session.failure, ConnectionLost)


if __name__ == '__main__':
    unittest.main()
