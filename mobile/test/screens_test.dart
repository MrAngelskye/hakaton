import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:naryadai_mobile/core/controller.dart';
import 'package:naryadai_mobile/core/storage.dart';
import 'package:naryadai_mobile/main.dart';
import 'package:naryadai_mobile/ui/create_task_screen.dart';
import 'package:naryadai_mobile/ui/report_screen.dart';

void main() {
  setUpAll(() => initializeDateFormatting('ru'));
  for (final role in ['worker', 'master']) {
    testWidgets('$role navigation at 360px and enlarged text', (tester) async {
      tester.view.physicalSize = const Size(360, 800);
      tester.view.devicePixelRatio = 1;
      tester.platformDispatcher.textScaleFactorTestValue = 1.3;
      addTearDown(() {
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
        tester.platformDispatcher.clearTextScaleFactorTestValue();
      });
      final c = AppController(MemoryStore());
      c.booting = false;
      await c.demo(role);
      await tester.pumpWidget(NaryadApp(c));
      await tester.pumpAndSettle();
      for (final label
          in role == 'worker'
              ? ['Наряды', 'График', 'Профиль', 'Смена']
              : ['Наряды', 'Приёмка', 'Команда', 'Смена']) {
        await tester.tap(
          find
              .descendant(
                of: find.byType(NavigationBar),
                matching: find.text(label),
              )
              .first,
        );
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
      }
      await tester.pumpWidget(const SizedBox());
      c.dispose();
    });
  }
  testWidgets(
    'report draft survives immediate back without waiting for debounce',
    (tester) async {
      final store = MemoryStore();
      final c = AppController(store);
      c.booting = false;
      await c.demo('worker');
      await tester.pumpWidget(NaryadApp(c));
      await tester.pumpAndSettle();
      final context = tester.element(find.byType(NavigationBar));
      Navigator.of(
        context,
      ).push(MaterialPageRoute<void>(builder: (_) => ReportScreen(c, 1048)));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byType(TextFormField).first,
        'Проверил привод и записал показания',
      );
      await tester.tap(find.byTooltip('Сохранить и вернуться'));
      await tester.pumpAndSettle();
      expect(
        (await c.loadDraft('report', 1048))['work'],
        'Проверил привод и записал показания',
      );
      await tester.pumpWidget(const SizedBox());
      c.dispose();
    },
  );
  testWidgets('master create form validates before network mutation', (
    tester,
  ) async {
    final c = AppController(MemoryStore());
    c.booting = false;
    await c.demo('master');
    await tester.pumpWidget(NaryadApp(c));
    await tester.pumpAndSettle();
    final context = tester.element(find.byType(NavigationBar));
    Navigator.of(
      context,
    ).push(MaterialPageRoute<void>(builder: (_) => CreateTaskScreen(c)));
    await tester.pumpAndSettle();
    await tester.drag(
      find
          .descendant(
            of: find.byType(CreateTaskScreen),
            matching: find.byType(Scrollable),
          )
          .first,
      const Offset(0, -1200),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Создать наряд'));
    await tester.pumpAndSettle();
    expect(find.text('Укажите название от 5 символов'), findsOneWidget);
    expect(c.busy, isFalse);
    await tester.pumpWidget(const SizedBox());
    c.dispose();
  });
}
