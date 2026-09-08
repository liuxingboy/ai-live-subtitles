from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QTextLayout, QTextOption
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QSizeGrip, QMenu, QApplication


class Overlay(QWidget):
    stop_requested = Signal()
    settings_changed = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle('实时双语字幕')
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(420)
        self._drag = None
        self._texts = ('', '')
        self.running = True
        self.stopping = False
        self.locked = False
        self.lock_available = False
        self.shortcut_prefix = 'Ctrl+Alt'
        self.setStyleSheet('QLabel { color: #171b20; background: transparent; } QPushButton { color: #252a31; background: rgba(219, 225, 232, 190); border: none; border-radius: 5px; padding: 4px 10px; } QPushButton:hover { background: #cbd4de; }')
        self.content_layout = QVBoxLayout(self)
        self.content_layout.setContentsMargins(16, 10, 36, 10)
        self.content_layout.setSpacing(6)
        self.status = QLabel('正在启动…')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setStyleSheet('color: #59616d; font-size: 12px;')
        self.status.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.content_layout.addWidget(self.status)
        self.close_button = QPushButton('×', self)
        self.close_button.setToolTip('退出字幕')
        self.close_button.setAccessibleName('退出字幕')
        self.close_button.setFixedSize(22, 22)
        self.close_button.setStyleSheet('QPushButton { color: #606773; background: transparent; border: none; padding: 0; font-size: 18px; } QPushButton:hover { color: #222; background: #d9dfe5; border-radius: 4px; }')
        self.close_button.clicked.connect(self.close)
        self.source = QLabel()
        self.translation = QLabel()
        for label, pixels in ((self.source, 18), (self.translation, 24)):
            font = label.font()
            font.setFamily('Microsoft YaHei UI')
            font.setPixelSize(pixels)
            label.setFont(font)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self.content_layout.addWidget(label)
        self.grip = QSizeGrip(self)
        self.grip.setFixedSize(14, 14)
        screen = self.screen().availableGeometry()
        self.resize(max(420, int(screen.width() * .55)), 90)
        self.move(screen.left() + (screen.width() - self.width()) // 2,
                  screen.bottom() - self.height() - int(screen.height() * .12))
        self.show_subtitles('', '')

    def _wrap(self, text, font):
        # Bound both rendering work and height for long ASR paragraphs.
        text = text[-1600:].replace('\n', ' ')
        layout = QTextLayout(text, font)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        layout.beginLayout()
        lines = []
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(max(100, self.width() - 56))
            lines.append(text[line.textStart():line.textStart() + line.textLength()])
        layout.endLayout()
        return ('…' if len(lines) > 3 else '') + '\n'.join(lines[-3:])

    def show_subtitles(self, source, translation):
        self._texts = (source, translation)
        self.source.setText(self._wrap(source or '等待原文…', self.source.font()))
        self.translation.setText(self._wrap(translation or '等待翻译…', self.translation.font()))
        for label in (self.source, self.translation):
            label.setFixedHeight(label.fontMetrics().lineSpacing() * max(1, len(label.text().splitlines())) + 2)
        self._fit_height()

    def set_status(self, state, message):
        colors = {'connected': '#18734c', 'connecting': '#845810', 'reconnecting': '#845810', 'error': '#b32632', 'stopped': '#59616d'}
        self.status.setStyleSheet(f'font-size: 12px; color: {colors.get(state, "#59616d")};')
        self.status.setText(message[:85])
        self.status.setVisible(state != 'connected')
        self.status.setToolTip(message)
        self._fit_height()

    def _fit_height(self):
        # Content-sized height prevents layout stretch from creating large gaps.
        visible_status = not self.status.isHidden()
        height = 20 + self.source.height() + self.translation.height() + 6
        if visible_status:
            height += self.status.sizeHint().height() + 6
        self.setFixedHeight(height)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 200))
        painter.drawRoundedRect(self.rect(), 12, 12)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'grip'):
            self.close_button.move(self.width() - 28, 4)
            self.grip.move(self.width() - 16, self.height() - 16)
            if event.size().width() != event.oldSize().width():
                self.show_subtitles(*self._texts)
                self.settings_changed.emit()

    def moveEvent(self, event):
        super().moveEvent(event)
        self.settings_changed.emit()

    def preferences(self):
        return dict(x=self.x(), y=self.y(), width=self.width(),
                    source_font=self.source.font().pixelSize(), translation_font=self.translation.font().pixelSize())

    def restore_preferences(self, values):
        for label, key, default in ((self.source, 'source_font', 18), (self.translation, 'translation_font', 24)):
            font = label.font()
            font.setPixelSize(max(12, min(48, values.get(key, default))))
            label.setFont(font)
        x, y = values.get('x', self.x()), values.get('y', self.y())
        screens = [s.availableGeometry() for s in QApplication.screens()]
        screen = next((s for s in screens if s.contains(x, y)), self.screen().availableGeometry())
        self.resize(max(420, min(screen.width(), values.get('width', self.width()))), self.height())
        self.show_subtitles(*self._texts)
        self.move(max(screen.left(), min(x, screen.right() - self.width() + 1)),
                  max(screen.top(), min(y, screen.bottom() - self.height() + 1)))

    def change_font(self, step):
        for label in (self.source, self.translation):
            font = label.font()
            font.setPixelSize(max(12, min(48, font.pixelSize() + step)))
            label.setFont(font)
        self.show_subtitles(*self._texts)
        self.settings_changed.emit()

    def toggle_lock(self):
        if not self.lock_available or self.stopping:
            return
        from ui.hotkeys import click_through
        try:
            click_through(int(self.winId()), not self.locked)
        except OSError as exc:
            print(f'[ERROR] 无法切换点击穿透：{exc}', flush=True)
            return
        self.locked = not self.locked
        self._drag = None
        self.close_button.setVisible(not self.locked)
        self.grip.setVisible(not self.locked)
        print(f'[INFO] 已锁定并点击穿透，{self.shortcut_prefix}+L 解锁。' if self.locked else '[INFO] 已解锁。', flush=True)

    def contextMenuEvent(self, event):
        if self.locked:
            return
        menu = QMenu(self)
        lock = menu.addAction(f'锁定并点击穿透  {self.shortcut_prefix}+L', self.toggle_lock)
        lock.setEnabled(self.lock_available)
        menu.addAction(f'放大字号  {self.shortcut_prefix}+=', lambda: self.change_font(2))
        menu.addAction(f'缩小字号  {self.shortcut_prefix}+-', lambda: self.change_font(-2))
        menu.addSeparator()
        menu.addAction(f'退出  {self.shortcut_prefix}+Q', self.close)
        menu.exec(event.globalPos())

    def mousePressEvent(self, event):
        if not self.locked and event.button() == Qt.MouseButton.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if not self.locked and self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, event):
        self._drag = None

    def closeEvent(self, event):
        if self.running:
            event.ignore()
            if not self.stopping:
                self.stopping = True
                self.close_button.setEnabled(False)
                self.set_status('stopped', '正在结束会话，请稍候…')
                self.stop_requested.emit()
        else:
            event.accept()
