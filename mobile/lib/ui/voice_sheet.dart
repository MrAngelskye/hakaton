import 'dart:async';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'theme.dart';

/// Local Vosk recognizer. No audio or transcription is sent to a cloud service.
class VoiceSheet extends StatefulWidget {
  const VoiceSheet({super.key});
  @override
  State<VoiceSheet> createState() => _VoiceSheetState();
}

class _VoiceSheetState extends State<VoiceSheet> with WidgetsBindingObserver {
  static const commands = MethodChannel('kz.bytex.naryadai/voice');
  static const events = EventChannel('kz.bytex.naryadai/voice.events');
  final text = TextEditingController();
  StreamSubscription<dynamic>? subscription;
  String status = 'Готов к записи', partial = '';
  bool recording = false, preparing = false;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused) stop();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    subscription?.cancel();
    commands.invokeMethod<void>('stop').catchError((_) {});
    text.dispose();
    super.dispose();
  }

  Future<void> start() async {
    if (kIsWeb || !Platform.isAndroid) {
      setState(
        () => status =
            'Локальная диктовка доступна в Android APK. Здесь можно ввести текст вручную.',
      );
      return;
    }
    setState(() {
      preparing = true;
      partial = '';
      status = 'Открываем локальную модель…';
    });
    subscription ??= events.receiveBroadcastStream().listen(
      (dynamic event) {
        if (!mounted || event is! Map) return;
        final kind = event['kind'];
        setState(() {
          if (kind == 'ready') {
            recording = true;
            preparing = false;
            status = 'Слушаю. Говорите короткими фразами.';
          }
          if (kind == 'partial') partial = '${event['text'] ?? ''}';
          if (kind == 'text') {
            final phrase = '${event['text'] ?? ''}'.trim();
            if (phrase.isNotEmpty) {
              text.text = '${text.text}${text.text.isEmpty ? '' : ' '}$phrase';
            }
            partial = '';
          }
          if (kind == 'error' || kind == 'stopped') {
            recording = false;
            preparing = false;
            partial = '';
            status =
                '${event['text'] ?? 'Запись остановлена. Проверьте текст.'}';
          }
        });
      },
      onError: (Object _) {
        if (mounted) {
          setState(() {
            preparing = false;
            recording = false;
            status = 'Распознавание недоступно. Введите текст вручную.';
          });
        }
      },
    );
    try {
      await commands.invokeMethod<void>('start');
    } on PlatformException catch (e) {
      if (mounted) {
        setState(() {
          preparing = false;
          status =
              e.message ??
              'Разрешите доступ к микрофону в настройках телефона.';
        });
      }
    } on MissingPluginException {
      if (mounted) {
        setState(() {
          preparing = false;
          status = 'Локальная диктовка доступна в Android APK.';
        });
      }
    }
  }

  Future<void> stop() async {
    try {
      await commands.invokeMethod<void>('stop');
    } catch (_) {}
    if (mounted) {
      setState(() {
        recording = false;
        preparing = false;
        partial = '';
      });
    }
  }

  @override
  Widget build(BuildContext context) => SafeArea(
    child: Padding(
      padding: EdgeInsets.fromLTRB(
        20,
        22,
        20,
        MediaQuery.viewInsetsOf(context).bottom + 20,
      ),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                const Icon(Icons.mic_none_rounded, color: Brand.navy),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    'Голосовой ввод',
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                ),
                IconButton(
                  tooltip: 'Закрыть',
                  onPressed: () => Navigator.pop(context),
                  icon: const Icon(Icons.close_rounded),
                ),
              ],
            ),
            const SizedBox(height: 10),
            const Text(
              'Речь распознаётся на телефоне. Проверьте числа, названия оборудования и единицы измерения перед добавлением.',
            ),
            const SizedBox(height: 16),
            AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: recording
                    ? Brand.navy.withValues(alpha: .08)
                    : Brand.soft,
                borderRadius: BorderRadius.circular(14),
              ),
              child: Text(status),
            ),
            if (partial.isNotEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 10),
                child: Text(
                  partial,
                  style: const TextStyle(
                    color: Brand.muted,
                    fontStyle: FontStyle.italic,
                  ),
                ),
              ),
            const SizedBox(height: 16),
            TextField(
              controller: text,
              minLines: 4,
              maxLines: 8,
              readOnly: recording || preparing,
              decoration: const InputDecoration(
                labelText: 'Распознанный текст',
                alignLabelWithHint: true,
              ),
            ),
            const SizedBox(height: 16),
            OutlinedButton.icon(
              onPressed: preparing
                  ? stop
                  : recording
                  ? stop
                  : start,
              icon: preparing
                  ? const SizedBox.square(
                      dimension: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : Icon(recording ? Icons.stop_rounded : Icons.mic_rounded),
              label: Text(
                recording || preparing ? 'Остановить' : 'Начать запись',
              ),
            ),
            const SizedBox(height: 10),
            FilledButton(
              onPressed: recording || preparing
                  ? null
                  : () => Navigator.pop(context, text.text.trim()),
              child: const Text('Добавить в отчёт'),
            ),
          ],
        ),
      ),
    ),
  );
}
