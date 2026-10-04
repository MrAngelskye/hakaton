from datetime import date
from PySide6.QtCore import Qt,QDate,QDateTime,QTime,QUrl,QTimer
from PySide6.QtGui import QPixmap,QDesktopServices
from PySide6.QtWidgets import (QLineEdit,QTextEdit,QComboBox,QDoubleSpinBox,QSpinBox,QDateEdit,
    QDateTimeEdit,QTimeEdit,QTableWidget,QTableWidgetItem,QHeaderView,QFileDialog,QAbstractItemView)
from app.store import STATUS,SITES,ROLES,EMPLOYEE_STATUS
from app.domain import PRIORITIES
from app.drafts import ReportDraft
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


class EquipmentChoice(NoWheelComboBox):
    def text(self):return self.currentData() or self.currentText()
    def setText(self,value):
        index=self.findText(value)
        if index<0:self.addItem(value,value);index=self.count()-1
        self.setCurrentIndex(index)


class CreateTask(Sheet):
    def __init__(self,store,user,parent,assignment=None):
        super().__init__('Исправление наряда' if hasattr(self,'t') else 'Выдать наряд',parent);self.store=store;self.user=user
        self.refs=store.references(user)
        self.body.addWidget(label('Демонстрационные справочники · заменяются администратором','muted',True))
        self.site=self.field('Участок',combo([(r['name'],r['name']) for r in self.refs['sites'] if r['active']]))
        self.equipment=EquipmentChoice();self.field('Оборудование *',self.equipment)
        self.site.currentIndexChanged.connect(self.fill_equipment);self.fill_equipment()
        people=[u for u in store.users(user,True) if u['active']]
        self.worker=self.field('Ответственный исполнитель *',combo([('Выберите сотрудника',None)]+[
            (u['name']+' · '+EMPLOYEE_STATUS[store.employee_status(user,u['id'])][0],u['id']) for u in people]))
        self.brigade=self.field('Бригада (необязательно)',combo([('Индивидуальная работа',None)]+[(r['name'],r['id']) for r in self.refs['brigades'] if r['active']]))
        self.normative=self.field('Шаблон / норматив',combo([('Без шаблона',None)]+[(r['name'],r['id']) for r in self.refs['normatives'] if r['active']]))
        self.priority=self.field('Приоритет',combo([(v,k) for k,v in PRIORITIES.items()]));self.priority.setCurrentIndex(self.priority.findData('normal'))
        self.title=self.field('Название задачи *',QLineEdit());self.title.setMaxLength(120)
        self.description=self.field('Проблема и ожидаемые работы *',QTextEdit());self.description.setFixedHeight(90)
        self.kind=self.field('Тип работ',combo([('Плановая','Плановая'),('Внеплановая','Внеплановая')]))
        self.duration=self.field('Плановое время, ч',number(1))
        today=QDate.currentDate();clock=QTime.currentTime()
        day=today.addDays(1) if clock.hour()>=17 else today
        self.day=DatePicker(day);self.field('День работ',self.day)
        start=QTime(8,0) if day!=today else QTime(max(8,clock.hour()+1),0)
        self.start=TimePicker(start);self.field('Плановое начало',self.start)
        self.deadline=DateTimePicker(QDateTime(day,QTime(18,0)));self.field('Срок выполнения',self.deadline)
        self.normative.currentIndexChanged.connect(self.apply_normative)
        if assignment:
            wid,day,start,end=assignment
            self.worker.setCurrentIndex(self.worker.findData(wid));self.day.setDate(QDate.fromString(day,'yyyy-MM-dd'))
            self.start.setTime(QTime(int(start),round(start%1*60)));self.duration.setValue(min(1,end-start))
            self.deadline.setDateTime(QDateTime(self.day.date(),QTime(int(end),round(end%1*60))))
        self.actions.addWidget(button('Отмена',self.reject));self.actions.addWidget(button('Выдать наряд',self.save,'primary','plus'))
    def fill_equipment(self):
        old=self.equipment.currentData();self.equipment.clear()
        site=next((r for r in self.refs['sites'] if r['name']==self.site.currentData()),None)
        for r in self.refs['equipment']:
            if r['active'] and site and r.get('site_id')==site['id']:self.equipment.addItem(r['name'],r['name'])
        index=self.equipment.findData(old)
        if index>=0:self.equipment.setCurrentIndex(index)
    def apply_normative(self):
        item=next((r for r in self.refs['normatives'] if r['id']==self.normative.currentData()),None)
        if item:
            self.duration.setValue(item['hours'])
            if not self.title.text():self.title.setText(item['name'])
            if not self.description.toPlainText():self.description.setPlainText('Выполнить '+item['name'].lower()+'. Проверить результат и описать контрольную проверку в отчёте.')
    def save(self):
        self.run_action(lambda:self.store.create_task(self.user,title=self.title.text(),description=self.description.toPlainText(),
            site=self.site.currentData(),equipment=self.equipment.text(),priority=self.priority.currentData(),kind=self.kind.currentData(),
            duration=self.duration.value(),day=self.day.date().toString('yyyy-MM-dd'),start=time_value(self.start),
            deadline=self.deadline.dateTime().toString('yyyy-MM-ddTHH:mm'),worker_id=self.worker.currentData(),
            brigade_id=self.brigade.currentData(),normative_id=self.normative.currentData(),issued=True))


