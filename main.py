import os
import sys
import time
import json
import qrcode
import threading
import requests
import base64
import chromedriver_autoinstaller
from io import BytesIO
from datetime import datetime
from flask import Flask, render_template, send_file, jsonify
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ============================================
# Configuration
# ============================================
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
MONGODB_URI = os.getenv('MONGODB_URI')
DB_NAME = os.getenv('DB_NAME', 'whatsapp_bot')
PORT = int(os.getenv('PORT', 5000))
ADMIN_IDS = os.getenv('ADMIN_IDS', '').split(',') if os.getenv('ADMIN_IDS') else []
DEFAULT_TARGET = os.getenv('DEFAULT_TARGET', '')

if not TELEGRAM_BOT_TOKEN:
    print("❌ TELEGRAM_BOT_TOKEN not set")
    sys.exit(1)

if not MONGODB_URI:
    print("❌ MONGODB_URI not set")
    sys.exit(1)

# ============================================
# MongoDB Setup - FIXED
# ============================================
class Database:
    def __init__(self):
        self.client = None
        self.db = None
        self.settings = None
        self.connect()
    
    def connect(self):
        """Connect to MongoDB"""
        try:
            self.client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
            self.client.admin.command('ping')
            self.db = self.client[DB_NAME]
            self.settings = self.db['settings']
            print("✅ MongoDB Connected")
            return True
        except Exception as e:
            print(f"❌ MongoDB Connection Failed: {e}")
            return False
    
    def save_qr(self, qr_data):
        """Save QR code"""
        try:
            if not self.settings:
                self.connect()
            self.settings.update_one(
                {'key': 'qr_code'},
                {'$set': {'value': qr_data, 'timestamp': datetime.now()}},
                upsert=True
            )
            return True
        except Exception as e:
            print(f"❌ Failed to save QR: {e}")
            return False
    
    def get_qr(self):
        """Get QR code"""
        try:
            if not self.settings:
                self.connect()
            setting = self.settings.find_one({'key': 'qr_code'})
            return setting.get('value') if setting else None
        except Exception as e:
            print(f"❌ Failed to get QR: {e}")
            return None
    
    def save_target(self, target_number):
        """Save target number"""
        try:
            if not self.settings:
                self.connect()
            self.settings.update_one(
                {'key': 'target_number'},
                {'$set': {'value': target_number, 'updated_at': datetime.now()}},
                upsert=True
            )
            return True
        except Exception as e:
            print(f"❌ Failed to save target: {e}")
            return False
    
    def get_target(self):
        """Get target number"""
        try:
            if not self.settings:
                self.connect()
            setting = self.settings.find_one({'key': 'target_number'})
            return setting.get('value') if setting else DEFAULT_TARGET
        except Exception as e:
            print(f"❌ Failed to get target: {e}")
            return DEFAULT_TARGET
    
    def save_auth_state(self, state):
        """Save auth state"""
        try:
            if not self.settings:
                self.connect()
            self.settings.update_one(
                {'key': 'auth_state'},
                {'$set': {'value': state, 'updated_at': datetime.now()}},
                upsert=True
            )
            return True
        except Exception as e:
            print(f"❌ Failed to save auth state: {e}")
            return False
    
    def get_auth_state(self):
        """Get auth state"""
        try:
            if not self.settings:
                self.connect()
            setting = self.settings.find_one({'key': 'auth_state'})
            return setting.get('value') if setting else False
        except Exception as e:
            print(f"❌ Failed to get auth state: {e}")
            return False

