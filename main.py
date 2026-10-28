import os
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from telegram.ext import Application, CommandHandler, MessageHandler, filters

# Clase para simular un servidor web básico
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot activo")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    server.serve_forever()

# --- FUNCIONES DEL BOT ---
async def start(update, context):
    await update.message.reply_text("¡Hola! Soy tu primer bot en la nube.")

async def responder(update, context):
    texto_usuario = update.message.text
    await update.message.reply_text(f"Me dijiste: {texto_usuario}")

if __name__ == '__main__':
    TOKEN = os.environ.get("TELEGRAM_TOKEN")
    
    # Iniciar el servidor web en un hilo secundario
    threading.Thread(target=run_web_server, daemon=True).start()
    
    # Iniciar el bot de Telegram
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder))
    
    print("El bot está funcionando...")
    app.run_polling()
