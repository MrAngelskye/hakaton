from pathlib import Path
from PySide6.QtCore import Qt, QSize, QByteArray, QPointF
from PySide6.QtGui import QIcon, QPixmap, QPainter, QWheelEvent
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QWidget,QFrame,QLabel,QPushButton,QVBoxLayout,QHBoxLayout,
                              QGridLayout,QScrollArea,QSizePolicy,QDialog,QApplication)

ROOT=Path(__file__).resolve().parents[1]


def scroll_page(widget,event):
    parent=widget.parentWidget()
    while parent is not None:
        if isinstance(parent,QScrollArea):
            viewport=parent.viewport()
            local=viewport.mapFromGlobal(event.globalPosition().toPoint())
            forwarded=QWheelEvent(QPointF(local),event.globalPosition(),event.pixelDelta(),event.angleDelta(),
                event.buttons(),event.modifiers(),event.phase(),event.inverted())
            QApplication.sendEvent(viewport,forwarded)
            event.accept()  # Не прокручивать страницу повторно при всплытии события.
            return
        parent=parent.parentWidget()
    event.ignore()


class ScrollButton(QPushButton):
    def wheelEvent(self,event):scroll_page(self,event)



def icon(name,color='#76728a'):
    p=ROOT/'assets'/'icons'/f'{name}.svg'
    if not p.exists():return QIcon()
    svg=p.read_text().replace('#76728a',color).replace('currentColor',color)
    pm=QPixmap(48,48);pm.fill(Qt.GlobalColor.transparent)
    painter=QPainter(pm);QSvgRenderer(QByteArray(svg.encode())).render(painter);painter.end()
    return QIcon(pm)


def label(text,name='',wrap=False):
    w=QLabel(str(text));w.setTextFormat(Qt.TextFormat.PlainText)
    if name:w.setObjectName(name)
    w.setWordWrap(wrap)
    return w


def button(text,callback=None,kind='',ico=None):
    w=ScrollButton(text)
    if kind:w.setObjectName(kind)
    if ico:w.setIcon(icon(ico,'#ffffff' if kind=='primary' else '#76728a'));w.setIconSize(QSize(20,20))
    w.setCursor(Qt.CursorShape.PointingHandCursor)
    if callback:w.clicked.connect(lambda checked=False:callback())
    return w


def row(*widgets):
    layout=QHBoxLayout();layout.setContentsMargins(0,0,0,0);layout.setSpacing(12)
    for w in widgets:layout.addWidget(w)
    return layout


def card(name='card',padding=22):
    w=QFrame();w.setObjectName(name)
    layout=QVBoxLayout(w);layout.setContentsMargins(padding,padding,padding,padding);layout.setSpacing(14)
    return w,layout


def avatar(name,size=44):
    w=label(''.join(p[0] for p in name.split()[:2]),'avatar')
    w.setAlignment(Qt.AlignmentFlag.AlignCenter);w.setFixedSize(size,size)
    return w


def tag(text,tone='neutral'):
    w=label(text,'tag');w.setProperty('tone',tone)
    w.setSizePolicy(QSizePolicy.Policy.Maximum,QSizePolicy.Policy.Fixed)
    return w


def brand():
    w=QWidget();w.setObjectName("brandContainer");l=QHBoxLayout(w);l.setContentsMargins(0,0,0,0);l.setSpacing(10)
    mark=QLabel();mark.setFixedSize(40,40);mark.setPixmap(icon('brand','#ffffff').pixmap(28,28))
    mark.setAlignment(Qt.AlignmentFlag.AlignCenter);mark.setStyleSheet('background:#302262;border-radius:13px;')
    l.addWidget(mark);l.addWidget(label('НарядAI','brand'));l.addStretch()
    return w


