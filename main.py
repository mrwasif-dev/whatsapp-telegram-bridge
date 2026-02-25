import os
import sys
import time
import qrcode
import threading
import base64
from io import BytesIO
from datetime import datetime
from flask import Flask, render_template, send_file, jsonify, request
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
ADMIN_IDS = os.getenv('ADMIN_IDS', '').split(',') if os.getenv('ADMIN_IDS') else []
DEFAULT_TARGET = os.getenv('DEFAULT_TARGET', '')

# ==================== DATABASE ====================
class Database:
    def __init__(self):
        try:
            self.client = MongoClient(MONGODB_URI)
            self.db = self.client['whatsapp_bot']
            self.settings = self.db['settings']
            print("✅ MongoDB Connected")
        except Exception as e:
            print(f"❌ MongoDB Error: {e}")
            sys.exit(1)

    def save_qr(self, qr_data):
        self.settings.update_one(
            {'key': 'qr_code'},
            {'$set': {'value': qr_data, 'timestamp': datetime.now()}},
            upsert=True
        )

    def get_qr(self):
        data = self.settings.find_one({'key': 'qr_code'})
        return data.get('value') if data else None

    def save_target(self, user_id, target):
        self.settings.update_one(
            {'user_id': user_id, 'key': 'target'},
            {'$set': {'value': target, 'updated': datetime.now()}},
            upsert=True
        )

    def get_target(self, user_id):
        data = self.settings.find_one({'user_id': user_id, 'key': 'target'})
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

# ==================== REAL WHATSAPP CONTROLLER ====================
class WhatsAppController:
    def __init__(self, db):
        self.db = db
        self.driver = None
        self.is_connected = False
        self.target_number = None
        self.setup_driver()

    def setup_driver(self):
        """Setup Chrome driver for WhatsApp Web"""
        try:
            options = Options()
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--window-size=1920,1080')
            
            # Load saved session if exists
            session = self.db.get_session()
            if session:
                options.add_argument(f'user-data-dir={session}')
            
            self.driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()),
                options=options
            )
            print("✅ Chrome driver initialized")
            return True
        except Exception as e:
            print(f"❌ Chrome driver error: {e}")
            return False

    def get_qr(self):
        """Get real WhatsApp Web QR code"""
        try:
            if not self.driver:
                self.setup_driver()
            
            self.driver.get('https://web.whatsapp.com')
            time.sleep(5)
            
            # Wait for QR code
            wait = WebDriverWait(self.driver, 30)
            qr_element = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'div[data-ref]'))
            )
            
            qr_data = qr_element.get_attribute('data-ref')
            
            if qr_data:
                # Generate QR image
                qr = qrcode.QRCode(version=1, box_size=10, border=5)
                qr.add_data(qr_data)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                
                buffered = BytesIO()
                img.save(buffered, format="PNG")
                img_base64 = base64.b64encode(buffered.getvalue()).decode()
                
                # Save to database
                self.db.save_qr(img_base64)
                
                # Start login checker in background
                threading.Thread(target=self.wait_for_login, daemon=True).start()
                
                return img_base64
            return None
        except Exception as e:
            print(f"❌ QR error: {e}")
            return None

    def wait_for_login(self):
        """Wait for user to scan QR and login"""
        try:
            print("⏳ Waiting for QR scan...")
            wait = WebDriverWait(self.driver, 120)
            
            # Wait for search box to appear (login successful)
            wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'div[contenteditable="true"][title="Search input textbox"]'))
            )
            
            # Save session
            self.db.save_session(self.driver.session_id)
            self.db.save_auth(True)
            self.is_connected = True
            print("✅ WhatsApp connected!")
            
        except Exception as e:
            print(f"❌ Login timeout: {e}")
            self.is_connected = False

    def send_message(self, to_number, message):
        """Send message to WhatsApp number"""
        if not self.is_connected:
            return False
        
        try:
            # Search for contact
            search_box = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'div[contenteditable="true"][title="Search input textbox"]'))
            )
            search_box.clear()
            search_box.send_keys(to_number)
            time.sleep(2)
            search_box.send_keys(Keys.ENTER)
            time.sleep(2)
            
            # Type and send message
            message_box = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'div[contenteditable="true"][title="Type a message"]'))
            )
            message_box.send_keys(message)
            message_box.send_keys(Keys.ENTER)
            
            return True
        except Exception as e:
            print(f"❌ Send error: {e}")
            return False

    def send_media(self, to_number, file_path, caption=""):
        """Send media file to WhatsApp"""
        if not self.is_connected:
            return False
        
        try:
            # Search contact
            search_box = self.driver.find_element(By.CSS_SELECTOR, 'div[contenteditable="true"][title="Search input textbox"]')
            search_box.clear()
            search_box.send_keys(to_number)
            time.sleep(2)
            search_box.send_keys(Keys.ENTER)
            time.sleep(2)
            
            # Attach file
            attach_btn = self.driver.find_element(By.CSS_SELECTOR, 'div[title="Attach"]')
            attach_btn.click()
            time.sleep(1)
            
            file_input = self.driver.find_element(By.CSS_SELECTOR, 'input[accept="*"]')
            file_input.send_keys(file_path)
            time.sleep(3)
            
            # Add caption
            if caption:
                caption_box = self.driver.find_element(By.CSS_SELECTOR, 'div[contenteditable="true"][title="Type a message"]')
                caption_box.send_keys(caption)
                time.sleep(1)
            
            # Send
            send_btn = self.driver.find_element(By.CSS_SELECTOR, 'span[data-icon="send"]')
            send_btn.click()
            
            return True
        except Exception as e:
            print(f"❌ Media error: {e}")
            return False

    def logout(self):
        """Logout from WhatsApp"""
        try:
            if self.driver:
                self.driver.quit()
            self.is_connected = False
            self.db.save_auth(False)
            self.db.save_qr(None)
            return True
        except:
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
    qr_base64 = db.get_qr()
    if qr_base64:
        qr_data = base64.b64decode(qr_base64)
        return send_file(BytesIO(qr_data), mimetype='image/png')
    return "QR not ready", 404

