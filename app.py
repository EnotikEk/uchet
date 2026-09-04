from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
from datetime import datetime
from auth import (login_required, admin_required, hash_password, verify_password,
                  get_user_organization_id, get_user_organization_name,
                  get_organization_for_new_record, get_organization_filter,
                  apply_organization_filter, get_view_organization_id,
                  get_organization_filter_for_view)
import sqlite3
import os
import sys
import pandas as pd
import openpyxl
from io import BytesIO, StringIO

from database import get_db, init_db, upgrade_db

# Автоматическая инициализация и обновление БД при первом запуске
try:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Users'")
    if not cursor.fetchone():
        init_db()
    else:
        # Обновляем схему для существующей БД
        upgrade_db()
    conn.close()
except Exception as e:
    print(f"Ошибка при проверке БД: {e}")
    init_db()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')
app.config['JSON_AS_ASCII'] = False

# Сессия живёт 12 часов и переживает закрытие вкладки.
# ВАЖНО: SECRET_KEY должен быть одинаковым при каждом запуске — если он
# меняется (например, задан в systemd, но не задан при ручном перезапуске),
# все выданные cookie становятся недействительными и пользователи молча
# оказываются разлогинены: запросы на создание записей и смену филиала
# перестают работать без видимой ошибки.
from datetime import timedelta
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=12)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True

@app.before_request
def make_session_permanent():
    session.permanent = True

STATUS_CART = ["Заправлен", "Пустой", "Заправка", "На складе", "Под списание"]
STATUS_MFU = ["Работает", "Ремонт"]