class CardGrid(QWidget):
    """Две колонки на широком окне, одна — на узком."""
    def __init__(self,cards):
        super().__init__();self.cards=cards;self.columns=0
        self.grid=QGridLayout(self);self.grid.setContentsMargins(0,0,0,0);self.grid.setSpacing(18)
        self.arrange(2)
    def arrange(self,n):
        if n==self.columns:return
        while self.grid.count():self.grid.takeAt(0)
        self.grid.setColumnStretch(0,1);self.grid.setColumnStretch(1,1 if n==2 else 0)
        for i,w in enumerate(self.cards):self.grid.addWidget(w,i//n,i%n)
        self.columns=n
    def resizeEvent(self,e):
        self.arrange(2 if self.width()>=750 else 1);super().resizeEvent(e)


class Sheet(QDialog):
    def __init__(self,title,parent=None):
        super().__init__(parent);self.setWindowTitle(title);self.resize(680,760)
        self.setMinimumWidth(580)
        main=QVBoxLayout(self);main.setContentsMargins(24,20,24,20);main.setSpacing(18)
        top=row(label(title,'section'));top.addStretch()
        close=button('Закрыть',self.reject);top.addWidget(close);main.addLayout(top)
        scroll=QScrollArea();scroll.setWidgetResizable(True)
        body=QWidget();self.body=QVBoxLayout(body);self.body.setContentsMargins(0,0,12,0);self.body.setSpacing(16)
        scroll.setWidget(body);main.addWidget(scroll)
        self.error=label('','',True);self.error.setStyleSheet('color:#ac4264;');self.error.hide();main.addWidget(self.error)
        self.actions=QHBoxLayout();self.actions.setSpacing(12);main.addLayout(self.actions)
    def fail(self,e):
        self.error.setText(str(e));self.error.show()
    def run_action(self,fn):
        try:fn();self.accept()
        except (ValueError,PermissionError,OSError) as e:self.fail(e)
    def field(self,title,widget):
        self.body.addWidget(label(title));self.body.addWidget(widget);return widget


# Колёсико меняет прокрутку страницы, а не значения внутри полей.
from PySide6.QtCore import QDate,QTime,QDateTime,Signal,QLocale
from PySide6.QtWidgets import QCalendarWidget,QButtonGroup,QDoubleSpinBox,QSpinBox,QComboBox


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self,event):scroll_page(self,event)


class NoWheelSpinBox(QSpinBox):
    def wheelEvent(self,event):scroll_page(self,event)


class NoWheelComboBox(QComboBox):
    def wheelEvent(self,event):scroll_page(self,event)


MONTHS=('январь','февраль','март','апрель','май','июнь',
        'июль','август','сентябрь','октябрь','ноябрь','декабрь')


class CalendarDialog(QDialog):
    def __init__(self,value,parent=None):
        super().__init__(parent);self.setWindowTitle('Выберите дату');self.resize(600,480)
        main=QVBoxLayout(self);main.setContentsMargins(24,24,24,24);main.setSpacing(16)
        main.addWidget(label('Выберите дату','section'))
        self.calendar=QCalendarWidget();self.calendar.setLocale(QLocale("ru_RU"));self.calendar.setNavigationBarVisible(False)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.calendar.setFirstDayOfWeek(Qt.DayOfWeek.Monday);self.calendar.setSelectedDate(value)
        self.calendar.setMinimumSize(530,280)
        self.month=label('','title');self.month.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main.addLayout(row(button('◀ Назад',self.calendar.showPreviousMonth,'secondary'),self.month,
                           button('Вперёд ▶',self.calendar.showNextMonth,'secondary')))
        self.calendar.currentPageChanged.connect(self.update_month)
        self.update_month(self.calendar.yearShown(),self.calendar.monthShown())
        main.addWidget(self.calendar,1)
        self.selected=label('','title');self.selected.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.calendar.selectionChanged.connect(self.update_selected);self.update_selected();main.addWidget(self.selected)
        today=button('Сегодня',self.today,'secondary')
        main.addLayout(row(today,button('Отмена',self.reject),button('Выбрать дату',self.accept,'primary','check')))
        self.calendar.activated.connect(lambda date:self.accept())
    def update_month(self,year,month):self.month.setText(f'{MONTHS[month-1].capitalize()} {year}')
    def update_selected(self):self.selected.setText('Выбрано: '+self.calendar.selectedDate().toString('dd.MM.yyyy'))
    def today(self):self.calendar.setSelectedDate(QDate.currentDate());self.calendar.showSelectedDate()


class DatePicker(QWidget):
    dateChanged=Signal(QDate)
    def __init__(self,value=None,parent=None):
        super().__init__(parent);self._value=value if value and value.isValid() else QDate.currentDate()
        l=QHBoxLayout(self);l.setContentsMargins(0,0,0,0);l.setSpacing(12)
        self.display=button('',self.choose,'secondary','calendar');self.display.setMinimumHeight(30)
        self.choose_button=button('Выбрать дату',self.choose,ico='calendar');self.choose_button.setMinimumHeight(30)
        l.addWidget(self.display,1);l.addWidget(self.choose_button);self.update_text()
    def date(self):return QDate(self._value)
    def setDate(self,value):
        if value.isValid() and value!=self._value:
            self._value=QDate(value);self.update_text();self.dateChanged.emit(self.date())
    def update_text(self):self.display.setText(self._value.toString('dd.MM.yyyy'))
    def choose(self):
        d=CalendarDialog(self.date(),self)
        if d.exec():self.setDate(d.calendar.selectedDate())
    def wheelEvent(self,event):scroll_page(self,event)


