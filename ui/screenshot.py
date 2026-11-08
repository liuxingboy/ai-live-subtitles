"""Screen selection and a transparent, independently closable translation window."""
from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QSizeGrip, QSlider, QVBoxLayout, QWidget, QKeySequenceEdit,
)
from app.screenshot_translation import DEFAULT_SHORTCUTS, MAX_CONTEXT, validate_shortcuts


def crop_selection(pixmap, rect, logical_size):
    """Map logical Qt coordinates to physical pixels, including mixed DPI monitors."""
    rect = rect.normalized().intersected(QRect(QPoint(), logical_size))
    if rect.width() < 3 or rect.height() < 3:
        return None
    sx, sy = pixmap.width() / logical_size.width(), pixmap.height() / logical_size.height()
    left, top = round(rect.x() * sx), round(rect.y() * sy)
    right, bottom = round((rect.x() + rect.width()) * sx), round((rect.y() + rect.height()) * sy)
    return pixmap.copy(left, top, right - left, bottom - top).toImage()


class RegionSelector(QWidget):
    selected = Signal(object)
    cancelled = Signal()

    def __init__(self, geometry, pixmap):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.pixmap = pixmap
        self.start = None
        self.end = None
        self.setGeometry(geometry)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.pixmap)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))
        if self.start is not None:
            selected = QRect(self.start, self.end).normalized().intersected(self.rect())
            painter.save()
            painter.setClipRect(selected)
            painter.drawPixmap(self.rect(), self.pixmap)
            painter.restore()
            painter.setPen(QPen(QColor('#67ddff'), 2))
            painter.drawRect(selected)
        painter.setPen(Qt.GlobalColor.white)
        font = painter.font()
        font.setPixelSize(18)
        painter.setFont(font)
        painter.fillRect(QRect(18, 18, 480, 44), QColor(0, 0, 0, 200))
        painter.drawText(QRect(30, 18, 460, 44), Qt.AlignmentFlag.AlignVCenter,
                         '拖拽框选文字 · 松开翻译 · Esc / 右键取消')

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.cancelled.emit()
        elif event.button() == Qt.MouseButton.LeftButton:
            self.start = self.end = event.position().toPoint()
            self.update()

    def mouseMoveEvent(self, event):
        if self.start is not None:
            self.end = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.start is not None:
            self.end = event.position().toPoint()
            image = crop_selection(self.pixmap, QRect(self.start, self.end), self.size())
            if image is None or image.isNull():
                self.start = self.end = None
                self.update()
            else:
                self.selected.emit(image)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
        else:
            super().keyPressEvent(event)


class TranslationPopup(QWidget):
    dismissed = Signal()

    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle('截图翻译')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(680, 450)
        self.setMinimumSize(380, 260)
        self._drag = None
        self.background_alpha = 100
        self.setStyleSheet('QLabel { color: white; background: transparent; } '
                           'QPlainTextEdit { color: white; background: transparent; border: none; '
                           'font-family: "Microsoft YaHei UI"; font-size: 17px; } '
                           'QPushButton { color: white; background: rgba(255,255,255,35); '
                           'border: none; border-radius: 5px; padding: 5px 10px; } '
                           'QPushButton:hover { background: rgba(255,255,255,70); }')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        header = QHBoxLayout()
        self.title = QLabel('截图翻译')
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        header.addWidget(self.title)
        header.addStretch()
        self.close_button = QPushButton('×')
        self.close_button.setToolTip('关闭 / 取消等待（Esc）')
        self.close_button.clicked.connect(self.close)
        header.addWidget(self.close_button)
        layout.addLayout(header)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addWidget(QLabel('原文'))
        self.original = QPlainTextEdit()
        self.original.setReadOnly(True)
        layout.addWidget(self.original, 1)
        layout.addWidget(QLabel('译文'))
        self.translation = QPlainTextEdit()
        self.translation.setReadOnly(True)
        layout.addWidget(self.translation, 2)
        footer = QHBoxLayout()
        self.copy_original = QPushButton('复制原文')
        self.copy_translation = QPushButton('复制译文')
        self.copy_original.clicked.connect(lambda: QApplication.clipboard().setText(self.original.toPlainText()))
        self.copy_translation.clicked.connect(lambda: QApplication.clipboard().setText(self.translation.toPlainText()))
        footer.addWidget(self.copy_original)
        footer.addWidget(self.copy_translation)
        footer.addStretch()
        footer.addWidget(QLabel('背景浓度'))
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0, 220)
        self.opacity.setValue(self.background_alpha)
        self.opacity.setFixedWidth(95)
        self.opacity.valueChanged.connect(self.set_background)
        footer.addWidget(self.opacity)
        footer.addWidget(QSizeGrip(self))
        layout.addLayout(footer)

    def set_background(self, value):
        self.background_alpha = value
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(255, 255, 255, 90), 1))
        painter.setBrush(QColor(15, 22, 34, self.background_alpha))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 12, 12)

    def pending(self, language):
        self.title.setText(f'截图翻译 → {language}')
        self.original.clear()
        self.translation.clear()
        self.copy_original.setEnabled(False)
        self.copy_translation.setEnabled(False)
        self.status.setText('正在识别并翻译… 关闭窗口可取消等待')

    def show_result(self, original, translation):
        self.original.setPlainText(original)
        self.translation.setPlainText(translation)
        self.copy_original.setEnabled(bool(original))
        self.copy_translation.setEnabled(bool(translation))
        self.status.setText('翻译完成' if original else '截图中未识别到可读文字，请框选文字区域重试。')

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, event):
        self._drag = None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.dismissed.emit()
        super().closeEvent(event)


