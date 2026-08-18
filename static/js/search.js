// search.js - Универсальная система поиска с маской

// Конфигурация поиска для разных таблиц
window.SearchConfig = {
    cartridges: {
        fields: [
            { value: 'all', label: 'Все поля', icon: 'fa-globe' },
            { value: 'model', label: 'Модель', icon: 'fa-cube' },
            { value: 'serial_number', label: 'Серийный номер', icon: 'fa-barcode' },
            { value: 'responsible', label: 'Ответственный', icon: 'fa-user' },
            { value: 'room', label: 'Кабинет', icon: 'fa-door-open' },
            { value: 'mfu', label: 'МФУ', icon: 'fa-print' },
            { value: 'ip', label: 'IP адрес', icon: 'fa-network-wired' },
            { value: 'status', label: 'Статус', icon: 'fa-chart-line' }
        ],
        getFieldValue: function(item, field) {
            switch(field) {
                case 'model': return item.model;
                case 'serial_number': return item.serial_number;
                case 'responsible': return item.responsible;
                case 'room': return item.room;
                case 'mfu': return item.mfu_name;
                case 'ip': return item.ip;
                case 'status': return item.status;
                default: return '';
            }
        }
    },

    equipment: {
        fields: [
            { value: 'all', label: 'Все поля', icon: 'fa-globe' },
            { value: 'type', label: 'Тип', icon: 'fa-tag' },
            { value: 'brand', label: 'Бренд', icon: 'fa-trademark' },
            { value: 'model', label: 'Модель', icon: 'fa-cube' },
            { value: 'serial_number', label: 'Серийный номер', icon: 'fa-barcode' },
            { value: 'inventory_number', label: 'Инвентарный номер', icon: 'fa-hashtag' },
            { value: 'responsible', label: 'Ответственный', icon: 'fa-user' },
            { value: 'mol', label: 'МОЛ', icon: 'fa-user-check' },
            { value: 'room', label: 'Кабинет', icon: 'fa-door-open' },
            { value: 'organization', label: 'Филиал', icon: 'fa-building' },
            { value: 'status', label: 'Статус', icon: 'fa-chart-line' }
        ],
        getFieldValue: function(item, field) {
            switch(field) {
                case 'type': return item.type;
                case 'brand': return item.brand;
                case 'model': return item.model;
                case 'serial_number': return item.serial_number;
                case 'inventory_number': return item.inventory_number;
                case 'responsible': return item.responsible;
                case 'mol': return item.mol;
                case 'room': return item.room;
                case 'organization': return item.organization;
                case 'status': return item.status;
                default: return '';
            }
        }
    },

    equipment: {
        fields: [
            { value: 'all', label: 'Все поля', icon: 'fa-globe' },
            { value: 'type', label: 'Тип', icon: 'fa-tag' },
            { value: 'brand', label: 'Бренд', icon: 'fa-trademark' },
            { value: 'model', label: 'Модель', icon: 'fa-cube' },
            { value: 'serial_number', label: 'Серийный номер', icon: 'fa-barcode' },
            { value: 'inventory_number', label: 'Инвентарный номер', icon: 'fa-hashtag' },
            { value: 'responsible', label: 'Ответственный', icon: 'fa-user' },
            { value: 'room', label: 'Кабинет', icon: 'fa-door-open' },
            { value: 'organization', label: 'Филиал', icon: 'fa-building' },
            { value: 'status', label: 'Статус', icon: 'fa-chart-line' }
        ],
        getFieldValue: function(item, field) {
            switch(field) {
                case 'type': return item.type;
                case 'brand': return item.brand;
                case 'model': return item.model;
                case 'serial_number': return item.serial_number;
                case 'inventory_number': return item.inventory_number;
                case 'responsible': return item.responsible;
                case 'room': return item.room;
                case 'organization': return item.organization;
                case 'status': return item.status;
                default: return '';
            }
        }
    },
    licenses: {
        fields: [
            { value: 'all', label: 'Все поля', icon: 'fa-globe' },
            { value: 'product_name', label: 'Название продукта', icon: 'fa-box' },
            { value: 'product_key', label: 'Ключ', icon: 'fa-key' },
            { value: 'company', label: 'Компания', icon: 'fa-building' }
        ],
        getFieldValue: function(item, field) {
            switch(field) {
                case 'product_name': return item.product_name;
                case 'product_key': return item.product_key;
                case 'company': return item.company;
                default: return '';
            }
        }
    },
    organizations: {
        fields: [
            { value: 'all', label: 'Все поля', icon: 'fa-globe' },
            { value: 'name', label: 'Название', icon: 'fa-building' },
            { value: 'address', label: 'Адрес', icon: 'fa-map-marker-alt' },
            { value: 'department', label: 'Отдел', icon: 'fa-users' },
            { value: 'office', label: 'Кабинет', icon: 'fa-door-open' }
        ],
        getFieldValue: function(item, field) {
            switch(field) {
                case 'name': return item.name;
                case 'address': return item.address;
                case 'department': return item.department;
                case 'office': return item.office;
                default: return '';
            }
        }
    },
    compatibility: {
        fields: [
            { value: 'all', label: 'Все поля', icon: 'fa-globe' },
            { value: 'cartridge', label: 'Модель картриджа', icon: 'fa-cube' },
            { value: 'mfu', label: 'Модель МФУ', icon: 'fa-print' }
        ],
        getFieldValue: function(item, field) {
            switch(field) {
                case 'cartridge': return item.cartridge;
                case 'mfu': return item.mfu;
                default: return '';
            }
        }
    },
    analytics: {
        fields: [
            { value: 'all', label: 'Все поля', icon: 'fa-globe' },
            { value: 'cartridge', label: 'Модель картриджа', icon: 'fa-cube' }
        ],
        getFieldValue: function(item, field) {
            return field === 'cartridge' ? item.cartridge : '';
        }
    },
    users: {
        fields: [
            { value: 'all', label: 'Все поля', icon: 'fa-globe' },
            { value: 'username', label: 'Логин', icon: 'fa-user' },
            { value: 'full_name', label: 'ФИО', icon: 'fa-id-card' },
            { value: 'role', label: 'Роль', icon: 'fa-shield-alt' }
        ],
        getFieldValue: function(item, field) {
            switch(field) {
                case 'username': return item.username;
                case 'full_name': return item.full_name;
                case 'role': return item.role === 'admin' ? 'Администратор' : 'Пользователь';
                default: return '';
            }
        }
    }
};

