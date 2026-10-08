import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'package:crypto/crypto.dart';
import 'package:http/http.dart' as http;
import 'package:uuid/uuid.dart';
import 'models.dart';
import 'storage.dart';

class ApiException implements Exception {
  final String message;
  final int status;
  const ApiException(this.message, [this.status = 0]);
  bool get isNetwork => status == 0 || status >= 500;
  @override
  String toString() => message;
}

String normalizeServer(String value) {
  final uri = Uri.tryParse(value.trim());
  if (uri == null ||
      uri.host.isEmpty ||
      uri.userInfo.isNotEmpty ||
      uri.hasQuery ||
      uri.hasFragment ||
      !['https', 'http'].contains(uri.scheme)) {
    throw const ApiException(
      'Укажите адрес сервера, например https://hakaton-cj24.onrender.com.',
    );
  }
  if (uri.scheme != 'https' &&
      !['localhost', '127.0.0.1', '10.0.2.2'].contains(uri.host)) {
    throw const ApiException('Для общего сервера требуется HTTPS.');
  }
  return uri.toString().replaceFirst(RegExp(r'/+$'), '');
}

Uri adminUri(String server) => Uri.parse(
  '${normalizeServer(server)}/',
).replace(queryParameters: {'role': 'admin', 'from': 'android'});

dynamic canonical(dynamic value) {
  if (value is Map) {
    return {
      for (final key in (value.keys.map((e) => '$e').toList()..sort()))
        key: canonical(value[key]),
    };
  }
  if (value is List) return value.map(canonical).toList();
  return value;
}

String fingerprint(dynamic value) =>
    sha256.convert(utf8.encode(jsonEncode(canonical(value)))).toString();

abstract class Backend {
  Session get session;
  Future<Json> snapshot(String day);
  Future<Json> catalogs();
  Future<dynamic> get(String path);
  Future<dynamic> call(
    String method, {
    List<dynamic> args = const [],
    Json kwargs = const {},
    List<Json> photos = const [],
  });
  Future<Uint8List> photo(String key);
  Future<void> logout();
  void close();
}

class ServerApi implements Backend {
  @override
  final Session session;
  final http.Client client;
  final PrivateStore store;
  ServerApi(this.session, this.store, {http.Client? client})
    : client = client ?? http.Client();
  String get _pendingKey => 'pending.${fingerprint(session.identity)}';

  static Future<Session> login(
    String server,
    String username,
    String password,
    String role, {
    http.Client? client,
  }) async {
    if (!['worker', 'master'].contains(role)) {
      throw const ApiException('Администратор входит через веб-панель.');
    }
    final base = normalizeServer(server);
    final transport = client ?? http.Client();
    try {
      final request = http.Request('POST', Uri.parse('$base/api/login'));
      request.followRedirects = false;
      request.headers['Content-Type'] = 'application/json';
      request.body = jsonEncode({
        'username': username.trim(),
        'password': password,
        'role': role,
      });
      final response = await transport
          .send(request)
          .then(http.Response.fromStream)
          .timeout(const Duration(seconds: 90));
      final body = decode(response);
      final session = Session.fromJson({'baseUrl': base, ...body});
      if (session == null || session.role != role) {
        throw const ApiException('Сервер вернул неподходящий профиль.');
      }
      return session;
    } on TimeoutException {
      throw const ApiException(
        'Сервер не ответил. Повторите вход: запуск сервера может занять около минуты.',
      );
    } on http.ClientException {
      throw const ApiException(
        'Нет связи с сервером. Проверьте интернет и адрес.',
      );
    } finally {
      if (client == null) transport.close();
    }
  }

  static dynamic decode(http.Response response) {
    dynamic body;
    try {
      body = jsonDecode(utf8.decode(response.bodyBytes));
    } catch (_) {
      throw ApiException(
        'Сервер вернул непонятный ответ. Повторите подключение.',
        response.statusCode,
      );
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final detail = object(body)['detail'];
      throw ApiException(
        detail is String
            ? detail
            : response.statusCode == 401
            ? 'Сессия завершена. Войдите снова.'
            : 'Проверьте поля и повторите действие.',
        response.statusCode,
      );
    }
    return body;
  }

