import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'api.dart';
import 'demo.dart';
import 'models.dart';
import 'storage.dart';

class AppController extends ChangeNotifier {
  final PrivateStore store;
  Backend? api;
  Snapshot? snapshot;
  Json catalogs = {};
  bool booting = true,
      refreshing = false,
      busy = false,
      online = true,
      foreground = true;
  String? error;
  String selectedDay = dayOf(companyNow());
  int clockOffset = 0;
  Timer? _timer;
  bool _disposed = false;
  AppController(this.store);
  Session? get session => api?.session;
  DateTime get now => companyNow(clockOffset);
  String get _cacheKey => 'cache.${fingerprint(session!.identity)}';
  String draftKey(String kind, int id) =>
      'draft.${fingerprint(session!.identity)}.$kind.$id';
  void changed() {
    if (!_disposed) notifyListeners();
  }

  Future<void> initialize() async {
    try {
      final saved = await store.read('session');
      final session = saved == null
          ? null
          : Session.fromJson(object(jsonDecode(saved)));
      if (session != null) {
        api = ServerApi(session, store);
        final cached = await store.read(_cacheKey);
        if (cached != null) {
          final data = object(jsonDecode(cached));
          snapshot = Snapshot(object(data['snapshot']));
          catalogs = object(data['catalogs']);
        }
      }
    } catch (_) {
      error =
          'Не удалось восстановить вход. Войдите под своей учётной записью.';
    }
    booting = false;
    changed();
    if (api != null) {
      await refresh();
      startPolling();
    }
  }

  Future<void> login(
    String server,
    String username,
    String password,
    String role,
  ) async {
    if (busy) return;
    busy = true;
    error = null;
    changed();
    try {
      final session = await ServerApi.login(server, username, password, role);
      await store.write('session', jsonEncode(session.toJson()));
      api?.close();
      api = ServerApi(session, store);
      snapshot = null;
      catalogs = {};
      await refresh();
      startPolling();
    } catch (e) {
      error = e.toString();
      rethrow;
    } finally {
      busy = false;
      changed();
    }
  }

  Future<void> demo(String role) async {
    api?.close();
    api = DemoApi(role);
    snapshot = null;
    catalogs = {};
    error = null;
    await refresh();
  }

  void startPolling() {
    _timer?.cancel();
    _timer = Timer.periodic(const Duration(seconds: 20), (_) {
      if (foreground && !busy) refresh();
    });
  }

  void setForeground(bool value) {
    foreground = value;
    if (value && api != null) refresh();
  }

  Future<void> refresh({bool reloadCatalogs = false}) async {
    if (api == null || refreshing) return;
    final backend = api!;
    refreshing = true;
    changed();
    try {
      final raw = await backend.snapshot(selectedDay);
      final refs = catalogs.isEmpty || reloadCatalogs
          ? await backend.catalogs()
          : catalogs;
      if (backend != api) return;
      snapshot = Snapshot(raw);
      catalogs = refs;
      online = true;
      error = null;
      if (raw['server_time'] is num) {
        clockOffset =
            (number(raw['server_time']) * 1000).round() -
            DateTime.now().millisecondsSinceEpoch;
      }
      if (!backend.session.isDemo) {
        await store.write(
          _cacheKey,
          jsonEncode({'snapshot': raw, 'catalogs': refs}),
        );
      }
    } on ApiException catch (e) {
      if (backend != api) return;
      online = false;
      error = e.message;
      if (e.status == 401) await logout(remote: false);
    } catch (_) {
      online = false;
      error =
          'Не удалось обновить данные. Сохранённый черновик доступен на устройстве.';
    } finally {
      refreshing = false;
      changed();
    }
  }

  Future<dynamic> mutate(
    String method, {
    List<dynamic> args = const [],
    Json kwargs = const {},
    List<Json> photos = const [],
  }) async {
    if (api == null) throw const ApiException('Войдите в приложение.');
    if (busy) {
      throw const ApiException('Дождитесь завершения предыдущего действия.');
    }
    busy = true;
    changed();
    try {
      final result = await api!.call(
        method,
        args: args,
        kwargs: kwargs,
        photos: photos,
      );
      await refresh();
      return result;
    } on ApiException catch (e) {
      if (e.status == 401) await logout(remote: false);
      rethrow;
    } finally {
      busy = false;
      changed();
    }
  }

  Future<Json> loadDraft(String kind, int id) async {
    final value = await store.read(draftKey(kind, id));
    try {
      return value == null ? {} : object(jsonDecode(value));
    } catch (_) {
      return {};
    }
  }

  Future<void> saveDraft(String kind, int id, Json data) =>
      store.write(draftKey(kind, id), jsonEncode(data));
  Future<void> deleteDraft(String kind, int id) =>
      store.delete(draftKey(kind, id));
  Future<void> logout({bool remote = true}) async {
    _timer?.cancel();
    final previous = api;
    if (previous != null && !previous.session.isDemo) {
      await store.delete(_cacheKey);
      await store.delete('session');
    }
    api = null;
    clockOffset = 0;
    snapshot = null;
    catalogs = {};
    online = true;
    changed();
    if (remote && previous != null) await previous.logout();
    previous?.close();
  }

  @override
  void dispose() {
    _disposed = true;
    _timer?.cancel();
    api?.close();
    super.dispose();
  }
}
