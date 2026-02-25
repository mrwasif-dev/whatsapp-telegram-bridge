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
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
MONGODB_URI = os.getenv('MONGODB_URI', 'mongodb+srv://username:password@cluster.mongodb.net/')
DB_NAME = os.getenv('DB_NAME', 'whatsapp_bot')
PORT = int(os.getenv('PORT', 5000))
ADMIN_IDS = os.getenv('ADMIN_IDS', '').split(',') if os.getenv('ADMIN_IDS') else []
DEFAULT_TARGET = os.getenv('DEFAULT_TARGET', '')

if not TELEGRAM_BOT_TOKEN:
    print("❌ TELEGRAM_BOT_TOKEN not set in environment variables")
    sys.exit(1)

# ============================================
# MongoDB Setup
# ============================================
class Database:
    def __init__(self):
        try:
            self.client = MongoClient(MONGODB_URI)
            self.db = self.client[DB_NAME]
            self.sessions = self.db['sessions']
            self.settings = self.db['settings']
            print("✅ MongoDB Connected")
        except ConnectionFailure as e:
            print(f"❌ MongoDB Connection Failed: {e}")
            sys.exit(1)
    
    def save_session(self, session_id, data):
        self.sessions.update_one(
            {'session_id': session_id},
            {'$set': {
                'data': data,
                'last_used': datetime.now()
            }},
            upsert=True
        )
    
    def get_session(self, session_id):
        return self.sessions.find_one({'session_id': session_id})
    
    def save_target(self, target_number):
        self.settings.update_one(
            {'key': 'target_number'},
            {'$set': {
                'value': target_number,
                'updated_at': datetime.now()
            }},
            upsert=True
        )
    
    def get_target(self):
        setting = self.settings.find_one({'key': 'target_number'})
        return setting.get('value') if setting else DEFAULT_TARGET
    
    def save_qr(self, qr_data):
        self.settings.update_one(
            {'key': 'qr_code'},
            {'$set': {
                'value': qr_data,
                'timestamp': datetime.now()
            }},
            upsert=True
        )
    
    def get_qr(self):
        setting = self.settings.find_one({'key': 'qr_code'})
        return setting.get('value') if setting else None
    
    def save_auth_state(self, state):
        self.settings.update_one(
            {'key': 'auth_state'},
            {'$set': {
                'value': state,
                'updated_at': datetime.now()
            }},
            upsert=True
        )
    
    def get_auth_state(self):
        setting = self.settings.find_one({'key': 'auth_state'})
        return setting.get('value') if setting else False

