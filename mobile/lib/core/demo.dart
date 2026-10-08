import 'dart:convert';
import 'dart:typed_data';
import 'api.dart';
import 'models.dart';

/// In-memory, explicitly synthetic preview. It never contacts the real server.
class DemoApi implements Backend {
  @override
  final Session session;
  late Json data;
  final String today = dayOf(companyNow());
  DemoApi(String role)
    : session = Session('demo://local', 'demo-session', {
        'id': role == 'master' ? 201 : 101,
        'name': role == 'master' ? 'Марина Лебедева' : 'Дмитрий Соколов',
        'role': role,
        'job': role == 'master'
            ? 'Мастер ремонтной смены'
            : 'Слесарь-ремонтник',
        'username': 'demo.$role',
      }) {
    final users = [
      session.user,
      if (role == 'master')
        {
          'id': 101,
          'name': 'Дмитрий Соколов',
          'role': 'worker',
          'job': 'Слесарь-ремонтник',
          'active': 1,
        },
      {
        'id': 102,
        'name': 'Алексей Морозов',
        'role': 'worker',
        'job': 'Электромонтёр',
        'active': 1,
      },
      {
        'id': 103,
        'name': 'Сергей Волков',
        'role': 'worker',
        'job': 'Механик',
        'active': 1,
      },
    ];
    final tasks = [
      _task(
        1048,
        'Проверить привод конвейера',
        'Конвейер К-12',
        'Дробильно-сортировочный комплекс',
        'inProgress',
        'high',
        101,
        9,
        1.5,
      ),
      _task(
        1049,
        'Осмотреть насосный узел',
        'Насос Н-04',
        'Обогатительная фабрика',
        'planned',
        'normal',
        101,
        11,
        1,
      ),
      _task(
        1050,
        'Проверить датчик положения',
        'Конвейер К-08',
        'Дробильно-сортировочный комплекс',
        'submitted',
        'urgent',
        102,
        8,
        1,
      ),
      _task(
        1051,
        'Осмотреть крепления ограждения',
        'Дробилка Д-02',
        'Дробильно-сортировочный комплекс',
        'available',
        'scheduled',
        null,
        null,
        1,
      ),
      _task(
        1046,
        'Проверить соединения редуктора',
        'Редуктор Р-03',
        'Ремонтно-механический цех',
        'revision',
        'normal',
        101,
        14,
        1,
      ),
      _task(
        1044,
        'Плановый осмотр электропривода',
        'Электропривод Э-06',
        'Карьер',
        'approved',
        'normal',
        101,
        8,
        1,
      ),
    ];
    data = {
      'tasks': tasks,
      'users': users,
      'reports': [
        {
          'id': 501,
          'task_id': 1050,
          'worker_id': 102,
          'worker_name': 'Алексей Морозов',
          'title': 'Проверить датчик положения',
          'status': 'submitted',
          'work':
              'Проверил соединение датчика, восстановил крепление и очистил контактную группу.',
          'result': 'Сигнал стабилен при контрольной проверке по карте работ.',
          'defect': 'D-01 · Ослабление крепления',
          'hours': .8,
          'materials': [],
          'photos': [],
          'photo_issues': [],
          'ai': {
            'status': 'completed',
            'score': 86,
            'summary':
                'Учебный пример: работы и контроль описаны. Реальную проверку модели демо не выполняет.',
            'findings': [],
            'quality_1_5': 4,
          },
        },
        {
          'id': 502,
          'task_id': 1046,
          'worker_id': 101,
          'worker_name': 'Дмитрий Соколов',
          'status': 'revision',
          'work': 'Осмотрел соединения редуктора.',
          'result': 'Выполнено.',
          'defect': 'D-01 · Ослабление крепления',
          'hours': .5,
          'materials': [],
          'photos': [],
          'comment':
              'Добавьте результат контрольной проверки и фото соединения.',
        },
        {
          'id': 503,
          'task_id': 1044,
          'worker_id': 101,
          'status': 'approved',
          'score': 94,
          'comment': 'Работа принята. Проверка описана понятно.',
          'work': 'Осмотрел электропривод по утверждённой карте.',
          'result': 'Отклонений не зафиксировано.',
          'hours': 1,
          'materials': [],
          'photos': [],
        },
      ],
      'metrics': [
        {
          'id': 101,
          'name': 'Дмитрий Соколов',
          'done': 12,
          'score': 91.2,
          'employee_status': 'busy',
          'on_time': 92,
        },
        {
          'id': 102,
          'name': 'Алексей Морозов',
          'done': 9,
          'score': 88.4,
          'employee_status': 'free',
        },
        {
          'id': 103,
          'name': 'Сергей Волков',
          'done': 7,
          'score': 90.1,
          'employee_status': 'free',
        },
      ],
      'employee_status': {'101': 'busy', '102': 'free', '103': 'free'},
      'shifts': {
        '101': {'start': 8, 'end': 18},
        '102': {'start': 8, 'end': 18},
        '103': {'start': 8, 'end': 18},
      },
      'free_slots': {
        '101': [
          [12, 14],
          [15, 18],
        ],
        '102': [
          [10, 18],
        ],
        '103': [
          [8, 18],
        ],
      },
      'notifications': [
        {
          'id': 601,
          'task_id': 1049,
          'kind': 'issued',
          'title': 'Новый наряд на смену',
          'body': 'Осмотреть насосный узел Н-04',
          'created_at': '${today}T08:30:00',
          'severity': 'info',
        },
        {
          'id': 602,
          'task_id': 1046,
          'kind': 'revision',
          'title': 'Отчёт требует уточнения',
          'body': 'Мастер оставил комментарий по редуктору Р-03',
          'created_at': '${today}T09:00:00',
          'severity': 'warning',
        },
      ],
      'ai_enabled': false,
      'truncated': false,
      'server_time':
          DateTime.parse('${today}T09:30:00+05:00').millisecondsSinceEpoch /
          1000,
    };
  }
  Json _task(
    int id,
    String title,
    String equipment,
    String site,
    String status,
    String priority,
    int? worker,
    double? start,
    double hours,
  ) => {
    'id': id,
    'title': title,
    'description':
        'Учебный наряд. Выполнить осмотр по утверждённой карте работ, записать наблюдения и результат контрольной проверки. Порядок работ и допуски определяет мастер.',
    'equipment': equipment,
    'site': site,
    'site_id': site == 'Обогатительная фабрика' ? 2 : 1,
    'equipment_id': id == 1049 ? 2 : 1,
    'status': status,
    'priority': priority,
    'worker_id': worker,
    'worker_name': worker == 101
        ? 'Дмитрий Соколов'
        : worker == 102
        ? 'Алексей Морозов'
        : null,
    'kind': priority == 'urgent' ? 'Внеплановая' : 'Плановая',
    'duration': hours,
    'start': start,
    'day': today,
    'deadline': '${today}T18:00:00',
    'created': '${today}T08:00:00',
    'issued_at': '${today}T08:00:00',
    'started_at': status == 'inProgress' ? '${today}T09:00:00' : null,
    'data_origin': 'synthetic',
    'master_id': 201,
  };
  @override
  Future<Json> snapshot(String day) async {
    final copy = object(jsonDecode(jsonEncode(data)));
    if (!session.isMaster) {
      copy['tasks'] = records(copy['tasks'])
          .where((t) => isMine(t, session.id) || t['status'] == 'available')
          .toList();
      copy['reports'] = records(
        copy['reports'],
      ).where((r) => integer(r['worker_id']) == session.id).toList();
      copy['metrics'] = records(
        copy['metrics'],
      ).where((r) => integer(r['id']) == session.id).toList();
    }
    return copy;
  }

