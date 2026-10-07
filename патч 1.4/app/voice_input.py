"""Optional, local report dictation. Reviewed text uses existing report fields/drafts."""
from pathlib import Path
from PySide6.QtCore import QObject, Signal, Qt, QSettings
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QFileDialog, QApplication
from app.widgets import label, button, row
from app.motion import BusyIndicator, Reveal
from app.speech import DictationSession, default_model_path


class _Bridge(QObject):
    status = Signal(int, str)
    partial = Signal(int, str)
    final = Signal(int, str)
    error = Signal(int, str)
    done = Signal(int)


class ReportVoiceInput(QWidget):
    def __init__(self, fields, parent=None, session_factory=DictationSession):
        super().__init__(parent)
        self.fields = fields
        self.session_factory = session_factory
        self.session = None
        self.target = None
        self.token = 0
        self.disposed = False
        self.busy = False
        self.baseline = ''
        self.settings = QSettings('NaryadAI', 'VoiceInput')
        self.bridge = _Bridge(self)
        self.bridge.status.connect(self._status)
        self.bridge.partial.connect(self._partial)
        self.bridge.final.connect(self._final)
        self.bridge.error.connect(self._error)
        self.bridge.done.connect(self._done)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.triggers = []
        triggers = row()
        for title, field in fields:
            trigger = button('Диктовать ' + title.lower(), lambda checked=False, f=field, t=title: self.open(f, t), 'secondary', 'mic')
            triggers.addWidget(trigger)
            self.triggers.append(trigger)
        layout.addLayout(triggers)
        self.panel = QWidget(self)
        self.panel.setObjectName('voicePanel')
        body = QVBoxLayout(self.panel)
        body.setContentsMargins(16, 16, 16, 16)
        body.setSpacing(12)
        self.heading = label('Голосовой ввод', 'section')
        self.note = label('Речь распознаётся локально на этом компьютере. Аудиозапись не сохраняется и не отправляется. Проверьте названия узлов, числа и результат перед добавлением.', 'muted', True)
        self.configure = button('Выбрать локальную модель', self.choose_model, 'secondary')
        self.status = label('', 'voiceStatus', True)
        self.status_reveal = Reveal(self.status)
        self.indicator = BusyIndicator(self.panel)
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        status_row.addWidget(self.indicator, 0, Qt.AlignmentFlag.AlignVCenter)
        status_row.addWidget(self.status, 1)
        self.partial = label('', 'muted', True)
        self.preview = QTextEdit()
        self.preview.setAcceptRichText(False)
        self.preview.setPlaceholderText('Распознанный текст: проверьте и исправьте, затем добавьте в отчёт.')
        self.preview.setMinimumHeight(110)
        self.start_button = button('Начать диктовку', self.start, 'secondary', 'mic')
        self.stop_button = button('Остановить', self.stop, 'secondary')
        self.apply_button = button('Добавить в отчёт', self.apply, 'primary')
        self.cancel_button = button('Отменить диктовку', self.cancel)
        for widget in (self.heading, self.note, self.configure):
            body.addWidget(widget)
        body.addLayout(status_row)
        body.addWidget(self.preview)
        body.addWidget(self.partial)
        body.addLayout(row(self.start_button, self.stop_button))
        body.addLayout(row(self.apply_button, self.cancel_button))
        layout.addWidget(self.panel)
        self.panel.hide()
        self.preview.textChanged.connect(self.render)
        self.app = QApplication.instance()
        if self.app:
            self.app.applicationStateChanged.connect(self._app_state)
        self.render()

    def feedback(self, text, error=False):
        self.status.setProperty('tone', 'error' if error else 'neutral')
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.status.setText(text)
        if error:
            self.status_reveal.start()

    def model_path(self):
        configured = self.settings.value('model_path', '')
        return Path(str(configured)) if configured else default_model_path()

    def open(self, field, title):
        if self.disposed or self.busy:
            return
        if self.target is not field and self.preview.toPlainText().strip():
            self.feedback('Добавьте текущий текст или отмените диктовку перед выбором другого поля.', True)
            return
        self.target = field
        self.heading.setText('Диктовка: ' + title.lower())
        self.panel.show()
        self.feedback('Нажмите «Начать диктовку». Для первой настройки запустите install_voice.bat.' if not self.model_path().is_dir() else 'Нажмите «Начать диктовку». После остановки проверьте текст.')
        self.render()

    def choose_model(self):
        path = QFileDialog.getExistingDirectory(self, 'Выберите распакованную русскую модель Vosk', str(self.model_path().parent))
        if path:
            model = Path(path)
            if not (model / 'am' / 'final.mdl').is_file() or not (model / 'conf' / 'mfcc.conf').is_file():
                self.feedback('Выберите папку распакованной модели: в ней должны быть am/final.mdl и conf/mfcc.conf.', True)
                return
            self.settings.setValue('model_path', str(model))
            self.feedback('Локальная модель выбрана. Можно начать диктовку.')

    def _emit(self, signal, token, *args):
        if self.disposed or token != self.token:
            return
        try:
            signal.emit(token, *args)
        except RuntimeError:
            pass  # Dialog was destroyed while the local model finished loading.

    def start(self):
        if self.disposed or self.busy or self.target is None or not self.target.isEnabled():
            return
        if self.session and self.session.is_alive():
            self.feedback('Предыдущая диктовка завершается. Повторите через секунду.', True)
            return
        if not self.model_path().is_dir():
            self.feedback('Русская модель не установлена. Запустите install_voice.bat или выберите уже распакованную модель. Ручной ввод доступен.', True)
            return
        self.token += 1
        token = self.token
        self.baseline = self.preview.toPlainText().strip()
        self.busy = True
        self.feedback('Подготавливаем локальное распознавание…')
        self.render()
        try:
            self.session = self.session_factory(
                self.model_path(),
                on_status=lambda text: self._emit(self.bridge.status, token, text),
                on_partial=lambda text: self._emit(self.bridge.partial, token, text),
                on_final=lambda text: self._emit(self.bridge.final, token, text),
                on_error=lambda text: self._emit(self.bridge.error, token, text),
                on_done=lambda: self._emit(self.bridge.done, token),
            )
            if not self.session.start():
                self.busy = False
                self.feedback('Диктовка уже запущена. Остановите предыдущую запись.', True)
                self.render()
        except Exception:
            self.busy = False
            self.feedback('Не удалось запустить голосовой ввод. Проверьте установку install_voice.bat; ручной ввод доступен.', True)
            self.render()

    def _status(self, token, text):
        if token == self.token and not self.disposed:
            self.feedback(text)

    def _partial(self, token, text):
        if token == self.token and not self.disposed:
            self.partial.setText('Предварительно: ' + text if text else '')

    def _final(self, token, text):
        if token == self.token and not self.disposed:
            self.preview.setPlainText('\n'.join(value for value in (self.baseline, text.strip()) if value))
            self.feedback('Проверьте текст и нажмите «Добавить в отчёт».' if text.strip() else 'Речь не распознана. Попробуйте снова или используйте ручной ввод.')

    def _error(self, token, text):
        if token == self.token and not self.disposed:
            self.feedback(text, True)

    def _done(self, token):
        if token == self.token and not self.disposed:
            self.busy = False
            self.partial.clear()
            self.render()

    def stop(self):
        if self.session and self.busy:
            self.stop_button.setEnabled(False)
            self.feedback('Завершаем распознавание…')
            self.session.stop()

    def _app_state(self, state):
        if state != Qt.ApplicationState.ApplicationActive:
            self.stop()

    def has_unapplied(self):
        return self.busy or bool(self.preview.toPlainText().strip())

    def apply(self):
        if self.busy or self.disposed or self.target is None or not self.target.isEnabled():
            return
        text = self.preview.toPlainText().strip()
        if not text:
            return
        previous = self.target.toPlainText()
        combined = previous + ('\n' if previous and not previous[-1].isspace() else '') + text
        if len(combined) > 10000:
            self.feedback('Предел поля — 10 000 символов. Сократите текст; ничего не добавлено.', True)
            return
        self.target.setPlainText(combined)  # Existing textChanged persists the report draft.
        self.preview.clear()
        self.feedback('Текст добавлен. Проверьте отчёт и отправьте его мастеру отдельно.')
        self.target.setFocus()
        self.render()

    def cancel(self):
        self.token += 1
        if self.session:
            self.session.cancel()
        self.busy = False
        self.baseline = ''
        self.preview.clear()
        self.partial.clear()
        self.panel.hide()
        self.render()

    def render(self):
        self.indicator.set_running(self.busy and not self.disposed)
        for trigger in self.triggers:
            trigger.setEnabled(not self.busy and not self.disposed)
        self.preview.setReadOnly(self.busy)
        self.configure.setEnabled(not self.busy)
        self.start_button.setEnabled(not self.busy and self.target is not None)
        self.stop_button.setEnabled(self.busy)
        self.apply_button.setEnabled(not self.busy and bool(self.preview.toPlainText().strip()))

    def dispose(self, *_):
        if self.disposed:
            return
        self.cancel()
        self.disposed = True
        if self.app:
            try:
                self.app.applicationStateChanged.disconnect(self._app_state)
            except (RuntimeError, TypeError):
                pass
