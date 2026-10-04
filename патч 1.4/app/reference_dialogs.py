"""Reference editing available to administrators; names and relations stay in DB."""
from PySide6.QtWidgets import QLineEdit,QCheckBox
from app.widgets import Sheet,button,label
from app.dialogs import combo,number

NAMES={'sites':'Участки','equipment':'Оборудование','brigades':'Бригады','defects':'Шифры неисправностей',
       'materials':'Материалы','normatives':'Нормативы'}


class ReferenceEditor(Sheet):
    def __init__(self,store,user,category,parent,item=None):
        super().__init__('Изменить запись' if item else 'Новая запись',parent)
        self.store=store;self.user=user;self.category=category;self.item=item or {}
        self.name=self.field('Название *',QLineEdit(self.item.get('name','')))
        self.active=QCheckBox('Действующая запись');self.active.setChecked(bool(self.item.get('active',1)));self.body.addWidget(self.active)
        if self.item.get('active'):
            self.active.setEnabled(False);self.active.setToolTip('Отключение выполняется отдельной кнопкой с проверкой текущих нарядов.')
        refs=store.references(user)
        if category in ('equipment','brigades'):
            self.site=self.field('Участок',combo([(r['name'],r['id']) for r in refs['sites'] if r['active']]))
            index=self.site.findData(self.item.get('site_id'))
            if index>=0:self.site.setCurrentIndex(index)
        if category=='materials':
            self.unit=self.field('Единица измерения *',QLineEdit(self.item.get('unit','шт.')))
            self.price=self.field('Цена, тг',number(self.item.get('price',0),0,100000000,.01))
        if category=='defects':self.code=self.field('Шифр *',QLineEdit(self.item.get('code','М-01')))
        if category=='normatives':self.hours=self.field('Норматив, ч',number(self.item.get('hours',1),.1,24,.1))
        self.members=[]
        if category=='brigades':
            self.body.addWidget(label('Участники бригады','section'))
            for worker in store.users(user,True):
                if not worker['active']:continue
                checkbox=QCheckBox(worker['name']);checkbox.setChecked(worker['id'] in self.item.get('members',[]))
                self.body.addWidget(checkbox);self.members.append((worker['id'],checkbox))
        self.actions.addWidget(button('Отмена',self.reject));self.actions.addWidget(button('Сохранить',self.save,'primary','check'))
    def save(self):
        value={'name':self.name.text(),'active':int(self.active.isChecked())}
        if self.item.get('id'):value['id']=self.item['id']
        if self.category in ('equipment','brigades'):value['site_id']=self.site.currentData()
        if self.category=='materials':value.update(unit=self.unit.text(),price=self.price.value())
        if self.category=='defects':value['code']=self.code.text()
        if self.category=='normatives':value['hours']=self.hours.value()
        if self.category=='brigades':value['members']=[uid for uid,checkbox in self.members if checkbox.isChecked()]
        self.run_action(lambda:self.store.save_reference(self.user,self.category,value))