class TaskDetails(Sheet):
    def __init__(self,store,user,tid,parent):
        t=store.task(user,tid);super().__init__(f'Наряд НР-{tid}',parent);self.store=store;self.user=user
        self.body.addLayout(row(tag(STATUS[t['status']]),tag(PRIORITIES[t['priority']],'urgent' if t['priority']=='urgent' else 'warning' if t['priority']=='high' else 'neutral')))
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
                self.start=TimePicker(QTime(int(start),int(round(start%1*60))));self.field('Начало работы',self.start)
                action=store.claim if t['status']=='available' else store.reschedule
                self.actions.addWidget(button('В график' if t['status']=='available' else 'Перенести',
                    lambda:self.run_action(lambda:action(user,tid,self.day.date().toString('yyyy-MM-dd'),time_value(self.start))),'secondary','calendar'))
            if t['worker_id']==user['id'] or user['role']=='admin':
                if t['status']=='issued':
                    self.actions.addWidget(button('Принять наряд',lambda:self.run_action(lambda:store.transition(user,tid,'accepted')),'primary','check'))
                    self.body.addWidget(button('Поставить в очередь',lambda:self.run_action(lambda:store.transition(user,tid,'queued')),'secondary','clock'))
                    self.body.addWidget(button('Отклонить с причиной',lambda:self.reject_order(store,user,tid),'danger'))
                if t['status'] in ('planned','accepted','queued','paused','revision'):
                    self.actions.addWidget(button('Продолжить работу' if t['status'] in ('paused','revision') else 'Начать работу',lambda:self.run_action(lambda:store.transition(user,tid,'inProgress')),'primary','play'))
                if t['status']=='inProgress':
                    self.actions.addWidget(button('Приостановить',lambda:self.pause(store,user,tid),'secondary','clock'))
                if t['status'] in ('inProgress','revision'):
                    self.actions.addWidget(button('Отправить отчёт',lambda:self.report(store,user,t,parent),'primary','report'))
        if user['role'] in ('master','admin') and t['status'] not in ('aiPending','submitted','approved','cancelled'):
            self.body.addWidget(button('Отменить наряд',lambda:self.cancel(store,user,tid),'danger'))
        if user['role'] in ('master','admin') and t['status'] in ('issued','accepted','queued','rejected','planned','available'):
            self.body.addWidget(button('Переназначить исполнителя',lambda:self.reassign(store,user,t),'secondary','team'))
        self.body.addWidget(button('История оборудования',lambda:EquipmentHistory(store,user,t['equipment'],self).exec(),'secondary','tool'))
        if user['role']=='master' and t['status']=='planned':
            self.day=DatePicker(QDate.fromString(t['day'],'yyyy-MM-dd'));self.field('Новый день в графике',self.day)
            self.start=TimePicker(QTime(int(t['start']),round(t['start']%1*60)));self.field('Новое начало',self.start)
            self.actions.addWidget(button('Перенести',lambda:self.run_action(lambda:store.reschedule(user,tid,self.day.date().toString('yyyy-MM-dd'),time_value(self.start))),'secondary','calendar'))
        if user['role']=='admin':
            self.body.addWidget(label('Инструменты поддержки','section'))
            self.body.addWidget(label('Действия администратора записываются в историю наряда.','muted',True))
            if t['status'] in ('available','planned','inProgress','paused','revision'):
                self.body.addWidget(button('Исправить наряд',lambda:self.support(store,user,t,parent),'secondary','edit'))
        if latest:
            self.body.addWidget(button('Открыть последний отчёт',lambda:self.show_report(store,user,latest,parent),'secondary','report'))
        self.body.addWidget(label('История наряда','section'))
        for e in store.events(user,tid):
            self.body.addWidget(label(e['created'].replace('T',' ')+' · '+e['name'],'muted',True))
            self.body.addWidget(label(e['message'],'',True))
    def reject_order(self,store,user,tid):
        d=Sheet('Причина отказа',self);reason=d.field('Почему не можете принять наряд? *',QTextEdit())
        d.actions.addWidget(button('Отклонить',lambda:d.run_action(lambda:store.transition(user,tid,'rejected',reason.toPlainText())),'danger'))
        if d.exec():self.accept()
    def reassign(self,store,user,t):
        if ReassignTask(store,user,t,self).exec():self.accept()
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
        self.end=self.field('Конец смены',TimePicker(QTime(int(b),round(b%1*60))))
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
        self.refs=store.references(user)
        self.defect=self.field('Шифр неисправности',combo([(r.get('code','')+' · '+r['name'],r.get('code','')+' · '+r['name']) for r in self.refs['defects'] if r['active']]))
        self.hours=self.field('Фактическое время, ч',number(t['duration'],.1,24,.1))
        self.body.addWidget(label('Материалы и стоимость','section'))
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['Материал','Кол-во','Ед.','Цена, тг'])
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        for i in (1,2,3):self.table.setColumnWidth(i,100)
        self.table.setMinimumHeight(160);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.body.addWidget(self.table)
        self.body.addLayout(row(button('Выбрать материал',self.choose_material,'secondary','plus'),button('Удалить строку',self.remove_material)))
        self.photo_sources=[];self.photo_box,self.photo_layout=card();self.body.addWidget(label('Фото результата *' if t['kind']=='Внеплановая' else 'Фото результата','section'))
        self.body.addWidget(button('Добавить фото',self.add_photos,'secondary','camera'));self.body.addWidget(self.photo_box)
        self.body.addWidget(label('До 3 фото · JPG, PNG, WebP · до 8 МБ каждое','muted',True))
        if old:
            self.work.setPlainText(old['work']);self.result_text.setPlainText(old['result']);self.select_defect(old['defect']);self.hours.setValue(old['hours'])
            for m in old['materials']:self.add_material(m)
            self.photo_sources=[str(store.photos/p) for p in old['photos'] if (store.photos/p).is_file()]
        self.refresh_photos()
        self.body.addWidget(label('На сервере отчёт сначала проверит ИИ, если он включён; окончательное решение принимает мастер.' if getattr(store,'is_remote',False) else 'Отчёт поступит мастеру для ручной проверки.','muted',True))
        self.actions.addWidget(button('Отмена',self.reject));self.actions.addWidget(button('Отправить мастеру',self.save,'primary','report'))
        self.draft=ReportDraft(store,user,t['id']);self._submitted=False
        draft=self.draft.load();missing_photos=0
        if draft:
            self.work.setPlainText(draft.get('work',''));self.result_text.setPlainText(draft.get('result',''))
            self.hours.setValue(draft.get('hours',t['duration']))
            self.select_defect(draft.get('defect',self.defect.currentText()))
            self.table.setRowCount(0)
            for m in draft.get('materials',[]):self.add_material(m)
            from pathlib import Path
            restored=[]
            for source in draft.get('photo_sources',[]):
                path=Path(source)
                if path.is_file():restored.append(str(path))
                elif old and path.name in old['photos'] and (store.photos/path.name).is_file():restored.append(str(store.photos/path.name))
                else:missing_photos+=1
            self.photo_sources=restored;self.refresh_photos()
        if missing_photos:self.body.addWidget(label(f'Не удалось восстановить {missing_photos} фото: исходные файлы перемещены или удалены. Добавьте их снова.','urgent',True))
        self.draft_status=label('Черновик восстановлен' if draft else 'Черновик сохраняется на этом устройстве','muted',True);self.body.addWidget(self.draft_status)
        self.draft_timer=QTimer(self);self.draft_timer.setSingleShot(True);self.draft_timer.setInterval(350);self.draft_timer.timeout.connect(self.save_draft)
        for editor in (self.work,self.result_text):editor.textChanged.connect(lambda:self.draft_timer.start())
        self.hours.valueChanged.connect(lambda:self.draft_timer.start());self.defect.currentIndexChanged.connect(lambda:self.draft_timer.start())
        self.table.itemChanged.connect(lambda:self.draft_timer.start())
    def select_defect(self,value):
        if self.defect.findText(value)<0:self.defect.addItem(value,value)
        self.defect.setCurrentText(value)
    def choose_material(self):
        d=Sheet('Выберите материал',self)
        items=[r for r in self.refs['materials'] if r['active']]
        choice=d.field('Материал',combo([(r['name']+' · '+r['unit'],r['id']) for r in items]))
        def add():
            material=next(r for r in items if r['id']==choice.currentData())
            self.add_material({'name':material['name'],'quantity':1,'unit':material['unit'],'price':material.get('price',0)});d.accept()
        d.actions.addWidget(button('Добавить',add,'primary','plus'));d.exec()
    def save_draft(self):
        if self._submitted:return
        materials=[]
        for n in range(self.table.rowCount()):
            values=[self.table.item(n,i).text() if self.table.item(n,i) else '' for i in range(4)]
            materials.append(dict(zip(('name','quantity','unit','price'),values)))
        try:
            self.draft.save({'work':self.work.toPlainText(),'result':self.result_text.toPlainText(),'defect':self.defect.currentText(),
                'hours':self.hours.value(),'materials':materials,'photo_sources':self.photo_sources})
            self.draft_status.setText('Черновик сохранён на этом устройстве')
        except OSError:self.draft_status.setText('Не удалось сохранить черновик. Проверьте место на диске.')
    def reject(self):
        if hasattr(self,'draft'):self.save_draft();self.draft_timer.stop()
        super().reject()
    def closeEvent(self,event):
        if hasattr(self,'draft'):self.save_draft();self.draft_timer.stop()
        super().closeEvent(event)

    def add_material(self,m=None):
        m=m or {'name':'','quantity':1,'unit':'шт.','price':0}
        n=self.table.rowCount();self.table.insertRow(n)
        for i,key in enumerate(['name','quantity','unit','price']):self.table.setItem(n,i,QTableWidgetItem(str(m[key])))
    def remove_material(self):
        if self.table.currentRow()>=0:
            self.table.removeRow(self.table.currentRow());self.draft_timer.start()
    def add_photos(self):
        paths,_=QFileDialog.getOpenFileNames(self,'Выберите фото','','Фото (*.jpg *.jpeg *.png *.webp)')
        selected=list(dict.fromkeys(self.photo_sources+paths))
        if len(selected)>3:self.fail('Выберите не больше 3 фото.');return
        if any(QPixmap(p).isNull() for p in paths):self.fail('Один из файлов не удалось открыть как фото.');return
        self.photo_sources=selected;self.refresh_photos()
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
        if hasattr(self,'draft_timer'):self.draft_timer.start()
    def remove_photo(self,p):self.photo_sources.remove(p);self.refresh_photos()
    def save(self):
        def action():
            materials=[]
            for n in range(self.table.rowCount()):
                vals=[self.table.item(n,i).text().strip() if self.table.item(n,i) else '' for i in range(4)]
                try:materials.append({'name':vals[0],'quantity':float(vals[1].replace(',','.')),'unit':vals[2],'price':float(vals[3].replace(',','.'))})
                except ValueError:raise ValueError(f'Проверьте количество и цену в строке {n+1}.')
            self.store.submit(self.user,self.t['id'],work=self.work.toPlainText(),result=self.result_text.toPlainText(),
                defect=self.defect.currentText(),hours=self.hours.value(),materials=materials,photo_sources=self.photo_sources)
            self._submitted=True;self.draft_timer.stop()
            try:self.draft.clear()
            except OSError:pass
        self.run_action(action)


