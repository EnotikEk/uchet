// main.js - ПОЛНЫЙ ФАЙЛ

// Глобальные функции
function showMessage(message, type = 'success') {
    const alertDiv = $(`
        <div class="alert alert-${type} alert-dismissible fade show position-fixed top-0 end-0 m-3" 
             style="z-index: 9999; min-width: 300px; box-shadow: 0 4px 20px rgba(0,0,0,0.15); 
                    border-radius: 12px; backdrop-filter: blur(10px);" role="alert">
            <i class="fas ${type === 'success' ? 'fa-check-circle' : type === 'danger' ? 'fa-exclamation-circle' : 'fa-info-circle'} me-2"></i>
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
    `);
    $('body').append(alertDiv);
    setTimeout(function() { 
        alertDiv.alert('close'); 
    }, 3000);
}

function formatDate(dateString) {
    if (!dateString) return '—';
    const date = new Date(dateString);
    return date.toLocaleDateString('ru-RU', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric'
    });
}

function getStatusColor(status) {
    const colors = {
        'Активна': 'success',
        'Истекает': 'warning',
        'Просрочена': 'danger',
        'Архив': 'secondary',
        'Активен': 'success',
        'Уволен': 'danger',
        'В отпуске': 'warning',
        'На больничном': 'info',
        'Заправлен': 'success',
        'Пустой': 'danger',
        'Заправка': 'warning',
        'На складе': 'info',
        'Работает': 'success',
        'Ремонт': 'warning'
    };
    return colors[status] || 'secondary';
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ============================================================
// УНИВЕРСАЛЬНЫЕ ФУНКЦИИ ДЛЯ РАБОТЫ С КАБИНЕТАМИ
// ============================================================

// Загрузка списка кабинетов для datalist
function loadRoomsForDatalist(datalistId, searchTerm = '') {
    return new Promise((resolve, reject) => {
        $.ajax({
            url: '/api/rooms/search',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({search: searchTerm}),
            success: function(rooms) {
                const datalist = $('#' + datalistId);
                datalist.empty();
                if (rooms && rooms.length > 0) {
                    for (let i = 0; i < rooms.length; i++) {
                        datalist.append(`<option value="${escapeHtml(rooms[i].number)}">${escapeHtml(rooms[i].number)}</option>`);
                    }
                }
                resolve(rooms);
            },
            error: function() {
                console.error("Ошибка загрузки кабинетов");
                reject();
            }
        });
    });
}

// Проверка существования кабинета
function checkRoomExists(roomNumber) {
    return new Promise((resolve, reject) => {
        $.ajax({
            url: '/api/rooms/search',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({search: roomNumber}),
            success: function(rooms) {
                const found = rooms.some(r => r.number === roomNumber);
                resolve(found);
            },
            error: function() {
                reject();
            }
        });
    });
}

// Добавление нового кабинета из любого поля
function addNewRoomFromField(inputId, datalistId, messageElementId = null) {
    const input = $('#' + inputId);
    const currentRoom = input.val().trim();
    
    if (!currentRoom) {
        showMessage('Введите номер кабинета', 'warning');
        return;
    }
    
    // Проверяем, есть ли уже такой кабинет в datalist
    const existingOptions = $('#' + datalistId + ' option');
    let exists = false;
    for (let i = 0; i < existingOptions.length; i++) {
        if (existingOptions[i].value === currentRoom) {
            exists = true;
            break;
        }
    }
    
    if (exists) {
        showMessage(`Кабинет "${currentRoom}" уже существует`, 'info');
        return;
    }
    
    // Проверяем, есть ли кабинет в БД
    checkRoomExists(currentRoom).then((found) => {
        if (found) {
            showMessage(`Кабинет "${currentRoom}" уже существует в базе данных`, 'info');
            loadRoomsForDatalist(datalistId);
            return;
        }
        
        showMessage(`Кабинет "${currentRoom}" будет добавлен при сохранении`, 'success');
        loadRoomsForDatalist(datalistId);
        input.val(currentRoom);
        
        if (messageElementId) {
            $('#' + messageElementId).html(`<span class="text-success">✅ Кабинет "${escapeHtml(currentRoom)}" будет добавлен</span>`);
        }
    }).catch(() => {
        showMessage('Ошибка проверки кабинета', 'danger');
    });
}

// Инициализация обработчиков для поля кабинета
function initRoomFieldHandlers(inputId, datalistId, addButtonId = null, messageElementId = null) {
    // Обработчик Enter
    $(document).on('keypress', '#' + inputId, function(e) {
        if (e.which === 13) {
            e.preventDefault();
            addNewRoomFromField(inputId, datalistId, messageElementId);
        }
    });
    
    // Обработчик кнопки "+"
    if (addButtonId) {
        $(document).on('click', '#' + addButtonId, function() {
            addNewRoomFromField(inputId, datalistId, messageElementId);
        });
    }
    
    // При фокусе загружаем список кабинетов
    $(document).on('focus', '#' + inputId, function() {
        loadRoomsForDatalist(datalistId);
    });
    
    // При потере фокуса проверяем, нужно ли добавить кабинет
    $(document).on('blur', '#' + inputId, function() {
        const value = $(this).val().trim();
        if (value) {
            // Проверяем, есть ли такой кабинет в datalist
            const existingOptions = $('#' + datalistId + ' option');
            let exists = false;
            for (let i = 0; i < existingOptions.length; i++) {
                if (existingOptions[i].value === value) {
                    exists = true;
                    break;
                }
            }
            
            if (!exists) {
                // Если кабинета нет в списке, добавляем его (но не сохраняем в БД)
                loadRoomsForDatalist(datalistId);
                if (messageElementId) {
                    $('#' + messageElementId).html(`<span class="text-info">ℹ️ Кабинет "${escapeHtml(value)}" будет создан при сохранении</span>`);
                }
            }
        }
    });
}

// Проверка авторизации при загрузке страницы
function checkAuth() {
    $.ajax({
        url: '/api/auth/me?_=' + Date.now(),
        method: 'GET',
        cache: false,
        success: function(user) {
            $('#userName').text(user.full_name || user.username);
            if (user.role === 'admin') {
                $('#adminMenu').show();
                $('#adminOrgSelector').show();
            }
            if (user.organization_name) {
                $('#userOrganization').text(' | ' + user.organization_name);
            }
        },
        error: function() {
            window.location.href = '/login';
        }
    });
}

// Выход из системы
function logout() {
    if (confirm('Выйти из системы?')) {
        $.ajax({
            url: '/api/auth/logout',
            method: 'POST',
            success: function() {
                window.location.href = '/login';
            }
        });
    }
}

// main.js - ДОБАВЬТЕ ЭТУ ФУНКЦИЮ

// ===== ПЕРЕКЛЮЧЕНИЕ ФИЛИАЛА ДЛЯ АДМИНИСТРАТОРА =====

function switchOrganization() {
    const select = document.getElementById('adminOrganizationSelect');
    if (!select) return;
    
    const orgId = select.value;
    console.log("Переключение филиала на:", orgId);
    
    // Показываем индикатор загрузки
    const btn = document.querySelector('.navbar-toggler');
    const originalHtml = btn ? btn.innerHTML : '';
    
    const previousOrg = select.getAttribute('data-current') || '__ALL__';

    $.ajax({
        url: '/api/admin/switch-organization',
        method: 'POST',
        contentType: 'application/json',
        dataType: 'json',
        data: JSON.stringify({ organization_id: orgId }),
        success: function(response) {
            if (!response || !response.success) {
                // Сервер ответил 200, но это не наш JSON (например, редирект на /login)
                console.error("Неожиданный ответ при переключении филиала:", response);
                showMessage('❌ Сессия истекла, войдите заново', 'danger');
                select.value = previousOrg;
                setTimeout(function() { window.location.href = '/login'; }, 1500);
                return;
            }

            // Обновляем отображение филиала в навигации
            if (response.organization_name) {
                $('#userOrganization').text(' | ' + response.organization_name);
            } else {
                $('#userOrganization').text('');
            }

            select.setAttribute('data-current', orgId);
            showMessage('✅ Филиал изменен на: ' + (response.organization_name || 'Все филиалы'), 'success');

            setTimeout(function() {
                location.reload();
            }, 500);
        },
        error: function(xhr) {
            console.error("Ошибка переключения филиала:", xhr.status, xhr.responseText);
            if (xhr.status === 401) {
                showMessage('❌ Сессия истекла, войдите заново', 'danger');
                setTimeout(function() { window.location.href = '/login'; }, 1500);
            } else if (xhr.status === 403) {
                showMessage('❌ Недостаточно прав для смены филиала', 'danger');
            } else {
                showMessage('❌ Ошибка при переключении филиала (код ' + xhr.status + ')', 'danger');
            }
            // Возвращаем предыдущее значение
            select.value = previousOrg;
        }
    });
}

// Обновляем checkAuth для отображения выбранного филиала
function checkAuth() {
    $.ajax({
        url: '/api/auth/me',
        method: 'GET',
        success: function(user) {
            $('#userName').text(user.full_name || user.username);
            if (user.role === 'admin') {
                $('#adminMenu').show();
                // Показываем селектор филиала
                $('#adminOrgSelector').show();
            }
            if (user.organization_name) {
                $('#userOrganization').text(' | ' + user.organization_name);
            }
        },
        error: function() {
            window.location.href = '/login';
        }
    });
}

// Анимация для кнопок
$(document).ready(function() {
    // Проверяем авторизацию, если не на странице логина
    if (window.location.pathname !== '/login') {
        checkAuth();
    }
    
    // Установка активного пункта меню
    const currentPath = window.location.pathname;
    $('.nav-link').each(function() {
        if ($(this).attr('href') === currentPath) {
            $(this).addClass('active');
        }
    });
    
    // Добавляем анимацию при загрузке
    $('.card').addClass('fade-in');
    
    // Плавный скролл
    $('a[href^="#"]').on('click', function(e) {
        e.preventDefault();
        const target = $(this.hash);
        if (target.length) {
            $('html, body').animate({
                scrollTop: target.offset().top - 70
            }, 500);
        }
    });
    
    // Подтверждение удаления с анимацией
    $(document).on('click', '.btn-danger', function(e) {
        if (!confirm('⚠️ Вы уверены?')) {
            e.preventDefault();
            return false;
        }
    });
});