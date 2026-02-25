import os
import sys
import time
import json
import qrcode
import threading
import requests
from io import BytesIO
from datetime import datetime
from bson import ObjectId

# Flask for web server
from flask import Flask, render_template, send_file

# Telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Selenium for WhatsApp
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# MongoDB
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

# Load config
from config import *

# ============================================
# MongoDB Setup
# ============================================
class Database:
    def __init__(self):
        try:
            self.client = MongoClient(MONGODB_URI)
            self.db = self.client[DB_NAME]
            self.sessions = self.db[COLLECTION_NAME]
            print("✅ MongoDB Connected")
        except ConnectionFailure:
            print("❌ MongoDB Connection Failed")
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
        self.sessions.update_one(
            {'session_id': 'default_target'},
            {'$set': {
                'target': target_number,
                'last_updated': datetime.now()
            }},
            upsert=True
        )
    
    def get_target(self):
        session = self.sessions.find_one({'session_id': 'default_target'})
        return session.get('target') if session else DEFAULT_TARGET
    
    def save_qr(self, qr_data):
        self.sessions.update_one(
            {'session_id': 'qr_code'},
            {'$set': {
                'qr': qr_data,
                'timestamp': datetime.now()
            }},
            upsert=True
        )
    
    def get_qr(self):
        session = self.sessions.find_one({'session_id': 'qr_code'})
        return session.get('qr') if session else None

# ============================================
# WhatsApp Web Controller
# ============================================
class WhatsAppController:
    def __init__(self, db):
        self.db = db
        self.driver = None
        self.is_ready = False
        self.qr_generated = False
        self.target_number = db.get_target()
        
    def start_browser(self):
        """شروع کریں براؤزر"""
        options = webdriver.ChromeOptions()
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        
        # سیشن لوڈ کریں اگر موجود ہو
        session_data = self.db.get_session('whatsapp_session')
        if session_data and session_data.get('data'):
            options.add_argument(f'user-data-dir={session_data["data"]}')
        
        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options
        )
        self.driver.get('https://web.whatsapp.com')
        
    def get_qr(self):
        """QR کوڈ حاصل کریں"""
        try:
            wait = WebDriverWait(self.driver, 10)
            qr_element = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'div[data-ref]'))
            )
            qr_data = qr_element.get_attribute('data-ref')
            
            if qr_data:
                # QR کوڈ جنریٹ کریں
                qr = qrcode.QRCode(version=1, box_size=10, border=5)
                qr.add_data(qr_data)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                
                # تصویر کو بائٹس میں تبدیل کریں
                img_bytes = BytesIO()
                img.save(img_bytes, format='PNG')
                img_bytes = img_bytes.getvalue()
                
                # ڈیٹا بیس میں سیو کریں
                self.db.save_qr(img_bytes)
                self.qr_generated = True
                
                return img_bytes
        except:
            return None
    
    def wait_for_login(self):
        """لاگ ان کا انتظار کریں"""
        try:
            wait = WebDriverWait(self.driver, 120)
            wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'div[title="Search input textbox"]'))
            )
            
            # سیشن سیو کریں
            user_data = self.driver.capabilities['chrome']['userDataDir']
            self.db.save_session('whatsapp_session', user_data)
            
            self.is_ready = True
            print("✅ WhatsApp Logged In")
            return True
        except:
            self.is_ready = False
            return False
    
    def send_message(self, text):
        """میسیج بھیجیں"""
        if not self.is_ready or not self.target_number:
            return False
        
        try:
            # سرچ باکس میں نمبر ڈالیں
            search_box = self.driver.find_element(By.CSS_SELECTOR, 'div[title="Search input textbox"]')
            search_box.clear()
            search_box.send_keys(self.target_number)
            time.sleep(2)
            
            # چیٹ اوپن کریں
            search_box.send_keys(Keys.ENTER)
            time.sleep(2)
            
            # میسیج ٹائپ کریں
            message_box = self.driver.find_element(By.CSS_SELECTOR, 'div[title="Type a message"]')
            message_box.send_keys(text)
            message_box.send_keys(Keys.ENTER)
            
            return True
        except:
            return False
    
    def send_file(self, file_path, caption=""):
        """فائل بھیجیں"""
        if not self.is_ready or not self.target_number:
            return False
        
        try:
            # اٹیچمنٹ بٹن پر کلک کریں
            attach_btn = self.driver.find_element(By.CSS_SELECTOR, 'div[title="Attach"]')
            attach_btn.click()
            time.sleep(1)
            
            # فائل اپ لوڈ کریں
            file_input = self.driver.find_element(By.CSS_SELECTOR, 'input[accept="*"]')
            file_input.send_keys(file_path)
            time.sleep(3)
            
            # کیپشن ڈالیں
            if caption:
                caption_box = self.driver.find_element(By.CSS_SELECTOR, 'div[title="Type a message"]')
                caption_box.send_keys(caption)
                time.sleep(1)
            
            # بھیجیں
            send_btn = self.driver.find_element(By.CSS_SELECTOR, 'span[data-icon="send"]')
            send_btn.click()
            
            return True
        except:
            return False
    
    def get_jid(self):
        """اپنا JID حاصل کریں"""
        return f"{self.target_number}@c.us" if self.target_number else None
    
    def logout(self):
        """لاگ آؤٹ کریں"""
        if self.driver:
            self.driver.quit()
            self.is_ready = False
            self.db.sessions.delete_one({'session_id': 'whatsapp_session'})
            return True
        return False