  @override
  Future<Json> catalogs() async => {
    'sites': [
      {'id': 1, 'name': 'Дробильно-сортировочный комплекс'},
      {'id': 2, 'name': 'Обогатительная фабрика'},
    ],
    'equipment': [
      {
        'id': 1,
        'name': 'Конвейер К-12',
        'site_id': 1,
        'inventory_number': 'DEMO-K12',
        'equipment_type': 'Конвейер',
      },
      {
        'id': 2,
        'name': 'Насос Н-04',
        'site_id': 2,
        'inventory_number': 'DEMO-N04',
        'equipment_type': 'Насос',
      },
    ],
    'defect_codes': [
      {'id': 1, 'code': 'D-01', 'name': 'Ослабление крепления'},
      {'id': 2, 'code': 'D-02', 'name': 'Заявленная течь'},
    ],
    'materials': [
      {'id': 1, 'name': 'Уплотнение', 'unit': 'шт', 'unit_price': 0},
      {'id': 2, 'name': 'Крепёж', 'unit': 'шт', 'unit_price': 0},
    ],
    'brigades': [],
    'work_norms': [],
  };
  @override
  Future<dynamic> get(String path) async {
    if (path.startsWith('/api/analytics')) {
      return {
        'counts': {'approved': 12, 'overdue': 1},
        'workers': data['metrics'],
        'failures': [],
      };
    }
    if (path.startsWith('/api/chat')) {
      return {'messages': [], 'pending': false, 'ai_enabled': false};
    }
    return {};
  }