# ============================================
# WhatsApp Web Controller with Heroku Support
# ============================================
class WhatsAppController:
    def __init__(self, db):
        self.db = db
        self.driver = None
        self.is_ready = False
        self.qr_generated = False
        self.target_number = db.get_target()
        
    def setup_chrome_driver(self):
        """Setup Chrome driver for Heroku"""
        # Auto install ChromeDriver
        chromedriver_autoinstaller.install()
        
        chrome_options = Options()
        
        # Heroku specific options
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--disable-software-rasterizer')
        chrome_options.add_argument('--disable-extensions')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        # Load saved session if exists
        session_data = self.db.get_session('whatsapp_session')
        if session_data and session_data.get('data'):
            chrome_options.add_argument(f'user-data-dir={session_data["data"]}')
        
        # For Heroku, we need to use a specific Chrome binary location
        chrome_options.binary_location = os.environ.get('GOOGLE_CHROME_BIN', '/app/.apt/usr/bin/google-chrome')
        
        try:
            service = Service(executable_path=os.environ.get('CHROMEDRIVER_PATH', '/app/.chromedriver/bin/chromedriver'))
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            print("✅ Chrome driver started successfully")
            return True
        except Exception as e:
            print(f"❌ Failed to start Chrome driver: {e}")
            return False
    
    def start_browser(self):
        """Start the browser and load WhatsApp Web"""
        if not self.setup_chrome_driver():
            return False
        
        try:
            self.driver.get('https://web.whatsapp.com')
            print("✅ WhatsApp Web loaded")
            return True
        except Exception as e:
            print(f"❌ Failed to load WhatsApp Web: {e}")
            return False
    
    def get_qr(self):
        """Get QR code as base64"""
        try:
            # Wait for QR code element
            wait = WebDriverWait(self.driver, 30)
            qr_element = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'div[data-ref]'))
            )
            
            qr_data = qr_element.get_attribute('data-ref')
            
            if qr_data:
                # Generate QR code
                qr = qrcode.QRCode(version=1, box_size=10, border=5)
                qr.add_data(qr_data)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                
                # Convert to base64
                buffered = BytesIO()
                img.save(buffered, format="PNG")
                img_base64 = base64.b64encode(buffered.getvalue()).decode()
                
                # Save to database
                self.db.save_qr(img_base64)
                self.qr_generated = True
                
                return img_base64
        except Exception as e:
            print(f"❌ QR generation error: {e}")
            return None
    
    def wait_for_login(self):
        """Wait for WhatsApp Web login"""
        try:
            # Wait for search box to appear (indicates successful login)
            wait = WebDriverWait(self.driver, 120)
            wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'div[contenteditable="true"][title="Search input textbox"]'))
            )
            
            # Save session data
            user_data = self.driver.capabilities.get('chrome', {}).get('userDataDir', '')
            self.db.save_session('whatsapp_session', user_data)
            self.db.save_auth_state(True)
            
            self.is_ready = True
            print("✅ WhatsApp Web logged in successfully")
            return True
        except Exception as e:
            print(f"❌ Login wait error: {e}")
            self.is_ready = False
            return False
    
    def send_message(self, text):
        """Send a message to target number"""
        if not self.is_ready or not self.target_number:
            return False
        
        try:
            # Search for target
            search_box = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'div[contenteditable="true"][title="Search input textbox"]'))
            )
            search_box.clear()
            search_box.send_keys(self.target_number)
            time.sleep(2)
            
            # Open chat
            search_box.send_keys(Keys.ENTER)
            time.sleep(2)
            
            # Type and send message
            message_box = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'div[contenteditable="true"][title="Type a message"]'))
            )
            message_box.send_keys(text)
            message_box.send_keys(Keys.ENTER)
            
            return True
        except Exception as e:
            print(f"❌ Send message error: {e}")
            return False
    
    def send_file(self, file_path, caption=""):
        """Send a file to target number"""
        if not self.is_ready or not self.target_number:
            return False
        
        try:
            # Search for target
            search_box = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'div[contenteditable="true"][title="Search input textbox"]'))
            )
            search_box.clear()
            search_box.send_keys(self.target_number)
            time.sleep(2)
            
            # Open chat
            search_box.send_keys(Keys.ENTER)
            time.sleep(2)
            
            # Click attach button
            attach_btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, 'div[title="Attach"]'))
            )
            attach_btn.click()
            time.sleep(1)
            
            # Upload file
            file_input = self.driver.find_element(By.CSS_SELECTOR, 'input[accept="*"]')
            file_input.send_keys(file_path)
            time.sleep(3)
            
            # Add caption if provided
            if caption:
                caption_box = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'div[contenteditable="true"][title="Type a message"]'))
                )
                caption_box.send_keys(caption)
                time.sleep(1)
            
            # Send
            send_btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, 'span[data-icon="send"]'))
            )
            send_btn.click()
            
            return True
        except Exception as e:
            print(f"❌ Send file error: {e}")
            return False
    
    def get_jid(self):
        """Get current JID"""
        return f"{self.target_number}@c.us" if self.target_number else None
    
    def logout(self):
        """Logout from WhatsApp"""
        try:
            if self.driver:
                self.driver.quit()
            self.is_ready = False
            self.db.sessions.delete_one({'session_id': 'whatsapp_session'})
            self.db.save_auth_state(False)
            return True
        except Exception as e:
            print(f"❌ Logout error: {e}")
            return False

# ============================================
# Flask Web Server for QR Code
# ============================================
app = Flask(__name__)
whatsapp = None
db = None

@app.route('/')
def home():
    """Home page with QR code"""
    return render_template('qr.html')

@app.route('/qr')
def get_qr():
    """Get QR code image"""
    qr_base64 = db.get_qr()
    if qr_base64:
        qr_data = base64.b64decode(qr_base64)
        return send_file(
            BytesIO(qr_data),
            mimetype='image/png',
            as_attachment=False,
            download_name='qr.png'
        )
    return {'error': 'No QR code available'}, 404

@app.route('/qr-base64')
def get_qr_base64():
    """Get QR code as base64"""
    qr_base64 = db.get_qr()
    if qr_base64:
        return jsonify({'qr': qr_base64})
    return jsonify({'error': 'No QR code'}), 404

