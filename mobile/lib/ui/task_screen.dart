import 'dart:typed_data';
import 'package:flutter/material.dart';
import '../core/controller.dart';
import '../core/models.dart';
import 'report_screen.dart';
import 'theme.dart';
import 'widgets.dart';

class TaskScreen extends StatefulWidget {
  final AppController controller;
  final int taskId;
  const TaskScreen(this.controller, this.taskId, {super.key});
  @override
  State<TaskScreen> createState() => _TaskScreenState();
}

class _TaskScreenState extends State<TaskScreen> {
  AppController get c => widget.controller;
  List<Json> photos = [], history = [];
  String? detailError;
  bool detailLoading = false;
  @override
  void initState() {
    super.initState();
    loadDetails();
  }

  Future<void> loadDetails() async {
    if (c.api == null) return;
    setState(() {
      detailLoading = true;
      detailError = null;
    });
    try {
      final values = await Future.wait([
        c.api!.call('photos_for_task', args: [widget.taskId]),
        c.api!.call('events', args: [widget.taskId]),
      ]);
      if (mounted) {
        setState(() {
          photos = records(values[0]);
          history = records(values[1]);
        });
      }
    } catch (e) {
      if (mounted) setState(() => detailError = e.toString());
    } finally {
      if (mounted) setState(() => detailLoading = false);
    }
  }