  Future<http.Response> _request(String path, {Json? body}) async {
    final request = http.Request(
      body == null ? 'GET' : 'POST',
      Uri.parse('${session.baseUrl}$path'),
    );
    request.followRedirects = false;
    request.headers['Authorization'] = 'Bearer ${session.token}';
    if (body != null) {
      request.headers['Content-Type'] = 'application/json';
      request.body = jsonEncode(body);
    }
    try {
      final response = await client
          .send(request)
          .then(http.Response.fromStream)
          .timeout(const Duration(seconds: 90));
      if (response.statusCode >= 300 && response.statusCode < 400) {
        throw const ApiException(
          'Сервер изменил адрес. Обновите его в настройках подключения.',
        );
      }
      return response;
    } on TimeoutException {
      throw const ApiException(
        'Сервер не ответил вовремя. При отправке повторите тот же отчёт: дубликат не создаётся.',
      );
    } on http.ClientException {
      throw const ApiException(
        'Нет связи. Черновик сохранён; повторите действие после подключения.',
      );
    }
  }

  @override
  Future<dynamic> get(String path) async => decode(await _request(path));
  @override
  Future<Json> snapshot(String day) async =>
      object(await get('/api/snapshot?day=$day&limit=500'));
  @override
  Future<Json> catalogs() async => object(await get('/api/catalogs'));
  @override
  Future<dynamic> call(
    String method, {
    List<dynamic> args = const [],
    Json kwargs = const {},
    List<Json> photos = const [],
  }) async {
    const readMethods = {
      'task',
      'events',
      'pauses',
      'shift',
      'free_slots',
      'employee_status',
      'catalogs',
      'photos_for_task',
      'notifications',
      'analytics',
      'metrics',
      'equipment_history',
      'task_downtimes',
    };
    if (readMethods.contains(method)) {
      return object(
        decode(
          await _request(
            '/api/call/$method',
            body: {
              'args': args,
              'kwargs': kwargs,
              'photos': photos,
              'request_id': const Uuid().v4().replaceAll('-', ''),
            },
          ),
        ),
      )['result'];
    }
    final payload = {
      'method': method,
      'args': args,
      'kwargs': kwargs,
      'photos': photos,
    };
    final hash = fingerprint(payload);
    final receipts = object(jsonDecode(await store.read(_pendingKey) ?? '{}'));
    final id = text(receipts[hash], const Uuid().v4().replaceAll('-', ''));
    receipts[hash] = id;
    await store.write(_pendingKey, jsonEncode(receipts));
    try {
      final body = decode(
        await _request(
          '/api/call/$method',
          body: {
            'args': args,
            'kwargs': kwargs,
            'photos': photos,
            'request_id': id,
          },
        ),
      );
      final latest = object(jsonDecode(await store.read(_pendingKey) ?? '{}'));
      latest.remove(hash);
      await store.write(_pendingKey, jsonEncode(latest));
      return object(body)['result'];
    } on ApiException catch (error) {
      if (error.status >= 400 && error.status < 500 && error.status != 429) {
        final latest = object(
          jsonDecode(await store.read(_pendingKey) ?? '{}'),
        );
        latest.remove(hash);
        await store.write(_pendingKey, jsonEncode(latest));
      }
      rethrow;
    }
  }

  @override
  Future<Uint8List> photo(String key) async {
    final response = await _request('/api/photos/${Uri.encodeComponent(key)}');
    if (response.statusCode != 200) {
      decode(response);
      throw const ApiException('Фото недоступно.');
    }
    return response.bodyBytes;
  }

  @override
  Future<void> logout() async {
    try {
      await _request('/api/logout', body: {});
    } catch (_) {
      /* local logout always succeeds */
    }
  }

  @override
  void close() => client.close();
}