@app.route('/status')
def status():
    """Check connection status"""
    return jsonify({
        'connected': whatsapp.is_ready if whatsapp else False,
        'target': whatsapp.target_number if whatsapp else None,
        'authenticated': db.get_auth_state() if db else False
    })

@app.route('/set-target', methods=['POST'])
def set_target():
    """Set target number via API"""
    from flask import request
    data = request.json
    if data and data.get('target'):
        db.save_target(data['target'])
        if whatsapp:
            whatsapp.target_number = data['target']
        return jsonify({'success': True, 'message': 'Target set successfully'})
    return jsonify({'success': False, 'message': 'Invalid data'}), 400

# ============================================
# Telegram Bot Handlers
# ============================================
class TelegramBot:
    def __init__(self, token, whatsapp_ctrl, database):
        self.token = token
        self.whatsapp = whatsapp_ctrl
        self.db = database
        self.app = Application.builder().token(token).build()
        self.setup_handlers()
    
    def setup_handlers(self):
        """Setup command handlers"""
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("help", self.help_command))
        self.app.add_handler(CommandHandler("settarget", self.settarget_command))
        self.app.add_handler(CommandHandler("gettarget", self.gettarget_command))
        self.app.add_handler(CommandHandler("status", self.status_command))
        self.app.add_handler(CommandHandler("qr", self.qr_command))
        self.app.add_handler(CommandHandler("logout", self.logout_command))
        self.app.add_handler(CommandHandler("jid", self.jid_command))
        self.app.add_handler(CommandHandler("ping", self.ping_command))
        
        # Admin commands
        self.app.add_handler(CommandHandler("admin", self.admin_command))
        self.app.add_handler(CommandHandler("stats", self.stats_command))
        
        # Media handler
        self.app.add_handler(MessageHandler(filters.ALL, self.handle_message))
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command"""
        welcome = """
🤖 *Telegram-WhatsApp Bridge Bot*

Welcome! This bot forwards media from Telegram to WhatsApp.

*Available Commands:*
/help - Get help
/settarget [number] - Set WhatsApp target number
/gettarget - Get current target
/status - Check WhatsApp status
/qr - Get QR code for WhatsApp Web
/logout - Logout from WhatsApp

