"""Editors for the canonical migration-002 catalogs."""
from PySide6.QtWidgets import QLineEdit,QCheckBox
from app.widgets import Sheet,button
from app.dialogs import combo,number
from app.widgets import label

NAMES={'sites':'Участки','equipment':'Оборудование','brigades':'Бригады','defect_codes':'Шифры неисправностей','materials':'Материалы','work_norms':'Нормативы'}
FIELDS={
 'sites':{'code':('Код','text',''),'name':('Название','text','')},
 'equipment':{'inventory_number':('Инвентарный номер','text',''),'name':('Название','text',''),'site_id':('Участок','sites',None),'equipment_type':('Тип оборудования','text',''),'criticality':('Критичность 1–5','integer',3)},
 'brigades':{'code':('Код','text',''),'name':('Название','text','')},
 'defect_codes':{'code':('Шифр','text',''),'name':('Название','text',''),'category':('Категория','text','')},
 'materials':{'code':('Код','text',''),'name':('Название','text',''),'unit':('Единица','text','шт.'),'unit_price':('Цена, тг','number',0)},
 'work_norms':{'equipment_type':('Тип оборудования','text',''),'kind':('Тип работ','kind','Плановая'),'defect_code_id':('Дефект','defect_codes',None),'hours':('Часы','number',1),'complexity':('Сложность','number',1),'active':('Действует','bool',1)}
}

class ReferenceEditor(Sheet):
    def __init__(self,store,user,category,parent,item=None):
        super().__init__('Изменить запись' if item else 'Новая запись',parent)
        self.store=store;self.user=user;self.category=category;self.item=item or {};self.inputs={}
        if category=='materials' and self.item.get('unit_price_known') is False:
            self.body.addWidget(label('Цена не указана. Введите фактическую цену по документу склада; ноль в поле — техническое начальное значение.','warning',True))
        if self.item.get('reference_only'):
            self.body.addWidget(label('Каталог производителя подтверждает модель. Применение на предприятии и совместимость с оборудованием требуют проверки.','muted',True))
        catalogs=store.catalogs(user)
        for key,(title,kind,default) in FIELDS[category].items():
            value=self.item.get(key,default)
            if kind=='text':widget=QLineEdit(str(value));widget.setMaxLength(200)
            elif kind in ('number','integer'):
                bounds=(.1,10) if key=='complexity' else (.1,24) if key=='hours' else (1,5) if key=='criticality' else (0,1e9)
                widget=number(value,*bounds,1 if kind=='integer' else .1);widget.setDecimals(0 if kind=='integer' else 2)
            elif kind=='bool':widget=QCheckBox();widget.setChecked(bool(value))
            else:
                items=[(v,v) for v in ('Плановая','Внеплановая')] if kind=='kind' else [(r['name'],r['id']) for r in catalogs[kind]]
                if key=='defect_code_id':items=[('Не указан',None)]+items
                widget=combo(items);index=widget.findData(value)
                if index>=0:widget.setCurrentIndex(index)
            self.inputs[key]=(widget,kind);self.field(title,widget)
        self.actions.addWidget(button('Отмена',self.reject));self.actions.addWidget(button('Сохранить',self.save,'primary','check'))
    def save(self):
        values={}
        for key,(widget,kind) in self.inputs.items():
            values[key]=widget.text().strip() if kind=='text' else int(widget.isChecked()) if kind=='bool' else int(widget.value()) if kind=='integer' else widget.value() if kind=='number' else widget.currentData()
        self.run_action(lambda:self.store.catalog_upsert(self.user,self.category,values,self.item.get('id')))
