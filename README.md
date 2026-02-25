# Telegram-WhatsApp Bridge Bot 🔗

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/mrwasif-dev/whatsapp-telegram-bridge)

A powerful bridge bot that forwards messages and media from Telegram to WhatsApp. Scan QR code, set target number, and start forwarding!

## ✨ Features

- 🔄 **Two-way Bridge**: Forward messages from Telegram to WhatsApp
- 📸 **Media Support**: Photos, videos, documents, audio files
- 🎯 **Target Management**: Set and change WhatsApp target number
- 📱 **QR Code Authentication**: Easy WhatsApp Web login
- 💾 **Session Persistence**: Sessions saved in MongoDB
- 🛡️ **Admin Controls**: Special commands for administrators
- 📊 **Status Monitoring**: Check connection status anytime

## 📋 Prerequisites

Before deploying, make sure you have:

- A [Telegram Bot Token](https://t.me/botfather) (from @BotFather)
- A [MongoDB](https://www.mongodb.com/atlas) database (MongoDB Atlas free tier works)
- A [Heroku](https://heroku.com) account
- (Optional) WhatsApp number with WhatsApp installed on phone

## 🚀 Quick Deployment

### One-Click Heroku Deployment

[![Deploy to Heroku](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/mrwasif-dev/whatsapp-telegram-bridge)

1. Click the button above
2. Fill in the config vars:
   - `TELEGRAM_BOT_TOKEN`: Your bot token from @BotFather
   - `MONGODB_URI`: Your MongoDB connection string
   - `ADMIN_IDS`: (Optional) Comma-separated Telegram user IDs
   - `DEFAULT_TARGET`: (Optional) Default WhatsApp number
3. Deploy the app
4. Scale both web and worker dynos:
   ```bash
   heroku ps:scale web=1 worker=1 -a your-app-name