  @override
  Future<dynamic> call(
    String method, {
    List<dynamic> args = const [],
    Json kwargs = const {},
    List<Json> photos = const [],
    String? operationContext,
  }) async {
    await Future<void>.delayed(const Duration(milliseconds: 300));
    final tasks = (data['tasks'] as List).cast<Json>();
    final reports = (data['reports'] as List).cast<Json>();
    final task = args.isEmpty
        ? null
        : tasks
              .where((t) => integer(t['id']) == integer(args.first))
              .firstOrNull;
    switch (method) {
      case 'transition':
        if (task != null) task['status'] = args[1];
        break;
      case 'claim':
        if (task != null) {
          task['worker_id'] = session.id;
          task['status'] = 'accepted';
          task['day'] = args[1];
          task['start'] = args[2];
        }
        break;
      case 'submit':
        if (task == null) throw const ApiException('Учебный наряд не найден.');
        for (final previous in reports.where(
          (r) => r['task_id'] == task['id'] && r['status'] == 'revision',
        )) {
          previous['status'] = 'superseded';
        }
        task['status'] = 'submitted';
        final id = 700 + reports.length;
        reports.add({
          'id': id,
          'task_id': task['id'],
          'worker_id': session.id,
          'status': 'submitted',
          ...kwargs,
          'photos': [],
          'ai': {'status': 'skipped', 'error': 'В демо модель не запускается.'},
        });
        return id;
      case 'review':
        final report = reports
            .where((r) => integer(r['id']) == integer(args[0]))
            .first;
        report['status'] = args[1] == true ? 'approved' : 'revision';
        report['score'] = args[1] == true ? args[2] : null;
        report['comment'] = args[3];
        tasks.firstWhere((t) => t['id'] == report['task_id'])['status'] =
            report['status'];
        break;
      case 'create_task':
        final id = 1100 + tasks.length;
        tasks.add({
          'id': id,
          ...kwargs,
          'status': kwargs['worker_id'] == null ? 'available' : 'planned',
          'data_origin': 'synthetic',
        });
        return id;
      case 'change_priority':
        if (task != null) task['priority'] = args[1];
        break;
      case 'reassign_task':
        if (task != null) {
          task['worker_id'] = args[1];
          task['day'] = args[2];
          task['start'] = args[3];
          task['status'] = 'planned';
        }
        break;
      case 'events':
        return [
          {
            'id': 1,
            'message': 'Учебный наряд создан мастером',
            'created': '${today}T08:00:00',
            'name': 'Мастер смены',
          },
        ];
      case 'photos_for_task':
        return [];
      case 'free_slots':
        return data['free_slots']['${args[0]}'] ?? [];
      case 'acknowledge_notification':
        (data['notifications'] as List).removeWhere((n) => n['id'] == args[0]);
        break;
      case 'acknowledge_notifications':
        data['notifications'] = [];
        break;
      case 'set_shift':
        data['shifts']['${args[0]}'] = {'start': args[2], 'end': args[3]};
        break;
      case 'equipment_history':
        return {'tasks': tasks, 'reports': reports};
      default:
        throw const ApiException(
          'Эта операция доступна при подключении к серверу.',
        );
    }
    return null;
  }

  @override
  Future<Uint8List> photo(String key) async => Uint8List(0);
  @override
  Future<void> logout() async {}
  @override
  void close() {}
}