# ========== СТРАНИЦА ВХОДА ==========
@app.route('/login')
def login_page():
    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '')
    
    if not username or not password:
        return jsonify({'error': 'Введите логин и пароль'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, username, password_hash, full_name, role, is_active, organization_id 
        FROM Users WHERE username = ?
    """, (username,))
    user = cursor.fetchone()
    conn.close()
    
    if not user:
        return jsonify({'error': 'Неверный логин или пароль'}), 401
    
    if not user[5]:
        return jsonify({'error': 'Учетная запись заблокирована'}), 401
    
    if not verify_password(password, user[2]):
        return jsonify({'error': 'Неверный логин или пароль'}), 401
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE Users SET last_login = ? WHERE id = ?", (datetime.now().isoformat(), user[0]))
    conn.commit()
    conn.close()
    
    session['user_id'] = user[0]
    session['username'] = user[1]
    session['full_name'] = user[3]
    session['role'] = user[4]
    session['organization_id'] = user[6] if len(user) > 6 else None
    
    org_name = None
    if session['organization_id']:
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM Organizations WHERE id = ?", (session['organization_id'],))
            row = cursor.fetchone()
            conn.close()
            if row:
                org_name = row[0]
                session['organization_name'] = org_name
        except:
            pass
    
    return jsonify({
        'success': True,
        'user': {
            'id': user[0],
            'username': user[1],
            'full_name': user[3],
            'role': user[4],
            'organization_id': session['organization_id'],
            'organization_name': org_name
        }
    })

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/auth/me', methods=['GET'])
@login_required
def get_current_user():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT u.id, u.username, u.full_name, u.role, u.organization_id, o.name as organization_name
        FROM Users u
        LEFT JOIN Organizations o ON u.organization_id = o.id
        WHERE u.id = ?
    """, (session.get('user_id'),))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        # Для администратора - показываем выбранный филиал
        view_org_name = None
        if session.get('role') == 'admin':
            view_org_id = session.get('view_organization_id')
            if view_org_id == '__ALL__':
                view_org_name = 'Все филиалы'
            elif view_org_id == '__NONE__':
                view_org_name = 'Без филиала'
            elif view_org_id:
                try:
                    conn = get_db()
                    cursor = conn.cursor()
                    cursor.execute("SELECT name FROM Organizations WHERE id = ?", (view_org_id,))
                    org_row = cursor.fetchone()
                    conn.close()
                    if org_row:
                        view_org_name = org_row[0]
                except:
                    pass
        
        return jsonify({
            'id': row[0],
            'username': row[1],
            'full_name': row[2] or '',
            'role': row[3],
            'organization_id': row[4],
            'organization_name': view_org_name or row[5] or ''
        })
    
    return jsonify({'error': 'Пользователь не найден'}), 404

# ========== ГЛАВНАЯ ==========
# app.py - ИСПРАВЛЕННАЯ ФУНКЦИЯ index()

# app.py - ИСПРАВЛЕННАЯ ФУНКЦИЯ index() с учетом филиала для всех счетчиков

@app.route('/')
@login_required
def index():
    conn = get_db()
    cursor = conn.cursor()
    
    org_id = get_user_organization_id()
    is_admin = session.get('role') == 'admin'
    
    # ===== ФИЛЬТР ДЛЯ КАРТРИДЖЕЙ =====
    if org_id:
        filter_cartridges = "AND C.organization_id = ?"
        filter_params_cartridges = [org_id]
    elif is_admin:
        filter_cartridges = ""
        filter_params_cartridges = []
    else:
        filter_cartridges = "AND C.organization_id IS NULL"
        filter_params_cartridges = []
    
    # ===== ФИЛЬТР ДЛЯ ЛИЦЕНЗИЙ =====
    if org_id:
        filter_licenses = "WHERE organization_id = ?"
        filter_params_licenses = [org_id]
    elif is_admin:
        filter_licenses = ""
        filter_params_licenses = []
    else:
        filter_licenses = "WHERE organization_id IS NULL"
        filter_params_licenses = []
    
    # ===== ФИЛЬТР ДЛЯ ОБОРУДОВАНИЯ =====
    if org_id:
        filter_equipment = "WHERE organization_id = ?"
        filter_params_equipment = [org_id]
    elif is_admin:
        filter_equipment = ""
        filter_params_equipment = []
    else:
        filter_equipment = "WHERE organization_id IS NULL"
        filter_params_equipment = []
    
    # ===== КОЛИЧЕСТВО КАРТРИДЖЕЙ =====
    cursor.execute(f"""
        SELECT COUNT(*) 
        FROM Catrigs C
        WHERE 1=1 {filter_cartridges}
    """, filter_params_cartridges)
    cartridges_count = cursor.fetchone()[0]
    
    # ===== КОЛИЧЕСТВО ЛИЦЕНЗИЙ (ТОЛЬКО СВОЕГО ФИЛИАЛА) =====
    cursor.execute(f"""
        SELECT COUNT(*) 
        FROM Licenses
        {filter_licenses}
    """, filter_params_licenses)
    licenses_count = cursor.fetchone()[0]
    
    # ===== КОЛИЧЕСТВО ОРГАНИЗАЦИЙ (всегда общее) =====
    cursor.execute("SELECT COUNT(*) FROM Organizations")
    organizations_count = cursor.fetchone()[0]
    
    # ===== КОЛИЧЕСТВО ОБОРУДОВАНИЯ (ТОЛЬКО СВОЕГО ФИЛИАЛА) =====
    cursor.execute(f"""
        SELECT COUNT(*) 
        FROM Equipment
        {filter_equipment}
    """, filter_params_equipment)
    equipment_count = cursor.fetchone()[0]
    
    # ===== ПРОСРОЧЕННЫЕ ЛИЦЕНЗИИ (ТОЛЬКО СВОЕГО ФИЛИАЛА) =====
    if org_id:
        cursor.execute("""
            SELECT COUNT(*) 
            FROM Licenses 
            WHERE expiry_date < date('now') 
            AND expiry_date IS NOT NULL 
            AND organization_id = ?
            AND (status IS NULL OR status != 'Не используется')
        """, (org_id,))
    elif is_admin:
        cursor.execute("""
            SELECT COUNT(*) 
            FROM Licenses 
            WHERE expiry_date < date('now') 
            AND expiry_date IS NOT NULL 
            AND (status IS NULL OR status != 'Не используется')
        """)
    else:
        cursor.execute("""
            SELECT COUNT(*) 
            FROM Licenses 
            WHERE expiry_date < date('now') 
            AND expiry_date IS NOT NULL 
            AND organization_id IS NULL
            AND (status IS NULL OR status != 'Не используется')
        """)
    expired_licenses = cursor.fetchone()[0]
    
    # ===== ПОСЛЕДНИЕ ДОБАВЛЕННЫЕ КАРТРИДЖИ =====
    cursor.execute(f"""
        SELECT 
            C.Model as model,
            C.Status,
            COALESCE(E.Department_Fullname, '—') as responsible,
            COALESCE(C.created_at, datetime('now')) as created_date,
            U.username as created_by_username, 
            U.full_name as created_by_fullname
        FROM Catrigs C
        LEFT JOIN Employees E ON C.Responsible = E.id
        LEFT JOIN Users U ON C.created_by = U.id
        WHERE 1=1 {filter_cartridges}
        ORDER BY C.created_at DESC, C.id DESC
        LIMIT 5
    """, filter_params_cartridges)
    recent_cartridges = cursor.fetchall()
    
    conn.close()
    
    return render_template('index.html', 
                         cartridges_count=cartridges_count,
                         licenses_count=licenses_count,
                         organizations_count=organizations_count,
                         equipment_count=equipment_count,
                         expired_licenses=expired_licenses,
                         recent_cartridges=recent_cartridges)

# ========== КАРТРИДЖИ ==========
@app.route('/cartridges')
@login_required
def cartridges():
    conn = get_db()
    cursor = conn.cursor()
    
    org_id = get_user_organization_id()
    is_admin = session.get('role') == 'admin'
    
    if org_id:
        filter_condition = "AND Organization_id = ?"
        filter_params = [org_id]
    elif is_admin:
        filter_condition = ""
        filter_params = []
    else:
        filter_condition = "AND Organization_id IS NULL"
        filter_params = []
    
    cursor.execute(f"""
        SELECT Department_Fullname FROM Employees 
        WHERE 1=1 {filter_condition}
        ORDER BY Department_Fullname
    """, filter_params)
    employees = [row[0] for row in cursor.fetchall()]
    
    cursor.execute("SELECT Name_MFU, id, Status FROM MFU ORDER BY Name_MFU")
    mfu_list = [{'name': row[0], 'id': row[1], 'status': row[2]} for row in cursor.fetchall()]
    
    cursor.execute("SELECT ModelName FROM CartridgeModels ORDER BY ModelName")
    cartridge_models = [row[0] for row in cursor.fetchall()]
    
    cursor.execute("SELECT Number, id FROM Rooms ORDER BY Number")
    rooms = [{'number': row[0], 'id': row[1]} for row in cursor.fetchall()]
    
    conn.close()
    
    return render_template('cartridges.html', 
                         employees=employees,
                         mfu_list=mfu_list,
                         cartridge_models=cartridge_models,
                         status_cart=STATUS_CART,
                         rooms=rooms)



@app.route('/api/cartridges', methods=['POST'])
@login_required
def add_cartridge():
    data = request.json
    print(f"DEBUG: ===== НОВЫЙ КАРТРИДЖ =====")
    print(f"DEBUG: Данные: {data}")
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        model = data.get('model', '').strip()
        if not model:
            return jsonify({'success': False, 'error': 'Модель картриджа не указана'}), 400
        
        # ===== ПОЛУЧАЕМ ФИЛИАЛ ДЛЯ НОВОЙ ЗАПИСИ =====
        org_id = get_organization_for_new_record()
        is_admin = session.get('role') == 'admin'
        view_org_id = session.get('view_organization_id')
        
        print(f"DEBUG: Филиал для новой записи: {org_id}")
        print(f"DEBUG: is_admin: {is_admin}, view_org_id: {view_org_id}")
        
        # ===== ПРОВЕРКА НАЛИЧИЯ =====
        # Если администратор с выбранным филиалом - проверяем в этом филиале
        if is_admin and view_org_id and view_org_id != '__ALL__' and view_org_id != '__NONE__':
            # Админ с конкретным филиалом
            cursor.execute("""
                SELECT InStock FROM Analytics 
                WHERE Cartridge = ? AND organization_id = ?
            """, (model, view_org_id))
            analytics = cursor.fetchone()
            in_stock = analytics[0] if analytics else 0
            print(f"DEBUG: Админ - проверка в филиале {view_org_id}, в наличии: {in_stock}")
        elif is_admin and view_org_id == '__ALL__':
            # Админ видит все филиалы - проверяем общее количество
            cursor.execute("""
                SELECT SUM(InStock) as total FROM Analytics 
                WHERE Cartridge = ?
            """, (model,))
            result = cursor.fetchone()
            in_stock = result[0] if result and result[0] else 0
            print(f"DEBUG: Админ (все филиалы) - всего в наличии: {in_stock}")
        elif org_id:
            # Обычный пользователь или админ с филиалом
            cursor.execute("""
                SELECT InStock FROM Analytics 
                WHERE Cartridge = ? AND organization_id = ?
            """, (model, org_id))
            analytics = cursor.fetchone()
            in_stock = analytics[0] if analytics else 0
            print(f"DEBUG: Проверка в филиале {org_id}, в наличии: {in_stock}")
        else:
            # Без филиала
            cursor.execute("""
                SELECT InStock FROM Analytics 
                WHERE Cartridge = ? AND organization_id IS NULL
            """, (model,))
            analytics = cursor.fetchone()
            in_stock = analytics[0] if analytics else 0
            print(f"DEBUG: Проверка без филиала, в наличии: {in_stock}")
        
        # ===== ЕСЛИ НЕТ В НАЛИЧИИ - СОЗДАЕМ =====
        if in_stock <= 0:
            print(f"DEBUG: Нет в наличии, создаем запись")
            
            # Проверяем, есть ли модель в CartridgeModels
            cursor.execute("SELECT id FROM CartridgeModels WHERE ModelName = ?", (model,))
            if not cursor.fetchone():
                cursor.execute("INSERT INTO CartridgeModels (ModelName) VALUES (?)", (model,))
                print(f"DEBUG: Модель {model} добавлена в CartridgeModels")
            
            # Создаем запись в аналитике с 1 шт.
            # Если админ с выбранным филиалом - создаем в этом филиале
            if is_admin and view_org_id and view_org_id != '__ALL__' and view_org_id != '__NONE__':
                cursor.execute("""
                    INSERT INTO Analytics (Cartridge, ToWriteOff, InStock, OnBalance, ToBuy, organization_id)
                    VALUES (?, 0, 1, 0, 0, ?)
                """, (model, view_org_id))
                print(f"DEBUG: Создана запись для {model} с 1 шт. в филиале {view_org_id}")
            elif org_id:
                cursor.execute("""
                    INSERT INTO Analytics (Cartridge, ToWriteOff, InStock, OnBalance, ToBuy, organization_id)
                    VALUES (?, 0, 1, 0, 0, ?)
                """, (model, org_id))
                print(f"DEBUG: Создана запись для {model} с 1 шт. в филиале {org_id}")
            else:
                cursor.execute("""
                    INSERT INTO Analytics (Cartridge, ToWriteOff, InStock, OnBalance, ToBuy, organization_id)
                    VALUES (?, 0, 1, 0, 0, NULL)
                """, (model,))
                print(f"DEBUG: Создана запись для {model} с 1 шт. без филиала")
            
            conn.commit()
            in_stock = 1
        
        # ===== ОБРАБОТКА ОТВЕТСТВЕННОГО =====
        responsible_id = None
        if data.get('responsible') and data.get('responsible') != '':
            cursor.execute("SELECT id FROM Employees WHERE Department_Fullname = ?", (data.get('responsible'),))
            row = cursor.fetchone()
            if row:
                responsible_id = row[0]
            else:
                cursor.execute("INSERT INTO Employees (Department_Fullname) VALUES (?)", (data.get('responsible'),))
                responsible_id = cursor.lastrowid
        
        # ===== ОБРАБОТКА КАБИНЕТА =====
        room_id = None
        room_number = data.get('room', '').strip()
        if room_number:
            cursor.execute("SELECT id FROM Rooms WHERE Number = ?", (room_number,))
            row = cursor.fetchone()
            if row:
                room_id = row[0]
            else:
                cursor.execute("INSERT INTO Rooms (Number) VALUES (?)", (room_number,))
                room_id = cursor.lastrowid
        
        # ===== ОБРАБОТКА МФУ =====
        equipment_id = None
        mfu_name = data.get('mfu', '')
        
        if mfu_name and mfu_name != '' and mfu_name != 'нет доступных МФУ' and mfu_name != '—':
            if ' (инв.' in mfu_name:
                search_name = mfu_name.split(' (инв.')[0]
            else:
                search_name = mfu_name
            
            # Ищем МФУ в выбранном филиале
            if is_admin and view_org_id and view_org_id != '__ALL__' and view_org_id != '__NONE__':
                cursor.execute("""
                    SELECT id FROM Equipment 
                    WHERE type IN ('МФУ', 'Принтер') 
                    AND (brand || ' ' || model = ? OR brand = ? OR model = ?)
                    AND organization_id = ?
                    LIMIT 1
                """, (search_name, search_name, search_name, view_org_id))
            elif org_id:
                cursor.execute("""
                    SELECT id FROM Equipment 
                    WHERE type IN ('МФУ', 'Принтер') 
                    AND (brand || ' ' || model = ? OR brand = ? OR model = ?)
                    AND organization_id = ?
                    LIMIT 1
                """, (search_name, search_name, search_name, org_id))
            else:
                cursor.execute("""
                    SELECT id FROM Equipment 
                    WHERE type IN ('МФУ', 'Принтер') 
                    AND (brand || ' ' || model = ? OR brand = ? OR model = ?)
                    AND organization_id IS NULL
                    LIMIT 1
                """, (search_name, search_name, search_name))
            
            row = cursor.fetchone()
            if row:
                equipment_id = row[0]
        
        # Добавляем поставку
        cursor.execute("INSERT INTO Postavki (Date_of_purchase) VALUES (?)", (datetime.now().date().isoformat(),))
        purchase_id = cursor.lastrowid
        
        # Вставляем картридж
        current_user_id = session.get('user_id')
        status = data.get('status', 'На складе')
        issued = data.get('issued', '0')
        ip = data.get('ip', '')
        
        import time
        serial_number = f"{model}_{int(time.time())}_{id}"
        
        # Проверяем наличие колонки organization_id
        cursor.execute("PRAGMA table_info(Catrigs)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'organization_id' not in columns:
            cursor.execute("ALTER TABLE Catrigs ADD COLUMN organization_id INTEGER")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_catrigs_organization ON Catrigs(organization_id)")
        
        # Определяем филиал для сохранения
        save_org_id = None
        if is_admin and view_org_id and view_org_id != '__ALL__' and view_org_id != '__NONE__':
            save_org_id = view_org_id
        elif org_id:
            save_org_id = org_id
        
        cursor.execute("""
            INSERT INTO Catrigs (
                Serial_number, Model, Responsible, Room_id, Status, 
                Purchase, Issued, equipment_id, Ip, created_at, created_by, organization_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?)
        """, (serial_number, model, responsible_id, room_id, status, 
              purchase_id, issued, equipment_id, ip, current_user_id, save_org_id))
        
        cartridge_id = cursor.lastrowid
        
        # Уменьшаем количество в наличии
        if save_org_id:
            cursor.execute("""
                UPDATE Analytics SET InStock = InStock - 1 
                WHERE Cartridge = ? AND organization_id = ?
            """, (model, save_org_id))
        else:
            cursor.execute("""
                UPDATE Analytics SET InStock = InStock - 1 
                WHERE Cartridge = ? AND organization_id IS NULL
            """, (model,))
        
        conn.commit()
        
        # Получаем обновленное значение
        if save_org_id:
            cursor.execute("""
                SELECT InStock FROM Analytics 
                WHERE Cartridge = ? AND organization_id = ?
            """, (model, save_org_id))
        else:
            cursor.execute("""
                SELECT InStock FROM Analytics 
                WHERE Cartridge = ? AND organization_id IS NULL
            """, (model,))
        
        result = cursor.fetchone()
        in_stock = result[0] if result else 0
        
        return jsonify({
            'success': True, 
            'message': f'✅ Картридж добавлен в филиал. Осталось в наличии: {in_stock} шт.',
            'id': cartridge_id, 
            'equipment_id': equipment_id,
            'organization_id': save_org_id
        })
        
    except Exception as e:
        conn.rollback()
        print(f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/debug/cartridge/<model>', methods=['GET'])
@login_required
def debug_cartridge_model(model):
    """Отладка - проверить модель картриджа"""
    conn = get_db()
    cursor = conn.cursor()
    
    org_id = get_user_organization_id()
    
    result = {
        'model': model,
        'user_org_id': org_id,
        'analytics': [],
        'cartridge_models': []
    }
    
    # Проверяем аналитику
    cursor.execute("""
        SELECT Cartridge, InStock, organization_id 
        FROM Analytics 
        WHERE Cartridge = ?
    """, (model,))
    result['analytics'] = [{'cartridge': r[0], 'in_stock': r[1], 'organization_id': r[2]} for r in cursor.fetchall()]
    
    # Проверяем CartridgeModels
    cursor.execute("SELECT ModelName FROM CartridgeModels WHERE ModelName = ?", (model,))
    result['cartridge_models'] = [r[0] for r in cursor.fetchall()]
    
    conn.close()
    return jsonify(result)

@app.route('/api/cartridges/<int:id>', methods=['DELETE'])
@login_required
def delete_cartridge(id):
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("DELETE FROM Catrigs WHERE id = ?", (id,))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/cartridges/<int:id>', methods=['PUT'])
@login_required
def update_cartridge(id):
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT Model, Status FROM Catrigs WHERE id = ?", (id,))
        current = cursor.fetchone()
        if not current:
            return jsonify({'success': False, 'error': 'Картридж не найден'}), 404
        
        old_status = current[1]
        model = current[0]
        new_status = data.get('status')
        
        responsible_id = None
        if data.get('responsible') and data.get('responsible') != '':
            cursor.execute("SELECT id FROM Employees WHERE Department_Fullname = ?", (data.get('responsible'),))
            row = cursor.fetchone()
            if row:
                responsible_id = row[0]
        
        room_id = None
        if data.get('room') and data.get('room') != '':
            cursor.execute("SELECT id FROM Rooms WHERE Number = ?", (data.get('room'),))
            row = cursor.fetchone()
            if row:
                room_id = row[0]
            else:
                cursor.execute("INSERT INTO Rooms (Number) VALUES (?)", (data.get('room'),))
                room_id = cursor.lastrowid
        
        equipment_id = None
        mfu_name = data.get('mfu', '')
        
        if mfu_name and mfu_name != '' and mfu_name != 'нет доступных МФУ' and mfu_name != '—':
            if ' (инв.' in mfu_name:
                search_name = mfu_name.split(' (инв.')[0]
            else:
                search_name = mfu_name
            
            org_id = get_user_organization_id()
            if org_id:
                cursor.execute("""
                    SELECT id FROM Equipment 
                    WHERE type IN ('МФУ', 'Принтер') 
                    AND (brand || ' ' || model = ? OR brand = ? OR model = ?)
                    AND organization_id = ?
                    LIMIT 1
                """, (search_name, search_name, search_name, org_id))
            else:
                cursor.execute("""
                    SELECT id FROM Equipment 
                    WHERE type IN ('МФУ', 'Принтер') 
                    AND (brand || ' ' || model = ? OR brand = ? OR model = ?)
                    AND organization_id IS NULL
                    LIMIT 1
                """, (search_name, search_name, search_name))
            
            row = cursor.fetchone()
            if row:
                equipment_id = row[0]
        
        if new_status == 'Под списание' and old_status != 'Под списание':
            org_id = get_user_organization_id()
            if org_id:
                cursor.execute("SELECT * FROM Analytics WHERE Cartridge = ? AND organization_id = ?", (model, org_id))
            else:
                cursor.execute("SELECT * FROM Analytics WHERE Cartridge = ? AND organization_id IS NULL", (model,))
            
            analytics = cursor.fetchone()
            
            if analytics:
                to_write_off = analytics[1] + 1
                in_stock = max(0, analytics[2] - 1)
                to_buy = analytics[4] + 1
                
                if org_id:
                    cursor.execute("""
                        UPDATE Analytics 
                        SET ToWriteOff = ?, InStock = ?, ToBuy = ?
                        WHERE Cartridge = ? AND organization_id = ?
                    """, (to_write_off, in_stock, to_buy, model, org_id))
                else:
                    cursor.execute("""
                        UPDATE Analytics 
                        SET ToWriteOff = ?, InStock = ?, ToBuy = ?
                        WHERE Cartridge = ? AND organization_id IS NULL
                    """, (to_write_off, in_stock, to_buy, model))
        
        elif old_status == 'Под списание' and new_status != 'Под списание':
            org_id = get_user_organization_id()
            if org_id:
                cursor.execute("SELECT * FROM Analytics WHERE Cartridge = ? AND organization_id = ?", (model, org_id))
            else:
                cursor.execute("SELECT * FROM Analytics WHERE Cartridge = ? AND organization_id IS NULL", (model,))
            
            analytics = cursor.fetchone()
            
            if analytics:
                to_write_off = max(0, analytics[1] - 1)
                in_stock = analytics[2] + 1
                to_buy = max(0, analytics[4] - 1)
                
                if org_id:
                    cursor.execute("""
                        UPDATE Analytics 
                        SET ToWriteOff = ?, InStock = ?, ToBuy = ?
                        WHERE Cartridge = ? AND organization_id = ?
                    """, (to_write_off, in_stock, to_buy, model, org_id))
                else:
                    cursor.execute("""
                        UPDATE Analytics 
                        SET ToWriteOff = ?, InStock = ?, ToBuy = ?
                        WHERE Cartridge = ? AND organization_id IS NULL
                    """, (to_write_off, in_stock, to_buy, model))
        
        cursor.execute("PRAGMA table_info(Catrigs)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'equipment_id' in columns:
            cursor.execute("""
                UPDATE Catrigs 
                SET Responsible=?, Room_id=?, Status=?, Issued=?, equipment_id=?, Ip=?
                WHERE id=?
            """, (responsible_id, room_id, new_status, data.get('issued', '0'), 
                  equipment_id, data.get('ip', ''), id))
        else:
            cursor.execute("""
                UPDATE Catrigs 
                SET Responsible=?, Room_id=?, Status=?, Issued=?, Ip=?
                WHERE id=?
            """, (responsible_id, room_id, new_status, data.get('issued', '0'), 
                  data.get('ip', ''), id))
        
        conn.commit()
        return jsonify({'success': True})
        
    except Exception as e:
        conn.rollback()
        print(f"ERROR [UPDATE]: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/cartridges/<int:id>/write-off', methods=['POST'])
@login_required
def write_off_cartridge(id):
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT id, Model, Status FROM Catrigs WHERE id = ?", (id,))
        cartridge = cursor.fetchone()
        
        if not cartridge:
            return jsonify({'success': False, 'error': 'Картридж не найден'}), 404
        
        cartridge_id = cartridge[0]
        model = cartridge[1]
        current_status = cartridge[2]
        
        if current_status == 'Под списание':
            return jsonify({'success': False, 'error': 'Картридж уже отправлен под списание'}), 400
        
        org_id = get_user_organization_id()
        
        if org_id:
            cursor.execute("SELECT * FROM Analytics WHERE Cartridge = ? AND organization_id = ?", (model, org_id))
        else:
            cursor.execute("SELECT * FROM Analytics WHERE Cartridge = ? AND organization_id IS NULL", (model,))
        
        analytics = cursor.fetchone()
        
        if analytics:
            to_write_off = analytics[1] if len(analytics) > 1 else 0
            in_stock = analytics[2] if len(analytics) > 2 else 0
            to_buy = analytics[4] if len(analytics) > 4 else 0
            
            new_to_write_off = to_write_off + 1
            new_in_stock = max(0, in_stock - 1)
            new_to_buy = to_buy + 1
            
            if org_id:
                cursor.execute("""
                    UPDATE Analytics 
                    SET ToWriteOff = ?, InStock = ?, ToBuy = ?
                    WHERE Cartridge = ? AND organization_id = ?
                """, (new_to_write_off, new_in_stock, new_to_buy, model, org_id))
            else:
                cursor.execute("""
                    UPDATE Analytics 
                    SET ToWriteOff = ?, InStock = ?, ToBuy = ?
                    WHERE Cartridge = ? AND organization_id IS NULL
                """, (new_to_write_off, new_in_stock, new_to_buy, model))
        else:
            if org_id:
                cursor.execute("""
                    INSERT INTO Analytics (Cartridge, ToWriteOff, InStock, OnBalance, ToBuy, organization_id)
                    VALUES (?, 1, 0, 0, 1, ?)
                """, (model, org_id))
            else:
                cursor.execute("""
                    INSERT INTO Analytics (Cartridge, ToWriteOff, InStock, OnBalance, ToBuy, organization_id)
                    VALUES (?, 1, 0, 0, 1, NULL)
                """, (model,))
        
        cursor.execute("UPDATE Catrigs SET Status = 'Под списание' WHERE id = ?", (id,))
        conn.commit()
        
        return jsonify({'success': True, 'message': 'Картридж отправлен под списание'})
        
    except Exception as e:
        conn.rollback()
        print(f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/cartridge-models/check', methods=['POST'])
@login_required
def check_cartridge_model():
    data = request.json
    name = data.get('name', '').strip()
    
    if not name:
        return jsonify({'exists': False, 'error': 'Название модели не указано'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM CartridgeModels WHERE ModelName = ?", (name,))
    result = cursor.fetchone()
    conn.close()
    
    return jsonify({'exists': result is not None})



@app.route('/api/mfu', methods=['GET'])
@login_required
def get_mfu():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, Name_MFU, Status FROM MFU ORDER BY Name_MFU")
    mfu_list = [{'id': row[0], 'name': row[1], 'status': row[2]} for row in cursor.fetchall()]
    conn.close()
    return jsonify(mfu_list)

@app.route('/api/mfu', methods=['POST'])
@login_required
def add_mfu():
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        org_id = get_organization_for_new_record()
        
        cursor.execute("""
            INSERT INTO Equipment (type, brand, model, status, organization_id, notes)
            VALUES ('МФУ', ?, ?, ?, ?, 'Добавлено из раздела картриджей')
        """, (data.get('name'), '', data.get('status', 'Работает'), org_id))
        
        conn.commit()
        return jsonify({'success': True, 'id': cursor.lastrowid})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'error': 'МФУ уже существует'}), 400
    finally:
        conn.close()

@app.route('/api/mfu/<int:id>/status', methods=['PUT'])
@login_required
def update_mfu_status(id):
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("UPDATE MFU SET Status = ? WHERE id = ?", (data.get('status'), id))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/cartridge-models', methods=['GET'])
@login_required
def get_cartridge_models():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT ModelName FROM CartridgeModels ORDER BY ModelName")
    models = [row[0] for row in cursor.fetchall()]
    conn.close()
    return jsonify(models)

@app.route('/api/cartridge-models', methods=['POST'])
@login_required
def add_cartridge_model():
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        model_name = data.get('name', '').strip()
        quantity = int(data.get('quantity', 0))
        
        if not model_name:
            return jsonify({'success': False, 'error': 'Введите название модели'}), 400
        
        # ===== ПОЛУЧАЕМ ФИЛИАЛ ДЛЯ НОВОЙ ЗАПИСИ =====
        org_id = get_organization_for_new_record()
        is_admin = session.get('role') == 'admin'
        view_org_id = session.get('view_organization_id')
        
        print(f"DEBUG: Филиал для новой модели: {org_id}")
        
        # Определяем филиал для сохранения
        save_org_id = None
        if is_admin and view_org_id and view_org_id != '__ALL__' and view_org_id != '__NONE__':
            save_org_id = view_org_id
        elif org_id:
            save_org_id = org_id
        
        # Добавляем модель в CartridgeModels (если её нет)
        cursor.execute("INSERT OR IGNORE INTO CartridgeModels (ModelName) VALUES (?)", (model_name,))
        
        # Проверяем, есть ли уже аналитика для этой модели в этом филиале
        if save_org_id:
            cursor.execute("""
                SELECT id, InStock FROM Analytics 
                WHERE Cartridge = ? AND organization_id = ?
            """, (model_name, save_org_id))
        else:
            cursor.execute("""
                SELECT id, InStock FROM Analytics 
                WHERE Cartridge = ? AND organization_id IS NULL
            """, (model_name,))
        
        existing = cursor.fetchone()
        
        if existing:
            # Обновляем существующую запись
            if save_org_id:
                cursor.execute("""
                    UPDATE Analytics 
                    SET InStock = InStock + ?
                    WHERE Cartridge = ? AND organization_id = ?
                """, (quantity, model_name, save_org_id))
            else:
                cursor.execute("""
                    UPDATE Analytics 
                    SET InStock = InStock + ?
                    WHERE Cartridge = ? AND organization_id IS NULL
                """, (quantity, model_name))
        else:
            # Создаем новую запись в аналитике
            cursor.execute("""
                INSERT INTO Analytics (Cartridge, ToWriteOff, InStock, OnBalance, ToBuy, organization_id)
                VALUES (?, 0, ?, 0, 0, ?)
            """, (model_name, quantity, save_org_id))
        
        conn.commit()
        
        return jsonify({
            'success': True, 
            'message': f'Модель "{model_name}" добавлена',
            'in_stock': quantity
        })
        
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'error': 'Модель уже существует'}), 400
    except Exception as e:
        conn.rollback()
        print(f"ERROR: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/debug/analytics', methods=['GET'])
@login_required
def debug_analytics():
    """Отладка - показать всю аналитику"""
    conn = get_db()
    cursor = conn.cursor()
    
    org_id = get_user_organization_id()
    
    cursor.execute("SELECT Cartridge, ToWriteOff, InStock, OnBalance, ToBuy, organization_id FROM Analytics")
    all_analytics = cursor.fetchall()
    
    result = {
        'all': [{'cartridge': row[0], 'to_write_off': row[1], 'in_stock': row[2], 
                 'on_balance': row[3], 'to_buy': row[4], 'organization_id': row[5]} for row in all_analytics],
        'user_org_id': org_id,
        'count': len(all_analytics)
    }
    
    conn.close()
    return jsonify(result)

# ========== АНАЛИТИКА ==========
@app.route('/api/analytics', methods=['GET'])
@login_required
def get_analytics():
    """Получить аналитику с названием филиала"""
    conn = get_db()
    cursor = conn.cursor()
    
    org_id = get_user_organization_id()
    is_admin = session.get('role') == 'admin'
    
    # Базовый запрос с JOIN на Organizations
    query = """
        SELECT a.Cartridge, a.ToWriteOff, a.InStock, a.OnBalance, a.ToBuy,
               a.organization_id, o.name as organization_name
        FROM Analytics a
        LEFT JOIN Organizations o ON a.organization_id = o.id
    """
    
    # Фильтр по филиалу
    if is_admin and not org_id:
        # Админ без филиала – видит всё
        query += " ORDER BY a.Cartridge"
        params = []
    elif org_id:
        query += " WHERE a.organization_id = ? ORDER BY a.Cartridge"
        params = [org_id]
    else:
        query += " WHERE a.organization_id IS NULL ORDER BY a.Cartridge"
        params = []
    
    cursor.execute(query, params)
    
    analytics = []
    for row in cursor.fetchall():
        analytics.append({
            'cartridge': row[0],
            'to_write_off': row[1],
            'in_stock': row[2],
            'on_balance': row[3],
            'to_buy': row[4],
            'organization_id': row[5],
            'organization_name': row[6] if row[6] else 'Без филиала'   # <-- название
        })
    
    conn.close()
    return jsonify(analytics)

# app.py - ДОБАВЬТЕ ЭТОТ ЭНДПОИНТ

@app.route('/api/admin/switch-organization', methods=['POST'])
@login_required
@admin_required
def switch_organization():
    """Переключение филиала для администратора"""
    data = request.json
    org_id = data.get('organization_id')
    
    print(f"DEBUG: Переключение филиала на: {org_id}")
    
    # Сохраняем выбранный филиал в сессию
    session['view_organization_id'] = org_id
    
    # Получаем название филиала для отображения
    org_name = None
    if org_id == '__ALL__':
        org_name = 'Все филиалы'
    elif org_id == '__NONE__':
        org_name = 'Без филиала'
    elif org_id:
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM Organizations WHERE id = ?", (org_id,))
            row = cursor.fetchone()
            conn.close()
            if row:
                org_name = row[0]
        except:
            pass
    
    return jsonify({
        'success': True,
        'organization_id': org_id,
        'organization_name': org_name
    })

# app.py - ДОБАВЬТЕ КОНТЕКСТНЫЙ ПРОЦЕССОР

@app.context_processor
def inject_organizations():
    """Добавляет список организаций во все шаблоны для селектора филиала"""
    organizations = []
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM Organizations ORDER BY name")
        organizations = [{'id': row[0], 'name': row[1]} for row in cursor.fetchall()]
        conn.close()
    except Exception as e:
        print(f"Ошибка загрузки организаций: {e}")
    
    return {'organizations': organizations}

@app.route('/api/analytics', methods=['POST'])
@login_required
def add_analytics():
    """Добавить или обновить запись в аналитике"""
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cartridge = data.get('cartridge', '').strip()
        to_write_off = int(data.get('to_write_off', 0))
        in_stock = int(data.get('in_stock', 0))
        on_balance = int(data.get('on_balance', 0))
        to_buy = int(data.get('to_buy', 0))
        
        if not cartridge:
            return jsonify({'success': False, 'error': 'Модель картриджа не указана'}), 400
        
        # Получаем филиал пользователя
        org_id = get_user_organization_id()
        is_admin = session.get('role') == 'admin'
        
        print(f"DEBUG: Обновление аналитики - модель: {cartridge}, филиал: {org_id}, is_admin: {is_admin}")
        
        # Проверяем, существует ли запись для этой модели в этом филиале
        if org_id:
            cursor.execute("""
                SELECT Cartridge FROM Analytics 
                WHERE Cartridge = ? AND organization_id = ?
            """, (cartridge, org_id))
        else:
            cursor.execute("""
                SELECT Cartridge FROM Analytics 
                WHERE Cartridge = ? AND organization_id IS NULL
            """, (cartridge,))
        
        existing = cursor.fetchone()
        
        if existing:
            # Обновляем существующую запись
            if org_id:
                cursor.execute("""
                    UPDATE Analytics 
                    SET ToWriteOff = ?, InStock = ?, OnBalance = ?, ToBuy = ?
                    WHERE Cartridge = ? AND organization_id = ?
                """, (to_write_off, in_stock, on_balance, to_buy, cartridge, org_id))
            else:
                cursor.execute("""
                    UPDATE Analytics 
                    SET ToWriteOff = ?, InStock = ?, OnBalance = ?, ToBuy = ?
                    WHERE Cartridge = ? AND organization_id IS NULL
                """, (to_write_off, in_stock, on_balance, to_buy, cartridge))
            print(f"DEBUG: Обновлена аналитика для {cartridge}")
        else:
            # Создаем новую запись
            cursor.execute("""
                INSERT INTO Analytics (Cartridge, ToWriteOff, InStock, OnBalance, ToBuy, organization_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (cartridge, to_write_off, in_stock, on_balance, to_buy, org_id))
            print(f"DEBUG: Создана аналитика для {cartridge}")
        
        conn.commit()
        return jsonify({'success': True})
        
    except Exception as e:
        conn.rollback()
        print(f"ERROR [add_analytics]: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/analytics/add-stock', methods=['POST'])
@login_required
def add_analytics_stock():
    data = request.json
    cartridge_model = data.get('cartridge', '').strip()
    quantity = int(data.get('quantity', 0))
    
    if not cartridge_model:
        return jsonify({'success': False, 'error': 'Модель картриджа не указана'}), 400
    
    if quantity <= 0:
        return jsonify({'success': False, 'error': 'Количество должно быть больше 0'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        org_id = get_user_organization_id()
        
        if org_id:
            cursor.execute("SELECT * FROM Analytics WHERE Cartridge = ? AND organization_id = ?", (cartridge_model, org_id))
        else:
            cursor.execute("SELECT * FROM Analytics WHERE Cartridge = ? AND organization_id IS NULL", (cartridge_model,))
        
        analytics = cursor.fetchone()
        
        if analytics:
            if org_id:
                cursor.execute("""
                    UPDATE Analytics 
                    SET InStock = InStock + ?
                    WHERE Cartridge = ? AND organization_id = ?
                """, (quantity, cartridge_model, org_id))
            else:
                cursor.execute("""
                    UPDATE Analytics 
                    SET InStock = InStock + ?
                    WHERE Cartridge = ? AND organization_id IS NULL
                """, (quantity, cartridge_model))
        else:
            cursor.execute("""
                INSERT INTO Analytics (Cartridge, ToWriteOff, InStock, OnBalance, ToBuy, organization_id)
                VALUES (?, 0, ?, 0, 0, ?)
            """, (cartridge_model, quantity, org_id))
        
        conn.commit()
        
        if org_id:
            cursor.execute("SELECT InStock FROM Analytics WHERE Cartridge = ? AND organization_id = ?", (cartridge_model, org_id))
        else:
            cursor.execute("SELECT InStock FROM Analytics WHERE Cartridge = ? AND organization_id IS NULL", (cartridge_model,))
        
        result = cursor.fetchone()
        in_stock = result[0] if result else quantity
        
        return jsonify({
            'success': True,
            'message': f'Количество для {cartridge_model} увеличено на {quantity}',
            'in_stock': in_stock
        })
        
    except Exception as e:
        conn.rollback()
        print(f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/analytics/check-stock', methods=['POST'])
@login_required
def check_stock():
    """Проверить количество в наличии для модели"""
    data = request.json
    model = data.get('model', '').strip()
    
    if not model:
        return jsonify({'success': False, 'error': 'Модель не указана'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    user_org_id = get_user_organization_id()
    is_admin = session.get('role') == 'admin'
    
    print(f"DEBUG: check_stock - модель: {model}, филиал: {user_org_id}, is_admin: {is_admin}")
    
    # Если админ без филиала - считаем общее количество по ВСЕМ филиалам
    if is_admin and not user_org_id:
        cursor.execute("""
            SELECT SUM(InStock) as total FROM Analytics 
            WHERE Cartridge = ?
        """, (model,))
        result = cursor.fetchone()
        in_stock = result[0] if result and result[0] else 0
        print(f"DEBUG: Админ - общее количество для {model}: {in_stock} шт.")
    else:
        # Обычный пользователь или админ с филиалом
        if user_org_id:
            cursor.execute("""
                SELECT InStock FROM Analytics 
                WHERE Cartridge = ? AND organization_id = ?
            """, (model, user_org_id))
        else:
            cursor.execute("""
                SELECT InStock FROM Analytics 
                WHERE Cartridge = ? AND organization_id IS NULL
            """, (model,))
        
        result = cursor.fetchone()
        in_stock = result[0] if result else 0
        print(f"DEBUG: В наличии для {model} в филиале {user_org_id}: {in_stock} шт.")
    
    conn.close()
    
    return jsonify({
        'success': True,
        'in_stock': in_stock,
        'model': model,
        'organization_id': user_org_id,
        'is_admin': is_admin
    })

# ========== ЭКСПОРТ АНАЛИТИКИ ==========
@app.route('/api/analytics/export/excel', methods=['GET'])
@login_required
def export_analytics_excel():
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        org_id = get_user_organization_id()
        is_admin = session.get('role') == 'admin'
        
        if org_id:
            query = """
                SELECT 
                    Cartridge as 'Модель картриджа',
                    ToWriteOff as 'Под списание',
                    InStock as 'В наличии',
                    OnBalance as 'На балансе',
                    ToBuy as 'Закупить'
                FROM Analytics 
                WHERE organization_id = ?
                ORDER BY Cartridge
            """
            params = [org_id]
        elif is_admin:
            query = """
                SELECT 
                    Cartridge as 'Модель картриджа',
                    ToWriteOff as 'Под списание',
                    InStock as 'В наличии',
                    OnBalance as 'На балансе',
                    ToBuy as 'Закупить'
                FROM Analytics 
                ORDER BY Cartridge
            """
            params = []
        else:
            query = """
                SELECT 
                    Cartridge as 'Модель картриджа',
                    ToWriteOff as 'Под списание',
                    InStock as 'В наличии',
                    OnBalance as 'На балансе',
                    ToBuy as 'Закупить'
                FROM Analytics 
                WHERE organization_id IS NULL
                ORDER BY Cartridge
            """
            params = []
        
        cursor.execute(query, params)
        data = cursor.fetchall()
        conn.close()
        
        if not data:
            return jsonify({'error': 'Нет данных для экспорта'}), 404
        
        df = pd.DataFrame(data, columns=['Модель картриджа', 'Под списание', 'В наличии', 'На балансе', 'Закупить'])
        
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Аналитика', index=False)
            
            worksheet = writer.sheets['Аналитика']
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                worksheet.column_dimensions[column_letter].width = adjusted_width
        
        output.seek(0)
        
        filename = f"analytics_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
        
    except ImportError:
        return jsonify({'error': 'Для экспорта в Excel требуется установка pandas и openpyxl'}), 500
    except Exception as e:
        print(f"ERROR export_analytics_excel: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics/export/csv', methods=['GET'])
@login_required
def export_analytics_csv():
    try:
        import csv
        
        conn = get_db()
        cursor = conn.cursor()
        
        org_id = get_user_organization_id()
        is_admin = session.get('role') == 'admin'
        
        if org_id:
            query = """
                SELECT Cartridge, ToWriteOff, InStock, OnBalance, ToBuy
                FROM Analytics 
                WHERE organization_id = ?
                ORDER BY Cartridge
            """
            params = [org_id]
        elif is_admin:
            query = """
                SELECT Cartridge, ToWriteOff, InStock, OnBalance, ToBuy
                FROM Analytics 
                ORDER BY Cartridge
            """
            params = []
        else:
            query = """
                SELECT Cartridge, ToWriteOff, InStock, OnBalance, ToBuy
                FROM Analytics 
                WHERE organization_id IS NULL
                ORDER BY Cartridge
            """
            params = []
        
        cursor.execute(query, params)
        data = cursor.fetchall()
        conn.close()
        
        if not data:
            return jsonify({'error': 'Нет данных для экспорта'}), 404
        
        output = StringIO()
        writer = csv.writer(output, delimiter=';')
        writer.writerow(['Модель картриджа', 'Под списание', 'В наличии', 'На балансе', 'Закупить'])
        
        for row in data:
            writer.writerow(row)
        
        output.seek(0)
        
        filename = f"analytics_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        return send_file(
            BytesIO(output.getvalue().encode('utf-8-sig')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        print(f"ERROR export_analytics_csv: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics/export/txt', methods=['GET'])
@login_required
def export_analytics_txt():
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        org_id = get_user_organization_id()
        is_admin = session.get('role') == 'admin'
        
        if org_id:
            query = "SELECT Cartridge FROM Analytics WHERE organization_id = ? ORDER BY Cartridge"
            params = [org_id]
        elif is_admin:
            query = "SELECT Cartridge FROM Analytics ORDER BY Cartridge"
            params = []
        else:
            query = "SELECT Cartridge FROM Analytics WHERE organization_id IS NULL ORDER BY Cartridge"
            params = []
        
        cursor.execute(query, params)
        data = cursor.fetchall()
        conn.close()
        
        if not data:
            return jsonify({'error': 'Нет данных для экспорта'}), 404
        
        output = StringIO()
        
        output.write("СПИСОК МОДЕЛЕЙ КАРТРИДЖЕЙ\n")
        output.write("=" * 50 + "\n")
        output.write(f"Дата экспорта: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n")
        output.write(f"Всего моделей: {len(data)}\n")
        output.write("-" * 50 + "\n\n")
        
        for i, row in enumerate(data, 1):
            output.write(f"{i:3}. {row[0]}\n")
        
        output.write("\n" + "-" * 50 + "\n")
        output.write(f"Итого: {len(data)} моделей\n")
        
        output.seek(0)
        
        filename = f"cartridge_models_list_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        return send_file(
            BytesIO(output.getvalue().encode('utf-8-sig')),
            mimetype='text/plain',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        print(f"ERROR export_analytics_txt: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# ========== СОВМЕСТИМОСТЬ ==========
@app.route('/compatibility')
@login_required
def compatibility_page():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT ModelName FROM CartridgeModels ORDER BY ModelName")
    cartridges = [row[0] for row in cursor.fetchall()]
    
    cursor.execute("SELECT Name_MFU FROM MFU ORDER BY Name_MFU")
    mfu_list = [row[0] for row in cursor.fetchall()]
    
    conn.close()
    return render_template('compatibility.html', cartridges=cartridges, mfu_list=mfu_list)

@app.route('/api/compatibility', methods=['GET'])
@login_required
def get_compatibility():
    conn = get_db()
    cursor = conn.cursor()

    # Показываем все записи без фильтрации по филиалу
    cursor.execute("""
        SELECT id, cartridge_model, mfu_model, organization_id 
        FROM Compatibility 
        ORDER BY cartridge_model
    """)

    compatibility = []
    for row in cursor.fetchall():
        compatibility.append({
            'id': row[0],
            'cartridge': row[1],
            'mfu': row[2],
            'organization_id': row[3]
        })

    conn.close()
    return jsonify(compatibility)

@app.route('/api/compatibility', methods=['POST'])
@login_required
def add_compatibility():
    data = request.json
    conn = get_db()
    cursor = conn.cursor()

    try:
        # Убираем привязку к филиалу – сохраняем как NULL
        # org_id = get_organization_for_new_record()  // было
        org_id = None  # <-- теперь всегда NULL
        cursor.execute("""
            INSERT INTO Compatibility (cartridge_model, mfu_model, organization_id)
            VALUES (?, ?, ?)
        """, (data.get('cartridge'), data.get('mfu'), org_id))
        conn.commit()
        return jsonify({'success': True, 'id': cursor.lastrowid})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'error': 'Такая запись уже существует'}), 400
    finally:
        conn.close()

@app.route('/api/compatibility/<int:id>', methods=['DELETE'])
@login_required
def delete_compatibility(id):
    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute("DELETE FROM Compatibility WHERE id = ?", (id,))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/compatibility/<int:id>', methods=['PUT'])
@login_required
def update_compatibility(id):
    data = request.json
    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE Compatibility 
            SET cartridge_model = ?, mfu_model = ?
            WHERE id = ?
        """, (data.get('cartridge'), data.get('mfu'), id))
        conn.commit()
        return jsonify({'success': True})
    except sqlite3.IntegrityError:
        conn.rollback()
        return jsonify({'success': False, 'error': 'Такая запись уже существует'}), 400
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/compatibility/check', methods=['POST'])
@login_required
def check_compatibility():
    data = request.json
    conn = get_db()
    cursor = conn.cursor()

    view_org_id = get_view_organization_id()
    is_admin = session.get('role') == 'admin'

    if is_admin and view_org_id == '__ALL__':
        cursor.execute("""
            SELECT * FROM Compatibility 
            WHERE cartridge_model = ? AND mfu_model = ?
        """, (data.get('cartridge'), data.get('mfu')))
    elif view_org_id:
        cursor.execute("""
            SELECT * FROM Compatibility 
            WHERE cartridge_model = ? AND mfu_model = ? AND organization_id = ?
        """, (data.get('cartridge'), data.get('mfu'), view_org_id))
    else:
        cursor.execute("""
            SELECT * FROM Compatibility 
            WHERE cartridge_model = ? AND mfu_model = ? AND organization_id IS NULL
        """, (data.get('cartridge'), data.get('mfu')))

    result = cursor.fetchone()
    conn.close()
    return jsonify({'compatible': result is not None})

@app.route('/api/compatibility/import-excel', methods=['POST'])
@login_required
def import_compatibility_excel():
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'Файл не выбран'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'Файл не выбран'}), 400

    if not file.filename.endswith(('.xlsx', '.xls')):
        return jsonify({'success': False, 'error': 'Поддерживаются только файлы Excel (.xlsx, .xls)'}), 400

    try:
        df = pd.read_excel(file)

        required_columns = ['cartridge_model', 'mfu_model']
        for col in required_columns:
            if col not in df.columns:
                return jsonify({'success': False, 'error': f'В файле отсутствует колонка "{col}"'}), 400

        conn = get_db()
        cursor = conn.cursor()
        org_id = get_organization_for_new_record()

        added = 0
        skipped = 0

        for _, row in df.iterrows():
            cartridge = str(row['cartridge_model']).strip()
            mfu = str(row['mfu_model']).strip()

            if cartridge and mfu and cartridge != 'nan' and mfu != 'nan':
                try:
                    cursor.execute("""
                        INSERT INTO Compatibility (cartridge_model, mfu_model, organization_id)
                        VALUES (?, ?, ?)
                    """, (cartridge, mfu, org_id))
                    added += 1
                except sqlite3.IntegrityError:
                    skipped += 1

        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'added': added,
            'skipped': skipped,
            'message': f'Импортировано {added} записей, пропущено дубликатов: {skipped}'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/api/compatibility/compatible-mfus', methods=['POST'])
@login_required
def get_compatible_mfus():
    data = request.json
    cartridge_model = data.get('cartridge_model', '').strip()

    if not cartridge_model:
        return jsonify([])

    conn = get_db()
    cursor = conn.cursor()

    view_org_id = get_view_organization_id()
    is_admin = session.get('role') == 'admin'

    # 1. Получаем список совместимых моделей МФУ
    if is_admin and view_org_id == '__ALL__':
        cursor.execute("""
            SELECT mfu_model FROM Compatibility 
            WHERE cartridge_model = ?
        """, (cartridge_model,))
    elif view_org_id:
        cursor.execute("""
            SELECT mfu_model FROM Compatibility 
            WHERE cartridge_model = ? AND organization_id = ?
        """, (cartridge_model, view_org_id))
    else:
        cursor.execute("""
            SELECT mfu_model FROM Compatibility 
            WHERE cartridge_model = ? AND organization_id IS NULL
        """, (cartridge_model,))

    compatible_mfu_names = [row[0] for row in cursor.fetchall()]

    # 2. Ищем эти модели МФУ в таблице Equipment
    result = []
    for mfu_name in compatible_mfu_names:
        if is_admin and view_org_id == '__ALL__':
            cursor.execute("""
                SELECT id, type, brand, model, status, inventory_number 
                FROM Equipment 
                WHERE type IN ('МФУ', 'Принтер') 
                AND (brand LIKE ? OR model LIKE ? OR brand || ' ' || model LIKE ?)
            """, (f'%{mfu_name}%', f'%{mfu_name}%', f'%{mfu_name}%'))
        elif view_org_id:
            cursor.execute("""
                SELECT id, type, brand, model, status, inventory_number 
                FROM Equipment 
                WHERE type IN ('МФУ', 'Принтер') 
                AND (brand LIKE ? OR model LIKE ? OR brand || ' ' || model LIKE ?)
                AND organization_id = ?
            """, (f'%{mfu_name}%', f'%{mfu_name}%', f'%{mfu_name}%', view_org_id))
        else:
            cursor.execute("""
                SELECT id, type, brand, model, status, inventory_number 
                FROM Equipment 
                WHERE type IN ('МФУ', 'Принтер') 
                AND (brand LIKE ? OR model LIKE ? OR brand || ' ' || model LIKE ?)
                AND organization_id IS NULL
            """, (f'%{mfu_name}%', f'%{mfu_name}%', f'%{mfu_name}%'))

        rows = cursor.fetchall()
        for row in rows:
            brand = row[2] or ''
            model = row[3] or ''
            if brand and model:
                name = f"{brand} {model}".strip()
            elif brand:
                name = brand
            elif model:
                name = model
            else:
                name = "Без названия"

            # Убираем дубли
            existing = next((r for r in result if r['id'] == row[0]), None)
            if not existing:
                result.append({
                    'id': row[0],
                    'name': name,
                    'status': row[4] or 'В работе',
                    'inventory_number': row[5] or ''
                })

    conn.close()
    return jsonify(result)

# ========== ЛИЦЕНЗИИ ==========
@app.route('/licenses')
@login_required
def licenses():
    return render_template('licenses.html')

@app.route('/api/licenses', methods=['GET'])
@login_required
def get_licenses():
    conn = get_db()
    cursor = conn.cursor()
    
    org_id = get_user_organization_id()
    is_admin = session.get('role') == 'admin'
    
    if org_id:
        cursor.execute("""
            SELECT id, product_name, product_key, expiry_date, company, quantity, used, organization_id, status
            FROM Licenses 
            WHERE organization_id = ?
            ORDER BY id DESC
        """, (org_id,))
    elif is_admin:
        cursor.execute("""
            SELECT id, product_name, product_key, expiry_date, company, quantity, used, organization_id, status
            FROM Licenses 
            ORDER BY id DESC
        """)
    else:
        cursor.execute("""
            SELECT id, product_name, product_key, expiry_date, company, quantity, used, organization_id, status
            FROM Licenses 
            WHERE organization_id IS NULL
            ORDER BY id DESC
        """)
    
    licenses = []
    for row in cursor.fetchall():
        licenses.append({
            'id': row[0],
            'product_name': row[1],
            'product_key': row[2],
            'expiry_date': row[3] if row[3] else '',
            'company': row[4] if row[4] else '',
            'quantity': row[5],
            'used': row[6],
            'organization_id': row[7],
            'status': row[8] if len(row) > 8 else 'Активна'   # <-- ДОБАВЛЕНО
        })
    
    conn.close()
    return jsonify(licenses)

@app.route('/api/licenses', methods=['POST'])
@login_required
def add_license():
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        save_org_id = get_organization_for_new_record()
        cursor.execute("""
            INSERT INTO Licenses (product_name, product_key, expiry_date, company, quantity, used, organization_id, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get('product_name'), 
            data.get('product_key'), 
            data.get('expiry_date'), 
            data.get('company'), 
            data.get('quantity', 0), 
            data.get('used', 0),
            save_org_id,
            data.get('status', 'Активна')   # <-- ДОБАВЛЕНО
        ))
        conn.commit()
        return jsonify({'success': True, 'id': cursor.lastrowid})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'error': 'Лицензия с таким ключом уже существует'}), 400
    finally:
        conn.close()

@app.route('/api/licenses/<int:id>', methods=['PUT'])
@login_required
def update_license(id):
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE Licenses 
            SET product_name=?, product_key=?, expiry_date=?, company=?, quantity=?, used=?, status=?
            WHERE id=?
        """, (
            data.get('product_name'), 
            data.get('product_key'), 
            data.get('expiry_date'),
            data.get('company'), 
            data.get('quantity', 0), 
            data.get('used', 0),
            data.get('status', 'Активна'),   # <-- ДОБАВЛЕНО
            id
        ))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/licenses/<int:id>', methods=['DELETE'])
@login_required
def delete_license(id):
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("DELETE FROM Licenses WHERE id = ?", (id,))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/licenses/import-excel', methods=['POST'])
@login_required
def import_licenses_excel():
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'Файл не выбран'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'Файл не выбран'}), 400
    
    if not file.filename.endswith(('.xlsx', '.xls')):
        return jsonify({'success': False, 'error': 'Поддерживаются только файлы Excel (.xlsx, .xls)'}), 400
    
    try:
        df = pd.read_excel(file)
        
        required_columns = ['Название продукта', 'Ключ продукта', 'Срок действия', 'Компания продукта', 'Количество', 'Используется (кол-во)']
        
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            return jsonify({
                'success': False, 
                'error': f'В файле отсутствуют колонки: {", ".join(missing_columns)}'
            }), 400
        
        conn = get_db()
        cursor = conn.cursor()
        org_id = get_organization_for_new_record()
        
        added = 0
        skipped = 0
        errors = []
        
        for idx, row in df.iterrows():
            try:
                product_name = str(row['Название продукта']).strip() if pd.notna(row['Название продукта']) else ''
                
                product_key = None
                if pd.notna(row['Ключ продукта']):
                    product_key = str(row['Ключ продукта']).strip()
                    if product_key == '' or product_key.lower() == 'nan':
                        product_key = None
                
                expiry_date_raw = str(row['Срок действия']).strip() if pd.notna(row['Срок действия']) else ''
                company = str(row['Компания продукта']).strip() if pd.notna(row['Компания продукта']) else ''
                quantity = int(row['Количество']) if pd.notna(row['Количество']) else 1
                used = int(row['Используется (кол-во)']) if pd.notna(row['Используется (кол-во)']) else 0
                
                if not product_name:
                    errors.append(f'Строка {idx+2}: пропущено название продукта')
                    skipped += 1
                    continue
                
                expiry_date = None
                if expiry_date_raw and expiry_date_raw.lower() != 'бессрочно' and expiry_date_raw.lower() != 'nan':
                    try:
                        for fmt in ['%d.%m.%Y', '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y']:
                            try:
                                expiry_date = datetime.strptime(expiry_date_raw, fmt).date().isoformat()
                                break
                            except ValueError:
                                continue
                        if expiry_date is None:
                            try:
                                parsed = pd.to_datetime(expiry_date_raw)
                                expiry_date = parsed.date().isoformat()
                            except:
                                errors.append(f'Строка {idx+2}: не удалось распарсить дату "{expiry_date_raw}"')
                                skipped += 1
                                continue
                    except Exception as e:
                        errors.append(f'Строка {idx+2}: ошибка обработки даты "{expiry_date_raw}" - {str(e)}')
                        skipped += 1
                        continue
                elif expiry_date_raw and expiry_date_raw.lower() == 'бессрочно':
                    expiry_date = '3000-01-01'
                
                if product_key:
                    cursor.execute("SELECT id FROM Licenses WHERE product_key = ?", (product_key,))
                    if cursor.fetchone():
                        errors.append(f'Строка {idx+2}: ключ "{product_key}" уже существует')
                        skipped += 1
                        continue
                
                cursor.execute("""
                    INSERT INTO Licenses (product_name, product_key, expiry_date, company, quantity, used, organization_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (product_name, product_key, expiry_date, company, quantity, used, org_id))
                added += 1
                
            except Exception as e:
                errors.append(f'Строка {idx+2}: {str(e)}')
                skipped += 1
        
        conn.commit()
        conn.close()
        
        result_message = f'✅ Импортировано лицензий: {added}'
        if skipped > 0:
            result_message += f', пропущено: {skipped}'
        if errors:
            result_message += f'\n\n⚠️ Ошибки:\n' + '\n'.join(errors[:5])
            if len(errors) > 5:
                result_message += f'\n... и еще {len(errors) - 5} ошибок'
        
        return jsonify({
            'success': True,
            'added': added,
            'skipped': skipped,
            'message': result_message,
            'errors': errors
        })
        
    except Exception as e:
        print(f"ERROR [IMPORT LICENSES]: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/api/licenses/search', methods=['POST'])
@login_required
def search_licenses():
    data = request.json
    search_term = data.get('search', '')
    conn = get_db()
    cursor = conn.cursor()
    
    org_id = get_user_organization_id()
    is_admin = session.get('role') == 'admin'
    
    if org_id:
        cursor.execute("""
            SELECT id, product_name, product_key, expiry_date, company, quantity, used 
            FROM Licenses 
            WHERE (product_name LIKE ? OR product_key LIKE ? OR company LIKE ?) AND organization_id = ?
            ORDER BY id DESC
        """, (f'%{search_term}%', f'%{search_term}%', f'%{search_term}%', org_id))
    elif is_admin:
        cursor.execute("""
            SELECT id, product_name, product_key, expiry_date, company, quantity, used 
            FROM Licenses 
            WHERE product_name LIKE ? OR product_key LIKE ? OR company LIKE ?
            ORDER BY id DESC
        """, (f'%{search_term}%', f'%{search_term}%', f'%{search_term}%'))
    else:
        cursor.execute("""
            SELECT id, product_name, product_key, expiry_date, company, quantity, used 
            FROM Licenses 
            WHERE (product_name LIKE ? OR product_key LIKE ? OR company LIKE ?) AND organization_id IS NULL
            ORDER BY id DESC
        """, (f'%{search_term}%', f'%{search_term}%', f'%{search_term}%'))
    
    licenses = []
    for row in cursor.fetchall():
        licenses.append({
            'id': row[0],
            'product_name': row[1],
            'product_key': row[2],
            'expiry_date': row[3] if row[3] else '',
            'company': row[4] if row[4] else '',
            'quantity': row[5],
            'used': row[6]
        })
    
    conn.close()
    return jsonify(licenses)

# ========== ОРГАНИЗАЦИИ ==========
@app.route('/api/organizations', methods=['GET'])
@login_required
def api_get_organizations():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM Organizations ORDER BY name")
    orgs = cursor.fetchall()
    result = []
    for org in orgs:
        cursor.execute("SELECT address FROM OrganizationAddresses WHERE organization_id = ?", (org[0],))
        addresses = [row[0] for row in cursor.fetchall()]
        result.append({'id': org[0], 'name': org[1], 'addresses': addresses})
    conn.close()
    return jsonify(result)
@app.route('/api/organizations/<int:id>', methods=['GET'])
@login_required
def api_get_organization(id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM Organizations WHERE id = ?", (id,))
    org = cursor.fetchone()
    if not org:
        return jsonify({'error': 'Не найдено'}), 404
    cursor.execute("SELECT address FROM OrganizationAddresses WHERE organization_id = ?", (id,))
    addresses = [row[0] for row in cursor.fetchall()]
    conn.close()
    return jsonify({'id': org[0], 'name': org[1], 'addresses': addresses})

@app.route('/api/organizations/list', methods=['GET'])
@login_required
def api_get_organizations_list():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM Organizations ORDER BY name")
    organizations = [{'id': row[0], 'name': row[1]} for row in cursor.fetchall()]
    conn.close()
    return jsonify(organizations)

@app.route('/api/organizations', methods=['POST'])
@login_required
def api_add_organization():
    data = request.json
    name = data.get('name')
    addresses = data.get('addresses', [])
    if not name:
        return jsonify({'success': False, 'error': 'Введите название'}), 400
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO Organizations (name) VALUES (?)", (name,))
        org_id = cursor.lastrowid
        for addr in addresses:
            if addr.strip():
                cursor.execute("INSERT INTO OrganizationAddresses (organization_id, address) VALUES (?, ?)",
                               (org_id, addr.strip()))
        conn.commit()
        return jsonify({'success': True, 'id': org_id})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/organizations/<int:id>', methods=['PUT'])
@login_required
def api_update_organization(id):
    data = request.json
    name = data.get('name')
    addresses = data.get('addresses', [])
    if not name:
        return jsonify({'success': False, 'error': 'Введите название'}), 400
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE Organizations SET name=? WHERE id=?", (name, id))
        cursor.execute("DELETE FROM OrganizationAddresses WHERE organization_id = ?", (id,))
        for addr in addresses:
            if addr.strip():
                cursor.execute("INSERT INTO OrganizationAddresses (organization_id, address) VALUES (?, ?)",
                               (id, addr.strip()))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/organizations/<int:id>', methods=['DELETE'])
@login_required
def api_delete_organization(id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM Employees WHERE Organization_id = ?", (id,))
        employees_count = cursor.fetchone()[0]
        if employees_count > 0:
            return jsonify({'success': False, 'error': 'Нельзя удалить организацию, в которой есть сотрудники'}), 400
        cursor.execute("DELETE FROM Organizations WHERE id = ?", (id,))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/organizations/search', methods=['POST'])
@login_required
def api_search_organizations():
    data = request.json
    search_term = data.get('search', '')
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, address FROM Organizations 
        WHERE name LIKE ? OR address LIKE ? ORDER BY name
    """, (f'%{search_term}%', f'%{search_term}%'))
    organizations = []
    for row in cursor.fetchall():
        organizations.append({
            'id': row[0],
            'name': row[1],
            'address': row[2] if row[2] else ''
        })
    conn.close()
    return jsonify(organizations)

@app.route('/organizations')
@login_required
def organizations():
    return render_template('organizations.html')

# ========== СОТРУДНИКИ ==========
@app.route('/api/employees', methods=['GET'])
@login_required
def api_get_employees():
    conn = get_db()
    cursor = conn.cursor()
    
    org_id = get_user_organization_id()
    is_admin = session.get('role') == 'admin'
    
    if org_id:
        cursor.execute("""
            SELECT e.id, e.Department_Fullname, 
                   o.id as organization_id, o.name as organization_name,
                   d.id as department_id, d.name as department_name
            FROM Employees e
            LEFT JOIN Organizations o ON e.Organization_id = o.id
            LEFT JOIN Departments d ON e.department_id = d.id
            WHERE e.Organization_id = ?
            ORDER BY e.Department_Fullname
        """, (org_id,))
    elif is_admin:
        cursor.execute("""
            SELECT e.id, e.Department_Fullname, 
                   o.id as organization_id, o.name as organization_name,
                   d.id as department_id, d.name as department_name
            FROM Employees e
            LEFT JOIN Organizations o ON e.Organization_id = o.id
            LEFT JOIN Departments d ON e.department_id = d.id
            ORDER BY e.Department_Fullname
        """)
    else:
        cursor.execute("""
            SELECT e.id, e.Department_Fullname, 
                   o.id as organization_id, o.name as organization_name,
                   d.id as department_id, d.name as department_name
            FROM Employees e
            LEFT JOIN Organizations o ON e.Organization_id = o.id
            LEFT JOIN Departments d ON e.department_id = d.id
            WHERE e.Organization_id IS NULL
            ORDER BY e.Department_Fullname
        """)
    
    employees = []
    for row in cursor.fetchall():
        employees.append({
            'id': row[0],
            'name': row[1],  # <-- ВАЖНО: поле 'name'
            'organization_id': row[2],
            'organization_name': row[3] if row[3] else '—',
            'department_id': row[4],
            'department_name': row[5] if row[5] else '—'
        })
    conn.close()
    return jsonify(employees)

@app.route('/api/employees/list', methods=['GET'])
@login_required
def api_get_employees_list():
    """Возвращает простой список сотрудников для select"""
    conn = get_db()
    cursor = conn.cursor()
    
    org_id = get_user_organization_id()
    is_admin = session.get('role') == 'admin'
    
    if org_id:
        cursor.execute("""
            SELECT Department_Fullname FROM Employees 
            WHERE Organization_id = ?
            ORDER BY Department_Fullname
        """, (org_id,))
    elif is_admin:
        cursor.execute("""
            SELECT Department_Fullname FROM Employees 
            ORDER BY Department_Fullname
        """)
    else:
        cursor.execute("""
            SELECT Department_Fullname FROM Employees 
            WHERE Organization_id IS NULL
            ORDER BY Department_Fullname
        """)
    
    employees = [row[0] for row in cursor.fetchall() if row[0]]
    conn.close()
    return jsonify(employees)

@app.route('/api/employees', methods=['POST'])
@login_required
def api_add_employee():
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    try:
        name = data.get('name', '').strip()
        organization_id = data.get('organization_id')
        department_id = data.get('department_id')
        
        if not name:
            return jsonify({'success': False, 'error': 'Введите имя сотрудника'}), 400
        
        if not organization_id:
            organization_id = get_organization_for_new_record()
        
        cursor.execute("""
            INSERT INTO Employees (Department_Fullname, Organization_id, department_id) 
            VALUES (?, ?, ?)
        """, (name, organization_id, department_id if department_id else None))
        
        conn.commit()
        return jsonify({'success': True, 'id': cursor.lastrowid})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'error': 'Сотрудник уже существует'}), 400
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/employees/<int:id>', methods=['PUT'])
@login_required
def api_update_employee(id):
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    try:
        name = data.get('name', '').strip()
        organization_id = data.get('organization_id')
        department_id = data.get('department_id')
        
        if not name:
            return jsonify({'success': False, 'error': 'Введите имя сотрудника'}), 400
        
        cursor.execute("""
            UPDATE Employees 
            SET Department_Fullname = ?, Organization_id = ?, department_id = ?
            WHERE id = ?
        """, (name, organization_id if organization_id else None, department_id if department_id else None, id))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/employees/quick-add', methods=['POST'])