# ============================================
# Flask Web Server for QR Code
# ============================================
app = Flask(__name__)
whatsapp = None
db = None

@app.route('/')
def home():
    return render_template('qr.html')

@app.route('/qr')
def get_qr():
    """QR کوڈ تصویر واپس کریں"""
    qr_data = db.get_qr()
    if qr_data:
        return send_file(
            BytesIO(qr_data),
            mimetype='image/png',
            as_attachment=False,
            download_name='qr.png'
        )
    return {'error': 'No QR code available'}, 404

@app.route('/status')
def status():
    """کنکشن سٹیٹس چیک کریں"""
    return {
        'connected': whatsapp.is_ready if whatsapp else False,
        'target': whatsapp.target_number if whatsapp else None
    }

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
        """کمانڈ ہینڈلرز سیٹ اپ کریں"""
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("help", self.help_command))
        self.app.add_handler(CommandHandler("settarget", self.settarget_command))
        self.app.add_handler(CommandHandler("gettarget", self.gettarget_command))
        self.app.add_handler(CommandHandler("status", self.status_command))
        self.app.add_handler(CommandHandler("qr", self.qr_command))
        self.app.add_handler(CommandHandler("logout", self.logout_command))
        self.app.add_handler(CommandHandler("jid", self.jid_command))
        self.app.add_handler(CommandHandler("ping", self.ping_command))
        
        # ایڈمن کمانڈز
        self.app.add_handler(CommandHandler("admin", self.admin_command))
        self.app.add_handler(CommandHandler("stats", self.stats_command))
        
        # میڈیا ہینڈلر
        self.app.add_handler(MessageHandler(filters.ALL, self.handle_message))
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """بوٹ شروع کریں"""
        welcome = """
🤖 *Telegram-WhatsApp Bridge Bot*

خوش آمدید! یہ بوٹ ٹیلیگرام سے واٹس ایپ پر میڈیا بھیجتا ہے۔

*کمانڈز:*
/help - مدد حاصل کریں
/settarget [نمبر] - واٹس ایپ نمبر سیٹ کریں
/gettarget - موجودہ نمبر دیکھیں
/status - واٹس ایپ سٹیٹس
/qr - QR کوڈ حاصل کریں
/logout - واٹس ایپ لاگ آؤٹ
        """
        await update.message.reply_text(welcome, parse_mode='Markdown')
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """مدد"""
        help_text = """
📚 *رہنمائی*

*سیٹ اپ:*
1️⃣ /qr سے QR کوڈ حاصل کریں
2️⃣ واٹس ایپ سے اسکین کریں
3️⃣ /settarget [نمبر] سے ٹارگٹ سیٹ کریں
4️⃣ اب کوئی بھی میڈیا بھیجیں

*مثال:* /settarget 923001234567

*واٹس ایپ کمانڈز:*
• ping - چیک کریں
• jid - اپنا JID دیکھیں
        """
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def settarget_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ٹارگٹ نمبر سیٹ کریں"""
        try:
            args = context.args
            if not args:
                await update.message.reply_text("⚠️ نمبر لکھیں: /settarget 923001234567")
                return
            
            target = args[0]
            if not target.isdigit() or len(target) < 10:
                await update.message.reply_text("❌ غلط نمبر۔ صرف ہندسے استعمال کریں (مثلاً 923001234567)")
                return
            
            self.db.save_target(target)
            self.whatsapp.target_number = target
            
            await update.message.reply_text(f"✅ ٹارگٹ سیٹ: +{target}")
        except Exception as e:
            await update.message.reply_text(f"❌ خرابی: {str(e)}")
    
    async def gettarget_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """موجودہ ٹارگٹ دیکھیں"""
        target = self.db.get_target()
        if target:
            await update.message.reply_text(f"📱 موجودہ ٹارگٹ: +{target}")
        else:
            await update.message.reply_text("⚠️ کوئی ٹارگٹ سیٹ نہیں")
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """کنکشن سٹیٹس"""
        if self.whatsapp.is_ready:
            status = "✅ واٹس ایپ کنیکٹ ہے"
            if self.whatsapp.target_number:
                status += f"\n📱 ٹارگٹ: +{self.whatsapp.target_number}"
        else:
            status = "❌ واٹس ایپ کنیکٹ نہیں ہے۔ /qr استعمال کریں"
        
        await update.message.reply_text(status)
    
    async def qr_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """QR کوڈ بھیجیں"""
        await update.message.reply_text("⏳ QR کوڈ جنریٹ ہو رہا ہے...")
        
        # QR کوڈ چیک کریں
        qr_data = self.db.get_qr()
        if qr_data:
            await update.message.reply_photo(
                photo=BytesIO(qr_data),
                caption="📱 واٹس ایپ سے اسکین کریں"
            )
        else:
            await update.message.reply_text(
                "⚠️ QR کوڈ دستیاب نہیں۔ ویب پیج چیک کریں:\n"
                f"http://localhost:{PORT}"
            )
    
    async def logout_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """واٹس ایپ لاگ آؤٹ"""
        if self.whatsapp.logout():
            await update.message.reply_text("✅ لاگ آؤٹ کر دیا گیا")
        else:
            await update.message.reply_text("❌ لاگ آؤٹ ناکام")
    
    async def jid_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """JID دکھائیں"""
        jid = self.whatsapp.get_jid()
        if jid:
            await update.message.reply_text(f"📱 JID: `{jid}`", parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ JID دستیاب نہیں")
    
    async def ping_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """پنگ"""
        await update.message.reply_text("🏓 Pong!")
    
    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ایڈمن پینل"""
        user_id = str(update.effective_user.id)
        if user_id not in ADMIN_IDS:
            await update.message.reply_text("❌ آپ ایڈمن نہیں ہیں")
            return
        
        admin_text = """
👑 *ایڈمن پینل*

/stats - بوٹ سٹیٹس
/broadcast [msg] - سب کو پیغام
/clearsessions - سیشن صاف کریں
        """
        await update.message.reply_text(admin_text, parse_mode='Markdown')
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """سٹیٹس دکھائیں"""
        user_id = str(update.effective_user.id)
        if user_id not in ADMIN_IDS:
            return
        
        # مونگو سٹیٹس
        sessions_count = self.db.sessions.count_documents({})
        
        stats = f"""
📊 *بوٹ سٹیٹس*

کل سیشنز: {sessions_count}
واٹس ایپ: {'✅' if self.whatsapp.is_ready else '❌'}
ٹارگٹ: {self.whatsapp.target_number or 'سیٹ نہیں'}
        """
        await update.message.reply_text(stats, parse_mode='Markdown')
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """میسیجز اور میڈیا ہینڈل کریں"""
        # چیک کریں واٹس ایپ ریڈی ہے یا نہیں
        if not self.whatsapp.is_ready:
            await update.message.reply_text("❌ واٹس ایپ کنیکٹ نہیں ہے۔ /qr استعمال کریں")
            return
        
        # ٹارگٹ چیک کریں
        target = self.db.get_target()
        if not target:
            await update.message.reply_text("⚠️ پہلے /settarget سے نمبر سیٹ کریں")
            return
        
        # ٹیکسٹ میسیج
        if update.message.text and not update.message.text.startswith('/'):
            success = self.whatsapp.send_message(update.message.text)
            if success:
                await update.message.reply_text("✅ پیغام بھیج دیا گیا")
            else:
                await update.message.reply_text("❌ بھیجنے میں خرابی")
        
        # فوٹو
        elif update.message.photo:
            file = await update.message.photo[-1].get_file()
            file_path = f"temp_{datetime.now().timestamp()}.jpg"
            await file.download_to_drive(file_path)
            
            caption = update.message.caption or "📸 تصویر"
            success = self.whatsapp.send_file(file_path, caption)
            
            os.remove(file_path)  # عارضی فائل ڈیلیٹ کریں
            
            if success:
                await update.message.reply_text("✅ تصویر بھیج دی گئی")
            else:
                await update.message.reply_text("❌ تصویر بھیجنے میں خرابی")
        
        # ویڈیو
        elif update.message.video:
            file = await update.message.video.get_file()
            file_path = f"temp_{datetime.now().timestamp()}.mp4"
            await file.download_to_drive(file_path)
            
            caption = update.message.caption or "🎥 ویڈیو"
            success = self.whatsapp.send_file(file_path, caption)
            
            os.remove(file_path)
            
            if success:
                await update.message.reply_text("✅ ویڈیو بھیج دی گئی")
            else:
                await update.message.reply_text("❌ ویڈیو بھیجنے میں خرابی")
        
        # دستاویز
        elif update.message.document:
            file = await update.message.document.get_file()
            file_name = update.message.document.file_name or f"doc_{datetime.now().timestamp()}"
            file_path = f"temp_{file_name}"
            await file.download_to_drive(file_path)
            
            caption = update.message.caption or "📄 دستاویز"
            success = self.whatsapp.send_file(file_path, caption)
            
            os.remove(file_path)
            
            if success:
                await update.message.reply_text("✅ دستاویز بھیج دی گئی")
            else:
                await update.message.reply_text("❌ دستاویز بھیجنے میں خرابی")
    
    def run(self):
        """بوٹ شروع کریں"""
        self.app.run_polling()