// Типы поиска
const SEARCH_TYPES = [
    { value: 'contains', label: 'Содержит', icon: 'fa-align-center', description: 'поиск по части слова' },
    { value: 'startswith', label: 'Начинается с', icon: 'fa-arrow-right', description: 'слова, начинающиеся с...' },
    { value: 'endswith', label: 'Заканчивается на', icon: 'fa-arrow-left', description: 'слова, заканчивающиеся на...' },
    { value: 'mask', label: 'Маска (%)', icon: 'fa-asterisk', description: '% - любое, _ - один символ' },
    { value: 'exact', label: 'Точно', icon: 'fa-equals', description: 'полное совпадение' }
];

// Экранирование спецсимволов для regex
function escapeRegex(string) {
    if (!string) return '';
    return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// Преобразование маски SQL в регулярное выражение
function maskToRegex(mask) {
    if (!mask) return null;
    let pattern = escapeRegex(mask);
    pattern = pattern.replace(/\\%/g, '.*');
    pattern = pattern.replace(/\\_/g, '.');
    return new RegExp('^' + pattern + '$', 'i');
}

// Создание регуляроки в зависимости от типа поиска
function createRegex(searchTerm, searchType) {
    if (!searchTerm) return null;
    
    try {
        switch(searchType) {
            case 'contains':
                return new RegExp(escapeRegex(searchTerm), 'i');
            case 'startswith':
                return new RegExp('^' + escapeRegex(searchTerm), 'i');
            case 'endswith':
                return new RegExp(escapeRegex(searchTerm) + '$', 'i');
            case 'mask':
                return maskToRegex(searchTerm);
            case 'exact':
                return new RegExp('^' + escapeRegex(searchTerm) + '$', 'i');
            default:
                return new RegExp(escapeRegex(searchTerm), 'i');
        }
    } catch(e) {
        console.error('Regex error:', e);
        return new RegExp(escapeRegex(searchTerm), 'i');
    }
}

// Проверка соответствия одного значения
function matchesField(value, regex) {
    if (!regex) return true;
    if (!value) return false;
    return regex.test(String(value));
}

// Фильтрация данных с поддержкой маски
function filterDataWithMask(data, searchTerm, searchField, searchType, config) {
    if (!data || !data.length) return [];
    if (!searchTerm) return [...data];
    
    const regex = createRegex(searchTerm, searchType);
    if (!regex) return [...data];
    
    const filtered = [];
    
    for (let i = 0; i < data.length; i++) {
        const item = data[i];
        let match = false;
        
        if (searchField === 'all') {
            // Поиск по всем полям конфигурации
            const fields = config.fields.filter(f => f.value !== 'all');
            for (let j = 0; j < fields.length; j++) {
                const fieldValue = config.getFieldValue(item, fields[j].value);
                if (matchesField(fieldValue, regex)) {
                    match = true;
                    break;
                }
            }
        } else {
            // Поиск по конкретному полю
            const fieldValue = config.getFieldValue(item, searchField);
            match = matchesField(fieldValue, regex);
        }
        
        if (match) {
            filtered.push(item);
        }
    }
    
    return filtered;
}

// Создание HTML для панели поиска
function createSearchPanel(tableId, config, onSearchCallback) {
    const searchTypesHtml = SEARCH_TYPES.map(t => 
        `<option value="${t.value}" title="${t.description}"><i class="fas ${t.icon}"></i> ${t.label}</option>`
    ).join('');
    
    const fieldsHtml = config.fields.map(f => 
        `<option value="${f.value}"><i class="fas ${f.icon}"></i> ${f.label}</option>`
    ).join('');
    
    return `
        <div class="search-panel card bg-light mb-3" data-table="${tableId}">
            <div class="card-body py-2">
                <div class="row align-items-center">
                    <div class="col-md-3 mb-2">
                        <label class="form-label small mb-1">
                            <i class="fas fa-search"></i> Тип поиска:
                        </label>
                        <select class="form-select form-select-sm search-type" data-table="${tableId}">
                            ${searchTypesHtml}
                        </select>
                    </div>
                    <div class="col-md-4 mb-2">
                        <label class="form-label small mb-1">
                            <i class="fas fa-columns"></i> Поле для поиска:
                        </label>
                        <select class="form-select form-select-sm search-field" data-table="${tableId}">
                            ${fieldsHtml}
                        </select>
                    </div>
                    <div class="col-md-5 mb-2">
                        <label class="form-label small mb-1">
                            <i class="fas fa-keyboard"></i> Поисковый запрос:
                        </label>
                        <div class="input-group input-group-sm">
                            <input type="text" class="form-control search-input" data-table="${tableId}" 
                                   placeholder="Введите текст... (%, _ - маска)">
                            <button class="btn btn-success search-btn" data-table="${tableId}">
                                <i class="fas fa-search"></i>
                            </button>
                            <button class="btn btn-danger reset-btn" data-table="${tableId}">
                                <i class="fas fa-times"></i>
                            </button>
                        </div>
                    </div>
                </div>
                <div class="row mt-2">
                    <div class="col-md-12">
                        <div class="small text-muted">
                            <i class="fas fa-info-circle"></i> 
                            <strong>Маска поиска:</strong> 
                            <code>%</code> - любое количество символов, 
                            <code>_</code> - один любой символ
                            <span class="ms-3"><i class="fas fa-lightbulb"></i> Примеры: <code>HP%</code>, <code>_12%</code>, <code>Q26_2A</code></span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;
}

// Инициализация поиска для таблицы
function initSearchForTable(tableId, dataGetter, renderCallback, configName) {
    const config = window.SearchConfig[configName];
    if (!config) {
        console.error(`Config not found for: ${configName}`);
        return;
    }
    
    // Находим или создаем панель поиска
    let searchPanel = $(`.search-panel[data-table="${tableId}"]`);
    if (searchPanel.length === 0) {
        const targetElement = $(`#${tableId}`).closest('.card').find('.card-body').first();
        if (targetElement.length) {
            targetElement.prepend(createSearchPanel(tableId, config));
            searchPanel = $(`.search-panel[data-table="${tableId}"]`);
        }
    }
    
    if (searchPanel.length === 0) return;
    
    // Обработчики событий
    searchPanel.find('.search-btn').off('click').on('click', function() {
        const searchTerm = searchPanel.find('.search-input').val();
        const searchField = searchPanel.find('.search-field').val();
        const searchType = searchPanel.find('.search-type').val();
        
        if (!searchTerm) {
            renderCallback(dataGetter());
            showSearchStats(tableId, dataGetter().length, dataGetter().length);
            return;
        }
        
        const data = dataGetter();
        const filtered = filterDataWithMask(data, searchTerm, searchField, searchType, config);
        
        renderCallback(filtered);
        showSearchStats(tableId, filtered.length, data.length, searchTerm, searchField, searchType, config);
    });
    
    searchPanel.find('.reset-btn').off('click').on('click', function() {
        searchPanel.find('.search-input').val('');
        renderCallback(dataGetter());
        showSearchStats(tableId, dataGetter().length, dataGetter().length);
    });
    
    searchPanel.find('.search-input').off('keypress').on('keypress', function(e) {
        if (e.which === 13) {
            searchPanel.find('.search-btn').click();
        }
    });
    
    // Сохраняем обработчик для внешнего вызова
    window[`search_${tableId}`] = function() {
        searchPanel.find('.search-btn').click();
    };
}

