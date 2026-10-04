"""Чат администратора. Сетевые операции выполняются вне потока интерфейса."""
import html,json,threading,uuid
from urllib.parse import quote
from PySide6.QtCore import QObject,Signal,QTimer,Qt
from PySide6.QtGui import QKeySequence,QShortcut
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QTextBrowser,QPlainTextEdit,QLabel
from app.widgets import button,label,card


class ChatRequest(QObject):
    ready=Signal(dict);failed=Signal(str);finished=Signal()
    def __init__(self,store,path,payload,parent):
        super().__init__(parent);self.store=store;self.path=path;self.payload=payload
    def start(self):threading.Thread(target=self.run,daemon=True,name='admin-chat').start()
    def run(self):
        try:
            response=self.store.request(self.path,self.payload)
            self.ready.emit(response)
        except (ValueError,OSError,PermissionError) as e:
            try:self.failed.emit(str(e))
            except RuntimeError:pass
        except RuntimeError:pass
        finally:
            try:self.finished.emit()
            except RuntimeError:pass


class AdminChatWidget(QWidget):
    def __init__(self,store,parent=None):
        super().__init__(parent);self.store=store;self.cid='';self._request=None
        self.state=None;self._signature='';self._retry=None;self._new_id=None
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(16)
        box,body=card();top=QHBoxLayout()
        top.addWidget(label('Помощник администратора','title'));top.addStretch()
        self.new_button=button('Новый чат',self.new_chat,'secondary','plus');top.addWidget(self.new_button);body.addLayout(top)
        self.status=label('Подключаемся к чату…','muted',True);body.addWidget(self.status)
        self.history=QTextBrowser();self.history.setObjectName('aiChatHistory');self.history.setMinimumHeight(340)
        self.history.setOpenExternalLinks(False);self.history.setOpenLinks(False);body.addWidget(self.history)
        self.error=label('','muted',True);self.error.hide();body.addWidget(self.error)
        self.editor=QPlainTextEdit();self.editor.setObjectName('aiChatMessage');self.editor.setPlaceholderText('Напишите вопрос… Например: помоги составить понятный отчёт о работе.')
        self.editor.setFixedHeight(105);body.addWidget(self.editor)
        controls=QHBoxLayout();controls.addWidget(label('Ctrl + Enter — отправить · до 4000 символов','muted'));controls.addStretch()
        self.send_button=button('Отправить',self.send,'primary','spark');controls.addWidget(self.send_button);body.addLayout(controls)
        layout.addWidget(box)
        layout.addWidget(label('ИИ видит сообщения этого чата. Для обсуждения наряда вставьте нужный текст. Решения и окончательную оценку принимает человек.','muted',True))
        self.shortcut=QShortcut(QKeySequence('Ctrl+Return'),self);self.shortcut.activated.connect(self.send)
        self.timer=QTimer(self);self.timer.setInterval(3000);self.timer.timeout.connect(self.poll);self.timer.start()
        self.editor.textChanged.connect(self.controls)
        self.controls();QTimer.singleShot(0,self,self.poll)

    def request(self,path,payload=None,operation='poll'):
        if self._request:return
        self._operation=operation
        loader=ChatRequest(self.store,path,payload,self);self._request=loader
        loader.ready.connect(self.received);loader.failed.connect(self.failed)
        loader.finished.connect(self.finished);loader.finished.connect(loader.deleteLater)
        self.controls();loader.start()

    def poll(self):
        if not self.isVisible() or self._request:return
        path='/api/chat'+('?conversation_id='+quote(self.cid,safe='') if self.cid else '')
        self.request(path)

    def received(self,state):
        self.state=state;self.cid=state['conversation_id'];self.error.hide()
        if self._retry and any(r['id']==self._retry['request_id'] for r in state['messages']):
            if self.editor.toPlainText().strip()==self._retry['message']:self.editor.clear()
            self._retry=None
        if self._operation=='new':self._new_id=None;self.editor.clear();self._retry=None
        if not state['ai_enabled']:self.status.setText('ИИ отключён на сервере. Для подключения установите AI_ENABLED=true на Render.')
        elif not state['online']:self.status.setText('ПК с ИИ не подключён. Запустите AnythingLLM, Ollama и start_worker.bat на компьютере с моделью.')
        elif state['pending']:self.status.setText('ИИ готовит ответ. При первом запуске модели это может занять несколько минут.')
        else:self.status.setText('ИИ подключён · можно отправить сообщение')
        signature=json.dumps(state['messages'],ensure_ascii=False)
        if signature!=self._signature:
            self._signature=signature;bar=self.history.verticalScrollBar();at_bottom=bar.maximum()-bar.value()<35;old=bar.value()
            blocks=[]
            for turn in state['messages']:
                blocks.append('<p><b>Вы</b></p><p>'+self.text(turn['message'])+'</p>')
                if turn['status']=='completed':blocks.append('<p><b>ИИ · '+html.escape(turn['model'])+'</b></p><p>'+self.text(turn['answer'])+'</p><hr>')
                elif turn['status']=='failed':blocks.append('<p><b>Не удалось получить ответ</b></p><p>'+self.text(turn['error'])+'</p><hr>')
                else:blocks.append('<p><i>'+('Ожидает обработки…' if turn['status']=='queued' else 'ИИ отвечает…')+'</i></p><hr>')
            self.history.setHtml(''.join(blocks) or '<p>Здесь появится ваш разговор с ИИ.</p>')
            bar.setValue(bar.maximum() if at_bottom else old)
        self.controls()

    @staticmethod
    def text(value):return html.escape(value).replace('\n','<br>')

    def failed(self,message):self.error.setText(message);self.error.show()
    def finished(self):self._request=None;self.controls()

    def controls(self):
        busy=bool(self._request);text=self.editor.toPlainText().strip()
        enabled=bool(self.state and self.state['ai_enabled'])
        pending=bool(self.state and self.state['pending'])
        self.send_button.setEnabled(not busy and enabled and not pending and 0<len(text)<=4000)
        self.send_button.setText('Повторить отправку' if self._retry else 'Отправить')
        self.new_button.setEnabled(not busy and bool(self.state) and not pending)

    def send(self):
        if not self.send_button.isEnabled():return
        message=self.editor.toPlainText().strip()
        if not self._retry or self._retry['message']!=message:
            self._retry={'conversation_id':self.cid,'request_id':uuid.uuid4().hex,'message':message}
        self.request('/api/chat',self._retry,'send')

    def new_chat(self):
        if not self.new_button.isEnabled():return
        self._new_id=self._new_id or uuid.uuid4().hex
        self.request('/api/chat/new',{'request_id':self._new_id},'new')
