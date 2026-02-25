import os
import sys
import time
import qrcode
import threading
import base64
from io import BytesIO
from datetime import datetime
from flask import Flask, render_template, send_file, jsonify
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from pymongo import MongoClient
from dotenv import load_dotenv

# Selenium imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

load_dotenv()

# ==================== CONFIG ====================
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
MONGODB_URI = os.getenv('MONGODB_URI')
PORT = int(os.getenv('PORT', 5000))
DEFAULT_TARGET = os.getenv('DEFAULT_TARGET', '')

if not TELEGRAM_BOT_TOKEN:
    print("❌ TELEGRAM_BOT_TOKEN not set")
    sys.exit(1)

if not MONGODB_URI:
    print("❌ MONGODB_URI not set")
    sys.exit(1)

# ==================== DATABASE ====================
class Database:
    def __init__(self):
        self.client = MongoClient(MONGODB_URI)
        self.db = self.client['whatsapp_bot']
        self.settings = self.db['settings']
        print("✅ MongoDB Connected")

    def save_qr(self, qr_data):
        self.settings.update_one(
            {'key': 'qr_code'},
            {'$set': {'value': qr_data, 'timestamp': datetime.now()}},
            upsert=True
        )

    def get_qr(self):
        data = self.settings.find_one({'key': 'qr_code'})
        return data.get('value') if data else None

    def save_target(self, target):
        self.settings.update_one(
            {'key': 'target'},
            {'$set': {'value': target, 'updated': datetime.now()}},
            upsert=True
        )

    def get_target(self):
        data = self.settings.find_one({'key': 'target'})
        return data.get('value') if data else DEFAULT_TARGET

    def save_auth(self, status):
        self.settings.update_one(
            {'key': 'auth'},
            {'$set': {'value': status, 'updated': datetime.now()}},
            upsert=True
        )

    def get_auth(self):
        data = self.settings.find_one({'key': 'auth'})
        return data.get('value') if data else False

    def save_session(self, session_data):
        self.settings.update_one(
            {'key': 'session'},
            {'$set': {'value': session_data, 'updated': datetime.now()}},
            upsert=True
        )

    def get_session(self):
        data = self.settings.find_one({'key': 'session'})
        return data.get('value') if data else None

# ==================== WHATSAPP CONTROLLER ====================
class WhatsAppController:
    def __init__(self, db):
        self.db = db
        self.driver = None
        self.is_connected = False
        self.qr_ready = False

    def start_driver(self):
        """Start Chrome driver"""
        try:
            options = Options()
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--window-size=1920,1080')
            options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            
            # Heroku ke liye
            if 'DYNO' in os.environ:
                options.binary_location = os.environ.get('GOOGLE_CHROME_BIN', '/app/.apt/usr/bin/google-chrome')
                service = Service(executable_path=os.environ.get('CHROMEDRIVER_PATH', '/app/.chromedriver/bin/chromedriver'))
            else:
                service = Service(ChromeDriverManager().install())
            
            self.driver = webdriver.Chrome(service=service, options=options)
            return True
        except Exception as e:
            print(f"❌ Driver error: {e}")
            return False

    def get_qr(self):
        """Get WhatsApp QR code"""
        try:
            if not self.driver:
                if not self.start_driver():
                    return None
            
            self.driver.get('https://web.whatsapp.com')
            time.sleep(5)
            
            # Wait for QR code
            wait = WebDriverWait(self.driver, 30)
            qr_element = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'div[data-ref]'))
            )
            
            qr_ref = qr_element.get_attribute('data-ref')
            if qr_ref:
                # Generate QR image
                qr = qrcode.QRCode(version=1, box_size=10, border=5)
                qr.add_data(qr_ref)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                
                buffered = BytesIO()
                img.save(buffered, format="PNG")
                img_base64 = base64.b64encode(buffered.getvalue()).decode()
                
                self.db.save_qr(img_base64)
                self.qr_ready = True
                
                # Start login checker
                threading.Thread(target=self.check_login, daemon=True).start()
                
                return img_base64
        except Exception as e:
            print(f"❌ QR error: {e}")
            return None

    def check_login(self):
        """Check if user scanned QR"""
        try:
            print("⏳ Waiting for QR scan...")
            wait = WebDriverWait(self.driver, 120)
            
            # Wait for search box (login successful)
            wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'div[contenteditable="true"][title="Search input textbox"]'))
            )
            
            self.is_connected = True
            self.db.save_auth(True)
            print("✅ WhatsApp Connected!")
            
        except Exception as e:
            print(f"❌ Login timeout: {e}")
            self.is_connected = False

    def send_message(self, to_number, message):
        """Send message"""
        if not self.is_connected:
            return False
        try:
            # Search for contact
            search = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'div[contenteditable="true"][title="Search input textbox"]'))
            )
            search.clear()
            search.send_keys(to_number)
            time.sleep(2)
            search.send_keys(Keys.ENTER)
            time.sleep(2)
            
            # Type and send message
            msg = self.driver.find_element(By.CSS_SELECTOR, 'div[contenteditable="true"][title="Type a message"]')
            msg.send_keys(message)
            msg.send_keys(Keys.ENTER)
            return True
        except Exception as e:
            print(f"❌ Send error: {e}")
            return False

