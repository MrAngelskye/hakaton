import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import '../core/attachments.dart';
import '../core/controller.dart';
import '../core/models.dart';
import 'theme.dart';
import 'voice_sheet.dart';
import 'widgets.dart';

class ReportScreen extends StatefulWidget {
  final AppController controller;
  final int taskId;
  const ReportScreen(this.controller, this.taskId, {super.key});
  @override
  State<ReportScreen> createState() => _ReportScreenState();
}

class _ReportScreenState extends State<ReportScreen>
    with WidgetsBindingObserver {
  AppController get c => widget.controller;
  final form = GlobalKey<FormState>();
  final work = TextEditingController(),
      result = TextEditingController(),
      hours = TextEditingController();
  final picker = ImagePicker();
  late DraftPhotos photoStore;
  final List<String> photos = [];
  final List<Json> materials = [];
  String? defect, saveError, restoreError;
  bool loading = true,
      submitting = false,
      picking = false,
      cameraPending = false,
      allowPop = false;
  late String draftKey;
  Timer? debounce;
  Future<void> saveQueue = Future<void>.value();
  DateTime? savedAt;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    draftKey = c.draftKey('report', widget.taskId);
    photoStore = DraftPhotos(c.session!.identity, 'report', widget.taskId);
    for (final field in [work, result, hours]) {
      field.addListener(changed);
    }
    restore();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    debounce?.cancel();
    for (final field in [work, result, hours]) {
      field.removeListener(changed);
      field.dispose();
    }
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (!loading && !submitting && state != AppLifecycleState.resumed) {
      persist();
    }
  }

  Future<void> leave() async {
    if (submitting || allowPop) return;
    if (restoreError != null) {
      setState(() => allowPop = true);
      Navigator.pop(context);
      return;
    }
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

  Json draft() => {
    'work': work.text,
    'result': result.text,
    'hours': hours.text,
    'defect': defect,
    'materials': List<Json>.from(materials),
    'photos': List<String>.from(photos),
    'cameraPending': cameraPending,
  };
  void changed() {
    if (loading || submitting) return;
    debounce?.cancel();
    debounce = Timer(const Duration(milliseconds: 500), persist);
  }

  Future<void> persist() {
    debounce?.cancel();
    final payload = draft();
    saveQueue = saveQueue
        .catchError((_) {})
        .then((_) => c.store.write(draftKey, jsonEncode(payload)))
        .then((_) {
          if (mounted) {
            setState(() {
              savedAt = DateTime.now();
              saveError = null;
            });
          }
        })
        .catchError((Object e) {
          if (mounted) {
            setState(
              () => saveError = 'Не удалось сохранить черновик на устройстве.',
            );
          }
        });
    return saveQueue;
  }

  Future<void> restore() async {
    if (mounted) {
      setState(() {
        loading = true;
        restoreError = null;
      });
    }
    Json saved;
    try {
      saved = await c.loadDraft('report', widget.taskId);
    } catch (_) {
      if (mounted) {
        setState(() {
          loading = false;
          restoreError =
              'Не удалось открыть сохранённый черновик. Повторите попытку.';
        });
      }
      return;
    }
    final previous = c.snapshot?.report(widget.taskId);
    if (!mounted) return;
    final values = saved.isNotEmpty
        ? saved
        : previous?['status'] == 'revision'
        ? previous!
        : <String, dynamic>{};
    work.text = text(values['work']);
    result.text = text(values['result']);
    hours.text = text(values['hours']);
    defect = text(values['defect']).split(' · ').first;
    if (!records(c.catalogs['defect_codes']).any((d) => d['code'] == defect)) {
      defect = null;
    }
    materials.clear();
    photos.clear();
    materials.addAll(records(values['materials']));
    if (saved['photos'] is List) {
      photos.addAll((saved['photos'] as List).map((p) => '$p'));
    }
    cameraPending = saved['cameraPending'] == true;
    setState(() => loading = false);
    if (!kIsWeb && Platform.isAndroid && cameraPending) {
      try {
        final lost = await picker.retrieveLostData();
        for (final image in lost.files ?? <XFile>[]) {
          if (photos.length < 5) photos.add(await photoStore.keep(image));
        }
      } catch (_) {
        if (mounted) {
          message(
            context,
            'Не удалось восстановить фото. Проверьте вложения и добавьте его заново.',
            error: true,
          );
        }
      }
      cameraPending = false;
      await persist();
      if (mounted) setState(() {});
    }
  }

  Future<void> addPhoto(ImageSource source) async {
    if (picking || photos.length >= 5) return;
    setState(() => picking = true);
    cameraPending = true;
    await persist();
    try {
      final image = await picker.pickImage(
        source: source,
        maxWidth: 2048,
        imageQuality: 85,
      );
      if (image != null) {
        final path = await photoStore.keep(image);
        if (mounted) setState(() => photos.add(path));
      }
    } catch (e) {
      if (mounted) {
        message(context, 'Не удалось добавить фото: $e', error: true);
      }
    } finally {
      cameraPending = false;
      await persist();
      if (mounted) setState(() => picking = false);
    }
  }

  Future<void> dictate(TextEditingController target) async {
    final transcript = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      builder: (_) => const VoiceSheet(),
    );
    if (transcript != null && transcript.trim().isNotEmpty && mounted) {
      target.text =
          '${target.text}${target.text.trim().isEmpty ? '' : '\n'}${transcript.trim()}';
      target.selection = TextSelection.collapsed(offset: target.text.length);
      await persist();
    }
  }

  Future<void> addMaterial() async {
    final available = records(
      c.catalogs['materials'],
    ).where((m) => m['active'] != 0 && m['active'] != false).toList();
    Json? selected;
    final quantity = TextEditingController(text: '1');
    final key = GlobalKey<FormState>();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, update) => AlertDialog(
          title: const Text('Использованный материал'),
          content: Form(
            key: key,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                DropdownButtonFormField<int>(
                  isExpanded: true,
                  items: available
                      .map(
                        (m) => DropdownMenuItem(
                          value: integer(m['id']),
                          enabled: m['unit_price'] != null,
                          child: Text(
                            '${m['name']}${m['unit_price'] == null ? ' · цена не подтверждена' : ''}',
                            maxLines: 2,
                          ),
                        ),
                      )
                      .toList(),
                  onChanged: (id) => update(
                    () => selected = available.firstWhere((m) => m['id'] == id),
                  ),
                  decoration: const InputDecoration(labelText: 'Материал'),
                  validator: (_) => selected == null
                      ? 'Выберите материал с подтверждённой ценой'
                      : null,
                ),
                const SizedBox(height: 16),
                TextFormField(
                  controller: quantity,
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  decoration: InputDecoration(
                    labelText: 'Количество',
                    suffixText: text(selected?['unit']),
                  ),
                  validator: (v) => number((v ?? '').replaceAll(',', '.')) <= 0
                      ? 'Укажите количество больше нуля'
                      : null,
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Отмена'),
            ),
            FilledButton(
              onPressed: () {
                if (key.currentState!.validate()) Navigator.pop(ctx, true);
              },
              child: const Text('Добавить'),
            ),
          ],
        ),
      ),
    );
    if (confirmed == true && selected != null && mounted) {
      setState(
        () => materials.add({
          'material_id': selected!['id'],
          'name': selected!['name'],
          'unit': selected!['unit'],
          'price': selected!['unit_price'],
          'quantity': number(quantity.text.replaceAll(',', '.')),
        }),
      );
      await persist();
    }
    Future<void>.delayed(const Duration(milliseconds: 400), quantity.dispose);
  }

  Future<void> submit() async {
    if (submitting || !form.currentState!.validate()) return;
    FocusScope.of(context).unfocus();
    final task = c.snapshot?.task(widget.taskId);
    if (task == null || !['inProgress', 'revision'].contains(task['status'])) {
      message(
        context,
        'Статус наряда изменился. Обновите данные.',
        error: true,
      );
      return;
    }
    if (task['kind'] == 'Внеплановая' && photos.isEmpty) {
      message(
        context,
        'Для внеплановой работы добавьте фото после выполнения.',
        error: true,
      );
      return;
    }
    await persist();
    if (!mounted) return;
    final yes = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Отправить отчёт?'),
        content: Text(
          'НР-${widget.taskId}\nФактическое время: ${hours.text} ч\nМатериалов: ${materials.length}\nФото: ${photos.length}\n\nПроверьте текст и вложения. Отчёт поступит на проверку ИИ и мастеру.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Вернуться к отчёту'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Отправить'),
          ),
        ],
      ),
    );
    if (yes != true || !mounted) return;
    setState(() => submitting = true);
    try {
      final attachments = await photoStore.upload(photos);
      await c.mutate(
        'submit',
        args: [widget.taskId],
        kwargs: {
          'work': work.text.trim(),
          'result': result.text.trim(),
          'defect': defect,
          'hours': number(hours.text.replaceAll(',', '.')),
          'materials': materials,
        },
        photos: attachments,
      );
      await saveQueue;
      await c.store.delete(draftKey);
      for (final path in photos) {
        await photoStore.remove(path);
      }
      if (mounted) {
        message(context, 'Отчёт отправлен на проверку');
        setState(() => allowPop = true);
        Navigator.pop(context);
      }
    } catch (e) {
      if (mounted) message(context, e.toString(), error: true);
    } finally {
      if (mounted) setState(() => submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: allowPop,
    onPopInvokedWithResult: (didPop, _) {
      if (!didPop) leave();
    },
    child: Scaffold(
      appBar: AppBar(
        title: const Text('Отчёт о выполнении'),
        leading: IconButton(
          tooltip: 'Сохранить и вернуться',
          onPressed: submitting ? null : leave,
          icon: const Icon(Icons.arrow_back_rounded),
        ),
      ),
      body: loading
          ? const LoadingView(label: 'Открываем черновик…')
          : restoreError != null
          ? Padding(
              padding: const EdgeInsets.all(20),
              child: EmptyState(
                'Черновик недоступен',
                restoreError!,
                icon: Icons.error_outline_rounded,
                action: FilledButton(
                  onPressed: restore,
                  child: const Text('Повторить'),
                ),
              ),
            )
          : Form(
              key: form,
              child: ListView(
                padding: const EdgeInsets.all(20),
                keyboardDismissBehavior:
                    ScrollViewKeyboardDismissBehavior.onDrag,
                children: [
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Surface(
                        child: Row(
                          children: [
                            const Icon(
                              Icons.assignment_outlined,
                              color: Brand.navy,
                            ),
                            const SizedBox(width: 12),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    'НР-${widget.taskId}',
                                    style: const TextStyle(
                                      color: Brand.muted,
                                      fontSize: 12,
                                    ),
                                  ),
                                  const SizedBox(height: 4),
                                  Text(
                                    text(
                                      c.snapshot?.task(widget.taskId)?['title'],
                                    ),
                                    style: Theme.of(
                                      context,
                                    ).textTheme.titleMedium,
                                  ),
                                ],
                              ),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 20),
                      Text(
                        saveError ??
                            (savedAt == null
                                ? 'Черновик сохраняется на устройстве'
                                : 'Черновик сохранён · ${savedAt!.hour.toString().padLeft(2, '0')}:${savedAt!.minute.toString().padLeft(2, '0')}'),
                        style: TextStyle(
                          color: saveError == null ? Brand.green : Brand.red,
                          fontSize: 12,
                        ),
                      ),
                      const SizedBox(height: 18),
                      reportField(
                        work,
                        'Что выполнено',
                        'Опишите фактические действия и обнаруженные замечания.',
                        10,
                      ),
                      const SizedBox(height: 18),
                      reportField(
                        result,
                        'Результат контрольной проверки',
                        'Как проверили результат? Какие показания получили?',
                        3,
                      ),
                      const SizedBox(height: 18),
                      DropdownButtonFormField<String>(
                        initialValue: defect,
                        isExpanded: true,
                        decoration: const InputDecoration(
                          labelText: 'Неисправность',
                        ),
                        items: records(c.catalogs['defect_codes'])
                            .map(
                              (d) => DropdownMenuItem(
                                value: text(d['code']),
                                child: Text(
                                  '${d['code']} · ${d['name']}',
                                  maxLines: 2,
                                ),
                              ),
                            )
                            .toList(),
                        onChanged: (value) {
                          setState(() => defect = value);
                          changed();
                        },
                        validator: (v) =>
                            v == null ? 'Выберите неисправность' : null,
                      ),
                      const SizedBox(height: 18),
                      TextFormField(
                        controller: hours,
                        enabled: !submitting,
                        keyboardType: const TextInputType.numberWithOptions(
                          decimal: true,
                        ),
                        decoration: const InputDecoration(
                          labelText: 'Фактически затраченное время',
                          suffixText: 'ч',
                          prefixIcon: Icon(Icons.timer_outlined),
                        ),
                        validator: (v) {
                          final n = number((v ?? '').replaceAll(',', '.'));
                          return n < .1 || n > 24
                              ? 'Укажите время от 0,1 до 24 часов'
                              : null;
                        },
                      ),
                      const SizedBox(height: 24),
                      SectionTitle(
                        'Материалы',
                        action: IconButton(
                          tooltip: 'Добавить материал',
                          onPressed: submitting ? null : addMaterial,
                          icon: const Icon(Icons.add_circle_outline_rounded),
                        ),
                      ),
                      if (materials.isEmpty)
                        const Text(
                          'Если материалы не использовались, оставьте список пустым.',
                          style: TextStyle(color: Brand.muted, fontSize: 12),
                        ),
                      ...materials.asMap().entries.map(
                        (entry) => ListTile(
                          contentPadding: EdgeInsets.zero,
                          title: Text(text(entry.value['name'])),
                          subtitle: Text(
                            '${entry.value['quantity']} ${entry.value['unit']}',
                          ),
                          trailing: IconButton(
                            tooltip: 'Удалить материал',
                            onPressed: submitting
                                ? null
                                : () {
                                    setState(
                                      () => materials.removeAt(entry.key),
                                    );
                                    changed();
                                  },
                            icon: const Icon(Icons.close_rounded),
                          ),
                        ),
                      ),
                      const SizedBox(height: 24),
                      SectionTitle(
                        'Фото после выполнения · ${photos.length}/5',
                      ),
                      const Text(
                        'Собственные снимки этого оборудования. Для внепланового наряда фото обязательно.',
                        style: TextStyle(color: Brand.muted, fontSize: 12),
                      ),
                      const SizedBox(height: 12),
                      Wrap(
                        spacing: 10,
                        runSpacing: 10,
                        children: photos
                            .map(
                              (path) => SizedBox(
                                width: 132,
                                height: 110,
                                child: Stack(
                                  children: [
                                    ClipRRect(
                                      borderRadius: BorderRadius.circular(14),
                                      child: Image.file(
                                        File(path),
                                        width: 132,
                                        height: 110,
                                        fit: BoxFit.cover,
                                        errorBuilder: (_, _, _) => const Center(
                                          child: Icon(
                                            Icons.broken_image_outlined,
                                          ),
                                        ),
                                      ),
                                    ),
                                    Positioned(
                                      top: 0,
                                      right: 0,
                                      child: IconButton.filledTonal(
                                        tooltip: 'Убрать фото',
                                        onPressed: submitting
                                            ? null
                                            : () async {
                                                setState(
                                                  () => photos.remove(path),
                                                );
                                                await persist();
                                                await photoStore.remove(path);
                                              },
                                        icon: const Icon(
                                          Icons.close_rounded,
                                          size: 18,
                                        ),
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            )
                            .toList(),
                      ),
                      const SizedBox(height: 12),
                      Wrap(
                        spacing: 10,
                        runSpacing: 10,
                        children: [
                          OutlinedButton.icon(
                            onPressed:
                                picking || photos.length >= 5 || submitting
                                ? null
                                : () => addPhoto(ImageSource.camera),
                            icon: const Icon(Icons.camera_alt_outlined),
                            label: const Text('Снять фото'),
                          ),
                          OutlinedButton.icon(
                            onPressed:
                                picking || photos.length >= 5 || submitting
                                ? null
                                : () => addPhoto(ImageSource.gallery),
                            icon: const Icon(Icons.photo_library_outlined),
                            label: const Text('Из галереи'),
                          ),
                        ],
                      ),
                      const SizedBox(height: 28),
                      ActionButton(
                        'Проверить и отправить',
                        icon: Icons.arrow_forward_rounded,
                        busy: submitting,
                        onPressed: submit,
                      ),
                      const SizedBox(height: 12),
                      const Text(
                        'Решение о приёмке и оценку выставляет мастер.',
                        textAlign: TextAlign.center,
                        style: TextStyle(color: Brand.muted, fontSize: 12),
                      ),
                    ],
                  ),
                ],
              ),
            ),
    ),
  );
  Widget reportField(
    TextEditingController field,
    String label,
    String hint,
    int minimum,
  ) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      TextFormField(
        controller: field,
        enabled: !submitting,
        minLines: 3,
        maxLines: 8,
        maxLength: 10000,
        decoration: InputDecoration(
          labelText: label,
          hintText: hint,
          alignLabelWithHint: true,
        ),
        validator: (v) => (v?.trim().length ?? 0) < minimum
            ? 'Добавьте описание от $minimum символов'
            : null,
      ),
      Align(
        alignment: Alignment.centerLeft,
        child: TextButton.icon(
          onPressed: submitting ? null : () => dictate(field),
          icon: const Icon(Icons.mic_none_rounded, size: 18),
          label: const Text('Продиктовать'),
        ),
      ),
    ],
  );
}
