import os
import asyncio
import re
import logging
from threading import Thread
from flask import Flask
from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ConversationHandler, MessageHandler, ContextTypes, filters

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURACIÓN ---
# Token insertado directamente para evitar errores de variables de entorno
TOKEN = "8634912458:AAHVJBE8vXTP9aLcfSQ3RbfcRRf2_qXVQl8"

# --- SERVIDOR WEB ---
app_flask = Flask(__name__)
@app_flask.route('/')
def health(): return "Bot Binter Online", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app_flask.run(host='0.0.0.0', port=port)

# --- BOT LOGIC ---
ORIGEN, DESTINO, FECHA, HORA_INI, HORA_FIN = range(5)
busquedas_activas = {}

async def buscar_vuelos_playwright(b):
    vuelos_validos = []
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
            page = await browser.new_page()
            query = f"vuelos binter {b['origen']} a {b['destino']} {b['fecha']}"
            await page.goto(f"https://google.com{query}&hl=es", timeout=60000)
            content = await page.content()
            patrones_hora = re.findall(r'\b(?:[0-1]?[0-9]|2[0-3])[:][0-5][0-9]\b', content)
            if any(x in content for x in ["Binter", "Canarias", "NT"]):
                for h in set(patrones_hora):
                    if b['hora_ini'] <= h <= b['hora_fin']:
                        vuelos_validos.append(h)
            await browser.close()
        except Exception as e:
            logger.error(f"Error búsqueda: {e}")
    return sorted(list(set(vuelos_validos)))

async def monitor_callback(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    if chat_id not in busquedas_activas: return
    b = busquedas_activas[chat_id]
    vuelos = await buscar_vuelos_playwright(b)
    if vuelos:
        msg = f"✈️ **VUELOS ENCONTRADOS**\n{b['origen']} -> {b['destino']}\n✅ " + "\n✅ ".join(vuelos)
        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
        context.job.schedule_removal()
        del busquedas_activas[chat_id]

# --- HANDLERS ---
async def start(u, c): await u.message.reply_text("✈️ Monitor Binter Cloud. Usa /buscar.")
async def buscar(u, c): await u.message.reply_text("📍 Origen (LPA):"); return ORIGEN
async def origen(u, c): c.user_data["origen"] = u.message.text.upper(); await u.message.reply_text("🏁 Destino (TFN):"); return DESTINO
async def destino(u, c): c.user_data["destino"] = u.message.text.upper(); await u.message.reply_text("📅 Fecha (AAAA-MM-DD):"); return FECHA
async def fecha(u, c): c.user_data["fecha"] = u.message.text; await u.message.reply_text("🕒 Hora inicio (12:00):"); return HORA_INI
async def hora_ini(u, c): c.user_data["hora_ini"] = u.message.text; await u.message.reply_text("🕒 Hora fin (20:00):"); return HORA_FIN
async def hora_fin(u, c):
    chat_id = u.effective_chat.id
    busquedas_activas[chat_id] = {
        "origen": c.user_data["origen"], "destino": c.user_data["destino"],
        "fecha": c.user_data["fecha"], "hora_ini": c.user_data["hora_ini"], "hora_fin": u.message.text
    }
    c.job_queue.run_repeating(monitor_callback, interval=300, first=5, chat_id=chat_id)
    await u.message.reply_text("✅ Monitor activado.")
    return ConversationHandler.END

if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("buscar", buscar)],
        states={
            ORIGEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, origen)],
            DESTINO: [MessageHandler(filters.TEXT & ~filters.COMMAND, destino)],
            FECHA: [MessageHandler(filters.TEXT & ~filters.COMMAND, fecha)],
            HORA_INI: [MessageHandler(filters.TEXT & ~filters.COMMAND, hora_ini)],
            HORA_FIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, hora_fin)],
        },
        fallbacks=[]
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    logger.info("🚀 Bot arrancando...")
    app.run_polling(drop_pending_updates=True)
