"""
Production-запуск приложения через waitress.

Использование:
    python server.py

Переменные окружения (можно задать в systemd через EnvironmentFile=/etc/uchet.env):
    SECRET_KEY      - постоянный секретный ключ (обязательно)
    DATABASE_PATH   - путь к файлу БД вне каталога с кодом
    HOST            - интерфейс (по умолчанию 0.0.0.0)
    PORT            - порт (по умолчанию 5000)
    THREADS         - число рабочих потоков waitress (по умолчанию 8)
"""
import os
from waitress import serve
from app import app

if __name__ == '__main__':
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', '5000'))
    threads = int(os.environ.get('THREADS', '8'))

    if app.config['SECRET_KEY'] == 'your-secret-key-here':
        print('ВНИМАНИЕ: используется дефолтный SECRET_KEY. '
              'Задайте переменную окружения SECRET_KEY, иначе сессии '
              'будут сбрасываться при перезапуске.')

    print(f'Запуск uchet на http://{host}:{port} (threads={threads})')
    serve(app, host=host, port=port, threads=threads)