  Future<void> action(
    String method, {
    List<dynamic> args = const [],
    Json kwargs = const {},
  }) async {
    try {
      await c.mutate(method, args: args, kwargs: kwargs);
      await loadDetails();
      if (mounted) message(context, 'Изменение сохранено');
    } catch (e) {
      if (mounted) message(context, e.toString(), error: true);
    }
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: c,
    builder: (context, _) {
      final task = c.snapshot?.task(widget.taskId);
      if (c.session == null || task == null) {
        return Scaffold(
          appBar: AppBar(title: const Text('Наряд')),
          body: const Padding(
            padding: EdgeInsets.all(20),
            child: EmptyState(
              'Наряд недоступен',
              'Обновите список нарядов или войдите снова.',
            ),
          ),
        );
      }
      final master = c.session!.isMaster;
      final status = text(task['status']);
      final report = c.snapshot!.report(widget.taskId);
      return Scaffold(
        appBar: AppBar(
          title: Text('Наряд НР-${task['id']}'),
          actions: [
            IconButton(
              tooltip: 'Обновить наряд',
              onPressed: () async {
                await c.refresh();
                await loadDetails();
              },
              icon: const Icon(Icons.refresh_rounded),
            ),
          ],
        ),
        body: ListView(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 28),
          children: [
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                StatePill(status),
                StatePill(text(task['priority']), priority: true),
              ],
            ),
            const SizedBox(height: 16),
            Text(
              text(task['title']),
              style: Theme.of(context).textTheme.headlineMedium,
            ),
            const SizedBox(height: 20),
            progress(status),
            const SizedBox(height: 20),
            Surface(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  DetailLine(
                    Icons.precision_manufacturing_outlined,
                    'Оборудование',
                    text(task['equipment']),
                  ),
                  DetailLine(
                    Icons.location_on_outlined,
                    'Участок',
                    text(task['site']),
                  ),
                  DetailLine(
                    Icons.schedule_rounded,
                    'Срок выполнения',
                    formatDate(task['deadline']),
                  ),
                  DetailLine(
                    Icons.calendar_today_outlined,
                    'План работ',
                    '${task['day']} · ${formatHour(task['start'])} · ${task['duration']} ч',
                  ),
                  if (master)
                    DetailLine(
                      Icons.person_outline_rounded,
                      'Исполнитель',
                      text(
                        task['worker_name'],
                        task['worker_id'] == null
                            ? 'Не назначен'
                            : '#${task['worker_id']}',
                      ),
                    ),
                ],
              ),
            ),
            const SizedBox(height: 20),
            const SectionTitle('Что нужно выполнить'),
            Surface(child: Text(text(task['description']))),
            if (task['rejection_reason'] != null &&
                text(task['rejection_reason']).isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 16),
                child: Surface(
                  child: DetailLine(
                    Icons.info_outline_rounded,
                    'Причина отказа',
                    text(task['rejection_reason']),
                  ),
                ),
              ),
            const SizedBox(height: 20),
            if (detailLoading) const LinearProgressIndicator(),
            if (photos.isNotEmpty) ...[
              const SectionTitle('Подтверждение работ'),
              Wrap(
                spacing: 12,
                runSpacing: 12,
                children: photos.map((p) => PhotoPreview(c, p)).toList(),
              ),
              const SizedBox(height: 20),
            ],
            if (report != null) ...[
              const SectionTitle('Отчёт сотрудника'),
              reportCard(report),
              const SizedBox(height: 20),
            ],
            if (detailError != null)
              Surface(
                child: Column(
                  children: [
                    Text(
                      'История и фото: $detailError',
                      style: const TextStyle(color: Brand.muted),
                    ),
                    TextButton(
                      onPressed: loadDetails,
                      child: const Text('Повторить загрузку'),
                    ),
                  ],
                ),
              ),
            if (history.isNotEmpty) ...[
              const SectionTitle('История наряда'),
              Surface(
                child: Column(
                  children: history.reversed
                      .take(10)
                      .map(
                        (e) => Padding(
                          padding: const EdgeInsets.symmetric(vertical: 8),
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Icon(
                                Icons.circle,
                                size: 9,
                                color: Brand.navy,
                              ),
                              const SizedBox(width: 12),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(text(e['message'])),
                                    const SizedBox(height: 4),
                                    Text(
                                      '${formatDate(e['created'])} · ${text(e['name'])}',
                                      style: const TextStyle(
                                        color: Brand.muted,
                                        fontSize: 11,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ],
                          ),
                        ),
                      )
                      .toList(),
                ),
              ),
            ],
            const SizedBox(height: 24),
            if (!master) workerActions(task) else masterActions(task, report),
          ],
        ),
      );
    },
  );
  Widget progress(String status) {
    final stage = status == 'approved'
        ? 3
        : ['aiPending', 'submitted'].contains(status)
        ? 2
        : ['inProgress', 'paused', 'revision'].contains(status)
        ? 1
        : 0;
    const titles = ['Наряд', 'Работа', 'Проверка', 'Принят'];
    const icons = [
      Icons.assignment_outlined,
      Icons.build_outlined,
      Icons.fact_check_outlined,
      Icons.task_alt_rounded,
    ];
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: List.generate(
        4,
        (i) => Expanded(
          child: Column(
            children: [
              Container(
                width: 34,
                height: 34,
                decoration: BoxDecoration(
                  color: i <= stage ? Brand.navy : Brand.soft,
                  shape: BoxShape.circle,
                ),
                child: Icon(
                  icons[i],
                  size: 18,
                  color: i <= stage ? Colors.white : Brand.muted,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                titles[i],
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 10,
                  fontWeight: FontWeight.w700,
                  color: i <= stage ? Brand.navy : Brand.muted,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget reportCard(Json report) {
    final ai = object(report['ai']);
    final issues = records(report['photo_issues']);
    return Surface(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            'Выполненные работы',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 8),
          Text(text(report['work'])),
          const SizedBox(height: 16),
          Text(
            'Результат проверки',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 8),
          Text(text(report['result'])),
          const Divider(),
          DetailLine(
            Icons.timer_outlined,
            'Фактически затрачено',
            '${report['hours']} ч',
          ),
          DetailLine(
            Icons.report_problem_outlined,
            'Неисправность',
            text(report['defect'], 'Не указана'),
          ),
          if (records(report['materials']).isNotEmpty) ...[
            const Divider(),
            Text('Материалы', style: Theme.of(context).textTheme.titleMedium),
            ...records(report['materials']).map(
              (m) => Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text('${m['name']} · ${m['quantity']} ${m['unit']}'),
              ),
            ),
          ],
          const Divider(),
          Row(
            children: [
              const Icon(
                Icons.auto_awesome_outlined,
                color: Brand.purple,
                size: 22,
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  'Предварительная проверка ИИ',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          if (['queued', 'processing'].contains(ai['status']))
            const Text(
              'ИИ анализирует отчёт. Окончательное решение принимает мастер.',
              style: TextStyle(color: Brand.purple),
            )
          else if (ai['status'] == 'completed') ...[
            if (ai['score'] != null)
              Text(
                '${ai['score']} / 100',
                style: const TextStyle(
                  fontSize: 28,
                  fontWeight: FontWeight.w800,
                  color: Brand.purple,
                ),
              ),
            const SizedBox(height: 6),
            Text(text(ai['summary'])),
            ...((ai['findings'] is List ? ai['findings'] : []) as List)
                .take(8)
                .map(
                  (f) => Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(
                      '• ${f is Map ? text(f['message'], text(f['description'], text(f['field']))) : f}',
                    ),
                  ),
                ),
          ] else
            Text(
              text(
                ai['error'],
                'Автоматическая проверка не выполнена. Отчёт проверяет мастер.',
              ),
              style: const TextStyle(color: Brand.muted),
            ),
          if (issues.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: Text(
                'Фото требуют внимания: ${issues.length} замечаний. Проверьте наличие, время и соответствие снимков.',
                style: const TextStyle(color: Brand.amber),
              ),
            ),
          if (text(report['comment']).isNotEmpty) ...[
            const Divider(),
            Text(
              'Комментарий мастера',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            Text(text(report['comment'])),
          ],
          if (report['score'] != null)
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: Text(
                'Оценка мастера: ${report['score']} / 100',
                style: const TextStyle(
                  fontWeight: FontWeight.w700,
                  color: Brand.green,
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget workerActions(Json task) {
    final status = text(task['status']);
    if (status == 'available') {
      return ActionButton(
        'Взять наряд',
        icon: Icons.add_task_rounded,
        busy: c.busy,
        onPressed: () => claim(task),
      );
    }
    if (!isMine(task, c.session!.id)) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if ([
          'planned',
          'accepted',
          'queued',
          'paused',
          'revision',
        ].contains(status))
          ActionButton(
            status == 'paused' ? 'Продолжить работу' : 'Начать работу',
            icon: Icons.play_arrow_rounded,
            busy: c.busy,
            onPressed: () =>
                action('transition', args: [task['id'], 'inProgress']),
          ),
        if (['planned', 'accepted'].contains(status))
          Padding(
            padding: const EdgeInsets.only(top: 10),
            child: OutlinedButton.icon(
              onPressed: c.busy
                  ? null
                  : () => action('transition', args: [task['id'], 'queued']),
              icon: const Icon(Icons.playlist_add_rounded),
              label: const Text('Поставить в очередь'),
            ),
          ),
        if (['planned', 'accepted', 'queued'].contains(status))
          TextButton(
            onPressed: c.busy
                ? null
                : () async {
                    final reason = await askReason(
                      context,
                      'Отказаться от наряда',
                    );
                    if (reason != null) {
                      await action(
                        'transition',
                        args: [task['id'], 'rejected'],
                        kwargs: {'reason': reason},
                      );
                    }
                  },
            child: const Text('Отказаться с указанием причины'),
          ),
        if (status == 'inProgress') ...[
          ActionButton(
            'Подготовить отчёт',
            icon: Icons.edit_note_rounded,
            onPressed: () async {
              await Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => ReportScreen(c, widget.taskId),
                ),
              );
              await loadDetails();
            },
          ),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            onPressed: c.busy
                ? null
                : () async {
                    final reason = await askReason(
                      context,
                      'Приостановить работу',
                    );
                    if (reason != null) {
                      await action(
                        'transition',
                        args: [task['id'], 'paused'],
                        kwargs: {'reason': reason},
                      );
                    }
                  },
            icon: const Icon(Icons.pause_rounded),
            label: const Text('Приостановить'),
          ),
        ],
        if (status == 'revision')
          Padding(
            padding: const EdgeInsets.only(top: 10),
            child: ActionButton(
              'Исправить отчёт',
              icon: Icons.edit_note_rounded,
              onPressed: () async {
                await Navigator.of(context).push(
                  MaterialPageRoute<void>(
                    builder: (_) => ReportScreen(c, widget.taskId),
                  ),
                );
                await loadDetails();
              },
            ),
          ),
        if (['aiPending', 'submitted'].contains(status))
          const Surface(
            child: Text(
              'Отчёт отправлен. Здесь появятся результат проверки, комментарий и решение мастера.',
            ),
          ),
      ],
    );
  }

  Widget masterActions(Json task, Json? report) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      if (task['status'] == 'submitted' && report != null) ...[
        ActionButton(
          'Проверить и принять',
          icon: Icons.task_alt_rounded,
          busy: c.busy,
          onPressed: () => review(report, true),
        ),
        const SizedBox(height: 10),
        OutlinedButton.icon(
          onPressed: c.busy ? null : () => review(report, false),
          icon: const Icon(Icons.assignment_return_outlined),
          label: const Text('Вернуть на доработку'),
        ),
      ],
      if (isActive(task) &&
          !['aiPending', 'submitted'].contains(task['status'])) ...[
        OutlinedButton.icon(
          onPressed: c.busy ? null : () => assign(task),
          icon: const Icon(Icons.person_add_alt_rounded),
          label: const Text('Назначить / переназначить'),
        ),
        const SizedBox(height: 10),
        OutlinedButton.icon(
          onPressed: c.busy ? null : () => choosePriority(task),
          icon: const Icon(Icons.flag_outlined),
          label: const Text('Изменить приоритет'),
        ),
        TextButton(
          onPressed: c.busy
              ? null
              : () async {
                  final reason = await askReason(context, 'Отменить наряд');
                  if (reason != null) {
                    await action(
                      'transition',
                      args: [task['id'], 'cancelled'],
                      kwargs: {'reason': reason},
                    );
                  }
                },
          child: const Text('Отменить с указанием причины'),
        ),
      ],
    ],
  );
  Future<void> review(Json report, bool approve) async {
    final comment = TextEditingController();
    final score = TextEditingController(
      text: object(report['ai'])['score'] == null
          ? ''
          : '${integer(object(report['ai'])['score'])}',
    );
    final form = GlobalKey<FormState>();
    final accepted = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(approve ? 'Принять работу' : 'Вернуть на доработку'),
        content: SingleChildScrollView(
          child: Form(
            key: form,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                if (approve) ...[
                  const Text(
                    'Подтвердите фактическое выполнение, контрольную проверку и фото. Оценку выставляете вы.',
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    controller: score,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: 'Оценка мастера · 0–100',
                    ),
                    validator: (v) {
                      final n = int.tryParse(v ?? '');
                      return n == null || n < 0 || n > 100
                          ? 'Укажите целое число от 0 до 100'
                          : null;
                    },
                  ),
                  const SizedBox(height: 16),
                ],
                TextFormField(
                  controller: comment,
                  minLines: 2,
                  maxLines: 5,
                  maxLength: 2000,
                  decoration: InputDecoration(
                    labelText: approve
                        ? 'Комментарий к результату'
                        : 'Что нужно исправить',
                  ),
                  validator: (v) => (v?.trim().length ?? 0) < 3
                      ? 'Добавьте комментарий от 3 символов'
                      : null,
                ),
              ],
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () {
              if (form.currentState!.validate()) Navigator.pop(ctx, true);
            },
            child: Text(approve ? 'Принять' : 'Вернуть'),
          ),
        ],
      ),
    );
    if (accepted == true && mounted) {
      await action(
        'review',
        args: [
          report['id'],
          approve,
          int.tryParse(score.text) ?? 0,
          comment.text.trim(),
        ],
      );
    }
    Future<void>.delayed(const Duration(milliseconds: 400), () {
      comment.dispose();
      score.dispose();
    });
  }

  Future<void> choosePriority(Json task) async {
    final priority = await showModalBottomSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Padding(
              padding: EdgeInsets.all(16),
              child: Text(
                'Приоритет наряда',
                style: TextStyle(fontWeight: FontWeight.w700, fontSize: 20),
              ),
            ),
            ...priorities.entries.map(
              (p) => ListTile(
                title: Text(p.value),
                trailing: task['priority'] == p.key
                    ? const Icon(Icons.check_rounded)
                    : null,
                onTap: () => Navigator.pop(ctx, p.key),
              ),
            ),
          ],
        ),
      ),
    );
    if (priority != null && mounted) {
      final reason = await askReason(context, 'Почему меняется приоритет?');
      if (reason != null) {
        await action('change_priority', args: [task['id'], priority, reason]);
      }
    }
  }

  Future<void> claim(Json task) async {
    final date = await showDatePicker(
      context: context,
      initialDate: DateTime(c.now.year, c.now.month, c.now.day),
      firstDate: DateTime(c.now.year, c.now.month, c.now.day),
      lastDate: c.now.add(const Duration(days: 365)),
    );
    if (!mounted || date == null) return;
    try {
      final slots = await c.api!.call(
        'free_slots',
        args: [c.session!.id, dayOf(date)],
      );
      if (!mounted) return;
      final valid = (slots is List ? slots : [])
          .where(
            (s) =>
                s is List &&
                s.length >= 2 &&
                number(s[1]) - number(s[0]) >= number(task['duration']),
          )
          .toList();
      if (valid.isEmpty) {
        message(
          context,
          'Нет свободного окна на этот день. Проверьте смену у мастера.',
          error: true,
        );
        return;
      }
      final start = await showModalBottomSheet<double>(
        context: context,
        builder: (ctx) => SafeArea(
          child: ListView(
            shrinkWrap: true,
            children: [
              const ListTile(title: Text('Выберите свободное время')),
              ...valid.map(
                (slot) => ListTile(
                  title: Text(
                    '${formatHour(slot[0])} — ${formatHour(number(slot[0]) + number(task['duration']))}',
                  ),
                  trailing: const Icon(Icons.arrow_forward_rounded),
                  onTap: () => Navigator.pop(ctx, number(slot[0])),
                ),
              ),
            ],
          ),
        ),
      );
      if (start != null) {
        await action('claim', args: [task['id'], dayOf(date), start]);
      }
    } catch (e) {
      if (mounted) message(context, e.toString(), error: true);
    }
  }

  Future<void> assign(Json task) async {
    final workers = c.snapshot!.users
        .where((u) => u['role'] == 'worker' && enabled(u['active'] ?? 1))
        .toList();
    final worker = await showModalBottomSheet<Json>(
      context: context,
      builder: (ctx) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            const ListTile(title: Text('Выберите исполнителя')),
            ...workers.map(
              (w) => ListTile(
                leading: IdentityAvatar(text(w['name'])),
                title: Text(text(w['name'])),
                subtitle: Text(
                  availabilityNames[c.snapshot!.employeeStatus['${w['id']}']] ??
                      'Не на смене',
                ),
                onTap: () => Navigator.pop(ctx, w),
              ),
            ),
          ],
        ),
      ),
    );
    if (!mounted || worker == null) return;
    final date = await showDatePicker(
      context: context,
      initialDate: DateTime.parse(text(task['day'])),
      firstDate: c.now.subtract(const Duration(days: 365)),
      lastDate: c.now.add(const Duration(days: 365)),
    );
    if (!mounted || date == null) return;
    final start = await showTimePicker(
      context: context,
      initialTime: const TimeOfDay(hour: 9, minute: 0),
    );
    if (!mounted || start == null) return;
    final reason = await askReason(context, 'Причина назначения');
    if (reason != null) {
      await action(
        'reassign_task',
        args: [
          task['id'],
          worker['id'],
          dayOf(date),
          start.hour + start.minute / 60,
          reason,
        ],
      );
    }
  }
}

