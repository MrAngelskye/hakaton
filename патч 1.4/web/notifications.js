/* Native browser notifications while this client is running. No API tokens in the service worker. */
'use strict';
window.NaryadNotifications = (() => {
  let session = null;
  let generation = 0;
  const key = user => `naryadai.notifications.${user.id}`;
  const supported = () => window.isSecureContext && 'Notification' in window;
  const read = name => { try { return localStorage.getItem(name); } catch (_) { return null; } };
  const write = (name, value) => { try { localStorage.setItem(name, value); } catch (_) { /* session still receives notices */ } };
  let memorySeen = new Set();
  const seen = user => { try { return new Set([...JSON.parse(read(key(user) + '.seen') || '[]'), ...memorySeen]); } catch (_) { return new Set(memorySeen); } };
  const enabled = user => Boolean(user && supported() && Notification.permission === 'granted' && read(key(user) + '.enabled') === 'yes');
  const status = user => !supported() ? 'Нужны HTTPS и браузер с поддержкой уведомлений.' : Notification.permission === 'denied' ? 'Уведомления заблокированы в настройках этого сайта.' : enabled(user) ? 'Включены на этом устройстве.' : 'Выключены на этом устройстве.';

  async function display(user, item) {
    const epoch = generation;
    const options = {body: (item.body || '').slice(0, 500), icon: '/web/icons/icon-192.png',
      tag: `naryadai:${user.id}:${item.id || 'summary'}`, data: {taskId: item.task_id || null, userId: user.id},
      requireInteraction: item.severity === 'critical'};
    const registration = 'serviceWorker' in navigator ? await navigator.serviceWorker.getRegistration('/') : null;
    if (session !== user.id || epoch !== generation) return false;
    if (registration?.active) await registration.showNotification('НарядAI · ' + item.title, options);
    else {
      const notice = new Notification('НарядAI · ' + item.title, options);
      notice.onclick = () => {window.focus();window.dispatchEvent(new CustomEvent('naryadai-notification', {detail: options.data}));notice.close();};
    }
    return true;
  }

  async function feed(items, user) {
    if (!user) return;
    if (session !== user.id) {session = user.id;generation++;memorySeen = new Set();}
    if (!enabled(user)) return;
    const epoch = generation;
    const deliver = async () => {
      if (epoch !== generation || session !== user.id) return;
      const recorded = seen(user);
      const fresh = items.filter(item => !item.read_at && !recorded.has(item.id));
      fresh.sort((a, b) => Number(b.severity === 'critical') - Number(a.severity === 'critical') || b.id - a.id);
      if (!fresh.length) return;
      const deliverOne = async item => {
        if (epoch !== generation || session !== user.id) return;
        if (await display(user, item)) {
          recorded.add(item.id);memorySeen.add(item.id);
          write(key(user) + '.seen', JSON.stringify([...recorded].slice(-2000)));
        }
      };
      if (fresh.length > 5) {
        if (fresh[0].severity === 'critical') await deliverOne(fresh.shift());
        if (epoch !== generation || session !== user.id) return;
        if (await display(user, {title: `Новых уведомлений: ${fresh.length}`, body: 'Откройте центр уведомлений, чтобы увидеть назначения и сообщения.'})) {
          fresh.forEach(item => {recorded.add(item.id);memorySeen.add(item.id);});
          write(key(user) + '.seen', JSON.stringify([...recorded].slice(-2000)));
        }
      } else for (const item of fresh) await deliverOne(item);
    };
    // A browser-level lock avoids duplicates from two tabs under the same account.
    try {if (navigator.locks) await navigator.locks.request(key(user), deliver);else await deliver();} catch (_) { /* inbox remains available; retry on reconnect */ }
  }

  async function enable(user) {
    if (!supported()) throw new Error('Для уведомлений откройте приложение по HTTPS в поддерживаемом браузере.');
    const permission = await Notification.requestPermission();
    if (session !== user.id) throw new Error('Сеанс завершён. Войдите снова.');
    if (permission !== 'granted') throw new Error(permission === 'denied' ? 'Разрешите уведомления в настройках сайта рядом с адресной строкой.' : 'Разрешение не получено. Сообщения доступны в центре уведомлений.');
    session = user.id;write(key(user) + '.enabled', 'yes');
    await display(user, {id: 'test', title: 'Уведомления подключены', body: 'Срочные наряды, сроки и сообщения будут появляться здесь.'});
  }

  async function stop() {
    const previous = session;session = null;generation++;memorySeen = new Set();
    try {
      const registration = await navigator.serviceWorker?.getRegistration('/');
      const notices = await registration?.getNotifications() || [];
      notices.filter(notice => notice.tag.startsWith(`naryadai:${previous}:`)).forEach(notice => notice.close());
    } catch (_) { /* logout does not depend on notification support */ }
  }

  function disable(user) {write(key(user) + '.enabled', 'no');return stop();}
  return {feed, enable, disable, enabled, status, stop};
})();
