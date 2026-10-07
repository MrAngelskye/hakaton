from datetime import date
from PySide6.QtCore import Qt,QDate,QDateTime,QTime,QUrl
from PySide6.QtGui import QPixmap,QDesktopServices
from PySide6.QtWidgets import (QLineEdit,QTextEdit,QComboBox,QDoubleSpinBox,QSpinBox,QDateEdit,
    QDateTimeEdit,QTimeEdit,QInputDialog,QTableWidget,QTableWidgetItem,QHeaderView,QFileDialog,QAbstractItemView)
from app.drafts import ReportDraft
from app.voice_input import ReportVoiceInput
from app.store import STATUS,SITES,ROLES
from app.case_store import PRIORITIES
from app.widgets import (Sheet,label,button,row,card,tag,DatePicker,TimePicker,DateTimePicker,
    NoWheelDoubleSpinBox,NoWheelSpinBox,NoWheelComboBox)


def combo(items):
    w=NoWheelComboBox()
    for text,data in items:w.addItem(text,data)
    return w


def number(value,low=.5,high=10,step=.5):
    w=NoWheelDoubleSpinBox();w.setRange(low,high);w.setSingleStep(step);w.setValue(value);return w


def time_value(w):
    t=w.time();return t.hour()+t.minute()/60


class CreateTask(Sheet):
    def __init__(self,store,user,parent,assignment=None):
        super().__init__('Исправление наряда' if hasattr(self,'t') else 'Новый наряд',parent);self.store=store;self.user=user
        self.catalogs=store.catalogs(user);self.photo_sources=[]
        self.title=self.field('Название задачи *',QLineEdit());self.title.setMaxLength(120)
        self.description=self.field('Описание работ *',QTextEdit());self.description.setFixedHeight(105)
        self.site=self.field('Участок',combo([(s['name'],s['name']) for s in self.catalogs['sites']]))
        self.equipment=self.field('Оборудование *',combo([]))
        self.site.currentIndexChanged.connect(self.update_equipment);self.update_equipment()
        self.priority=self.field('Приоритет',combo([(name,key) for key,name in PRIORITIES.items()]))
        self.priority.setCurrentIndex(self.priority.findData('normal'))
        self.kind=self.field('Тип работ',combo([('Плановая','Плановая'),('Внеплановая','Внеплановая')]))
        self.duration=self.field('Плановое время, ч',number(1))
        self.norm=self.field('Норматив',combo([('Без норматива',None)]+[(n['equipment_type']+' · '+n['kind']+f" · {n['hours']} ч",n['id']) for n in self.catalogs['work_norms'] if n['active']]))
        self.complexity=self.field('Сложность',number(1,.1,10,.1))
        def norm_changed():
            n=next((x for x in self.catalogs['work_norms'] if x['id']==self.norm.currentData()),None)
            if n:self.duration.setValue(n['hours']);self.complexity.setValue(n['complexity']);self.kind.setCurrentIndex(self.kind.findData(n['kind']))
        self.norm.currentIndexChanged.connect(norm_changed)
        people=[u for u in store.users(user,True) if u['active']]
        self.worker=self.field('Исполнитель',combo([('Свободный наряд — сотрудник выберет сам',None)]+[(u['name'],u['id']) for u in people]))
        self.brigade=self.field('Бригада (необязательно)',combo([('Индивидуальное назначение',None)]+[(b['name'],b['id']) for b in self.catalogs['brigades']]))
        self.before_label=label('Фото до ремонта не добавлены','muted',True);self.body.addWidget(self.before_label)
        self.body.addWidget(button('Добавить фото до ремонта',self.add_before_photos,'secondary','camera'))
        self.day=DatePicker(QDate.currentDate())
        self.field('День работ',self.day)
        self.start=TimePicker(QTime(8,0));self.field('Начало при назначении сотруднику',self.start)
        self.deadline=DateTimePicker(QDateTime(QDate.currentDate(),QTime(18,0)));self.field('Срок выполнения',self.deadline)
        if assignment:
            wid,day,start,end=assignment
            self.worker.setCurrentIndex(self.worker.findData(wid));self.day.setDate(QDate.fromString(day,'yyyy-MM-dd'))
            self.start.setTime(QTime(int(start),round(start%1*60)))
            self.duration.setValue(min(1,end-start))
            self.deadline.setDateTime(QDateTime(self.day.date(),QTime(int(end),round(end%1*60))))
            self.body.addWidget(label(f'Выбрано свободное время: {self.start.time().toString("HH:mm")}–{QTime(int(end),round(end%1*60)).toString("HH:mm")}','muted',True))
        self.actions.addWidget(button('Отмена',self.reject));self.actions.addWidget(button('Создать наряд',self.save,'primary','plus'))
    def save(self):
        self.run_action(lambda:self.store.create_task(self.user,title=self.title.text(),description=self.description.toPlainText(),
            site=self.site.currentData(),equipment=self.equipment.currentText(),equipment_id=self.equipment.currentData(),priority=self.priority.currentData(),kind=self.kind.currentData(),
            duration=self.duration.value(),day=self.day.date().toString('yyyy-MM-dd'),start=time_value(self.start),
            deadline=self.deadline.dateTime().toString('yyyy-MM-ddTHH:mm'),worker_id=self.worker.currentData(),brigade_id=self.brigade.currentData(),norm_id=self.norm.currentData(),complexity=self.complexity.value(),photo_sources=self.photo_sources))

    def update_equipment(self):
        self.equipment.clear()
        sid=next((x['id'] for x in self.catalogs['sites'] if x['name']==self.site.currentData()),None)
        for e in self.catalogs['equipment']:
            if e['site_id']==sid:self.equipment.addItem(e['name']+' · '+e['inventory_number'],e['id'])
    def add_before_photos(self):
        paths,_=QFileDialog.getOpenFileNames(self,'Фото до ремонта','','Фото (*.jpg *.jpeg *.png *.webp)')
        selected=list(dict.fromkeys(self.photo_sources+paths))
        if len(selected)>5:self.fail('До 5 фото до ремонта.');return
        self.photo_sources=selected;self.before_label.setText('Фото до ремонта: '+str(len(selected)))


