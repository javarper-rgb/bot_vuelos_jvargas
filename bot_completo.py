import os
import asyncio
import re
import logging
from threading import Thread
from flask import Flask
from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ConversationHandler, MessageHandler, ContextTypes, filters

# --- CONFIGURACIÓN DE LOGS ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURACIÓN DIRECTA ---
TOKEN = "8634912458:AAGXOXd9tWJx1r0c2coRmOLonhTIIs7-h3k"

# --- SERVIDOR WEB (Para Render) ---
app_flask = Flask(__name__)

@app_flask.route('/')
def health():
    return "Bot Binter Cloud Online", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Servidor Flask en puerto {port}")
    app_flask.run(host='0.0.0.0', port=port)

# --- LÓGICA DEL BOT ---
ORIGEN, DESTINO, FECHA, HORA_INI, HORA_FIN = range(5)
busquedas_activas = {}

async def buscar_vuelos_playwright(b):
    vuelos_validos = []
    async with async_playwright() as p:
        try:
            # User-Agent real para que Google no nos detecte como Bot básico
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
            
            browser = await p.chromium.launch(
                headless=True, 
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
            )
            
            context = await browser.new_context(user_agent=user_agent)
            page = await context.new_page()
            
            # Búsqueda optimizada
            query = f"vuelos binter de {b['origen']} a {b['destino']} el {b['fecha']}"
            url = f"https://google.com{query.replace(' ', '+')}&hl=es"
            
            logger.info(f"Navegando a Google: {url}")
            await page.goto(url, wait_until="networkidle", timeout=60000)
            
            # Esperamos a que carguen los elementos dinámicos
            await page.wait_for_timeout(5000) 
            content = await page.content()
            
            # Extraer horas (HH:MM)
            patrones_hora = re.findall(r'\b(?:[0-1]?[0-9]|2[0-3])[:][0-5][0-9]\b', content)
            logger.info(f"Horas detectadas en bruto: {patrones_hora}")
            
            # Filtrado por rango horario del usuario
            if "Binter" in content or "Canarias" in content or "vuelos" in content:
                for h in set(patrones_hora):
                    if b['hora_ini'] <= h <= b['hora_fin']:
                        vuelos_validos.append(h)
            
            await browser.close()
        except Exception as e:
            logger.error(f"Error en Playwright: {e}")
            
    return sorted(list(set(vuelos_validos)))

async def monitor_callback(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    if chat_id not in busquedas_activas: return
    
    b = busquedas_activas[chat_id]
    logger.info(f"Buscando vuelos para el chat {chat_id}...")
    
    vuelos = await buscar_vuelos_playwright(b)
    
    if vuelos:
        msg = f"✈️ **¡VUELOS ENCONTRADOS!**\n{b['origen']} ➔ {b['destino']} ({b['fecha']})\n\n🕒 **Horas disponibles:**\n✅ " + "\n✅ ".join(vuelos)
        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
        context.job.schedule_removal()
        del busquedas_activas[chat_id]
    else:
        logger.info(f"No se encontraron vuelos para {chat_id} en esta pasada.")

# --- HANDLERS ---
async def start(u: Update, c):
    await u.message.reply_text("✈️ **Monitor Binter Cloud Activo**\nUsa /buscar para empezar.")

async def buscar(u: Update, c):
    await u.message.reply_text("📍 Origen (ej: LPA):")
    return ORIGEN

async def origen(u: Update, c):
    c.user_data["origen"] = u.message.text.upper()
    await u.message.reply_text("🏁 Destino (ej: TFN):")
    return DESTINO

async def destino(u: Update, c):
    c.user_data["destino"] = u.message.text.upper()
    await u.message.reply_text("📅 Fecha (AAAA-MM-DD):")
    return FECHA

async def fecha(u: Update, c):
    c.user_data["fecha"] = u.message.text
    await u.message.reply_text("🕒 Hora inicio (ej: 08:00):")
    return HORA_INI

async def hora_ini(u: Update, c):
    c.user_data["hora_ini"] = u.message.text
    await u.message.reply_text("🕒 Hora fin (ej: 22:00):")
    return HORA_FIN

async def hora_fin(u: Update, c):
    chat_id = u.effective_chat.id
    busquedas_activas[chat_id] = {
        "origen": c.user_data["origen"], "destino": c.user_data["destino"],
        "fecha": c.user_data["fecha"], "hora_ini": c.user_data["hora_ini"],
        "hora_fin": u.message.text
    }
    # Revisión cada 5 min
    c.job_queue.run_repeating(monitor_callback, interval=300, first=5, chat_id=chat_id)
    await u.message.reply_text("✅ **Monitor activado.** Revisaré cada 5 minutos y te avisaré si hay vuelos.")
    return ConversationHandler.END

# --- INICIO ---
if __name__ == "__main__":
    # 1. Servidor Flask
    Thread(target=run_flask, daemon=True).start()
    
    # 2. Configurar Bot
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
    
    logger.info("🚀 Iniciando Bot con Token Nuevo...")
    
    # drop_pending_updates limpia mensajes antiguos y evita el error Conflict
    app.run_polling(drop_pending_updates=True)

