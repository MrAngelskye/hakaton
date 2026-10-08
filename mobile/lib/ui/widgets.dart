import 'package:flutter/material.dart';
import '../core/controller.dart';
import '../core/models.dart';
import 'theme.dart';

void message(BuildContext context, String value, {bool error = false}) {
  if (!context.mounted) return;
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(
      content: Text(value),
      backgroundColor: error ? Brand.red : Brand.deep,
    ),
  );
}

class Surface extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry padding;
  const Surface({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(18),
  });
  @override
  Widget build(BuildContext context) => Card(
    child: Padding(padding: padding, child: child),
  );
}

class SectionTitle extends StatelessWidget {
  final String title;
  final Widget? action;
  const SectionTitle(this.title, {super.key, this.action});
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(top: 6, bottom: 12),
    child: Row(
      children: [
        Expanded(
          child: Text(title, style: Theme.of(context).textTheme.titleLarge),
        ),
        ?action,
      ],
    ),
  );
}

class StatePill extends StatelessWidget {
  final String value;
  final bool priority;
  const StatePill(this.value, {super.key, this.priority = false});
  @override
  Widget build(BuildContext context) {
    final tone = ['urgent', 'revision', 'rejected', 'overdue'].contains(value)
        ? Brand.red
        : ['approved', 'free'].contains(value)
        ? Brand.green
        : ['paused', 'high', 'queued'].contains(value)
        ? Brand.amber
        : value == 'aiPending'
        ? Brand.purple
        : Brand.navy;
    final title = priority
        ? priorities[value]
        : statuses[value] ?? availabilityNames[value];
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: tone.withValues(alpha: .08),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        title ?? value,
        style: TextStyle(
          color: tone,
          fontWeight: FontWeight.w700,
          fontSize: 12,
        ),
      ),
    );
  }
}

class ActionButton extends StatelessWidget {
  final String label;
  final IconData icon;
  final Future<void> Function()? onPressed;
  final bool busy;
  const ActionButton(
    this.label, {
    super.key,
    required this.icon,
    this.onPressed,
    this.busy = false,
  });
  @override
  Widget build(BuildContext context) => FilledButton.icon(
    onPressed: busy ? null : onPressed,
    icon: busy
        ? const SizedBox.square(
            dimension: 20,
            child: CircularProgressIndicator(strokeWidth: 2),
          )
        : Icon(icon, size: 20),
    label: Text(label),
  );
}

class EmptyState extends StatelessWidget {
  final String title, description;
  final IconData icon;
  final Widget? action;
  const EmptyState(
    this.title,
    this.description, {
    super.key,
    this.icon = Icons.task_alt_rounded,
    this.action,
  });
  @override
  Widget build(BuildContext context) => Surface(
    child: Column(
      children: [
        const SizedBox(height: 12),
        Container(
          padding: const EdgeInsets.all(16),
          decoration: const BoxDecoration(
            color: Brand.soft,
            shape: BoxShape.circle,
          ),
          child: Icon(icon, color: Brand.navy, size: 32),
        ),
        const SizedBox(height: 16),
        Text(
          title,
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.titleMedium,
        ),
        const SizedBox(height: 8),
        Text(
          description,
          textAlign: TextAlign.center,
          style: const TextStyle(color: Brand.muted),
        ),
        if (action != null)
          Padding(padding: const EdgeInsets.only(top: 16), child: action!),
        const SizedBox(height: 12),
      ],
    ),
  );
}

