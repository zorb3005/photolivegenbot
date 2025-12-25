import os
from dotenv import load_dotenv

load_dotenv()

# Обязательные настройки YooKassa
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID", "")
YOOKASSA_API_KEY = os.getenv("YOOKASSA_API_KEY", "")

# Публичный базовый URL бэкенда (для return_url и вебхуков)
BASE_PUBLIC_URL = os.getenv("BASE_PUBLIC_URL", "https://example.com")