# ============================================
# WhatsApp Controller
# ============================================
class WhatsAppController:
    def __init__(self, db):
        self.db = db
        self.driver = None
        self.is_ready = False
        self.qr_generated = False
        self.target_number = db.get_target()
    
    def setup_chrome(self):
        """Setup Chrome for Heroku"""
        chromedriver_autoinstaller.install()
        options = Options()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.binary_location = os.environ.get('GOOGLE_CHROME_BIN', '/app/.apt/usr/bin/google-chrome')
        
        service = Service(executable_path=os.environ.get('CHROMEDRIVER_PATH', '/app/.chromedriver/bin/chromedriver'))
        self.driver = webdriver.Chrome(service=service, options=options)
        return True
    
    def start(self):
        """Start WhatsApp Web"""
        try:
            self.setup_chrome()
            self.driver.get('https://web.whatsapp.com')
            print("✅ WhatsApp Web loaded")
            return True
        except Exception as e:
            print(f"❌ Failed to start: {e}")
            return False
    
    def get_qr(self):
        """Get and save QR code"""
        try:
            wait = WebDriverWait(self.driver, 30)
            qr_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div[data-ref]')))
            qr_data = qr_element.get_attribute('data-ref')
            
            if qr_data:
                qr = qrcode.QRCode(version=1, box_size=10, border=5)
                qr.add_data(qr_data)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                
                buffered = BytesIO()
                img.save(buffered, format="PNG")
                img_base64 = base64.b64encode(buffered.getvalue()).decode()
                
                self.db.save_qr(img_base64)
                self.qr_generated = True
                print("✅ QR code saved")
                return img_base64
        except Exception as e:
            print(f"❌ QR generation error: {e}")
            return None
    
    def wait_for_login(self):
        """Wait for WhatsApp login"""
        try:
            wait = WebDriverWait(self.driver, 120)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div[contenteditable="true"][title="Search input textbox"]')))
            self.is_ready = True
            self.db.save_auth_state(True)
            print("✅ WhatsApp logged in")
            return True
        except Exception as e:
            print(f"❌ Login failed: {e}")
            return False
    
    def send_message(self, text):
        """Send message"""
        if not self.is_ready or not self.target_number:
            return False
        try:
            search = self.driver.find_element(By.CSS_SELECTOR, 'div[contenteditable="true"][title="Search input textbox"]')
            search.clear()
            search.send_keys(self.target_number)
            time.sleep(2)
            search.send_keys(Keys.ENTER)
            time.sleep(2)
            
            msg = self.driver.find_element(By.CSS_SELECTOR, 'div[contenteditable="true"][title="Type a message"]')
            msg.send_keys(text)
            msg.send_keys(Keys.ENTER)
            return True
        except:
            return False

# ============================================
# Flask Web Server
# ============================================
app = Flask(__name__)
whatsapp = None
db = None

@app.route('/')
def home():
    return render_template('qr.html')

@app.route('/qr')
def get_qr():
    """Get QR code image"""
    qr_base64 = db.get_qr()
    if qr_base64:
        qr_data = base64.b64decode(qr_base64)
        return send_file(BytesIO(qr_data), mimetype='image/png')
    return jsonify({'error': 'No QR'}), 404

@app.route('/qr-base64')
def get_qr_base64():
    """Get QR as base64"""
    qr_base64 = db.get_qr()
    if qr_base64:
        return jsonify({'qr': qr_base64})
    return jsonify({'error': 'No QR'}), 404

@app.route('/status')
def status():
    """Get status"""
    return jsonify({
        'connected': whatsapp.is_ready if whatsapp else False,
        'target': whatsapp.target_number if whatsapp else None,
        'authenticated': db.get_auth_state() if db else False
    })

