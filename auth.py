from functools import wraps
from flask import session, request, jsonify, redirect, url_for
import hashlib
import secrets

def hash_password(password):
    """Хэширование пароля"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password, password_hash):
    """Проверка пароля"""
    return hash_password(password) == password_hash

def generate_session_token():
    """Генерация токена сессии"""
    return secrets.token_hex(32)

def wants_json():
    """
    Нужно ли отвечать JSON'ом вместо редиректа.
    Важно за nginx: AJAX-запрос, получивший редирект на /login, приходит
    в jQuery как HTML со статусом 200, и фронтенд молча ничего не делает.
    """
    return (
        request.is_json
        or request.path.startswith('/api/')
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    )

def login_required(f):
    """Декоратор для проверки авторизации"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if wants_json():
                return jsonify({'error': 'Требуется авторизация'}), 401
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Декоратор для проверки прав администратора"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if wants_json():
                return jsonify({'error': 'Требуется авторизация'}), 401
            return redirect(url_for('login_page'))
        if session.get('role') != 'admin':
            if wants_json():
                return jsonify({'error': 'Доступ запрещен. Требуются права администратора'}), 403
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


# auth.py (дополнение)
from functools import wraps
from flask import session, request, jsonify, redirect, url_for, g
import hashlib
import secrets
from database import get_db

def hash_password(password):
    """Хэширование пароля"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password, password_hash):
    """Проверка пароля"""
    return hash_password(password) == password_hash

def generate_session_token():
    """Генерация токена сессии"""
    return secrets.token_hex(32)

def login_required(f):
    """Декоратор для проверки авторизации"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if wants_json():
                return jsonify({'error': 'Требуется авторизация'}), 401
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Декоратор для проверки прав администратора"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if wants_json():
                return jsonify({'error': 'Требуется авторизация'}), 401
            return redirect(url_for('login_page'))
        if session.get('role') != 'admin':
            if wants_json():
                return jsonify({'error': 'Доступ запрещен. Требуются права администратора'}), 403
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# ===== НОВАЯ ФУНКЦИЯ: ПОЛУЧЕНИЕ ФИЛИАЛА ТЕКУЩЕГО ПОЛЬЗОВАТЕЛЯ =====
# auth.py - ПОЛНОСТЬЮ ИСПРАВЛЕННАЯ ФУНКЦИЯ

def get_user_organization_id():
    """
    Получить ID филиала текущего пользователя.
    Если пользователь администратор и у него нет филиала - возвращает None,
    но при проверке наличия админ видит все филиалы.
    """
    if 'user_id' not in session:
        return None
    
    # Если филиал уже сохранен в сессии, используем его
    if 'organization_id' in session:
        return session.get('organization_id')
    
    # Иначе загружаем из БД
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT organization_id FROM Users WHERE id = ?", (session['user_id'],))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            org_id = row[0]
            session['organization_id'] = org_id
            return org_id
    except Exception as e:
        print(f"Ошибка получения филиала пользователя: {e}")
    
    return None

def get_user_organization_name():
    """Получить название филиала текущего пользователя"""
    org_id = get_user_organization_id()
    if not org_id:
        return None
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM Organizations WHERE id = ?", (org_id,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    except:
        return None

# auth.py - ОБНОВЛЕННАЯ ФУНКЦИЯ

def get_organization_filter(field_name='organization_id', table_alias=''):
    """
    Получить SQL условие для фильтрации по филиалу с учетом выбранного филиала администратора.
    
    Аргументы:
        field_name: имя поля в таблице (по умолчанию 'organization_id')
        table_alias: алиас таблицы (например 'C' для Catrigs)
    
    Возвращает:
        tuple: (sql_condition, params)
    """
    # Если пользователь не авторизован - нет фильтра
    if 'user_id' not in session:
        return ('', [])
    
    view_org_id = get_view_organization_id()
    is_admin = session.get('role') == 'admin'
    
    # Формируем имя поля с алиасом
    full_field = f"{table_alias}.{field_name}" if table_alias else field_name
    
    # Если администратор и выбраны все филиалы
    if is_admin and view_org_id == '__ALL__':
        return ('', [])
    
    # Если администратор и выбраны записи без филиала
    if is_admin and view_org_id == '__NONE__':
        return (f'AND {full_field} IS NULL', [])
    
    # Если есть конкретный филиал
    if view_org_id:
        return (f'AND {full_field} = ?', [view_org_id])
    
    # Если нет филиала - показываем записи без филиала
    if not view_org_id:
        return (f'AND {full_field} IS NULL', [])
    
    return ('', [])

