import math
from datetime import date,datetime
from PySide6.QtCore import Qt,QDate,QTimer,Signal
from PySide6.QtGui import QPainter,QColor,QPen
from PySide6.QtWidgets import (QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFrame,
    QScrollArea,QLineEdit,QButtonGroup,QLabel,QDateEdit,QProgressBar,QSizePolicy,
    QFileDialog,QMessageBox,QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView)
from app.widgets import label,button,brand,card,row,avatar,tag,CardGrid,Sheet,DatePicker
from app.store import ROLES,STATUS,EMPLOYEE_STATUS
from app.dialogs import CreateTask,TaskDetails,ReviewReport,AddUser,EditShift,combo
from app.integrations import INTEGRATION_AREAS


def fmt_time(n):return f'{int(n):02d}:{int(round(n%1*60)):02d}'
def tone(status):return 'success' if status=='approved' else 'urgent' if status=='revision' else 'neutral' if status in ('cancelled','paused','available') else 'purple'
def score_text(n):return '—' if n is None else f'{n:.1f}'


class LoginWindow(QMainWindow):
    logged_in=Signal(dict)
    def __init__(self,store):
        super().__init__();self.store=store;self.setWindowTitle('НарядAI · Вход');self.resize(1140,800);self.setMinimumSize(930,740)
        host=QWidget();layout=QHBoxLayout(host);layout.setContentsMargins(36,36,36,36);layout.setSpacing(56)
        story,l=card('story',36);story.setMinimumWidth(450);l.addWidget(brand());l.addStretch()
        l.addWidget(label('ALLUR · Производственная смена','',True))
        l.addWidget(label('Ваша смена.\nВсё по плану.','heading',True))
        l.addWidget(label('Выбирайте задачи, планируйте время\nи делитесь результатами работы.','muted',True))
        steps,s=card('storySteps',22);s.addWidget(label('Рабочий день под контролем','title'))
        for i,(title,sub) in enumerate([('Выбрать наряд на участке','Сборка, сварка, окраска и контроль'),
                                       ('Выполнить и отправить отчёт','Работы, время, материалы и фото'),
                                       ('Получить обратную связь','Комментарий и оценка мастера')],1):
            s.addWidget(label(f'{i:02d}  {title}','',True));s.addWidget(label(sub,'muted',True))
        l.addWidget(steps);l.addStretch();l.addWidget(label('Демонстрационная версия · ручная проверка','muted'))
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
        f.addWidget(label('Пароль'));self.password=QLineEdit('1234');self.password.setObjectName('password');self.password.setEchoMode(QLineEdit.EchoMode.Password);f.addWidget(self.password)
        self.error=label('','',True);self.error.setStyleSheet('color:#ac4264;');self.error.hide();f.addWidget(self.error)
        self.enter=button('Войти',self.login,'primary');self.enter.setObjectName('primary');self.enter.setDefault(True);f.addWidget(self.enter)
        self.password.returnPressed.connect(self.login);self.username.returnPressed.connect(self.login)
        f.addWidget(label('Тестовые аккаунты: master, worker1–worker4, admin.\nПароль для всех: 1234.','muted',True));f.addStretch()
        layout.addWidget(form,1);self.setCentralWidget(host)
    def choose_role(self,role):
        self.role=role;self.username.setText({'worker':'worker1','master':'master','admin':'admin'}[role]);self.error.hide()
    def login(self):
        try:self.logged_in.emit(self.store.authenticate(self.username.text(),self.password.text(),self.role))
        except (ValueError,PermissionError) as e:self.error.setText(str(e));self.error.show()


class Timeline(QWidget):
    def __init__(self,tasks,open_task,shift=None):
        super().__init__();self.first=math.floor(shift['start']) if shift else 8
        self.last=math.ceil(shift['end']) if shift else 18
        self.setMinimumHeight((self.last-self.first)*80+50);self.events=[]
        for t in tasks:
            if t['start'] is None:continue
            b=button(fmt_time(t['start'])+'–'+fmt_time(t['start']+t['duration'])+'  ·  '+STATUS[t['status']]+'\n'+t['title'],lambda tid=t['id']:open_task(tid))
            b.setParent(self);b.setToolTip(t['title']);b.setStyleSheet('text-align:left;background:#eeedff;color:#514475;border:1px solid #dedaef;border-left:4px solid #7970dc;border-radius:12px;padding:8px 12px;')
            self.events.append((t,b))
    def resizeEvent(self,e):
        for t,b in self.events:
            b.setGeometry(62,int((t['start']-self.first)*80+4),max(100,self.width()-76),max(25,int(t['duration']*80-8)))
        super().resizeEvent(e)
    def paintEvent(self,e):
        p=QPainter(self);p.setPen(QPen(QColor('#e8e6f0')))
        for i in range(self.last-self.first+1):
            y=i*80+2;p.drawLine(60,y,self.width()-12,y);p.setPen(QColor('#9992ae'));p.drawText(0,y+15,f'{i+self.first:02d}:00');p.setPen(QColor('#e8e6f0'))
        p.end()