class TimeDialog(QDialog):
    def __init__(self,value,parent=None):
        super().__init__(parent);self.setWindowTitle('Выберите время');self.resize(560,580)
        self.value=QTime(value);main=QVBoxLayout(self);main.setContentsMargins(24,24,24,24);main.setSpacing(15)
        self.preview=label(self.value.toString('HH:mm'),'heading');self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main.addWidget(self.preview);main.addWidget(label('Часы','section'))
        hours=QGridLayout();hours.setSpacing(8);self.hour_group=QButtonGroup(self)
        for h in range(24):
            b=button(f'{h:02d}',lambda n=h:self.set_hour(n),'timeChoice');b.setCheckable(True);b.setMinimumSize(66,44)
            self.hour_group.addButton(b,h);b.setChecked(h==self.value.hour());hours.addWidget(b,h//6,h%6)
        main.addLayout(hours);main.addWidget(label('Минуты','section'))
        minutes=QGridLayout();minutes.setSpacing(8);self.minute_group=QButtonGroup(self)
        choices=sorted(set(range(0,60,5))|{self.value.minute()})
        for i,m in enumerate(choices):
            b=button(f'{m:02d}',lambda n=m:self.set_minute(n),'timeChoice');b.setCheckable(True);b.setMinimumSize(66,44)
            self.minute_group.addButton(b,m);b.setChecked(m==self.value.minute());minutes.addWidget(b,i//6,i%6)
        main.addLayout(minutes)
        main.addWidget(label('Нажмите час, затем минуты и «Выбрать время».','muted',True))
        main.addLayout(row(button('Отмена',self.reject),button('Выбрать время',self.accept,'primary','check')))
    def set_hour(self,h):self.value=QTime(h,self.value.minute());self.preview.setText(self.value.toString('HH:mm'))
    def set_minute(self,m):self.value=QTime(self.value.hour(),m);self.preview.setText(self.value.toString('HH:mm'))


class TimePicker(QWidget):
    timeChanged=Signal(QTime)
    def __init__(self,value=None,parent=None):
        super().__init__(parent);self._value=QTime(value or QTime(8,0))
        l=QHBoxLayout(self);l.setContentsMargins(0,0,0,0);l.setSpacing(12)
        self.display=button('',self.choose,'secondary','clock');self.display.setMinimumHeight(30)
        self.choose_button=button('Выбрать время',self.choose,ico='clock');self.choose_button.setMinimumHeight(30)
        l.addWidget(self.display,1);l.addWidget(self.choose_button);self.update_text()
    def time(self):return QTime(self._value)
    def setTime(self,value):
        if value.isValid() and value!=self._value:
            self._value=QTime(value);self.update_text();self.timeChanged.emit(self.time())
    def update_text(self):self.display.setText(self._value.toString('HH:mm'))
    def choose(self):
        d=TimeDialog(self.time(),self)
        if d.exec():self.setTime(d.value)
    def wheelEvent(self,event):scroll_page(self,event)


class DateTimePicker(QWidget):
    dateTimeChanged=Signal(QDateTime)
    def __init__(self,value=None,parent=None):
        super().__init__(parent);value=value or QDateTime.currentDateTime()
        self.day_picker=DatePicker(value.date());self.time_picker=TimePicker(value.time())
        l=QVBoxLayout(self);l.setContentsMargins(0,0,0,0);l.setSpacing(12)
        l.addWidget(self.day_picker);l.addWidget(self.time_picker)
        self.day_picker.dateChanged.connect(lambda _:self.dateTimeChanged.emit(self.dateTime()))
        self.time_picker.timeChanged.connect(lambda _:self.dateTimeChanged.emit(self.dateTime()))
    def dateTime(self):return QDateTime(self.day_picker.date(),self.time_picker.time())
    def setDateTime(self,value):
        self.day_picker.setDate(value.date());self.time_picker.setTime(value.time())
