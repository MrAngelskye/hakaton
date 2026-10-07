"""Optional offline dictation. No Qt, network requests or audio files.

Each session is single-use. Callbacks run on the worker thread; a GUI must
forward them through queued signals. Dependency factories make lifecycle tests
independent of microphone hardware and the optional speech packages.
"""
import json
import math
import os
import queue
import sys
import threading
import time
from pathlib import Path


MODEL_NAME = 'vosk-model-small-ru-0.22'
ROOT = Path(__file__).resolve().parents[1]


def valid_model_path(path):
    folder = Path(path).expanduser()
    return (folder / 'am' / 'final.mdl').is_file() and (folder / 'conf' / 'mfcc.conf').is_file()


def default_model_path():
    """Find an installed model, otherwise return the per-user install location."""
    project = ROOT / 'voice_models' / MODEL_NAME
    local = os.environ.get('LOCALAPPDATA')
    user = Path(local) / 'NaryadAI' / 'voice_models' / MODEL_NAME if local else project
    for path in (project, user):
        if valid_model_path(path):
            return path
    return user


def _windows_short_path(path):
    """Read an existing 8.3 alias without changing filesystem/system settings."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    get_short_path = kernel.GetShortPathNameW
    get_short_path.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    get_short_path.restype = wintypes.DWORD
    needed = get_short_path(path, None, 0)
    if not needed or needed > 32768:
        return None
    buffer = ctypes.create_unicode_buffer(needed + 1)
    written = get_short_path(path, buffer, len(buffer))
    if not written or written >= len(buffer):
        return None
    return buffer.value


def native_model_path(path):
    """Supply Vosk's Windows native library an existing short ASCII path.

    Python and Qt keep the original Unicode path. Vosk 0.3.45 on Windows may
    fail to open model files through its native narrow-character file APIs.
    An 8.3 alias is used only when Windows supplies one and it resolves to the
    same installed model; no files are copied or renamed here.
    """
    original = str(Path(path).expanduser().resolve())
    if sys.platform != 'win32':
        return original
    if original.isascii() and len(original) < 260:
        return original
    try:
        short = _windows_short_path(original)
        if short and short.isascii() and len(short) < 260 and valid_model_path(short):
            if os.path.samefile(Path(original) / 'am' / 'final.mdl', Path(short) / 'am' / 'final.mdl'):
                return short
    except (OSError, ValueError, AttributeError):
        pass
    raise RuntimeError('Vosk не может открыть модель из этой папки Windows. '
                       'Выберите короткую папку с латинскими буквами, например '
                       'C:\\NaryadAI\\voice_models\\vosk-model-small-ru-0.22. '
                       'Существующие файлы модели не изменены.')


class DictationSession:
    """Capture mono PCM and transcribe locally, keeping at most 64 audio blocks.

    Factory signatures: model_factory(str_path), recognizer_factory(model, rate),
    device_info_factory() -> {'default_samplerate': number}, and
    stream_factory(**RawInputStream_kwargs) -> context manager.

    stop() retains final text; cancel() discards it. on_done always runs for
    cleanup, including after cancellation. No other callback runs after cancel.
    """
    def __init__(self, model_path=None, on_status=None, on_partial=None,
                 on_final=None, on_error=None, on_done=None, max_seconds=120,
                 *, model_factory=None, recognizer_factory=None,
                 stream_factory=None, device_info_factory=None):
        seconds = float(max_seconds)
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError('Длительность диктовки должна быть положительным числом.')
        self.model_path = Path(model_path or default_model_path()).expanduser()
        self.max_seconds = min(seconds, 120.0)
        self._callbacks = {'status': on_status, 'partial': on_partial,
                           'final': on_final, 'error': on_error, 'done': on_done}
        self._model_factory = model_factory
        self._recognizer_factory = recognizer_factory
        self._stream_factory = stream_factory
        self._device_info_factory = device_info_factory
        self._stop = threading.Event()
        self._cancel = threading.Event()
        self._accept_audio = threading.Event()
        self._queue = queue.Queue(maxsize=64)
        self._audio_error = None
        self._thread = None
        self._started = False
        self._state_lock = threading.Lock()
        self._callback_lock = threading.RLock()

    def start(self):
        with self._state_lock:
            if self._started:
                return False
            self._started = True
            self._thread = threading.Thread(target=self._run, name='report-dictation', daemon=True)
            self._thread.start()
            return True

    def stop(self):
        self._stop.set()

    def cancel(self):
        with self._callback_lock:
            self._cancel.set()
            self._stop.set()
            self._accept_audio.clear()

    def is_alive(self):
        return bool(self._thread and self._thread.is_alive())

    def _emit(self, name, *args):
        with self._callback_lock:
            if self._cancel.is_set() and name != 'done':
                return
            callback = self._callbacks.get(name)
            if callback:
                try:
                    callback(*args)
                except Exception:
                    # A disconnected GUI callback must not retain the microphone.
                    pass

    def _factories(self):
        model_factory = self._model_factory
        recognizer_factory = self._recognizer_factory
        stream_factory = self._stream_factory
        device_info_factory = self._device_info_factory
        if model_factory is None or recognizer_factory is None:
            try:
                from vosk import Model, KaldiRecognizer
            except (ImportError, OSError) as error:
                raise RuntimeError('Локальное распознавание не установлено. Запустите install_voice.bat.') from error
            model_factory = model_factory or Model
            recognizer_factory = recognizer_factory or KaldiRecognizer
        if stream_factory is None or device_info_factory is None:
            try:
                import sounddevice
            except (ImportError, OSError) as error:
                raise RuntimeError('Захват микрофона не установлен. Запустите install_voice.bat.') from error
            stream_factory = stream_factory or sounddevice.RawInputStream
            device_info_factory = device_info_factory or (lambda: sounddevice.query_devices(kind='input'))
        return model_factory, recognizer_factory, stream_factory, device_info_factory

    def _capture(self, data, frames, audio_time, status):
        if not self._accept_audio.is_set():
            return
        if status:
            self._audio_error = 'Микрофон потерял часть записи. Повторите диктовку или введите текст вручную.'
            self._stop.set()
            return
        try:
            self._queue.put_nowait(bytes(data))
        except queue.Full:
            self._audio_error = 'Компьютер не успевает распознавать речь. Повторите более короткую диктовку.'
            self._stop.set()

    @staticmethod
    def _text(payload, key='text'):
        try:
            value = json.loads(payload)
        except (TypeError, ValueError) as error:
            raise RuntimeError('Распознавание вернуло некорректный результат.') from error
        if not isinstance(value, dict) or not isinstance(value.get(key, ''), str):
            raise RuntimeError('Распознавание вернуло некорректный результат.')
        return value.get(key, '').strip()

    def _run(self):
        completed = []
        recognizer = None
        last_partial = None
        try:
            if self._stop.is_set():
                return
            if not valid_model_path(self.model_path):
                raise RuntimeError('Русская голосовая модель не найдена. Запустите install_voice.bat или выберите папку модели.')
            model_factory, recognizer_factory, stream_factory, device_info_factory = self._factories()
            if self._stop.is_set():
                return
            self._emit('status', 'Загружаю локальную модель…')
            model_location = native_model_path(self.model_path)
            if self._stop.is_set():
                return
            try:
                model = model_factory(model_location)
            except Exception as error:
                raise RuntimeError('Не удалось загрузить локальную голосовую модель. Проверьте выбранную папку.') from error
            # Loading cannot always be interrupted, but a closed form must never
            # start recording when the delayed model constructor returns.
            if self._stop.is_set():
                return
            try:
                device = device_info_factory()
                raw_rate = float(device['default_samplerate'])
                if not math.isfinite(raw_rate) or raw_rate <= 0:
                    raise ValueError('invalid sample rate')
                rate = int(raw_rate)
                recognizer = recognizer_factory(model, rate)
                stream = stream_factory(samplerate=rate, channels=1, dtype='int16',
                                        blocksize=0, callback=self._capture)
            except Exception as error:
                raise RuntimeError('Микрофон недоступен. Проверьте подключение и разрешение микрофона в настройках устройства.') from error
            if self._stop.is_set():
                # PortAudio constructors create an inactive stream; free it if
                # cancellation occurred before entering its recording context.
                close = getattr(stream, 'close', None)
                if close:
                    close()
                return

            def consume(data):
                nonlocal last_partial
                if recognizer.AcceptWaveform(data):
                    text = self._text(recognizer.Result())
                    if text:
                        completed.append(text)
                    current = ' '.join(completed)
                else:
                    partial = self._text(recognizer.PartialResult(), 'partial')
                    current = ' '.join(completed + ([partial] if partial else []))
                if current != last_partial:
                    last_partial = current
                    self._emit('partial', current)

            self._accept_audio.set()
            try:
                with stream:
                    self._emit('status', 'Слушаю…')
                    deadline = time.monotonic() + self.max_seconds
                    while not self._stop.is_set():
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        try:
                            data = self._queue.get(timeout=min(0.05, remaining))
                        except queue.Empty:
                            continue
                        consume(data)
                    self._accept_audio.clear()
            finally:
                self._accept_audio.clear()
            if self._cancel.is_set():
                return
            if self._audio_error:
                raise RuntimeError(self._audio_error)
            self._emit('status', 'Обрабатываю речь…')
            # The input stream is closed now; this finite queue cannot grow.
            while not self._queue.empty() and not self._cancel.is_set():
                consume(self._queue.get_nowait())
            if self._cancel.is_set():
                return
            tail = self._text(recognizer.FinalResult())
            if tail:
                completed.append(tail)
            self._emit('final', ' '.join(completed))
        except Exception as error:
            self._emit('error', str(error) or 'Не удалось распознать речь. Можно заполнить отчёт вручную.')
        finally:
            self._accept_audio.clear()
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
            self._emit('done')
