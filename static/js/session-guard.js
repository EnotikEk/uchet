// Автоматический выход из учётной записи:
//  1) после бездействия (время задаётся на сервере, SESSION_IDLE_MINUTES);
//  2) после закрытия всех вкладок приложения.
//
// Закрытие вкладок: каждая открытая вкладка записана в реестре в localStorage и
// удаляет себя при закрытии. Новая вкладка без своей отметки в sessionStorage
// смотрит в реестр: если открытых вкладок нет, пользователь разлогинивается. Открытие ещё одной вкладки при уже открытой
// (Ctrl+клик и т.п.) выход не вызывает.
//
// Бездействие: время последнего действия (мышь, клавиатура, прокрутка) общее для
// всех вкладок, чтобы простаивающая вкладка не выкинула пользователя, пока он
// работает в соседней. Пока пользователь активен, сервер раз в несколько минут
// получает запрос, чтобы его собственный таймер тоже не истёк.
(function () {
    'use strict';

    var TAB_KEY = 'uchet_tab_open';
    var TABS_KEY = 'uchet_open_tabs';
    var ACTIVITY_KEY = 'uchet_last_activity_at';
    var HEARTBEAT_MS = 5000;
    var CLOSED_AFTER_MS = 15000;
    var SERVER_PING_MS = 5 * 60 * 1000;
    var idleMinutes = window.SESSION_IDLE_MINUTES || 30;
    var IDLE_MS = idleMinutes * 60 * 1000;

    function storageGet(storage, key) {
        try { return storage.getItem(key); } catch (e) { return null; }
    }
    function storageSet(storage, key, value) {
        try { storage.setItem(key, value); } catch (e) { /* хранилище недоступно */ }
    }

    var loggingOut = false;
    function logout(reason) {
        if (loggingOut) return;
        loggingOut = true;
        try { sessionStorage.removeItem(TAB_KEY); } catch (e) { /* ignore */ }
        fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' })
            .catch(function () { /* всё равно уходим на страницу входа */ })
            .then(function () { window.location.href = '/login?reason=' + reason; });
    }

    // ----- Закрытие вкладок -----
    // Реестр открытых вкладок: {id вкладки: время последней отметки}. Закрываемая
    // вкладка сразу удаляет себя (pagehide), поэтому повторное открытие сайта
    // сразу после закрытия последней вкладки тоже приводит к выходу. Отметки по
    // времени нужны на случай, если браузер упал и pagehide не сработал.
    function readTabs() {
        try { return JSON.parse(localStorage.getItem(TABS_KEY) || '{}') || {}; } catch (e) { return {}; }
    }
    function aliveTabs() {
        var tabs = readTabs(), t = Date.now(), alive = {};
        Object.keys(tabs).forEach(function (id) {
            if (t - tabs[id] < CLOSED_AFTER_MS) alive[id] = tabs[id];
        });
        return alive;
    }

    var now = Date.now();
    var tabId = Math.random().toString(36).slice(2) + now.toString(36);
    if (!storageGet(sessionStorage, TAB_KEY) && Object.keys(aliveTabs()).length === 0) {
        logout('closed');
        return;
    }
    storageSet(sessionStorage, TAB_KEY, '1');

    function heartbeat() {
        var tabs = aliveTabs();
        tabs[tabId] = Date.now();
        storageSet(localStorage, TABS_KEY, JSON.stringify(tabs));
    }
    heartbeat();
    setInterval(heartbeat, HEARTBEAT_MS);
    window.addEventListener('pageshow', heartbeat);  // возврат на страницу кнопкой «Назад»
    window.addEventListener('pagehide', function () {
        var tabs = readTabs();
        delete tabs[tabId];
        storageSet(localStorage, TABS_KEY, JSON.stringify(tabs));
    });

    // ----- Бездействие -----
    var lastActivity = now;
    var lastSharedWrite = 0;
    var lastServerPing = now;
    storageSet(localStorage, ACTIVITY_KEY, String(now));

    function onActivity() {
        lastActivity = Date.now();
        if (lastActivity - lastSharedWrite > 2000) {
            lastSharedWrite = lastActivity;
            storageSet(localStorage, ACTIVITY_KEY, String(lastActivity));
        }
    }
    ['mousemove', 'mousedown', 'keydown', 'scroll', 'touchstart', 'wheel'].forEach(function (evt) {
        document.addEventListener(evt, onActivity, { passive: true, capture: true });
    });

    setInterval(function () {
        var shared = parseInt(storageGet(localStorage, ACTIVITY_KEY) || '0', 10);
        var last = Math.max(lastActivity, shared);
        var t = Date.now();
        if (t - last > IDLE_MS) {
            logout('expired');
            return;
        }
        // Пользователь работает (например, долго заполняет форму) — продлеваем сессию на сервере.
        if (lastActivity > lastServerPing && t - lastServerPing > SERVER_PING_MS) {
            lastServerPing = t;
            fetch('/api/auth/me', { credentials: 'same-origin', cache: 'no-store' })
                .then(function (r) { if (r.status === 401) logout('expired'); })
                .catch(function () { /* сеть недоступна — попробуем позже */ });
        }
    }, 10000);
})();