class MainWindow(QMainWindow):
    logged_out=Signal()
    def __init__(self,store,user):
        super().__init__();self.store=store;self.user=user;self.setWindowTitle('НарядAI · Allur');self.resize(1360,900);self.setMinimumSize(1040,760)
        self.page_key='overview' if user['role']!='worker' else 'tasks'
        self.task_filter='available' if user['role']=='worker' else 'all';self.report_filter='submitted';self.query='';self.priority='all';self.schedule_day=QDate.currentDate()
        host=QWidget();outer=QHBoxLayout(host);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0)
        sidebar,self.side=card('sidebar',24);sidebar.setFixedWidth(244);self.side.setSpacing(8)
        self.side.addWidget(brand());self.side.addSpacing(16);self.side.addWidget(label('ALLUR','title'));self.side.addWidget(label('Производственная смена','muted'));self.side.addSpacing(22)
        self.side.addWidget(label(ROLES[user['role']].upper(),'muted'));self.side.addSpacing(6)
        self.nav={}
        items=[('overview','grid','Смена'),('tasks','tasks','Наряды'),('reports','report','Отчёты'),('team','team','Команда'),('team_schedule','calendar','График команды'),('costs','chart','Материалы')]
        if user['role']=='worker':items=[('tasks','tasks','Задачи'),('schedule','calendar','График'),('reports','report','Отчёты'),('profile','user','Профиль')]
        elif user['role']=='admin':items += [('users','shield','Пользователи'),('integrations','spark','Подключения')]
        for key,ico,title in items:
            b=button(title,lambda k=key:self.navigate(k),'nav',ico);b.setCheckable(True);self.nav[key]=b;self.side.addWidget(b)
        if user['role'] in ('master','admin'):
            self.create_button=button('Создать наряд',self.create_task,'primary','plus');self.side.addWidget(self.create_button)
        self.side.addStretch();self.side.addWidget(label('Поддержка и полный доступ' if user['role']=='admin' else 'Демонстрационная версия','muted',True))
        account=row(avatar(user['name']),label(user['name'].split()[0]+'\n'+ROLES[user['role']],'muted'));self.side.addLayout(account)
        self.side.addWidget(button('Выйти',self.logged_out.emit,'nav','logout'));outer.addWidget(sidebar)
        content=QWidget();c=QVBoxLayout(content);c.setContentsMargins(0,0,0,0);c.setSpacing(0)
        top=QFrame();top.setObjectName('topbar');top.setFixedHeight(86);tl=QHBoxLayout(top);tl.setContentsMargins(34,0,34,0)
        tl.addWidget(label('ALLUR  ·  Производственная смена','muted'));tl.addStretch();tl.addWidget(tag(ROLES[user['role']]))
        self.bell=button('Уведомления',self.notifications,ico='bell');tl.addWidget(self.bell);tl.addWidget(avatar(user['name']))
        c.addWidget(top);self.scroll=QScrollArea();self.scroll.setWidgetResizable(True);c.addWidget(self.scroll,1)
        outer.addWidget(content,1);self.setCentralWidget(host)
        self.search_timer=QTimer(self);self.search_timer.setSingleShot(True);self.search_timer.setInterval(180);self.search_timer.timeout.connect(self.filter_cards)
        self.refresh_timer=QTimer(self);self.refresh_timer.setInterval(15000);self.refresh_timer.timeout.connect(self.refresh_if_idle);self.refresh_timer.start()
        self.render()
    def refresh_if_idle(self):
        from PySide6.QtWidgets import QApplication
        if QApplication.activeModalWidget():return
        if self.page_key not in ('tasks','users'):
            old_signature=self.refresh_signature
            try:self.load()
            except PermissionError:
                self.render();return
            if self.refresh_signature!=old_signature:
                scroll_value=self.scroll.verticalScrollBar().value()
                self.render()
                QTimer.singleShot(0,lambda:self.scroll.verticalScrollBar().setValue(scroll_value))
    def navigate(self,key):
        if key not in self.nav:return
        self.page_key=key;self.query='';self.render()
    def load(self):
        self.tasks=self.store.tasks(self.user);self.reports=self.store.reports(self.user)
        people=self.store.users(self.user,True) if self.user['role']!='worker' else [self.user]
        shifts=[self.store.shift(self.user,p['id'],self.schedule_day.toString('yyyy-MM-dd')) for p in people]
        self.refresh_signature=repr((self.tasks,self.reports,shifts,datetime.now().strftime('%Y%m%d%H%M')))
    def render(self):
        try:self.load()
        except PermissionError:
            QMessageBox.information(self,'Доступ','Аккаунт отключён.');self.logged_out.emit();return
        for k,b in self.nav.items():b.setChecked(k==self.page_key)
        count=sum(r['status']==('revision' if self.user['role']=='worker' else 'submitted') for r in self.reports)
        self.bell.setText(f'Уведомления · {count}' if count else 'Уведомления')
        page=QWidget();page.setMaximumWidth(1220);self.body=QVBoxLayout(page);self.body.setContentsMargins(36,32,36,30);self.body.setSpacing(23)
        methods={'overview':self.overview,'tasks':self.tasks_page,'reports':self.reports_page,'team':self.team_page,
                 'schedule':self.schedule_page,'team_schedule':self.team_schedule_page,'profile':self.profile_page,'costs':self.costs_page,'users':self.users_page,'integrations':self.integrations_page}
        methods[self.page_key]();self.body.addStretch();self.body.addWidget(label('ALLUR · НарядAI · Демонстрационная версия','muted'))
        old=self.scroll.takeWidget()
        if old:old.deleteLater()
        self.scroll.setWidget(page)
    def heading(self,title,subtitle,action=None):
        w=QWidget();l=QHBoxLayout(w);l.setContentsMargins(0,0,0,0)
        left=QVBoxLayout();left.addWidget(label('ALLUR · '+ROLES[self.user['role']],'eyebrow'));left.addWidget(label(title,'heading'));left.addWidget(label(subtitle,'muted',True));l.addLayout(left,1)
        if action:l.addWidget(action)
        else:l.addWidget(tag(date.today().strftime('%d.%m.%Y')))
        self.body.addWidget(w)
    def empty(self,title,sub):
        w,l=card();l.addWidget(label(title,'section',True));l.addWidget(label(sub,'muted',True));return w
    def stats(self,items):
        l=QHBoxLayout();l.setSpacing(16)
        for value,title in items:
            w,c=card('stat');c.addWidget(label(value,'number'));c.addWidget(label(title,'muted',True));l.addWidget(w,1)
        self.body.addLayout(l)
    def task_card(self,t):
        w,l=card();w.setMinimumWidth(300)
        l.addLayout(row(label(f"НР-{t['id']}",'muted'),tag('Срочный','urgent') if t['priority']=='urgent' else tag(STATUS[t['status']],tone(t['status']))))
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
        l.addWidget(label(r['title'],'title',True));l.addWidget(label(r['worker_name']+' · '+f"{r['hours']:g} ч",'muted'))
        bottom=row(label(f"{r['score']} / 100" if r['score'] is not None else 'Ожидает проверки' if r['status']=='submitted' else 'Без оценки','title'),button('Проверить' if r['status']=='submitted' and self.user['role']!='worker' else 'Открыть',lambda:self.open_report(r['id']),'secondary'))
        l.addLayout(bottom);return w
    def overview(self):
        self.heading('Обзор смены','Задачи, результаты и команда в одном месте',button('Создать наряд',self.create_task,'primary','plus'))
        pending=[r for r in self.reports if r['status']=='submitted']
        hero,l=card('hero',28);l.addWidget(label('НУЖНА ВАША ПРОВЕРКА','muted'));l.addWidget(label(f'{len(pending)} отчёта на проверке','heading'))
        l.addWidget(label('Проверьте результаты и дайте сотрудникам обратную связь.','muted',True));b=button('Перейти к проверке',lambda:self.navigate('reports'),'secondary','report');b.setMaximumWidth(250);l.addWidget(b);self.body.addWidget(hero)
        approved=[r for r in self.reports if r['status']=='approved' and (r['reviewed'] or '').startswith(date.today().isoformat())]
        self.stats([(str(sum(t['status']=='available' for t in self.tasks)),'Доступно'),
                    (str(sum(t['status'] in ('planned','inProgress','paused','revision') for t in self.tasks)),'В плане / работе'),
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
                     button('Создать наряд',self.create_task,'primary','plus') if self.user['role']!='worker' else button('Обновить',self.render,ico='refresh'))
        if self.user['role']!='worker':
            refresh=button('Обновить список',self.render,ico='refresh');refresh.setMaximumWidth(220);self.body.addWidget(refresh)
        self.tabs([('available','Доступные'),('mine','Мои текущие'),('all','Все') ] if self.user['role']=='worker' else [('all','Все'),('available','Свободные'),('active','Текущие'),('approved','Принятые')],self.task_filter,self.change_task_filter)
        tools=QHBoxLayout();self.search=QLineEdit(self.query);self.search.setPlaceholderText('Поиск по номеру, названию, оборудованию или участку');self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.on_query);tools.addWidget(self.search,1)
        self.priority_box=combo([('Все приоритеты','all'),('Только срочные','urgent')]);self.priority_box.setCurrentIndex(1 if self.priority=='urgent' else 0)
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
        self.tabs([('submitted','На проверке'),('revision','Доработка'),('approved','Принятые'),('all','История')],self.report_filter,self.change_report_filter)
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
            self.render();self.statusBar().showMessage('Наряд назначен в график',5000)
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
        else:self.body.addWidget(self.empty('Назначенных работ нет','Выберите свободный наряд в разделе «Задачи».' if shift else 'Мастер может настроить рабочую смену.'))
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
        if d.exec():self.statusBar().showMessage('Пароль обновлён',5000)
    def add_user(self):
        if AddUser(self.store,self.user,self).exec():self.render();self.statusBar().showMessage('Аккаунт создан',5000)
    def toggle_user(self,u):
        try:self.store.set_active(self.user,u['id'],not u['active']);self.render()
        except (ValueError,PermissionError) as e:QMessageBox.information(self,'Пользователь',str(e))
    def integrations_page(self):
        self.heading('Подключения и модули','Управление дополнительными возможностями приложения')
        notice,l=card();l.addWidget(label('Модели пока не выбраны','section'))
        l.addWidget(label('Здесь можно будет подключать локальные модели или внешние сервисы. Конкретные модели и их задачи определим позже.','muted',True))
        self.body.addWidget(notice)
        for title,description in INTEGRATION_AREAS:
            w,l=card();l.addLayout(row(label(title,'section'),tag('Нет подключения','neutral')))
            l.addWidget(label(description,'muted',True));self.body.addWidget(w)
        self.body.addWidget(label('Этот раздел доступен только администратору.','muted',True))
    def create_task(self):
        if CreateTask(self.store,self.user,self).exec():self.render();self.statusBar().showMessage('Наряд создан',5000)
    def open_task(self,tid):
        try:
            if TaskDetails(self.store,self.user,tid,self).exec():self.render();self.statusBar().showMessage('Изменения сохранены',5000)
        except (ValueError,PermissionError) as e:QMessageBox.information(self,'Наряд',str(e))
    def open_report(self,rid):
        # Всегда открываем свежие данные — другой пользователь мог уже проверить отчёт.
        r=next((r for r in self.store.reports(self.user) if r['id']==rid),None)
        if r and ReviewReport(self.store,self.user,r,self).exec():self.render();self.statusBar().showMessage('Решение сохранено',5000)
    def notifications(self):
        status='revision' if self.user['role']=='worker' else 'submitted'
        items=[r for r in self.store.reports(self.user) if r['status']==status]
        d=Sheet('Уведомления',self)
        if not items:d.body.addWidget(label('Новых уведомлений пока нет','section'))
        for r in items:
            d.body.addWidget(label(r['worker_name'],'muted'));d.body.addWidget(button(r['title'],lambda rid=r['id']:self.open_report(rid),'secondary'))
        d.exec()
    def export_reports(self):
        p,_=QFileDialog.getSaveFileName(self,'Экспорт отчётов','NaryadAI_reports.csv','CSV (*.csv)')
        if p:
            if not p.lower().endswith('.csv'):p+='.csv'
            try:self.store.export_reports(self.user,p);self.statusBar().showMessage('Отчёты экспортированы',5000)
            except OSError as e:QMessageBox.warning(self,'Экспорт',str(e))
