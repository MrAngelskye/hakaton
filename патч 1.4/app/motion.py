"""Short, interruptible transitions. All effects are owned by their widgets."""
from PySide6.QtCore import QObject, Signal, QSettings, QEvent, QPropertyAnimation, QEasingCurve, Qt, QTimer, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QLabel, QGraphicsOpacityEffect, QWidget

PAGE_DURATION = 180
DIALOG_DURATION = 160


class BusyIndicator(QWidget):
    """Indeterminate feedback for actual asynchronous work, without polling effects.

    Hidden indicators and the reduced-motion setting stop the timer. The static
    arc and its adjacent text still communicate loading when animation is off.
    """
    def __init__(self, parent=None, color='#07316E'):
        super().__init__(parent)
        self.setFixedSize(20, 20)
        self.setAccessibleName('Загрузка')
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.color = QColor(color)
        self.running = False
        self.angle = 0
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.advance)
        preferences().changed.connect(self.sync)
        self.hide()

    def set_running(self, running):
        self.running = bool(running)
        self.setVisible(self.running)
        self.sync()

    def sync(self, *_):
        if self.running and self.isVisible() and not preferences().reduced:
            self.timer.start()
        else:
            self.timer.stop()
            self.angle = 0
        self.update()

    def advance(self):
        self.angle = (self.angle + 14) % 360
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self.sync()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QColor(self.color)
        track.setAlpha(40)
        bounds = QRectF(2, 2, 16, 16)
        painter.setPen(QPen(track, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawEllipse(bounds)
        painter.setPen(QPen(self.color, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(bounds, (90 - self.angle) * 16, -100 * 16)


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