// Показать статистику поиска
function showSearchStats(tableId, found, total, searchTerm, searchField, searchType, config) {
    let statsDiv = $(`#${tableId}Stats`);
    if (statsDiv.length === 0) {
        statsDiv = $(`<div id="${tableId}Stats" class="mt-2"></div>`);
        $(`#${tableId}`).after(statsDiv);
    }
    
    if (!searchTerm) {
        statsDiv.html(`
            <div class="alert alert-success alert-dismissible fade show" role="alert">
                <i class="fas fa-check-circle"></i> Всего записей: ${total}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            </div>
        `);
        setTimeout(() => statsDiv.find('.alert').alert('close'), 3000);
        return;
    }
    
    let searchTypeText = SEARCH_TYPES.find(t => t.value === searchType)?.label || searchType;
    let searchFieldText = config?.fields.find(f => f.value === searchField)?.label || searchField;
    
    statsDiv.html(`
        <div class="alert alert-info alert-dismissible fade show" role="alert">
            <i class="fas fa-search"></i> 
            <strong>Результаты поиска:</strong> найдено ${found} из ${total}<br>
            <small><i class="fas fa-filter"></i> Запрос: "${escapeHtml(searchTerm)}" (${searchTypeText}, ${searchFieldText})</small>
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
    `);
}

// Быстрый поиск по полю
function quickSearch(tableId, field, searchTerm, configName) {
    const config = window.SearchConfig[configName];
    if (!config) return;
    
    const searchPanel = $(`.search-panel[data-table="${tableId}"]`);
    if (searchPanel.length) {
        searchPanel.find('.search-field').val(field);
        searchPanel.find('.search-input').val(searchTerm);
        searchPanel.find('.search-type').val('contains');
        searchPanel.find('.search-btn').click();
    }
}

// Экранирование HTML
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}