# ============================================
# Telegram Bot
# ============================================
class TelegramBot:
    def __init__(self, token, whatsapp_ctrl, database):
        self.token = token
        self.whatsapp = whatsapp_ctrl
        self.db = database
        self.app = Application.builder().token(token).build()
        self.setup_handlers()
    
    def setup_handlers(self):
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("help", self.help))
        self.app.add_handler(CommandHandler("settarget", self.settarget))
        self.app.add_handler(CommandHandler("gettarget", self.gettarget))
        self.app.add_handler(CommandHandler("status", self.status))
        self.app.add_handler(CommandHandler("qr", self.qr))
        self.app.add_handler(CommandHandler("ping", self.ping))
        self.app.add_handler(MessageHandler(filters.ALL, self.handle_message))
    
    async def start(self, update: Update, context):
        await update.message.reply_text(
            "🤖 Telegram-WhatsApp Bridge Bot\n\n"
            "Commands:\n"
            "/help - Show help\n"
            "/settarget [number] - Set WhatsApp target\n"
            "/gettarget - Show current target\n"
            "/status - Check connection\n"
            "/qr - Get QR code"
        )
    
    async def help(self, update: Update, context):
        await update.message.reply_text(
            "📚 Help\n\n"
            "1. Set target: /settarget 923001234567\n"
            "2. Get QR: /qr\n"
            "3. Scan QR with WhatsApp\n"
            "4. Send any media to forward"
        )
    
    async def settarget(self, update: Update, context):
        try:
            args = context.args
            if not args:
                await update.message.reply_text("Usage: /settarget 923001234567")
                return
            target = args[0]
            self.db.save_target(target)
            self.whatsapp.target_number = target
            await update.message.reply_text(f"✅ Target set: +{target}")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")
    
    async def gettarget(self, update: Update, context):
        target = self.db.get_target()
        if target:
            await update.message.reply_text(f"📱 Target: +{target}")
        else:
            await update.message.reply_text("⚠️ No target set")
    
    async def status(self, update: Update, context):
        status = "✅ Connected" if self.whatsapp.is_ready else "❌ Disconnected"
        await update.message.reply_text(f"WhatsApp: {status}")
    
    async def qr(self, update: Update, context):
        qr_base64 = self.db.get_qr()
        if qr_base64:
            qr_data = base64.b64decode(qr_base64)
            await update.message.reply_photo(photo=BytesIO(qr_data), caption="Scan with WhatsApp")
        else:
            await update.message.reply_text("⏳ QR not ready yet, try again in 30 seconds")
    
    async def ping(self, update: Update, context):
        await update.message.reply_text("🏓 Pong!")
    
    async def handle_message(self, update: Update, context):
        if not self.whatsapp.is_ready:
            await update.message.reply_text("❌ WhatsApp not connected")
            return
        
        if not self.db.get_target():
            await update.message.reply_text("⚠️ No target set")
            return
        
        if update.message.text and not update.message.text.startswith('/'):
            success = self.whatsapp.send_message(update.message.text)
            await update.message.reply_text("✅ Sent" if success else "❌ Failed")
    
    def run(self):
        self.app.run_polling()

# ============================================
# Background Worker
# ============================================
def whatsapp_worker():
    """WhatsApp background worker"""
    global whatsapp, db
    print("📱 Starting WhatsApp worker...")
    
    whatsapp = WhatsAppController(db)
    if not whatsapp.start():
        print("❌ Failed to start WhatsApp")
        return
    
    # Generate QR
    for i in range(30):  # Try for 5 minutes
        qr = whatsapp.get_qr()
        if qr:
            print("✅ QR generated")
            break
        time.sleep(10)
    
    # Wait for login
    if whatsapp.wait_for_login():
        print("✅ WhatsApp ready")
        while True:
            time.sleep(60)
    else:
        print("❌ Login timeout")

def start_worker():
    thread = threading.Thread(target=whatsapp_worker)
    thread.daemon = True
    thread.start()

# ============================================
# Main
# ============================================
if __name__ == '__main__':
    print("🚀 Starting Bot...")
    
    # Initialize database
    db = Database()
    
    if 'DYNO' in os.environ:
        dyno_type = os.environ.get('DYNO', '').split('.')[0]
        if dyno_type == 'web':
            print("🌐 Starting web server...")
            whatsapp = WhatsAppController(db)
            start_worker()
            app.run(host='0.0.0.0', port=PORT)
        else:
            print("🤖 Starting worker...")
            whatsapp = WhatsAppController(db)
            start_worker()
            bot = TelegramBot(TELEGRAM_BOT_TOKEN, whatsapp, db)
            bot.run()
    else:
        print("💻 Local mode")
        whatsapp = WhatsAppController(db)
        start_worker()
        
        def run_flask():
            app.run(host='0.0.0.0', port=PORT, debug=False)
        
        flask_thread = threading.Thread(target=run_flask)
        flask_thread.daemon = True
        flask_thread.start()
        
        bot = TelegramBot(TELEGRAM_BOT_TOKEN, whatsapp, db)
        bot.run()
