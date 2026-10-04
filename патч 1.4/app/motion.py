"""Short, interruptible transitions. All effects are owned by their widgets."""
from PySide6.QtCore import QObject, Signal, QSettings, QEvent, QPropertyAnimation, QEasingCurve, Qt
from PySide6.QtWidgets import QApplication, QLabel, QGraphicsOpacityEffect

PAGE_DURATION = 180
DIALOG_DURATION = 160


class MotionPreferences(QObject):
    changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.reduced = False
        self.settings = None

    def configure(self, path):
        self.settings = QSettings(str(path), QSettings.Format.IniFormat)
        self.set_reduced(self.settings.value('accessibility/reduced_motion', False, type=bool))

    def set_reduced(self, reduced):
        reduced = bool(reduced)
        if self.settings:
            self.settings.setValue('accessibility/reduced_motion', reduced)
            self.settings.sync()
        if self.reduced != reduced:
            self.reduced = reduced
            self.changed.emit(reduced)


def preferences():
    app = QApplication.instance()
    if not hasattr(app, '_motion_preferences'):
        app._motion_preferences = MotionPreferences(app)
    return app._motion_preferences


class PageTransition(QObject):
    """Fade the old viewport over the new page without blocking mouse or keyboard."""
    def __init__(self, viewport):
        super().__init__(viewport)
        self.viewport = viewport
        self.overlay = None
        self.animation = None
        viewport.installEventFilter(self)
        preferences().changed.connect(self.clear)

    def capture(self):
        self.clear()
        if not preferences().reduced and self.viewport.isVisible():
            return self.viewport.grab()
        return None

    def start(self, snapshot):
        self.clear()
        if snapshot is None or snapshot.isNull() or preferences().reduced:
            return
        self.overlay = QLabel(self.viewport)
        self.overlay.setObjectName('pageTransition')
        self.overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.overlay.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.overlay.setPixmap(snapshot)
        self.overlay.setGeometry(self.viewport.rect())
        effect = QGraphicsOpacityEffect(self.overlay)
        self.overlay.setGraphicsEffect(effect)
        self.animation = QPropertyAnimation(effect, b'opacity', self)
        self.animation.setDuration(PAGE_DURATION)
        self.animation.setStartValue(1.0)
        self.animation.setEndValue(0.0)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(self.clear)
        self.overlay.show()
        self.overlay.raise_()
        self.animation.start()

    def clear(self, *_):
        if self.animation:
            self.animation.stop()
            self.animation.deleteLater()
            self.animation = None
        if self.overlay:
            self.overlay.hide()
            self.overlay.deleteLater()
            self.overlay = None

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Hide):
            self.clear()
        return False


class Reveal(QObject):
    def __init__(self, widget):
        super().__init__(widget)
        self.widget = widget
        self.animation = None
        self.effect = None
        widget.installEventFilter(self)
        preferences().changed.connect(self.finish)

    def start(self):
        self.finish()
        if preferences().reduced:
            return
        self.effect = QGraphicsOpacityEffect(self.widget)
        self.widget.setGraphicsEffect(self.effect)
        self.animation = QPropertyAnimation(self.effect, b'opacity', self)
        self.animation.setDuration(DIALOG_DURATION)
        self.animation.setStartValue(0.65)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(self.finish)
        self.animation.start()

    def finish(self, *_):
        if self.animation:
            self.animation.stop()
            self.animation.deleteLater()
            self.animation = None
        if self.effect:
            self.widget.setGraphicsEffect(None)
            self.effect = None

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Hide:
            self.finish()
        return False