class PhotoPreview extends StatefulWidget {
  final AppController controller;
  final Json photo;
  const PhotoPreview(this.controller, this.photo, {super.key});
  @override
  State<PhotoPreview> createState() => _PhotoPreviewState();
}

class _PhotoPreviewState extends State<PhotoPreview> {
  late Future<Uint8List> bytes;
  @override
  void initState() {
    super.initState();
    bytes = widget.controller.api!.photo(text(widget.photo['object_key']));
  }

  @override
  Widget build(BuildContext context) => SizedBox(
    width: 142,
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        FutureBuilder<Uint8List>(
          future: bytes,
          builder: (context, value) => ClipRRect(
            borderRadius: BorderRadius.circular(14),
            child: value.hasData
                ? InkWell(
                    onTap: () => showDialog<void>(
                      context: context,
                      builder: (ctx) => Dialog(
                        child: Stack(
                          children: [
                            InteractiveViewer(
                              child: Image.memory(
                                value.data!,
                                fit: BoxFit.contain,
                              ),
                            ),
                            Positioned(
                              right: 0,
                              top: 0,
                              child: IconButton(
                                tooltip: 'Закрыть фото',
                                onPressed: () => Navigator.pop(ctx),
                                icon: const Icon(Icons.close_rounded),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                    child: Image.memory(
                      value.data!,
                      width: 142,
                      height: 110,
                      fit: BoxFit.cover,
                      errorBuilder: (_, _, _) => const SizedBox(
                        height: 110,
                        child: Center(child: Icon(Icons.broken_image_outlined)),
                      ),
                    ),
                  )
                : Container(
                    height: 110,
                    color: Brand.soft,
                    child: Center(
                      child: value.hasError
                          ? IconButton(
                              tooltip: 'Повторить загрузку фото',
                              onPressed: () => setState(
                                () => bytes = widget.controller.api!.photo(
                                  text(widget.photo['object_key']),
                                ),
                              ),
                              icon: const Icon(Icons.refresh_rounded),
                            )
                          : const CircularProgressIndicator(strokeWidth: 2),
                    ),
                  ),
          ),
        ),
        const SizedBox(height: 6),
        Text(
          widget.photo['kind'] == 'before' ? 'До работ' : 'После работ',
          style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
        ),
      ],
    ),
  );
}
