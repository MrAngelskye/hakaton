import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';
import 'package:intl/intl.dart';
import '../core/controller.dart';
import '../core/models.dart';
import 'task_screen.dart';
import 'create_task_screen.dart';
import 'theme.dart';
import 'widgets.dart';

class AppShell extends StatefulWidget {
  final AppController controller;
  const AppShell(this.controller, {super.key});
  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  int tab = 0;
  String filter = 'Активные', query = '';
  AppController get c => widget.controller;
  bool get master => c.session!.isMaster;
  List<Json> get tasks => c.snapshot?.tasks ?? [];
  void openTask(Json task) => Navigator.of(context).push(
    MaterialPageRoute<void>(builder: (_) => TaskScreen(c, integer(task['id']))),
  );
  void openNotifications() => Navigator.of(context).push(
    MaterialPageRoute<void>(
      builder: (_) => NotificationsScreen(c, onTask: openTask),
    ),
  );
  @override
  Widget build(BuildContext context) {
    if (c.session == null) return const Scaffold(body: SizedBox.shrink());
    final user = c.session!.user;
    final labels = master
        ? ['Смена', 'Наряды', 'Приёмка', 'Команда']
        : ['Смена', 'Наряды', 'График', 'Профиль'];
    final icons = master
        ? [
            Icons.dashboard_outlined,
            Icons.assignment_outlined,
            Icons.fact_check_outlined,
            Icons.groups_outlined,
          ]
        : [
            Icons.dashboard_outlined,
            Icons.assignment_outlined,
            Icons.calendar_today_outlined,
            Icons.person_outline_rounded,
          ];
    final bodies = [
      home,
      taskList,
      master ? reviewList : schedule,
      master ? team : profile,
    ];
    return Scaffold(
      appBar: AppBar(
        titleSpacing: 20,
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'НарядAI',
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
            ),
            Text(
              master ? 'Мастер · рабочая смена' : 'Сотрудник · рабочая смена',
              style: const TextStyle(fontSize: 11, color: Brand.muted),
            ),
          ],
        ),
        actions: [
          IconButton(
            tooltip: 'Уведомления',
            onPressed: openNotifications,
            icon: Badge(
              isLabelVisible: (c.snapshot?.notifications.length ?? 0) > 0,
              label: Text('${c.snapshot?.notifications.length ?? 0}'),
              child: const Icon(Icons.notifications_none_rounded),
            ),
          ),
          Padding(
            padding: const EdgeInsets.only(right: 12),
            child: IconButton(
              tooltip: 'Профиль и выход',
              onPressed: () => showModalBottomSheet<void>(
                context: context,
                isScrollControlled: true,
                builder: (_) => SafeArea(
                  child: SingleChildScrollView(
                    padding: const EdgeInsets.all(20),
                    child: profile(),
                  ),
                ),
              ),
              icon: IdentityAvatar(text(user['name']), size: 34),
            ),
          ),
        ],
      ),
      body: SafeArea(
        top: false,
        child: Column(
          children: [
            if (c.session!.isDemo)
              Container(
                width: double.infinity,
                color: const Color(0xFFFFF3DC),
                padding: const EdgeInsets.symmetric(
                  horizontal: 20,
                  vertical: 8,
                ),
                child: const Text(
                  'ДЕМОНСТРАЦИЯ · вымышленные данные',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: Brand.amber,
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            if (!c.online)
              Material(
                color: const Color(0xFFFFF3DC),
                child: InkWell(
                  onTap: () => c.refresh(),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 20,
                      vertical: 10,
                    ),
                    child: Row(
                      children: [
                        const Icon(
                          Icons.cloud_off_outlined,
                          size: 20,
                          color: Brand.amber,
                        ),
                        const SizedBox(width: 10),
                        const Expanded(
                          child: Text(
                            'Нет связи · черновики доступны',
                            style: TextStyle(color: Brand.amber, fontSize: 12),
                          ),
                        ),
                        const Text(
                          'Повторить',
                          style: TextStyle(
                            color: Brand.navy,
                            fontWeight: FontWeight.w700,
                            fontSize: 12,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            if (c.refreshing) const LinearProgressIndicator(minHeight: 2),
            Expanded(
              child: c.snapshot == null
                  ? c.refreshing
                        ? const LoadingView()
                        : Padding(
                            padding: const EdgeInsets.all(20),
                            child: EmptyState(
                              'Не удалось подключиться',
                              c.error ??
                                  'Проверьте интернет и повторите подключение.',
                              icon: Icons.cloud_off_outlined,
                              action: OutlinedButton(
                                onPressed: () => c.refresh(),
                                child: const Text('Повторить подключение'),
                              ),
                            ),
                          )
                  : RefreshIndicator(
                      onRefresh: () => c.refresh(reloadCatalogs: true),
                      child: AnimatedSwitcher(
                        duration: MediaQuery.disableAnimationsOf(context)
                            ? Duration.zero
                            : const Duration(milliseconds: 200),
                        child: ListView(
                          key: ValueKey('$tab'),
                          padding: const EdgeInsets.fromLTRB(20, 12, 20, 96),
                          physics: const AlwaysScrollableScrollPhysics(),
                          children: [bodies[tab]()],
                        ),
                      ),
                    ),
            ),
          ],
        ),
      ),
      floatingActionButton: master && tab < 2
          ? FloatingActionButton.extended(
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute<void>(builder: (_) => CreateTaskScreen(c)),
              ),
              backgroundColor: Brand.navy,
              foregroundColor: Colors.white,
              icon: const Icon(Icons.add_rounded),
              label: const Text('Выдать наряд'),
            )
          : null,
      bottomNavigationBar: NavigationBar(
        selectedIndex: tab,
        onDestinationSelected: (value) => setState(() {
          tab = value;
          filter = 'Активные';
          query = '';
        }),
        destinations: List.generate(
          4,
          (i) => NavigationDestination(icon: Icon(icons[i]), label: labels[i]),
        ),
      ),
    );
  }

  Widget home() {
    final own = tasks.where((t) => master || isMine(t, c.session!.id)).toList();
    final active = own.where(isActive).toList();
    final overdue = active.where((t) => isOverdue(t, c.now)).length;
    final waiting = tasks.where((t) => t['status'] == 'submitted').toList();
    final focus = master
        ? waiting.firstOrNull
        : own
              .where(
                (t) => [
                  'inProgress',
                  'revision',
                  'planned',
                  'accepted',
                  'queued',
                ].contains(t['status']),
              )
              .firstOrNull;
    final name = text(c.session!.user['name']).split(' ').first;
    return Column(
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
                    width: 122,
                    height: 28,
                  ),
                  const Spacer(),
                  Text(
                    DateFormat('d MMM', 'ru').format(c.now),
                    style: const TextStyle(
                      color: Color(0xFFC4D5EB),
                      fontSize: 12,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 28),
              Text(
                'Добрый день, $name',
                style: const TextStyle(color: Color(0xFFC4D5EB), fontSize: 14),
              ),
              const SizedBox(height: 8),
              Text(
                master ? 'Вся смена\nперед вами.' : 'Начнём\nс главного.',
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 29,
                  height: 1.12,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 16),
              Text(
                master
                    ? '${waiting.length} ${waiting.length == 1 ? 'отчёт ожидает' : 'отчётов ожидают'} вашего решения'
                    : 'Наряды, время и результат — в одном месте.',
                style: const TextStyle(color: Color(0xFFC4D5EB), fontSize: 13),
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        Row(
          children: [
            Expanded(
              child: metric(
                '${active.length}',
                master ? 'Активных нарядов' : 'Моих нарядов',
                Icons.assignment_outlined,
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: metric(
                '$overdue',
                'Просрочено',
                Icons.schedule_rounded,
                tone: overdue > 0 ? Brand.red : Brand.green,
              ),
            ),
          ],
        ),
        const SizedBox(height: 24),
        SectionTitle(master ? 'Требует вашего решения' : 'Сейчас в фокусе'),
        if (focus != null)
          TaskTile(focus, c, onTap: () => openTask(focus))
        else
          EmptyState(
            master ? 'Приёмка завершена' : 'Нет текущей работы',
            master
                ? 'Новые отчёты появятся здесь после отправки сотрудником.'
                : 'Откройте доступные наряды или дождитесь назначения мастера.',
            action: TextButton(
              onPressed: () => setState(() {
                tab = master ? 2 : 1;
                filter = master ? 'Активные' : 'Доступные';
              }),
              child: Text(master ? 'Открыть приёмку' : 'Выбрать наряд'),
            ),
          ),
        const SizedBox(height: 24),
        SectionTitle(
          master ? 'Загрузка команды' : 'Дальше по плану',
          action: TextButton(
            onPressed: () => setState(() => tab = master ? 3 : 2),
            child: const Text('Смотреть'),
          ),
        ),
        if (master)
          Surface(
            child: Row(
              children: [
                const Icon(Icons.groups_outlined, color: Brand.navy, size: 32),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${c.snapshot!.employeeStatus.values.where((v) => v == 'free').length} сотрудников свободны',
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      const SizedBox(height: 5),
                      const Text(
                        'Статусы поступают из общей базы',
                        style: TextStyle(color: Brand.muted, fontSize: 12),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          )
        else
          ...own
              .where((t) => isActive(t) && t['id'] != focus?['id'])
              .take(2)
              .map(
                (t) => Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: TaskTile(t, c, onTap: () => openTask(t)),
                ),
              ),
        const SizedBox(height: 18),
        Row(
          children: [
            Icon(
              c.online ? Icons.cloud_done_outlined : Icons.cloud_off_outlined,
              size: 16,
              color: Brand.muted,
            ),
            const SizedBox(width: 7),
            Expanded(
              child: Text(
                c.session!.isDemo
                    ? 'Учебная смена · модель не запускается'
                    : 'Общая база · обновление каждые 20 секунд',
                style: const TextStyle(color: Brand.muted, fontSize: 11),
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget metric(
    String value,
    String label,
    IconData icon, {
    Color tone = Brand.navy,
  }) => Surface(
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, color: tone, size: 22),
        const SizedBox(height: 12),
        Text(
          value,
          style: TextStyle(
            fontSize: 30,
            fontWeight: FontWeight.w800,
            color: tone,
          ),
        ),
        const SizedBox(height: 4),
        Text(label, style: const TextStyle(color: Brand.muted, fontSize: 12)),
      ],
    ),
  );

  Widget taskList() {
    final filters = master
        ? ['Активные', 'Приёмка', 'История']
        : ['Активные', 'Доступные', 'История'];
    final selected = tasks.where((t) {
      final inCategory = filter == 'История'
          ? !isActive(t)
          : filter == 'Доступные'
          ? t['status'] == 'available'
          : filter == 'Приёмка'
          ? ['submitted', 'aiPending'].contains(t['status'])
          : isActive(t) && (master || isMine(t, c.session!.id));
      return inCategory &&
          '${t['title']} ${t['equipment']} ${t['id']} ${t['site']}'
              .toLowerCase()
              .contains(query.toLowerCase());
    }).toList()..sort((a, b) => priorityOrder(a).compareTo(priorityOrder(b)));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SectionTitle(
          'Наряды',
          action: Text(
            '${selected.length}',
            style: const TextStyle(color: Brand.muted),
          ),
        ),
        TextField(
          decoration: const InputDecoration(
            hintText: 'Номер, оборудование или название',
            prefixIcon: Icon(Icons.search_rounded),
          ),
          onChanged: (value) => setState(() => query = value),
        ),
        const SizedBox(height: 14),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: filters
              .map(
                (name) => ChoiceChip(
                  label: Text(name),
                  selected: filter == name,
                  onSelected: (_) => setState(() => filter = name),
                ),
              )
              .toList(),
        ),
        const SizedBox(height: 18),
        if (c.snapshot!.data['truncated'] == true)
          const Padding(
            padding: EdgeInsets.only(bottom: 12),
            child: Text(
              'Показаны последние 500 нарядов. Полная история доступна в веб-панели.',
              style: TextStyle(color: Brand.muted, fontSize: 12),
            ),
          ),
        if (selected.isEmpty)
          const EmptyState(
            'Нарядов пока нет',
            'Попробуйте другой раздел или обновите данные.',
          )
        else
          ...selected.map(
            (t) => Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: TaskTile(t, c, onTap: () => openTask(t)),
            ),
          ),
      ],
    );
  }

  int priorityOrder(Json task) => isOverdue(task, c.now)
      ? 0
      : task['status'] == 'inProgress'
      ? 1
      : task['priority'] == 'urgent'
      ? 2
      : task['status'] == 'revision'
      ? 3
      : 4;

  Widget reviewList() {
    final list = tasks
        .where((t) => ['submitted', 'aiPending'].contains(t['status']))
        .toList();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SectionTitle('Приёмка работ'),
        const Text(
          'ИИ помогает с проверкой. Окончательное решение и оценка — за вами.',
          style: TextStyle(color: Brand.muted),
        ),
        const SizedBox(height: 20),
        if (list.isEmpty)
          const EmptyState(
            'Все отчёты рассмотрены',
            'Когда сотрудник отправит отчёт, он появится здесь.',
            icon: Icons.fact_check_outlined,
          )
        else
          ...list.map(
            (task) => Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: TaskTile(task, c, onTap: () => openTask(task)),
            ),
          ),
      ],
    );
  }

  Widget schedule() {
    final list =
        tasks
            .where(
              (t) =>
                  isMine(t, c.session!.id) &&
                  t['day'] == c.selectedDay &&
                  t['start'] != null &&
                  t['status'] != 'cancelled',
            )
            .toList()
          ..sort((a, b) => number(a['start']).compareTo(number(b['start'])));
    final shift = object(c.snapshot!.shifts['${c.session!.id}']);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SectionTitle('Мой график'),
        OutlinedButton.icon(
          onPressed: () async {
            final date = await showDatePicker(
              context: context,
              initialDate: DateTime.parse(c.selectedDay),
              firstDate: c.now.subtract(const Duration(days: 365)),
              lastDate: c.now.add(const Duration(days: 365)),
            );
            if (date != null) {
              c.selectedDay = dayOf(date);
              await c.refresh();
            }
          },
          icon: const Icon(Icons.calendar_today_outlined, size: 18),
          label: Text(
            DateFormat(
              'EEEE, d MMMM',
              'ru',
            ).format(DateTime.parse(c.selectedDay)),
          ),
        ),
        const SizedBox(height: 16),
        Surface(
          child: DetailLine(
            Icons.access_time_rounded,
            'Смена',
            shift['start'] == null
                ? 'Смена не назначена'
                : '${formatHour(shift['start'])} — ${formatHour(shift['end'])}',
          ),
        ),
        const SizedBox(height: 20),
        if (list.isEmpty)
          const EmptyState(
            'График свободен',
            'Назначенные и принятые наряды появятся на временной шкале.',
          )
        else
          ...list.map(
            (t) => Padding(
              padding: const EdgeInsets.only(bottom: 16),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SizedBox(
                    width: 52,
                    child: Column(
                      children: [
                        Text(
                          formatHour(t['start']),
                          style: const TextStyle(
                            color: Brand.navy,
                            fontWeight: FontWeight.w800,
                            fontSize: 12,
                          ),
                        ),
                        Container(
                          width: 2,
                          height: 140,
                          margin: const EdgeInsets.only(top: 8),
                          color: Brand.border,
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(child: TaskTile(t, c, onTap: () => openTask(t))),
                ],
              ),
            ),
          ),
      ],
    );
  }

  Widget team() {
    final workers = c.snapshot!.users
        .where((u) => u['role'] == 'worker' && enabled(u['active'] ?? 1))
        .toList();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SectionTitle('Команда'),
        const Text(
          'Свободные исполнители, текущие работы и результаты.',
          style: TextStyle(color: Brand.muted),
        ),
        const SizedBox(height: 20),
        if (workers.isEmpty)
          const EmptyState(
            'Сотрудники не добавлены',
            'Администратор создаёт аккаунты и назначает доступы через веб-панель.',
            icon: Icons.groups_outlined,
          ),
        ...workers.map((worker) {
          final workerTasks = tasks
              .where((t) => isMine(t, integer(worker['id'])) && isActive(t))
              .toList();
          final stats =
              c.snapshot!.metrics
                  .where((m) => m['id'] == worker['id'])
                  .firstOrNull ??
              {};
          return Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Surface(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      IdentityAvatar(text(worker['name'])),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              text(worker['name']),
                              style: Theme.of(context).textTheme.titleMedium,
                            ),
                            Text(
                              text(worker['specialty'], text(worker['job'])),
                              style: const TextStyle(
                                color: Brand.muted,
                                fontSize: 12,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 14),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      StatePill(
                        text(
                          c.snapshot!.employeeStatus['${worker['id']}'],
                          'off',
                        ),
                      ),
                      Text(
                        '${workerTasks.length} активных · ${integer(stats['done'])} закрыто',
                        style: const TextStyle(
                          color: Brand.muted,
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ),
                  if (stats['score'] != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 8),
                      child: Text(
                        'Рейтинг за 90 дней: ${number(stats['score']).toStringAsFixed(1)} / 100',
                        style: const TextStyle(
                          fontSize: 12,
                          color: Brand.muted,
                        ),
                      ),
                    ),
                  if (workerTasks.isNotEmpty)
                    TextButton.icon(
                      onPressed: () => openTask(workerTasks.first),
                      icon: const Icon(Icons.arrow_forward_rounded, size: 18),
                      label: const Text('Текущий наряд'),
                    ),
                  OutlinedButton.icon(
                    onPressed: () => editShift(worker),
                    icon: const Icon(Icons.schedule_rounded, size: 18),
                    label: const Text('Настроить смену'),
                  ),
                ],
              ),
            ),
          );
        }),
      ],
    );
  }

  Future<void> editShift(Json worker) async {
    final existing = object(c.snapshot!.shifts['${worker['id']}']);
    final start = await showTimePicker(
      context: context,
      initialTime: TimeOfDay(
        hour: integer(existing['start'], 8) % 24,
        minute: 0,
      ),
    );
    if (!mounted || start == null) return;
    final end = await showTimePicker(
      context: context,
      initialTime: TimeOfDay(
        hour: integer(existing['end'], 18) % 24,
        minute: 0,
      ),
    );
    if (!mounted || end == null) return;
    try {
      await c.mutate(
        'set_shift',
        args: [
          worker['id'],
          c.selectedDay,
          start.hour + start.minute / 60,
          end.hour + end.minute / 60,
        ],
      );
      if (mounted) message(context, 'Смена сохранена');
    } catch (e) {
      if (mounted) message(context, e.toString(), error: true);
    }
  }

  Widget profile() {
    final user = c.session!.user;
    final stats =
        c.snapshot?.metrics.where((m) => m['id'] == user['id']).firstOrNull ??
        {};
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SectionTitle('Профиль'),
        Surface(
          child: Row(
            children: [
              IdentityAvatar(text(user['name']), size: 54),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      text(user['name']),
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: 6),
                    Text(
                      text(user['job']),
                      style: const TextStyle(color: Brand.muted, fontSize: 12),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 20),
        if (!master) ...[
          const SectionTitle('Мои результаты'),
          const Text(
            'За последние 90 дней · по решениям мастера',
            style: TextStyle(color: Brand.muted, fontSize: 12),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: metric(
                  '${integer(stats['done'])}',
                  'Принято работ',
                  Icons.task_alt_rounded,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: metric(
                  stats['score'] == null
                      ? '—'
                      : number(stats['score']).toStringAsFixed(1),
                  'Рейтинг / 100',
                  Icons.insights_rounded,
                ),
              ),
            ],
          ),
          const SizedBox(height: 20),
        ],
        Surface(
          child: Column(
            children: [
              DetailLine(
                Icons.badge_outlined,
                'Роль',
                master ? 'Мастер' : 'Сотрудник',
              ),
              DetailLine(
                Icons.business_outlined,
                'Предприятие',
                'АО «Костанайские минералы»',
              ),
              DetailLine(
                Icons.cloud_outlined,
                'Подключение',
                c.session!.isDemo
                    ? 'Локальная демонстрация'
                    : c.session!.baseUrl,
              ),
            ],
          ),
        ),
        const SizedBox(height: 20),
        OutlinedButton.icon(
          onPressed: () => c.logout(),
          icon: const Icon(Icons.logout_rounded),
          label: const Text('Выйти из аккаунта'),
        ),
        const SizedBox(height: 12),
        const Text(
          'НарядAI · ByteX · Android 1.0\nЧерновики сохраняются на вашем устройстве.',
          textAlign: TextAlign.center,
          style: TextStyle(color: Brand.muted, fontSize: 12),
        ),
      ],
    );
  }
}

