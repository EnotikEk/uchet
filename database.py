import os
import sys
import hashlib
import psycopg2
import psycopg2.extras
import psycopg2.errors

# На Windows консоль может использовать кодировку cp1251, из-за чего print()
# со спецсимволами (✅, ⚠️) роняет инициализацию БД с UnicodeEncodeError.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def _load_env_file():
    """Подхватить переменные из .env рядом с этим файлом (DATABASE_URL,
    SECRET_KEY и т.п.), чтобы приложение подключалось к БД при любом способе
    запуска — systemd, gunicorn вручную, python app.py — без export.
    Уже заданные в окружении переменные имеют приоритет и не перезаписываются."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    try:
        with open(path, encoding='utf-8') as f:
            lines = f.readlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        if line.startswith('export '):
            line = line[len('export '):].strip()
        key, value = line.split('=', 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_env_file()


def get_db_config():
    """Параметры подключения к PostgreSQL.

    DATABASE_URL (напр. postgresql://user:pass@host:5432/dbname) имеет приоритет —
    его использует и gunicorn в проде, и Docker-тест. Если не задан, собираем
    из отдельных PG*-переменных (те же имена, что понимает сам psql/libpq),
    с локальными значениями по умолчанию для разработки на этой машине.
    """
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        return database_url
    return {
        'host': os.environ.get('PGHOST', 'localhost'),
        'port': os.environ.get('PGPORT', '5432'),
        'dbname': os.environ.get('PGDATABASE', 'uchet'),
        'user': os.environ.get('PGUSER', 'uchet'),
        'password': os.environ.get('PGPASSWORD', 'uchet'),
    }


def _translate_placeholders(sql):
    """'?'-плейсхолдеры (стиль sqlite3, используется по всему app.py) → '%s'
    (стиль psycopg2). Один проход по строке, '?' внутри 'строковых литералов'
    не трогаем — так безопаснее простой замены .replace('?', '%s'), хотя в этом
    проекте '?' в текстах самих запросов и так никогда не встречается (значения
    всегда параметризуются, а не подставляются в текст запроса)."""
    out = []
    in_string = False
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if in_string:
            out.append(ch)
            if ch == "'":
                if i + 1 < n and sql[i + 1] == "'":  # экранированная '' внутри литерала
                    out.append(sql[i + 1])
                    i += 2
                    continue
                in_string = False
            i += 1
            continue
        if ch == "'":
            in_string = True
            out.append(ch)
        elif ch == '?':
            out.append('%s')
        else:
            out.append(ch)
        i += 1
    return ''.join(out)


# Таблицы без суррогатного числового id (составной первичный ключ) — для них
# нельзя автоматически дописывать "RETURNING id" (см. CompatCursor.execute).
_NO_ID_TABLES = {'analytics'}


def _insert_table_name(sql):
    import re
    m = re.match(r'\s*INSERT\s+INTO\s+"?(\w+)"?', sql, re.IGNORECASE)
    return m.group(1).lower() if m else None


class CompatCursor(psycopg2.extras.DictCursor):
    """Курсор с поведением, привычным по sqlite3, — чтобы при переходе на
    PostgreSQL не переписывать вручную все ~270 SQL-запросов в app.py:

    - принимает те же '?'-плейсхолдеры, что и раньше (см. _translate_placeholders);
    - после INSERT даёт `cursor.lastrowid`, как в sqlite3 (в psycopg2 такого
      атрибута нет в принципе — эмулируем через автоматический 'RETURNING id');
    - строки результата поддерживают и row['column'], и row[0] одновременно
      (это уже делает сам DictRow из psycopg2.extras, ничего сверх делать не нужно).
    """

    @property
    def lastrowid(self):
        # Базовый курсор psycopg2 сам объявляет `lastrowid` как read-only
        # атрибут (для совместимости с DBAPI, всегда None) — просто
        # присвоить self.lastrowid нельзя, поэтому переопределяем его
        # здесь обычным свойством поверх приватного атрибута.
        return getattr(self, '_lastrowid', None)

    @lastrowid.setter
    def lastrowid(self, value):
        self._lastrowid = value

    def execute(self, sql, params=None):
        translated = _translate_placeholders(sql)
        stripped = translated.lstrip().upper()

        wants_lastrowid = False
        if stripped.startswith('INSERT'):
            table = _insert_table_name(translated)
            if table not in _NO_ID_TABLES and 'RETURNING' not in translated.upper():
                translated = translated.rstrip().rstrip(';') + ' RETURNING id'
                wants_lastrowid = True

        if params is None:
            result = super().execute(translated)
        else:
            result = super().execute(translated, params)

        if wants_lastrowid:
            row = self.fetchone()
            self.lastrowid = row[0] if row else None
        else:
            self.lastrowid = None
        return result


def get_db():
    """Открыть соединение с PostgreSQL. Каждый запрос — новое соединение
    (как и раньше с sqlite3): при небольшой нагрузке этого инструмента пул
    не требуется, а PostgreSQL, в отличие от файлового SQLite, спокойно
    выдерживает много параллельных соединений от разных воркеров gunicorn —
    именно ради снятия этого ограничения и делалась миграция с SQLite."""
    config = get_db_config()
    if isinstance(config, str):
        return psycopg2.connect(config, cursor_factory=CompatCursor)
    return psycopg2.connect(cursor_factory=CompatCursor, **config)


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def _column_exists(cursor, table, column):
    cursor.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
        (table.lower(), column.lower())
    )
    return cursor.fetchone() is not None


def _pk_columns(cursor, table):
    cursor.execute("""
        SELECT a.attname
        FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = %s::regclass AND i.indisprimary
    """, (table,))
    return [row[0] for row in cursor.fetchall()]


def _table_exists(cursor, table):
    cursor.execute("SELECT 1 FROM information_schema.tables WHERE table_name = %s", (table.lower(),))
    return cursor.fetchone() is not None


def _migrate_analytics_pk(cursor):
    """Убедиться, что уникальность в Analytics обеспечена обычным
    UNIQUE-индексом по (Cartridge, organization_id), а не PRIMARY KEY.

    В SQLite-версии это был составной PRIMARY KEY, и SQLite не требует
    NOT NULL на колонках составного PRIMARY KEY — там спокойно жили
    картриджи "без филиала" (organization_id IS NULL). PostgreSQL же,
    в соответствии со стандартом SQL, требует NOT NULL на каждой колонке
    PRIMARY KEY — с ним такие картриджи сохранить нельзя. Поэтому здесь
    используется обычный UNIQUE-индекс, который такую уникальность даёт,
    но не требует NOT NULL (и, как и обычный unique-индекс в SQLite,
    несколько NULL в organization_id уникальности не нарушают).
    """
    if not _table_exists(cursor, 'Analytics'):
        return

    if _pk_columns(cursor, 'analytics'):
        cursor.execute("ALTER TABLE Analytics DROP CONSTRAINT analytics_pkey")

    if not _column_exists(cursor, 'Analytics', 'organization_id'):
        cursor.execute("ALTER TABLE Analytics ADD COLUMN organization_id INTEGER")

    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_analytics_unique ON Analytics(Cartridge, organization_id)"
    )


def _migrate_equipment_status_vocabulary(cursor):
    """Перевести Equipment.status со старого словаря на новый единый.

    Раньше статусы были: В работе/Ремонт/На складе/Списано/Простаивает.
    Новый единый словарь для всего оборудования (компьютеры, мониторы, МФУ,
    периферия, комплектующие): Резерв/Установлено/Сломано/Ремонтируется/
    Списание/Списано/Нераспределено (на складе).

    Безопасно перезапускать на каждом старте: после первого прогона ни одна
    строка не содержит старых значений (единственное пересечение словарей —
    'Списано', которое в переносе не участвует, так как совпадает само с собой).
    """
    if not _table_exists(cursor, 'Equipment'):
        return

    remap = {
        'В работе': 'Установлено',
        'Ремонт': 'Ремонтируется',
        'На складе': 'Нераспределено (на складе)',
        'Простаивает': 'Резерв',
    }

    placeholders = ','.join(['%s'] * len(remap))
    cursor.execute(f"SELECT COUNT(*) FROM Equipment WHERE status IN ({placeholders})", list(remap.keys()))
    if cursor.fetchone()[0] == 0:
        return

    for old_status, new_status in remap.items():
        cursor.execute("UPDATE Equipment SET status = %s WHERE status = %s", (new_status, old_status))
    print("✅ Статусы оборудования перенесены на новый единый словарь")


def init_db():
    """Создать схему БД с нуля (для только что созданной, пустой PostgreSQL-базы)."""
    print("Создание схемы базы данных в PostgreSQL")
    config = get_db_config()
    conn = psycopg2.connect(config) if isinstance(config, str) else psycopg2.connect(**config)
    cursor = conn.cursor()

    # ========== ОРГАНИЗАЦИИ (создаём раньше остальных — на неё много ссылок) ==========
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Organizations (
            id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name TEXT NOT NULL,
            address TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS OrganizationAddresses (
            id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            organization_id INTEGER NOT NULL,
            address TEXT NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_org_addresses_org ON OrganizationAddresses(organization_id)")

    # ========== ПОЛЬЗОВАТЕЛИ ==========
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Users (
            id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT,
            role TEXT DEFAULT 'user',
            organization_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP,
            is_active INTEGER DEFAULT 1,
            can_delete_history INTEGER DEFAULT 0
        )
    """)

    # ========== ОТДЕЛЫ / КАБИНЕТЫ / СОТРУДНИКИ ==========
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Departments (
            id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name TEXT NOT NULL,
            office TEXT,
            organization_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            address_id INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS DepartmentOffices (
            id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            department_id INTEGER NOT NULL,
            office TEXT NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_department_offices_dept ON DepartmentOffices(department_id)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Rooms (
            id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            Number TEXT UNIQUE,
            department_id INTEGER
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Employees (
            id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            Department_Fullname TEXT UNIQUE,
            Organization_id INTEGER,
            department_id INTEGER
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_employees_department ON Employees(department_id)")

    # ========== КАРТРИДЖИ ==========
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Postavki (
            id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            Date_of_purchase DATE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS MFU (
            id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            Name_MFU TEXT UNIQUE,
            Status TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS CartridgeModels (
            id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            ModelName TEXT UNIQUE,
            Ip TEXT UNIQUE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Catrigs (
            id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
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
            organization_id INTEGER,
            address_id INTEGER
        )
    """)
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_catrigs_serial ON Catrigs(Serial_number)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_catrigs_status ON Catrigs(Status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_catrigs_ip ON Catrigs(Ip)')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_catrigs_created ON Catrigs(created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_catrigs_created_by ON Catrigs(created_by)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_catrigs_equipment ON Catrigs(equipment_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_catrigs_organization ON Catrigs(organization_id)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Analytics (
            Cartridge TEXT NOT NULL,
            ToWriteOff INTEGER DEFAULT 0,
            InStock INTEGER DEFAULT 0,
            OnBalance INTEGER DEFAULT 0,
            ToBuy INTEGER DEFAULT 0,
            organization_id INTEGER,
            address_id INTEGER
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_analytics_organization ON Analytics(organization_id)")
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_analytics_unique ON Analytics(Cartridge, organization_id)"
    )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Compatibility (
            id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            cartridge_model TEXT,
            mfu_model TEXT,
            organization_id INTEGER,
            UNIQUE(cartridge_model, mfu_model)
        )
    """)

    # ========== ОБОРУДОВАНИЕ ==========
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Equipment (
            id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
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
            scan_format TEXT,
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
            status TEXT DEFAULT 'Установлено',
            purchase_date DATE,
            warranty_until DATE,
            price DECIMAL(10,2),
            supplier TEXT,
            notes TEXT,
            parent_equipment_id INTEGER,
            network_name TEXT,
            manufacture_year INTEGER,
            photo TEXT,
            cable_type TEXT,
            characteristics TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by INTEGER,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_by INTEGER,
            address_id INTEGER
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_equipment_type ON Equipment(type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_equipment_serial ON Equipment(serial_number)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_equipment_inventory ON Equipment(inventory_number)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_equipment_status ON Equipment(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_equipment_organization ON Equipment(organization_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_equipment_responsible ON Equipment(responsible_employee)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_equipment_mol ON Equipment(mol_employee)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_equipment_room ON Equipment(room_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_equipment_parent ON Equipment(parent_equipment_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_equipment_address ON Equipment(address_id)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS EquipmentMovements (
            id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
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
            to_mol INTEGER
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_movements_equipment ON EquipmentMovements(equipment_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_movements_date ON EquipmentMovements(movement_date)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS PeripheralTypes (
            id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        )
    """)
    for name in ('Мышь', 'Клавиатура', 'ИБП', 'Внешний диск', 'Док-станция',
                 'Веб-камера', 'Гарнитура', 'Колонки'):
        cursor.execute("INSERT INTO PeripheralTypes (name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (name,))

    # ========== ЛИЦЕНЗИИ ==========
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Licenses (
            id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            product_name TEXT NOT NULL,
            product_key TEXT UNIQUE,
            expiry_date DATE,
            email TEXT,
            company TEXT,
            quantity INTEGER DEFAULT 0,
            used INTEGER DEFAULT 0,
            organization_id INTEGER,
            status TEXT DEFAULT 'Активна',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            address_id INTEGER
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_licenses_expiry ON Licenses(expiry_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_licenses_organization ON Licenses(organization_id)")

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_organizations_name ON Organizations(name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON Users(username)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_role ON Users(role)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_organization ON Users(organization_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rooms_department ON Rooms(department_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_departments_address ON Departments(address_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_analytics_address ON Analytics(address_id)")

    # Администратор по умолчанию
    default_password = hash_password("admin123")
    cursor.execute("""
        INSERT INTO Users (username, password_hash, full_name, role, is_active)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (username) DO NOTHING
    """, ("admin", default_password, "Главный администратор", "admin", 1))

    conn.commit()

    # Оборачиваем в CompatCursor, чтобы переиспользовать общие функции-миграции без дублирования.
    compat_cursor = conn.cursor(cursor_factory=CompatCursor)
    _migrate_analytics_pk(compat_cursor)
    _migrate_equipment_status_vocabulary(compat_cursor)
    conn.commit()

    conn.close()
    print("✅ База данных инициализирована")


def upgrade_db():
    """Догнать схему до актуальной версии на уже существующей PostgreSQL-базе.

    В отличие от SQLite, PostgreSQL сам поддерживает 'ADD COLUMN IF NOT EXISTS' —
    поэтому не нужен весь тот ручной "проверить PRAGMA, потом ALTER" ритуал,
    который был в SQLite-версии этого файла; миграция колонок сводится к
    идемпотентным ALTER TABLE ... ADD COLUMN IF NOT EXISTS.
    """
    conn = get_db()
    cursor = conn.cursor()

    equipment_columns = {
        'ram_type': 'TEXT', 'refresh_rate': 'INTEGER', 'panel_type': 'TEXT',
        'response_time': 'INTEGER', 'viewing_angle': 'TEXT', 'ports': 'TEXT',
        'network_type': 'TEXT', 'poe': 'TEXT', 'managed': 'TEXT', 'ip_address': 'TEXT',
        'print_type': 'TEXT', 'print_format': 'TEXT', 'print_speed': 'INTEGER',
        'color_type': 'TEXT', 'duplex': 'TEXT', 'printer_ports': 'TEXT',
        'scanner_resolution': 'TEXT', 'scanner_speed': 'TEXT', 'duplex_scanner': 'TEXT',
        'scan_format': 'TEXT', 'phone_number': 'TEXT', 'phone_ip': 'TEXT',
        'sip_account': 'TEXT', 'lines': 'INTEGER', 'phone_poe': 'TEXT',
        'ups_power': 'TEXT', 'ups_type': 'TEXT', 'ups_outlets': 'INTEGER',
        'ups_usb': 'TEXT', 'ups_runtime': 'INTEGER', 'connection_type': 'TEXT',
        'color': 'TEXT', 'characteristics': 'TEXT',
        'parent_equipment_id': 'INTEGER', 'network_name': 'TEXT',
        'manufacture_year': 'INTEGER', 'photo': 'TEXT', 'cable_type': 'TEXT',
        'address_id': 'INTEGER',
    }
    for col_name, col_type in equipment_columns.items():
        cursor.execute(f"ALTER TABLE Equipment ADD COLUMN IF NOT EXISTS {col_name} {col_type}")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_equipment_parent ON Equipment(parent_equipment_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_equipment_address ON Equipment(address_id)")

    for col_name, col_type in {
        'status': "TEXT DEFAULT 'Активна'", 'organization_id': 'INTEGER',
        'created_at': 'TIMESTAMP', 'updated_at': 'TIMESTAMP', 'address_id': 'INTEGER',
    }.items():
        cursor.execute(f"ALTER TABLE Licenses ADD COLUMN IF NOT EXISTS {col_name} {col_type}")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_licenses_organization ON Licenses(organization_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_licenses_address ON Licenses(address_id)")

    for col_name, col_type in {
        'organization_id': 'INTEGER', 'equipment_id': 'INTEGER', 'address_id': 'INTEGER',
    }.items():
        cursor.execute(f'ALTER TABLE Catrigs ADD COLUMN IF NOT EXISTS {col_name} {col_type}')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_catrigs_organization ON Catrigs(organization_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_catrigs_equipment ON Catrigs(equipment_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_catrigs_address ON Catrigs(address_id)")

    cursor.execute("ALTER TABLE Analytics ADD COLUMN IF NOT EXISTS organization_id INTEGER")
    cursor.execute("ALTER TABLE Analytics ADD COLUMN IF NOT EXISTS address_id INTEGER")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_analytics_organization ON Analytics(organization_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_analytics_address ON Analytics(address_id)")

    cursor.execute("ALTER TABLE Compatibility ADD COLUMN IF NOT EXISTS organization_id INTEGER")

    cursor.execute("ALTER TABLE Departments ADD COLUMN IF NOT EXISTS office TEXT")
    cursor.execute("ALTER TABLE Departments ADD COLUMN IF NOT EXISTS address_id INTEGER")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_departments_address ON Departments(address_id)")

    cursor.execute("ALTER TABLE Rooms ADD COLUMN IF NOT EXISTS department_id INTEGER")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rooms_department ON Rooms(department_id)")

    cursor.execute("ALTER TABLE Employees ADD COLUMN IF NOT EXISTS department_id INTEGER")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_employees_department ON Employees(department_id)")

    cursor.execute("ALTER TABLE Users ADD COLUMN IF NOT EXISTS can_delete_history INTEGER DEFAULT 0")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS DepartmentOffices (
            id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            department_id INTEGER NOT NULL,
            office TEXT NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_department_offices_dept ON DepartmentOffices(department_id)")

    try:
        _migrate_analytics_pk(cursor)
    except Exception as e:
        print(f"⚠️ Ошибка миграции ключа Analytics: {e}")

    try:
        _migrate_equipment_status_vocabulary(cursor)
    except Exception as e:
        print(f"⚠️ Ошибка миграции статусов Equipment: {e}")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