class ReviewReport(Sheet):
    def __init__(self,store,user,r,parent):
        super().__init__(f"Отчёт ОТ-{r['id']:04d}",parent);self.store=store;self.user=user;self.r=r
        if hasattr(store,'ensure_photos'):store.ensure_photos(r)
        self.body.addLayout(row(tag(STATUS[r['status']]),label(f"НР-{r['task_id']}",'muted')))
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
        task=store.task(user,r['task_id'])
        self.body.addWidget(label('Исходная задача','section'));self.body.addWidget(label(task['description'],'',True))
        self.body.addWidget(label('Проверки данных и фотографий','section'))
        self.check_targets={}
        names={'work':'Выполненные работы','result':'Контрольная проверка','photos':'Фото результата','materials':'Материалы','hours':'Время'}
        for check in r.get('checks',[]):
            if check.get('severity')=='info':continue
            field=check.get('field','photos')
            self.body.addWidget(button(names.get(field,field)+': '+check['message'],lambda key=field:self.focus_check(key),'secondary'))
        self.body.addWidget(label(r['title'],'heading',True));self.body.addWidget(label(r['worker_name']+' · '+r['created'].replace('T',' '),'muted',True))
        for title,text in [('Оборудование',r['equipment']+' · '+r['site']),('Выполненные работы',r['work']),
                           ('Результат',r['result']),('Дефект',r['defect']),('Фактическое время',f"{r['hours']:g} ч")]:
            target=label(title,'muted');self.body.addWidget(target);self.body.addWidget(label(text,'',True))
            self.check_targets[{'Выполненные работы':'work','Результат':'result','Фактическое время':'hours'}.get(title,title)]=target
        material_target=label('Материалы','section');self.body.addWidget(material_target);self.check_targets['materials']=material_target
        for m in r['materials']:
            self.body.addWidget(label(f"{m['name']} · {m['quantity']:g} {m['unit']} × {m['price']:,.2f} тг",'',True))
        total=sum(m['quantity']*m['price'] for m in r['materials'])
        self.body.addWidget(label(f'Итого: {total:,.2f} тг' if r['materials'] else 'Материалы не использовались','title'))
        photo_target=label('Фото результата','section');self.body.addWidget(photo_target);self.check_targets['photos']=photo_target
        for p in r['photos']:
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
            self.score=NoWheelSpinBox();self.score.setRange(0,100);self.score.setSpecialValueText('0');self.score.setValue(ai['score'] if ai and ai.get('status')=='completed' else 0)
            self.field('Ручная оценка мастера, 0–100',self.score)
            self.comment=self.field('Комментарий сотруднику *',QTextEdit());self.comment.setFixedHeight(90)
            self.actions.addWidget(button('Вернуть на доработку',lambda:self.decide(False),'danger'))
            self.actions.addWidget(button('Принять работу',lambda:self.decide(True),'primary','check'))
        else:self.actions.addWidget(button('Закрыть',self.reject))
    def focus_check(self,key):
        from PySide6.QtWidgets import QScrollArea
        target=self.check_targets.get(key)
        if target:
            target.setFocus();self.findChild(QScrollArea).ensureWidgetVisible(target,20,30)
    def decide(self,approve):
        self.run_action(lambda:self.store.review(self.user,self.r['id'],approve,self.score.value(),self.comment.toPlainText()))


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
        # Preserve the site of an existing order from an earlier demo database.
        if self.site.findText(t['site'])<0:self.site.addItem(t['site'],t['site'])
        self.site.setCurrentText(t['site']);self.equipment.setText(t['equipment'])
        self.priority.setCurrentIndex(self.priority.findData(t['priority']))
        self.kind.setCurrentText(t['kind']);self.duration.setValue(t['duration'])
        self.worker.setCurrentIndex(self.worker.findData(t['worker_id']))
        self.day.setDate(QDate.fromString(t['day'],'yyyy-MM-dd'))
        start=t['start'] if t['start'] is not None else 8
        self.start.setTime(QTime(int(start),int(round(start%1*60))))
        self.deadline.setDateTime(QDateTime.fromString(t['deadline'],Qt.DateFormat.ISODate))
        # У начатой задачи меняем только описание, срок и приоритет.
        locked=t['status'] not in ('available','planned')
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
            description=self.description.toPlainText(),site=self.site.currentData(),equipment=self.equipment.text(),
            priority=self.priority.currentData(),kind=self.kind.currentData(),duration=self.duration.value(),
            day=self.day.date().toString('yyyy-MM-dd'),start=time_value(self.start) if self.worker.currentData() else None,
            deadline=self.deadline.dateTime().toString('yyyy-MM-ddTHH:mm'),worker_id=self.worker.currentData(),reason=self.reason.text()))


