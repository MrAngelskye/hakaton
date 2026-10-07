"""Actual native control geometry and asynchronous feedback; no live services."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from PySide6.QtCore import QDate, QCoreApplication, QEvent, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QStyle,
                              QStyleOptionComboBox, QStyleOptionSpinBox, QTextEdit)
from app.theme import apply_theme, COLORS
from app.motion import BusyIndicator, preferences
from app.widgets import (NoWheelComboBox, NoWheelSpinBox, CalendarDialog, Sheet,
                         Toast, button, icon)
from app.voice_input import ReportVoiceInput
from app.ai_chat import AdminChatWidget


APP = QApplication.instance() or QApplication([])
# The Windows offscreen plugin has no system font discovery. Load a system
# font for the same text metrics used by the normal Windows application.
if not QFontDatabase.families():
    for font in ('segoeui.ttf', 'segoeuib.ttf', 'seguisb.ttf'):
        path = Path('C:/Windows/Fonts') / font
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
APP.setStyle('Fusion')
apply_theme(APP)


class Session:
    def __init__(self, path, **callbacks):
        self.callbacks = callbacks
    def start(self): return True
    def is_alive(self): return False
    def cancel(self): pass
    def stop(self): pass


class NativePolish(unittest.TestCase):
    def setUp(self):
        self.widgets = []
        self.temp = tempfile.TemporaryDirectory()
        preferences().settings = None
        preferences().set_reduced(False)

    def tearDown(self):
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        APP.processEvents()
        preferences().set_reduced(False)
        self.temp.cleanup()

    def show(self, widget):
        self.widgets.append(widget)
        widget.show()
        APP.processEvents()
        return widget

    def test_combo_arrow_centered_separate_from_text(self):
        combo = NoWheelComboBox()
        combo.addItems(['Дробильно-сортировочный участок', 'Ремонтная мастерская'])
        combo.resize(340, 46)
        self.show(combo)
        option = QStyleOptionComboBox()
        combo.initStyleOption(option)
        arrow = combo.style().subControlRect(QStyle.ComplexControl.CC_ComboBox,
            option, QStyle.SubControl.SC_ComboBoxArrow, combo)
        edit = combo.style().subControlRect(QStyle.ComplexControl.CC_ComboBox,
            option, QStyle.SubControl.SC_ComboBoxEditField, combo)
        self.assertTrue(combo.rect().contains(arrow))
        self.assertLess(edit.right(), arrow.left())
        self.assertLessEqual(abs(arrow.center().y() - combo.rect().center().y()), 1)
        self.assertGreaterEqual(arrow.width(), 30)

    def test_spin_hit_areas_are_separate_and_increment(self):
        spin = NoWheelSpinBox()
        spin.setRange(0, 100)
        spin.setValue(4)
        spin.resize(220, 46)
        self.show(spin)
        option = QStyleOptionSpinBox()
        spin.initStyleOption(option)
        rects = [spin.style().subControlRect(QStyle.ComplexControl.CC_SpinBox,
            option, part, spin) for part in (QStyle.SubControl.SC_SpinBoxUp,
                QStyle.SubControl.SC_SpinBoxDown, QStyle.SubControl.SC_SpinBoxEditField)]
        up, down, edit = rects
        self.assertFalse(up.intersects(down))
        self.assertTrue(spin.rect().contains(up))
        self.assertTrue(spin.rect().contains(down))
        self.assertLess(edit.right(), min(up.left(), down.left()))
        QTest.mouseClick(spin, Qt.MouseButton.LeftButton, pos=up.center())
        self.assertEqual(spin.value(), 5)
        QTest.mouseClick(spin, Qt.MouseButton.LeftButton, pos=down.center())
        self.assertEqual(spin.value(), 4)

    def test_icon_only_buttons_are_centered_and_calendar_moves(self):
        for name in ('chevron-left', 'chevron-right', 'chevron-down', 'chevron-up'):
            with self.subTest(name=name):
                control = button('', ico=name)
                control.setIcon(icon(name, '#A52337'))
                control.resize(72, 46)
                self.show(control)
                image = control.grab().toImage()
                points = [(x, y) for y in range(image.height()) for x in range(image.width())
                    if (c := image.pixelColor(x, y)).red() > 120 and c.green() < 80 and c.blue() < 110]
                self.assertTrue(points)
                center_x = (min(x for x, _ in points) + max(x for x, _ in points)) / 2
                center_y = (min(y for _, y in points) + max(y for _, y in points)) / 2
                self.assertLessEqual(abs(center_x - (control.width() - 1) / 2), 1.5)
                self.assertLessEqual(abs(center_y - (control.height() - 1) / 2), 1.5)
        dialog = self.show(CalendarDialog(QDate(2026, 10, 7)))
        QTest.mouseClick(dialog.previous_button, Qt.MouseButton.LeftButton)
        self.assertEqual(dialog.calendar.monthShown(), 9)
        QTest.mouseClick(dialog.next_button, Qt.MouseButton.LeftButton)
        self.assertEqual(dialog.calendar.monthShown(), 10)

    def test_spinner_stops_when_hidden_and_reduced_motion(self):
        parent = QWidget()
        layout = QVBoxLayout(parent)
        indicator = BusyIndicator(parent)
        layout.addWidget(indicator)
        self.show(parent)
        indicator.set_running(True)
        QTest.qWait(100)
        self.assertTrue(indicator.timer.isActive())
        self.assertNotEqual(indicator.angle, 0)
        parent.hide()
        self.assertFalse(indicator.timer.isActive())
        parent.show()
        APP.processEvents()
        self.assertTrue(indicator.timer.isActive())
        preferences().set_reduced(True)
        self.assertTrue(indicator.isVisible())
        self.assertFalse(indicator.timer.isActive())
        indicator.set_running(False)
        self.assertFalse(indicator.isVisible())

    def test_error_reveal_preserves_form_and_toast_is_bounded(self):
        parent = self.show(QWidget())
        parent.resize(460, 400)
        dialog = self.show(Sheet('Проверка', parent))
        text = QTextEdit()
        text.setPlainText('Данные не потеряны')
        dialog.field('Работы', text)
        dialog.fail('Нет связи. Повторите отправку.')
        self.assertEqual(text.toPlainText(), 'Данные не потеряны')
        self.assertIsNotNone(dialog.error_reveal.animation)
        preferences().set_reduced(True)
        self.assertIsNone(dialog.error_reveal.animation)
        toast = Toast(parent)
        toast.show_message('Ошибка подключения. ' * 30, error=True)
        APP.processEvents()
        self.assertEqual(toast.property('tone'), 'error')
        self.assertTrue(parent.rect().contains(toast.geometry()))
        self.assertEqual(toast.symbol.width(), toast.symbol.height())
        self.assertTrue(toast.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))

    def test_voice_busy_error_and_completion_keep_review_guard(self):
        field = QTextEdit()
        voice = ReportVoiceInput([('Работы', field)], session_factory=Session)
        voice.model_path = lambda: Path(self.temp.name)
        self.show(voice)
        voice.open(field, 'Работы')
        voice.start()
        APP.processEvents()
        self.assertTrue(voice.indicator.timer.isActive())
        voice._error(voice.token, 'Микрофон недоступен. Ручной ввод работает.')
        self.assertEqual(voice.status.property('tone'), 'error')
        voice._done(voice.token)
        self.assertFalse(voice.indicator.timer.isActive())
        self.assertTrue(field.isEnabled())
        voice.preview.setPlainText('Текст, который нужно проверить')
        self.assertTrue(voice.has_unapplied())
        self.assertEqual(field.toPlainText(), '')
        voice.dispose()

    def test_chat_poll_is_quiet_but_pending_reply_shows_progress(self):
        chat = AdminChatWidget(object())
        chat.timer.stop()
        chat.request = lambda *args, **kwargs: None
        self.show(chat)
        chat.state = {'ai_enabled': True, 'pending': False}
        chat._request = object()
        chat._operation = 'poll'
        chat.controls()
        self.assertFalse(chat.indicator.running)
        chat._operation = 'send'
        chat.controls()
        self.assertTrue(chat.indicator.running)
        self.assertTrue(chat.indicator.timer.isActive())
        chat._request = None
        chat.state['pending'] = True
        chat.controls()
        self.assertTrue(chat.indicator.running)
        chat.state['pending'] = False
        chat.controls()
        self.assertFalse(chat.indicator.running)
        self.assertFalse(chat.indicator.timer.isActive())

    def test_disabled_variants_visibly_distinguish_busy_actions(self):
        for kind in ('primary', 'secondary'):
            with self.subTest(kind=kind):
                action = button('Отправить', kind=kind)
                action.resize(180, 46)
                action.setEnabled(False)
                self.show(action)
                image = action.grab().toImage()
                self.assertEqual(image.pixelColor(20, action.height()//2).name().upper(), COLORS['surface_alt'])
                action.setEnabled(True)
                APP.processEvents()
                image = action.grab().toImage()
                self.assertNotEqual(image.pixelColor(20, action.height()//2).name().upper(), COLORS['surface_alt'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
