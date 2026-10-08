// Характеристики оборудования по типам.
//
// EQUIPMENT_TYPE_SPECS описывает, какие поля показывать для каждого типа. По этому
// описанию строятся форма добавления, карточка просмотра и режим редактирования.
//
// Поле: { key, label, col?, kind?, options?, placeholder?, general? }
//   col     — колонка таблицы Equipment, куда пишется значение (processor, ram, ...);
//             без col значение хранится в Equipment.specs (JSON) под ключом key.
//   kind    — 'text' (по умолчанию), 'number', 'select', 'size' (объём: стандартные
//             значения + «Другой» со своим вводом), 'list' (сколько угодно строк —
//             диски компьютера, входы монитора; вид строки задаёт LIST_KINDS[list]).
//   general — поле показывается в форме добавления, но в карточке выводится отдельно
//             (сетевое имя, год производства), поэтому в блок характеристик не входит.
(function () {
    'use strict';

    const OTHER = 'Другой';
    const DISK_TYPES = ['HDD', 'SSD SATA', 'SSD M.2 NVMe', 'SSD M.2 SATA', 'eMMC'];
    const DISK_SIZES = ['120 ГБ', '128 ГБ', '240 ГБ', '256 ГБ', '480 ГБ', '500 ГБ', '512 ГБ',
                        '1 ТБ', '2 ТБ', '4 ТБ', '8 ТБ'];
    const RAM_TYPES = ['DDR2', 'DDR3', 'DDR4', 'DDR5'];
    const PORT_TYPES = ['HDMI', 'DisplayPort', 'Mini DisplayPort', 'VGA (D-Sub)', 'DVI-D', 'DVI-I',
                        'USB Type-C', 'Thunderbolt', 'USB-хаб', 'Аудио 3.5 мм'];
    const YES_NO = ['Да', 'Нет'];

    // ----- Общие наборы полей -----
    const general = [
        { key: 'network_name', col: 'network_name', label: 'Сетевое имя', placeholder: 'PC-001', general: true },
        { key: 'manufacture_year', col: 'manufacture_year', label: 'Год производства', kind: 'number', general: true },
    ];
    const cpuRam = [
        { key: 'processor', col: 'processor', label: 'Процессор', placeholder: 'Intel Core i5-10400' },
        { key: 'ram', col: 'ram', label: 'ОЗУ (ГБ)', kind: 'number' },
        { key: 'ram_type', col: 'ram_type', label: 'Тип ОЗУ', kind: 'select', options: RAM_TYPES },
    ];
    const disks = [{ key: 'disks', label: 'Диски', kind: 'list', list: 'disks' }];
    const osNet = [
        { key: 'os', col: 'os', label: 'ОС', placeholder: 'Windows 10 Pro' },
        { key: 'os_key', col: 'os_key', label: 'Ключ ОС' },
        { key: 'ip_address', col: 'ip_address', label: 'IP-адрес' },
    ];
    const screen = [
        { key: 'monitor_size', col: 'monitor_size', label: 'Диагональ (")', kind: 'number' },
        { key: 'resolution', col: 'resolution', label: 'Разрешение', kind: 'select',
          options: ['1366x768', '1600x900', '1920x1080', '2560x1440', '3840x2160'] },
    ];
    const connection = (options) => ({ key: 'connection_type', col: 'connection_type', label: 'Подключение',
        kind: 'select', options: options || ['USB', 'Bluetooth', 'Радиоканал', 'Jack 3.5mm'] });
    const color = { key: 'color', col: 'color', label: 'Цвет' };
    const printer = [
        { key: 'print_type', col: 'print_type', label: 'Тип печати', kind: 'select', options: ['Лазерный', 'Струйный', 'Матричный', 'Термо'] },
        { key: 'print_format', col: 'print_format', label: 'Формат', kind: 'select', options: ['A4', 'A3', 'A3-A4'] },
        { key: 'print_speed', col: 'print_speed', label: 'Скорость печати (стр/мин)', kind: 'number' },
        { key: 'color_type', col: 'color_type', label: 'Цветность', kind: 'select', options: ['Ч/Б', 'Цветной'] },
        { key: 'duplex', col: 'duplex', label: 'Двусторонняя печать', kind: 'select', options: YES_NO },
    ];
    const scanner = [
        { key: 'scanner_resolution', col: 'scanner_resolution', label: 'Разрешение сканера', placeholder: '1200x1200 dpi' },
        { key: 'scanner_speed', col: 'scanner_speed', label: 'Скорость сканера' },
    ];
    const ip = { key: 'ip_address', col: 'ip_address', label: 'IP-адрес' };

    window.EQUIPMENT_TYPE_SPECS = {
        'Компьютер': [...general, ...cpuRam, ...disks, ...osNet,
            { key: 'gpu', label: 'Видеокарта' },
            { key: 'form_factor', label: 'Корпус', kind: 'select', options: ['Tower', 'Mini-Tower', 'Desktop', 'Mini PC'] }],
        'Ноутбук': [...general, ...cpuRam, ...disks, ...osNet,
            { key: 'monitor_size', col: 'monitor_size', label: 'Диагональ экрана (")', kind: 'number' },
            { key: 'gpu', label: 'Видеокарта' },
            { key: 'battery', label: 'Состояние батареи', kind: 'select', options: ['Хорошее', 'Изношена', 'Нет'] }],
        'Моноблок': [...general, ...cpuRam, ...disks, ...osNet, ...screen],
        'Сервер': [...general, ...cpuRam, ...disks, ...osNet,
            { key: 'form_factor', label: 'Форм-фактор', kind: 'select', options: ['Tower', 'Rack 1U', 'Rack 2U', 'Rack 4U', 'Blade'] },
            { key: 'raid', label: 'RAID', kind: 'select', options: ['Нет', 'RAID 0', 'RAID 1', 'RAID 5', 'RAID 6', 'RAID 10'] },
            { key: 'psu_count', label: 'Блоков питания', kind: 'number' }],
        'Планшет': [...general,
            { key: 'processor', col: 'processor', label: 'Процессор' },
            { key: 'ram', col: 'ram', label: 'ОЗУ (ГБ)', kind: 'number' },
            { key: 'storage', col: 'storage', label: 'Память', kind: 'size' },
            { key: 'os', col: 'os', label: 'ОС', placeholder: 'Android, iPadOS...' },
            { key: 'monitor_size', col: 'monitor_size', label: 'Диагональ (")', kind: 'number' },
            { key: 'sim', label: 'SIM-карта', kind: 'select', options: YES_NO },
            { key: 'imei', label: 'IMEI' }],

        'Монитор': [...screen,
            { key: 'refresh_rate', col: 'refresh_rate', label: 'Частота (Гц)', kind: 'number' },
            { key: 'panel_type', col: 'panel_type', label: 'Тип матрицы', kind: 'select', options: ['IPS', 'VA', 'TN', 'OLED'] },
            { key: 'response_time', col: 'response_time', label: 'Время отклика (мс)', kind: 'number' },
            { key: 'viewing_angle', col: 'viewing_angle', label: 'Угол обзора' },
            { key: 'ports', label: 'Входы (подключение)', kind: 'list', list: 'ports' }],

        'МФУ': [...printer, ...scanner, ip],
        'Принтер': [...printer, ip],
        'Сканер': [...scanner,
            { key: 'scan_format', col: 'scan_format', label: 'Формат сканирования', kind: 'select', options: ['A4', 'A3'] },
            { key: 'duplex_scanner', col: 'duplex_scanner', label: 'Двустороннее сканирование', kind: 'select', options: YES_NO },
            { key: 'scanner_kind', label: 'Тип сканера', kind: 'select', options: ['Планшетный', 'Протяжный', 'Ручной'] }],

        'Сетевое оборудование': [
            { key: 'net_kind', label: 'Вид устройства', kind: 'select',
              options: ['Коммутатор', 'Маршрутизатор', 'Точка доступа', 'Межсетевой экран', 'Модем', 'Медиаконвертер'] },
            { key: 'port_count', col: 'port_count', label: 'Кол-во портов', kind: 'number' },
            { key: 'speed', col: 'speed', label: 'Скорость портов', kind: 'select', options: ['100 Мбит/с', '1 Гбит/с', '2.5 Гбит/с', '10 Гбит/с'] },
            { key: 'poe', col: 'poe', label: 'PoE', kind: 'select', options: YES_NO },
            { key: 'managed', col: 'managed', label: 'Управляемый', kind: 'select', options: YES_NO },
            { key: 'sfp_ports', label: 'SFP-портов', kind: 'number' },
            ip],

        'ИБП': [
            { key: 'ups_power', col: 'ups_power', label: 'Мощность (VA)' },
            { key: 'ups_power_w', label: 'Мощность (Вт)', kind: 'number' },
            { key: 'ups_type', col: 'ups_type', label: 'Тип', kind: 'select', options: ['Резервный', 'Линейно-интерактивный', 'On-line'] },
            { key: 'ups_outlets', col: 'ups_outlets', label: 'Розеток', kind: 'number' },
            { key: 'ups_runtime', col: 'ups_runtime', label: 'Время работы (мин)', kind: 'number' },
            { key: 'ups_battery', label: 'Аккумулятор', placeholder: '12V 9Ah × 2' },
            { key: 'ups_battery_date', label: 'Замена батареи', placeholder: 'месяц.год' }],

        'Мышь/Клавиатура': [
            { key: 'device_kind', label: 'Устройство', kind: 'select', options: ['Мышь', 'Клавиатура', 'Комплект'] },
            connection(['USB', 'Bluetooth', 'Радиоканал', 'PS/2']), color],
        'Веб-камера/Гарнитура/Микрофон': [
            { key: 'device_kind', label: 'Устройство', kind: 'select', options: ['Веб-камера', 'Гарнитура', 'Микрофон'] },
            connection(['USB', 'Bluetooth', 'Jack 3.5mm', 'Радиоканал']),
            { key: 'camera_resolution', label: 'Разрешение камеры', kind: 'select', options: ['720p', '1080p', '2K', '4K'] },
            color],
        'Колонки': [
            connection(['Jack 3.5mm', 'USB', 'Bluetooth']),
            { key: 'power_w', label: 'Мощность (Вт)', kind: 'number' }, color],
        'Внешний диск': [
            { key: 'disk_kind', label: 'Тип', kind: 'select', options: ['HDD', 'SSD', 'Флешка'] },
            { key: 'storage', col: 'storage', label: 'Объём', kind: 'size' },
            connection(['USB 2.0', 'USB 3.0', 'USB Type-C', 'Thunderbolt']), color],
        'Другое': [
            { key: 'connection_type', col: 'connection_type', label: 'Подключение' }, color],

        'Процессор': [
            { key: 'socket', label: 'Сокет', placeholder: 'LGA1200, AM4...' },
            { key: 'cores', label: 'Ядер / потоков', placeholder: '6 / 12' },
            { key: 'frequency', label: 'Частота (ГГц)' },
            { key: 'tdp', label: 'TDP (Вт)', kind: 'number' }],
        'Оперативная память': [
            { key: 'ram', col: 'ram', label: 'Объём (ГБ)', kind: 'number' },
            { key: 'ram_type', col: 'ram_type', label: 'Тип', kind: 'select', options: RAM_TYPES },
            { key: 'frequency_mhz', label: 'Частота (МГц)', kind: 'number' },
            { key: 'ram_form', label: 'Форм-фактор', kind: 'select', options: ['DIMM', 'SO-DIMM'] }],
        'Накопитель': [
            { key: 'disk_kind', label: 'Тип', kind: 'select', options: DISK_TYPES },
            { key: 'storage', col: 'storage', label: 'Объём', kind: 'size' },
            { key: 'disk_form', label: 'Форм-фактор', kind: 'select', options: ['2.5"', '3.5"', 'M.2 2280', 'M.2 2242', 'mSATA'] }],
        'Материнская плата': [
            { key: 'socket', label: 'Сокет' },
            { key: 'chipset', label: 'Чипсет' },
            { key: 'ram_type', col: 'ram_type', label: 'Тип ОЗУ', kind: 'select', options: RAM_TYPES },
            { key: 'board_form', label: 'Форм-фактор', kind: 'select', options: ['ATX', 'Micro-ATX', 'Mini-ITX', 'E-ATX'] }],
        'Видеокарта': [
            { key: 'ram', col: 'ram', label: 'Видеопамять (ГБ)', kind: 'number' },
            { key: 'memory_type', label: 'Тип памяти', kind: 'select', options: ['GDDR5', 'GDDR6', 'GDDR6X', 'DDR4'] },
            { key: 'ports', col: 'ports', label: 'Выходы', placeholder: 'HDMI, DP, DVI' },
            { key: 'power_w', label: 'Потребление (Вт)', kind: 'number' }],
        'Аккумулятор': [
            { key: 'capacity_mah', label: 'Ёмкость (мА·ч)', kind: 'number' },
            { key: 'voltage', label: 'Напряжение (В)' },
            { key: 'for_device', label: 'Для устройства' }],
        'Контроллер': [
            { key: 'interface', label: 'Интерфейс', kind: 'select', options: ['PCI-E', 'PCI', 'USB', 'M.2'] },
            { key: 'ports', col: 'ports', label: 'Порты' },
            { key: 'purpose', label: 'Назначение', placeholder: 'RAID, SATA, USB...' }],
        'Привод': [
            { key: 'drive_kind', label: 'Тип', kind: 'select', options: ['DVD-RW', 'DVD-ROM', 'Blu-ray', 'CD-RW'] },
            { key: 'connection_type', col: 'connection_type', label: 'Подключение', kind: 'select', options: ['SATA', 'USB', 'IDE'] }],
        'Звуковая карта': [
            { key: 'interface', label: 'Интерфейс', kind: 'select', options: ['PCI-E', 'PCI', 'USB'] },
            { key: 'channels', label: 'Каналов', placeholder: '2.0, 5.1, 7.1' }],
        'Блок питания': [
            { key: 'power_w', label: 'Мощность (Вт)', kind: 'number' },
            { key: 'certificate', label: 'Сертификат', kind: 'select',
              options: ['Нет', '80+', '80+ Bronze', '80+ Silver', '80+ Gold', '80+ Platinum'] },
            { key: 'psu_form', label: 'Форм-фактор', kind: 'select', options: ['ATX', 'SFX', 'TFX', 'Серверный'] }],
        'PCI-устройство': [
            { key: 'interface', label: 'Интерфейс', kind: 'select', options: ['PCI-E x1', 'PCI-E x4', 'PCI-E x16', 'PCI'] },
            { key: 'purpose', label: 'Назначение' }],
        'Сетевая карта': [
            { key: 'speed', col: 'speed', label: 'Скорость', kind: 'select', options: ['100 Мбит/с', '1 Гбит/с', '2.5 Гбит/с', '10 Гбит/с', 'Wi-Fi'] },
            { key: 'port_count', col: 'port_count', label: 'Портов', kind: 'number' },
            { key: 'interface', label: 'Интерфейс', kind: 'select', options: ['PCI-E', 'PCI', 'USB', 'M.2'] }],
        'Кабель': [
            { key: 'cable_type', col: 'cable_type', label: 'Тип разъёма', kind: 'select',
              options: ['DVI', 'HDMI', 'RJ45', 'USB-C', 'USB-A', 'VGA', 'DisplayPort', 'Jack 3.5mm', 'Питание', 'Другое'] },
            { key: 'length_m', label: 'Длина (м)' }],
    };

    // Колонки Equipment, которые заполняются формой характеристик (для режима
    // редактирования: значения колонок, не относящихся к текущему типу, сохраняются как есть).
    window.EQUIPMENT_SPEC_COLUMNS = Array.from(new Set(
        Object.values(window.EQUIPMENT_TYPE_SPECS).flat().filter(f => f.col).map(f => f.col)));

    function esc(v) {
        const div = document.createElement('div');
        div.textContent = v == null ? '' : String(v);
        return div.innerHTML;
    }

    function fieldValue(field, item) {
        if (!item) return '';
        if (field.kind === 'list') return (item.specs && item.specs[field.key]) || null;
        const v = field.col ? item[field.col] : (item.specs || {})[field.key];
        return v == null ? '' : v;
    }

    // ----- Выбор из стандартных значений + «Другой» со своим вводом -----
    function choiceControl(values, value, small, attrs, placeholder, emptyLabel) {
        const sel = small ? ' form-select-sm' : '', inp = small ? ' form-control-sm' : '';
        const isStd = !value || values.includes(value);
        const opts = [`<option value="">${emptyLabel || ''}</option>`]
            .concat(values.map(v => `<option ${v === value ? 'selected' : ''}>${esc(v)}</option>`))
            .concat([`<option value="${OTHER}" ${!isStd ? 'selected' : ''}>${OTHER}…</option>`]).join('');
        return `<div class="d-flex gap-1 choice-control" ${attrs || ''}>
            <select class="form-select${sel} choice-select">${opts}</select>
            <input class="form-control${inp} choice-custom" placeholder="${esc(placeholder || '')}" value="${isStd ? '' : esc(value)}" style="${isStd ? 'display:none;' : ''}">
        </div>`;
    }

    function choiceValue(box) {
        const sel = box.querySelector('.choice-select').value;
        return sel === OTHER ? box.querySelector('.choice-custom').value.trim() : sel;
    }

    const sizeControl = (value, small, attrs) => choiceControl(DISK_SIZES, value, small, attrs, 'напр. 750 ГБ');

    // ----- Списки строк (сколько угодно): диски компьютера, входы монитора -----
    // row(значение, small) — html строки; read(строка) — значение строки; text(значение) —
    // текст для старой колонки col (по ней работают таблица, поиск, отчёты);
    // fromLegacy(item) — строки из старой текстовой колонки, если списка ещё нет.
    const removeBtn = (small, title) =>
        `<button type="button" class="btn btn-outline-danger${small ? ' btn-sm' : ''} list-remove" title="${title}"><i class="fas fa-times"></i></button>`;

    const LIST_KINDS = {
        disks: {
            col: 'storage',
            addLabel: 'Добавить диск',
            row(disk, small) {
                disk = disk || {};
                const sel = small ? ' form-select-sm' : '';
                const typeOpts = ['<option value="">Тип</option>']
                    .concat(DISK_TYPES.map(t => `<option ${t === disk.type ? 'selected' : ''}>${t}</option>`)).join('');
                return `<select class="form-select${sel} disk-type" style="max-width: 11rem;">${typeOpts}</select>
                    ${sizeControl(disk.size || '', small, 'style="flex:1"')}
                    ${removeBtn(small, 'Убрать диск')}`;
            },
            read: row => ({ type: row.querySelector('.disk-type').value, size: choiceValue(row.querySelector('.choice-control')) }),
            isEmpty: d => !d.type && !d.size,
            text: d => [d.type, d.size].filter(Boolean).join(' '),
            fromLegacy: item => item.storage ? [{ type: '', size: item.storage }] : null,
        },
        ports: {
            col: 'connection_type',
            addLabel: 'Добавить вход',
            row(port, small) {
                port = port || {};
                const inp = small ? ' form-control-sm' : '';
                return `${choiceControl(PORT_TYPES, port.type || '', small, 'style="flex:1"', 'свой тип входа', 'Тип входа')}
                    <input type="number" min="1" class="form-control${inp} port-count" style="max-width: 5.5rem;" title="Количество" placeholder="кол-во" value="${esc(port.count || 1)}">
                    ${removeBtn(small, 'Убрать вход')}`;
            },
            read: row => ({ type: choiceValue(row.querySelector('.choice-control')),
                            count: Math.max(1, parseInt(row.querySelector('.port-count').value, 10) || 1) }),
            isEmpty: p => !p.type,
            text: p => p.type + (p.count > 1 ? ` ×${p.count}` : ''),
            // «HDMI, DP x2, VGA» → строки; неизвестный тип откроется как «Другой» со своим текстом
            fromLegacy: item => {
                if (!item.connection_type) return null;
                return String(item.connection_type).split(/[,;\/]+/).map(part => {
                    const m = part.trim().match(/^(.*?)\s*[x×]\s*(\d+)$/i);
                    return { type: (m ? m[1] : part).trim(), count: m ? parseInt(m[2], 10) : 1 };
                }).filter(p => p.type);
            },
        },
    };

    function listRow(kind, value, small) {
        return `<div class="d-flex gap-1 mb-1 list-row">${LIST_KINDS[kind].row(value, small)}</div>`;
    }

    function listControl(field, values, small) {
        const rows = (values && values.length ? values : [{}]).map(v => listRow(field.list, v, small)).join('');
        return `<div class="list-control" data-spec-key="${field.key}" data-list="${field.list}" data-small="${small ? '1' : ''}">
            <div class="list-rows">${rows}</div>
            <button type="button" class="btn btn-outline-primary btn-sm list-add"><i class="fas fa-plus"></i> ${LIST_KINDS[field.list].addLabel}</button>
        </div>`;
    }

    // Обработчики «Другой», добавления/удаления строк — один раз на документ
    let wired = false;
    function wire() {
        if (wired) return;
        wired = true;
        document.addEventListener('change', e => {
            if (!e.target.classList.contains('choice-select')) return;
            const custom = e.target.closest('.choice-control').querySelector('.choice-custom');
            const other = e.target.value === OTHER;
            custom.style.display = other ? '' : 'none';
            if (other) custom.focus(); else custom.value = '';
        });
        document.addEventListener('click', e => {
            const add = e.target.closest('.list-add');
            if (add) {
                const box = add.closest('.list-control');
                box.querySelector('.list-rows').insertAdjacentHTML('beforeend', listRow(box.dataset.list, {}, !!box.dataset.small));
                return;
            }
            const remove = e.target.closest('.list-remove');
            if (remove) {
                const box = remove.closest('.list-control');
                remove.closest('.list-row').remove();
                const rows = box.querySelector('.list-rows');
                if (!rows.children.length) {
                    rows.insertAdjacentHTML('beforeend', listRow(box.dataset.list, {}, !!box.dataset.small));
                }
            }
        });
    }

    function specFields(type, opts) {
        const fields = window.EQUIPMENT_TYPE_SPECS[type] || [];
        return opts && opts.skipGeneral ? fields.filter(f => !f.general) : fields;
    }

    // Форма характеристик для типа. opts: { small: true } — компактные поля (карточка),
    // skipGeneral — без сетевого имени/года (они в карточке отдельными полями).
    window.renderSpecForm = function (container, type, item, opts) {
        wire();
        opts = opts || {};
        const sm = opts.small ? ' form-control-sm' : '';
        const smSel = opts.small ? ' form-select-sm' : '';
        const fields = specFields(type, opts);
        if (!fields.length) { container.innerHTML = ''; return false; }
        let html = '<div class="row">';
        for (const f of fields) {
            const value = fieldValue(f, item);
            const label = `<label class="form-label${opts.small ? ' small mb-0' : ''}">${f.label}</label>`;
            if (f.kind === 'list') {
                // Старая запись: списка ещё нет, но есть текст в старой колонке — разбираем его в строки
                const list = value || (item ? LIST_KINDS[f.list].fromLegacy(item) : null);
                html += `<div class="col-12 mb-2">${label}${listControl(f, list, opts.small)}</div>`;
                continue;
            }
            let control;
            if (f.kind === 'size') {
                control = sizeControl(String(value), opts.small, `data-spec-key="${f.key}"`);
            } else if (f.kind === 'select') {
                const options = f.options.slice();
                if (value !== '' && !options.includes(String(value))) options.push(String(value));
                control = `<select class="form-select${smSel}" data-spec-key="${f.key}"><option value=""></option>${
                    options.map(o => `<option ${String(value) === o ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>`;
            } else {
                control = `<input type="${f.kind === 'number' ? 'number' : 'text'}" class="form-control${sm}" data-spec-key="${f.key}"
                    value="${esc(value)}" placeholder="${esc(f.placeholder || '')}">`;
            }
            html += `<div class="col-md-4 mb-2">${label}${control}</div>`;
        }
        container.innerHTML = html + '</div>';
        return true;
    };

    // Собрать значения формы: { columns: {колонка: значение}, specs: {ключ: значение} }.
    // Списки уходят в specs[ключ], а их текстовая сводка — в старую колонку (storage, connection_type).
    window.collectSpecForm = function (container, type, opts) {
        const result = { columns: {}, specs: {} };
        for (const f of specFields(type, opts)) {
            const el = container.querySelector(`[data-spec-key="${f.key}"]`);
            if (!el) continue;
            if (f.kind === 'list') {
                const kind = LIST_KINDS[f.list];
                const list = Array.from(el.querySelectorAll('.list-row')).map(kind.read).filter(v => !kind.isEmpty(v));
                result.specs[f.key] = list;
                result.columns[kind.col] = list.map(kind.text).filter(Boolean).join('; ');
                continue;
            }
            const value = f.kind === 'size' ? choiceValue(el) : el.value.trim();
            if (f.col) result.columns[f.col] = value;
            else result.specs[f.key] = value;
        }
        return result;
    };

    // Характеристики для карточки просмотра: [{label, html}] только заполненные
    window.specViewItems = function (item, opts) {
        const items = [];
        for (const f of specFields(item.type, opts)) {
            if (f.kind === 'list') {
                const kind = LIST_KINDS[f.list];
                const list = (item.specs && item.specs[f.key]) || [];
                const html = list.length
                    ? list.map(v => esc(kind.text(v))).join('<br>')
                    : esc(item[kind.col] || '');
                if (html) items.push({ label: f.label, html });
                continue;
            }
            const value = fieldValue(f, item);
            if (value !== '' && value != null) items.push({ label: f.label, html: esc(value) });
        }
        return items;
    };
})();
