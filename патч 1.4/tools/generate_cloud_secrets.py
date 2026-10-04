"""Создать два разных секрета локально. Файл не попадает в GitHub."""
import secrets
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

if __name__=='__main__':
    target=ROOT/'cloud-secrets.txt'
    if target.exists():raise SystemExit('cloud-secrets.txt уже существует. Используйте его; действующие ключи не заменены.')
    target.write_text('AI_WORKER_TOKEN='+secrets.token_urlsafe(48)+'\nBOOTSTRAP_PASSWORD='+secrets.token_urlsafe(18)+'\n',encoding='utf-8')
    print('Создан cloud-secrets.txt. Значения внесите в Environment сервиса Render.')
    print('BOOTSTRAP_PASSWORD — начальный пароль всех тестовых аккаунтов. В чат и GitHub файл не отправляйте.')
