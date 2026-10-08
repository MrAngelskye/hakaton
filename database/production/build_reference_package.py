"""Rebuild public reference package; never generate operational incidents."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CASE = 'CASE1-REQUIREMENTS'

# Invented display names, not names of company employees. Login identifiers stay stable.
FICTIONAL_NAMES = [
    'Белозёров Артём Сергеевич',
    'Корнеев Павел Андреевич',
    'Лебедева Марина Викторовна',
    'Соколов Дмитрий Игоревич',
    'Морозов Алексей Павлович',
    'Волков Сергей Николаевич',
    'Орлов Андрей Михайлович',
    'Крылов Денис Олегович',
    'Фролов Максим Евгеньевич',
    'Белов Николай Петрович',
    'Захаров Роман Владимирович',
    'Тихонов Иван Анатольевич',
    'Макаров Антон Дмитриевич',
    'Ермаков Олег Вячеславович',
    'Комаров Евгений Валерьевич',
    'Савельев Михаил Борисович',
    'Новиков Кирилл Романович',
    'Петрова Светлана Александровна',
]
FICTIONAL_IDENTITY_NOTE = (
    'ФИО полностью вымышлено, совпадения случайны. Источник подтверждает только название '
    'должности, а не личность. Разряд, бригада и смена не подтверждены.'
)

TOPICS = [
 ('Насос','Диагностика заявленной течи насоса','Внеплановая'),
 ('Насос','Осмотр доступных соединений насосного узла','Плановая'),
 ('Конвейер','Диагностика заявленного схода конвейерной ленты','Внеплановая'),
 ('Конвейер','Осмотр состояния роликов конвейера','Плановая'),
 ('Конвейер','Осмотр ограждений и креплений конвейера','Плановая'),
 ('Дробильное оборудование','Диагностика заявленной вибрации дробильного оборудования','Внеплановая'),
 ('Дробильное оборудование','Осмотр доступных элементов дробильного оборудования','Плановая'),
 ('Подшипниковый узел','Диагностика заявленного перегрева подшипникового узла','Внеплановая'),
 ('Подшипниковый узел','Контроль состояния подшипникового узла по утверждённой карте','Плановая'),
 ('Редуктор','Диагностика заявленной течи редуктора','Внеплановая'),
 ('Редуктор','Осмотр доступных соединений редуктора','Плановая'),
 ('Электродвигатель','Диагностика заявленного перегрева электродвигателя','Внеплановая'),
 ('Электрооборудование','Осмотр обозначений и доступных ограждений электрооборудования','Плановая'),
 ('КИПиА','Проверка зарегистрированного отказа датчика','Внеплановая'),
 ('КИПиА','Проверка показаний прибора по утверждённой методике','Плановая'),
 ('Трубопровод','Осмотр заявленного повреждения трубопровода','Внеплановая'),
 ('Горно-транспортное оборудование','Осмотр зарегистрированного дефекта горно-транспортной машины','Внеплановая'),
 ('Автотранспорт','Осмотр автотранспортной техники по утверждённой карте ТО','Плановая'),
 ('Подвижной состав','Осмотр заявленного дефекта подвижного состава','Внеплановая'),
 ('Сварное соединение','Осмотр зарегистрированного повреждения сварного соединения','Внеплановая'),
]
DEFECTS = [
 ('Отклонений не зафиксировано','Общее'),('Заявленный износ подшипника','Механика'),
 ('Заявленный перегрев','Механика'),('Заявленная вибрация','Механика'),
 ('Заявленный шум','Механика'),('Заявленная течь масла','Герметичность'),
 ('Заявленная течь жидкости','Герметичность'),('Повреждение уплотнения','Герметичность'),
 ('Повреждение ленты','Конвейер'),('Сход ленты','Конвейер'),('Повреждение ролика','Конвейер'),
 ('Повреждение ограждения','Ограждения'),('Ослабление крепления','Механика'),
 ('Загрязнение доступного узла','Общее'),('Заявленный отказ датчика','КИПиА'),
 ('Заявленный отказ привода','Электрооборудование'),('Видимое повреждение кабеля','Электрооборудование'),
 ('Видимая коррозия','Общее'),('Видимая трещина','Общее'),('Требуется уточнение причины','Общее'),
]


def build():
    raw = json.loads((ROOT/'public_sources.json').read_text(encoding='utf-8'))
    sources = [{k:r.get(k) for k in ('source_id','title','url','publisher','source_kind','retrieved_at','published_at','license_id','evidence')} for r in raw['sources']]
    sources.append({'source_id':CASE,'title':'Кейс 1 «НарядAI» — требования заказчика',
        'url':'https://drive.google.com/drive/folders/1Xx-QKkGMSk2Df6X9jIH2TbpQxZI_zaV1',
        'publisher':'АО «Костанайские минералы» / Qostanai Industry Hackathon',
        'source_kind':'user_provided_case','retrieved_at':'2026-10-07','published_at':None,
        'license_id':'facts_only_no_image_rights',
        'evidence':'Кейс задаёт роли, поля наряда и требования к отчёту. Предлагает тестовую историю; внутренние производственные записи и личные данные не предоставлены.'})
    by_job = {r['code']:r for r in raw['job_titles']}
    accounts = []
    def account(role, number, job, source):
        accounts.append({'username':f'{role}.{number:02}', 'name':FICTIONAL_NAMES[len(accounts)],
            'job':job,'role':role,'source_id':source,'identity_status':'unassigned_anonymized_profile',
            'identity_origin':'fictional','note':FICTIONAL_IDENTITY_NOTE})
    account('admin',1,'Администратор системы',CASE)
    for i,key in enumerate(('master_electric','shift_senior_master'),1):
        row=by_job[key];account('master',i,row['name'],row['source_id'])
    worker_jobs=[r for r in raw['job_titles'] if r['code'] not in ('master_electric','shift_senior_master')]
    for i in range(15):
        row=worker_jobs[i%len(worker_jobs)];account('worker',i+1,row['name'],row['source_id'])
    categories=list(dict.fromkeys(row[0] for row in TOPICS))
    equipment=[{'code':f'REF-TYPE-{i:02}','name':name,'source_id':CASE,'company_context':False,
                'note':'Категория для регистрации объекта. Не инвентарная единица и не подтверждение наличия оборудования на предприятии.'} for i,name in enumerate(categories,1)]
    templates=[]
    for i,(category,title,kind) in enumerate(TOPICS,1):
        templates.append({'template_id':f'TPL-{i:03}','title':title,'equipment_category':category,'kind':kind,'source_id':CASE,
            'problem_description':f'Черновик: {title.lower()}. Мастер указывает фактическую заявку, инвентарный номер, наблюдаемые признаки, срок и исполнителя. Порядок работы и допуски берутся из утверждённой документации предприятия.',
            'closeout_requirements':['Описать фактически выполненные действия.','Указать фактическое время и использованные материалы.',
                'Зафиксировать результат контрольной проверки по утверждённой методике.','Приложить собственные фото этого оборудования; не использовать снимки справочного фотокаталога.',
                'Передать результат на проверку мастеру.']})
    return {'schema_version':1,'researched_on':raw['researched_on'],'company':raw['company'],
        'boundaries_ru':raw['boundaries_ru'],'sources':sources,'sites':raw['sites'],'job_titles':raw['job_titles'],
        'materials':raw['materials'],'accounts':accounts,'equipment_types':equipment,'work_order_templates':templates,
        'defect_codes':[{'code':f'APP-{i:02}','name':name,'category':cat,'source_id':CASE} for i,(name,cat) in enumerate(DEFECTS)],
        'operational_tasks':[],'operational_reports':[]}


if __name__=='__main__':
    target=ROOT/'reference_catalog.json'
    target.write_text(json.dumps(build(),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Reference catalog rebuilt. No passwords or operational records generated.')
