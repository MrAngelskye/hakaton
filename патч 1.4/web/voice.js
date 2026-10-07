/* Reviewed voice input for reports. Recognition never submits or edits a report itself. */
(function (global) {
  'use strict';
  const LIMIT = 10000;
  let active = null;
  let mountId = 0;
  const defaultFactory = () => {
    const Recognition = global.SpeechRecognition || global.webkitSpeechRecognition;
    return Recognition ? new Recognition() : null;
  };
  const errorMessages = {
    'not-allowed': 'Доступ к микрофону запрещён. Разрешите его в настройках сайта и попробуйте снова.',
    'service-not-allowed': 'Сервис распознавания недоступен или запрещён. Используйте клавиатуру.',
    'audio-capture': 'Микрофон не найден или занят. Проверьте подключение и доступ к нему.',
    'no-speech': 'Речь не распознана. Подойдите ближе к микрофону или заполните поле вручную.',
    network: 'Нет связи с сервисом распознавания. Уже распознанный текст сохранён в предпросмотре.',
    'language-not-supported': 'Русский язык недоступен в этом сервисе. Используйте клавиатуру.',
    'bad-grammar': 'Браузер не смог настроить распознавание. Используйте клавиатуру.',
    aborted: 'Диктовка остановлена. Проверьте распознанный текст.'
  };
  function supportsSpeech() {
    return Boolean(global.SpeechRecognition || global.webkitSpeechRecognition);
  }
  function mount(form, options = {}) {
    const fields = ['work', 'result'].map(id => form?.querySelector('textarea#' + id)).filter(Boolean);
    if (!form || fields.length !== 2) return null;
    const factory = options.recognitionFactory || defaultFactory;
    const supported = Boolean(options.recognitionFactory || supportsSpeech());
    const id = 'report-voice-' + (++mountId);
    const listeners = [];
    const buttons = [];
    let target = null, recognition = null, busy = false, stopping = false, destroyed = false, sequence = 0;
    let stopTimer = null, sessionTimer = null, baseline = '', results = new Map();
    const listen = (node, event, callback) => {
      node.addEventListener(event, callback);
      listeners.push([node, event, callback]);
    };
    const make = (tag, className, text) => {
      const node = document.createElement(tag);
      if (className) node.className = className;
      if (text) node.textContent = text;
      return node;
    };
    const button = (text, className) => {
      const node = make('button', className, text);
      node.type = 'button';
      return node;
    };
    const panel = make('section', 'voice-panel');
    panel.hidden = true;
    panel.id = id;
    panel.setAttribute('aria-label', 'Голосовой ввод отчёта');
    const heading = make('h3', 'voice-heading', 'Голосовой ввод');
    const note = make('p', 'voice-note', 'Диктуйте фактические действия и результат проверки. Перед добавлением исправьте текст: шум и технические названия могут распознаваться неточно.');
    const privacy = make('label', 'voice-consent');
    const consent = make('input');
    consent.type = 'checkbox';
    const disclosure = make('span', '', 'Разрешаю браузерное распознавание: голос может передаваться сервису браузера. Приложение не сохраняет аудиозапись.');
    privacy.append(consent, disclosure);
    const previewLabel = make('label', '', 'Распознанный текст — проверьте и исправьте');
    const preview = make('textarea', 'voice-preview');
    preview.id = id + '-preview';
    preview.rows = 4;
    preview.maxLength = LIMIT;
    preview.placeholder = 'Здесь появится текст. Он ещё не добавлен в отчёт.';
    previewLabel.htmlFor = preview.id;
    const interim = make('p', 'voice-interim');
    interim.setAttribute('aria-label', 'Предварительное распознавание');
    const status = make('p', 'voice-status');
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    const controls = make('div', 'voice-actions');
    const startButton = button('Начать диктовку', 'voice-start');
    const stopButton = button('Остановить', 'voice-stop');
    const applyButton = button('Добавить в отчёт', 'voice-apply primary');
    const cancelButton = button('Отмена', 'voice-cancel ghost');
    controls.append(startButton, stopButton, applyButton, cancelButton);
    panel.append(heading, note, privacy, previewLabel, preview, interim, status, controls);
    const fieldset = form.querySelector('#report-fields');
    if (fieldset) fieldset.insertAdjacentElement('afterend', panel);
    else form.append(panel);

    function current() {
      if (destroyed || !form.isConnected || !panel.isConnected) return false;
      try { return !options.isCurrent || Boolean(options.isCurrent()); }
      catch (_) { return false; }
    }
    function editable(field = target) {
      return current() && field?.isConnected && !field.disabled && !field.readOnly && !field.matches(':disabled');
    }
    function setStatus(text, error = false) {
      status.textContent = text;
      status.classList.toggle('error-text', error);
    }
    function render() {
      buttons.forEach(item => { item.disabled = busy || !editable(item._voiceTarget); });
      preview.disabled = busy;
      consent.disabled = busy;
      startButton.disabled = busy || !supported || global.isSecureContext === false || !consent.checked || !editable();
      stopButton.disabled = !busy || stopping;
      applyButton.disabled = busy || !editable() || !preview.value.trim();
      startButton.textContent = preview.value.trim() ? 'Продолжить диктовку' : 'Начать диктовку';
    }
    function clearTimers() {
      global.clearTimeout(stopTimer);
      global.clearTimeout(sessionTimer);
      stopTimer = sessionTimer = null;
    }
    function finish(message, error = false, abort = false) {
      ++sequence;
      clearTimers();
      const old = recognition;
      recognition = null;
      busy = false;
      stopping = false;
      if (old) {
        old.onstart = old.onresult = old.onerror = old.onend = null;
        if (abort) { try { old.abort(); } catch (_) {} }
      }
      if (active === handle) active = null;
      interim.textContent = '';
      if (message && current()) setStatus(message, error);
      render();
    }
    function cancel() {
      finish('', false, true);
      preview.value = '';
      results.clear();
      baseline = '';
      consent.checked = false;
      panel.hidden = true;
      render();
    }
    function interrupt() {
      if (!busy) return;
      finish('Диктовка прервана при переключении приложения. Уже распознанный текст сохранён: проверьте его или продолжите диктовку.', false, true);
    }
    function destroy() {
      if (destroyed) return;
      cancel();
      destroyed = true;
      listeners.forEach(([node, event, callback]) => node.removeEventListener(event, callback));
      buttons.forEach(node => node.remove());
      panel.remove();
    }
    function stop() {
      if (!busy || stopping || !recognition) return;
      stopping = true;
      stopButton.disabled = true;
      setStatus('Завершаем распознавание…');
      stopTimer = global.setTimeout(() => {
        finish('Ответ сервиса не получен. Проверьте уже распознанный текст или введите продолжение вручную.', true, true);
      }, 5000);
      try { recognition.stop(); }
      catch (_) { finish('Диктовка завершена. Проверьте текст.', false, true); }
    }
    function start() {
      if (busy || !editable() || !consent.checked || !supported || global.isSecureContext === false) return;
      if (preview.value.length >= LIMIT) {
        setStatus('В предпросмотре уже 10 000 символов. Добавьте текст в отчёт или сократите его.', true);
        return;
      }
      if (active && active !== handle) active.cancel();
      try { recognition = factory(); }
      catch (_) { recognition = null; }
      if (!recognition) { setStatus('Распознавание недоступно. Заполните отчёт вручную.', true); return; }
      recognition.lang = 'ru-RU';
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.maxAlternatives = 1;
      baseline = preview.value.trim();
      results = new Map();
      busy = true;
      stopping = false;
      active = handle;
      const token = ++sequence;
      const valid = () => token === sequence && busy && editable();
      recognition.onstart = () => { if (valid()) setStatus('Микрофон включён. Говорите. Отчёт не отправляется.'); else if (token === sequence) cancel(); };
      recognition.onresult = event => {
        if (!valid()) { if (token === sequence) cancel(); return; }
        for (const index of results.keys()) {
          if (index >= event.results.length) results.delete(index);
        }
        for (let i = Number(event.resultIndex) || 0; i < event.results.length; i++) {
          const item = event.results[i];
          results.set(i, {text: String(item?.[0]?.transcript || '').trim(), final: Boolean(item?.isFinal)});
        }
        const ordered = [...results.entries()].sort((a, b) => a[0] - b[0]).map(entry => entry[1]);
        const confirmed = ordered.filter(item => item.final).map(item => item.text).filter(Boolean).join(' ');
        const text = [baseline, confirmed].filter(Boolean).join(' ');
        preview.value = text.slice(0, LIMIT);
        const provisional = ordered.filter(item => !item.final).map(item => item.text).filter(Boolean).join(' ');
        interim.textContent = provisional ? 'Предварительно: ' + provisional.slice(0, LIMIT) : '';
        if (text.length > LIMIT) {
          finish('Достигнут лимит 10 000 символов. Конец диктовки не помещается: сократите текст и продиктуйте его отдельно.', true, true);
        }
      };
      recognition.onerror = event => {
        if (token !== sequence) return;
        if (!editable()) { cancel(); return; }
        finish(errorMessages[event.error] || 'Ошибка распознавания. Проверьте текст и при необходимости используйте клавиатуру.', true, true);
      };
      recognition.onend = () => {
        if (token !== sequence) return;
        if (!editable()) { cancel(); return; }
        finish(preview.value.trim() ? 'Диктовка завершена. Проверьте текст и нажмите «Добавить в отчёт».' : 'Готового текста нет. Попробуйте снова или заполните поле вручную.');
      };
      setStatus('Запрашиваем доступ к микрофону…');
      render();
      sessionTimer = global.setTimeout(stop, 120000);
      try { recognition.start(); }
      catch (_) { finish('Не удалось включить микрофон. Проверьте разрешение сайта и попробуйте снова.', true, true); }
    }
    function apply() {
      if (busy || !editable()) return;
      const text = preview.value.trim();
      if (!text) return;
      const previous = target.value;
      const combined = previous + (previous && !/\s$/.test(previous) ? '\n' : '') + text;
      const maximum = target.maxLength >= 0 ? Math.min(target.maxLength, LIMIT) : LIMIT;
      if (combined.length > maximum) {
        setStatus('В поле недостаточно места: предел ' + maximum + ' символов. Сократите предпросмотр или текст отчёта. Ничего не добавлено.', true);
        return;
      }
      target.value = combined;
      target.dispatchEvent(new global.Event('input', {bubbles: true}));
      preview.value = '';
      setStatus('Текст добавлен. Проверьте отчёт; отправка мастеру выполняется отдельно.');
      if (typeof options.onApply === 'function') options.onApply(target, text);
      render();
      target.focus();
    }
    fields.forEach(field => {
      const trigger = button('Диктовать', 'voice-trigger');
      trigger._voiceTarget = field;
      trigger.setAttribute('aria-controls', id);
      trigger.setAttribute('aria-label', field.id === 'work' ? 'Диктовать выполненные работы' : 'Диктовать результат проверки');
      const label = form.querySelector('label[for="' + field.id + '"]');
      if (label) label.insertAdjacentElement('afterend', trigger);
      else field.insertAdjacentElement('afterend', trigger);
      buttons.push(trigger);
      listen(trigger, 'click', () => {
        if (!editable(field) || busy) return;
        if (target && target !== field && preview.value.trim()) {
          setStatus('Сначала добавьте текущий текст в отчёт или нажмите «Отмена», затем выберите другое поле.', true);
          return;
        }
        target = field;
        panel.hidden = false;
        heading.textContent = field.id === 'work' ? 'Диктовка выполненных работ' : 'Диктовка результата проверки';
        setStatus(!supported ? 'В этом браузере голосовой ввод недоступен. Поля отчёта можно заполнить вручную.' : global.isSecureContext === false ? 'Микрофон доступен через HTTPS или localhost. Откройте защищённый адрес приложения.' : 'Подтвердите условия распознавания и нажмите «Начать диктовку».');
        render();
        const reducedMotion = global.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
        panel.scrollIntoView?.({block: 'nearest', behavior: reducedMotion ? 'auto' : 'smooth'});
      });
    });
    listen(consent, 'change', render);
    listen(preview, 'input', render);
    listen(startButton, 'click', start);
    listen(stopButton, 'click', stop);
    listen(applyButton, 'click', apply);
    listen(cancelButton, 'click', cancel);
    const handle = {cancel, interrupt, destroy, refresh: render, isBusy: () => busy, hasUnapplied: () => busy || Boolean(preview.value.trim())};
    render();
    return handle;
  }
  function cancelActive() { if (active) active.cancel(); }
  document.addEventListener('visibilitychange', () => { if (document.hidden && active) active.interrupt(); });
  global.addEventListener('pagehide', () => { if (active) active.interrupt(); });
  global.NaryadVoice = Object.freeze({mount, cancelActive, supportsSpeech});
})(window);