class NotificationsScreen extends StatelessWidget {
  final AppController controller;
  final void Function(Json) onTask;
  const NotificationsScreen(this.controller, {super.key, required this.onTask});
  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: controller,
    builder: (context, _) => Scaffold(
      appBar: AppBar(title: const Text('Уведомления')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          if ((controller.snapshot?.notifications ?? []).isEmpty)
            const EmptyState(
              'Вы всё прочитали',
              'Здесь появятся назначения, напоминания и комментарии мастера.',
              icon: Icons.notifications_none_rounded,
            ),
          ...(controller.snapshot?.notifications ?? []).map(
            (item) => Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Surface(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Row(
                      children: [
                        Icon(
                          item['severity'] == 'critical'
                              ? Icons.priority_high_rounded
                              : Icons.notifications_none_rounded,
                          color: item['severity'] == 'critical'
                              ? Brand.red
                              : Brand.navy,
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Text(
                            text(
                              item['title'],
                              text(
                                object(item['payload'])['title'],
                                'Уведомление',
                              ),
                            ),
                            style: Theme.of(context).textTheme.titleMedium,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 10),
                    Text(
                      text(
                        item['body'],
                        text(object(item['payload'])['comment']),
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      formatDate(item['created_at']),
                      style: const TextStyle(color: Brand.muted, fontSize: 12),
                    ),
                    const SizedBox(height: 10),
                    Wrap(
                      spacing: 8,
                      children: [
                        if (item['task_id'] != null)
                          TextButton(
                            onPressed: () {
                              final t = controller.snapshot?.task(
                                integer(item['task_id']),
                              );
                              if (t != null) onTask(t);
                            },
                            child: const Text('Открыть наряд'),
                          ),
                        TextButton(
                          onPressed: controller.busy
                              ? null
                              : () async {
                                  try {
                                    await controller.mutate(
                                      'acknowledge_notification',
                                      args: [item['id']],
                                    );
                                  } catch (e) {
                                    if (context.mounted) {
                                      message(
                                        context,
                                        e.toString(),
                                        error: true,
                                      );
                                    }
                                  }
                                },
                          child: const Text('Прочитано'),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    ),
  );
}
