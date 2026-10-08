import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';
import 'package:url_launcher/url_launcher.dart';
import '../core/api.dart';
import '../core/controller.dart';
import '../core/models.dart';
import '../core/storage.dart';
import 'theme.dart';
import 'widgets.dart';

class LoginScreen extends StatefulWidget {
  final AppController controller;
  const LoginScreen(this.controller, {super.key});
  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final form = GlobalKey<FormState>();
  final username = TextEditingController(), password = TextEditingController();
  final server = TextEditingController(text: serverDefault);
  String role = 'worker';
  bool reveal = false, showServer = false;
  @override
  void initState() {
    super.initState();
    Preferences.server().then((value) {
      if (mounted && value.isNotEmpty) server.text = value;
    });
  }

  @override
  void dispose() {
    username.dispose();
    password.dispose();
    server.dispose();
    super.dispose();
  }

  Future<void> submit() async {
    if (!form.currentState!.validate()) return;
    try {
      await Preferences.saveServer(normalizeServer(server.text));
      await widget.controller.login(
        server.text,
        username.text,
        password.text,
        role,
      );
    } catch (e) {
      if (mounted) message(context, e.toString(), error: true);
    }
  }

  Future<void> openAdmin() async {
    try {
      if (!await launchUrl(
        adminUri(server.text),
        mode: LaunchMode.externalApplication,
      )) {
        throw const ApiException(
          'Не удалось открыть браузер. Проверьте адрес сервера.',
        );
      }
    } catch (e) {
      if (mounted) message(context, e.toString(), error: true);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: SafeArea(
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 520),
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
            child: Form(
              key: form,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Container(
                    padding: const EdgeInsets.all(24),
                    decoration: BoxDecoration(
                      color: Brand.deep,
                      borderRadius: BorderRadius.circular(24),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            SvgPicture.asset(
                              'assets/km-logo-white.svg',
                              width: 126,
                              height: 34,
                            ),
                            const Spacer(),
                            const Text(
                              'НарядAI',
                              style: TextStyle(
                                color: Colors.white,
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 30),
                        const Text(
                          'Ваша смена.\nВсё под контролем.',
                          style: TextStyle(
                            color: Colors.white,
                            fontSize: 29,
                            height: 1.15,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                        const SizedBox(height: 12),
                        const Text(
                          'Наряды, отчёты и решения мастера\nв одном приложении.',
                          style: TextStyle(
                            color: Color(0xFFC4D5EB),
                            fontSize: 14,
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 28),
                  Text(
                    'Вход в рабочую смену',
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'Выберите свою роль',
                    style: TextStyle(color: Brand.muted),
                  ),
                  const SizedBox(height: 16),
                  Row(
                    children: [
                      Expanded(
                        child: roleCard(
                          'worker',
                          'Сотрудник',
                          Icons.engineering_outlined,
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: roleCard(
                          'master',
                          'Мастер',
                          Icons.assignment_ind_outlined,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 20),
                  TextFormField(
                    controller: username,
                    autofillHints: const [AutofillHints.username],
                    textInputAction: TextInputAction.next,
                    decoration: const InputDecoration(
                      labelText: 'Логин',
                      prefixIcon: Icon(Icons.person_outline_rounded),
                    ),
                    validator: (v) =>
                        v == null || v.trim().isEmpty ? 'Введите логин' : null,
                  ),
                  const SizedBox(height: 14),
                  TextFormField(
                    controller: password,
                    obscureText: !reveal,
                    autofillHints: const [AutofillHints.password],
                    onFieldSubmitted: (_) => submit(),
                    decoration: InputDecoration(
                      labelText: 'Пароль',
                      prefixIcon: const Icon(Icons.lock_outline_rounded),
                      suffixIcon: IconButton(
                        tooltip: reveal ? 'Скрыть пароль' : 'Показать пароль',
                        onPressed: () => setState(() => reveal = !reveal),
                        icon: Icon(
                          reveal
                              ? Icons.visibility_off_outlined
                              : Icons.visibility_outlined,
                        ),
                      ),
                    ),
                    validator: (v) =>
                        v == null || v.isEmpty ? 'Введите пароль' : null,
                  ),
                  const SizedBox(height: 20),
                  ActionButton(
                    'Войти',
                    icon: Icons.arrow_forward_rounded,
                    busy: widget.controller.busy,
                    onPressed: submit,
                  ),
                  if (widget.controller.error != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 12),
                      child: Text(
                        widget.controller.error!,
                        style: const TextStyle(color: Brand.red),
                      ),
                    ),
                  const SizedBox(height: 16),
                  OutlinedButton.icon(
                    onPressed: widget.controller.busy ? null : openAdmin,
                    icon: const Icon(Icons.open_in_browser_rounded, size: 20),
                    label: const Text('Администратор · веб-панель'),
                  ),
                  const SizedBox(height: 8),
                  TextButton(
                    onPressed: () => setState(() => showServer = !showServer),
                    child: const Text('Настройки подключения'),
                  ),
                  if (showServer)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 16),
                      child: TextFormField(
                        controller: server,
                        keyboardType: TextInputType.url,
                        decoration: const InputDecoration(
                          labelText: 'Адрес сервера',
                          helperText: 'Общий адрес для приложения и веб-панели',
                        ),
                      ),
                    ),
                  const Divider(),
                  TextButton.icon(
                    onPressed: widget.controller.busy
                        ? null
                        : () => widget.controller.demo(role),
                    icon: const Icon(Icons.play_circle_outline_rounded),
                    label: const Text('Посмотреть демонстрацию'),
                  ),
                  const Text(
                    'В демонстрации используются вымышленные данные.\nДля работы войдите с личным логином и паролем.',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Brand.muted, fontSize: 12),
                  ),
                  const SizedBox(height: 16),
                  const Text(
                    'ByteX · Костанайские минералы',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Brand.muted, fontSize: 12),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    ),
  );
  Widget roleCard(String value, String label, IconData icon) {
    final selected = role == value;
    return Semantics(
      selected: selected,
      button: true,
      child: Material(
        color: selected ? Brand.navy : Colors.white,
        borderRadius: BorderRadius.circular(16),
        child: InkWell(
          borderRadius: BorderRadius.circular(16),
          onTap: widget.controller.busy
              ? null
              : () => setState(() => role = value),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 180),
            padding: const EdgeInsets.symmetric(vertical: 18, horizontal: 8),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: selected ? Brand.navy : Brand.border),
            ),
            child: Column(
              children: [
                Icon(
                  icon,
                  size: 28,
                  color: selected ? Colors.white : Brand.navy,
                ),
                const SizedBox(height: 10),
                Text(
                  label,
                  style: TextStyle(
                    color: selected ? Colors.white : Brand.ink,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