@login_required
def api_quick_add_employee():
    data = request.json
    name = data.get('name', '').strip()
    organization_id = data.get('organization_id')
    
    if not name:
        return jsonify({'success': False, 'error': 'Введите имя сотрудника'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    try:
        if not organization_id:
            organization_id = get_organization_for_new_record()
        
        cursor.execute("INSERT INTO Employees (Department_Fullname, Organization_id) VALUES (?, ?)", 
                      (name, organization_id))
        conn.commit()
        return jsonify({'success': True, 'id': cursor.lastrowid, 'name': name})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'error': 'Сотрудник уже существует'}), 400
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/employees/<int:id>', methods=['DELETE'])
@login_required
def api_delete_employee(id):
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT Department_Fullname FROM Employees WHERE id = ?", (id,))
        employee = cursor.fetchone()
        if not employee:
            return jsonify({'success': False, 'error': 'Сотрудник не найден'}), 404
        
        employee_name = employee[0]
        
        cursor.execute("UPDATE Catrigs SET Responsible = NULL WHERE Responsible = ?", (id,))
        catrigs_updated = cursor.rowcount
        
        cursor.execute("UPDATE Equipment SET mol_employee = NULL WHERE mol_employee = ?", (id,))
        equipment_mol_updated = cursor.rowcount
        
        cursor.execute("UPDATE Equipment SET responsible_employee = NULL WHERE responsible_employee = ?", (id,))
        equipment_resp_updated = cursor.rowcount
        
        cursor.execute("UPDATE EquipmentMovements SET from_mol = NULL WHERE from_mol = ?", (id,))
        cursor.execute("UPDATE EquipmentMovements SET to_mol = NULL WHERE to_mol = ?", (id,))
        cursor.execute("UPDATE EquipmentMovements SET from_employee = NULL WHERE from_employee = ?", (id,))
        cursor.execute("UPDATE EquipmentMovements SET to_employee = NULL WHERE to_employee = ?", (id,))
        
        cursor.execute("DELETE FROM Employees WHERE id = ?", (id,))
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': f'Сотрудник "{employee_name}" удален',
            'details': {
                'cartridges_updated': catrigs_updated,
                'equipment_mol_updated': equipment_mol_updated,
                'equipment_responsible_updated': equipment_resp_updated
            }
        })
        
    except Exception as e:
        conn.rollback()
        print(f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        conn.close()

# ========== ОТДЕЛЫ ==========
@app.route('/api/departments', methods=['GET'])
@login_required
def api_get_departments():
    conn = get_db()
    cursor = conn.cursor()
    
    org_id = get_user_organization_id()
    is_admin = session.get('role') == 'admin'
    
    if org_id:
        cursor.execute("""
            SELECT d.id, d.name, d.organization_id, o.name as organization_name,
                   GROUP_CONCAT(do.office, '||') as offices_str
            FROM Departments d
            LEFT JOIN Organizations o ON d.organization_id = o.id
            LEFT JOIN DepartmentOffices do ON d.id = do.department_id
            WHERE d.organization_id = ?
            GROUP BY d.id
            ORDER BY d.name
        """, (org_id,))
    elif is_admin:
        cursor.execute("""
            SELECT d.id, d.name, d.organization_id, o.name as organization_name,
                   GROUP_CONCAT(do.office, '||') as offices_str
            FROM Departments d
            LEFT JOIN Organizations o ON d.organization_id = o.id
            LEFT JOIN DepartmentOffices do ON d.id = do.department_id
            GROUP BY d.id
            ORDER BY d.name
        """)
    else:
        cursor.execute("""
            SELECT d.id, d.name, d.organization_id, o.name as organization_name,
                   GROUP_CONCAT(do.office, '||') as offices_str
            FROM Departments d
            LEFT JOIN Organizations o ON d.organization_id = o.id
            LEFT JOIN DepartmentOffices do ON d.id = do.department_id
            WHERE d.organization_id IS NULL
            GROUP BY d.id
            ORDER BY d.name
        """)
    
    departments = []
    for row in cursor.fetchall():
        offices = row[4].split('||') if row[4] else []
        departments.append({
            'id': row[0],
            'name': row[1],
            'organization_id': row[2],
            'organization_name': row[3] if row[3] else '—',
            'offices': offices
        })
    conn.close()
    return jsonify(departments)

@app.route('/api/departments', methods=['POST'])
@login_required
def api_add_department():
    data = request.json
    name = data.get('name', '').strip()
    organization_id = data.get('organization_id')
    offices = data.get('offices', [])
    
    if not name:
        return jsonify({'success': False, 'error': 'Введите название отдела'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    try:
        if not organization_id:
            organization_id = get_organization_for_new_record()
        
        cursor.execute("""
            INSERT INTO Departments (name, organization_id)
            VALUES (?, ?)
        """, (name, organization_id if organization_id else None))
        dept_id = cursor.lastrowid
        
        for office in offices:
            office = office.strip()
            if office:
                cursor.execute("INSERT INTO DepartmentOffices (department_id, office) VALUES (?, ?)",
                               (dept_id, office))
        
        conn.commit()
        return jsonify({'success': True, 'id': dept_id})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/departments/<int:id>', methods=['PUT'])
@login_required
def api_update_department(id):
    data = request.json
    name = data.get('name', '').strip()
    organization_id = data.get('organization_id')
    offices = data.get('offices', [])
    
    if not name:
        return jsonify({'success': False, 'error': 'Введите название отдела'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE Departments 
            SET name = ?, organization_id = ?
            WHERE id = ?
        """, (name, organization_id if organization_id else None, id))
        
        # Удалить старые кабинеты и вставить новые
        cursor.execute("DELETE FROM DepartmentOffices WHERE department_id = ?", (id,))
        for office in offices:
            office = office.strip()
            if office:
                cursor.execute("INSERT INTO DepartmentOffices (department_id, office) VALUES (?, ?)",
                               (id, office))
        
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/departments/<int:id>', methods=['DELETE'])
@login_required
def api_delete_department(id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM Employees WHERE department_id = ?", (id,))
        employees_count = cursor.fetchone()[0]
        if employees_count > 0:
            return jsonify({'success': False, 'error': 'Нельзя удалить отдел, в котором есть сотрудники'}), 400
        
        cursor.execute("DELETE FROM Departments WHERE id = ?", (id,))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/departments/list', methods=['GET'])
@login_required
def api_get_departments_list():
    conn = get_db()
    cursor = conn.cursor()
    
    org_id = get_user_organization_id()
    is_admin = session.get('role') == 'admin'
    
    if org_id:
        cursor.execute("""
            SELECT d.id, d.name, o.name as organization_name
            FROM Departments d
            LEFT JOIN Organizations o ON d.organization_id = o.id
            WHERE d.organization_id = ?
            ORDER BY d.name
        """, (org_id,))
    elif is_admin:
        cursor.execute("""
            SELECT d.id, d.name, o.name as organization_name
            FROM Departments d
            LEFT JOIN Organizations o ON d.organization_id = o.id
            ORDER BY d.name
        """)
    else:
        cursor.execute("""
            SELECT d.id, d.name, o.name as organization_name
            FROM Departments d
            LEFT JOIN Organizations o ON d.organization_id = o.id
            WHERE d.organization_id IS NULL
            ORDER BY d.name
        """)
    
    departments = [{'id': row[0], 'name': row[1], 'organization_name': row[2] or ''} for row in cursor.fetchall()]
    conn.close()
    return jsonify(departments)

# ========== УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ ==========
@app.route('/users')
@admin_required
def users_page():
    return render_template('users.html')

@app.route('/api/users', methods=['GET'])
@admin_required
def get_users():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            u.id, u.username, u.full_name, u.role, u.created_at, u.last_login, u.is_active,
            u.organization_id, o.name as organization_name
        FROM Users u
        LEFT JOIN Organizations o ON u.organization_id = o.id
        ORDER BY CASE WHEN u.role = 'admin' THEN 0 ELSE 1 END, u.username
    """)
    
    users = []
    for row in cursor.fetchall():
        users.append({
            'id': row[0],
            'username': row[1],
            'full_name': row[2] or '',
            'role': row[3],
            'created_at': row[4],
            'last_login': row[5],
            'is_active': row[6],
            'organization_id': row[7],
            'organization_name': row[8] or '—'
        })
    
    conn.close()
    return jsonify(users)

@app.route('/api/users', methods=['POST'])
@admin_required
def add_user():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '')
    full_name = data.get('full_name', '').strip()
    role = data.get('role', 'user')
    organization_id = data.get('organization_id')
    
    if not username:
        return jsonify({'error': 'Введите логин'}), 400
    if not password:
        return jsonify({'error': 'Введите пароль'}), 400
    if len(password) < 4:
        return jsonify({'error': 'Пароль должен содержать минимум 4 символа'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO Users (username, password_hash, full_name, role, organization_id, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
        """, (username, hash_password(password), full_name, role, organization_id if organization_id else None))
        conn.commit()
        return jsonify({'success': True, 'id': cursor.lastrowid})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Пользователь с таким логином уже существует'}), 400
    finally:
        conn.close()

@app.route('/api/users/<int:id>', methods=['PUT'])
@admin_required
def update_user(id):
    data = request.json
    
    if id == session.get('user_id'):
        return jsonify({'error': 'Нельзя редактировать свою учетную запись через эту форму'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE Users 
            SET full_name = ?, role = ?, is_active = ?, organization_id = ?
            WHERE id = ?
        """, (data.get('full_name', ''), data.get('role', 'user'), 
              data.get('is_active', 1), data.get('organization_id'), id))
        
        new_password = data.get('password', '')
        if new_password and len(new_password) >= 4:
            cursor.execute("UPDATE Users SET password_hash = ? WHERE id = ?", (hash_password(new_password), id))
        
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/users/<int:id>', methods=['DELETE'])
@admin_required
def delete_user(id):
    if id == session.get('user_id'):
        return jsonify({'error': 'Нельзя удалить свою учетную запись'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT role FROM Users WHERE id = ?", (id,))
    user_role = cursor.fetchone()
    
    if user_role and user_role[0] == 'admin':
        cursor.execute("SELECT COUNT(*) FROM Users WHERE role = 'admin' AND is_active = 1")
        admin_count = cursor.fetchone()[0]
        if admin_count <= 1:
            conn.close()
            return jsonify({'error': 'Нельзя удалить последнего администратора'}), 400
    
    try:
        cursor.execute("DELETE FROM Users WHERE id = ?", (id,))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/users/change-password', methods=['POST'])
@login_required
def change_own_password():
    data = request.json
    old_password = data.get('old_password', '')
    new_password = data.get('new_password', '')
    
    if not old_password or not new_password:
        return jsonify({'error': 'Введите старый и новый пароль'}), 400
    
    if len(new_password) < 4:
        return jsonify({'error': 'Новый пароль должен содержать минимум 4 символа'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash FROM Users WHERE id = ?", (session['user_id'],))
    current_hash = cursor.fetchone()
    
    if not current_hash or not verify_password(old_password, current_hash[0]):
        conn.close()
        return jsonify({'error': 'Неверный текущий пароль'}), 401
    
    cursor.execute("UPDATE Users SET password_hash = ? WHERE id = ?", (hash_password(new_password), session['user_id']))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

# ========== УЧЕТ ОБОРУДОВАНИЯ ==========
@app.route('/equipment')
@login_required
def equipment_page():
    conn = get_db()
    cursor = conn.cursor()
    
    org_id = get_user_organization_id()
    is_admin = session.get('role') == 'admin'
    
    if org_id:
        filter_condition = "AND Organization_id = ?"
        filter_params = [org_id]
    elif is_admin:
        filter_condition = ""
        filter_params = []
    else:
        filter_condition = "AND Organization_id IS NULL"
        filter_params = []
    
    cursor.execute(f"""
        SELECT Department_Fullname FROM Employees 
        WHERE 1=1 {filter_condition}
        ORDER BY Department_Fullname
    """, filter_params)
    employees = [row[0] for row in cursor.fetchall()]
    
    cursor.execute("SELECT Number, id FROM Rooms ORDER BY Number")
    rooms = [{'number': row[0], 'id': row[1]} for row in cursor.fetchall()]
    
    cursor.execute("SELECT id, name FROM Organizations ORDER BY name")
    organizations = [{'id': row[0], 'name': row[1]} for row in cursor.fetchall()]
    
    conn.close()
    
    return render_template('equipment.html', 
                         employees=employees,
                         rooms=rooms,
                         organizations=organizations)



@app.route('/api/equipment', methods=['POST'])
@login_required
def add_equipment():
    data = request.json
    print("📦 ПОЛУЧЕННЫЕ ДАННЫЕ:", data)

    conn = get_db()
    cursor = conn.cursor()
    
    try:
        org_id = get_organization_for_new_record()
        is_admin = session.get('role') == 'admin'
        view_org_id = session.get('view_organization_id')
        
        # Проверка уникальности инвентарного номера
        inventory_number = data.get('inventory_number', '').strip() if data.get('inventory_number') else None
        if inventory_number:
            if org_id:
                cursor.execute("SELECT id FROM Equipment WHERE inventory_number = ? AND organization_id = ?", (inventory_number, org_id))
            else:
                cursor.execute("SELECT id FROM Equipment WHERE inventory_number = ? AND organization_id IS NULL", (inventory_number,))
            existing = cursor.fetchone()
            if existing:
                conn.close()
                return jsonify({'success': False, 'error': f'Оборудование с инвентарным номером "{inventory_number}" уже существует в вашем филиале!'}), 400
        
        # Обработка ответственного
        responsible_id = None
        if data.get('responsible'):
            cursor.execute("SELECT id FROM Employees WHERE Department_Fullname = ?", (data.get('responsible'),))
            row = cursor.fetchone()
            if row:
                responsible_id = row[0]
            else:
                cursor.execute("INSERT INTO Employees (Department_Fullname) VALUES (?)", (data.get('responsible'),))
                responsible_id = cursor.lastrowid
        
        # Обработка МОЛ
        mol_id = None
        if data.get('mol'):
            cursor.execute("SELECT id FROM Employees WHERE Department_Fullname = ?", (data.get('mol'),))
            row = cursor.fetchone()
            if row:
                mol_id = row[0]
            else:
                cursor.execute("INSERT INTO Employees (Department_Fullname) VALUES (?)", (data.get('mol'),))
                mol_id = cursor.lastrowid
        
        # Обработка комнаты
        room_id = None
        room_number = data.get('room', '').strip()
        if room_number:
            cursor.execute("SELECT id FROM Rooms WHERE Number = ?", (room_number,))
            row = cursor.fetchone()
            if row:
                room_id = row[0]
            else:
                cursor.execute("INSERT INTO Rooms (Number) VALUES (?)", (room_number,))
                room_id = cursor.lastrowid
        
        current_user_id = session.get('user_id')
        
        # Форматирование дат
        purchase_date = data.get('purchase_date')
        if purchase_date and purchase_date != '':
            if '.' in purchase_date:
                parts = purchase_date.split('.')
                if len(parts) == 3:
                    purchase_date = f"{parts[2]}-{parts[1]}-{parts[0]}"
        else:
            purchase_date = None
        
        warranty_until = data.get('warranty_until')
        if warranty_until and warranty_until != '':
            if '.' in warranty_until:
                parts = warranty_until.split('.')
                if len(parts) == 3:
                    warranty_until = f"{parts[2]}-{parts[1]}-{parts[0]}"
        else:
            warranty_until = None
        
        # Определение филиала для сохранения
        save_org_id = None
        if is_admin and view_org_id and view_org_id != '__ALL__' and view_org_id != '__NONE__':
            save_org_id = view_org_id
        elif org_id:
            save_org_id = org_id
        
        # ===== ВСТАВКА – 61 колонка, 61 значение =====
        cursor.execute("""
        INSERT INTO Equipment (
            type, brand, model, serial_number, inventory_number,
            processor, ram, ram_type, storage, os, os_key,
            monitor_size, resolution, refresh_rate, panel_type, response_time, viewing_angle, ports,
            port_count, speed, network_type, poe, managed, ip_address,
            print_type, print_format, print_speed, color_type, duplex, printer_ports,
            scanner_resolution, scanner_speed,
            duplex_scanner, scan_format,
            phone_number, phone_ip, sip_account, lines, phone_poe,
            ups_power, ups_type, ups_outlets, ups_usb, ups_runtime,
            connection_type, color,
            is_set, set_type, 
            responsible_employee, mol_employee, room_id, organization_id, status,
            purchase_date, warranty_until, price, supplier,
            characteristics, notes,
            created_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
    """, (
        data.get('type'), data.get('brand'), data.get('model'),
        data.get('serial_number'), inventory_number,
        data.get('processor'), data.get('ram'), data.get('ram_type'),
        data.get('storage'), data.get('os'), data.get('os_key'),
        data.get('monitor_size'), data.get('resolution'), data.get('refresh_rate'),
        data.get('panel_type'), data.get('response_time'), data.get('viewing_angle'), data.get('ports'),
        data.get('port_count'), data.get('speed'), data.get('network_type'),
        data.get('poe'), data.get('managed'), data.get('ip_address'),
        data.get('print_type'), data.get('print_format'), data.get('print_speed'),
        data.get('color_type'), data.get('duplex'), data.get('printer_ports'),
        data.get('scanner_resolution'), data.get('scanner_speed'),
        data.get('duplex_scanner'), data.get('scan_format'),
        data.get('phone_number'), data.get('phone_ip'), data.get('sip_account'),
        data.get('lines'), data.get('phone_poe'),
        data.get('ups_power'), data.get('ups_type'), data.get('ups_outlets'),
        data.get('ups_usb'), data.get('ups_runtime'),
        data.get('connection_type'), data.get('color'),
        data.get('is_set', 0), data.get('set_type'),  
        responsible_id, mol_id, room_id, save_org_id,
        data.get('status', 'В работе'),
        purchase_date, warranty_until, data.get('price'),
        data.get('supplier'),
        data.get('characteristics'), data.get('notes'),
        current_user_id
    ))
        
        conn.commit()
        return jsonify({'success': True, 'message': 'Оборудование добавлено', 'id': cursor.lastrowid})
    except Exception as e:
        conn.rollback()
        print(f"❌ ОШИБКА add_equipment: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/equipment/<int:id>', methods=['PUT'])
@login_required
def update_equipment(id):
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        new_inventory = data.get('inventory_number', '').strip() if data.get('inventory_number') else None
        
        org_id = get_user_organization_id()

        if new_inventory:
            if org_id:
                cursor.execute("SELECT id FROM Equipment WHERE inventory_number = ? AND id != ? AND organization_id = ?", (new_inventory, id, org_id))
            else:
                cursor.execute("SELECT id FROM Equipment WHERE inventory_number = ? AND id != ? AND organization_id IS NULL", (new_inventory, id))
            existing = cursor.fetchone()
            if existing:
                conn.close()
                return jsonify({
                    'success': False, 
                    'error': f'Оборудование с инвентарным номером "{new_inventory}" уже существует в вашем филиале!'
                }), 400
                
        responsible_id = None
        if data.get('responsible'):
            cursor.execute("SELECT id FROM Employees WHERE Department_Fullname = ?", (data.get('responsible'),))
            row = cursor.fetchone()
            if row:
                responsible_id = row[0]
            else:
                cursor.execute("INSERT INTO Employees (Department_Fullname) VALUES (?)", (data.get('responsible'),))
                responsible_id = cursor.lastrowid
        
        mol_id = None
        if data.get('mol'):
            cursor.execute("SELECT id FROM Employees WHERE Department_Fullname = ?", (data.get('mol'),))
            row = cursor.fetchone()
            if row:
                mol_id = row[0]
            else:
                cursor.execute("INSERT INTO Employees (Department_Fullname) VALUES (?)", (data.get('mol'),))
                mol_id = cursor.lastrowid
        
        room_id = None
        room_number = data.get('room', '').strip()
        if room_number:
            cursor.execute("SELECT id FROM Rooms WHERE Number = ?", (room_number,))
            row = cursor.fetchone()
            if row:
                room_id = row[0]
            else:
                cursor.execute("INSERT INTO Rooms (Number) VALUES (?)", (room_number,))
                room_id = cursor.lastrowid
        
        organization_id = data.get('organization_id') if data.get('organization_id') else org_id
        current_user_id = session.get('user_id')
        
        purchase_date = data.get('purchase_date')
        if purchase_date and purchase_date != '' and purchase_date != 'null' and purchase_date != 'None':
            if '.' in str(purchase_date):
                parts = str(purchase_date).split('.')
                if len(parts) == 3:
                    purchase_date = f"{parts[2]}-{parts[1]}-{parts[0]}"
        else:
            purchase_date = None
        
        warranty_until = data.get('warranty_until')
        if warranty_until and warranty_until != '' and warranty_until != 'null' and warranty_until != 'None':
            if '.' in str(warranty_until):
                parts = str(warranty_until).split('.')
                if len(parts) == 3:
                    warranty_until = f"{parts[2]}-{parts[1]}-{parts[0]}"
        else:
            warranty_until = None
        
        # UPDATE
        cursor.execute("""
        UPDATE Equipment SET
            type=?, brand=?, model=?, serial_number=?, inventory_number=?,
            processor=?, ram=?, ram_type=?, storage=?, os=?, os_key=?,
            monitor_size=?, resolution=?, refresh_rate=?, panel_type=?, response_time=?, viewing_angle=?, ports=?,
            port_count=?, speed=?, network_type=?, poe=?, managed=?, ip_address=?,
            print_type=?, print_format=?, print_speed=?, color_type=?, duplex=?, printer_ports=?,
            scanner_resolution=?, scanner_speed=?,
            duplex_scanner=?, scan_format=?,  
            phone_number=?, phone_ip=?, sip_account=?, lines=?, phone_poe=?,
            ups_power=?, ups_type=?, ups_outlets=?, ups_usb=?, ups_runtime=?,
            connection_type=?, color=?,
            is_set=?, set_type=?,
            responsible_employee=?, mol_employee=?, room_id=?, organization_id=?, status=?,
            purchase_date=?, warranty_until=?, price=?, supplier=?,
            characteristics=?, notes=?,
            updated_by=?, updated_at=datetime('now')
        WHERE id=?
    """, (
        data.get('type'), data.get('brand'), data.get('model'),
        data.get('serial_number'), new_inventory,
        data.get('processor'), data.get('ram'), data.get('ram_type'),
        data.get('storage'), data.get('os'), data.get('os_key'),
        data.get('monitor_size'), data.get('resolution'), data.get('refresh_rate'),
        data.get('panel_type'), data.get('response_time'), data.get('viewing_angle'), data.get('ports'),
        data.get('port_count'), data.get('speed'), data.get('network_type'),
        data.get('poe'), data.get('managed'), data.get('ip_address'),
        data.get('print_type'), data.get('print_format'), data.get('print_speed'),
        data.get('color_type'), data.get('duplex'), data.get('printer_ports'),
        data.get('scanner_resolution'), data.get('scanner_speed'),
        data.get('duplex_scanner'), data.get('scan_format'),
        data.get('phone_number'), data.get('phone_ip'), data.get('sip_account'),
        data.get('lines'), data.get('phone_poe'),
        data.get('ups_power'), data.get('ups_type'), data.get('ups_outlets'),
        data.get('ups_usb'), data.get('ups_runtime'),
        data.get('connection_type'), data.get('color'),
        data.get('is_set', 0), data.get('set_type'), 
        responsible_id, mol_id, room_id, organization_id,
        data.get('status', 'В работе'),
        purchase_date, warranty_until, data.get('price'),
        data.get('supplier'),
        data.get('characteristics'), data.get('notes'),
        current_user_id, id
    ))
        
        conn.commit()
        return jsonify({'success': True, 'message': 'Оборудование обновлено'})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/equipment/import-excel', methods=['POST'])
@login_required
def import_equipment_excel():
    import json
    import traceback
    import math
    import re

    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'Файл не выбран'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'Файл не выбран'}), 400

    if not file.filename.endswith(('.xlsx', '.xls')):
        return jsonify({'success': False, 'error': 'Поддерживаются только файлы Excel (.xlsx, .xls)'}), 400

    sheets_json = request.form.get('sheets')
    try:
        selected_sheets = json.loads(sheets_json) if sheets_json else []
    except json.JSONDecodeError:
        selected_sheets = []

    try:
        df_dict = pd.read_excel(file, sheet_name=None)
    except Exception as e:
        return jsonify({'success': False, 'error': f'Ошибка чтения Excel: {str(e)}'}), 400

    conn = get_db()
    cursor = conn.cursor()
    added = 0
    updated = 0
    skipped = 0
    errors = []
    skipped_reasons = {}

    org_id = get_organization_for_new_record()
    print(f"[ИМПОРТ] Филиал пользователя (org_id): {org_id}")

    if org_id is None:
        print("[ИМПОРТ] ВНИМАНИЕ: у пользователя нет филиала. Сотрудники, отделы и оборудование будут созданы без филиала (NULL).")

    col_mapping = {
        'inventory': ['инвентарный номер', 'инв. номер', 'инвентарный'],
        'model': ['модель', 'model'],
        'serial': ['серийный номер', 'серийный', 's/n', 'sn'],
        'room': ['кабинет', 'местонахождение', 'кабинет (местонахождение)'],
        'responsible': ['ответственный сотрудник', 'ответственный', 'сотрудник', 'пользователь'],
        'department': ['отдел', 'подразделение'],
        'status': ['текущее состояние', 'состояние', 'статус'],
        'notes': ['примечания', 'примечание', 'дефекты'],
        'type': ['наименование оборудования', 'тип оборудования'],
        'model_bgu': ['наименование оборудования'],
        'tech_spec': ['технические характеристики', 'характеристики'],
        'mol': ['материально-ответственное лицо', 'мол', 'материально ответственное', 'м.о.л.', 'мол (материально-ответственное лицо)']
    }

    def find_column(df_columns, keywords):
        for col in df_columns:
            col_lower = col.lower().strip()
            for kw in keywords:
                if kw in col_lower:
                    return col
        return None

    if selected_sheets:
        sheets_to_process = {name: df_dict.get(name) for name in selected_sheets if name in df_dict}
    else:
        sheets_to_process = {name: df for name, df in df_dict.items() if not df.empty}

    if not sheets_to_process:
        return jsonify({'success': False, 'error': 'Не выбрано ни одного листа для импорта'}), 400

    for sheet_name, sheet_df in sheets_to_process.items():
        if sheet_df.empty:
            errors.append(f"Лист '{sheet_name}' пуст")
            continue

        cols = sheet_df.columns.tolist()
        print(f"\n[ИМПОРТ] Лист: {sheet_name}")
        print(f"[ИМПОРТ] Все колонки: {cols}")

        col_inventory = find_column(cols, col_mapping['inventory'])
        col_department = find_column(cols, col_mapping['department'])
        col_room = find_column(cols, col_mapping['room'])
        col_responsible = find_column(cols, col_mapping['responsible'])
        col_mol = find_column(cols, col_mapping['mol'])
        col_model_bgu = find_column(cols, col_mapping['model_bgu'])
        col_model = find_column(cols, col_mapping['model'])
        col_serial = find_column(cols, col_mapping['serial'])
        col_status = find_column(cols, col_mapping['status'])
        col_notes = find_column(cols, col_mapping['notes'])
        col_type = find_column(cols, col_mapping['type'])
        col_tech_spec = find_column(cols, col_mapping['tech_spec'])

        print(f"[ИМПОРТ] Найдены колонки:")
        print(f"  Инвентарный номер: {col_inventory}")
        print(f"  Отдел: {col_department}")
        print(f"  Кабинет: {col_room}")
        print(f"  Ответственный: {col_responsible}")
        print(f"  МОЛ: {col_mol}")
        print(f"  Тип: {col_type}")

        if not col_type:
            error_msg = f"Лист '{sheet_name}': НЕ НАЙДЕНА колонка 'Наименование оборудования'! Переименуйте колонку в Excel."
            errors.append(error_msg)
            print(f"[ИМПОРТ] ОШИБКА: {error_msg}")
            continue

        total_rows = len(sheet_df)
        print(f"[ИМПОРТ] Всего строк в листе '{sheet_name}': {total_rows}")

        processed = 0
        for idx, row in sheet_df.iterrows():
            try:
                # 1. Инвентарный номер
                inventory = None
                if col_inventory and pd.notna(row[col_inventory]):
                    inv_raw = row[col_inventory]
                    if isinstance(inv_raw, float) and not math.isnan(inv_raw):
                        if inv_raw.is_integer():
                            inventory = str(int(inv_raw))
                        else:
                            inventory = str(inv_raw)
                    else:
                        inv_str = str(inv_raw).strip()
                        if inv_str not in ('', 'nan', 'none', 'null', '—', '-', '_'):
                            inventory = inv_str

                # 2. Отдел (регистронезависимый поиск)
                department_name = ''
                if col_department and pd.notna(row[col_department]):
                    department_name = str(row[col_department]).strip()

                department_id = None
                if department_name:
                    dept_name_norm = department_name.strip()
                    if org_id is not None:
                        cursor.execute(
                            "SELECT id FROM Departments WHERE LOWER(name) = LOWER(?) AND organization_id = ?",
                            (dept_name_norm, org_id)
                        )
                    else:
                        cursor.execute(
                            "SELECT id FROM Departments WHERE LOWER(name) = LOWER(?) AND organization_id IS NULL",
                            (dept_name_norm,)
                        )
                    dept = cursor.fetchone()
                    if dept:
                        department_id = dept[0]
                        print(f"[ИМПОРТ] Строка {idx+2}: найден существующий отдел '{dept_name_norm}' (id={department_id})")
                    else:
                        cursor.execute(
                            "INSERT INTO Departments (name, organization_id) VALUES (?, ?)",
                            (dept_name_norm, org_id)
                        )
                        department_id = cursor.lastrowid
                        print(f"[ИМПОРТ] Строка {idx+2}: создан новый отдел '{dept_name_norm}' (id={department_id})")
                        conn.commit()

                # 3. Кабинет
                room_number = ''
                if col_room and pd.notna(row[col_room]):
                    room_raw = row[col_room]
                    if isinstance(room_raw, float):
                        try:
                            room_number = str(int(room_raw))
                        except:
                            room_number = str(room_raw)
                    else:
                        room_number = str(room_raw).strip()

                room_id = None
                if room_number:
                    cursor.execute("SELECT id, department_id FROM Rooms WHERE Number = ?", (room_number,))
                    room = cursor.fetchone()
                    if room:
                        room_id = room[0]
                        if room[1] != department_id:
                            cursor.execute("UPDATE Rooms SET department_id = ? WHERE id = ?", (department_id, room_id))
                            conn.commit()
                    else:
                        cursor.execute(
                            "INSERT INTO Rooms (Number, department_id) VALUES (?, ?)",
                            (room_number, department_id)
                        )
                        room_id = cursor.lastrowid
                        print(f"[ИМПОРТ] Строка {idx+2}: создан кабинет '{room_number}' (id={room_id})")
                        conn.commit()

                    # ОБНОВЛЯЕМ ПОЛЕ office В ТАБЛИЦЕ Departments (для обратной совместимости)
                    if department_id and room_number:
                        cursor.execute(
                            "UPDATE Departments SET office = ? WHERE id = ? AND (office IS NULL OR office != ?)",
                            (room_number, department_id, room_number)
                        )
                        if cursor.rowcount > 0:
                            print(f"[ИМПОРТ] Строка {idx+2}: обновлён office у отдела '{department_name}' -> '{room_number}'")
                            conn.commit()

                    # ===== НОВАЯ ЛОГИКА: ДОБАВЛЯЕМ СВЯЗЬ В DepartmentOffices =====
                    if department_id and room_id:
                        cursor.execute(
                            "SELECT id FROM DepartmentOffices WHERE department_id = ? AND office = ?",
                            (department_id, room_number)
                        )
                        if not cursor.fetchone():
                            cursor.execute(
                                "INSERT INTO DepartmentOffices (department_id, office) VALUES (?, ?)",
                                (department_id, room_number)
                            )
                            print(f"[ИМПОРТ] Строка {idx+2}: добавлена связь отдела {department_name} с кабинетом {room_number}")
                            conn.commit()

                # 4. Ответственный сотрудник
                responsible_name = ''
                if col_responsible and pd.notna(row[col_responsible]):
                    responsible_name = str(row[col_responsible]).strip()

                responsible_id = None
                if responsible_name:
                    cursor.execute("SELECT id FROM Employees WHERE Department_Fullname = ?", (responsible_name,))
                    emp = cursor.fetchone()
                    if emp:
                        responsible_id = emp[0]
                    else:
                        cursor.execute(
                            "INSERT INTO Employees (Department_Fullname, Organization_id) VALUES (?, ?)",
                            (responsible_name, org_id)
                        )
                        responsible_id = cursor.lastrowid
                        conn.commit()

                # 5. МОЛ
                mol_name = ''
                if col_mol and pd.notna(row[col_mol]):
                    mol_name = str(row[col_mol]).strip()

                mol_id = None
                if mol_name:
                    cursor.execute("SELECT id FROM Employees WHERE Department_Fullname = ?", (mol_name,))
                    emp = cursor.fetchone()
                    if emp:
                        mol_id = emp[0]
                    else:
                        cursor.execute(
                            "INSERT INTO Employees (Department_Fullname, Organization_id) VALUES (?, ?)",
                            (mol_name, org_id)
                        )
                        mol_id = cursor.lastrowid
                        conn.commit()

                # 6. Тип оборудования
                equipment_type = 'Другое'
                type_raw = ''
                if col_type and pd.notna(row[col_type]):
                    type_raw = str(row[col_type]).strip()
                elif col_model_bgu and pd.notna(row[col_model_bgu]):
                    type_raw = str(row[col_model_bgu]).strip()

                if type_raw:
                    type_clean = re.sub(r'\s+', ' ', type_raw).strip()
                    type_lower = type_clean.lower()
                    computer_keywords = ['системный', 'системник', 'компьютер', 'пк', 'pc']
                    if any(keyword in type_lower for keyword in computer_keywords):
                        equipment_type = 'Компьютер'
                    else:
                        type_mapping = {
                            'ноутбук': 'Ноутбук', 'лэптоп': 'Ноутбук', 'laptop': 'Ноутбук',
                            'моноблок': 'Моноблок', 'all-in-one': 'Моноблок',
                            'монитор': 'Монитор', 'дисплей': 'Монитор', 'monitor': 'Монитор',
                            'принтер': 'Принтер', 'printer': 'Принтер',
                            'мфу': 'МФУ',
                            'сканер': 'Сканер', 'scanner': 'Сканер',
                            'сетевое оборудование': 'Сетевое оборудование',
                            'коммутатор': 'Сетевое оборудование',
                            'маршрутизатор': 'Сетевое оборудование',
                            'роутер': 'Сетевое оборудование',
                            'switch': 'Сетевое оборудование',
                            'router': 'Сетевое оборудование',
                            'ибп': 'ИБП', 'бесперебойник': 'ИБП', 'ups': 'ИБП',
                            'мышь': 'Мышь/Клавиатура', 'клавиатура': 'Мышь/Клавиатура',
                            'мышь/клавиатура': 'Мышь/Клавиатура',
                            'mouse': 'Мышь/Клавиатура', 'keyboard': 'Мышь/Клавиатура',
                            'внешний диск': 'Внешний диск', 'external drive': 'Внешний диск',
                            'колонки': 'Колонки', 'speakers': 'Колонки',
                            'веб-камера': 'Веб-камера/Гарнитура/Микрофон',
                            'камера': 'Веб-камера/Гарнитура/Микрофон',
                            'гарнитура': 'Веб-камера/Гарнитура/Микрофон',
                            'микрофон': 'Веб-камера/Гарнитура/Микрофон',
                            'webcam': 'Веб-камера/Гарнитура/Микрофон',
                            'headset': 'Веб-камера/Гарнитура/Микрофон',
                        }
                        found = False
                        for key, value in type_mapping.items():
                            if key in type_lower:
                                equipment_type = value
                                found = True
                                break
                        if not found:
                            equipment_type = type_clean.title()

                # 7. Остальные поля
                brand_value = ''
                if col_model and pd.notna(row[col_model]):
                    brand_value = str(row[col_model]).strip()
                if not brand_value and col_model_bgu and pd.notna(row[col_model_bgu]):
                    brand_value = str(row[col_model_bgu]).strip()
                if not brand_value and col_tech_spec and pd.notna(row[col_tech_spec]):
                    brand_value = str(row[col_tech_spec]).strip()

                characteristics = ''
                if col_tech_spec and pd.notna(row[col_tech_spec]):
                    characteristics = str(row[col_tech_spec]).strip()

                serial = ''
                if col_serial and pd.notna(row[col_serial]):
                    serial = str(row[col_serial]).strip()

                status_raw = ''
                if col_status and pd.notna(row[col_status]):
                    status_raw = str(row[col_status]).strip()
                status = 'В работе' if not status_raw else (
                    'Простаивает' if 'простаивает' in status_raw.lower() else
                    'Ремонт' if 'ремонт' in status_raw.lower() else
                    'Списано' if 'списано' in status_raw.lower() else
                    'На складе' if 'резерв' in status_raw.lower() else 'В работе'
                )

                notes = ''
                if col_notes and pd.notna(row[col_notes]):
                    notes = str(row[col_notes]).strip()

                # 8. Оборудование – вставка/обновление
                if inventory is None:
                    # Вставка без инвентарного номера
                    cursor.execute("""
                        INSERT INTO Equipment (
                            type, brand, model, serial_number, inventory_number,
                            room_id, responsible_employee, mol_employee,
                            status, notes, characteristics,
                            organization_id, created_at, created_by
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)
                    """, (equipment_type, brand_value, '', serial, None,
                          room_id, responsible_id, mol_id, status, notes, characteristics,
                          org_id, session.get('user_id'))
                    )
                    added += 1
                    print(f"[ИМПОРТ] Строка {idx+2}: добавлена запись без инвентарного номера")
                else:
                    # Поиск существующей записи с учётом филиала
                    if org_id is not None:
                        cursor.execute(
                            "SELECT id FROM Equipment WHERE inventory_number = ? AND organization_id = ?",
                            (inventory, org_id)
                        )
                    else:
                        cursor.execute(
                            "SELECT id FROM Equipment WHERE inventory_number = ? AND organization_id IS NULL",
                            (inventory,)
                        )
                    existing = cursor.fetchone()
                    if existing:
                        # Обновление
                        cursor.execute("""
                            UPDATE Equipment SET
                                type = ?, brand = ?, model = '',
                                serial_number = ?, room_id = ?,
                                responsible_employee = ?, mol_employee = ?,
                                status = ?, notes = ?, characteristics = ?,
                                organization_id = ?, updated_at = datetime('now'), updated_by = ?
                            WHERE id = ?
                        """, (equipment_type, brand_value, serial, room_id,
                              responsible_id, mol_id, status, notes, characteristics,
                              org_id, session.get('user_id'), existing[0]))
                        updated += 1
                        print(f"[ИМПОРТ] Строка {idx+2}: обновлена запись с инвентарным номером {inventory} (id={existing[0]})")
                    else:
                        # Вставка с инвентарным номером
                        cursor.execute("""
                            INSERT INTO Equipment (
                                type, brand, model, serial_number, inventory_number,
                                room_id, responsible_employee, mol_employee,
                                status, notes, characteristics,
                                organization_id, created_at, created_by
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)
                        """, (equipment_type, brand_value, '', serial, inventory,
                              room_id, responsible_id, mol_id, status, notes, characteristics,
                              org_id, session.get('user_id'))
                        )
                        added += 1
                        print(f"[ИМПОРТ] Строка {idx+2}: добавлена новая запись с инвентарным номером {inventory}")

                conn.commit()
                processed += 1

            except Exception as e:
                errors.append(f"Строка {idx+2} (лист {sheet_name}): {str(e)}")
                skipped += 1
                print(f"[ИМПОРТ] ОШИБКА в строке {idx+2}: {str(e)}")

        print(f"[ИМПОРТ] Лист '{sheet_name}': обработано {processed} строк из {total_rows}")

    conn.close()

    # Формируем отчёт
    skip_details = ""
    if skipped_reasons:
        skip_details = "\n\nПричины пропуска:\n" + "\n".join([f"  - {k}: {v} раз" for k, v in list(skipped_reasons.items())[:10]])

    result_message = f"✅ Импорт завершён: добавлено {added}, обновлено {updated}, пропущено {skipped}{skip_details}"
    if errors:
        result_message += f"\n⚠️ Ошибки: {len(errors)}\n" + "\n".join(errors[:10])

    return jsonify({
        'success': True,
        'added': added,
        'updated': updated,
        'skipped': skipped,
        'message': result_message,
        'errors': errors[:20],
        'details': {
            'total_added': added,
            'total_updated': updated,
            'total_skipped': skipped
        }
    })

@app.route('/api/equipment/import-excel/sheets', methods=['POST'])
@login_required
def get_excel_sheets():
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'Файл не выбран'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'Файл не выбран'}), 400
    
    if not file.filename.endswith(('.xlsx', '.xls')):
        return jsonify({'success': False, 'error': 'Поддерживаются только файлы Excel (.xlsx, .xls)'}), 400
    
    try:
        # Читаем только имена листов без полной загрузки данных
        xl = pd.ExcelFile(file)
        sheets = xl.sheet_names
        return jsonify({'success': True, 'sheets': sheets})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/api/equipment/<int:id>', methods=['DELETE'])
@login_required
def delete_equipment(id):
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT COUNT(*) FROM EquipmentMovements WHERE equipment_id = ?", (id,))
        movements_count = cursor.fetchone()[0]
        
        if movements_count > 0:
            return jsonify({'success': False, 'error': 'Нельзя удалить оборудование с историей перемещений.'}), 400
        
        cursor.execute("DELETE FROM Equipment WHERE id = ?", (id,))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/api/equipment/<int:id>/movements', methods=['GET'])
@login_required
def get_equipment_movements(id):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            em.id, em.movement_date,
            COALESCE(from_mol.Department_Fullname, '—') as from_mol,
            COALESCE(to_mol.Department_Fullname, '—') as to_mol,
            COALESCE(from_emp.Department_Fullname, '—') as from_employee,
            COALESCE(to_emp.Department_Fullname, '—') as to_employee,
            COALESCE(from_room.Number, '—') as from_room,
            COALESCE(to_room.Number, '—') as to_room,
            COALESCE(from_org.name, '—') as from_organization,
            COALESCE(to_org.name, '—') as to_organization,
            em.reason, em.comment,
            u.username as created_by,
            e.type || ' ' || e.brand || ' ' || e.model as equipment_name
        FROM EquipmentMovements em
        LEFT JOIN Employees from_mol ON em.from_mol = from_mol.id
        LEFT JOIN Employees to_mol ON em.to_mol = to_mol.id
        LEFT JOIN Employees from_emp ON em.from_employee = from_emp.id
        LEFT JOIN Employees to_emp ON em.to_employee = to_emp.id
        LEFT JOIN Rooms from_room ON em.from_room = from_room.id
        LEFT JOIN Rooms to_room ON em.to_room = to_room.id
        LEFT JOIN Organizations from_org ON em.from_organization = from_org.id
        LEFT JOIN Organizations to_org ON em.to_organization = to_org.id
        LEFT JOIN Users u ON em.created_by = u.id
        LEFT JOIN Equipment e ON em.equipment_id = e.id
        WHERE em.equipment_id = ?
        ORDER BY em.movement_date DESC
    """, (id,))
    
    movements = []
    for row in cursor.fetchall():
        movements.append({
            'id': row[0],
            'movement_date': row[1],
            'from_mol': row[2],
            'to_mol': row[3],
            'from_employee': row[4],
            'to_employee': row[5],
            'from_room': row[6],
            'to_room': row[7],
            'from_organization': row[8],
            'to_organization': row[9],
            'reason': row[10] or '',
            'comment': row[11] or '',
            'created_by': row[12] or '',
            'equipment_name': row[13] or f'Оборудование #{id}'
        })
    
    conn.close()
    return jsonify(movements)

@app.route('/api/equipment/<int:id>/movements', methods=['POST'])
@login_required
def add_equipment_movement(id):
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT responsible_employee, room_id, organization_id, status, mol_employee
            FROM Equipment WHERE id = ?
        """, (id,))
        current = cursor.fetchone()
        
        if not current:
            return jsonify({'success': False, 'error': 'Оборудование не найдено'}), 404
        
        from_employee = current[0]
        from_room = current[1]
        from_organization = current[2]
        old_status = current[3]
        from_mol = current[4]
        
        to_mol = None
        if data.get('to_mol'):
            cursor.execute("SELECT id FROM Employees WHERE Department_Fullname = ?", (data.get('to_mol'),))
            row = cursor.fetchone()
            if row:
                to_mol = row[0]
        
        to_employee = None
        if data.get('to_employee'):
            cursor.execute("SELECT id FROM Employees WHERE Department_Fullname = ?", (data.get('to_employee'),))
            row = cursor.fetchone()
            if row:
                to_employee = row[0]
        
        to_room = None
        if data.get('to_room'):
            cursor.execute("SELECT id FROM Rooms WHERE Number = ?", (data.get('to_room'),))
            row = cursor.fetchone()
            if row:
                to_room = row[0]
        
        to_organization = data.get('to_organization') if data.get('to_organization') else None
        
        new_status = data.get('new_status')
        reason = data.get('reason', '')
        
        if reason == 'Ремонт' and (not new_status or new_status == ''):
            new_status = 'Ремонт'
        elif reason == 'Списание' and (not new_status or new_status == ''):
            new_status = 'Списано'
        elif not new_status or new_status == '':
            new_status = old_status
        
        current_user_id = session.get('user_id')
        comment = data.get('comment', '')
        movement_date = data.get('movement_date', datetime.now().date().isoformat())
        
        cursor.execute("""
            INSERT INTO EquipmentMovements (
                equipment_id, from_employee, to_employee, from_room, to_room,
                from_organization, to_organization, reason, comment, created_by, movement_date,
                from_mol, to_mol
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (id, from_employee, to_employee, from_room, to_room,
              from_organization, to_organization, reason, comment, current_user_id, movement_date,
              from_mol, to_mol))
        
        cursor.execute("""
            UPDATE Equipment 
            SET responsible_employee=?, room_id=?, organization_id=?, status=?,
                mol_employee=?, updated_at=datetime('now'), updated_by=?
            WHERE id=?
        """, (to_employee if to_employee is not None else from_employee, 
              to_room if to_room is not None else from_room, 
              to_organization if to_organization is not None else from_organization, 
              new_status,
              to_mol if to_mol is not None else from_mol,
              current_user_id, id))
        
        conn.commit()
        return jsonify({'success': True, 'message': 'Перемещение записано'})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        conn.close()

@app.route('/api/equipment/movements/all', methods=['GET'])
@login_required
def get_all_movements():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            em.id, em.movement_date,
            COALESCE(from_mol.Department_Fullname, '—') as from_mol,
            COALESCE(to_mol.Department_Fullname, '—') as to_mol,
            COALESCE(from_emp.Department_Fullname, '—') as from_employee,
            COALESCE(to_emp.Department_Fullname, '—') as to_employee,
            COALESCE(from_room.Number, '—') as from_room,
            COALESCE(to_room.Number, '—') as to_room,
            COALESCE(from_org.name, '—') as from_organization,
            COALESCE(to_org.name, '—') as to_organization,
            em.reason,
            u.username as created_by
        FROM EquipmentMovements em
        LEFT JOIN Equipment e ON em.equipment_id = e.id
        LEFT JOIN Employees from_mol ON em.from_mol = from_mol.id
        LEFT JOIN Employees to_mol ON em.to_mol = to_mol.id
        LEFT JOIN Employees from_emp ON em.from_employee = from_emp.id
        LEFT JOIN Employees to_emp ON em.to_employee = to_emp.id
        LEFT JOIN Rooms from_room ON em.from_room = from_room.id
        LEFT JOIN Rooms to_room ON em.to_room = to_room.id
        LEFT JOIN Organizations from_org ON em.from_organization = from_org.id
        LEFT JOIN Organizations to_org ON em.to_organization = to_org.id
        LEFT JOIN Users u ON em.created_by = u.id
        ORDER BY em.movement_date DESC
        LIMIT 100
    """)
    
    movements = []
    for row in cursor.fetchall():
        movements.append({
            'id': row[0],
            'movement_date': row[1],
            'from_mol': row[2] or '—',
            'to_mol': row[3] or '—',    
            'from_employee': row[4],
            'to_employee': row[5],
            'from_room': row[6],
            'to_room': row[7],
            'from_organization': row[8],
            'to_organization': row[9],
            'reason': row[10] or '—',
            'created_by': row[11] or '—'
        })
    
    conn.close()
    return jsonify(movements)

@app.route('/api/equipment/movements/clear', methods=['DELETE'])
@login_required
def clear_all_movements():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT can_delete_history FROM Users WHERE id = ?", (session['user_id'],))
    user = cursor.fetchone()
    
    if not user or not user[0]:
        return jsonify({'success': False, 'error': 'У вас нет прав на удаление истории перемещений'}), 403
    
    try:
        cursor.execute("DELETE FROM EquipmentMovements")
        conn.commit()
        return jsonify({'success': True, 'message': 'История перемещений очищена'})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        conn.close()



@app.route('/api/peripheral-types', methods=['GET'])
@login_required
def get_peripheral_types():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM PeripheralTypes ORDER BY name")
    types = [row[0] for row in cursor.fetchall()]
    conn.close()
    return jsonify(types)

@app.route('/api/equipment/types-fields', methods=['GET'])
@login_required
def get_equipment_type_fields():
    type_fields = {
        'Компьютер': ['processor', 'ram', 'storage', 'os', 'os_key'],
        'Ноутбук': ['processor', 'ram', 'storage', 'os', 'os_key'],
        'Монитор': ['monitor_size', 'resolution'],
        'Сервер': ['processor', 'ram', 'storage', 'os', 'os_key'],
        'Сетевое оборудование': ['port_count', 'speed'],
        'Принтер': ['speed', 'notes'],
        'МФУ': ['speed', 'notes'],
        'Сканер': ['resolution', 'notes'],
        'IP-телефон': ['port_count', 'notes'],
        'Мышь': ['notes'],
        'Клавиатура': ['notes'],
        'ИБП': ['notes'],
        'Внешний диск': ['storage', 'notes'],
        'Док-станция': ['notes'],
        'Веб-камера': ['resolution', 'notes'],
        'Гарнитура': ['notes'],
        'Колонки': ['notes'],
        'Другое': ['processor', 'ram', 'storage', 'os', 'os_key', 'monitor_size', 'resolution', 'port_count', 'speed']
    }
    return jsonify(type_fields)

@app.route('/api/departments/search', methods=['POST'])
@login_required
def search_departments():
    data = request.json
    search_term = data.get('search', '').strip()
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Ищем по полю office (кабинет) или name (отдел)
    cursor.execute("""
        SELECT id, office, name, organization_id
        FROM Departments
        WHERE office LIKE ? OR name LIKE ?
        ORDER BY office
    """, (f'%{search_term}%', f'%{search_term}%'))
    
    depts = []
    for row in cursor.fetchall():
        depts.append({
            'id': row[0],
            'office': row[1] or '',
            'name': row[2] or '',
            'organization_id': row[3]
        })
    conn.close()
    return jsonify(depts)

@app.route('/api/rooms/search', methods=['POST'])
@login_required
def search_rooms():
    data = request.json
    search_term = data.get('search', '').strip()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.id, r.Number, r.department_id, d.name as department_name
        FROM Rooms r
        LEFT JOIN Departments d ON r.department_id = d.id
        WHERE r.Number LIKE ?
        ORDER BY r.Number
    """, (f'%{search_term}%',))
    rooms = [{'id': row[0], 'number': row[1], 'department_id': row[2], 'department_name': row[3] or ''} for row in cursor.fetchall()]
    conn.close()
    return jsonify(rooms)



# app.py - ИСПРАВЛЕННЫЕ ЗАПРОСЫ

# ========== КАРТРИДЖИ ==========

# auth.py - ДОБАВЬТЕ ЭТУ ФУНКЦИЮ

def get_view_organization_id():
    """
    Получить ID филиала для просмотра (для администратора).
    Возвращает:
    - '__ALL__' - если нужно показать все записи (админ по умолчанию)
    - '__NONE__' - если нужно показать записи без филиала
    - число - ID конкретного филиала
    """
    if 'user_id' not in session:
        return None

    is_admin = session.get('role') == 'admin'

    # Для администратора всегда используем view_organization_id, по умолчанию '__ALL__'
    if is_admin:
        return session.get('view_organization_id', '__ALL__')

    # Для обычного пользователя – его собственный филиал
    return get_user_organization_id()

@app.route('/api/cartridges', methods=['GET'])
@login_required
def get_cartridges():
    conn = get_db()
    cursor = conn.cursor()
    conn.row_factory = sqlite3.Row
    
    # Получаем филиал для просмотра
    view_org_id = get_view_organization_id()
    is_admin = session.get('role') == 'admin'
    
    print(f"DEBUG: get_cartridges - is_admin: {is_admin}, view_org_id: {view_org_id}")
    
    filter_condition = ""
    filter_params = []
    
    # Формируем фильтр в зависимости от выбранного филиала
    if is_admin and view_org_id == '__ALL__':
        # Администратор видит все филиалы
        filter_condition = ""
        filter_params = []
        print(f"DEBUG: Админ - показываем все филиалы")
    elif is_admin and view_org_id == '__NONE__':
        # Администратор видит записи без филиала
        filter_condition = "AND C.organization_id IS NULL"
        filter_params = []
        print(f"DEBUG: Админ - показываем записи без филиала")
    elif view_org_id:
        # Конкретный филиал
        filter_condition = "AND C.organization_id = ?"
        filter_params = [view_org_id]
        print(f"DEBUG: Фильтр по филиалу: {view_org_id}")
    else:
        # Обычный пользователь без филиала или админ без выбора
        filter_condition = "AND C.organization_id IS NULL"
        filter_params = []
        print(f"DEBUG: Показываем записи без филиала")
    
    # Проверяем наличие колонки equipment_id
    cursor.execute("PRAGMA table_info(Catrigs)")
    columns = [col[1] for col in cursor.fetchall()]
    has_equipment_id = 'equipment_id' in columns
    has_organization_id = 'organization_id' in columns
    
    if has_equipment_id:
        cursor.execute(f"""
            SELECT 
                C.id,
                C.Serial_number,
                C.Model,
                COALESCE(E.Department_Fullname, '') as responsible,
                COALESCE(R.Number, '') as room,
                COALESCE(C.Status, '') as status,
                COALESCE(C.Issued, '0') as issued,
                COALESCE(C.Ip, '') as ip,
                C.created_at,
                U.username as created_by_username,
                U.full_name as created_by_fullname,
                EQ.id as equipment_id,
                EQ.status as equipment_status,
                EQ.brand as equipment_brand,
                EQ.model as equipment_model,
                EQ.inventory_number as equipment_inventory,
                EQ.type as equipment_type,
                C.organization_id
            FROM Catrigs C
            LEFT JOIN Employees E ON C.Responsible = E.id
            LEFT JOIN Rooms R ON C.Room_id = R.id
            LEFT JOIN Equipment EQ ON C.equipment_id = EQ.id
            LEFT JOIN Users U ON C.created_by = U.id
            WHERE 1=1 {filter_condition}
            ORDER BY C.id DESC
        """, filter_params)
    else:
        cursor.execute(f"""
            SELECT 
                C.id,
                C.Serial_number,
                C.Model,
                COALESCE(E.Department_Fullname, '') as responsible,
                COALESCE(R.Number, '') as room,
                COALESCE(C.Status, '') as status,
                COALESCE(C.Issued, '0') as issued,
                COALESCE(C.Ip, '') as ip,
                C.created_at,
                U.username as created_by_username,
                U.full_name as created_by_fullname,
                C.organization_id
            FROM Catrigs C
            LEFT JOIN Employees E ON C.Responsible = E.id
            LEFT JOIN Rooms R ON C.Room_id = R.id
            LEFT JOIN Users U ON C.created_by = U.id
            WHERE 1=1 {filter_condition}
            ORDER BY C.id DESC
        """, filter_params)
    
    cartridges = []
    for row in cursor.fetchall():
        if has_equipment_id:
            mfu_name = ''
            mfu_status = ''
            mfu_inventory = ''
            equipment_id = row['equipment_id'] if 'equipment_id' in row.keys() else None
            
            if equipment_id:
                brand = row['equipment_brand'] or ''
                model = row['equipment_model'] or ''
                if brand and model:
                    mfu_name = f"{brand} {model}".strip()
                elif brand:
                    mfu_name = brand
                elif model:
                    mfu_name = model
                else:
                    mfu_name = "МФУ"
                
                mfu_status = row['equipment_status'] or '—'
                mfu_inventory = row['equipment_inventory'] or ''
            
            created_by = row['created_by_username'] or row['created_by_fullname'] or ''
            
            cartridges.append({
                'id': row['id'],
                'serial_number': row['Serial_number'] or '',
                'model': row['Model'] or '',
                'responsible': row['responsible'] or '',
                'room': row['room'] or '',
                'status': row['status'] or '—',
                'mfu_status': mfu_status or '—',
                'mfu_name': mfu_name or '—',
                'mfu_inventory': mfu_inventory or '',
                'issued': row['issued'] or '0',
                'ip': row['ip'] or '',
                'created_at': row['created_at'],
                'created_by': created_by,
                'organization_id': row['organization_id'] if 'organization_id' in row.keys() else None
            })
        else:
            created_by = row['created_by_username'] or row['created_by_fullname'] or ''
            cartridges.append({
                'id': row['id'],
                'serial_number': row['Serial_number'] or '',
                'model': row['Model'] or '',
                'responsible': row['responsible'] or '',
                'room': row['room'] or '',
                'status': row['status'] or '—',
                'mfu_status': '—',
                'mfu_name': '—',
                'mfu_inventory': '',
                'issued': row['issued'] or '0',
                'ip': row['ip'] or '',
                'created_at': row['created_at'],
                'created_by': created_by,
                'organization_id': row['organization_id'] if 'organization_id' in row.keys() else None
            })
    
    conn.close()
    print(f"DEBUG: Загружено картриджей: {len(cartridges)}")
    return jsonify(cartridges)


# ========== ПОИСК КАРТРИДЖЕЙ ПО IP ==========

@app.route('/api/cartridges/search/by-ip', methods=['POST'])
@login_required
def search_cartridges_by_ip():
    data = request.json
    ip = data.get('ip', '').strip()
    
    conn = get_db()
    cursor = conn.cursor()
    conn.row_factory = sqlite3.Row
    
    org_id = get_user_organization_id()
    is_admin = session.get('role') == 'admin'
    
    filter_condition = ""
    filter_params = []
    
    if org_id:
        filter_condition = "AND C.organization_id = ?"
        filter_params = [org_id]
    elif not is_admin:
        filter_condition = "AND C.organization_id IS NULL"
    
    cursor.execute("PRAGMA table_info(Catrigs)")
    columns = [col[1] for col in cursor.fetchall()]
    has_equipment_id = 'equipment_id' in columns
    
    if has_equipment_id:
        cursor.execute(f"""
            SELECT 
                C.id,
                C.Serial_number,
                C.Model,
                E.Department_Fullname as responsible,
                R.Number as room,
                C.Status,
                C.Issued,
                C.Ip,
                C.created_at,
                U.username as created_by_username,
                U.full_name as created_by_fullname,
                EQ.status as equipment_status,
                EQ.brand as equipment_brand,
                EQ.model as equipment_model,
                EQ.inventory_number as equipment_inventory,
                C.organization_id
            FROM Catrigs C
            LEFT JOIN Employees E ON C.Responsible = E.id
            LEFT JOIN Rooms R ON C.Room_id = R.id
            LEFT JOIN Equipment EQ ON C.equipment_id = EQ.id
            LEFT JOIN Users U ON C.created_by = U.id
            WHERE C.Ip LIKE ? {filter_condition}
            ORDER BY C.id DESC
        """, (f'%{ip}%', *filter_params))
    else:
        cursor.execute(f"""
            SELECT 
                C.id,
                C.Serial_number,
                C.Model,
                E.Department_Fullname as responsible,
                R.Number as room,
                C.Status,
                C.Issued,
                C.Ip,
                C.created_at,
                U.username as created_by_username,
                U.full_name as created_by_fullname,
                C.organization_id
            FROM Catrigs C
            LEFT JOIN Employees E ON C.Responsible = E.id
            LEFT JOIN Rooms R ON C.Room_id = R.id
            LEFT JOIN Users U ON C.created_by = U.id
            WHERE C.Ip LIKE ? {filter_condition}
            ORDER BY C.id DESC
        """, (f'%{ip}%', *filter_params))
    
    cartridges = []
    for row in cursor.fetchall():
        if has_equipment_id:
            mfu_name = ''
            mfu_status = ''
            if row['equipment_brand'] or row['equipment_model']:
                brand = row['equipment_brand'] or ''
                model = row['equipment_model'] or ''
                mfu_name = f"{brand} {model}".strip()
                if row['equipment_inventory']:
                    mfu_name += f" (инв. {row['equipment_inventory']})"
                mfu_status = row['equipment_status'] or ''
            
            cartridges.append({
                'id': row['id'],
                'serial_number': row['Serial_number'] or '',
                'responsible': row['responsible'] or '',
                'room': row['room'] or '',
                'status': row['Status'] or '',
                'mfu_status': mfu_status or '',
                'mfu_name': mfu_name or '',
                'issued': row['Issued'] or '',
                'ip': row['Ip'] or '',
                'created_at': row['created_at'],
                'created_by': row['created_by_username'] or row['created_by_fullname'] or None,
                'organization_id': row['organization_id'] if 'organization_id' in row.keys() else None
            })
        else:
            cartridges.append({
                'id': row['id'],
                'serial_number': row['Serial_number'] or '',
                'responsible': row['responsible'] or '',
                'room': row['room'] or '',
                'status': row['Status'] or '',
                'mfu_status': '',
                'mfu_name': '',
                'issued': row['Issued'] or '',
                'ip': row['Ip'] or '',
                'created_at': row['created_at'],
                'created_by': row['created_by_username'] or row['created_by_fullname'] or None,
                'organization_id': row['organization_id'] if 'organization_id' in row.keys() else None
            })
    
    conn.close()
    return jsonify(cartridges)


# ========== ОБОРУДОВАНИЕ ==========

@app.route('/api/equipment', methods=['GET'])
@login_required
def get_equipment():
    conn = get_db()
    cursor = conn.cursor()
    
    org_id = get_user_organization_id()
    is_admin = session.get('role') == 'admin'
    
    filter_condition = ""
    filter_params = []
    
    if org_id:
        filter_condition = "AND e.organization_id = ?"
        filter_params = [org_id]
    elif not is_admin:
        filter_condition = "AND e.organization_id IS NULL"
    
    cursor.execute(f"""
        SELECT 
            e.id, e.type, e.brand, e.model, e.serial_number, e.inventory_number,
            e.processor, e.ram, e.ram_type, e.storage, e.os, e.os_key,
            e.monitor_size, e.resolution, e.refresh_rate, e.panel_type, e.response_time, 
            e.viewing_angle, e.ports,
            e.port_count, e.speed, e.network_type, e.poe, e.managed, e.ip_address,
            e.print_type, e.print_format, e.print_speed, e.color_type, e.duplex, e.printer_ports,
            e.scanner_resolution, e.scanner_speed,
            e.duplex_scanner, e.scan_format,
            e.phone_number, e.phone_ip, e.sip_account, e.lines, e.phone_poe,
            e.ups_power, e.ups_type, e.ups_outlets, e.ups_usb, e.ups_runtime,
            e.connection_type, e.color,
            e.is_set, e.set_type,
            e.characteristics,
            e.notes,
            COALESCE(resp_emp.Department_Fullname, '') as responsible,
            COALESCE(mol_emp.Department_Fullname, '') as mol,
            rm.Number as room,
            d.name as department_name,
            org.name as organization,
            e.organization_id, e.status, e.purchase_date, e.warranty_until,
            e.price, e.supplier,
            e.created_at,
            u.username as created_by_username, u.full_name as created_by_fullname
        FROM Equipment e
        LEFT JOIN Employees resp_emp ON e.responsible_employee = resp_emp.id
        LEFT JOIN Employees mol_emp ON e.mol_employee = mol_emp.id
        LEFT JOIN Rooms rm ON e.room_id = rm.id
        LEFT JOIN Departments d ON rm.department_id = d.id
        LEFT JOIN Organizations org ON e.organization_id = org.id
        LEFT JOIN Users u ON e.created_by = u.id
        WHERE 1=1 {filter_condition}
        ORDER BY e.created_at DESC, e.id DESC
    """, filter_params)
    
    equipment = []
    for row in cursor.fetchall():
        equipment.append({
            'id': row[0],
            'type': row[1] or '',
            'brand': row[2] or '',
            'model': row[3] or '',
            'serial_number': row[4] or '',
            'inventory_number': row[5] or '',
            'processor': row[6] or '',
            'ram': row[7] or '',
            'ram_type': row[8] or '',
            'storage': row[9] or '',
            'os': row[10] or '',
            'os_key': row[11] or '',
            'monitor_size': row[12] or '',
            'resolution': row[13] or '',
            'refresh_rate': row[14] or '',
            'panel_type': row[15] or '',
            'response_time': row[16] or '',
            'viewing_angle': row[17] or '',
            'ports': row[18] or '',
            'port_count': row[19] or '',
            'speed': row[20] or '',
            'network_type': row[21] or '',
            'poe': row[22] or '',
            'managed': row[23] or '',
            'ip_address': row[24] or '',
            'print_type': row[25] or '',
            'print_format': row[26] or '',
            'print_speed': row[27] or '',
            'color_type': row[28] or '',
            'duplex': row[29] or '',
            'printer_ports': row[30] or '',
            'scanner_resolution': row[31] or '',
            'scanner_speed': row[32] or '',
            'duplex_scanner': row[33] or '',
            'scan_format': row[34] or '',
            'phone_number': row[35] or '',
            'phone_ip': row[36] or '',
            'sip_account': row[37] or '',
            'lines': row[38] or '',
            'phone_poe': row[39] or '',
            'ups_power': row[40] or '',
            'ups_type': row[41] or '',
            'ups_outlets': row[42] or '',
            'ups_usb': row[43] or '',
            'ups_runtime': row[44] or '',
            'connection_type': row[45] or '',
            'color': row[46] or '',
            'is_set': row[47] if len(row) > 47 else 0,
            'set_type': row[48] if len(row) > 48 else '',
            'characteristics': row[49] if len(row) > 49 else '',
            'notes': row[50] if len(row) > 50 else '',
            'responsible': row[51] if len(row) > 51 else '',
            'mol': row[52] if len(row) > 52 else '',
            'room': row[53] if len(row) > 53 else '',
            'department_name': row[54] if len(row) > 54 else '',
            'organization': row[55] if len(row) > 55 else '',
            'organization_id': row[56] if len(row) > 56 else None,
            'status': row[57] if len(row) > 57 else 'В работе',
            'purchase_date': row[58] if len(row) > 58 and row[58] else '',
            'warranty_until': row[59] if len(row) > 59 and row[59] else '',
            'price': float(row[60]) if len(row) > 60 and row[60] else 0,
            'supplier': row[61] if len(row) > 61 else '',
            'created_at': row[62] if len(row) > 62 else None,
            'created_by': row[63] if len(row) > 63 else row[64] if len(row) > 64 else ''
        })
    
    conn.close()
    return jsonify(equipment)


# ========== СТАТИСТИКА ОБОРУДОВАНИЯ (ИСПРАВЛЕННАЯ) ==========

@app.route('/api/equipment/statistics', methods=['GET'])
@login_required
def get_equipment_statistics():
    conn = get_db()
    cursor = conn.cursor()
    
    org_id = get_user_organization_id()
    is_admin = session.get('role') == 'admin'
    
    # Для каждого запроса используем алиас e для таблицы Equipment
    if org_id:
        # Свой филиал
        cursor.execute("SELECT COUNT(*) FROM Equipment e WHERE e.organization_id = ?", (org_id,))
        total = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT e.type, COUNT(*) FROM Equipment e
            WHERE e.organization_id = ?
            GROUP BY e.type ORDER BY COUNT(*) DESC
        """, (org_id,))
        by_type = [{'type': row[0] or 'Не указан', 'count': row[1]} for row in cursor.fetchall()]
        
        cursor.execute("""
            SELECT e.status, COUNT(*) FROM Equipment e
            WHERE e.organization_id = ?
            GROUP BY e.status
        """, (org_id,))
        by_status = [{'status': row[0] or 'Не указан', 'count': row[1]} for row in cursor.fetchall()]
        
        cursor.execute("""
            SELECT org.name, COUNT(*) 
            FROM Equipment e
            LEFT JOIN Organizations org ON e.organization_id = org.id
            WHERE e.organization_id = ?
            GROUP BY org.name
            ORDER BY COUNT(*) DESC
        """, (org_id,))
        by_organization = [{'organization': row[0] or 'Не указана', 'count': row[1]} for row in cursor.fetchall()]
        
        cursor.execute("""
            SELECT COUNT(*) FROM Equipment e
            WHERE e.warranty_until IS NOT NULL AND e.warranty_until >= date('now')
            AND e.organization_id = ?
        """, (org_id,))
        under_warranty = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM Equipment e
            WHERE e.warranty_until IS NOT NULL AND e.warranty_until < date('now')
            AND e.organization_id = ?
        """, (org_id,))
        expired_warranty = cursor.fetchone()[0]
        
    elif not is_admin:
        # Обычный пользователь без филиала - только записи с NULL
        cursor.execute("SELECT COUNT(*) FROM Equipment e WHERE e.organization_id IS NULL")
        total = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT e.type, COUNT(*) FROM Equipment e
            WHERE e.organization_id IS NULL
            GROUP BY e.type ORDER BY COUNT(*) DESC
        """)
        by_type = [{'type': row[0] or 'Не указан', 'count': row[1]} for row in cursor.fetchall()]
        
        cursor.execute("""
            SELECT e.status, COUNT(*) FROM Equipment e
            WHERE e.organization_id IS NULL
            GROUP BY e.status
        """)
        by_status = [{'status': row[0] or 'Не указан', 'count': row[1]} for row in cursor.fetchall()]
        
        cursor.execute("""
            SELECT org.name, COUNT(*) 
            FROM Equipment e
            LEFT JOIN Organizations org ON e.organization_id = org.id
            WHERE e.organization_id IS NULL
            GROUP BY org.name
            ORDER BY COUNT(*) DESC
        """)
        by_organization = [{'organization': row[0] or 'Не указана', 'count': row[1]} for row in cursor.fetchall()]
        
        cursor.execute("""
            SELECT COUNT(*) FROM Equipment e
            WHERE e.warranty_until IS NOT NULL AND e.warranty_until >= date('now')
            AND e.organization_id IS NULL
        """)
        under_warranty = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM Equipment e
            WHERE e.warranty_until IS NOT NULL AND e.warranty_until < date('now')
            AND e.organization_id IS NULL
        """)
        expired_warranty = cursor.fetchone()[0]
        
    else:
        # Администратор без филиала - видит всё
        cursor.execute("SELECT COUNT(*) FROM Equipment e")
        total = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT e.type, COUNT(*) FROM Equipment e
            GROUP BY e.type ORDER BY COUNT(*) DESC
        """)
        by_type = [{'type': row[0] or 'Не указан', 'count': row[1]} for row in cursor.fetchall()]
        
        cursor.execute("""
            SELECT e.status, COUNT(*) FROM Equipment e
            GROUP BY e.status
        """)
        by_status = [{'status': row[0] or 'Не указан', 'count': row[1]} for row in cursor.fetchall()]
        
        cursor.execute("""
            SELECT org.name, COUNT(*) 
            FROM Equipment e
            LEFT JOIN Organizations org ON e.organization_id = org.id
            GROUP BY org.name
            ORDER BY COUNT(*) DESC
        """)
        by_organization = [{'organization': row[0] or 'Не указана', 'count': row[1]} for row in cursor.fetchall()]
        
        cursor.execute("""
            SELECT COUNT(*) FROM Equipment e
            WHERE e.warranty_until IS NOT NULL AND e.warranty_until >= date('now')
        """)
        under_warranty = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM Equipment e
            WHERE e.warranty_until IS NOT NULL AND e.warranty_until < date('now')
        """)
        expired_warranty = cursor.fetchone()[0]
    
    conn.close()
    
    return jsonify({
        'total': total,
        'by_type': by_type,
        'by_status': by_status,
        'by_organization': by_organization,
        'under_warranty': under_warranty,
        'expired_warranty': expired_warranty
    })


# ========== ПОИСК ОБОРУДОВАНИЯ ==========

@app.route('/api/equipment/search', methods=['POST'])
@login_required
def search_equipment():
    data = request.json
    search_term = data.get('search', '').strip()
    search_field = data.get('field', 'all')

    conn = get_db()
    cursor = conn.cursor()

    org_id = get_user_organization_id()
    is_admin = session.get('role') == 'admin'

    # Фильтр по филиалу
    filter_condition = ""
    filter_params = []

    if org_id:
        filter_condition = "AND e.organization_id = ?"
        filter_params = [org_id]
    elif not is_admin:
        filter_condition = "AND e.organization_id IS NULL"

    # Базовый запрос с исправленным JOIN
    query = f"""
        SELECT 
            e.id, e.type, e.brand, e.model, e.serial_number, e.inventory_number,
            e.processor, e.ram, e.storage, e.os, e.status,
            COALESCE(resp_emp.Department_Fullname, '—') as responsible,
            COALESCE(mol_emp.Department_Fullname, '—') as mol,
            r.Number as room, 
            org.name as organization,
            d.name as department_name,
            e.created_at, 
            u.username as created_by,
            e.monitor_size, e.resolution, e.port_count, e.speed,
            e.os_key, e.purchase_date, e.warranty_until, e.price, e.supplier,
            e.notes,
            e.characteristics
        FROM Equipment e
        LEFT JOIN Employees resp_emp ON e.responsible_employee = resp_emp.id
        LEFT JOIN Employees mol_emp ON e.mol_employee = mol_emp.id
        LEFT JOIN Rooms r ON e.room_id = r.id
        LEFT JOIN Departments d ON r.department_id = d.id          -- <-- ИСПРАВЛЕНО
        LEFT JOIN Organizations org ON e.organization_id = org.id
        LEFT JOIN Users u ON e.created_by = u.id
        WHERE 1=1 {filter_condition}
    """

    # Обработка поискового запроса по выбранному полю
    if search_term:
        if search_field == 'serial_number':
            query += " AND e.serial_number LIKE ?"
            filter_params.append(f'%{search_term}%')
        elif search_field == 'inventory_number':
            query += " AND e.inventory_number LIKE ?"
            filter_params.append(f'%{search_term}%')
        elif search_field == 'model':
            query += " AND e.model LIKE ?"
            filter_params.append(f'%{search_term}%')
        elif search_field == 'type':
            query += " AND e.type LIKE ?"
            filter_params.append(f'%{search_term}%')
        elif search_field == 'brand':
            query += " AND e.brand LIKE ?"
            filter_params.append(f'%{search_term}%')
        elif search_field == 'responsible':
            query += " AND resp_emp.Department_Fullname LIKE ?"
            filter_params.append(f'%{search_term}%')
        elif search_field == 'mol':
            query += " AND mol_emp.Department_Fullname LIKE ?"
            filter_params.append(f'%{search_term}%')
        elif search_field == 'room':
            query += " AND r.Number LIKE ?"
            filter_params.append(f'%{search_term}%')
        elif search_field == 'organization':
            query += " AND org.name LIKE ?"
            filter_params.append(f'%{search_term}%')
        elif search_field == 'status':
            query += " AND e.status LIKE ?"
            filter_params.append(f'%{search_term}%')
        elif search_field == 'all':
            conditions = [
                "e.type LIKE ?",
                "e.brand LIKE ?",
                "e.model LIKE ?",
                "e.serial_number LIKE ?",
                "e.inventory_number LIKE ?",
                "resp_emp.Department_Fullname LIKE ?",
                "mol_emp.Department_Fullname LIKE ?",
                "r.Number LIKE ?",
                "org.name LIKE ?",
                "e.status LIKE ?"
            ]
            query += " AND (" + " OR ".join(conditions) + ")"
            filter_params.extend([f'%{search_term}%'] * len(conditions))

    query += " ORDER BY e.created_at DESC, e.id DESC"

    cursor.execute(query, filter_params)

    equipment = []
    for row in cursor.fetchall():
        equipment.append({
            'id': row[0],
            'type': row[1] or '',
            'brand': row[2] or '',
            'model': row[3] or '',
            'serial_number': row[4] or '',
            'inventory_number': row[5] or '',
            'processor': row[6] or '',
            'ram': row[7] or '',
            'storage': row[8] or '',
            'os': row[9] or '',
            'status': row[10] or 'В работе',
            'responsible': row[11] or '',
            'mol': row[12] or '',
            'room': row[13] or '',
            'organization': row[14] or '',
            'department_name': row[15] or '',
            'created_at': row[16] if len(row) > 16 else None,
            'created_by': row[17] if len(row) > 17 else None,
            'monitor_size': row[18] if len(row) > 18 else '',
            'resolution': row[19] if len(row) > 19 else '',
            'port_count': row[20] if len(row) > 20 else '',
            'speed': row[21] if len(row) > 21 else '',
            'os_key': row[22] if len(row) > 22 else '',
            'purchase_date': row[23] if len(row) > 23 else '',
            'warranty_until': row[24] if len(row) > 24 else '',
            'price': row[25] if len(row) > 25 else 0,
            'supplier': row[26] if len(row) > 26 else '',
            'notes': row[27] if len(row) > 27 else '',
            'characteristics': row[28] if len(row) > 28 else ''
        })

    conn.close()
    return jsonify(equipment)

# ========== ОТЧЕТ ПО ОБОРУДОВАНИЮ ==========

@app.route('/api/equipment/report', methods=['POST'])
@login_required
def get_equipment_report():
    data = request.json
    report_type = data.get('type', 'mol')
    employee_name = data.get('employee_name', '').strip()
    
    conn = get_db()
    cursor = conn.cursor()
    
    org_id = get_user_organization_id()
    is_admin = session.get('role') == 'admin'
    
    # Проверяем, что сотрудник выбран
    if not employee_name:
        conn.close()
        return jsonify({'error': 'Выберите сотрудника'}), 400
    
    # Ищем сотрудника
    cursor.execute("SELECT id FROM Employees WHERE Department_Fullname = ?", (employee_name,))
    employee = cursor.fetchone()
    
    if not employee:
        conn.close()
        return jsonify({'error': 'Сотрудник не найден'}), 404
    
    employee_id = employee[0]
    
    # Формируем фильтр по филиалу с алиасом e
    filter_condition = ""
    filter_params = []
    
    if org_id:
        filter_condition = "AND e.organization_id = ?"
        filter_params = [org_id]
    elif not is_admin:
        filter_condition = "AND e.organization_id IS NULL"
    
    # Формируем запрос в зависимости от типа отчета
    if report_type == 'mol':
        query = f"""
            SELECT 
                e.id, e.type, e.brand, e.model, e.serial_number, e.inventory_number,
                e.processor, e.ram, e.storage, e.os, e.os_key,
                e.monitor_size, e.resolution, e.port_count, e.speed,
                e.status, e.purchase_date, e.warranty_until, e.price, e.supplier, e.notes,
                r.Number as room, org.name as organization,
                e.created_at, u.username as created_by
            FROM Equipment e
            LEFT JOIN Rooms r ON e.room_id = r.id
            LEFT JOIN Organizations org ON e.organization_id = org.id
            LEFT JOIN Users u ON e.created_by = u.id
            WHERE e.mol_employee = ? {filter_condition}
            ORDER BY e.type, e.brand, e.model
        """
        cursor.execute(query, (employee_id, *filter_params))
    else:
        query = f"""
            SELECT 
                e.id, e.type, e.brand, e.model, e.serial_number, e.inventory_number,
                e.processor, e.ram, e.storage, e.os, e.os_key,
                e.monitor_size, e.resolution, e.port_count, e.speed,
                e.status, e.purchase_date, e.warranty_until, e.price, e.supplier, e.notes,
                r.Number as room, org.name as organization,
                e.created_at, u.username as created_by
            FROM Equipment e
            LEFT JOIN Rooms r ON e.room_id = r.id
            LEFT JOIN Organizations org ON e.organization_id = org.id
            LEFT JOIN Users u ON e.created_by = u.id
            WHERE e.responsible_employee = ? {filter_condition}
            ORDER BY e.type, e.brand, e.model
        """
        cursor.execute(query, (employee_id, *filter_params))
    
    equipment = []
    for row in cursor.fetchall():
        equipment.append({
            'id': row[0],
            'type': row[1] or '',
            'brand': row[2] or '',
            'model': row[3] or '',
            'serial_number': row[4] or '',
            'inventory_number': row[5] or '',
            'processor': row[6] or '',
            'ram': row[7] or '',
            'storage': row[8] or '',
            'os': row[9] or '',
            'os_key': row[10] or '',
            'monitor_size': row[11] or '',
            'resolution': row[12] or '',
            'port_count': row[13] or '',
            'speed': row[14] or '',
            'status': row[15] or 'В работе',
            'purchase_date': row[16] if row[16] else '',
            'warranty_until': row[17] if row[17] else '',
            'price': float(row[18]) if row[18] else 0,
            'supplier': row[19] or '',
            'notes': row[20] or '',
            'room': row[21] or '',
            'organization': row[22] or '',
            'created_at': row[23],
            'created_by': row[24] or ''
        })
    
    conn.close()
    
    current_user = session.get('full_name', session.get('username', 'Пользователь'))
    
    return jsonify({
        'employee_name': employee_name,
        'report_type': report_type,
        'report_type_name': 'Материально-ответственное лицо' if report_type == 'mol' else 'Ответственный сотрудник',
        'equipment': equipment,
        'count': len(equipment),
        'generated_at': datetime.now().strftime('%d.%m.%Y %H:%M:%S'),
        'generated_by': current_user
    })


# ========== МФУ ИЗ ОБОРУДОВАНИЯ ==========

@app.route('/api/equipment-mfu', methods=['GET'])
@login_required
def get_equipment_mfu():
    conn = get_db()
    cursor = conn.cursor()
    
    org_id = get_user_organization_id()
    is_admin = session.get('role') == 'admin'
    
    filter_condition = ""
    filter_params = []
    
    if org_id:
        filter_condition = "AND organization_id = ?"
        filter_params = [org_id]
    elif not is_admin:
        filter_condition = "AND organization_id IS NULL"
    
    cursor.execute(f"""
        SELECT id, type, brand, model, status, inventory_number, organization_id 
        FROM Equipment 
        WHERE type IN ('МФУ', 'Принтер') {filter_condition}
        ORDER BY brand, model
    """, filter_params)
    
    mfu_list = []
    for row in cursor.fetchall():
        if row[2] and row[3]:
            name = f"{row[2]} {row[3]}".strip()
        elif row[2]:
            name = row[2]
        elif row[3]:
            name = row[3]
        else:
            name = "Без названия"
        
        mfu_list.append({
            'id': row[0],
            'name': name,
            'status': row[4] or 'В работе',
            'inventory_number': row[5] or '',
            'organization_id': row[6] if len(row) > 6 else None
        })
    
    conn.close()
    return jsonify(mfu_list)

@app.after_request
def add_no_cache_headers(response):
    """Добавляет заголовки, запрещающие кэширование"""
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# ========== ДЕБАГ ==========

@app.route('/api/debug/organizations', methods=['GET'])
@login_required
def debug_organizations():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM Organizations")
    orgs = cursor.fetchall()
    conn.close()
    return jsonify({
        'count': len(orgs),
        'organizations': [{'id': row[0], 'name': row[1]} for row in orgs]
    })

@app.route('/api/debug/equipment/<int:id>', methods=['GET'])
@login_required
def debug_equipment(id):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM Equipment WHERE id = ?", (id,))
    columns = [description[0] for description in cursor.description]
    row = cursor.fetchone()
    
    result = {}
    if row:
        for i, col in enumerate(columns):
            result[col] = row[i]
    
    conn.close()
    return jsonify(result)

@app.route('/api/debug/compatibility-check', methods=['GET'])
@login_required
def debug_compatibility_check():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, cartridge_model, mfu_model FROM Compatibility")
    compatibility = cursor.fetchall()
    
    cursor.execute("""
        SELECT id, type, brand, model, inventory_number 
        FROM Equipment 
        WHERE type IN ('МФУ', 'Принтер')
    """)
    equipment_mfu = cursor.fetchall()
    
    conn.close()
    
    return jsonify({
        'compatibility': [{'id': c[0], 'cartridge': c[1], 'mfu': c[2]} for c in compatibility],
        'equipment_mfu': [{'id': e[0], 'type': e[1], 'brand': e[2], 'model': e[3], 'inventory': e[4]} for e in equipment_mfu]
    })

# ========== ЗАПУСК ==========
if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == '--dev':
        app.run(debug=True, host='127.0.0.1', port=5000)
    else:
        print("""
        ⚠️  ВНИМАНИЕ: Запуск в режиме разработки!
        Для production используйте: python server.py
        Или укажите аргумент --dev для режима отладки
        """)
        app.run(debug=False, host='0.0.0.0', port=5000)