# ==================== FLASK WEB ====================
app = Flask(__name__)
db = Database()
wa = WhatsAppController(db)

@app.route('/')
def home():
    return render_template('qr.html')

@app.route('/qr')
def get_qr():
    qr = db.get_qr()
    if qr:
        qr_data = base64.b64decode(qr)
        return send_file(BytesIO(qr_data), mimetype='image/png')
    return "QR not ready", 404

@app.route('/qr-base64')
def get_qr_base64():
    qr = db.get_qr()
    return jsonify({'qr': qr})

@app.route('/status')
def get_status():
    return jsonify({
        'connected': wa.is_connected,
        'qr_ready': wa.qr_ready,
        'auth': db.get_auth()
    })

# ==================== TELEGRAM BOT ====================
class TelegramBot:
    def __init__(self, token, wa, db):
        self.wa = wa
        self.db = db
        self.app = Application.builder().token(token).build()
        self.setup_handlers()

    def setup_handlers(self):
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("help", self.cmd_help))
        self.app.add_handler(CommandHandler("settarget", self.cmd_settarget))
        self.app.add_handler(CommandHandler("gettarget", self.cmd_gettarget))
        self.app.add_handler(CommandHandler("qr", self.cmd_qr))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("ping", self.cmd_ping))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))

    async def cmd_start(self, update: Update, context):
        await update.message.reply_text(
            "🤖 *WhatsApp Bridge Bot*\n\n"
            "Commands:\n"
            "• /settarget 923001234567 - Set WhatsApp number\n"
            "• /qr - Get WhatsApp QR code\n"
            "• /status - Check connection\n"
            "• /help - More commands",
            parse_mode='Markdown'
        )

    async def cmd_help(self, update: Update, context):
        await update.message.reply_text(
            "📚 *How to Use:*\n\n"
            "1. Set target number:\n"
            "   /settarget 923001234567\n\n"
            "2. Get QR code:\n"
            "   /qr\n\n"
            "3. Scan QR with WhatsApp Web\n\n"
            "4. Check connection:\n"
            "   /status\n\n"
            "5. Send any message to forward"
        )

    async def cmd_settarget(self, update: Update, context):
        if not context.args:
            await update.message.reply_text("Usage: /settarget 923001234567")
            return
        target = context.args[0]
        if not target.isdigit() or len(target) < 10:
            await update.message.reply_text("❌ Invalid number. Use format: 923001234567")
            return
        self.db.save_target(target)
        await update.message.reply_text(f"✅ Target set to: +{target}")

    async def cmd_gettarget(self, update: Update, context):
        target = self.db.get_target()
        if target:
            await update.message.reply_text(f"📱 Current target: +{target}")
        else:
            await update.message.reply_text("⚠️ No target set")

    async def cmd_qr(self, update: Update, context):
        await update.message.reply_text("⏳ Generating WhatsApp QR code...")
        qr = self.wa.get_qr()
        if qr:
            qr_data = base64.b64decode(qr)
            await update.message.reply_photo(
                photo=BytesIO(qr_data),
                caption="📱 Scan this QR with WhatsApp Web\nBot will notify when connected"
            )
        else:
            await update.message.reply_text("❌ Failed to generate QR")

    async def cmd_status(self, update: Update, context):
        status = "✅ Connected" if self.wa.is_connected else "❌ Disconnected"
        await update.message.reply_text(f"WhatsApp: {status}")

    async def cmd_ping(self, update: Update, context):
        await update.message.reply_text("🏓 Pong!")

    async def handle_text(self, update: Update, context):
        if not self.wa.is_connected:
            await update.message.reply_text("❌ WhatsApp not connected. Use /qr first")
            return
        
        target = self.db.get_target()
        if not target:
            await update.message.reply_text("❌ No target set. Use /settarget")
            return
        
        success = self.wa.send_message(target, update.message.text)
        if success:
            await update.message.reply_text("✅ Message forwarded to WhatsApp")
        else:
            await update.message.reply_text("❌ Failed to send message")

    def run(self):
        self.app.run_polling()

# ==================== MAIN ====================
if __name__ == '__main__':
    print("🚀 Starting WhatsApp Bridge Bot...")
    
    if 'DYNO' in os.environ:  # Heroku
        dyno = os.environ.get('DYNO', '').split('.')[0]
        if dyno == 'web':
            print("🌐 Starting web server...")
            app.run(host='0.0.0.0', port=PORT)
        else:
            print("🤖 Starting telegram bot...")
            bot = TelegramBot(TELEGRAM_BOT_TOKEN, wa, db)
            bot.run()
    else:  # Local
        print("💻 Running in local mode")
        
        def run_flask():
            app.run(host='0.0.0.0', port=PORT, debug=False)
        
        flask_thread = threading.Thread(target=run_flask)
        flask_thread.daemon = True
        flask_thread.start()
        
        bot = TelegramBot(TELEGRAM_BOT_TOKEN, wa, db)
        bot.run()
