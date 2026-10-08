import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:naryadai_mobile/core/api.dart';
import 'package:naryadai_mobile/core/controller.dart';
import 'package:naryadai_mobile/core/models.dart';
import 'package:naryadai_mobile/core/storage.dart';

void main() {
  final session = Session('https://example.test', 'private-token', {
    'id': 1,
    'role': 'worker',
    'name': 'Сотрудник',
  });
  test(
    'same submission reuses request id after lost response and app restart',
    () async {
      final store = MemoryStore();
      final requests = <Json>[];
      var fail = true;
      final client = MockClient((request) async {
        requests.add(object(jsonDecode(request.body)));
        expect(request.headers['Authorization'], 'Bearer private-token');
        if (fail) {
          fail = false;
          throw http.ClientException('connection lost');
        }
        return http.Response(jsonEncode({'result': 501}), 200);
      });
      final first = ServerApi(session, store, client: client);
      await expectLater(
        first.call('submit', args: [14], kwargs: {'work': 'проверка'}),
        throwsA(isA<ApiException>()),
      );
      final restarted = ServerApi(session, store, client: client);
      expect(
        await restarted.call(
          'submit',
          args: [14],
          kwargs: {'work': 'проверка'},
        ),
        501,
      );
      expect(requests[0]['request_id'], requests[1]['request_id']);
      expect(jsonDecode(store.values.values.single), isEmpty);
    },
  );
  test('read calls do not modify pending mutation receipts', () async {
    final store = MemoryStore();
    final client = MockClient((_) async => http.Response('{"result":[]}', 200));
    await ServerApi(
      session,
      store,
      client: client,
    ).call('free_slots', args: [1, '2026-10-08']);
    expect(store.values, isEmpty);
  });
  test(
    'definitive validation failure clears receipt, changed payload gets new id',
    () async {
      final store = MemoryStore();
      final ids = <String>[];
      final client = MockClient((request) async {
        ids.add(object(jsonDecode(request.body))['request_id']);
        return http.Response.bytes(
          utf8.encode('{"detail":"Проверьте поля"}'),
          400,
        );
      });
      final api = ServerApi(session, store, client: client);
      for (var n = 0; n < 2; n++) {
        await expectLater(
          api.call('submit', kwargs: {'hours': n}),
          throwsA(isA<ApiException>()),
        );
      }
      expect(ids[0], isNot(ids[1]));
      expect(jsonDecode(store.values.values.single), isEmpty);
    },
  );
  test('HTTPS and credential-free admin URL', () async {
    expect(
      adminUri('https://example.test/').toString(),
      'https://example.test/?role=admin&from=android',
    );
    for (final address in [
      'http://192.168.1.2',
      'https://name:secret@example.test',
      'https://example.test?token=secret',
    ]) {
      expect(() => normalizeServer(address), throwsA(isA<ApiException>()));
    }
    await expectLater(
      ServerApi.login('https://example.test', 'admin', 'secret', 'admin'),
      throwsA(isA<ApiException>()),
    );
  });
  test('private drafts separated by account and server', () async {
    final store = MemoryStore();
    final c = AppController(store);
    await c.demo('worker');
    await c.saveDraft('report', 1048, {'work': 'личный черновик'});
    await c.demo('master');
    expect(await c.loadDraft('report', 1048), isEmpty);
    await c.demo('worker');
    expect((await c.loadDraft('report', 1048))['work'], 'личный черновик');
    c.dispose();
  });
  test('overnight schedule and plant timezone', () {
    expect(parseCompanyDate('2026-10-08T18:00:00'), DateTime(2026, 10, 8, 18));
    expect(formatHour(25.5), '01:30 (+1 д.)');
    expect(parseCompanyDate('2026-10-08T10:30:00Z')!.hour, 15);
    expect(parseCompanyDate('2026-10-08T10:30:00')!.hour, 10);
  });
}
