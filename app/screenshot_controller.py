"""Qt-owned screenshot lifecycle and cancellable asynchronous HTTP requests."""
import json

from PySide6.QtCore import QBuffer, QIODevice, QObject, QTimer, QUrl, Qt
from PySide6.QtGui import QCursor
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QApplication

from app.preferences import TARGET_LANGUAGES
from app.screenshot_translation import (
    read_context, read_shortcuts, request_body, request_error, response_text, save_context,
    save_shortcuts, screenshot_connection,
)
from ui.screenshot import ContextDialog, RegionSelector, ScreenshotShortcutDialog, TranslationPopup


class ScreenshotController(QObject):
    def __init__(self, app, tray, subtitle_window, language):
        super().__init__(app)
        self.app, self.tray, self.subtitle_window = app, tray, subtitle_window
        self.language = language
        self.context = read_context()
        self.popup = TranslationPopup()
        self.popup.dismissed.connect(self.cancel_request)
        self.dialog = None
        self.shortcut_dialog = None
        self.shortcuts = read_shortcuts()
        self.selectors = []
        self.hidden = []
        self.capturing = False
        self.closed = False
        self.reply = None
        self.network = QNetworkAccessManager(self)
        self.capture_timer = QTimer(self)
        self.capture_timer.setSingleShot(True)
        self.capture_timer.timeout.connect(self.capture)
        self.request_timer = QTimer(self)
        self.request_timer.setSingleShot(True)
        self.request_timer.timeout.connect(self.timeout)
        self.shortcut = None
        tray.screenshot_region_requested.connect(lambda: self.begin('region'))
        tray.screenshot_full_requested.connect(lambda: self.begin('full'))
        tray.screenshot_context_requested.connect(self.edit_context)
        tray.screenshot_shortcuts_requested.connect(self.edit_shortcuts)
        self.register_shortcuts()
        subtitle_window.stop_requested.connect(self.shutdown)
        app.aboutToQuit.connect(self.shutdown)

    def begin(self, mode):
        if self.closed or self.subtitle_window.stopping or self.capturing or self.shortcut_dialog is not None:
            return
        if self.reply is not None:
            self.popup.show()
            self.popup.raise_()
            return
        self.mode = mode
        self.screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        self.capturing = True
        self.tray.menu.hide()
        self.hidden = [window for window in (self.subtitle_window, self.popup, self.dialog)
                       if window is not None and window.isVisible() and not window.isMinimized()]
        for window in self.hidden:
            window.hide()
        # Let the compositor remove our windows and the tray menu before capturing.
        self.capture_timer.start(220)

    def capture(self):
        if self.closed:
            return
        if self.subtitle_window.stopping:
            self.finish_capture()
            return
        try:
            screens = [self.screen] if self.mode == 'full' else QApplication.screens()
            snapshots = [(screen.geometry(), screen.grabWindow(0)) for screen in screens]
            if not snapshots or any(pixmap.isNull() for _, pixmap in snapshots):
                raise ValueError('无法读取屏幕，请退出独占全屏模式后重试。')
            if self.mode == 'full':
                self.selected(snapshots[0][1].toImage())
                return
            for geometry, pixmap in snapshots:
                selector = RegionSelector(geometry, pixmap)
                selector.selected.connect(self.selected)
                selector.cancelled.connect(self.finish_capture)
                self.selectors.append(selector)
                selector.show()
                selector.raise_()
            for selector in self.selectors:
                if selector.geometry().contains(QCursor.pos()):
                    selector.activateWindow()
                    selector.setFocus()
        except (RuntimeError, ValueError):
            self.finish_capture()
            self.show_error('无法读取屏幕，请退出独占全屏模式或检查显示器后重试。')

    def finish_capture(self):
        self.capture_timer.stop()
        for selector in self.selectors:
            selector.hide()
            selector.deleteLater()
        self.selectors.clear()
        self.capturing = False
        for window in self.hidden:
            if not self.closed:
                window.show()
        self.hidden.clear()

    def selected(self, image):
        if not self.capturing or self.closed:
            return
        self.finish_capture()
        try:
            key, url = screenshot_connection()
            language = self.language()
            # Preserve text legibility while bounding upload size for very large desktops.
            if max(image.width(), image.height()) > 2560:
                image = image.scaled(2560, 2560, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            if not image.save(buffer, 'PNG'):
                raise ValueError('截图编码失败，请重试。')
            body = request_body(bytes(buffer.data()), self.context, language)
            request = QNetworkRequest(QUrl(url))
            request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, 'application/json')
            request.setRawHeader(b'Authorization', ('Bearer ' + key).encode('utf-8'))
            # Do not forward the credential to a redirected endpoint.
            request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                                 QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
            request.setTransferTimeout(45000)
            self.popup.pending(TARGET_LANGUAGES[language])
            self.show_popup()
            reply = self.network.post(request, json.dumps(body, ensure_ascii=False).encode('utf-8'))
            self.reply = reply
            reply.finished.connect(lambda: self.completed(reply))
            self.request_timer.start(45000)
        except ValueError as exc:
            self.show_error(str(exc))

    def show_popup(self):
        if not self.popup.isVisible():
            screen = getattr(self, 'screen', None)
            if screen not in QApplication.screens():
                screen = QApplication.primaryScreen()
            if screen:
                bounds = screen.availableGeometry()
                self.popup.resize(min(680, bounds.width()), min(450, bounds.height()))
                self.popup.move(bounds.center() - self.popup.rect().center())
        self.popup.show()
        self.popup.raise_()
        self.popup.activateWindow()

    def show_error(self, message):
        self.popup.pending('错误')
        self.popup.status.setText(message)
        self.show_popup()

    def completed(self, reply):
        if reply is not self.reply:
            reply.deleteLater()
            return
        self.reply = None
        self.request_timer.stop()
        raw = bytes(reply.readAll())
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if status and status != 200:
            self.popup.status.setText(request_error(status, raw))
        elif reply.error() != QNetworkReply.NetworkError.NoError:
            self.popup.status.setText('网络连接失败或超时，请检查网络后重新截图。')
        else:
            try:
                self.popup.show_result(*response_text(raw))
            except ValueError as exc:
                self.popup.status.setText(str(exc))
        reply.deleteLater()

    def cancel_request(self):
        self.request_timer.stop()
        reply, self.reply = self.reply, None
        if reply is not None:
            reply.abort()
            reply.deleteLater()

    def timeout(self):
        self.cancel_request()
        self.popup.status.setText('翻译等待超过 45 秒，已停止等待。请稍后重新截图。')

    def edit_context(self):
        if self.closed or self.capturing:
            return
        if self.dialog is not None:
            self.dialog.show()
            self.dialog.raise_()
            self.dialog.activateWindow()
            return
        self.dialog = ContextDialog(self.context)
        self.dialog.accepted.connect(self.store_context)
        self.dialog.finished.connect(self.context_closed)
        self.dialog.show()

    def store_context(self):
        context = self.dialog.editor.toPlainText()
        try:
            save_context(context)
        except (OSError, ValueError):
            self.tray.showMessage('背景说明未保存', '保存失败，原设置保留。请检查项目目录写入权限。',
                                  self.tray.MessageIcon.Warning)
        else:
            self.context = context

    def context_closed(self):
        self.dialog.deleteLater()
        self.dialog = None

    def create_shortcuts(self, values):
        from ui.hotkeys import ScreenshotHotkey
        return ScreenshotHotkey(self.app, {'region': lambda: self.begin('region'),
                                          'full': lambda: self.begin('full')}, values)

    def register_shortcuts(self):
        errors = {}
        if self.app.platformName() == 'windows':
            self.shortcut = self.create_shortcuts(self.shortcuts)
            errors = self.shortcut.errors
            if errors:
                self.tray.showMessage('截图快捷键不可用', '\n'.join(errors.values()) +
                                      '\n可从托盘“截图翻译 → 设置截图快捷键”修改。',
                                      self.tray.MessageIcon.Warning)
        self.tray.set_screenshot_shortcuts(self.shortcuts, errors)

    def edit_shortcuts(self):
        if self.closed or self.capturing:
            return
        if self.shortcut_dialog is not None:
            self.shortcut_dialog.raise_()
            self.shortcut_dialog.activateWindow()
            return
        if self.shortcut is not None:
            self.shortcut.close()
            self.shortcut = None
        self.shortcut_dialog = ScreenshotShortcutDialog(self.shortcuts)
        self.shortcut_dialog.apply_requested.connect(self.store_shortcuts)
        self.shortcut_dialog.finished.connect(self.shortcuts_closed)
        self.shortcut_dialog.show()

    def store_shortcuts(self, values):
        candidate = None
        if self.app.platformName() == 'windows':
            candidate = self.create_shortcuts(values)
            if candidate.errors:
                self.shortcut_dialog.note.setText('\n'.join(candidate.errors.values()) + '\n请更换组合键。')
                candidate.close()
                return
        try:
            save_shortcuts(values)
        except (OSError, ValueError):
            if candidate is not None:
                candidate.close()
            self.shortcut_dialog.note.setText('保存失败，原设置保留。请检查项目目录写入权限。')
            return
        self.shortcuts = values
        self.shortcut = candidate
        self.tray.set_screenshot_shortcuts(values, {})
        self.shortcut_dialog.accept()

    def shortcuts_closed(self):
        self.shortcut_dialog.deleteLater()
        self.shortcut_dialog = None
        if not self.closed and self.shortcut is None:
            self.register_shortcuts()

    def shutdown(self):
        if self.closed:
            return
        self.closed = True
        self.finish_capture()
        self.cancel_request()
        if self.dialog is not None:
            self.dialog.close()
        if self.shortcut_dialog is not None:
            self.shortcut_dialog.close()
        self.popup.close()
        self.popup.deleteLater()
        if self.shortcut is not None:
            self.shortcut.close()
