import math
import threading
from datetime import date,datetime
from PySide6.QtCore import Qt,QDate,QTimer,Signal,QObject
from PySide6.QtGui import QPainter,QColor,QPen
from PySide6.QtWidgets import (QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFrame,
    QScrollArea,QLineEdit,QButtonGroup,QLabel,QDateEdit,QProgressBar,QSizePolicy,
    QFileDialog,QMessageBox,QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,QCheckBox,QTextEdit,QApplication)
from app.widgets import label,button,brand,card,row,avatar,tag,CardGrid,Sheet,DatePicker,motion_toggle,Toast
from app.theme import COLORS
from app.motion import PageTransition
from app.store import ROLES,STATUS,EMPLOYEE_STATUS
from app.case_store import PRIORITIES
from app.dialogs import CreateTask,TaskDetails,ReviewReport,AddUser,EditShift,combo
from app.integrations import INTEGRATION_AREAS


def fmt_time(n):return f'{int(n)%24:02d}:{int(round(n%1*60)):02d}'+(' (+1 день)' if n>=24 else '')
def tone(status):return {'approved':'success','revision':'urgent','paused':'warning','inProgress':'info','planned':'purple','submitted':'info','aiPending':'purple'}.get(status,'neutral')
def score_text(n):return '—' if n is None else f'{n:.1f}'


class SnapshotLoader(QObject):
    ready=Signal(dict);failed=Signal(str);finished=Signal()
    def __init__(self,store,day,parent):super().__init__(parent);self.store=store;self.day=day;self.running=False
    def isRunning(self):return self.running
    def start(self):
        self.running=True;threading.Thread(target=self.run,daemon=True,name='client-refresh').start()
    def run(self):
        from urllib.parse import quote
        try:
            snapshot=self.store.request('/api/snapshot?day='+quote(self.day,safe=''));self.ready.emit(snapshot)
        except (OSError,ValueError,PermissionError) as e:
            try:self.failed.emit(str(e))
            except RuntimeError:pass
        except RuntimeError:pass  # Окно закрыто во время запроса.
        finally:
            self.running=False
            try:self.finished.emit()
            except RuntimeError:pass


class LoginWindow(QMainWindow):
    logged_in=Signal(dict)
    def __init__(self,store):
        super().__init__();self.store=store;self.setWindowTitle('НарядAI · Вход');self.resize(1140,800);self.setMinimumSize(930,740)
        host=QWidget();layout=QHBoxLayout(host);layout.setContentsMargins(36,36,36,36);layout.setSpacing(56)
        story,l=card('story',36);story.setMinimumWidth(450);l.addWidget(brand());l.addWidget(label('Костанайские минералы','title'));l.addStretch()
        l.addWidget(label('Костанайские минералы · Производственная смена','',True))
        l.addWidget(label('Ваша смена.\nВсё по плану.','heading',True))
        l.addWidget(label('Выбирайте задачи, планируйте время\nи делитесь результатами работы.','muted',True))
        steps,s=card('storySteps',22);s.addWidget(label('Рабочий день под контролем','title'))
        for i,(title,sub) in enumerate([('Выбрать наряд на участке','Карьер, дробление, обогащение и ремонт'),
                                       ('Выполнить и отправить отчёт','Работы, время, материалы и фото'),
                                       ('Получить обратную связь','Комментарий и оценка мастера')],1):
            s.addWidget(label(f'{i:02d}  {title}','',True));s.addWidget(label(sub,'muted',True))
        l.addWidget(steps);l.addStretch();l.addWidget(label('Общий сервер · проверка мастером' if getattr(store,'is_remote',False) else 'Демонстрационная версия · ручная проверка','muted'))
        layout.addWidget(story,1)
        form=QWidget();f=QVBoxLayout(form);f.setSpacing(14);f.setContentsMargins(0,8,0,8)
        f.addStretch();f.addWidget(label('Добро пожаловать','heading'));f.addWidget(label('Войдите в свою рабочую смену','muted'))
        f.addSpacing(10);f.addWidget(label('Выберите роль','title'))
        self.roles=QButtonGroup(self);self.roles.setExclusive(True)
        for i,(role,title,sub) in enumerate([('worker','Сотрудник','Задачи, график и результаты'),('master','Мастер','Наряды, отчёты и команда'),('admin','Администратор','Пользователи и настройки'),('manager','Руководитель','Отчёты и рейтинг')]):
            b=button(title+'\n'+sub,kind='role',ico={'worker':'user','master':'tool','admin':'shield','manager':'chart'}[role]);b.setCheckable(True)
            self.roles.addButton(b,i);b.clicked.connect(lambda checked=False,r=role:self.choose_role(r));f.addWidget(b)
        self.roles.button(0).setChecked(True);self.role='worker'
        f.addWidget(label('Логин'));self.username=QLineEdit('worker1');self.username.setObjectName('username');self.username.setPlaceholderText('worker1');f.addWidget(self.username)
        f.addWidget(label('Пароль'));self.password=QLineEdit('' if getattr(store,'is_remote',False) else '1234');self.password.setObjectName('password');self.password.setEchoMode(QLineEdit.EchoMode.Password);f.addWidget(self.password)
        self.error=label('','error',True);self.error.hide();f.addWidget(self.error)
        self.enter=button('Войти',self.login,'primary');self.enter.setObjectName('primary');self.enter.setDefault(True);f.addWidget(self.enter)
        self.password.returnPressed.connect(self.login);self.username.returnPressed.connect(self.login)
        f.addWidget(label('Тестовые аккаунты: master, worker1–worker15, admin, manager.\n'+('Пароль выдаёт администратор сервера.' if getattr(store,'is_remote',False) else 'Пароль для всех: 1234.'),'muted',True));f.addWidget(motion_toggle());f.addStretch()
        layout.addWidget(form,1);self.setCentralWidget(host)
    def choose_role(self,role):
        self.role=role;self.username.setText({'worker':'worker1','master':'master','admin':'admin','manager':'manager'}[role]);self.error.hide()
    def login(self):
        try:self.logged_in.emit(self.store.authenticate(self.username.text(),self.password.text(),self.role))
        except (ValueError,PermissionError,OSError) as e:self.error.setText(str(e));self.error.show()