*How to use:*
1. Set target number using /settarget
2. Scan QR code using /qr
3. Send any media (photo, video, document) to forward
        """
        await update.message.reply_text(welcome, parse_mode='Markdown')
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Help command"""
        help_text = """
📚 *Help & Commands*

*Setup Commands:*
• /settarget [number] - Set WhatsApp number (format: 923001234567)
• /gettarget - Show current target
• /qr - Get WhatsApp Web QR code
• /status - Check connection status
• /logout - Logout from WhatsApp

*General Commands:*
• /ping - Check if bot is alive
• /jid - Get your JID
• /help - Show this help

*Admin Commands:*
• /admin - Admin panel
• /stats - Bot statistics

*Supported Media:*
• Photos 📸
• Videos 🎥
• Documents 📄
• Audio 🎵
• Voice notes 🎤

*Note:* Max file size: 50MB
        """
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def settarget_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set target number"""
        try:
            args = context.args
            if not args:
                await update.message.reply_text(
                    "⚠️ Please provide a phone number.\n"
                    "Example: /settarget 923001234567"
                )
                return
            
            target = args[0].strip()
            
            # Validate number (basic validation)
            if not target.isdigit() or len(target) < 10:
                await update.message.reply_text(
                    "❌ Invalid number format. Use international format without + or spaces.\n"
                    "Example: 923001234567"
                )
                return
            
            # Save to database
            self.db.save_target(target)
            self.whatsapp.target_number = target
            
            await update.message.reply_text(f"✅ Target number set to: +{target}")
            
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")
    
    async def gettarget_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get current target"""
        target = self.db.get_target()
        if target:
            await update.message.reply_text(f"📱 Current target: +{target}")
        else:
            await update.message.reply_text("⚠️ No target number set. Use /settarget to set one.")
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Check connection status"""
        if self.whatsapp.is_ready:
            status = "✅ WhatsApp is connected"
            if self.whatsapp.target_number:
                status += f"\n📱 Target: +{self.whatsapp.target_number}"
        else:
            status = "❌ WhatsApp is not connected. Use /qr to connect."
        
        await update.message.reply_text(status)
    
    async def qr_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send QR code"""
        await update.message.reply_text("⏳ Generating QR code...")
        
        # Check if QR is available
        qr_base64 = self.db.get_qr()
        if qr_base64:
            qr_data = base64.b64decode(qr_base64)
            await update.message.reply_photo(
                photo=BytesIO(qr_data),
                caption="📱 Scan this QR code with WhatsApp Web"
            )
        else:
            # Provide web URL for QR
            base_url = os.getenv('BASE_URL', f'https://your-app.herokuapp.com')
            await update.message.reply_text(
                f"⚠️ QR code not ready. Please visit:\n{base_url}\n\n"
                "Or wait a few seconds and try /qr again."
            )
    
    async def logout_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Logout from WhatsApp"""
        if self.whatsapp.logout():
            await update.message.reply_text("✅ Logged out successfully")
        else:
            await update.message.reply_text("❌ Logout failed")
    
    async def jid_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get JID"""
        jid = self.whatsapp.get_jid()
        if jid:
            await update.message.reply_text(f"📱 JID: `{jid}`", parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ JID not available. Set target first.")
    
    async def ping_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Ping command"""
        await update.message.reply_text("🏓 Pong! Bot is alive.")
    
    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin panel"""
        user_id = str(update.effective_user.id)
        if user_id not in ADMIN_IDS:
            await update.message.reply_text("❌ You are not authorized")
            return
        
        admin_text = """
👑 *Admin Panel*

/stats - View bot statistics
/broadcast [message] - Broadcast to all users
/clearsessions - Clear all sessions
/restart - Restart WhatsApp connection
        """
        await update.message.reply_text(admin_text, parse_mode='Markdown')
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show bot statistics"""
        user_id = str(update.effective_user.id)
        if user_id not in ADMIN_IDS:
            return
        
        try:
            # Get MongoDB stats
            sessions_count = self.db.sessions.count_documents({})
            settings_count = self.db.settings.count_documents({})
            
            stats = f"""
📊 *Bot Statistics*

Total Sessions: {sessions_count}
Settings Records: {settings_count}
WhatsApp Status: {'✅ Connected' if self.whatsapp.is_ready else '❌ Disconnected'}
Current Target: {self.whatsapp.target_number or 'Not set'}
QR Available: {'✅ Yes' if self.db.get_qr() else '❌ No'}
            """
            await update.message.reply_text(stats, parse_mode='Markdown')
            
        except Exception as e:
            await update.message.reply_text(f"❌ Error getting stats: {str(e)}")
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle messages and media"""
        # Ignore commands
        if update.message.text and update.message.text.startswith('/'):
            return
        
        # Check if WhatsApp is ready
        if not self.whatsapp.is_ready:
            await update.message.reply_text("❌ WhatsApp is not connected. Use /qr to connect first.")
            return
        
        # Check target
        target = self.db.get_target()
        if not target:
            await update.message.reply_text("⚠️ No target set. Use /settarget [number] first.")
            return
        
        # Handle text message
        if update.message.text:
            success = self.whatsapp.send_message(update.message.text)
            if success:
                await update.message.reply_text("✅ Message forwarded to WhatsApp")
            else:
                await update.message.reply_text("❌ Failed to send message")
        
        # Handle photo
        elif update.message.photo:
            try:
                file = await update.message.photo[-1].get_file()
                file_path = f"/tmp/photo_{int(time.time())}.jpg"
                await file.download_to_drive(file_path)
                
                caption = update.message.caption or "📸 Photo from Telegram"
                success = self.whatsapp.send_file(file_path, caption)
                
                # Clean up
                if os.path.exists(file_path):
                    os.remove(file_path)
                
                if success:
                    await update.message.reply_text("✅ Photo forwarded to WhatsApp")
                else:
                    await update.message.reply_text("❌ Failed to send photo")
                    
            except Exception as e:
                await update.message.reply_text(f"❌ Error: {str(e)}")
        
        # Handle video
        elif update.message.video:
            try:
                file = await update.message.video.get_file()
                file_path = f"/tmp/video_{int(time.time())}.mp4"
                await file.download_to_drive(file_path)
                
                caption = update.message.caption or "🎥 Video from Telegram"
                success = self.whatsapp.send_file(file_path, caption)
                
                # Clean up
                if os.path.exists(file_path):
                    os.remove(file_path)
                
                if success:
                    await update.message.reply_text("✅ Video forwarded to WhatsApp")
                else:
                    await update.message.reply_text("❌ Failed to send video")
                    
            except Exception as e:
                await update.message.reply_text(f"❌ Error: {str(e)}")
        
        # Handle document
        elif update.message.document:
            try:
                file = await update.message.document.get_file()
                file_name = update.message.document.file_name or f"doc_{int(time.time())}"
                file_path = f"/tmp/{file_name}"
                await file.download_to_drive(file_path)
                
                caption = update.message.caption or "📄 Document from Telegram"
                success = self.whatsapp.send_file(file_path, caption)
                
                # Clean up
                if os.path.exists(file_path):
                    os.remove(file_path)
                
                if success:
                    await update.message.reply_text("✅ Document forwarded to WhatsApp")
                else:
                    await update.message.reply_text("❌ Failed to send document")
                    
            except Exception as e:
                await update.message.reply_text(f"❌ Error: {str(e)}")
        
        # Handle other media types
        else:
            await update.message.reply_text("⚠️ Unsupported media type. Send photo, video, or document.")
    
    def run(self):
        """Start the bot"""
        self.app.run_polling()

# ============================================
# Background Workers
# ============================================
def whatsapp_worker():
    """WhatsApp background worker"""
    global whatsapp, db
    
    print("📱 Starting WhatsApp worker...")
    
    # Initialize WhatsApp controller
    whatsapp = WhatsAppController(db)
    
    # Start browser
    if not whatsapp.start_browser():
        print("❌ Failed to start WhatsApp browser")
        return
    
    # Wait for QR and login
    qr_retries = 0
    max_retries = 30  # 5 minutes with 10 second intervals
    
    while qr_retries < max_retries and not whatsapp.qr_generated:
        qr = whatsapp.get_qr()
        if qr:
            print("✅ QR code generated")
        time.sleep(10)
        qr_retries += 1
    
    # Wait for login
    if whatsapp.wait_for_login():
        print("✅ WhatsApp worker ready")
        
        # Keep worker alive
        while True:
            time.sleep(60)
            # Periodic checks
            if not whatsapp.is_ready:
                print("⚠️ WhatsApp disconnected, attempting reconnect...")
                break
    else:
        print("❌ WhatsApp login timeout")

def start_whatsapp_worker():
    """Start WhatsApp worker in a thread"""
    worker_thread = threading.Thread(target=whatsapp_worker)
    worker_thread.daemon = True
    worker_thread.start()

# ============================================
# Main Application
# ============================================
def main():
    """Main entry point"""
    global db
    
    print("🚀 Starting Telegram-WhatsApp Bridge Bot...")
    
    # Initialize database
    db = Database()
    
    # Check if we're on Heroku (worker or web)
    if 'DYNO' in os.environ:
        # On Heroku, different dynos handle different tasks
        dyno_type = os.environ.get('DYNO', '').split('.')[0]
        
        if dyno_type == 'web':
            # Web dyno - Flask server
            print("🌐 Starting web server...")
            
            # Initialize WhatsApp (will be used by web interface)
            global whatsapp
            whatsapp = WhatsAppController(db)
            
            # Start WhatsApp in background
            start_whatsapp_worker()
            
            # Run Flask
            app.run(host='0.0.0.0', port=PORT)
            
        else:
            # Worker dyno - Telegram bot
            print("🤖 Starting Telegram bot...")
            
            # Initialize WhatsApp
            whatsapp = WhatsAppController(db)
            
            # Start WhatsApp in background
            start_whatsapp_worker()
            
            # Start Telegram bot
            telegram_bot = TelegramBot(TELEGRAM_BOT_TOKEN, whatsapp, db)
            telegram_bot.run()
    
    else:
        # Local development - run everything
        print("💻 Running in development mode...")
        
        # Initialize components
        whatsapp = WhatsAppController(db)
        
        # Start WhatsApp in background
        start_whatsapp_worker()
        
        # Start Flask in background
        def run_flask():
            app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)
        
        flask_thread = threading.Thread(target=run_flask)
        flask_thread.daemon = True
        flask_thread.start()
        
        # Start Telegram bot
        telegram_bot = TelegramBot(TELEGRAM_BOT_TOKEN, whatsapp, db)
        telegram_bot.run()

if __name__ == '__main__':
    main()
