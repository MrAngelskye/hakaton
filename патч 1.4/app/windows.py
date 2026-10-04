import math
import threading
from datetime import date,datetime
from PySide6.QtCore import Qt,QDate,QTimer,Signal,QObject
from PySide6.QtGui import QPainter,QColor,QPen
from PySide6.QtWidgets import (QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFrame,
    QScrollArea,QLineEdit,QButtonGroup,QLabel,QDateEdit,QProgressBar,QSizePolicy,
    QFileDialog,QMessageBox,QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,QSpinBox)
from app.widgets import label,button,brand,card,row,avatar,tag,CardGrid,Sheet,DatePicker,motion_toggle,Toast,company_logo
from app.theme import COLORS
from app.domain import PRIORITIES,company_time
from app.reference_dialogs import ReferenceEditor,NAMES
from app.dialogs import EquipmentHistory
from app.motion import PageTransition
from app.store import ROLES,STATUS,EMPLOYEE_STATUS
from app.dialogs import CreateTask,TaskDetails,ReviewReport,AddUser,EditShift,combo
from app.integrations import INTEGRATION_AREAS


def fmt_time(n):return f'{int(n):02d}:{int(round(n%1*60)):02d}'
def tone(status):return {'approved':'success','revision':'urgent','paused':'warning','inProgress':'info','planned':'purple','submitted':'info','aiPending':'purple'}.get(status,'neutral')
def score_text(n):return '—' if n is None else f'{n:.1f}'


