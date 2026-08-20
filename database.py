import sqlite3
import os
import sys
from datetime import datetime
import hashlib

def get_db_path():
    """Получение пути к базе данных в зависимости от способа запуска"""
    env_db_path = os.environ.get('DATABASE_PATH')
    if env_db_path:
        db_dir = os.path.dirname(env_db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        return env_db_path
    
    if getattr(sys, 'frozen', False):
        appdata = os.environ.get('APPDATA', os.path.expanduser('~'))
        db_dir = os.path.join(appdata, 'VolgoBaltAccounting')
        os.makedirs(db_dir, exist_ok=True)
        print(f"[database] Используем APPDATA: {db_dir}")
        return os.path.join(db_dir, 'db.db')
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(script_dir, 'db.db')

def get_db():
    db_path = get_db_path()
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
        print(f"[database] Создана директория: {db_dir}")
    
    if not os.path.exists(db_path):
        print(f"[database] БД не найдена, создаем новую: {db_path}")
        init_db()
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def init_db():
    db_path = get_db_path()
    print(f"Создание базы данных: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # ========== ТАБЛИЦЫ ДЛЯ УЧЕТА КАРТРИДЖЕЙ ==========
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            Department_Fullname TEXT UNIQUE,
            Organization_id INTEGER,
            FOREIGN KEY(Organization_id) REFERENCES Organizations(id)
        )
    """)
    
    cursor.execute("PRAGMA table_info(Employees)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'department_id' not in columns:
        cursor.execute("ALTER TABLE Employees ADD COLUMN department_id INTEGER")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_employees_department ON Employees(department_id)")
        print("✅ Добавлено поле department_id в таблицу Employees")
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            Number TEXT UNIQUE,
            department_id INTEGER,
            FOREIGN KEY(department_id) REFERENCES Departments(id) ON DELETE SET NULL
        )
    """)
        
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Postavki (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            Date_of_purchase DATE
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS MFU (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            Name_MFU TEXT UNIQUE,
            Status TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS CartridgeModels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ModelName TEXT UNIQUE,
            Ip TEXT UNIQUE
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Catrigs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            Serial_number TEXT,
            Model TEXT,
            Responsible INTEGER,
            Room_id INTEGER,
            Status TEXT,
            Purchase INTEGER,
            Issued TEXT,
            equipment_id INTEGER,
            Ip TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by INTEGER,
            FOREIGN KEY(Responsible) REFERENCES Employees(id),
            FOREIGN KEY(Room_id) REFERENCES Rooms(id),
            FOREIGN KEY(Purchase) REFERENCES Postavki(id),
            FOREIGN KEY(equipment_id) REFERENCES Equipment(id),
            FOREIGN KEY(created_by) REFERENCES Users(id)
        )
    """)
    
    cursor.execute("PRAGMA table_info(Catrigs)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'equipment_id' not in columns:
        cursor.execute("ALTER TABLE Catrigs ADD COLUMN equipment_id INTEGER")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_catrigs_equipment ON Catrigs(equipment_id)")
        print("✅ Добавлено поле equipment_id в таблицу Catrigs")

    cursor.execute("PRAGMA table_info(Catrigs)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'Ip' not in columns:
        cursor.execute("ALTER TABLE Catrigs ADD COLUMN Ip TEXT")
    if 'created_at' not in columns:
        cursor.execute("ALTER TABLE Catrigs ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    if 'created_by' not in columns:
        cursor.execute("ALTER TABLE Catrigs ADD COLUMN created_by INTEGER")
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Analytics (
            Cartridge TEXT PRIMARY KEY,
            ToWriteOff INTEGER DEFAULT 0,
            InStock INTEGER DEFAULT 0,
            OnBalance INTEGER DEFAULT 0,
            ToBuy INTEGER DEFAULT 0
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Compatibility (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cartridge_model TEXT,
            mfu_model TEXT,
            FOREIGN KEY(cartridge_model) REFERENCES CartridgeModels(ModelName),
            FOREIGN KEY(mfu_model) REFERENCES MFU(Name_MFU),
            UNIQUE(cartridge_model, mfu_model)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            office TEXT,
            organization_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(organization_id) REFERENCES Organizations(id)
        )
    """)

    cursor.execute("PRAGMA table_info(Analytics)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'organization_id' not in columns:
        cursor.execute("ALTER TABLE Analytics ADD COLUMN organization_id INTEGER")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_analytics_organization ON Analytics(organization_id)")
        print("✅ Добавлена колонка organization_id в таблицу Analytics")

    cursor.execute("PRAGMA table_info(Departments)")
    cols = [c[1] for c in cursor.fetchall()]
    if 'office' not in cols:
        cursor.execute("ALTER TABLE Departments ADD COLUMN office TEXT")

    # ========== ТАБЛИЦА ДЛЯ УЧЕТА ОБОРУДОВАНИЯ ==========
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Equipment'")
    table_exists = cursor.fetchone()
    
    if not table_exists:
        cursor.execute("""
            CREATE TABLE Equipment (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                mol_employee INTEGER,
                brand TEXT,
                model TEXT,
                serial_number TEXT,
                inventory_number TEXT,
                processor TEXT,
                ram INTEGER,
                ram_type TEXT,
                storage TEXT,
                os TEXT,
                os_key TEXT,
                monitor_size INTEGER,
                resolution TEXT,
                refresh_rate INTEGER,
                panel_type TEXT,
                response_time INTEGER,
                viewing_angle TEXT,
                ports TEXT,
                port_count INTEGER,
                speed TEXT,
                network_type TEXT,
                poe TEXT,
                managed TEXT,
                ip_address TEXT,
                print_type TEXT,
                print_format TEXT,
                print_speed INTEGER,
                color_type TEXT,
                duplex TEXT,
                printer_ports TEXT,
                scanner_resolution TEXT,
                scanner_speed TEXT,
                duplex_scanner TEXT,
                scan_format TEXT,          -- <-- ДОБАВЛЕНА
                phone_number TEXT,
                phone_ip TEXT,
                sip_account TEXT,
                lines INTEGER,
                phone_poe TEXT,
                ups_power TEXT,
                ups_type TEXT,
                ups_outlets INTEGER,
                ups_usb TEXT,
                ups_runtime INTEGER,
                connection_type TEXT,
                color TEXT,
                is_set INTEGER DEFAULT 0,
                set_type TEXT,
                responsible_employee INTEGER,
                room_id INTEGER,
                organization_id INTEGER,
                status TEXT DEFAULT 'В работе',
                purchase_date DATE,
                warranty_until DATE,
                price DECIMAL(10,2),
                supplier TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by INTEGER,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_by INTEGER,
                FOREIGN KEY(responsible_employee) REFERENCES Employees(id),
                FOREIGN KEY(mol_employee) REFERENCES Employees(id),
                FOREIGN KEY(room_id) REFERENCES Rooms(id),
                FOREIGN KEY(organization_id) REFERENCES Organizations(id),
                FOREIGN KEY(created_by) REFERENCES Users(id),
                FOREIGN KEY(updated_by) REFERENCES Users(id)
            )
        """)
        print("✅ Таблица Equipment создана")
    else:
        # Обновляем существующую таблицу – добавляем недостающие колонки
        cursor.execute("PRAGMA table_info(Equipment)")
        existing_columns = [col[1] for col in cursor.fetchall()]
        
        new_columns = {
            'ram_type': 'TEXT',
            'refresh_rate': 'INTEGER',
            'panel_type': 'TEXT',
            'response_time': 'INTEGER',
            'viewing_angle': 'TEXT',
            'ports': 'TEXT',
            'network_type': 'TEXT',
            'poe': 'TEXT',
            'managed': 'TEXT',
            'ip_address': 'TEXT',
            'print_type': 'TEXT',
            'print_format': 'TEXT',
            'print_speed': 'INTEGER',
            'color_type': 'TEXT',
            'duplex': 'TEXT',
            'duplex_scanner': 'TEXT',
            'scan_format': 'TEXT',      # <-- ДОБАВЛЕНА
            'printer_ports': 'TEXT',
            'scanner_resolution': 'TEXT',
            'scanner_speed': 'TEXT',
            'phone_number': 'TEXT',
            'phone_ip': 'TEXT',
            'sip_account': 'TEXT',
            'lines': 'INTEGER',
            'phone_poe': 'TEXT',
            'ups_power': 'TEXT',
            'ups_type': 'TEXT',
            'ups_outlets': 'INTEGER',
            'ups_usb': 'TEXT',
            'ups_runtime': 'INTEGER',
            'connection_type': 'TEXT',
            'color': 'TEXT',
        }
        
        for col_name, col_type in new_columns.items():
            if col_name not in existing_columns:
                try:
                    cursor.execute(f"ALTER TABLE Equipment ADD COLUMN {col_name} {col_type}")
                    print(f"✅ Добавлена колонка {col_name} в таблицу Equipment")
                except Exception as e:
                    print(f"⚠️ Ошибка добавления {col_name}: {e}")
    
    # ========== ТАБЛИЦЫ ДЛЯ УЧЕТА ЛИЦЕНЗИЙ ==========
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Licenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            product_key TEXT UNIQUE,
            expiry_date DATE,
            email TEXT,
            company TEXT,
            quantity INTEGER DEFAULT 0,
            used INTEGER DEFAULT 0
        )
    """)
    
    # ========== ТАБЛИЦА ДЛЯ УЧЕТА ОРГАНИЗАЦИЙ ==========
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Organizations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            address TEXT
        )
    """)
    
    # ========== ТАБЛИЦА ДЛЯ ПОЛЬЗОВАТЕЛЕЙ ==========
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT,
            role TEXT DEFAULT 'user',
            organization_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP,
            is_active INTEGER DEFAULT 1,
            FOREIGN KEY(organization_id) REFERENCES Organizations(id)
        )
    """)
    
    cursor.execute("PRAGMA table_info(Users)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'organization_id' not in columns:
        cursor.execute("ALTER TABLE Users ADD COLUMN organization_id INTEGER")
    
    # ========== ИНДЕКСЫ ==========
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_catrigs_serial ON Catrigs(Serial_number)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_catrigs_status ON Catrigs(Status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_catrigs_ip ON Catrigs(Ip)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_catrigs_created ON Catrigs(created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_catrigs_created_by ON Catrigs(created_by)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_licenses_expiry ON Licenses(expiry_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_organizations_name ON Organizations(name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON Users(username)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_role ON Users(role)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_organization ON Users(organization_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_equipment_type ON Equipment(type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_equipment_serial ON Equipment(serial_number)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_equipment_inventory ON Equipment(inventory_number)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_equipment_status ON Equipment(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_equipment_organization ON Equipment(organization_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_equipment_responsible ON Equipment(responsible_employee)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_equipment_mol ON Equipment(mol_employee)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_equipment_room ON Equipment(room_id)")

    # Создаем администратора по умолчанию
    default_password = hash_password("admin123")
    cursor.execute("""
        INSERT OR IGNORE INTO Users (username, password_hash, full_name, role, is_active)
        VALUES (?, ?, ?, ?, ?)
    """, ("admin", default_password, "Главный администратор", "admin", 1))
    
    # Таблица для истории перемещений оборудования
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS EquipmentMovements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipment_id INTEGER NOT NULL,
            from_employee INTEGER,
            to_employee INTEGER,
            from_room INTEGER,
            to_room INTEGER,
            from_organization INTEGER,
            to_organization INTEGER,
            movement_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reason TEXT,
            comment TEXT,
            created_by INTEGER,
            from_mol INTEGER, 
            to_mol INTEGER,
            FOREIGN KEY(from_mol) REFERENCES Employees(id), 
            FOREIGN KEY(to_mol) REFERENCES Employees(id),
            FOREIGN KEY(equipment_id) REFERENCES Equipment(id) ON DELETE CASCADE,
            FOREIGN KEY(from_employee) REFERENCES Employees(id),
            FOREIGN KEY(to_employee) REFERENCES Employees(id),
            FOREIGN KEY(from_room) REFERENCES Rooms(id),
            FOREIGN KEY(to_room) REFERENCES Rooms(id),
            FOREIGN KEY(from_organization) REFERENCES Organizations(id),
            FOREIGN KEY(to_organization) REFERENCES Organizations(id),
            FOREIGN KEY(created_by) REFERENCES Users(id)
        )
    """)     
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_movements_equipment ON EquipmentMovements(equipment_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_movements_date ON EquipmentMovements(movement_date)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS PeripheralTypes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    """)

    cursor.execute("INSERT OR IGNORE INTO PeripheralTypes (name) VALUES ('Мышь')")
    cursor.execute("INSERT OR IGNORE INTO PeripheralTypes (name) VALUES ('Клавиатура')")
    cursor.execute("INSERT OR IGNORE INTO PeripheralTypes (name) VALUES ('ИБП')")
    cursor.execute("INSERT OR IGNORE INTO PeripheralTypes (name) VALUES ('Внешний диск')")
    cursor.execute("INSERT OR IGNORE INTO PeripheralTypes (name) VALUES ('Док-станция')")
    cursor.execute("INSERT OR IGNORE INTO PeripheralTypes (name) VALUES ('Веб-камера')")
    cursor.execute("INSERT OR IGNORE INTO PeripheralTypes (name) VALUES ('Гарнитура')")
    cursor.execute("INSERT OR IGNORE INTO PeripheralTypes (name) VALUES ('Колонки')")

    cursor.execute("PRAGMA table_info(Users)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'can_delete_history' not in columns:
        cursor.execute("ALTER TABLE Users ADD COLUMN can_delete_history INTEGER DEFAULT 0")
        print("✅ Добавлена колонка can_delete_history в таблицу Users")

    # Добавляем недостающие колонки в Equipment (если были пропущены)
    cursor.execute("PRAGMA table_info(Equipment)")
    existing_columns = [col[1] for col in cursor.fetchall()]
    extra_columns = {
        'ram_type': 'TEXT',
        'refresh_rate': 'INTEGER',
        'panel_type': 'TEXT',
        'response_time': 'INTEGER',
        'ports': 'TEXT',
        'network_type': 'TEXT',
        'poe': 'TEXT',
        'managed': 'TEXT',
        'ip_address': 'TEXT',
        'print_type': 'TEXT',
        'print_format': 'TEXT',
        'print_speed': 'INTEGER',
        'color_type': 'TEXT',
        'duplex': 'TEXT',
        'printer_ports': 'TEXT',
        'scanner_resolution': 'TEXT',
        'scanner_speed': 'TEXT',
        'duplex_scanner': 'TEXT',
        'scan_format': 'TEXT',     # <-- добавлено
        'phone_number': 'TEXT',
        'phone_ip': 'TEXT',
        'sip_account': 'TEXT',
        'lines': 'INTEGER',
        'phone_poe': 'TEXT',
        'ups_power': 'TEXT',
        'ups_type': 'TEXT',
        'ups_outlets': 'INTEGER',
        'ups_usb': 'TEXT',
        'ups_runtime': 'INTEGER',
        'connection_type': 'TEXT',
        'color': 'TEXT',
        'viewing_angle': 'TEXT'
    }
    
    for col_name, col_type in extra_columns.items():
        if col_name not in existing_columns:
            try:
                cursor.execute(f"ALTER TABLE Equipment ADD COLUMN {col_name} {col_type}")
                print(f"✅ Добавлена колонка {col_name} в таблицу Equipment")
            except Exception as e:
                print(f"⚠️ Ошибка добавления {col_name}: {e}")

    cursor.execute("PRAGMA table_info(Catrigs)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'equipment_id' not in columns:
        cursor.execute("ALTER TABLE Catrigs ADD COLUMN equipment_id INTEGER")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_catrigs_equipment ON Catrigs(equipment_id)")
        print("✅ Добавлено поле equipment_id в таблицу Catrigs")
        
        cursor.execute("""
            UPDATE Catrigs 
            SET equipment_id = (
                SELECT Equipment.id FROM Equipment 
                WHERE Equipment.type IN ('МФУ', 'Принтер')
                AND Equipment.brand || ' ' || Equipment.model = (
                    SELECT MFU.Name_MFU FROM MFU WHERE MFU.id = Catrigs.MFU_id
                )
                LIMIT 1
            )
            WHERE MFU_id IS NOT NULL AND equipment_id IS NULL
        """)
        print(f"✅ Мигрировано {cursor.rowcount} картриджей на связь с Equipment")

    # Добавляем колонку status в Licenses, если её нет
    cursor.execute("PRAGMA table_info(Licenses)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'status' not in columns:
        cursor.execute("ALTER TABLE Licenses ADD COLUMN status TEXT DEFAULT 'Активна'")
        print("✅ Добавлена колонка status в таблицу Licenses")

    cursor.execute("PRAGMA table_info(Rooms)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'department_id' not in columns:
        cursor.execute("ALTER TABLE Rooms ADD COLUMN department_id INTEGER")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_rooms_department ON Rooms(department_id)")
        print("✅ Добавлено поле department_id в таблицу Rooms")

    conn.commit()
    conn.close()
    print("✅ База данных инициализирована")

def upgrade_db():
    """Обновление схемы базы данных до актуальной версии"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(Equipment)")
    existing_columns = [col[1] for col in cursor.fetchall()]

    new_columns = {
        'ram_type': 'TEXT',
        'refresh_rate': 'INTEGER',
        'panel_type': 'TEXT',
        'response_time': 'INTEGER',
        'ports': 'TEXT',
        'network_type': 'TEXT',
        'poe': 'TEXT',
        'managed': 'TEXT',
        'ip_address': 'TEXT',
        'print_type': 'TEXT',
        'print_format': 'TEXT',
        'print_speed': 'INTEGER',
        'color_type': 'TEXT',
        'duplex': 'TEXT',
        'printer_ports': 'TEXT',
        'scanner_resolution': 'TEXT',
        'scanner_speed': 'TEXT',
        'duplex_scanner': 'TEXT',
        'scan_format': 'TEXT',      # <-- добавлено
        'phone_number': 'TEXT',
        'phone_ip': 'TEXT',
        'sip_account': 'TEXT',
        'lines': 'INTEGER',
        'phone_poe': 'TEXT',
        'ups_power': 'TEXT',
        'ups_type': 'TEXT',
        'ups_outlets': 'INTEGER',
        'ups_usb': 'TEXT',
        'ups_runtime': 'INTEGER',
        'connection_type': 'TEXT',
        'color': 'TEXT',
        'viewing_angle': 'TEXT'
    }

    for col_name, col_type in new_columns.items():
        if col_name not in existing_columns:
            try:
                cursor.execute(f"ALTER TABLE Equipment ADD COLUMN {col_name} {col_type}")
                print(f"✅ Добавлена колонка {col_name} в таблицу Equipment")
            except Exception as e:
                print(f"⚠️ Ошибка добавления {col_name}: {e}")

    cursor.execute("PRAGMA table_info(Licenses)")
    licenses_cols = [col[1] for col in cursor.fetchall()]
    if 'status' not in licenses_cols:
        cursor.execute("ALTER TABLE Licenses ADD COLUMN status TEXT DEFAULT 'Активна'")
        print("✅ Добавлена колонка status в Licenses")

    cursor.execute("PRAGMA table_info(Catrigs)")
    catrigs_cols = [col[1] for col in cursor.fetchall()]
    if 'organization_id' not in catrigs_cols:
        try:
            cursor.execute("ALTER TABLE Catrigs ADD COLUMN organization_id INTEGER")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_catrigs_organization ON Catrigs(organization_id)")
            print("✅ Добавлена колонка organization_id в Catrigs")
        except Exception as e:
            print(f"⚠️ Ошибка добавления organization_id в Catrigs: {e}")

    cursor.execute("PRAGMA table_info(Analytics)")
    analytics_cols = [col[1] for col in cursor.fetchall()]
    if 'organization_id' not in analytics_cols:
        try:
            cursor.execute("ALTER TABLE Analytics ADD COLUMN organization_id INTEGER")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_analytics_organization ON Analytics(organization_id)")
            print("✅ Добавлена колонка organization_id в Analytics")
        except Exception as e:
            print(f"⚠️ Ошибка добавления organization_id в Analytics: {e}")

    if 'equipment_id' not in catrigs_cols:
        try:
            cursor.execute("ALTER TABLE Catrigs ADD COLUMN equipment_id INTEGER")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_catrigs_equipment ON Catrigs(equipment_id)")
            print("✅ Добавлена колонка equipment_id в Catrigs")
        except Exception as e:
            print(f"⚠️ Ошибка добавления equipment_id в Catrigs: {e}")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()