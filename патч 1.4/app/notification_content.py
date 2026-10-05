"""Shared, plain-text notification content for desktop, browser and integrations."""

TITLES = {
    'issued': 'Вам выдан наряд', 'assigned': 'Вам переназначен наряд',
    'urgent': 'Срочный наряд', 'unaccepted': 'Наряд ещё не принят',
    'deadline_reminder': 'Скоро заканчивается время', 'overdue': 'Время наряда истекло',
    'next_task': 'Следующий наряд', 'announcement': 'Оповещение',
    'report': 'Отчёт готов к проверке', 'approved': 'Работа принята',
    'revision': 'Отчёт возвращён на доработку', 'rejected': 'Исполнитель отказался',
}


def notification_content(item):
    payload = item.get('payload') or {}
    kind = item.get('kind', '')
    urgent = kind == 'urgent' or kind in ('issued', 'assigned') and payload.get('priority') == 'urgent'
    title = 'Срочный наряд' if urgent else TITLES.get(kind, 'Уведомление')
    severity = 'critical' if urgent or kind == 'overdue' or payload.get('important') else 'warning' if kind in ('deadline_reminder', 'revision', 'unaccepted') else 'info'
    if kind == 'announcement':
        title = payload.get('title') or title
        body = payload.get('message', '')
        if payload.get('sender_name'):
            body += '\nОтправитель: ' + payload['sender_name']
    else:
        prefix = 'НР-' + str(item['task_id']) if item.get('task_id') else ''
        body = ' · '.join(part for part in (prefix, payload.get('title', '')) if part)
        detail = payload.get('reason') or payload.get('comment')
        if kind in ('deadline_reminder', 'overdue') and payload.get('deadline'):
            detail = 'Срок: ' + str(payload['deadline']).replace('T', ' ')[:16]
        elif kind == 'next_task':
            detail = 'Вы свободны. Можно принять или начать следующую работу.'
        elif urgent:
            detail = 'Требуется срочное внимание. Откройте наряд.'
        if detail:
            body += '\n' + detail
    return {'title': title, 'body': body.strip(), 'severity': severity}