class Timeline(QWidget):
    def __init__(self,tasks,open_task,shift=None):
        super().__init__();self.first=math.floor(shift['start']) if shift else 8
        self.last=math.ceil(shift['end']) if shift else 18
        self.setMinimumHeight((self.last-self.first)*80+50);self.events=[]
        for t in tasks:
            if t['start'] is None:continue
            b=button('',lambda tid=t['id']:open_task(tid),'timeline')
            b.setProperty('tone',tone(t['status']))
            b.setParent(self);b.setToolTip(fmt_time(t['start'])+'–'+fmt_time(t['start']+t['duration'])+' · '+STATUS[t['status']]+'\n'+t['title'])
            self.events.append((t,b))
    def resizeEvent(self,e):
        for t,b in self.events:
            b.setGeometry(62,int((t['start']-self.first)*80+4),max(100,self.width()-76),max(25,int(t['duration']*80-8)))
            time=fmt_time(t['start'])+'–'+fmt_time(t['start']+t['duration'])
            text=time+' · '+t['title'] if t['duration']<1 else t['title']
            text=b.fontMetrics().elidedText(text,Qt.TextElideMode.ElideRight,max(20,b.width()-32))
            b.setText(text if t['duration']<1 else time+' · '+STATUS[t['status']]+'\n'+text)
        super().resizeEvent(e)
    def paintEvent(self,e):
        p=QPainter(self);p.setPen(QPen(QColor(COLORS['border'])))
        for i in range(self.last-self.first+1):
            y=i*80+2;p.drawLine(60,y,self.width()-12,y);p.setPen(QColor(COLORS['muted']));p.drawText(0,y+15,f'{i+self.first:02d}:00');p.setPen(QColor(COLORS['border']))
        p.end()


