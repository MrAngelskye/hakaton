import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'core/controller.dart';
import 'core/storage.dart';
import 'ui/login_screen.dart';
import 'ui/shell.dart';
import 'ui/theme.dart';
import 'ui/widgets.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await initializeDateFormatting('ru');
  final controller = AppController(SecureStore());
  runApp(NaryadApp(controller));
  await controller.initialize();
}

class NaryadApp extends StatefulWidget {
  final AppController controller;
  const NaryadApp(this.controller, {super.key});
  @override
  State<NaryadApp> createState() => _NaryadAppState();
}

class _NaryadAppState extends State<NaryadApp> with WidgetsBindingObserver {
  final navigator = GlobalKey<NavigatorState>();
  String? identity;
  void sessionChanged() {
    final next = widget.controller.session?.identity;
    if (identity != null && next != identity) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) navigator.currentState?.popUntil((route) => route.isFirst);
      });
    }
    identity = next;
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    identity = widget.controller.session?.identity;
    widget.controller.addListener(sessionChanged);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    widget.controller.removeListener(sessionChanged);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) =>
      widget.controller.setForeground(state == AppLifecycleState.resumed);
  @override
  Widget build(BuildContext context) => MaterialApp(
    navigatorKey: navigator,
    title: 'НарядAI',
    debugShowCheckedModeBanner: false,
    theme: Brand.theme(),
    locale: const Locale('ru'),
    supportedLocales: const [Locale('ru'), Locale('en')],
    localizationsDelegates: GlobalMaterialLocalizations.delegates,
    home: AnimatedBuilder(
      animation: widget.controller,
      builder: (context, _) {
        final child = widget.controller.booting
            ? const Scaffold(body: LoadingView(label: 'Открываем НарядAI…'))
            : widget.controller.session == null
            ? LoginScreen(widget.controller)
            : AppShell(widget.controller);
        return AnimatedSwitcher(
          duration: MediaQuery.disableAnimationsOf(context)
              ? Duration.zero
              : const Duration(milliseconds: 220),
          child: child,
        );
      },
    ),
  );
}
