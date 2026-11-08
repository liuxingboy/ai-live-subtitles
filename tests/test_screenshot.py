import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import ctypes
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from app.screenshot_translation import (
    DEFAULT_SHORTCUTS, MAX_CONTEXT, normalize_shortcut, read_context, read_shortcuts,
    request_body, request_error, response_text, save_context, save_shortcuts,
    screenshot_connection, validate_shortcuts,
)
from ui.screenshot import ContextDialog, RegionSelector, TranslationPopup, crop_selection
from ui.tray import SubtitleTray


def response(original='Hello', translation='你好', **choice):
    return json.dumps({'choices': [{'message': {'content': json.dumps({
        'original': original, 'translation': translation})}, **choice}]}).encode()


class ScreenshotProtocolTests(unittest.TestCase):
    def test_shortcut_validation_and_settings_preserve_each_other(self):
        self.assertEqual(normalize_shortcut('alt+ctrl+f1'), 'Ctrl+Alt+F1')
        self.assertEqual(normalize_shortcut('Ctrl+Meta+K'), 'Ctrl+Win+K')
        for text in ('F1', 'Shift+A', 'Ctrl+Ctrl+F1', 'Ctrl+F25', 'Ctrl+F1, Ctrl+F2', ''):
            with self.subTest(text=text), self.assertRaises(ValueError):
                normalize_shortcut(text)
        with self.assertRaises(ValueError):
            validate_shortcuts({'region': 'Ctrl+F1', 'full': 'Ctrl+F1'})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            self.assertEqual(read_shortcuts(path), DEFAULT_SHORTCUTS)
            save_context('游戏背景', path)
            shortcuts = {'region': 'Ctrl+Shift+A', 'full': 'Alt+F10'}
            save_shortcuts(shortcuts, path)
            self.assertEqual(read_context(path), '游戏背景')
            save_context('新的背景', path)
            self.assertEqual(read_shortcuts(path), shortcuts)
            path.write_text('{"shortcuts": null}', encoding='utf-8')
            self.assertEqual(read_shortcuts(path), DEFAULT_SHORTCUTS)

    def test_reuses_key_workspace_and_host_override(self):
        env = {'DASHSCOPE_API_KEY': 'test', 'DASHSCOPE_WORKSPACE_ID': 'workspace'}
        key, url = screenshot_connection(env)
        self.assertEqual(key, 'test')
        self.assertEqual(url, 'https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions')
        env['DASHSCOPE_WS_HOST'] = 'custom.cn-beijing.maas.aliyuncs.com'
        self.assertIn('https://custom.', screenshot_connection(env)[1])
        with self.assertRaises(ValueError):
            screenshot_connection({})

    def test_payload_uses_current_image_context_language_without_history(self):
        body = request_body(b'png-image', '最终幻想7 重制版', 'ja')
        self.assertEqual(body['model'], 'qwen3.7-flash')
        self.assertFalse(body['enable_thinking'])
        self.assertEqual(len(body['messages']), 2)
        self.assertIn('日语', body['messages'][0]['content'])
        content = body['messages'][1]['content']
        self.assertIn('最终幻想7', content[0]['text'])
        self.assertTrue(content[1]['image_url']['url'].startswith('data:image/png;base64,'))
        with self.assertRaises(ValueError):
            request_body(b'png', 'a' * (MAX_CONTEXT + 1))

    def test_context_roundtrip_and_corrupt_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'prefs.json'
            self.assertEqual(read_context(path), '')
            save_context('这是游戏文本', path)
            self.assertEqual(read_context(path), '这是游戏文本')
            with self.assertRaises(ValueError):
                save_context('a' * (MAX_CONTEXT + 1), path)
            self.assertEqual(read_context(path), '这是游戏文本')
            for value in ('[]', '{bad', '{"context":3}'):
                path.write_text(value, encoding='utf-8')
                self.assertEqual(read_context(path), '')

    def test_response_validation_and_no_text(self):
        self.assertEqual(response_text(response()), ('Hello', '你好'))
        self.assertEqual(response_text(response('', '')), ('', ''))
        for raw in (b'{}', b'bad', b'{"choices":[null]}', b'\xff', response(original=[]), response(translation=''),
                    response(finish_reason='length'), response(finish_reason='content_filter')):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                response_text(raw)

    def test_error_does_not_echo_server_credentials(self):
        raw = json.dumps({'error': {'code': 'invalid_api_key', 'message': 'secret sk-sensitive'}})
        self.assertIn('权限', request_error(403, raw))
        self.assertNotIn('secret', request_error(403, raw))
        self.assertIn('内容审核', request_error(400, '{"error":{"code":"data_inspection_failed"}}'))
        self.assertIn('频繁', request_error(429, b'bad'))


class ScreenshotUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_high_dpi_selection_clips_and_preserves_pixels(self):
        pixmap = QPixmap(800, 400)
        pixmap.fill(QColor('red'))
        pixmap.setDevicePixelRatio(2)
        image = crop_selection(pixmap, QRect(10, 20, 100, 60), QSize(400, 200))
        self.assertEqual(image.size(), QSize(200, 120))
        self.assertEqual(image.pixelColor(0, 0), QColor('red'))
        image = crop_selection(pixmap, QRect(-10, -10, 40, 40), QSize(400, 200))
        self.assertEqual(image.size(), QSize(60, 60))
        self.assertIsNone(crop_selection(pixmap, QRect(0, 0, 1, 1), QSize(400, 200)))

    def test_selector_drag_and_escape(self):
        pixmap = QPixmap(800, 400)
        pixmap.fill(QColor('white'))
        selector = RegionSelector(QRect(0, 0, 400, 200), pixmap)
        selected, cancelled = Mock(), Mock()
        selector.selected.connect(selected)
        selector.cancelled.connect(cancelled)
        selector.show()
        QTest.mousePress(selector, Qt.MouseButton.LeftButton, pos=QPoint(30, 40))
        QTest.mouseMove(selector, QPoint(130, 100))
        QTest.mouseRelease(selector, Qt.MouseButton.LeftButton, pos=QPoint(130, 100))
        selected.assert_called_once()
        self.assertEqual(selected.call_args.args[0].size(), QSize(202, 122))
        QTest.keyClick(selector, Qt.Key.Key_Escape)
        cancelled.assert_called_once()
        selector.close()
        selector.deleteLater()

    def test_popup_is_transparent_plain_text_and_independently_closable(self):
        popup = TranslationPopup()
        dismissed = Mock()
        popup.dismissed.connect(dismissed)
        popup.pending('中文')
        self.assertFalse(popup.copy_translation.isEnabled())
        popup.show_result('<b>Hello</b>', '你好')
        self.assertEqual(popup.original.toPlainText(), '<b>Hello</b>')
        self.assertTrue(popup.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        popup.copy_translation.click()
        self.assertEqual(self.app.clipboard().text(), '你好')
        popup.close()
        dismissed.assert_called_once()
        popup.deleteLater()

    def test_context_editor_and_tray_actions(self):
        dialog = ContextDialog('游戏文本')
        save = dialog.buttons.button(QDialogButtonBox.StandardButton.Save)
        self.assertTrue(save.isEnabled())
        dialog.editor.setPlainText('a' * (MAX_CONTEXT + 1))
        self.assertFalse(save.isEnabled())
        dialog.close()
        dialog.deleteLater()
        tray = SubtitleTray(QIcon())
        actions = [Mock(), Mock(), Mock()]
        for signal, action in zip((tray.screenshot_region_requested, tray.screenshot_full_requested,
                                   tray.screenshot_context_requested), actions):
            signal.connect(action)
        tray.screenshot_region_action.trigger()
        tray.screenshot_full_action.trigger()
        tray.screenshot_context_action.trigger()
        for action in actions:
            action.assert_called_once()
        tray.shutdown()

    def test_capture_cancel_restores_window_and_sends_nothing(self):
        from app.screenshot_controller import ScreenshotController
        from ui.overlay import Overlay
        window, tray = Overlay(), SubtitleTray(QIcon())
        window.running = False
        window.show()
        with patch('app.screenshot_controller.read_context', return_value=''):
            controller = ScreenshotController(self.app, tray, window, lambda: 'zh')
        try:
            with patch.object(controller.network, 'post') as post:
                controller.begin('region')
                self.assertFalse(window.isVisible())
                controller.finish_capture()
                self.assertTrue(window.isVisible())
                self.assertFalse(controller.capture_timer.isActive())
                post.assert_not_called()
        finally:
            controller.shutdown()
            window.close()
            tray.shutdown()

    def test_request_completion_and_cancellation_ignore_late_results(self):
        from app.screenshot_controller import ScreenshotController
        from ui.overlay import Overlay
        window, tray = Overlay(), SubtitleTray(QIcon())
        window.running = False
        with patch('app.screenshot_controller.read_context', return_value=''):
            controller = ScreenshotController(self.app, tray, window, lambda: 'zh')
        try:
            reply = Mock()
            reply.readAll.return_value = response()
            reply.attribute.return_value = 200
            reply.error.return_value = QNetworkReply.NetworkError.NoError
            controller.reply = reply
            controller.completed(reply)
            self.assertEqual(controller.popup.translation.toPlainText(), '你好')
            controller.reply = reply
            controller.cancel_request()
            reply.abort.assert_called_once()
            reply.readAll.reset_mock()
            controller.completed(reply)
            reply.readAll.assert_not_called()
            self.assertIsNone(controller.reply)
        finally:
            controller.shutdown()
            window.close()
            tray.shutdown()

    def test_full_capture_posts_once_and_timeout_cancels(self):
        from app.screenshot_controller import ScreenshotController
        from ui.overlay import Overlay
        window, tray = Overlay(), SubtitleTray(QIcon())
        window.running = False
        with patch('app.screenshot_controller.read_context', return_value='游戏背景'):
            controller = ScreenshotController(self.app, tray, window, lambda: 'ja')
        try:
            pixmap = QPixmap(800, 400)
            pixmap.fill(QColor('white'))
            screen = Mock()
            screen.geometry.return_value = QRect(0, 0, 800, 400)
            screen.grabWindow.return_value = pixmap
            reply = Mock()
            with patch('app.screenshot_controller.screenshot_connection', return_value=('test-key', 'https://example.com/chat/completions')), \
                    patch.object(controller.network, 'post', return_value=reply) as post:
                controller.mode, controller.screen, controller.capturing = 'full', screen, True
                controller.capture()
                post.assert_called_once()
                body = json.loads(post.call_args.args[1])
                self.assertIn('日语', body['messages'][0]['content'])
                self.assertIn('游戏背景', body['messages'][1]['content'][0]['text'])
                request = post.call_args.args[0]
                self.assertEqual(bytes(request.rawHeader('Authorization')), b'Bearer test-key')
                self.assertEqual(request.attribute(QNetworkRequest.Attribute.RedirectPolicyAttribute),
                                 QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
                controller.begin('region')
                post.assert_called_once()
                controller.timeout()
                reply.abort.assert_called_once()
                self.assertIsNone(controller.reply)
                self.assertIn('45 秒', controller.popup.status.text())
        finally:
            controller.shutdown()
            window.close()
            tray.shutdown()

    def test_shortcut_conflict_and_unregister(self):
        from ui.hotkeys import ScreenshotHotkey, W
        actions = {'region': Mock(), 'full': Mock()}
        with patch('ui.hotkeys.user32.RegisterHotKey', side_effect=[0, 1]), \
                patch('ui.hotkeys.user32.UnregisterHotKey'):
            hotkey = ScreenshotHotkey(self.app, actions, DEFAULT_SHORTCUTS)
            self.assertIn('region', hotkey.errors)
            self.assertNotIn('full', hotkey.errors)
            self.assertIn(hotkey.ID + 1, hotkey.actions)
            hotkey.close()
        with patch('ui.hotkeys.user32.RegisterHotKey', return_value=1) as register, \
                patch('ui.hotkeys.user32.UnregisterHotKey') as unregister:
            hotkey = ScreenshotHotkey(self.app, actions, DEFAULT_SHORTCUTS)
            self.assertEqual(register.call_count, 2)
            self.assertEqual(register.call_args_list[0].args, (None, hotkey.ID, 0x4003, 0x70))
            self.assertEqual(register.call_args_list[1].args, (None, hotkey.ID + 1, 0x4003, 0x71))
            message = W.MSG()
            message.message, message.wParam = 0x312, hotkey.ID
            self.assertEqual(hotkey.nativeEventFilter(None, ctypes.addressof(message)), (True, 0))
            actions['region'].assert_called_once()
            message.wParam = hotkey.ID + 1
            hotkey.nativeEventFilter(None, ctypes.addressof(message))
            actions['full'].assert_called_once()
            hotkey.close()
            hotkey.close()
            self.assertEqual(unregister.call_count, 2)

    def test_shortcut_edit_conflict_save_failure_cancel_and_success(self):
        from app.screenshot_controller import ScreenshotController
        from ui.overlay import Overlay
        from PySide6.QtGui import QKeySequence
        window, tray = Overlay(), SubtitleTray(QIcon())
        window.running = False
        controller = ScreenshotController(self.app, tray, window, lambda: 'zh')
        old = controller.shortcuts.copy()
        new = {'region': 'Ctrl+Shift+F3', 'full': 'Ctrl+Shift+F4'}
        try:
            controller.edit_shortcuts()
            dialog = controller.shortcut_dialog
            with patch.object(controller, 'begin') as begin:
                dialog.editors['region'].setKeySequence(QKeySequence(new['region']))
                begin.assert_not_called()
            # Simulate native registration conflicts even on the offscreen test backend.
            candidate = Mock(errors={'full': 'Ctrl+Shift+F4 被占用'})
            with patch.object(self.app, 'platformName', return_value='windows'), \
                    patch.object(controller, 'create_shortcuts', return_value=candidate), \
                    patch('app.screenshot_controller.save_shortcuts') as save:
                controller.store_shortcuts(new)
                candidate.close.assert_called_once()
                save.assert_not_called()
                self.assertEqual(controller.shortcuts, old)
                self.assertIn('占用', dialog.note.text())
            with patch('app.screenshot_controller.save_shortcuts', side_effect=OSError('denied')):
                controller.store_shortcuts(new)
                self.assertEqual(controller.shortcuts, old)
                self.assertIn('保存失败', dialog.note.text())
            with patch.object(controller, 'register_shortcuts') as register:
                dialog.reject()
                register.assert_called_once()
            self.assertIsNone(controller.shortcut_dialog)
            controller.edit_shortcuts()
            with patch('app.screenshot_controller.save_shortcuts') as save:
                controller.store_shortcuts(new)
                save.assert_called_once_with(new)
            self.assertEqual(controller.shortcuts, new)
            self.assertIsNone(controller.shortcut_dialog)
            self.assertIn(new['full'], tray.screenshot_full_action.text())
        finally:
            controller.shutdown()
            window.close()
            tray.shutdown()
