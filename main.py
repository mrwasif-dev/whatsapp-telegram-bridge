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

load_dotenv()

# ==================== CONFIG ====================
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
MONGODB_URI = os.getenv('MONGODB_URI')
PORT = int(os.getenv('PORT', 5000))
DEFAULT_TARGET = os.getenv('DEFAULT_TARGET', '')

if not TELEGRAM_BOT_TOKEN or not MONGODB_URI:
    print("❌ Missing environment variables")
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

# ==================== FAKE WHATSAPP ====================
class FakeWhatsApp:
    """یہ صرف ڈیمو کے لیے ہے - اصلی WhatsApp connection بعد میں لگائیں گے"""
    def __init__(self, db):
        self.db = db
        self.is_ready = False
        self.target = db.get_target()
        
        # پہلے سے سیو شدہ QR چیک کریں
        if not db.get_qr():
            self.generate_fake_qr()
    
    def generate_fake_qr(self):
        """ایک فرضی QR کوڈ بنا کر سیو کر دیتا ہے"""
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data("https://web.whatsapp.com")
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        img_base64 = base64.b64encode(buffered.getvalue()).decode()
        
        self.db.save_qr(img_base64)
        print("✅ Fake QR generated")
    
    def connect(self):
        """واٹس ایپ کنیکٹ کرنے کا عمل"""
        print("📱 Connecting to WhatsApp...")
        time.sleep(3)
        self.is_ready = True
        self.db.save_auth(True)
        print("✅ WhatsApp Connected!")
        return True

# ==================== FLASK WEB ====================
app = Flask(__name__)
whatsapp = None
db = Database()

@app.route('/')
def home():
    return render_template('qr.html')

@app.route('/qr')
def get_qr():
    qr_base64 = db.get_qr()
    if qr_base64:
        qr_data = base64.b64decode(qr_base64)
        return send_file(BytesIO(qr_data), mimetype='image/png')
    return "No QR", 404

@app.route('/qr-base64')
def get_qr_base64():
    qr_base64 = db.get_qr()
    if qr_base64:
        return jsonify({'qr': qr_base64})
    return jsonify({'qr': None})

@app.route('/status')
def status():
    return jsonify({
        'connected': whatsapp.is_ready if whatsapp else False,
        'target': whatsapp.target if whatsapp else None,
        'authenticated': db.get_auth()
    })

# ==================== TELEGRAM BOT ====================
class TelegramBot:
    def __init__(self, token, wa, database):
        self.wa = wa
        self.db = database
        self.app = Application.builder().token(token).build()
        self.setup()
    
    def setup(self):
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("help", self.help))
        self.app.add_handler(CommandHandler("settarget", self.set_target))
        self.app.add_handler(CommandHandler("gettarget", self.get_target))
        self.app.add_handler(CommandHandler("status", self.status))
        self.app.add_handler(CommandHandler("qr", self.qr))
        self.app.add_handler(CommandHandler("connect", self.connect))
        self.app.add_handler(CommandHandler("ping", self.ping))
    
    async def start(self, update: Update, context):
        await update.message.reply_text(
            "🤖 *Telegram-WhatsApp Bot*\n\n"
            "Commands:\n"
            "/settarget 923001234567 - Set WhatsApp number\n"
            "/gettarget - Show current target\n"
            "/qr - Get QR code\n"
            "/connect - Connect WhatsApp\n"
            "/status - Check status\n"
            "/ping - Ping test",
            parse_mode='Markdown'
        )
    
    async def help(self, update: Update, context):
        await update.message.reply_text(
            "📚 *How to use:*\n\n"
            "1. Set target: /settarget 923001234567\n"
            "2. Get QR: /qr\n"
            "3. Connect: /connect\n"
            "4. Send any message to test"
        )
    
    async def set_target(self, update: Update, context):
        try:
            if not context.args:
                await update.message.reply_text("Usage: /settarget 923001234567")
                return
            target = context.args[0]
            self.db.save_target(target)
            self.wa.target = target
            await update.message.reply_text(f"✅ Target set: +{target}")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
    
    async def get_target(self, update: Update, context):
        target = self.db.get_target()
        if target:
            await update.message.reply_text(f"📱 Target: +{target}")
        else:
            await update.message.reply_text("⚠️ No target set")
    
    async def status(self, update: Update, context):
        status = "✅ Connected" if self.wa.is_ready else "❌ Disconnected"
        await update.message.reply_text(f"WhatsApp: {status}")
    
    async def qr(self, update: Update, context):
        qr_base64 = self.db.get_qr()
        if qr_base64:
            qr_data = base64.b64decode(qr_base64)
            await update.message.reply_photo(
                photo=BytesIO(qr_data),
                caption="📱 Scan this QR with WhatsApp Web"
            )
        else:
            await update.message.reply_text("❌ QR not available")
    
    async def connect(self, update: Update, context):
        await update.message.reply_text("⏳ Connecting to WhatsApp...")
        success = self.wa.connect()
        if success:
            await update.message.reply_text("✅ WhatsApp Connected!")
        else:
            await update.message.reply_text("❌ Connection failed")
    
    async def ping(self, update: Update, context):
        await update.message.reply_text("🏓 Pong!")
    
    def run(self):
        print("🤖 Telegram Bot Started")
        self.app.run_polling()

# ==================== WORKER ====================
def start_whatsapp():
    global whatsapp
    whatsapp = FakeWhatsApp(db)
    print("📱 WhatsApp Worker Ready")
    
    # خودکار کنیکٹ
    if not whatsapp.is_ready:
        whatsapp.connect()

# ==================== MAIN ====================
if __name__ == '__main__':
    print("🚀 Starting Bot...")
    
    # سٹارٹ WhatsApp
    start_whatsapp()
    
    if 'DYNO' in os.environ:  # Heroku
        dyno = os.environ.get('DYNO', '').split('.')[0]
        if dyno == 'web':
            print("🌐 Starting Web Server...")
            app.run(host='0.0.0.0', port=PORT)
        else:
            print("🤖 Starting Telegram Bot...")
            bot = TelegramBot(TELEGRAM_BOT_TOKEN, whatsapp, db)
            bot.run()
    else:  # Local
        print("💻 Local Mode")
        
        # Flask in background
        def run_flask():
            app.run(host='0.0.0.0', port=PORT, debug=False)
        
        flask_thread = threading.Thread(target=run_flask)
        flask_thread.daemon = True
        flask_thread.start()
        
        # Telegram Bot
        bot = TelegramBot(TELEGRAM_BOT_TOKEN, whatsapp, db)
        bot.run()