class SnapshotLoader(QObject):
    ready=Signal(dict);failed=Signal(str);finished=Signal()
    def __init__(self,store,day,parent):super().__init__(parent);self.store=store;self.day=day;self.token=store.token;self.running=False
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
        story,l=card('story',36);story.setMinimumWidth(450);l.addWidget(brand());l.addWidget(company_logo());l.addStretch()
        l.addWidget(label('АО «Костанайские Минералы»','',True))
        l.addWidget(label('Наряд выдан.\nИИ на контроле.','heading',True))
        l.addWidget(label('Наряды, сроки и результаты ремонта\nв одном рабочем пространстве.','muted',True))
        steps,s=card('storySteps',22);s.addWidget(label('Рабочий день под контролем','title'))
        for i,(title,sub) in enumerate([('Работать с нарядом на участке','Добыча, дробление, обогащение и ремонт'),
                                       ('Выполнить и отправить отчёт','Работы, время, материалы и фото'),
                                       ('Получить обратную связь','Комментарий и оценка мастера')],1):
            s.addWidget(label(f'{i:02d}  {title}','',True));s.addWidget(label(sub,'muted',True))
        l.addWidget(steps);l.addStretch();l.addWidget(label('Общий сервер · проверка мастером' if getattr(store,'is_remote',False) else 'Демонстрационная версия · ручная проверка','muted'))
        layout.addWidget(story,1)
        form=QWidget();f=QVBoxLayout(form);f.setSpacing(14);f.setContentsMargins(0,8,0,8)
        f.addStretch();f.addWidget(label('Добро пожаловать','heading'));f.addWidget(label('Войдите в свою рабочую смену','muted'))
        f.addSpacing(10);f.addWidget(label('Выберите роль','title'))
        self.roles=QButtonGroup(self);self.roles.setExclusive(True)
        for i,(role,title,sub) in enumerate([('worker','Сотрудник','Задачи, график и результаты'),('master','Мастер','Наряды, отчёты и команда'),('admin','Администратор','Пользователи и настройки')]):
            b=button(title+'\n'+sub,kind='role',ico={'worker':'user','master':'tool','admin':'shield'}[role]);b.setCheckable(True)
            self.roles.addButton(b,i);b.clicked.connect(lambda checked=False,r=role:self.choose_role(r));f.addWidget(b)
        self.roles.button(0).setChecked(True);self.role='worker'
        f.addWidget(label('Логин'));self.username=QLineEdit('worker1');self.username.setObjectName('username');self.username.setPlaceholderText('worker1');f.addWidget(self.username)
        f.addWidget(label('Пароль'));self.password=QLineEdit('' if getattr(store,'is_remote',False) else '1234');self.password.setObjectName('password');self.password.setEchoMode(QLineEdit.EchoMode.Password);f.addWidget(self.password)
        self.error=label('','error',True);self.error.hide();f.addWidget(self.error)
        self.enter=button('Войти',self.login,'primary');self.enter.setObjectName('primary');self.enter.setDefault(True);f.addWidget(self.enter)
        self.password.returnPressed.connect(self.login);self.username.returnPressed.connect(self.login)
        f.addWidget(label('Тестовые аккаунты: master, worker1–worker4, admin.\n'+('Пароль выдаёт администратор сервера.' if getattr(store,'is_remote',False) else 'Пароль для всех: 1234.'),'muted',True));f.addWidget(motion_toggle());f.addStretch()
        layout.addWidget(form,1);self.setCentralWidget(host)
    def choose_role(self,role):
        self.role=role;self.username.setText({'worker':'worker1','master':'master','admin':'admin'}[role]);self.error.hide()
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
        super().__init__();self.store=store;self.user=user;self.setWindowTitle('НарядAI · Костанайские Минералы');self.resize(1360,900);self.setMinimumSize(1040,760)
        self.page_key='overview'
        self.task_filter='mine' if user['role']=='worker' else 'all';self.report_filter='submitted';self.query='';self.priority='all';self.schedule_day=QDate.currentDate()
        host=QWidget();outer=QHBoxLayout(host);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0)
        sidebar,self.side=card('sidebar',18);self.side.setSpacing(8)
        self.side.addWidget(brand());self.side.addSpacing(16);self.side.addWidget(label('Костанайские\nМинералы','title'));self.side.addWidget(label('Производственная смена','muted'));self.side.addSpacing(22)
        self.side.addWidget(label(ROLES[user['role']].upper(),'muted'));self.side.addSpacing(6)
        self.nav={}
        items=[('overview','grid','Смена'),('tasks','tasks','Наряды'),('reports','report','Отчёты'),('team','team','Команда'),('team_schedule','calendar','График команды'),('costs','chart','Материалы')]
        if user['role']=='worker':items=[('overview','grid','Моя смена'),('tasks','tasks','Наряды'),('schedule','calendar','График'),('reports','report','Отчёты'),('profile','user','Профиль')]
        elif user['role']=='admin':items += [('ai_chat','spark','Чат с ИИ'),('users','shield','Пользователи'),('integrations','spark','Подключения'),('references','tool','Справочники')]
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
        tl.addWidget(label('Костанайские Минералы · Смена','muted'));tl.addStretch();tl.addWidget(tag(ROLES[user['role']]))
        self.bell=button('Уведомления',self.notifications,ico='bell');tl.addWidget(self.bell);tl.addWidget(avatar(user['name']))
        c.addWidget(top);self.scroll=QScrollArea();self.scroll.setWidgetResizable(True);c.addWidget(self.scroll,1)
        outer.addWidget(content,1);self.setCentralWidget(host)
        self.transition=PageTransition(self.scroll.viewport());self.toast=Toast(self)
        self.search_timer=QTimer(self);self.search_timer.setSingleShot(True);self.search_timer.setInterval(180);self.search_timer.timeout.connect(self.filter_cards)
        self.refresh_timer=QTimer(self);self.refresh_timer.setInterval(3000 if getattr(store,'is_remote',False) else 15000);self.refresh_timer.timeout.connect(self.refresh_if_idle);self.refresh_timer.start()
        self._snapshot_loader=None;self.refresh_signature='';self.tasks=[];self.reports=[]
        self.render()
    def refresh_if_idle(self):
        from PySide6.QtWidgets import QApplication
        if QApplication.activeModalWidget():return
        if getattr(self.store,'is_remote',False):
            if self._snapshot_loader and self._snapshot_loader.isRunning():return
            loader=SnapshotLoader(self.store,self.schedule_day.toString('yyyy-MM-dd'),self)
            self._snapshot_loader=loader;loader.ready.connect(self.remote_snapshot);loader.failed.connect(lambda msg:self.statusBar().showMessage(msg,5000))
            loader.finished.connect(self.network_finished);loader.finished.connect(loader.deleteLater);loader.start();return
        if self.page_key not in ('tasks','users','ai_chat'):
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
        if not self.store.actor or self.store.actor['id']!=self.user['id']:return
        sender=self.sender()
        if isinstance(sender,SnapshotLoader) and sender.token!=self.store.token:return
        if snapshot['day']!=self.schedule_day.toString('yyyy-MM-dd'):return
        old=self.refresh_signature;self.store._snapshot=snapshot
        if QApplication.activeModalWidget():return
        self.load(refresh_remote=False)
        self.statusBar().showMessage('Подключено к '+self.store.url,4000)
        if self.refresh_signature==old:return
        count=sum(not a.get('acknowledged') for a in self.alerts)+sum(r['status']==('revision' if self.user['role']=='worker' else 'submitted') for r in self.reports)
        self.bell.setText(f'Уведомления · {count}' if count else 'Уведомления')
        if self.page_key=='ai_chat':return
        if self.page_key=='tasks' and hasattr(self,'search'):self.filter_cards();return
        scroll_value=self.scroll.verticalScrollBar().value();self.render(refresh_remote=False,animate=False)
        QTimer.singleShot(0,self.scroll,lambda:self.scroll.verticalScrollBar().setValue(scroll_value))
    def load(self,refresh_remote=True):
        if getattr(self.store,'is_remote',False) and refresh_remote:self.store.refresh_snapshot(self.schedule_day.toString('yyyy-MM-dd'))
        self.tasks=self.store.tasks(self.user);self.reports=self.store.reports(self.user);self.alerts=self.store.alerts(self.user)
        people=self.store.users(self.user,True) if self.user['role']!='worker' else [self.user]
        shifts=[self.store.shift(self.user,p['id'],self.schedule_day.toString('yyyy-MM-dd')) for p in people]
        self.refresh_signature=repr((self.tasks,self.reports,self.alerts,shifts,datetime.now().strftime('%Y%m%d%H%M')))
    def render(self,*,refresh_remote=True,animate=True):
        try:self.load(refresh_remote=refresh_remote)
        except PermissionError:
            QMessageBox.information(self,'Доступ','Аккаунт отключён.');self.logged_out.emit();return
        except (ValueError,OSError) as e:self.statusBar().showMessage(str(e),7000);return
        snapshot=self.transition.capture() if animate else None
        if not animate:self.transition.clear()
        for k,b in self.nav.items():b.setChecked(k==self.page_key)
        count=sum(not a.get('acknowledged') for a in self.alerts)+sum(r['status']==('revision' if self.user['role']=='worker' else 'submitted') for r in self.reports)
        self.bell.setText(f'Уведомления · {count}' if count else 'Уведомления')
        page=QWidget();page.setMaximumWidth(1220);self.body=QVBoxLayout(page);self.body.setContentsMargins(36,32,36,30);self.body.setSpacing(23)
        methods={'overview':self.overview,'tasks':self.tasks_page,'reports':self.reports_page,'team':self.team_page,
                 'schedule':self.schedule_page,'team_schedule':self.team_schedule_page,'profile':self.profile_page,'costs':self.costs_page,'users':self.users_page,'integrations':self.integrations_page,'ai_chat':self.ai_chat_page,'references':self.references_page}
        methods[self.page_key]();self.body.addStretch();self.body.addWidget(label('Костанайские Минералы · НарядAI · Демонстрационная версия','muted'))
        old=self.scroll.takeWidget()
        if old:old.deleteLater()
        self.scroll.setWidget(page)
        self.transition.start(snapshot)
    def heading(self,title,subtitle,action=None):
        w=QWidget();l=QHBoxLayout(w);l.setContentsMargins(0,0,0,0)
        left=QVBoxLayout();left.addWidget(label('Костанайские Минералы · '+ROLES[self.user['role']],'eyebrow'));left.addWidget(label(title,'heading'));left.addWidget(label(subtitle,'muted',True));l.addLayout(left,1)
        if action:l.addWidget(action)
        else:l.addWidget(tag(date.today().strftime('%d.%m.%Y')))
        self.body.addWidget(w)
    def ai_chat_page(self):
        self.heading('Чат с ИИ','Личный диалог администратора с подключённой моделью')
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
        l.addWidget(tag(PRIORITIES[t['priority']],'urgent' if t['priority']=='urgent' else 'warning' if t['priority']=='high' else 'neutral'))
        l.addWidget(label(t['title'],'title',True));l.addWidget(label(t['equipment']+' · '+t['site'],'muted',True))
        l.addWidget(label((fmt_time(t['start'])+'–'+fmt_time(t['start']+t['duration']) if t['start'] is not None else f"{t['duration']:g} ч")+'  ·  '+t['day'],'muted'))
        l.addWidget(label('Срок: '+t['deadline'].replace('T',' '),'muted'))
        if t['status'] not in ('submitted','aiPending','approved','cancelled','rejected'):
            minutes=round((company_time(t['deadline'])-company_time()).total_seconds()/60)
            l.addWidget(tag('Просрочен на '+str(abs(minutes))+' мин' if minutes<0 else 'Осталось '+str(minutes)+' мин','urgent' if minutes<0 else 'warning' if minutes<=30 else 'neutral'))
        if t['status']=='paused':
            l.addWidget(tag('Приостановлен','employeeYellow'))
            l.addWidget(label('Причина: '+self.store.pauses(self.user,t['id'])[-1]['reason'],'',True))
        actions={'issued':'Принять наряд','accepted':'Начать работу','queued':'Начать работу','planned':'Начать работу','paused':'Продолжить','inProgress':'Отправить отчёт','revision':'Доработать'}
        caption=actions.get(t['status'],'Открыть') if self.user['role']=='worker' and t['worker_id']==self.user['id'] else 'Открыть'
        l.addStretch();l.addLayout(row(label(t['worker_name'] or 'Свободный наряд','muted',True),button(caption,lambda:self.primary_task(t),'primary' if caption!='Открыть' else 'secondary')))
        return w
    def report_card(self,r):
        w,l=card();l.addLayout(row(label(f"ОТ-{r['id']:04d} · НР-{r['task_id']}",'muted'),tag(STATUS[r['status']],tone(r['status']))))
        if r.get('ai',{}).get('status')=='completed':l.addWidget(label(f"Предварительно ИИ: {r['ai']['score']} / 100",'muted'))
        l.addWidget(label(r['title'],'title',True));l.addWidget(label(r['worker_name']+' · '+f"{r['hours']:g} ч",'muted'))
        bottom=row(label(f"{r['score']} / 100" if r['score'] is not None else 'Ожидает проверки' if r['status']=='submitted' else 'Без оценки','title'),button('Проверить' if r['status']=='submitted' and self.user['role']!='worker' else 'Открыть',lambda:self.open_report(r['id']),'secondary'))
        l.addLayout(bottom);return w
    def overview(self):
        if self.user['role']=='worker':self.worker_overview();return
        self.heading('Обзор смены','Задачи, результаты и команда в одном месте',button('Создать наряд',self.create_task,'primary','plus'))
        pending=[r for r in self.reports if r['status']=='submitted']
        hero,l=card('hero',28);l.addWidget(label('НУЖНА ВАША ПРОВЕРКА','muted'));l.addWidget(label(f'{len(pending)} отчёта на проверке','heading'))
        l.addWidget(label('Проверьте результаты и дайте сотрудникам обратную связь.','muted',True));b=button('Перейти к проверке',lambda:self.navigate('reports'),'secondary','report');b.setMaximumWidth(250);l.addWidget(b);self.body.addWidget(hero)
        approved=[r for r in self.reports if r['status']=='approved' and (r['reviewed'] or '').startswith(date.today().isoformat())]
        self.stats([(str(sum(t['status']=='available' for t in self.tasks)),'Доступно'),
                    (str(sum(t['status'] in ('issued','accepted','queued','planned','inProgress','paused','revision') for t in self.tasks)),'В плане / работе'),
                    (str(len(pending)),'На проверке'),(str(len(approved)),'Принято сегодня')])
        self.attention_panel()
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
        self.heading('Мои задачи' if self.user['role']=='worker' else 'Наряды','Назначенные работы, сроки и результаты',
                     button('Создать наряд',self.create_task,'primary','plus') if self.user['role']!='worker' else button('Обновить',self.render,ico='refresh'))
        if self.user['role']!='worker':
            refresh=button('Обновить список',self.render,ico='refresh');refresh.setMaximumWidth(220);self.body.addWidget(refresh)
        self.tabs([('available','Доступные'),('mine','Мои текущие'),('all','Все') ] if self.user['role']=='worker' else [('all','Все'),('available','Свободные'),('active','Текущие'),('approved','Принятые')],self.task_filter,self.change_task_filter)
        tools=QHBoxLayout();self.search=QLineEdit(self.query);self.search.setPlaceholderText('Поиск по номеру, названию, оборудованию или участку');self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.on_query);tools.addWidget(self.search,1)
        self.priority_box=combo([('Все приоритеты','all')]+[(v,k) for k,v in PRIORITIES.items()]);self.priority_box.setCurrentIndex(self.priority_box.findData(self.priority))
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
            match={'all':True,'available':t['status']=='available','mine':t['worker_id']==self.user['id'] and t['status'] not in ('approved','cancelled'),
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
        self.heading('Моя команда','Рейтинг рассчитан по всем принятым отчётам; оценку выставляет мастер')
        people=self.store.metrics(self.user);done=sum(p['done'] for p in people)
        average=sum((p['score'] or 0)*p['done'] for p in people)/done if done else None
        self.stats([(str(len(people)),'Сотрудников'),(str(done),'Принято работ'),(score_text(average),'Средняя оценка'),(f"{sum(p['hours'] for p in people):g} ч",'Принятые работы')])
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
                button('Изменить смену',lambda person=p:self.edit_shift(person,day),'secondary','edit')))
            for t in self.tasks:
                if t['worker_id']==p['id'] and t['day']==day and t['status']!='cancelled':
                    l.addWidget(button(f"{fmt_time(t['start'])}–{fmt_time(t['start']+t['duration'])} · НР-{t['id']} · {STATUS[t['status']]} · {t['title']}",lambda tid=t['id']:self.open_task(tid),'secondary'))
                    if t['status']=='paused':l.addWidget(label('Причина паузы: '+self.store.pauses(self.user,t['id'])[-1]['reason'],'',True))
            l.addWidget(label('Свободное время','section'))
            slots=self.store.free_slots(self.user,p['id'],day)
            for start,end in slots:
                l.addLayout(row(tag(fmt_time(start)+'–'+fmt_time(end),'employeeGreen'),
                    button('Назначить на это время',lambda wid=p['id'],a=start,b=end:self.assign_slot(wid,day,a,b),'primary','plus')))
            if not slots:l.addWidget(label('Нет свободных окон от 30 минут. При просроченной активной работе сначала завершите её или обновите график.','muted',True))
            self.body.addWidget(w)

    def edit_shift(self,worker,day):
        if EditShift(self.store,self.user,worker,day,self).exec():self.render()

    def assign_slot(self,wid,day,start,end):
        if CreateTask(self.store,self.user,self,assignment=(wid,day,start,end)).exec():
            self.render();self.notify_success('Наряд назначен в график')
    def person(self,p):
        d=Sheet(p['name'],self);d.body.addWidget(label(p['job'],'muted'));d.body.addWidget(label(f"Принято: {p['done']} · Средняя оценка: {score_text(p['score'])}",'title',True))
        for t in self.tasks:
            if t['worker_id']==p['id'] and t['status'] not in ('approved','cancelled'):
                d.body.addWidget(button(f"НР-{t['id']} · {t['title']}",lambda tid=t['id']:self.open_task(tid)))
        for r in self.reports:
            if r['worker_id']==p['id']:d.body.addWidget(label(f"ОТ-{r['id']:04d} · {STATUS[r['status']]} · {r['title']}",'',True))
        d.exec()
    def schedule_page(self):
        self.heading('Мой график','Смена и назначенные работы · нажмите на задачу, чтобы открыть наряд')
        selector=DatePicker(self.schedule_day);selector.dateChanged.connect(self.change_schedule);self.body.addWidget(selector)
        tasks=[t for t in self.tasks if t['worker_id']==self.user['id'] and t['day']==self.schedule_day.toString('yyyy-MM-dd') and t['status']!='cancelled']
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
        else:self.body.addWidget(self.empty('Назначенных работ нет','Новый наряд появится после назначения мастером.' if shift else 'Мастер может настроить рабочую смену.'))
    def change_schedule(self,d):self.schedule_day=d;self.render()
    def profile_page(self):
        self.heading('Мой профиль','Ваши результаты по принятым работам')
        w,l=card();l.addLayout(row(avatar(self.user['name'],64),label(self.user['name'],'section')));l.addWidget(label(self.user['job'],'muted'));self.body.addWidget(w)
        rr=[r for r in self.reports if r['status']=='approved'];score=sum(r['score'] for r in rr)/len(rr) if rr else None
        self.stats([(str(len(rr)),'Принято'),(score_text(score),'Средняя оценка'),(f"{sum(r['hours'] for r in rr):g} ч",'Выполнено')])
        self.body.addWidget(label('Последние результаты','section'));self.body.addWidget(CardGrid([self.report_card(r) for r in self.reports[:4]]) if self.reports else self.empty('Пока без отчётов','После первой работы здесь появится результат.'))
    def costs_page(self):
        self.heading('Материалы и затраты','Стоимость указана сотрудниками и проверяется мастером',button('Экспорт CSV',self.export_reports,'secondary','report'))
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
            l.addWidget(button('Сбросить пароль',lambda uid=u['id']:self.reset_password(uid),'secondary'))
            self.body.addWidget(w)
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
        status='revision' if self.user['role']=='worker' else 'submitted'
        items=[r for r in self.store.reports(self.user) if r['status']==status]
        alerts=self.store.alerts(self.user);d=Sheet('Уведомления',self)
        if not items and not alerts:d.body.addWidget(label('Новых уведомлений пока нет','section'))
        for alert in alerts:
            w,l=card();l.addWidget(label(f"НР-{alert['task_id']} · {alert['equipment']}",'section',True));l.addWidget(label(alert['message'],'',True))
            l.addWidget(button('Открыть НР-'+str(alert['task_id']),lambda tid=alert['task_id']:self.open_task(tid),'secondary'))
            if not alert.get('acknowledged'):
                l.addWidget(button('Прочитано',lambda aid=alert['id']:self.mark_alert(aid,d),'secondary','check'))
            d.body.addWidget(w)
        for r in items:
            d.body.addWidget(label(r['worker_name'],'muted'));d.body.addWidget(button(r['title'],lambda rid=r['id']:self.open_report(rid),'secondary'))
        d.exec();self.render(animate=False)
    def mark_alert(self,aid,dialog):
        try:self.store.acknowledge_alert(self.user,aid);dialog.accept()
        except (ValueError,PermissionError,OSError) as e:dialog.fail(e)
    def export_reports(self):
        p,_=QFileDialog.getSaveFileName(self,'Экспорт отчётов','NaryadAI_reports.csv','CSV (*.csv)')
        if p:
            if not p.lower().endswith('.csv'):p+='.csv'
            try:self.store.export_reports(self.user,p);self.notify_success('Отчёты экспортированы')
            except OSError as e:QMessageBox.warning(self,'Экспорт',str(e))
    def notify_success(self,message):
        self.statusBar().showMessage(message,5000);self.toast.show_message(message)

    def primary_task(self,t):
        if t['worker_id']==self.user['id'] and t['status'] in ('issued','accepted','queued','planned','paused','revision'):
            try:
                self.store.transition(self.user,t['id'],'accepted' if t['status']=='issued' else 'inProgress')
                self.render();self.notify_success('Наряд принят' if t['status']=='issued' else 'Работа начата')
            except (ValueError,PermissionError,OSError) as e:QMessageBox.information(self,'Наряд',str(e))
        else:self.open_task(t['id'])
    def worker_overview(self):
        self.heading('Моя смена','Назначенные наряды и ближайшие действия',button('Все наряды',lambda:self.navigate('tasks'),'secondary','tasks'))
        own=[t for t in self.tasks if t['worker_id']==self.user['id'] and t['status'] not in ('approved','cancelled','rejected','submitted','aiPending')]
        current=[t for t in own if t['status'] in ('inProgress','paused','revision')]
        following=sorted([t for t in own if t not in current],key=lambda t:(t['priority']!='urgent',t['deadline']))
        self.stats([(str(len(own)),'Назначено'),(str(sum(t['status']=='issued' for t in own)),'Ждут принятия'),
            (str(sum(not a.get('acknowledged') for a in self.alerts)),'Уведомления')])
        self.body.addWidget(label('Текущая работа','section'))
        self.body.addWidget(CardGrid([self.task_card(t) for t in current]) if current else self.empty('Работа ещё не начата','Примите назначенный наряд и нажмите «Начать работу».'))
        self.body.addWidget(label('Следующие наряды','section'))
        self.body.addWidget(CardGrid([self.task_card(t) for t in following[:4]]) if following else self.empty('Очередь пуста','Мастер увидит вашу загрузку и назначит следующий наряд.'))
    def attention_panel(self):
        data=self.store.attention(self.user)
        w,l=card();l.addWidget(label('Требуют внимания','section'))
        alerts=[a for a in data.get('alerts',[]) if not a.get('acknowledged')]
        for alert in alerts[:4]:l.addWidget(button(f"НР-{alert['task_id']} · {alert['equipment']} · {alert['message']}",lambda tid=alert['task_id']:self.open_task(tid),'secondary'))
        for pause in data.get('pauses',[])[:3]:
            l.addWidget(button(pause['equipment']+' · '+pause['reason']+' · '+str(round(pause['minutes']))+' мин',lambda tid=pause['task_id']:self.open_task(tid),'secondary','clock'))
        for repeated in data.get('repeated_equipment',[])[:3]:
            l.addWidget(button('Повторные неисправности · '+repeated['equipment'],lambda name=repeated['equipment']:EquipmentHistory(self.store,self.user,name,self).exec(),'secondary','tool'))
        if not alerts and not data.get('pauses') and not data.get('repeated_equipment'):l.addWidget(label('Активных предупреждений нет','muted'))
        l.addWidget(label('Показатели рассчитаны по нарядам и зафиксированным паузам.','muted',True));self.body.addWidget(w)
    def references_page(self):
        self.heading('Справочники','Демонстрационные данные; замените их согласованными данными предприятия')
        category=getattr(self,'reference_category','sites')
        selector=combo([(title,key) for key,title in NAMES.items()]);selector.setCurrentIndex(selector.findData(category))
        selector.currentIndexChanged.connect(lambda:self.change_reference_category(selector.currentData()));self.body.addWidget(selector)
        self.body.addWidget(button('Добавить запись',lambda:self.edit_reference(category),'primary','plus'))
        for item in self.store.references(self.user,category):
            w,l=card();l.addWidget(label(item['name'],'title',True));l.addWidget(tag('Действует' if item['active'] else 'Архив','success' if item['active'] else 'neutral'))
            description=' · '.join(str(item[k]) for k in ('code','unit','hours') if item.get(k) is not None)
            if description:l.addWidget(label(description,'muted'))
            l.addWidget(button('Изменить',lambda item=item:self.edit_reference(category,item),'secondary','edit'));self.body.addWidget(w)
            if item['active']:l.addWidget(button('Отключить запись',lambda rid=item['id']:self.archive_reference(category,rid),'danger'))
        self.body.addWidget(button('Настроить напоминания',self.notification_preferences,'secondary','clock'))
    def change_reference_category(self,key):self.reference_category=key;self.render()
    def edit_reference(self,category,item=None):
        if ReferenceEditor(self.store,self.user,category,self,item).exec():self.render();self.notify_success('Справочник обновлён')
    def archive_reference(self,category,rid):
        try:self.store.delete_reference(self.user,category,rid);self.render();self.notify_success('Запись отключена')
        except (ValueError,PermissionError,OSError) as e:QMessageBox.information(self,'Справочник',str(e))
    def notification_preferences(self):
        settings=self.store.notification_settings(self.user);d=Sheet('Напоминания и эскалация',self)
        fields={}
        for key,title in [('reminder_minutes','До срока, мин'),('accept_minutes','Без принятия, мин'),('urgent_accept_minutes','Аварийный без принятия, мин')]:
            fields[key]=QSpinBox()
            fields[key].setRange(1,240);fields[key].setValue(settings[key]);d.field(title,fields[key])
        d.actions.addWidget(button('Сохранить',lambda:d.run_action(lambda:self.store.set_notification_settings(self.user,**{key:field.value() for key,field in fields.items()})),'primary','check'))
        d.exec()
