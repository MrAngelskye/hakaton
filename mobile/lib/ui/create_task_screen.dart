import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import '../core/controller.dart';
import '../core/models.dart';
import 'widgets.dart';

class CreateTaskScreen extends StatefulWidget {
  final AppController controller;
  const CreateTaskScreen(this.controller, {super.key});
  @override
  State<CreateTaskScreen> createState() => _CreateTaskScreenState();
}

class _CreateTaskScreenState extends State<CreateTaskScreen>
    with WidgetsBindingObserver {
  AppController get c => widget.controller;
  final form = GlobalKey<FormState>();
  final title = TextEditingController(),
      description = TextEditingController(),
      duration = TextEditingController(text: '1');
  int? equipmentId, workerId;
  String priority = 'normal', kind = 'Плановая';
  late DateTime day, deadline;
  double start = 9;
  bool loading = true, sending = false, allowPop = false;
  String? saveError;
  Timer? timer;
  late String draftKey;
  Future<void> queue = Future<void>.value();
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    day = DateUtils.dateOnly(c.now.add(const Duration(days: 1)));
    deadline = day.add(const Duration(hours: 18));
    draftKey = c.draftKey('create', 0);
    for (final f in [title, description, duration]) {
      f.addListener(changed);
    }
    restore();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    timer?.cancel();
    for (final f in [title, description, duration]) {
      f.dispose();
    }
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (!loading && !sending && state != AppLifecycleState.resumed) persist();
  }

  Future<void> restore() async {
    try {
      final data = await c.loadDraft('create', 0);
      if (!mounted) return;
      title.text = text(data['title']);
      description.text = text(data['description']);
      duration.text = text(data['duration'], '1');
      priority = text(data['priority'], 'normal');
      kind = text(data['kind'], 'Плановая');
      equipmentId = data['equipment_id'] is num
          ? integer(data['equipment_id'])
          : null;
      workerId = data['worker_id'] is num ? integer(data['worker_id']) : null;
      day = DateTime.tryParse(text(data['day'])) ?? day;
      deadline = DateTime.tryParse(text(data['deadline'])) ?? deadline;
      start = number(data['start'], 9);
      if (!records(
        c.catalogs['equipment'],
      ).any((e) => e['id'] == equipmentId)) {
        equipmentId = null;
      }
      if (!(c.snapshot?.users ?? []).any(
        (u) => u['id'] == workerId && u['role'] == 'worker',
      )) {
        workerId = null;
      }
    } catch (_) {
      saveError = 'Не удалось восстановить черновик.';
    }
    if (mounted) setState(() => loading = false);
  }

  void changed() {
    if (loading || sending) return;
    timer?.cancel();
    timer = Timer(const Duration(milliseconds: 500), persist);
  }

  Future<void> persist() {
    timer?.cancel();
    final data = {
      'title': title.text,
      'description': description.text,
      'duration': duration.text,
      'priority': priority,
      'kind': kind,
      'equipment_id': equipmentId,
      'worker_id': workerId,
      'day': day.toIso8601String(),
      'deadline': deadline.toIso8601String(),
      'start': start,
    };
    queue = queue
        .catchError((_) {})
        .then((_) => c.store.write(draftKey, jsonEncode(data)))
        .then((_) {
          if (mounted) setState(() => saveError = null);
        })
        .catchError((Object _) {
          if (mounted) {
            setState(
              () => saveError = 'Черновик не сохранён. Повторите сохранение.',
            );
          }
        });
    return queue;
  }

  Future<void> leave() async {
    if (sending || allowPop) return;
    await persist();
    if (saveError != null) {
      if (mounted) message(context, saveError!, error: true);
      return;
    }
    if (mounted) {
      setState(() => allowPop = true);
      Navigator.pop(context);
    }
  }

  Future<void> pickDay(bool due) async {
    final chosen = await showDatePicker(
      context: context,
      initialDate: due ? deadline : day,
      firstDate: DateTime(c.now.year - 1),
      lastDate: c.now.add(const Duration(days: 365)),
    );
    if (chosen == null || !mounted) return;
    if (due) {
      final time = await showTimePicker(
        context: context,
        initialTime: TimeOfDay.fromDateTime(deadline),
      );
      if (time == null || !mounted) return;
      setState(
        () => deadline = chosen.add(
          Duration(hours: time.hour, minutes: time.minute),
        ),
      );
    } else {
      setState(() => day = chosen);
    }
    changed();
  }

  Future<void> send() async {
    if (!form.currentState!.validate() || sending) return;
    final equipment = records(
      c.catalogs['equipment'],
    ).firstWhere((e) => e['id'] == equipmentId);
    final site = records(
      c.catalogs['sites'],
    ).where((s) => s['id'] == equipment['site_id']).firstOrNull;
    if (site == null) {
      message(
        context,
        'У оборудования не указан участок. Исправьте справочник в веб-панели.',
        error: true,
      );
      return;
    }
    if (deadline.isBefore(c.now) ||
        deadline.isBefore(day.add(Duration(minutes: (start * 60).round())))) {
      message(
        context,
        'Срок должен быть позже начала работы и текущего времени.',
        error: true,
      );
      return;
    }
    await persist();
    if (!mounted) return;
    setState(() => sending = true);
    try {
      await c.mutate(
        'create_task',
        kwargs: {
          'title': title.text.trim(),
          'description': description.text.trim(),
          'site': site['name'],
          'equipment': equipment['name'],
          'site_id': site['id'],
          'equipment_id': equipmentId,
          'priority': priority,
          'kind': kind,
          'duration': number(duration.text.replaceAll(',', '.')),
          'day': dayOf(day),
          'start': workerId == null ? null : start,
          'deadline':
              '${dayOf(deadline)}T${deadline.hour.toString().padLeft(2, '0')}:${deadline.minute.toString().padLeft(2, '0')}:00',
          'worker_id': workerId,
          'complexity': 1,
        },
      );
      await queue;
      await c.store.delete(draftKey);
      if (mounted) {
        message(context, 'Наряд создан');
        setState(() => allowPop = true);
        Navigator.pop(context);
      }
    } catch (e) {
      if (mounted) message(context, e.toString(), error: true);
    } finally {
      if (mounted) setState(() => sending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final equipment = records(
      c.catalogs['equipment'],
    ).where((e) => e['active'] != 0 && e['active'] != false).toList();
    final workers = (c.snapshot?.users ?? <Json>[])
        .where(
          (u) =>
              u['role'] == 'worker' && u['active'] != 0 && u['active'] != false,
        )
        .toList();
    return PopScope(
      canPop: allowPop,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) leave();
      },
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Новый наряд'),
          leading: IconButton(
            tooltip: 'Сохранить и вернуться',
            onPressed: sending ? null : leave,
            icon: const Icon(Icons.arrow_back_rounded),
          ),
        ),
        body: loading
            ? const LoadingView()
            : equipment.isEmpty
            ? const EmptyState(
                'Добавьте оборудование',
                'Администратор заполняет участки и оборудование в веб-панели. После этого обновите данные приложения.',
                icon: Icons.precision_manufacturing_outlined,
              )
            : Form(
                key: form,
                child: ListView(
                  padding: const EdgeInsets.all(20),
                  children: [
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Text(
                          saveError ??
                              'Черновик сохраняется на этом устройстве',
                          style: TextStyle(
                            color: saveError == null
                                ? Colors.green.shade800
                                : Colors.red.shade800,
                          ),
                        ),
                        const SizedBox(height: 20),
                        TextFormField(
                          controller: title,
                          maxLength: 160,
                          decoration: const InputDecoration(
                            labelText: 'Название работы',
                          ),
                          validator: (v) => (v?.trim().length ?? 0) < 5
                              ? 'Укажите название от 5 символов'
                              : null,
                        ),
                        const SizedBox(height: 16),
                        TextFormField(
                          controller: description,
                          minLines: 3,
                          maxLines: 8,
                          decoration: const InputDecoration(
                            labelText: 'Что нужно сделать',
                            alignLabelWithHint: true,
                          ),
                          validator: (v) => (v?.trim().length ?? 0) < 10
                              ? 'Опишите задачу от 10 символов'
                              : null,
                        ),
                        const SizedBox(height: 16),
                        DropdownButtonFormField<int>(
                          initialValue: equipmentId,
                          isExpanded: true,
                          decoration: const InputDecoration(
                            labelText: 'Оборудование',
                          ),
                          items: equipment
                              .map(
                                (e) => DropdownMenuItem(
                                  value: integer(e['id']),
                                  child: Text(text(e['name']), maxLines: 2),
                                ),
                              )
                              .toList(),
                          onChanged: (v) {
                            setState(() => equipmentId = v);
                            changed();
                          },
                          validator: (v) =>
                              v == null ? 'Выберите оборудование' : null,
                        ),
                        const SizedBox(height: 16),
                        DropdownButtonFormField<String>(
                          initialValue: priority,
                          decoration: const InputDecoration(
                            labelText: 'Приоритет',
                          ),
                          items: priorities.entries
                              .map(
                                (e) => DropdownMenuItem(
                                  value: e.key,
                                  child: Text(e.value),
                                ),
                              )
                              .toList(),
                          onChanged: (v) {
                            setState(() => priority = v!);
                            changed();
                          },
                        ),
                        const SizedBox(height: 16),
                        DropdownButtonFormField<String>(
                          initialValue: kind,
                          decoration: const InputDecoration(
                            labelText: 'Тип работы',
                          ),
                          items: ['Плановая', 'Внеплановая']
                              .map(
                                (v) =>
                                    DropdownMenuItem(value: v, child: Text(v)),
                              )
                              .toList(),
                          onChanged: (v) {
                            setState(() => kind = v!);
                            changed();
                          },
                        ),
                        const SizedBox(height: 16),
                        TextFormField(
                          controller: duration,
                          keyboardType: const TextInputType.numberWithOptions(
                            decimal: true,
                          ),
                          decoration: const InputDecoration(
                            labelText: 'Плановое время',
                            suffixText: 'ч',
                          ),
                          validator: (v) {
                            final n = number((v ?? '').replaceAll(',', '.'));
                            return n < .5 || n > 10
                                ? 'От 0,5 до 10 часов'
                                : null;
                          },
                        ),
                        const SizedBox(height: 16),
                        DropdownButtonFormField<int>(
                          initialValue: workerId,
                          isExpanded: true,
                          decoration: const InputDecoration(
                            labelText: 'Исполнитель',
                          ),
                          items: [
                            const DropdownMenuItem<int>(
                              value: null,
                              child: Text(
                                'Свободный наряд — сотрудник выберет сам',
                              ),
                            ),
                            ...workers.map(
                              (u) => DropdownMenuItem(
                                value: integer(u['id']),
                                child: Text(text(u['name'])),
                              ),
                            ),
                          ],
                          onChanged: (v) {
                            setState(() => workerId = v);
                            changed();
                          },
                        ),
                        const SizedBox(height: 12),
                        ListTile(
                          contentPadding: EdgeInsets.zero,
                          leading: const Icon(Icons.calendar_month_outlined),
                          title: const Text('День выполнения'),
                          subtitle: Text(dayOf(day)),
                          trailing: const Icon(Icons.chevron_right_rounded),
                          onTap: () => pickDay(false),
                        ),
                        if (workerId != null)
                          ListTile(
                            contentPadding: EdgeInsets.zero,
                            leading: const Icon(Icons.schedule_rounded),
                            title: const Text('Начало работы'),
                            subtitle: Text(formatHour(start)),
                            trailing: const Icon(Icons.chevron_right_rounded),
                            onTap: () async {
                              final t = await showTimePicker(
                                context: context,
                                initialTime: TimeOfDay(
                                  hour: start.floor(),
                                  minute: ((start % 1) * 60).round(),
                                ),
                              );
                              if (t != null && mounted) {
                                setState(() => start = t.hour + t.minute / 60);
                                changed();
                              }
                            },
                          ),
                        ListTile(
                          contentPadding: EdgeInsets.zero,
                          leading: const Icon(Icons.flag_outlined),
                          title: const Text('Крайний срок'),
                          subtitle: Text(
                            '${dayOf(deadline)} · ${formatHour(deadline.hour + deadline.minute / 60)}',
                          ),
                          trailing: const Icon(Icons.chevron_right_rounded),
                          onTap: () => pickDay(true),
                        ),
                        const SizedBox(height: 24),
                        const Text(
                          'Сервер проверит пересечения в графике и доступность исполнителя. Учитывайте инструкции и допуски предприятия.',
                        ),
                        const SizedBox(height: 16),
                        ActionButton(
                          'Создать наряд',
                          icon: Icons.add_rounded,
                          busy: sending,
                          onPressed: send,
                        ),
                      ],
                    ),
                  ],
                ),
              ),
      ),
    );
  }
}