class MainWindow(QMainWindow):
    logged_out=Signal()
    def __init__(self,store,user):
        super().__init__();self.store=store;self.user=user;self.setWindowTitle('НарядAI · Костанайские минералы');self.resize(1360,900);self.setMinimumSize(1040,760)
        self.page_key='overview' if user['role']!='worker' else 'tasks'
        self.task_filter='mine' if user['role']=='worker' else 'all';self.report_filter='submitted';self.query='';self.priority='all';self.schedule_day=QDate.currentDate()
        host=QWidget();outer=QHBoxLayout(host);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0)
        sidebar,self.side=card('sidebar',18);self.side.setSpacing(8)
        self.side.addWidget(brand());self.side.addSpacing(16);self.side.addWidget(label('Костанайские минералы','title'));self.side.addWidget(label('Производственная смена','muted'));self.side.addSpacing(22)
        self.side.addWidget(label(ROLES[user['role']].upper(),'muted'));self.side.addSpacing(6)
        self.nav={}
        items=[('overview','grid','Смена'),('tasks','tasks','Наряды'),('reports','report','Отчёты'),('team','team','Команда'),('team_schedule','calendar','График команды'),('costs','chart','Материалы'),('analytics','chart','Сводка за период')]
        if user['role']=='worker':items=[('tasks','tasks','Задачи'),('schedule','calendar','График'),('reports','report','Отчёты'),('profile','user','Профиль')]
        elif user['role']=='admin':items += [('ai_chat','spark','Чат с ИИ'),('users','shield','Пользователи'),('integrations','spark','Подключения')]
        elif user['role'] in ('master','manager'):items += [('ai_chat','spark','Чат с аналитикой')]
        if user['role'] in ('master','admin'):items += [('references','tasks','Справочники')]
        if user['role']!='worker':items += [('equipment','tasks','Оборудование')]
        for key,ico,title in items:
            b=button(title,lambda k=key:self.navigate(k),'nav',ico);b.setCheckable(True);self.nav[key]=b;self.side.addWidget(b)
        if user['role'] in ('master','admin'):
            self.create_button=button('Создать наряд',self.create_task,'primary','plus');self.side.addWidget(self.create_button)
        self.side.addStretch();self.side.addWidget(label('Поддержка и полный доступ' if user['role']=='admin' else 'Демонстрационная версия','muted',True))
        account=row(avatar(user['name']),label(user['name'].split()[0]+'\n'+ROLES[user['role']],'muted'));self.side.addLayout(account)
        self.side.addWidget(motion_toggle());self.side.addWidget(button('Выйти',self.logged_out.emit,'nav','logout'))
        sidebar_scroll=QScrollArea();sidebar_scroll.setObjectName('sidebarScroll');sidebar_scroll.setFixedWidth(246)
        sidebar_scroll.setWidgetResizable(True);sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sidebar_scroll.setWidget(sidebar);outer.addWidget(sidebar_scroll)
        content=QWidget();c=QVBoxLayout(content);c.setContentsMargins(0,0,0,0);c.setSpacing(0)
        top=QFrame();top.setObjectName('topbar');top.setFixedHeight(86);tl=QHBoxLayout(top);tl.setContentsMargins(34,0,34,0)
        tl.addWidget(label('Костанайские минералы  ·  Производственная смена','muted'));tl.addStretch();tl.addWidget(tag(ROLES[user['role']]))
        self.bell=button('Уведомления',self.notifications,ico='bell');tl.addWidget(self.bell);tl.addWidget(avatar(user['name']))
        c.addWidget(top);self.scroll=QScrollArea();self.scroll.setWidgetResizable(True);c.addWidget(self.scroll,1)
        outer.addWidget(content,1);self.setCentralWidget(host)
        self.transition=PageTransition(self.scroll.viewport());self.toast=Toast(self)
        self.search_timer=QTimer(self);self.search_timer.setSingleShot(True);self.search_timer.setInterval(180);self.search_timer.timeout.connect(self.filter_cards)
        self.refresh_timer=QTimer(self);self.refresh_timer.setInterval(3000 if getattr(store,'is_remote',False) else 5000);self.refresh_timer.timeout.connect(self.refresh_if_idle);self.refresh_timer.start()
        self._snapshot_loader=None;self.refresh_signature='';self.tasks=[];self.reports=[]
        from app.desktop_notifications import DesktopNotifications
        self.desktop_notifications=DesktopNotifications(self,store,user)
        self.desktop_notifications.activated.connect(self.open_notification)
        self.desktop_notifications.delivered.connect(lambda text:self.statusBar().showMessage(text,10000))
        self.desktop_notifications.delivered.connect(lambda text:self.toast.show_message(text[:220]) if self.isVisible() else None)
        self.render()
    def refresh_if_idle(self):
        from PySide6.QtWidgets import QApplication
        if getattr(self.store,'is_remote',False):
            if self._snapshot_loader and self._snapshot_loader.isRunning():return
            loader=SnapshotLoader(self.store,self.schedule_day.toString('yyyy-MM-dd'),self)
            self._snapshot_loader=loader;loader.ready.connect(self.remote_snapshot);loader.failed.connect(lambda msg:self.statusBar().showMessage(msg,5000))
            loader.finished.connect(self.network_finished);loader.finished.connect(loader.deleteLater);loader.start();return
        try:
            self.store.notification_tick()
            self.deliver_notifications(self.store.notifications(self.user))
        except (ValueError,OSError,PermissionError) as e:self.statusBar().showMessage(str(e),5000)
        if QApplication.activeModalWidget():return
        if self.page_key not in ('users','ai_chat'):
            old_signature=self.refresh_signature
            try:self.load()
            except PermissionError:
                self.render();return
            if self.refresh_signature!=old_signature:
                scroll_value=self.scroll.verticalScrollBar().value()
                self.render(animate=False)
                QTimer.singleShot(0,self.scroll,lambda:self.scroll.verticalScrollBar().setValue(scroll_value))
    def navigate(self,key):
        if key not in self.nav:return
        self.page_key=key;self.query='';self.render()
    def network_finished(self):
        if self.sender() is self._snapshot_loader:self._snapshot_loader=None
    def remote_snapshot(self,snapshot):
        from PySide6.QtWidgets import QApplication
        self.deliver_notifications(snapshot.get('notifications',[]))
        if snapshot['day']!=self.schedule_day.toString('yyyy-MM-dd'):return
        old=self.refresh_signature;self.store._snapshot=snapshot
        if QApplication.activeModalWidget():return
        self.load(refresh_remote=False)
        self.statusBar().showMessage('Подключено к '+self.store.url,4000)
        if self.refresh_signature==old:return
        if self.page_key=='ai_chat':return
        if self.page_key=='tasks' and hasattr(self,'search'):self.filter_cards();return
        scroll_value=self.scroll.verticalScrollBar().value();self.render(refresh_remote=False,animate=False)
        QTimer.singleShot(0,self.scroll,lambda:self.scroll.verticalScrollBar().setValue(scroll_value))
    def load(self,refresh_remote=True):
        if getattr(self.store,'is_remote',False) and refresh_remote:self.store.refresh_snapshot(self.schedule_day.toString('yyyy-MM-dd'))
        self.tasks=self.store.tasks(self.user);self.reports=self.store.reports(self.user)
        people=self.store.users(self.user,True) if self.user['role']!='worker' else [self.user]
        shifts=[self.store.shift(self.user,p['id'],self.schedule_day.toString('yyyy-MM-dd')) for p in people]
        inbox=self.store.snapshot().get('notifications',[]) if getattr(self.store,'is_remote',False) else self.store.notifications(self.user)
        self.deliver_notifications(inbox)
        self.refresh_signature=repr((self.tasks,self.reports,shifts,inbox,datetime.now().strftime('%Y%m%d%H%M')))
    def deliver_notifications(self,items):
        self.bell.setText('Уведомления'+(' · '+str(len(items)) if items else ''))
        self.desktop_notifications.feed(items)
    def open_notification(self,tid):
        if QApplication.activeModalWidget():
            QApplication.activeModalWidget().raise_()
            self.statusBar().showMessage('Сохраните или закройте текущее окно, затем откройте уведомления.',10000)
            return
        if tid:self.open_task(tid)
        else:self.notifications()
    def closeEvent(self,event):
        if self.desktop_notifications.hide_to_tray():event.ignore()
        else:event.accept();self.desktop_notifications.quit()
    def render(self,*,refresh_remote=True,animate=True):
        try:self.load(refresh_remote=refresh_remote)
        except PermissionError:
            QMessageBox.information(self,'Доступ','Аккаунт отключён.');self.logged_out.emit();return
        except (ValueError,OSError) as e:self.statusBar().showMessage(str(e),7000);return
        snapshot=self.transition.capture() if animate else None
        if not animate:self.transition.clear()
        for k,b in self.nav.items():b.setChecked(k==self.page_key)
        page=QWidget();page.setMaximumWidth(1220);self.body=QVBoxLayout(page);self.body.setContentsMargins(36,32,36,30);self.body.setSpacing(23)
        methods={'overview':self.overview,'tasks':self.tasks_page,'reports':self.reports_page,'team':self.team_page,
                 'schedule':self.schedule_page,'team_schedule':self.team_schedule_page,'profile':self.profile_page,'costs':self.costs_page,'users':self.users_page,'integrations':self.integrations_page,'ai_chat':self.ai_chat_page,'analytics':self.analytics_page,'references':self.references_page,'equipment':self.equipment_page}
        methods[self.page_key]();self.body.addStretch();self.body.addWidget(label('Костанайские минералы · НарядAI · Демонстрационная версия','muted'))
        old=self.scroll.takeWidget()
        if old:old.deleteLater()
        self.scroll.setWidget(page)
        self.transition.start(snapshot)
    def heading(self,title,subtitle,action=None):
        w=QWidget();l=QHBoxLayout(w);l.setContentsMargins(0,0,0,0)
        left=QVBoxLayout();left.addWidget(label('Костанайские минералы · '+ROLES[self.user['role']],'eyebrow'));left.addWidget(label(title,'heading'));left.addWidget(label(subtitle,'muted',True));l.addLayout(left,1)
        if action:l.addWidget(action)
        else:l.addWidget(tag(date.today().strftime('%d.%m.%Y')))
        self.body.addWidget(w)
    def ai_chat_page(self):
        self.heading('Чат с аналитикой','Проверенные агрегаты за неделю и текущая доступность работников; ИИ не меняет БД')
        if not getattr(self.store,'is_remote',False):
            self.body.addWidget(self.empty('Подключите приложение к общему серверу','Запустите configure_client.bat, укажите адрес сервера и откройте start_client.bat.'))
            return
        from app.ai_chat import AdminChatWidget
        self.chat_widget=AdminChatWidget(self.store);self.body.addWidget(self.chat_widget)
    def empty(self,title,sub):
        w,l=card();l.addWidget(label(title,'section',True));l.addWidget(label(sub,'muted',True));return w
    def stats(self,items):
        l=QHBoxLayout();l.setSpacing(16)
        for i,(value,title) in enumerate(items):
            w,c=card('stat');w.setProperty('accent',i==0);c.addWidget(label(value,'number'));c.addWidget(label(title,'muted',True));l.addWidget(w,1)
        self.body.addLayout(l)
    def task_card(self,t):
        w,l=card();w.setMinimumWidth(300)
        l.addLayout(row(label(f"НР-{t['id']}",'muted'),tag(STATUS[t['status']],tone(t['status']))))
        l.addWidget(tag(PRIORITIES[t['priority']],'urgent' if t['priority']=='urgent' else 'neutral'))
        l.addWidget(label(t['title'],'title',True));l.addWidget(label(t['equipment']+' · '+t['site'],'muted',True))
        l.addWidget(label((fmt_time(t['start'])+'–'+fmt_time(t['start']+t['duration']) if t['start'] is not None else f"{t['duration']:g} ч")+'  ·  '+t['day'],'muted'))
        l.addWidget(label('Срок: '+t['deadline'].replace('T',' '),'muted'))
        if t['status']=='paused':
            l.addWidget(tag('Приостановлен','employeeYellow'))
            l.addWidget(label('Причина: '+self.store.pauses(self.user,t['id'])[-1]['reason'],'',True))
        l.addStretch();l.addLayout(row(label(t['worker_name'] or 'Свободный наряд','muted',True),button('Выбрать' if t['status']=='available' and self.user['role']=='worker' else 'Открыть',lambda:self.open_task(t['id']),'secondary')))
        return w
    def report_card(self,r):
        w,l=card();l.addLayout(row(label(f"ОТ-{r['id']:04d} · НР-{r['task_id']}",'muted'),tag(STATUS[r['status']],tone(r['status']))))
        if r.get('ai',{}).get('status')=='completed':l.addWidget(label(f"Предварительно ИИ: {r['ai']['score']} / 100",'muted'))
        l.addWidget(label(r['title'],'title',True));l.addWidget(label(r['worker_name']+' · '+f"{r['hours']:g} ч",'muted'))
        bottom=row(label(f"{r['score']} / 100" if r['score'] is not None else 'Ожидает проверки' if r['status']=='submitted' else 'Без оценки','title'),button('Проверить' if r['status']=='submitted' and self.user['role']!='worker' else 'Открыть',lambda:self.open_report(r['id']),'secondary'))
        l.addLayout(bottom);return w
    def overview(self):
        self.heading('Обзор смены','Задачи, результаты и команда в одном месте',button('Создать наряд',self.create_task,'primary','plus') if self.user['role'] in ('master','admin') else button('Обновить',self.render,ico='refresh'))
        pending=[r for r in self.reports if r['status']=='submitted']
        hero,l=card('hero',28);l.addWidget(label('НУЖНА ВАША ПРОВЕРКА','muted'));l.addWidget(label(f'{len(pending)} отчёта на проверке','heading'))
        l.addWidget(label('Проверьте результаты и дайте сотрудникам обратную связь.','muted',True));b=button('Перейти к проверке',lambda:self.navigate('reports'),'secondary','report');b.setMaximumWidth(250);l.addWidget(b);self.body.addWidget(hero)
        approved=[r for r in self.reports if r['status']=='approved' and (r['reviewed'] or '').startswith(date.today().isoformat())]
        self.stats([(str(sum(t['status']=='available' for t in self.tasks)),'Доступно'),
                    (str(sum(t['status'] in ('planned','accepted','queued','rejected','inProgress','paused','revision') for t in self.tasks)),'В плане / работе'),
                    (str(len(pending)),'На проверке'),(str(len(approved)),'Принято сегодня')])
        self.body.addWidget(label('Ожидают решения','section'))
        self.body.addWidget(CardGrid([self.report_card(r) for r in pending[:2]]) if pending else self.empty('Все отчёты проверены','Новые результаты появятся после отправки сотрудниками.'))
        w,l=card();l.addWidget(label('Команда · рейтинг по принятым отчётам','section'))
        for i,p in enumerate(self.store.metrics(self.user)[:4],1):
            l.addLayout(row(label(f'{i:02d}','muted'),avatar(p['name']),label(p['name'],'title'),label(f"{p['done']} принято · {score_text(p['score'])} / 100",'muted')))
        self.body.addWidget(w)
    def tabs(self,items,current,callback):
        w=QFrame();w.setObjectName('tabs');l=QHBoxLayout(w);l.setContentsMargins(5,5,5,5);l.setSpacing(4);group=QButtonGroup(w)
        for k,title in items:
            b=button(title,lambda key=k:callback(key),'tab');b.setCheckable(True);b.setChecked(k==current);group.addButton(b);l.addWidget(b)
        self.body.addWidget(w)
    def change_task_filter(self,k):self.task_filter=k;self.render()
    def tasks_page(self):
        self.heading('Мои задачи' if self.user['role']=='worker' else 'Наряды','Выберите наряд или откройте текущую задачу',
                     button('Создать наряд',self.create_task,'primary','plus') if self.user['role'] in ('master','admin') else button('Обновить',self.render,ico='refresh'))
        if self.user['role']!='worker':
            refresh=button('Обновить список',self.render,ico='refresh');refresh.setMaximumWidth(220);self.body.addWidget(refresh)
        self.tabs([('available','Доступные'),('mine','Мои текущие'),('all','Все') ] if self.user['role']=='worker' else [('all','Все'),('available','Свободные'),('active','Текущие'),('approved','Принятые')],self.task_filter,self.change_task_filter)
        tools=QHBoxLayout();self.search=QLineEdit(self.query);self.search.setPlaceholderText('Поиск по номеру, названию, оборудованию или участку');self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.on_query);tools.addWidget(self.search,1)
        self.priority_box=combo([('Все приоритеты','all')]+[(name,key) for key,name in PRIORITIES.items()]);self.priority_box.setCurrentIndex(self.priority_box.findData(self.priority))
        self.priority_box.currentIndexChanged.connect(self.on_priority);tools.addWidget(self.priority_box);self.body.addLayout(tools)
        self.cards_host=QWidget();self.cards_layout=QVBoxLayout(self.cards_host);self.cards_layout.setContentsMargins(0,0,0,0);self.body.addWidget(self.cards_host);self.filter_cards()
    def on_query(self,text):self.query=text;self.search_timer.start()
    def on_priority(self):self.priority=self.priority_box.currentData();self.filter_cards()
    def filter_cards(self):
        if self.page_key!='tasks' or not hasattr(self,'cards_layout'):return
        while self.cards_layout.count():
            x=self.cards_layout.takeAt(0)
            if x.widget():x.widget().deleteLater()
        items=[]
        for t in self.tasks:
            match={'all':True,'available':t['status']=='available','mine':(t['worker_id']==self.user['id'] or self.user['id'] in t.get('member_ids',[])) and t['status'] not in ('approved','cancelled'),
                   'active':t['status'] not in ('available','approved','cancelled'),'approved':t['status']=='approved'}[self.task_filter]
            text=' '.join(str(t[k]) for k in ('id','title','site','equipment','worker_name')).lower()
            if match and (self.priority=='all' or t['priority']==self.priority) and self.query.lower() in text:items.append(t)
        self.cards_layout.addWidget(CardGrid([self.task_card(t) for t in items]) if items else self.empty('Наряды не найдены','Попробуйте изменить поиск или фильтр.'))
    def reports_page(self):
        self.heading('Отчёты','История результатов и решения мастера',button('Экспорт CSV',self.export_reports,'secondary','report'))
        self.tabs([('aiPending','Проверяет ИИ'),('submitted','У мастера'),('revision','Доработка'),('approved','Принятые'),('all','История')],self.report_filter,self.change_report_filter)
        items=[r for r in self.reports if self.report_filter=='all' or r['status']==self.report_filter]
        self.body.addWidget(CardGrid([self.report_card(r) for r in items]) if items else self.empty('Отчётов пока нет','Отправленные результаты появятся здесь.'))
    def change_report_filter(self,k):self.report_filter=k;self.render()
    def team_page(self):
        self.heading('Моя команда','Последние 90 дней: качество 40%, сроки 25%, доработки 15%, сложность и объём 15%, отказы 5%')
        people=self.store.metrics(self.user);done=sum(p['done'] for p in people)
        average=sum((p['score'] or 0)*p['done'] for p in people)/done if done else None
        self.stats([(str(len(people)),'Сотрудников'),(str(done),'Принято работ'),(score_text(average),'Рейтинг'),(f"{sum(p['hours'] for p in people):g} ч",'Принятые работы')])
        cards=[]
        for p in people:
            w,l=card();l.addLayout(row(avatar(p['name'],52),label(p['name'],'title',True)));l.addWidget(label(p['job'],'muted',True))
            l.addWidget(tag(*EMPLOYEE_STATUS[p['employee_status']]))
            l.addWidget(label(f"{p['done']} принято  ·  {score_text(p['score'])} / 100  ·  {p['active_count']} текущих",'',True))
            l.addWidget(button('Статистика сотрудника',lambda person=p:self.person(person),'secondary'));cards.append(w)
        self.body.addWidget(CardGrid(cards))
        self.body.addWidget(button('Посмотреть свободное время команды',lambda:self.navigate('team_schedule'),'secondary','calendar'))

    def team_schedule_page(self):
        self.heading('График команды','Настройте смену и назначьте наряд на свободное время')
        selector=DatePicker(self.schedule_day);selector.dateChanged.connect(self.change_schedule);self.body.addWidget(selector)
        legend=row(*[tag(*v) for v in EMPLOYEE_STATUS.values()]);self.body.addLayout(legend)
        self.body.addWidget(label('Цвет показывает состояние сейчас. Интервалы ниже относятся к выбранной дате; отображаются окна от 30 минут.','muted',True))
        day=self.schedule_day.toString('yyyy-MM-dd')
        for p in self.store.users(self.user,True):
            if not p['active']:continue
            w,l=card();l.addLayout(row(avatar(p['name']),label(p['name'],'title',True),tag(*EMPLOYEE_STATUS[self.store.employee_status(self.user,p['id'])])))
            shift=self.store.shift(self.user,p['id'],day)
            l.addLayout(row(label('Смена '+fmt_time(shift['start'])+'–'+fmt_time(shift['end']) if shift else 'Не на смене в выбранный день','muted'),
                button('Изменить смену',lambda person=p:self.edit_shift(person,day),'secondary','edit') if self.user['role'] in ('master','admin') else label('Только просмотр','muted')))
            for t in self.tasks:
                if (t['worker_id']==p['id'] or p['id'] in t.get('member_ids',[])) and t['day']==day and t['status']!='cancelled':
                    l.addWidget(button(f"{fmt_time(t['start'])}–{fmt_time(t['start']+t['duration'])} · НР-{t['id']} · {STATUS[t['status']]} · {t['title']}",lambda tid=t['id']:self.open_task(tid),'secondary'))
                    if t['status']=='paused':l.addWidget(label('Причина паузы: '+self.store.pauses(self.user,t['id'])[-1]['reason'],'',True))
            l.addWidget(label('Свободное время','section'))
            slots=self.store.free_slots(self.user,p['id'],day)
            for start,end in slots:
                l.addLayout(row(tag(fmt_time(start)+'–'+fmt_time(end),'employeeGreen'),
                    button('Назначить на это время',lambda wid=p['id'],a=start,b=end:self.assign_slot(wid,day,a,b),'primary','plus') if self.user['role'] in ('master','admin') else label('Свободно','muted')))
            if not slots:l.addWidget(label('Нет свободных окон от 30 минут. При просроченной активной работе сначала завершите её или обновите график.','muted',True))
            self.body.addWidget(w)

    def edit_shift(self,worker,day):
        if EditShift(self.store,self.user,worker,day,self).exec():self.render()

    def assign_slot(self,wid,day,start,end):
        if CreateTask(self.store,self.user,self,assignment=(wid,day,start,end)).exec():
            self.render();self.notify_success('Наряд назначен в график')
    def person(self,p):
        d=Sheet(p['name'],self);d.body.addWidget(label(p['job'],'muted'));d.body.addWidget(label(f"Принято: {p['done']} · Рейтинг: {score_text(p['score'])}",'title',True))
        for t in self.tasks:
            if (t['worker_id']==p['id'] or p['id'] in t.get('member_ids',[])) and t['status'] not in ('approved','cancelled'):
                d.body.addWidget(button(f"НР-{t['id']} · {t['title']}",lambda tid=t['id']:self.open_task(tid)))
        for r in self.reports:
            if r['worker_id']==p['id']:d.body.addWidget(label(f"ОТ-{r['id']:04d} · {STATUS[r['status']]} · {r['title']}",'',True))
        d.exec()
    def schedule_page(self):
        self.heading('Мой график','Смена и назначенные работы · нажмите на задачу, чтобы открыть наряд')
        selector=DatePicker(self.schedule_day);selector.dateChanged.connect(self.change_schedule);self.body.addWidget(selector)
        tasks=[t for t in self.tasks if (t['worker_id']==self.user['id'] or self.user['id'] in t.get('member_ids',[])) and t['day']==self.schedule_day.toString('yyyy-MM-dd') and t['status']!='cancelled']
        day=self.schedule_day.toString('yyyy-MM-dd');shift=self.store.shift(self.user,self.user['id'],day)
        hours=sum(t['duration'] for t in tasks);total=shift['end']-shift['start'] if shift else 0
        w,l=card();l.addWidget(tag(*EMPLOYEE_STATUS[self.store.employee_status(self.user,self.user['id'])]))
        l.addWidget(label('Смена '+fmt_time(shift['start'])+'–'+fmt_time(shift['end']) if shift else 'В выбранный день вы не на смене','title'))
        l.addWidget(label(f'В графике: {hours:g} ч из {total:g}','muted'))
        bar=QProgressBar();bar.setRange(0,100);bar.setValue(round(hours/total*100) if total else 0);bar.setTextVisible(False);l.addWidget(bar)
        slots=self.store.free_slots(self.user,self.user['id'],day)
        l.addWidget(label('Свободное время: '+(', '.join(fmt_time(a)+'–'+fmt_time(b) for a,b in slots) or 'Нет окон от 30 минут'),'muted',True));self.body.addWidget(w)
        if tasks:
            w,l=card();l.addWidget(Timeline(tasks,self.open_task,shift));self.body.addWidget(w)
        else:self.body.addWidget(self.empty('Назначенных работ нет','Выберите свободный наряд в разделе «Задачи».' if shift else 'Мастер может настроить рабочую смену.'))
    def change_schedule(self,d):self.schedule_day=d;self.render()
    def profile_page(self):
        self.heading('Мой профиль','Ваши результаты по принятым работам')
        w,l=card();l.addLayout(row(avatar(self.user['name'],64),label(self.user['name'],'section')));l.addWidget(label(self.user['job'],'muted'));self.body.addWidget(w)
        metric=next((r for r in self.store.metrics(self.user) if r['id']==self.user['id']),None)
        self.stats([(str(metric['done'] if metric else 0),'Закрыто за 90 дней'),(score_text(metric['score'] if metric else None),'Рейтинг'),(f"{metric['hours'] if metric else 0:g} ч",'Выполнено')])
        self.body.addWidget(label('Последние результаты','section'));self.body.addWidget(CardGrid([self.report_card(r) for r in self.reports[:4]]) if self.reports else self.empty('Пока без отчётов','После первой работы здесь появится результат.'))
    def references_page(self):
        from app.reference_dialogs import NAMES,ReferenceEditor
        self.heading('Справочники','Единые каталоги БД 002. Данные учебные; история нарядов сохраняется.')
        category=getattr(self,'reference_category','sites')
        def choose(key):self.reference_category=key;self.render()
        self.tabs(list(NAMES.items()),category,choose)
        def edit(item=None):
            if ReferenceEditor(self.store,self.user,category,self,item).exec():self.render()
        self.body.addWidget(button('Добавить запись',lambda:edit(),'primary','plus'))
        for item in self.store.catalogs(self.user)[category]:
            w,l=card();l.addWidget(label(item.get('name') or item.get('equipment_type'),'title',True));l.addWidget(label(' · '.join(str(v) for k,v in item.items() if k not in ('id','name') and v is not None),'muted',True));l.addWidget(button('Изменить',lambda value=item:edit(value),'secondary','edit'));self.body.addWidget(w)

    def equipment_page(self):
        self.heading('Оборудование','История по инвентарному номеру за весь период')
        for e in self.store.catalogs(self.user)['equipment']:
            self.body.addWidget(button(e['inventory_number']+' · '+e['name'],lambda eid=e['id']:self.equipment_history(eid),'secondary','tasks'))

    def equipment_history(self,eid):
        data=self.store.equipment_history(self.user,eid);d=Sheet(data['equipment']['name'],self)
        d.body.addWidget(label(data['equipment']['inventory_number'],'muted'));d.body.addWidget(label('Простой оборудования','section'))
        for item in data['downtimes']:d.body.addWidget(label(item['reason']+' · '+item['started_at']+' — '+(item['ended_at'] or 'открыт'),'',True))
        d.body.addWidget(label('Наряды за весь период','section'))
        for t in data['tasks']:d.body.addWidget(button(f"НР-{t['id']} · {t['title']} · {STATUS[t['status']]}",lambda tid=t['id']:self.open_task(tid),'secondary'))
        d.actions.addWidget(button('Закрыть',d.reject));d.exec()

    def analytics_page(self):
        self.heading('Сводка за период','Выданные наряды, исполнение, рейтинг, неисправности и простой оборудования')
        start,end=getattr(self,'analytics_dates',(QDate.currentDate().addDays(-6),QDate.currentDate()))
        self.analytics_start=DatePicker(start);self.analytics_end=DatePicker(end)
        self.body.addLayout(row(label('С', 'muted'),self.analytics_start,label('По (включительно)','muted'),self.analytics_end,button('Рассчитать',self.reload_analytics,'primary','chart')))
        try:result=self.store.analytics(self.user,start.toString('yyyy-MM-dd'),end.addDays(1).toString('yyyy-MM-dd'))
        except (ValueError,OSError,PermissionError) as e:self.body.addWidget(label(str(e),'error',True));return
        counts=result['counts'];self.stats([(str(counts['issued']),'Выдано'),(str(counts['completed']),'Выполнено'),(str(counts['completed_late']),'Выполнено с опозданием'),(str(counts['rejected']),'Отказов')])
        self.body.addWidget(label('Состояния на конец периода: '+', '.join(STATUS.get(k,k)+': '+str(v) for k,v in counts.get('status_at_end',{}).items()),'muted',True))
        self.body.addWidget(label('Рейтинг исполнителей','section'))
        for r in result['workers']:
            if r['done']:self.body.addWidget(label(r['name']+' · '+score_text(r['score'])+' · закрыто '+str(r['done'])+' · качество '+score_text(r['quality_score'])+' · сложность/объём '+str(r['complexity_volume']),'',True))
        self.body.addWidget(label('Рейтинг бригад','section'))
        for b in result['brigades']:self.body.addWidget(label(b['name']+' · '+score_text(b['score'])+' · закрыто '+str(b['done']),'',True))
        self.body.addWidget(label('Проблемное оборудование (число ремонтов)','section'))
        equipment={e['id']:e for e in self.store.catalogs(self.user)['equipment']}
        for r in result['failures'][:10]:self.body.addWidget(label(equipment.get(r['equipment_id'],{}).get('name',str(r['equipment_id']))+' · '+str(r['repairs'])+' · наряды '+', '.join(map(str,r['task_ids'])),'',True))
        self.body.addWidget(label('Простой оборудования без двойного счёта пересечений','section'))
        for r in result['equipment_downtime']:self.body.addWidget(label(equipment.get(r['equipment_id'],{}).get('name',str(r['equipment_id']))+' · '+str(r['hours'])+' ч','',True))
        self.body.addWidget(label('Расход материалов','section'))
        for r in result['materials'][:20]:self.body.addWidget(label(r['name']+' · '+str(r['quantity'])+' '+r['unit']+' · '+str(r['cost'])+' тг','',True))
        if result['coverage']['legacy_completion_times']:self.body.addWidget(label('Для '+str(result['coverage']['legacy_completion_times'])+' исторических отчётов время завершения восстановлено по отправке отчёта.','muted',True))
    def reload_analytics(self):
        self.analytics_dates=(self.analytics_start.date(),self.analytics_end.date());self.render()
    def costs_page(self):
        self.heading('Материалы и затраты','Единицы и цены из справочника; на экране показан период текущей истории',button('Экспорт CSV',self.export_reports,'secondary','report'))
        accepted=[r for r in self.reports if r['status']=='approved'];total=sum(m['quantity']*m['price'] for r in accepted for m in r['materials'])
        self.stats([(f'{total:,.2f} тг','По принятым отчётам'),(str(len(accepted)),'Принятых отчётов')])
        table=QTableWidget(0,5);table.setHorizontalHeaderLabels(['Наряд','Материал','Кол-во','Цена, тг','Сумма, тг'])
        for r in accepted:
            for m in r['materials']:
                n=table.rowCount();table.insertRow(n)
                for i,v in enumerate([f"НР-{r['task_id']}",m['name'],f"{m['quantity']:g} {m['unit']}",f"{m['price']:,.2f}",f"{m['quantity']*m['price']:,.2f}"]):table.setItem(n,i,QTableWidgetItem(str(v)))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);table.setMinimumHeight(330);self.body.addWidget(table)
        self.body.addWidget(label('Сейчас это учёт материалов. Автоматизацию расчётов можно будет подключить позже.','muted',True))
    def users_page(self):
        self.heading('Пользователи','Создание аккаунтов и управление доступом',button('Добавить',self.add_user,'primary','plus'))
        for u in self.store.users(self.user):
            w,l=card();l.addLayout(row(avatar(u['name']),label(u['name']+' · '+u['username'],'title',True),tag('Активен' if u['active'] else 'Отключён','success' if u['active'] else 'urgent')))
            l.addWidget(label(ROLES[u['role']]+' · '+u['job'],'muted',True))
            if u['id']!=self.user['id']:l.addWidget(button('Отключить' if u['active'] else 'Включить',lambda user=u:self.toggle_user(user),'danger' if u['active'] else 'secondary'))
            if u['role']=='worker':l.addWidget(button('Профиль и бригада',lambda person=u:self.employee_profile(person),'secondary','team'))
            l.addWidget(button('Сбросить пароль',lambda uid=u['id']:self.reset_password(uid),'secondary'))
            self.body.addWidget(w)
    def employee_profile(self,person):
        from app.dialogs import number
        d=Sheet('Профиль сотрудника',self)
        specialty=d.field('Специальность',QLineEdit(person['specialty'] or person['job']))
        grade=d.field('Разряд 1–6',number(person['grade'] or 1,1,6,1));grade.setDecimals(0)
        brigade=d.field('Бригада',combo([('Без бригады',None)]+[(b['name'],b['id']) for b in self.store.catalogs(self.user)['brigades']]))
        brigade.setCurrentIndex(max(0,brigade.findData(person['brigade_id'])))
        d.body.addWidget(label('Изменение состава сохраняет историю уже выданных нарядов.','muted',True))
        d.actions.addWidget(button('Сохранить',lambda:d.run_action(lambda:self.store.set_employee_profile(self.user,person['id'],specialty.text(),int(grade.value()),brigade.currentData())),'primary','check'))
        if d.exec():self.render()

    def reset_password(self,uid):
        d=Sheet('Новый пароль',self);password=QLineEdit();password.setEchoMode(QLineEdit.EchoMode.Password)
        d.field('Новый пароль (от 4 символов)',password)
        d.actions.addWidget(button('Сохранить пароль',lambda:d.run_action(lambda:self.store.reset_password(self.user,uid,password.text())),'primary'))
        if d.exec():self.notify_success('Пароль обновлён')
    def add_user(self):
        if AddUser(self.store,self.user,self).exec():self.render();self.notify_success('Аккаунт создан')
    def toggle_user(self,u):
        try:self.store.set_active(self.user,u['id'],not u['active']);self.render()
        except (ValueError,PermissionError) as e:QMessageBox.information(self,'Пользователь',str(e))
    def integrations_page(self):
        self.heading('Подключения и модули','Управление дополнительными возможностями приложения')
        remote=getattr(self.store,'is_remote',False);enabled=remote and self.store.snapshot()['ai_enabled']
        notice,l=card();l.addWidget(label('Проверка отчётов: '+('включена на сервере' if enabled else 'ручная'),'section'))
        l.addWidget(label('Модель для проверки выбирается в AnythingLLM на ПК обработчика. Управление подключениями через эту панель добавим позже.','muted',True))
        self.body.addWidget(notice)
        for title,description in INTEGRATION_AREAS:
            active=enabled and title=='Тексты и отчёты'
            w,l=card();l.addLayout(row(label(title,'section'),tag('Серверная проверка' if active else 'Следующий этап','purple' if active else 'neutral')))
            l.addWidget(label(description,'muted',True));self.body.addWidget(w)
        self.body.addWidget(label('Этот раздел доступен только администратору.','muted',True))
    def create_task(self):
        if CreateTask(self.store,self.user,self).exec():self.render();self.notify_success('Наряд создан')
    def open_task(self,tid):
        try:
            if TaskDetails(self.store,self.user,tid,self).exec():self.render();self.notify_success('Изменения сохранены')
        except (ValueError,PermissionError,OSError) as e:QMessageBox.information(self,'Наряд',str(e))
    def open_report(self,rid):
        # Всегда открываем свежие данные — другой пользователь мог уже проверить отчёт.
        try:
            if getattr(self.store,'is_remote',False):self.store.refresh_snapshot(self.schedule_day.toString('yyyy-MM-dd'))
            r=next((r for r in self.store.reports(self.user) if r['id']==rid),None)
            if r and ReviewReport(self.store,self.user,r,self).exec():self.render();self.notify_success('Решение сохранено')
        except (ValueError,PermissionError,OSError) as e:QMessageBox.information(self,'Отчёт',str(e))
    def notifications(self):
        from app.notification_content import notification_content
        try:items=self.store.notifications(self.user)
        except (ValueError,OSError,PermissionError) as e:QMessageBox.information(self,'Уведомления',str(e));return
        d=Sheet('Уведомления',self)
        enabled=QCheckBox('Всплывающие уведомления Windows');enabled.setChecked(self.desktop_notifications.enabled)
        enabled.toggled.connect(self.desktop_notifications.set_enabled);d.body.addWidget(enabled)
        d.body.addWidget(label('Крестик сворачивает приложение к часам. Для полного выхода используйте меню значка.','muted',True))
        d.body.addWidget(button('Проверить уведомление',self.desktop_notifications.test))
        if self.user['role'] in ('master','admin'):
            def compose():d.accept();QTimer.singleShot(0,self,self.send_announcement)
            d.body.addWidget(button('Оповестить сотрудников',compose,'primary'))
        if items:d.body.addWidget(button('Прочитать все',lambda:d.run_action(lambda:self.store.acknowledge_notifications(self.user,[i['id'] for i in items]))))
        if not items:d.body.addWidget(label('Новых уведомлений пока нет','section'))
        for item in items:
            content=notification_content(item)
            w,l=card();l.addWidget(label(content['title'],'title'));l.addWidget(label(item['created_at'],'muted'))
            l.addWidget(label(content['body'],'',True))
            if item['task_id']:
                def open_item(tid=item['task_id']):d.accept();QTimer.singleShot(0,self,lambda:self.open_task(tid))
                l.addWidget(button('Открыть наряд',open_item,'secondary'))
            l.addWidget(button('Прочитано',lambda nid=item['id']:d.run_action(lambda:self.store.acknowledge_notification(self.user,nid))));d.body.addWidget(w)
        d.body.addStretch()
        d.exec();self.render(animate=False)
    def send_announcement(self):
        d=Sheet('Оповестить сотрудников',self)
        people=[u for u in self.store.users(self.user,True) if u['active']]
        recipient=d.field('Получатель',combo([('Все сотрудники',None)]+[(p['name'],p['id']) for p in people]))
        title=d.field('Заголовок',QLineEdit());title.setMaxLength(120)
        message=d.field('Сообщение',QTextEdit());message.setFixedHeight(150)
        important=QCheckBox('Важное сообщение');d.body.addWidget(important)
        def send():
            ids=[recipient.currentData()] if recipient.currentData() is not None else None
            self.store.send_announcement(self.user,title.text(),message.toPlainText(),ids,important.isChecked())
        d.body.addWidget(button('Отправить',lambda:d.run_action(send),'primary'))
        if d.exec():self.notify_success('Оповещение отправлено сотрудникам')
    def export_reports(self):
        p,_=QFileDialog.getSaveFileName(self,'Экспорт отчётов','NaryadAI_reports.csv','CSV (*.csv)')
        if p:
            if not p.lower().endswith('.csv'):p+='.csv'
            try:self.store.export_reports(self.user,p);self.notify_success('Отчёты экспортированы')
            except OSError as e:QMessageBox.warning(self,'Экспорт',str(e))
    def notify_success(self,message):
        self.statusBar().showMessage(message,5000);self.toast.show_message(message)