def get_user_organization_id():
    """
    Получить ID филиала для текущего пользователя.
    Для администратора - учитывает выбранный филиал в сессии.
    """
    if 'user_id' not in session:
        return None
    
    # Проверяем, является ли пользователь администратором
    is_admin = session.get('role') == 'admin'
    
    # Если администратор и есть выбранный филиал в сессии
    if is_admin and 'view_organization_id' in session:
        view_org_id = session.get('view_organization_id')
        
        # Если выбран "__ALL__" - возвращаем None (админ видит всё)
        if view_org_id == '__ALL__':
            return None
        
        # Если выбран "__NONE__" - возвращаем специальное значение для записей без филиала
        if view_org_id == '__NONE__':
            return '__NONE__'
        
        # Если выбран конкретный филиал
        if view_org_id:
            return view_org_id
    
    # Если филиал уже сохранен в сессии, используем его
    if 'organization_id' in session:
        return session.get('organization_id')
    
    # Иначе загружаем из БД
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT organization_id FROM Users WHERE id = ?", (session['user_id'],))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            org_id = row[0]
            session['organization_id'] = org_id
            return org_id
    except Exception as e:
        print(f"Ошибка получения филиала пользователя: {e}")
    
    return None

# auth.py - ДОБАВЬТЕ ЭТУ ФУНКЦИЮ

def get_view_organization_id():
    """
    Получить ID филиала для просмотра (для администратора).
    Возвращает:
    - None - если нужно показать все записи (админ без филиала)
    - '__NONE__' - если нужно показать записи без филиала
    - число - ID конкретного филиала
    """
    if 'user_id' not in session:
        return None
    
    # Проверяем, является ли пользователь администратором
    is_admin = session.get('role') == 'admin'
    
    if is_admin and 'view_organization_id' in session:
        return session.get('view_organization_id')
    
    return get_user_organization_id()

def get_organization_filter_for_view(field_name='organization_id'):
    """
    Получить SQL условие для фильтрации с учетом выбранного филиала администратора.
    """
    view_org_id = get_view_organization_id()
    is_admin = session.get('role') == 'admin'
    
    # Если администратор и выбраны все филиалы
    if is_admin and view_org_id == '__ALL__':
        return ('', [])
    
    # Если администратор и выбраны записи без филиала
    if is_admin and view_org_id == '__NONE__':
        return (f'AND {field_name} IS NULL', [])
    
    # Если есть конкретный филиал
    if view_org_id:
        return (f'AND {field_name} = ?', [view_org_id])
    
    # Если нет филиала - показываем записи без филиала
    if not view_org_id:
        return (f'AND {field_name} IS NULL', [])
    
    return ('', [])

def get_user_organization_name():
    """Получить название филиала текущего пользователя"""
    org_id = get_user_organization_id()
    if not org_id:
        return None
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM Organizations WHERE id = ?", (org_id,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    except:
        return None

# auth.py - ОБНОВЛЕННАЯ ФУНКЦИЯ

def get_organization_for_new_record():
    """
    Получить ID филиала для новой записи.
    Для администратора - используется выбранный филиал (view_organization_id).
    Для обычного пользователя - его собственный филиал.
    """
    if 'user_id' not in session:
        return None
    
    is_admin = session.get('role') == 'admin'
    
    # Если администратор и есть выбранный филиал в сессии
    if is_admin and 'view_organization_id' in session:
        view_org_id = session.get('view_organization_id')
        
        # Если выбран "__ALL__" - сохраняем без филиала (NULL)
        if view_org_id == '__ALL__':
            return None
        
        # Если выбран "__NONE__" - сохраняем без филиала (NULL)
        if view_org_id == '__NONE__':
            return None
        
        # Если выбран конкретный филиал - используем его
        if view_org_id:
            print(f"DEBUG: Администратор создает запись в филиале: {view_org_id}")
            return view_org_id
    
    # Для обычного пользователя или если нет выбранного филиала
    return get_user_organization_id()

def get_organization_filter_where(field_name='organization_id'):
    """
    Получить SQL условие WHERE для фильтрации по филиалу.
    Используется для запросов, где нет других условий.
    """
    condition, params = get_organization_filter(field_name)
    if condition:
        # Заменяем AND на WHERE, если это первое условие
        return (condition.replace('AND', 'WHERE', 1), params)
    return ('', [])

def apply_organization_filter(query, field_name='organization_id', use_where=False):
    """
    Применить фильтр по филиалу к SQL запросу.
    
    Аргументы:
        query: исходный SQL запрос
        field_name: имя поля для фильтрации
        use_where: использовать WHERE вместо AND
    
    Возвращает:
        tuple: (modified_query, params)
    """
    org_id = get_user_organization_id()
    
    # Если нет филиала - возвращаем исходный запрос
    if not org_id:
        return (query, [])
    
    # Проверяем, является ли пользователь администратором
    is_admin = session.get('role') == 'admin'
    
    # Если администратор без филиала - не фильтруем
    if is_admin and not org_id:
        return (query, [])
    
    # Добавляем условие фильтрации
    if use_where:
        condition = f"WHERE {field_name} = ?"
    else:
        condition = f"AND {field_name} = ?"
    
    # Если в запросе уже есть WHERE, добавляем с AND, иначе с WHERE
    if 'WHERE' in query.upper():
        modified_query = f"{query} {condition}"
    else:
        modified_query = f"{query} WHERE {field_name} = ?"
    
    return (modified_query, [org_id])