@app.route('/qr-base64')
def get_qr_base64():
    qr_base64 = db.get_qr()
    if qr_base64:
        return jsonify({'qr': qr_base64})
    return jsonify({'qr': None})

@app.route('/status')
def get_status():
    return jsonify({
        'connected': wa.is_connected,
        'authenticated': db.get_auth()
    })

# ==================== TELEGRAM BOT ====================
class TelegramBot:
    def __init__(self, token, wa_controller, database):
        self.wa = wa_controller
        self.db = database
        self.app = Application.builder().token(token).build()
        self.setup_handlers()

    def setup_handlers(self):
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("help", self.cmd_help))
        self.app.add_handler(CommandHandler("settarget", self.cmd_settarget))
        self.app.add_handler(CommandHandler("gettarget", self.cmd_gettarget))
        self.app.add_handler(CommandHandler("qr", self.cmd_qr))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("logout", self.cmd_logout))
        self.app.add_handler(CommandHandler("ping", self.cmd_ping))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))
        self.app.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))

    async def cmd_start(self, update: Update, context):
        await update.message.reply_text(
            "🤖 *WhatsApp Bridge Bot*\n\n"
            "Commands:\n"
            "/settarget 923001234567 - Set WhatsApp number\n"
            "/qr - Get WhatsApp QR\n"
            "/status - Check connection\n"
            "/help - More commands",
            parse_mode='Markdown'
        )

    async def cmd_help(self, update: Update, context):
        await update.message.reply_text(
            "📚 *How to use:*\n\n"
            "1. Set target: /settarget 923001234567\n"
            "2. Get QR: /qr\n"
            "3. Scan QR with WhatsApp\n"
            "4. Wait for 'Connected' message\n"
            "5. Send any message or photo"
        )

    async def cmd_settarget(self, update: Update, context):
        if not context.args:
            await update.message.reply_text("Usage: /settarget 923001234567")
            return
        target = context.args[0]
        self.db.save_target(update.effective_user.id, target)
        self.wa.target_number = target
        await update.message.reply_text(f"✅ Target set: +{target}")

    async def cmd_gettarget(self, update: Update, context):
        target = self.db.get_target(update.effective_user.id)
        if target:
            await update.message.reply_text(f"📱 Target: +{target}")
        else:
            await update.message.reply_text("⚠️ No target set")

    async def cmd_qr(self, update: Update, context):
        await update.message.reply_text("⏳ Generating WhatsApp QR...")
        
        qr_base64 = self.wa.get_qr()
        if qr_base64:
            qr_data = base64.b64decode(qr_base64)
            await update.message.reply_photo(
                photo=BytesIO(qr_data),
                caption="📱 Scan this QR with WhatsApp Web\nBot will notify when connected"
            )
        else:
            await update.message.reply_text("❌ Failed to generate QR")

    async def cmd_status(self, update: Update, context):
        status = "✅ Connected" if self.wa.is_connected else "❌ Disconnected"
        await update.message.reply_text(f"WhatsApp: {status}")

    async def cmd_logout(self, update: Update, context):
        if self.wa.logout():
            await update.message.reply_text("✅ Logged out")
        else:
            await update.message.reply_text("❌ Logout failed")

    async def cmd_ping(self, update: Update, context):
        await update.message.reply_text("🏓 Pong!")

    async def handle_text(self, update: Update, context):
        if not self.wa.is_connected:
            await update.message.reply_text("❌ WhatsApp not connected. Use /qr first")
            return
        
        target = self.db.get_target(update.effective_user.id)
        if not target:
            await update.message.reply_text("❌ No target set. Use /settarget")
            return
        
        success = self.wa.send_message(target, update.message.text)
        if success:
            await update.message.reply_text("✅ Sent")
        else:
            await update.message.reply_text("❌ Failed")

    async def handle_photo(self, update: Update, context):
        if not self.wa.is_connected:
            await update.message.reply_text("❌ WhatsApp not connected")
            return
        
        target = self.db.get_target(update.effective_user.id)
        if not target:
            await update.message.reply_text("❌ No target set")
            return
        
        try:
            file = await update.message.photo[-1].get_file()
            file_path = f"/tmp/photo_{int(time.time())}.jpg"
            await file.download_to_drive(file_path)
            
            caption = update.message.caption or "📸 Photo"
            success = self.wa.send_media(target, file_path, caption)
            
            if os.path.exists(file_path):
                os.remove(file_path)
            
            if success:
                await update.message.reply_text("✅ Photo sent")
            else:
                await update.message.reply_text("❌ Failed")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")

    def run(self):
        self.app.run_polling()

# ==================== MAIN ====================
if __name__ == '__main__':
    print("🚀 Starting Bot...")
    
    if 'DYNO' in os.environ:  # Heroku
        dyno = os.environ.get('DYNO', '').split('.')[0]
        if dyno == 'web':
            app.run(host='0.0.0.0', port=PORT)
        else:
            bot = TelegramBot(TELEGRAM_BOT_TOKEN, wa, db)
            bot.run()
    else:  # Local
        def run_flask():
            app.run(host='0.0.0.0', port=PORT, debug=False)
        
        flask_thread = threading.Thread(target=run_flask)
        flask_thread.daemon = True
        flask_thread.start()
        
        bot = TelegramBot(TELEGRAM_BOT_TOKEN, wa, db)
        bot.run()