# ============================================
# Main Function
# ============================================
def main():
    global whatsapp, db
    
    print("🚀 بوٹ شروع ہو رہا ہے...")
    
    # ڈیٹا بیس کنیکٹ کریں
    db = Database()
    
    # واٹس ایپ کنٹرولر بنائیں
    whatsapp = WhatsAppController(db)
    
    # واٹس ایپ براؤزر الگ تھریڈ میں شروع کریں
    def start_whatsapp():
        print("📱 واٹس ایپ شروع ہو رہا ہے...")
        whatsapp.start_browser()
        
        # QR کوڈ حاصل کریں
        qr_retries = 0
        while qr_retries < 30 and not whatsapp.qr_generated:  # 5 منٹ تک کوشش
            qr = whatsapp.get_qr()
            if qr:
                print("✅ QR کوڈ جنریٹ ہو گیا")
            time.sleep(10)
            qr_retries += 1
        
        # لاگ ان کا انتظار کریں
        if whatsapp.wait_for_login():
            print("✅ واٹس ایپ تیار ہے")
    
    whatsapp_thread = threading.Thread(target=start_whatsapp)
    whatsapp_thread.daemon = True
    whatsapp_thread.start()
    
    # فلاسک سرور الگ تھریڈ میں شروع کریں
    def start_flask():
        app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)
    
    flask_thread = threading.Thread(target=start_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # ٹیلیگرام بوٹ شروع کریں
    telegram = TelegramBot(TELEGRAM_BOT_TOKEN, whatsapp, db)
    print("🤖 ٹیلیگرام بوٹ شروع ہو رہا ہے...")
    telegram.run()

if __name__ == '__main__':
    main()