class TaskDetails(Sheet):
    def __init__(self,store,user,tid,parent):
        t=store.task(user,tid);super().__init__(f'Наряд НР-{tid}',parent)
        self.body.addLayout(row(tag(STATUS[t['status']]),tag(PRIORITIES[t['priority']],'urgent' if t['priority']=='urgent' else 'neutral')))
        self.body.addWidget(label(t['title'],'heading',True));self.body.addWidget(label(t['description'],'',True))
        for k,v in [('Оборудование',t['equipment']),('Участок',t['site']),('Исполнитель',t['worker_name'] or 'Не назначен'),
                    ('Плановое время',f"{t['duration']:g} ч"),('Срок',t['deadline'].replace('T',' · '))]:
            self.body.addWidget(label(k,'muted'));self.body.addWidget(label(v,'',True))
        latest=store.latest_report(user,tid)
        if t['status']=='paused':
            pause=store.pauses(user,tid)[-1]
            notice,l=card();l.addWidget(label('Причина приостановки','title'))
            l.addWidget(label(pause['reason'],'',True));l.addWidget(label('С '+pause['started'].replace('T',' '),'muted'))
            self.body.addWidget(notice)
        if latest and latest['status']=='revision':
            notice,l=card();l.addWidget(label('Комментарий мастера','title'));l.addWidget(label(latest['comment'],'',True));self.body.addWidget(notice)
        if user['role']=='worker' or (user['role']=='admin' and t['worker_id'] is not None):
            if t['status'] in ('available','planned'):
                self.day=DatePicker(QDate.fromString(t['day'],'yyyy-MM-dd'))
                self.field('День в графике',self.day)
                start=t['start'] or 8
                self.start=TimePicker(QTime(int(start)%24,int(round(start%1*60))));self.field('Начало работы',self.start)
                action=store.claim if t['status']=='available' else store.reschedule
                self.actions.addWidget(button('В график' if t['status']=='available' else 'Перенести',
                    lambda:self.run_action(lambda:action(user,tid,self.day.date().toString('yyyy-MM-dd'),time_value(self.start))),'secondary','calendar'))
            if t['worker_id']==user['id'] or user['id'] in t.get('member_ids',[]) or user['role']=='admin':
                if t['status']=='planned':
                    self.actions.addWidget(button('Принять',lambda:self.run_action(lambda:store.transition(user,tid,'accepted')),'primary','check'))
                    self.actions.addWidget(button('В очередь',lambda:self.run_action(lambda:store.transition(user,tid,'queued')),'secondary','clock'))
                    self.body.addWidget(button('Отклонить с причиной',lambda:self.reject_task(store,user,tid),'danger'))
                if t['status'] in ('accepted','queued','paused'):
                    self.actions.addWidget(button('Продолжить работу' if t['status']=='paused' else 'Начать работу',lambda:self.run_action(lambda:store.transition(user,tid,'inProgress')),'primary','play'))
                if t['status']=='inProgress':
                    self.actions.addWidget(button('Приостановить',lambda:self.pause(store,user,tid),'secondary','clock'))
                if t['status'] in ('inProgress','revision'):
                    self.actions.addWidget(button('Отправить отчёт',lambda:self.report(store,user,t,parent),'primary','report'))
        if user['role'] in ('master','admin') and t['status'] not in ('aiPending','submitted','approved','cancelled'):
            self.body.addWidget(button('Отменить наряд',lambda:self.cancel(store,user,tid),'danger'))
        if user['role']=='master' and t['status'] in ('planned','accepted','queued'):
            self.day=DatePicker(QDate.fromString(t['day'],'yyyy-MM-dd'));self.field('Новый день в графике',self.day)
            self.start=TimePicker(QTime(int(t['start']),round(t['start']%1*60)));self.field('Новое начало',self.start)
            self.actions.addWidget(button('Перенести',lambda:self.run_action(lambda:store.reschedule(user,tid,self.day.date().toString('yyyy-MM-dd'),time_value(self.start))),'secondary','calendar'))
        if user['role'] in ('master','admin'):
            self.body.addWidget(button('Изменить приоритет',lambda:self.manage_priority(store,user,t),'secondary','edit'))
            if t['status'] in ('available','planned','accepted','queued','rejected','inProgress','paused','revision'):
                self.body.addWidget(button('Переназначить',lambda:self.reassign(store,user,t),'secondary','team'))
            self.body.addWidget(button('Начать простой оборудования',lambda:self.downtime(store,user,t),'secondary','clock'))
            for downtime in store.task_downtimes(user,tid):
                if not downtime['ended_at']:
                    self.body.addWidget(label('Открытый простой: '+downtime['reason'],'warning',True))
                    self.body.addWidget(button('Завершить простой оборудования',lambda did=downtime['id']:self.run_action(lambda:store.end_downtime(user,did)),'secondary','check'))
            self.body.addWidget(label('Инструменты поддержки','section'))
            self.body.addWidget(label('Действия администратора записываются в историю наряда.','muted',True))
            if t['status'] in ('available','planned','accepted','queued','rejected'):
                self.body.addWidget(button('Исправить наряд',lambda:self.support(store,user,t,parent),'secondary','edit'))
        if latest:
            self.body.addWidget(button('Открыть последний отчёт',lambda:self.show_report(store,user,latest,parent),'secondary','report'))
        self.body.addWidget(label('История наряда','section'))
        for e in store.events(user,tid):
            self.body.addWidget(label(e['created'].replace('T',' ')+' · '+e['name'],'muted',True))
            self.body.addWidget(label(e['message'],'',True))
    def reject_task(self,store,user,tid):
        reason,ok=QInputDialog.getMultiLineText(self,'Отказ','Причина отказа:')
        if ok:self.run_action(lambda:store.transition(user,tid,'rejected',reason))
    def manage_priority(self,store,user,t):
        d=Sheet('Изменить приоритет',self);p=d.field('Приоритет',combo([(name,key) for key,name in PRIORITIES.items()]));reason=d.field('Причина',QLineEdit())
        d.actions.addWidget(button('Сохранить',lambda:d.run_action(lambda:store.change_priority(user,t['id'],p.currentData(),reason.text())),'primary'))
        if d.exec():self.accept()
    def reassign(self,store,user,t):
        d=Sheet('Переназначить наряд',self);people=store.users(user,True);catalog=store.catalogs(user)
        p=d.field('Ведущий исполнитель',combo([('Автоматически для бригады',None)]+[(x['name'],x['id']) for x in people if x['active']]))
        b=d.field('Бригада',combo([('Индивидуально',None)]+[(x['name'],x['id']) for x in catalog['brigades']]))
        day=d.field('День начала смены',DatePicker(QDate.fromString(t['day'],'yyyy-MM-dd')));start=d.field('Начало',TimePicker(QTime(int(t['start'] or 8)%24,0)));reason=d.field('Причина',QLineEdit())
        d.actions.addWidget(button('Переназначить',lambda:d.run_action(lambda:store.reassign_task(user,t['id'],p.currentData(),day.date().toString('yyyy-MM-dd'),time_value(start),reason.text(),brigade_id=b.currentData())),'primary'))
        if d.exec():self.accept()
    def downtime(self,store,user,t):
        reason,ok=QInputDialog.getMultiLineText(self,'Простой оборудования','Причина простоя (отдельно от паузы работника):')
        if ok:self.run_action(lambda:store.start_downtime(user,t['id'],reason))
    def pause(self,store,user,tid):
        if PauseTask(store,user,tid,self).exec():self.accept()
    def support(self,store,user,t,parent):
        if SupportTask(store,user,t,parent).exec():self.accept()
    def report(self,store,user,t,parent):
        d=SubmitReport(store,user,t,parent)
        if d.exec():self.accept()
    def show_report(self,store,user,r,parent):
        if ReviewReport(store,user,r,parent).exec():self.accept()
    def cancel(self,store,user,tid):
        from PySide6.QtWidgets import QMessageBox
        if QMessageBox.question(self,'Отмена наряда','Отменить этот наряд? История останется.',
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            self.run_action(lambda:store.transition(user,tid,'cancelled'))


class PauseTask(Sheet):
    def __init__(self,store,user,tid,parent):
        super().__init__('Приостановить работу',parent);self.store=store;self.user=user;self.tid=tid
        self.cause=self.field('Причина',combo([(v,v) for v in ['Ожидание материалов','Неисправность оборудования','Нужна помощь мастера','Другое']]))
        self.reason=self.field('Что произошло? *',QTextEdit());self.reason.setFixedHeight(115)
        self.body.addWidget(label('Опишите причину. Мастер увидит её в наряде; время паузы сохранится в истории.','muted',True))
        self.actions.addWidget(button('Отмена',self.reject));self.actions.addWidget(button('Приостановить',self.save,'primary','clock'))
    def save(self):
        def action():
            text=self.reason.toPlainText().strip()
            if not 3<=len(text)<=900:raise ValueError('Добавьте пояснение от 3 до 900 символов.')
            self.store.transition(self.user,self.tid,'paused',self.cause.currentData()+': '+text)
        self.run_action(action)


class EditShift(Sheet):
    def __init__(self,store,user,worker,day,parent):
        super().__init__('Смена · '+worker['name'],parent);self.store=store;self.user=user;self.worker=worker;self.day=day
        shift=store.shift(user,worker['id'],day)
        self.body.addWidget(label('Дата: '+QDate.fromString(day,'yyyy-MM-dd').toString('dd.MM.yyyy'),'title'))
        self.mode=self.field('Режим',combo([('Рабочая смена','work'),('Не на смене / выходной','off')]))
        if not shift:self.mode.setCurrentIndex(1)
        a,b=(shift['start'],shift['end']) if shift else (8,18)
        self.start=self.field('Начало смены',TimePicker(QTime(int(a),round(a%1*60))))
        self.end=self.field('Конец смены',TimePicker(QTime(int(b)%24,round(b%1*60))))
        self.mode.currentIndexChanged.connect(self.update_fields);self.update_fields()
        self.body.addWidget(label('Изменение действует на выбранную дату. Назначенные наряды должны помещаться в смену.','muted',True))
        self.actions.addWidget(button('Отмена',self.reject));self.actions.addWidget(button('Сохранить смену',self.save,'primary','calendar'))
    def update_fields(self):
        enabled=self.mode.currentData()=='work';self.start.setEnabled(enabled);self.end.setEnabled(enabled)
    def save(self):
        self.run_action(lambda:self.store.set_shift(self.user,self.worker['id'],self.day,
            time_value(self.start) if self.mode.currentData()=='work' else None,
            time_value(self.end) if self.mode.currentData()=='work' else None))


class SubmitReport(Sheet):
    def __init__(self,store,user,t,parent):
        super().__init__('Отчёт о выполнении',parent);self.store=store;self.user=user;self.t=t
        self.body.addWidget(label(f"НР-{t['id']} · {t['title']}",'section',True))
        if user['role']=='admin':self.body.addWidget(label('Поддержка: отчёт за сотрудника '+(t['worker_name'] or '')+'. Автор действия будет указан в истории.','muted',True))
        old=store.latest_report(user,t['id']) if t['status']=='revision' else None
        if old and hasattr(store,'ensure_photos'):store.ensure_photos(old)
        if old:self.body.addWidget(label('Нужна доработка: '+old['comment'],'',True))
        self.work=self.field('Выполненные работы *',QTextEdit());self.work.setFixedHeight(110)
        self.result_text=self.field('Результат контрольной проверки *',QTextEdit());self.result_text.setFixedHeight(85)
        self.voice=ReportVoiceInput([('Выполненные работы',self.work),('Результат проверки',self.result_text)],self)
        self.body.addWidget(self.voice);self.finished.connect(self.voice.dispose)
        self.defect=self.field('Дефект',combo([(d['code']+' · '+d['name'],d['code']) for d in store.catalogs(user)['defect_codes']]))
        self.hours=self.field('Фактическое время, ч',number(t['duration'],.1,24,.1))
        self.body.addWidget(label('Материалы и стоимость','section'))
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['Материал','Кол-во','Ед.','Цена, тг'])
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        for i in (1,2,3):self.table.setColumnWidth(i,100)
        self.table.setMinimumHeight(160);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.body.addWidget(self.table)
        self.body.addLayout(row(button('Добавить материал',self.add_material,'secondary','plus'),button('Удалить строку',self.remove_material)))
        self.photo_sources=[];self.photo_box,self.photo_layout=card();self.body.addWidget(label('Фото результата','section'))
        self.body.addWidget(button('Добавить фото',self.add_photos,'secondary','camera'));self.body.addWidget(self.photo_box)
        self.body.addWidget(label('До 5 фото · JPG, PNG, WebP · до 8 МБ каждое','muted',True))
        if old:
            self.work.setPlainText(old['work']);self.result_text.setPlainText(old['result']);self.defect.setCurrentText(old['defect']);self.hours.setValue(old['hours'])
            for m in old['materials']:self.add_material(m)
            self.photo_sources=[str(store.photos/p) for p in old['photos'] if (store.photos/p).is_file()]
        self.draft=ReportDraft(store,user,t['id'])
        saved=self.draft.load()
        if saved:
            self.work.setPlainText(saved.get('work',''));self.result_text.setPlainText(saved.get('result',''));self.hours.setValue(saved.get('hours',t['duration']))
            self.defect.setCurrentIndex(max(0,self.defect.findText(saved.get('defect',''))));self.table.setRowCount(0)
            for material in saved.get('materials',[]):self.add_material(material)
            self.photo_sources=[p for p in saved.get('photo_sources',[]) if __import__('pathlib').Path(p).is_file()]
            self.body.addWidget(label('Восстановлен черновик этого наряда','muted',True))
        self.refresh_photos()
        self.actions.addWidget(button('Сохранить черновик',self.save_draft,'secondary'))
        self.work.textChanged.connect(self.persist_draft);self.result_text.textChanged.connect(self.persist_draft);self.hours.valueChanged.connect(self.persist_draft);self.defect.currentIndexChanged.connect(self.persist_draft)
        self.table.itemChanged.connect(self.persist_draft);self.finished.connect(lambda _:self.persist_draft() if not getattr(self,'submitted',False) else None)
        self.body.addWidget(label('На сервере отчёт сначала проверит ИИ, если он включён; окончательное решение принимает мастер.' if getattr(store,'is_remote',False) else 'Отчёт поступит мастеру для ручной проверки.','muted',True))
        self.actions.addWidget(button('Отмена',self.reject));self.actions.addWidget(button('Отправить мастеру',self.save,'primary','report'))
    def persist_draft(self,*_):
        if not hasattr(self,'draft') or getattr(self,'submitted',False):return
        materials=[]
        for n in range(self.table.rowCount()):
            widget=self.table.cellWidget(n,0)
            if widget is None:continue
            item={'name':widget.currentText()}
            for column,key in [(1,'quantity'),(2,'unit'),(3,'price')]:item[key]=self.table.item(n,column).text() if self.table.item(n,column) else ''
            materials.append(item)
        try:self.draft.save({'work':self.work.toPlainText(),'result':self.result_text.toPlainText(),'defect':self.defect.currentText(),'hours':self.hours.value(),'materials':materials,'photo_sources':self.photo_sources})
        except OSError as e:self.fail('Не удалось сохранить черновик: '+str(e))
    def save_draft(self):
        if self.voice.has_unapplied():self.fail('Добавьте распознанный текст в отчёт или отмените диктовку перед сохранением.');return
        self.persist_draft();self.reject()

    def add_material(self,m=None):
        m=m if isinstance(m,dict) else {'name':'','quantity':1,'unit':'шт.','price':0}
        n=self.table.rowCount();self.table.insertRow(n);materials=self.store.catalogs(self.user)['materials']
        choices=combo([(x['name'],x['id']) for x in materials]);choices.setEditable(True);self.table.setCellWidget(n,0,choices)
        self.table.setItem(n,1,QTableWidgetItem(str(m['quantity'])))
        def changed():
            row=next((i for i in range(self.table.rowCount()) if self.table.cellWidget(i,0) is choices),None)
            if row is None:return
            material=next((x for x in materials if x['name']==choices.currentText()),None)
            for column,value in [(2,material['unit'] if material else m.get('unit','шт.')),(3,material['unit_price'] if material else m.get('price',0))]:
                item=QTableWidgetItem(str(value))
                if material:item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row,column,item)
        choices.currentTextChanged.connect(changed)
        old=next((i for i,x in enumerate(materials) if x['name']==m['name']),-1);choices.setCurrentIndex(old);choices.setEditText(m['name']);changed()
    def remove_material(self):
        if self.table.currentRow()>=0:self.table.removeRow(self.table.currentRow());self.persist_draft()
    def add_photos(self):
        paths,_=QFileDialog.getOpenFileNames(self,'Выберите фото','','Фото (*.jpg *.jpeg *.png *.webp)')
        selected=list(dict.fromkeys(self.photo_sources+paths))
        if len(selected)>5:self.fail('Выберите не больше 5 фото.');return
        if any(QPixmap(p).isNull() for p in paths):self.fail('Один из файлов не удалось открыть как фото.');return
        self.photo_sources=selected;self.refresh_photos();self.persist_draft()
    def refresh_photos(self):
        while self.photo_layout.count():
            item=self.photo_layout.takeAt(0)
            if item.widget():item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    child=item.layout().takeAt(0)
                    if child.widget():child.widget().deleteLater()
        if not self.photo_sources:self.photo_layout.addWidget(label('Фото ещё не добавлены','muted'))
        for p in self.photo_sources:
            w=label('');w.setPixmap(QPixmap(p).scaled(100,74,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
            line=row(w,button('Убрать',lambda path=p:self.remove_photo(path)))
            self.photo_layout.addLayout(line)
    def remove_photo(self,p):self.photo_sources.remove(p);self.refresh_photos();self.persist_draft()
    def save(self):
        if self.voice.has_unapplied():self.fail('Добавьте распознанный текст в отчёт или отмените диктовку перед отправкой.');return
        def action():
            materials=[]
            for n in range(self.table.rowCount()):
                vals=[self.table.item(n,i).text().strip() if self.table.item(n,i) else '' for i in range(4)]
                try:materials.append({'material_id':next((x['id'] for x in self.store.catalogs(self.user)['materials'] if x['name']==self.table.cellWidget(n,0).currentText()),None),'name':self.table.cellWidget(n,0).currentText(),'quantity':float(vals[1].replace(',','.')),'unit':vals[2],'price':float(vals[3].replace(',','.'))})
                except ValueError:raise ValueError(f'Проверьте количество и цену в строке {n+1}.')
            self.store.submit(self.user,self.t['id'],work=self.work.toPlainText(),result=self.result_text.toPlainText(),
                defect=self.defect.currentText(),hours=self.hours.value(),materials=materials,photo_sources=self.photo_sources)
            self.submitted=True;self.draft.clear()
        self.run_action(action)


class ReviewReport(Sheet):
    def __init__(self,store,user,r,parent):
        super().__init__(f"Отчёт ОТ-{r['id']:04d}",parent);self.store=store;self.user=user;self.r=r
        if hasattr(store,'ensure_photos'):store.ensure_photos(r)
        self.body.addLayout(row(tag(STATUS[r['status']]),label(f"НР-{r['task_id']}",'muted')))
        if r.get('photo_issues'):
            self.body.addWidget(label('Проверка фото: '+', '.join(x['code'] for x in r['photo_issues']),'warning',True))
        ai=r.get('ai')
        if ai:
            w,l=card();l.addWidget(label('Предварительная проверка ИИ','section'))
            if ai['status']=='completed':
                verdict={'acceptable':'Существенных замечаний нет','needs_clarification':'Нужны уточнения','insufficient_data':'Недостаточно данных'}
                l.addWidget(label(f"Оценка ИИ: {ai['score']} / 100",'title'));l.addWidget(label(verdict[ai['verdict']],'muted',True))
                l.addWidget(label(ai['summary'],'',True))
                for finding in ai['findings']:l.addWidget(label('• '+finding,'',True))
                names={'description':'Описание работ','matching':'Соответствие наряду','verification':'Контрольная проверка','materials_time':'Материалы и время'}
                for key,value in ai['criteria'].items():l.addWidget(label(names[key]+f': {value}','muted'))
                l.addWidget(label('Модель: '+ai['model'],'muted',True))
            elif ai['status'] in ('queued','processing'):l.addWidget(label('Модель обрабатывает отчёт. Он поступит мастеру после проверки.','muted',True))
            else:l.addWidget(label(ai.get('error') or 'ИИ выключен. Отчёт проверяет мастер.','muted',True))
            l.addWidget(label('Оценка ИИ рекомендательная. В рейтинг входит только оценка мастера.','muted',True));self.body.addWidget(w)
        self.body.addWidget(label(r['title'],'heading',True));self.body.addWidget(label(r['worker_name']+' · '+r['created'].replace('T',' '),'muted',True))
        for title,text in [('Оборудование',r['equipment']+' · '+r['site']),('Выполненные работы',r['work']),
                           ('Результат',r['result']),('Дефект',r['defect']),('Фактическое время',f"{r['hours']:g} ч")]:
            self.body.addWidget(label(title,'muted'));self.body.addWidget(label(text,'',True))
        self.body.addWidget(label('Материалы','section'))
        for m in r['materials']:
            self.body.addWidget(label(f"{m['name']} · {m['quantity']:g} {m['unit']} × {m['price']:,.2f} тг",'',True))
        total=sum(m['quantity']*m['price'] for m in r['materials'])
        self.body.addWidget(label(f'Итого: {total:,.2f} тг' if r['materials'] else 'Материалы не использовались','title'))
        before=[p['object_key'] for p in store.photos_for_task(user,r['task_id']) if p['kind']=='before']
        if before and hasattr(store,'ensure_photos'):store.ensure_photos({'photos':before})
        self.body.addWidget(label('Фото до ремонта и результата','section'))
        for p in before+r['photos']:
            self.body.addWidget(label('До ремонта' if p in before else 'После ремонта','muted'))
            path=store.photos/p
            if path.is_file():
                w=label('');w.setPixmap(QPixmap(str(path)).scaled(530,260,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation));self.body.addWidget(w)
                self.body.addWidget(button('Открыть фото',lambda path=path:QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))))
            else:self.body.addWidget(label('Файл фото отсутствует','muted'))
        if not r['photos']:self.body.addWidget(label('Фото не приложены','muted'))
        if r['comment']:
            w,l=card();l.addWidget(label('Решение мастера','section'));l.addWidget(label(r['comment'],'',True))
            l.addWidget(label((r['reviewer_name'] or '')+(f" · {r['score']} / 100" if r['score'] is not None else ''),'muted'));self.body.addWidget(w)
        if user['role'] in ('master','admin') and r['status']=='submitted':
            self.score=NoWheelSpinBox();self.score.setRange(-1,100);self.score.setSpecialValueText('Выберите оценку');self.score.setValue(ai['score'] if ai and ai.get('status')=='completed' else -1)
            self.field('Ручная оценка мастера, 0–100',self.score)
            self.comment=self.field('Комментарий сотруднику *',QTextEdit());self.comment.setFixedHeight(90)
            self.actions.addWidget(button('Вернуть на доработку',lambda:self.decide(False),'danger'))
            self.actions.addWidget(button('Принять работу',lambda:self.decide(True),'primary','check'))
        else:self.actions.addWidget(button('Закрыть',self.reject))
    def decide(self,approve):
        if approve and self.score.value()<0:self.fail('Укажите итоговую оценку мастера.');return
        self.run_action(lambda:self.store.review(self.user,self.r['id'],approve,max(0,self.score.value()),self.comment.toPlainText()))


