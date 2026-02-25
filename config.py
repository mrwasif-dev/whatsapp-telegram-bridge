import os
from dotenv import load_dotenv

load_dotenv()

# ٹیلیگرام کنفیگریشن
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')

# مونگو ڈی بی کنفیگریشن
MONGODB_URI = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/')
DB_NAME = 'whatsapp_bot'
COLLECTION_NAME = 'sessions'

# واٹس ایپ کنفیگریشن
DEFAULT_TARGET = os.getenv('DEFAULT_TARGET', '')  # مثلاً 923001234567

# ایڈمن آئی ڈیز (کاما سے الگ کریں)
ADMIN_IDS = os.getenv('ADMIN_IDS', '').split(',') if os.getenv('ADMIN_IDS') else []

# پورٹ نمبر
PORT = int(os.getenv('PORT', 5000))
