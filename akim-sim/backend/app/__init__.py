"""Пакет приложения.

Здесь единственная задача — подхватить .env из корня проекта до того, как
любой модуль прочитает os.environ. Без этого локальный запуск (`uvicorn`,
`make dev-back`) не видел ключ LLM и молча уходил в шаблонный режим: .env
читал только Docker через env_file в compose.

override=False принципиально: переменные, заданные в окружении вручную,
сильнее файла — на это опираются тесты, которые ставят LLM_PROVIDER=none.
"""
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv не установлен — работаем только на окружении
    pass
else:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
