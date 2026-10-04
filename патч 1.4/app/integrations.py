"""Независимые точки подключения. Модели и провайдеры пока не выбраны."""
from enum import Enum
from typing import Protocol

class Capability(str,Enum):
    ACCOUNTING='accounting'
    IMAGES='images'
    SUMMARY='summary'
    CUSTOM='custom'

# Категории возможностей не назначают конкретную модель или поставщика.
INTEGRATION_AREAS=(
    ('Изображения','Распознавание и анализ фотографий'),
    ('Тексты и отчёты','Обработка описаний и подготовка результатов'),
    ('Расчёты и данные','Обработка чисел и табличных данных'),
    ('Другие модули','Дополнительные возможности приложения'),
)
# Совместимость с расширениями предыдущей версии: список не содержит выбранных ИИ.
PLANNED_PROVIDERS=()

class Provider(Protocol):
    def run(self,payload:dict)->dict: ...

class IntegrationRegistry:
    def __init__(self):self._providers:dict[Capability,Provider]={}
    def register(self,capability:Capability,provider:Provider):self._providers[capability]=provider
    def run(self,capability:Capability,payload:dict)->dict:
        if capability not in self._providers:raise RuntimeError('Модуль ещё не подключён.')
        return self._providers[capability].run(payload)
