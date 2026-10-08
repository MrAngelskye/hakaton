"""Measure local inference separately from the cloud and AnythingLLM."""
import argparse
import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.packaged import DEFAULT_SERVER, configuration_dir, worker_config_paths

PROMPT = 'Ответь одним коротким предложением: сколько будет 2 + 2?'


def request_json(url, payload=None, timeout=20):
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise OSError('Слишком большой ответ сервиса.')
        return json.loads(body)
    except HTTPError as error:
        raise OSError('Сервис вернул HTTP '+str(error.code)) from None
    except (URLError, TimeoutError):
        raise OSError('Сервис не отвечает. Проверьте, что он запущен.') from None


def metrics(response, elapsed):
    duration = float(response.get('eval_duration') or 0) / 1e9
    count = int(response.get('eval_count') or 0)
    return {'wall_seconds': round(elapsed, 2),
            'load_seconds': round(float(response.get('load_duration') or 0) / 1e9, 2),
            'prompt_seconds': round(float(response.get('prompt_eval_duration') or 0) / 1e9, 2),
            'prompt_tokens': int(response.get('prompt_eval_count') or 0),
            'generated_tokens': count,
            'generation_seconds': round(duration, 2),
            'tokens_per_second': round(count / duration, 2) if duration > 0 else None,
            'complete': response.get('done') is True}


def diagnose(model, ollama_url):
    report = {'model': model, 'tests': {}, 'note': 'Короткие тесты без фотографий и рабочих данных; не замер полной проверки отчёта.'}
    settings = None
    server = DEFAULT_SERVER
    paths = worker_config_paths()
    if paths:
        from worker_entry import load_worker
        try:
            worker = load_worker(*paths)
            settings, server = worker.ai.settings, worker.server
        except (OSError, ValueError) as error:
            report['settings_error'] = str(error)
    print('1/4 Проверяю общий сервер…', flush=True)
    start = time.perf_counter()
    try:
        health = request_json(server+'/health', timeout=100)
        report['tests']['cloud'] = {'seconds': round(time.perf_counter()-start, 2), 'ok': health.get('ok') is True}
    except OSError as error:
        report['tests']['cloud'] = {'error': str(error)}
    print('2/4 Проверяю Ollama…', flush=True)
    try:
        report['ollama_version'] = request_json(ollama_url+'/api/version').get('version')
        loaded = request_json(ollama_url+'/api/ps')
        report['loaded_before'] = [{k: m.get(k) for k in ('name','size','size_vram','context_length')} for m in loaded.get('models',[])]
    except OSError as error:
        report['ollama_error'] = str(error)
        return report
    payload = {'model': model, 'messages': [{'role': 'user','content': PROMPT}], 'stream': False,
               'think': False, 'keep_alive': '10m',
               'options': {'num_ctx': 4096, 'num_predict': 128, 'temperature': 0}}
    for name in ('first','second'):
        print('3/4 Короткий запрос к модели: '+name+' (можно остановить Ctrl+C)…', flush=True)
        start = time.perf_counter()
        try:
            response = request_json(ollama_url+'/api/chat', payload, timeout=600)
            if response.get('error'):
                raise OSError('Ollama отклонила запрос. Проверьте имя модели и поддержку think=false.')
            report['tests'][name] = metrics(response,time.perf_counter()-start)
        except OSError as error:
            report['tests'][name] = {'error': str(error)}
            break
    try:
        loaded = request_json(ollama_url+'/api/ps')
        report['loaded_after'] = [{k: m.get(k) for k in ('name','size','size_vram','context_length')} for m in loaded.get('models',[])]
    except OSError:
        pass
    print('4/4 Проверяю короткий запрос через AnythingLLM…', flush=True)
    if settings:
        from server.anythingllm import AnythingLLM, AIError
        from urllib.parse import quote
        import uuid
        ai = AnythingLLM(settings)
        slug = settings.chat_workspace or settings.workspace
        start = time.perf_counter()
        try:
            ai.check_workspace(slug)
            answer = ai.request('/workspace/'+quote(slug,safe='')+'/chat',
                                {'message': PROMPT, 'mode': 'chat', 'sessionId': 'naryadai-diagnostic-'+uuid.uuid4().hex})
            report['tests']['anythingllm'] = {'seconds': round(time.perf_counter()-start, 2),
                                              'ok': bool(answer.get('textResponse')) and not answer.get('error'),
                                              'note': 'Настройки модели, thinking и контекста здесь задаёт AnythingLLM.'}
        except (AIError, OSError) as error:
            report['tests']['anythingllm'] = {'error': str(error)}
    else:
        report['tests']['anythingllm'] = {'skipped': 'Сначала настройте EXE обработчика ИИ.'}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default='qwen3.5:9b')
    parser.add_argument('--ollama-url', default='http://127.0.0.1:11434')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--smoke-test', type=Path)
    args = parser.parse_args()
    if args.smoke_test:
        assert metrics({'eval_count': 20, 'eval_duration': 2_000_000_000, 'done': True}, 2)['tokens_per_second'] == 10
        args.smoke_test.parent.mkdir(parents=True, exist_ok=True)
        args.smoke_test.write_text('{"ok":true,"diagnostics":true,"network_requests":0}', encoding='utf-8')
        return 0
    try:
        report = diagnose(args.model, args.ollama_url.rstrip('/'))
    except KeyboardInterrupt:
        print('Проверка остановлена. Настройки не изменены.')
        return 0
    destination = args.output or configuration_dir().parent/'ai-diagnostics.json'
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    print('\nРезультат сохранён: '+str(destination), flush=True)
    print('Во время ответа также выполните в PowerShell: ollama ps', flush=True)
    if getattr(sys,'frozen',False):
        input('Нажмите Enter, чтобы закрыть окно…')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