class AddUser(Sheet):
    def __init__(self,store,user,parent):
        super().__init__('Новый пользователь',parent);self.store=store;self.user=user
        self.username=self.field('Логин',QLineEdit());self.name=self.field('Имя и фамилия',QLineEdit())
        self.job=self.field('Должность / участок',QLineEdit());self.role=self.field('Роль',combo([(v,k) for k,v in ROLES.items()]))
        self.password=self.field('Пароль (от 4 символов)',QLineEdit());self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.actions.addWidget(button('Создать аккаунт',self.save,'primary','plus'))
    def save(self):
        self.run_action(lambda:self.store.add_user(self.user,self.username.text(),self.name.text(),self.job.text(),self.role.currentData(),self.password.text()))


class SupportTask(CreateTask):
    def __init__(self,store,user,t,parent):
        self.t=t
        super().__init__(store,user,parent)
        self.setWindowTitle('Поддержка · исправление наряда')
        self.title.setText(t['title']);self.description.setPlainText(t['description'])
        self.site.setCurrentText(t['site']);self.equipment.setCurrentIndex(self.equipment.findData(t['equipment_id']));self.brigade.setEnabled(False)
        self.priority.setCurrentIndex(self.priority.findData(t['priority']))
        self.kind.setCurrentText(t['kind']);self.duration.setValue(t['duration'])
        self.worker.setCurrentIndex(self.worker.findData(t['worker_id']))
        self.day.setDate(QDate.fromString(t['day'],'yyyy-MM-dd'))
        start=t['start'] if t['start'] is not None else 8
        self.start.setTime(QTime(int(start)%24,int(round(start%1*60))))
        self.deadline.setDateTime(QDateTime.fromString(t['deadline'],Qt.DateFormat.ISODate))
        # У начатой задачи меняем только описание, срок и приоритет.
        locked=t['status'] not in ('available','planned','accepted','queued','rejected')
        for w in (self.worker,self.day,self.start,self.duration):w.setEnabled(not locked)
        self.reason=self.field('Причина исправления *',QLineEdit())
        self.body.addWidget(label('После сохранения исправление появится в истории наряда.','muted',True))
        while self.actions.count():
            item=self.actions.takeAt(0)
            if item.widget():item.widget().deleteLater()
        self.actions.addWidget(button('Отмена',self.reject))
        self.actions.addWidget(button('Сохранить исправление',self.save,'primary','check'))
    def save(self):
        self.run_action(lambda:self.store.support_update_task(self.user,self.t['id'],title=self.title.text(),
            description=self.description.toPlainText(),site=self.site.currentData(),equipment=self.equipment.currentText(),equipment_id=self.equipment.currentData(),
            priority=self.priority.currentData(),kind=self.kind.currentData(),duration=self.duration.value(),
            day=self.day.date().toString('yyyy-MM-dd'),start=time_value(self.start) if self.worker.currentData() else None,
            deadline=self.deadline.dateTime().toString('yyyy-MM-ddTHH:mm'),worker_id=self.worker.currentData(),reason=self.reason.text()))