class ReassignTask(Sheet):
    def __init__(self,store,user,t,parent):
        super().__init__('Переназначить НР-'+str(t['id']),parent)
        people=[u for u in store.users(user,True) if u['active']]
        worker=self.field('Новый ответственный',combo([(u['name'],u['id']) for u in people]))
        day=self.field('День',DatePicker(QDate.fromString(t['day'],'yyyy-MM-dd')))
        start=t['start'] if t['start'] is not None else 8
        clock=self.field('Начало',TimePicker(QTime(int(start),round(start%1*60))))
        reason=self.field('Причина *',QTextEdit())
        self.actions.addWidget(button('Переназначить',lambda:self.run_action(lambda:store.reassign_task(user,t['id'],worker.currentData(),
            day.date().toString('yyyy-MM-dd'),time_value(clock),reason.toPlainText())),'primary','team'))


class EquipmentHistory(Sheet):
    def __init__(self,store,user,equipment,parent):
        super().__init__('История оборудования',parent);data=store.equipment_history(user,equipment)
        self.body.addWidget(label(equipment,'heading',True))
        self.body.addWidget(label('Зафиксированные паузы: '+str(round(data.get('pause_minutes',0)))+' мин','title'))
        self.body.addWidget(label('Паузы наряда не всегда означают простой оборудования. Исторические записи без замеров отмечены отдельно.','muted',True))
        for item in data.get('repeat_defects',[]):self.body.addWidget(label(item['defect']+' · повторов '+str(item['count']),'',True))
        for task in data.get('tasks',[]):
            self.body.addWidget(label('НР-'+str(task['id'])+' · '+task['title'],'section',True))
            self.body.addWidget(label(STATUS[task['status']]+' · '+task.get('timing_note',''),'muted',True))
            report=task.get('last_report')
            if report:self.body.addWidget(label(report['result'],'',True))