class ContextDialog(QDialog):
    def __init__(self, context):
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle('截图翻译 · 背景说明')
        self.resize(540, 290)
        layout = QVBoxLayout(self)
        label = QLabel('说明游戏、人物或专业领域，帮助模型选择正确译法。\n'
                       '说明会随截图发送给百炼；不填写时使用通用翻译。')
        label.setWordWrap(True)
        layout.addWidget(label)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText('例如：这是游戏《最终幻想7 重制版》中的文本。')
        self.editor.setPlainText(context)
        layout.addWidget(self.editor)
        self.note = QLabel()
        layout.addWidget(self.note)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                                       QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存')
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.editor.textChanged.connect(self.validate)
        self.validate()

    def validate(self):
        length = len(self.editor.toPlainText())
        self.note.setText(f'{length} / {MAX_CONTEXT} 字')
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(length <= MAX_CONTEXT)


class ScreenshotShortcutDialog(QDialog):
    apply_requested = Signal(dict)

    def __init__(self, shortcuts):
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle('截图翻译 · 全局快捷键')
        self.resize(480, 260)
        layout = QVBoxLayout(self)
        label = QLabel('点击输入框后按下组合键。保存后立即生效，重启后保留。\n'
                       '编辑期间暂停截图快捷键；请使用 Ctrl 或 Alt 加字母、数字或 F1–F24。')
        label.setWordWrap(True)
        layout.addWidget(label)
        self.editors = {}
        for mode, title in (('region', '框选截图'), ('full', '全屏截图')):
            row = QHBoxLayout()
            row.addWidget(QLabel(title))
            editor = QKeySequenceEdit()
            editor.setMaximumSequenceLength(1)
            editor.setKeySequence(QKeySequence(shortcuts[mode].replace('Win', 'Meta')))
            row.addWidget(editor)
            layout.addLayout(row)
            self.editors[mode] = editor
        self.note = QLabel()
        self.note.setTextFormat(Qt.TextFormat.PlainText)
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        reset = QPushButton('恢复默认：Ctrl+Alt+F1 / F2')
        reset.clicked.connect(self.reset_defaults)
        layout.addWidget(reset)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.submit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def reset_defaults(self):
        for mode, shortcut in DEFAULT_SHORTCUTS.items():
            self.editors[mode].setKeySequence(QKeySequence(shortcut))
        self.note.clear()

    def submit(self):
        try:
            values = validate_shortcuts({mode: editor.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
                                         for mode, editor in self.editors.items()})
        except ValueError as exc:
            self.note.setText(str(exc))
            return
        self.apply_requested.emit(values)