class TaskTile extends StatelessWidget {
  final Json task;
  final AppController controller;
  final VoidCallback onTap;
  const TaskTile(this.task, this.controller, {super.key, required this.onTap});
  @override
  Widget build(BuildContext context) {
    final overdue = isOverdue(task, controller.now);
    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(20),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Text(
                    'НР-${task['id']}',
                    style: const TextStyle(
                      color: Brand.muted,
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                      letterSpacing: .6,
                    ),
                  ),
                  const Spacer(),
                  if (task['priority'] == 'urgent')
                    const Icon(
                      Icons.priority_high_rounded,
                      color: Brand.red,
                      size: 20,
                    ),
                  const Icon(
                    Icons.arrow_forward_rounded,
                    size: 20,
                    color: Brand.muted,
                  ),
                ],
              ),
              const SizedBox(height: 9),
              Text(
                text(task['title']),
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 8),
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Icon(
                    Icons.precision_manufacturing_outlined,
                    size: 16,
                    color: Brand.muted,
                  ),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      text(task['equipment']),
                      style: const TextStyle(color: Brand.muted, fontSize: 13),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  StatePill(text(task['status'])),
                  StatePill(text(task['priority']), priority: true),
                ],
              ),
              const SizedBox(height: 14),
              Row(
                children: [
                  Icon(
                    Icons.schedule_rounded,
                    size: 15,
                    color: overdue ? Brand.red : Brand.muted,
                  ),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      deadlineText(task, controller.now),
                      style: TextStyle(
                        color: overdue ? Brand.red : Brand.muted,
                        fontSize: 12,
                      ),
                    ),
                  ),
                  Text(
                    '${task['duration']} ч',
                    style: const TextStyle(color: Brand.muted, fontSize: 12),
                  ),
                ],
              ),
              if (controller.session?.isMaster == true)
                Padding(
                  padding: const EdgeInsets.only(top: 10),
                  child: Text(
                    text(
                      task['worker_name'],
                      task['worker_id'] == null
                          ? 'Исполнитель не назначен'
                          : 'Исполнитель #${task['worker_id']}',
                    ),
                    style: const TextStyle(fontSize: 12, color: Brand.muted),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class IdentityAvatar extends StatelessWidget {
  final String name;
  final double size;
  const IdentityAvatar(this.name, {super.key, this.size = 42});
  @override
  Widget build(BuildContext context) {
    final initials = name
        .split(RegExp(r'\s+'))
        .where((s) => s.isNotEmpty)
        .take(2)
        .map((s) => s.substring(0, 1))
        .join();
    return CircleAvatar(
      radius: size / 2,
      backgroundColor: Brand.soft,
      foregroundColor: Brand.navy,
      child: Text(
        initials,
        style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 14),
      ),
    );
  }
}

class LoadingView extends StatelessWidget {
  final String label;
  const LoadingView({super.key, this.label = 'Подключаем рабочую смену…'});
  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(28),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const CircularProgressIndicator(strokeWidth: 3),
          const SizedBox(height: 24),
          Text(label, textAlign: TextAlign.center),
          const SizedBox(height: 8),
          const Text(
            'Первое подключение к серверу может занять около минуты.',
            textAlign: TextAlign.center,
            style: TextStyle(color: Brand.muted, fontSize: 12),
          ),
        ],
      ),
    ),
  );
}

class DetailLine extends StatelessWidget {
  final IconData icon;
  final String label, value;
  const DetailLine(this.icon, this.label, this.value, {super.key});
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 7),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, size: 19, color: Brand.muted),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                label,
                style: const TextStyle(color: Brand.muted, fontSize: 12),
              ),
              const SizedBox(height: 3),
              Text(value),
            ],
          ),
        ),
      ],
    ),
  );
}

Future<String?> askReason(BuildContext context, String title) async {
  final input = TextEditingController();
  final value = await showDialog<String>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(title),
      content: TextField(
        controller: input,
        autofocus: true,
        minLines: 2,
        maxLines: 4,
        maxLength: 1000,
        decoration: const InputDecoration(
          labelText: 'Причина',
          hintText: 'Укажите не менее 3 символов',
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(ctx),
          child: const Text('Отмена'),
        ),
        TextButton(
          onPressed: () {
            if (input.text.trim().length >= 3) {
              Navigator.pop(ctx, input.text.trim());
            }
          },
          child: const Text('Подтвердить'),
        ),
      ],
    ),
  );
  // Route transition may still reference the controller for one frame.
  Future<void>.delayed(const Duration(milliseconds: 400), input.dispose);
  return value;
}
