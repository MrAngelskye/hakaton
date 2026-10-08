import 'package:intl/intl.dart';

typedef Json = Map<String, dynamic>;

Json object(dynamic value) =>
    value is Map ? Map<String, dynamic>.from(value) : {};
List<Json> records(dynamic value) =>
    value is List ? value.map(object).toList() : [];
int integer(dynamic value, [int fallback = 0]) =>
    value is num ? value.toInt() : int.tryParse('$value') ?? fallback;
double number(dynamic value, [double fallback = 0]) =>
    value is num ? value.toDouble() : double.tryParse('$value') ?? fallback;
String text(dynamic value, [String fallback = '']) =>
    value == null ? fallback : '$value';
bool enabled(dynamic value) => value == true || value == 1;

const serverDefault = String.fromEnvironment(
  'SERVER_URL',
  defaultValue: 'https://hakaton-cj24.onrender.com',
);
const statuses = {
  'available': 'Доступен',
  'planned': 'Выдан',
  'accepted': 'Принят',
  'queued': 'В очереди',
  'rejected': 'Отказ исполнителя',
  'inProgress': 'В работе',
  'paused': 'Приостановлен',
  'aiPending': 'Проверяет ИИ',
  'submitted': 'У мастера',
  'revision': 'На доработку',
  'approved': 'Закрыт',
  'cancelled': 'Отменён',
  'superseded': 'Предыдущая версия',
};
const priorities = {
  'urgent': 'Аварийный',
  'high': 'Высокий',
  'normal': 'Обычный',
  'scheduled': 'Плановый',
};
const availabilityNames = {
  'free': 'Свободен',
  'busy': 'В работе',
  'queued': 'Есть наряды',
  'off': 'Не на смене',
};

// Local DateTime values carry the enterprise's wall-clock fields. This keeps
// date-picker values comparable even when the phone's timezone differs.
DateTime wallDate(DateTime value) => DateTime(
  value.year,
  value.month,
  value.day,
  value.hour,
  value.minute,
  value.second,
  value.millisecond,
);
DateTime companyNow([int offsetMillis = 0]) => wallDate(
  DateTime.now().toUtc().add(Duration(hours: 5, milliseconds: offsetMillis)),
);
String dayOf(DateTime value) => DateFormat('yyyy-MM-dd').format(value);
DateTime? parseCompanyDate(dynamic value) {
  final source = text(value);
  if (source.isEmpty) return null;
  final zoned = RegExp(r'(Z|[+-]\d{2}:\d{2})$').hasMatch(source);
  final instant = DateTime.tryParse(
    zoned ? source : '$source+05:00',
  )?.toUtc().add(const Duration(hours: 5));
  return instant == null ? null : wallDate(instant);
}

String formatDate(dynamic value) {
  final date = parseCompanyDate(value);
  return date == null
      ? 'Не указано'
      : DateFormat('d MMM, HH:mm', 'ru').format(date);
}

String formatHour(dynamic value) {
  if (value == null) return 'Без времени';
  final minutes = (number(value) * 60).round();
  final day = minutes ~/ (24 * 60);
  return '${((minutes ~/ 60) % 24).toString().padLeft(2, '0')}:${(minutes % 60).toString().padLeft(2, '0')}${day > 0 ? ' (+$day д.)' : ''}';
}

bool isActive(Json task) => !['approved', 'cancelled'].contains(task['status']);
bool isMine(Json task, int userId) =>
    integer(task['worker_id']) == userId ||
    (task['member_ids'] is List && task['member_ids'].contains(userId));
bool isOverdue(Json task, DateTime at) =>
    ![
      'approved',
      'cancelled',
      'aiPending',
      'submitted',
    ].contains(task['status']) &&
    (parseCompanyDate(task['deadline'])?.isBefore(at) ?? false);
String deadlineText(Json task, DateTime now) {
  if (task['status'] == 'approved') return 'Работа принята';
  if (['aiPending', 'submitted'].contains(task['status'])) {
    return 'Отчёт отправлен';
  }
  final due = parseCompanyDate(task['deadline']);
  if (due == null) return 'Срок не указан';
  final minutes = due.difference(now).inMinutes;
  if (minutes < 0) return 'Просрочен · ${(-minutes / 60).ceil()} ч';
  if (minutes < 60) return 'Осталось $minutes мин';
  if (minutes < 1440) return 'Осталось ${minutes ~/ 60} ч ${minutes % 60} мин';
  return 'До ${formatDate(task['deadline'])}';
}

class Session {
  final String baseUrl, token;
  final Json user;
  const Session(this.baseUrl, this.token, this.user);
  int get id => integer(user['id']);
  String get role => text(user['role']);
  bool get isMaster => role == 'master';
  bool get isDemo => token == 'demo-session';
  String get identity => '$baseUrl|$id|$role';
  Json toJson() => {'baseUrl': baseUrl, 'token': token, 'user': user};
  static Session? fromJson(Json value) {
    final user = object(value['user']);
    if (!['worker', 'master'].contains(user['role']) ||
        integer(user['id']) < 1 ||
        text(value['token']).isEmpty) {
      return null;
    }
    return Session(text(value['baseUrl']), text(value['token']), user);
  }
}

class Snapshot {
  final Json data;
  const Snapshot(this.data);
  List<Json> get tasks => records(data['tasks']);
  List<Json> get reports => records(data['reports']);
  List<Json> get users => records(data['users']);
  List<Json> get metrics => records(data['metrics']);
  List<Json> get notifications => records(data['notifications']);
  Json get shifts => object(data['shifts']);
  Json get employeeStatus => object(data['employee_status']);
  Json? task(int id) => tasks.where((t) => integer(t['id']) == id).firstOrNull;
  Json? report(int taskId) => reports
      .where(
        (r) =>
            integer(r['task_id']) == taskId &&
            !['superseded', 'cancelled'].contains(r['status']),
      )
      .firstOrNull;
}
