"""
Одноразовый перенос данных из существующей SQLite-базы (db.db) в PostgreSQL.

Перед запуском схема в PostgreSQL уже должна существовать — она создаётся
автоматически при первом старте app.py с переменной DATABASE_URL,
указывающей на PostgreSQL (init_db()/upgrade_db() вызываются при импорте
database.py).

Использование:
    python migrate_data_to_postgres.py [путь-к-sqlite-файлу]

Если путь не указан, используется db.db в текущей папке. Целевая
PostgreSQL берётся из тех же переменных окружения, что и у app.py
(DATABASE_URL либо PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD).

ВАЖНО: не запускайте этот скрипт на "живом" db.db, пока с ним работает
запущенное приложение — сначала сделайте копию файла.

Скрипт безопасно перезапускать на пустую PostgreSQL-базу. Если в целевой
таблице уже есть строки, она пропускается с предупреждением (чтобы не
создать задвоенные записи) — перед повторным запуском либо очистите
таблицы в PostgreSQL, либо используйте новую пустую базу.
"""
import sys
import sqlite3

import psycopg2

from database import get_db_config

TABLES_IN_ORDER = [
    'Organizations',
    'OrganizationAddresses',
    'Users',
    'Departments',
    'DepartmentOffices',
    'Rooms',
    'Employees',
    'Postavki',
    'MFU',
    'CartridgeModels',
    'Equipment',
    'Catrigs',
    'EquipmentMovements',
    'Analytics',
    'Compatibility',
    'PeripheralTypes',
    'Licenses',
]


def connect_postgres():
    config = get_db_config()
    if isinstance(config, str):
        return psycopg2.connect(config)
    return psycopg2.connect(**config)


def get_sqlite_columns(sconn, table):
    cur = sconn.execute('PRAGMA table_info("{}")'.format(table))
    return [row[1] for row in cur.fetchall()]


def get_pg_columns(pconn, table):
    cur = pconn.cursor()
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
        (table.lower(),)
    )
    return {row[0] for row in cur.fetchall()}


def migrate_table(sconn, pconn, table):
    # Таблицы/колонки в PostgreSQL создаются БЕЗ кавычек (database.py), поэтому
    # Postgres сворачивает их имена в нижний регистр — на стороне PostgreSQL
    # идентификаторы здесь тоже не квотируются, иначе "Organizations" не
    # совпадёт с фактически созданной organizations. На стороне SQLite имена
    # регистрозависимы и хранятся как есть — там кавычки нужны и сохраняются.
    sqlite_cols = get_sqlite_columns(sconn, table)
    if not sqlite_cols:
        print('  [{}] таблицы нет в SQLite, пропуск'.format(table))
        return 0

    pcur = pconn.cursor()
    pcur.execute('SELECT COUNT(*) FROM {}'.format(table))
    if pcur.fetchone()[0] > 0:
        print('  [{}] в PostgreSQL уже есть данные, пропуск (во избежание дублей)'.format(table))
        return 0

    pg_cols = get_pg_columns(pconn, table)
    cols = [c for c in sqlite_cols if c.lower() in pg_cols]
    skipped_cols = [c for c in sqlite_cols if c.lower() not in pg_cols]
    if skipped_cols:
        print('  [{}] колонок нет в PostgreSQL, будут пропущены: {}'.format(table, skipped_cols))

    sqlite_quoted_cols = ', '.join('"{}"'.format(c) for c in cols)
    select_sql = 'SELECT {} FROM "{}"'.format(sqlite_quoted_cols, table)
    rows = sconn.execute(select_sql).fetchall()

    if not rows:
        print('  [{}] пустая таблица, 0 строк'.format(table))
        return 0

    pg_cols_list = ', '.join(cols)
    has_id = 'id' in [c.lower() for c in cols]
    overriding = ' OVERRIDING SYSTEM VALUE' if has_id else ''
    placeholders = ', '.join(['%s'] * len(cols))
    insert_sql = 'INSERT INTO {} ({}){} VALUES ({})'.format(table, pg_cols_list, overriding, placeholders)

    pcur.executemany(insert_sql, [tuple(row) for row in rows])

    if has_id:
        pcur.execute('SELECT COALESCE(MAX(id), 1) FROM {}'.format(table))
        max_id = pcur.fetchone()[0]
        pcur.execute("SELECT setval(pg_get_serial_sequence(%s, 'id'), %s)", (table.lower(), max_id))

    pconn.commit()
    print('  [{}] перенесено строк: {}'.format(table, len(rows)))
    return len(rows)


def _clear_default_seed_data(pconn):
    """init_db() всегда создаёт дефолтного пользователя admin и стандартный
    набор PeripheralTypes — даже в только что созданной "пустой" базе.
    Из-за этого migrate_table() решил бы, что Users/PeripheralTypes уже
    заполнены, и пропустил бы перенос настоящих данных из SQLite. Убираем
    только точно совпадающие дефолтные записи — реальные данные, если они
    почему-то уже есть, не трогаем.
    """
    pcur = pconn.cursor()
    pcur.execute("DELETE FROM users WHERE username = 'admin' AND full_name = 'Главный администратор'")
    pcur.execute("""
        DELETE FROM peripheraltypes WHERE name IN (
            'Мышь', 'Клавиатура', 'ИБП', 'Внешний диск',
            'Док-станция', 'Веб-камера', 'Гарнитура', 'Колонки'
        )
    """)
    pconn.commit()


def main():
    sqlite_path = sys.argv[1] if len(sys.argv) > 1 else 'db.db'
    print('Источник (SQLite): {}'.format(sqlite_path))

    sconn = sqlite3.connect(sqlite_path)
    sconn.row_factory = sqlite3.Row

    pconn = connect_postgres()
    _clear_default_seed_data(pconn)

    print('Перенос данных...')
    total = 0
    for table in TABLES_IN_ORDER:
        try:
            total += migrate_table(sconn, pconn, table)
        except Exception as e:
            pconn.rollback()
            print('  [{}] ОШИБКА: {}'.format(table, e))

    print('\nГотово. Всего строк перенесено: {}'.format(total))

    print('\nСверка количества строк источник -> приёмник:')
    all_ok = True
    for table in TABLES_IN_ORDER:
        scur = sconn.execute('SELECT COUNT(*) FROM "{}"'.format(table))
        src_count = scur.fetchone()[0]
        pcur = pconn.cursor()
        pcur.execute('SELECT COUNT(*) FROM {}'.format(table))
        dst_count = pcur.fetchone()[0]
        status = 'OK' if src_count == dst_count else 'РАСХОЖДЕНИЕ'
        if src_count != dst_count:
            all_ok = False
        print('  {}: SQLite={} PostgreSQL={} [{}]'.format(table, src_count, dst_count, status))

    sconn.close()
    pconn.close()

    if not all_ok:
        print('\nВНИМАНИЕ: есть расхождения в количестве строк — см. вывод выше.')
        sys.exit(1)
    print('\nВсе таблицы совпадают по количеству строк.')


if __name__ == '__main__':
    main()
