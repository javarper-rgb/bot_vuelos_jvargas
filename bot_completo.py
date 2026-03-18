import os
import asyncio
import re
import logging
from threading import Thread
from flask import Flask
from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ConversationHandler, MessageHandler, ContextTypes, filters

# --- LOGGING PARA DEPURACIÓN ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- SERVIDOR WEB (Obligatorio para Render) ---
app_flask = Flask(__name__)

@app_flask.route('/')
def health():
    return "Bot de Vuelos Binter Activo", 200

def run_flask():
    # Render asigna el puerto automáticamente en la variable PORT
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Iniciando servidor Flask en puerto {port}")
    app_flask.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# --- CONFIGURACIÓN BOT ---
TOKEN = os.environ.get("8634912458:AAHVJBE8vXTP9aLcfSQ3RbfcRRf2_qXVQl8")
ORIGEN, DESTINO, FECHA, HORA_INI, HORA_FIN = range(5)
busquedas_activas = {}

# --- LÓGICA DE BÚSQUEDA (Playwright) ---
async def buscar_vuelos_playwright(b):
    vuelos_validos = []
    async with async_playwright() as p:
        try:
            # Flags esenciales para correr en Docker/Render sin errores de permisos
            browser = await p.chromium.launch(
                headless=True, 
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
            )
            page = await browser.new_page()
            
            query = f"vuelos binter {b['origen']} a {b['destino']} {b['fecha']}"
            logger.info(f"Buscando en Google: {query}")
            
            # Navegar con tiempo de espera generoso
            await page.goto(f"https://google.com{query}&hl=es", timeout=60000)
            content = await page.content()
            
            # Extraer horas del contenido
            patrones_hora = re.findall(r'\b(?:[0-1]?[0-9]|2[0-3])[:][0-5][0-9]\b', content)
            
            if any(x in content for x in ["Binter", "Canarias", "NT"]):
                for h in set(patrones_hora):
                    if b['hora_ini'] <= h <= b['hora_fin']:
                        vuelos_validos.append(h)
            
            await browser.close()
        except Exception as e:
            logger.error(f"Error en Playwright: {e}")
    return sorted(list(set(vuelos_validos)))

async def monitor_callback(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    b = busquedas_activas.get(chat_id)
    if not b: return
    
    logger.info(f"Ejecutando revisión automática para {chat_id}")
    vuelos = await buscar_vuelos_playwright(b)
    
    if vuelos:
        msg = f"✈️ **¡VUELOS ENCONTRADOS!**\n{b['origen']} ➔ {b['destino']} ({b['fecha']})\n\n🕒 **Horas detectadas:**\n✅ " + "\n✅ ".join(vuelos)
        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
        # Detener el monitor tras encontrar éxito
        context.job.schedule_removal()
        del busquedas_activas[chat_id]

# --- HANDLERS DE TELEGRAM ---
async def start(u: Update, c):
    await u.message.reply_text("✈️ **Monitor Binter (Cloud Edition)**\nUsa /buscar para configurar una alerta.")

async def buscar(u: Update, c):
    await u.message.reply_text("📍 Indica el código de **Origen** (ej: LPA):")
    return ORIGEN

async def origen(u: Update, c):
    c.user_data["origen"] = u.message.text.upper()
    await u.message.reply_text("🏁 Indica el código de **Destino** (ej: TFN):")
    return DESTINO

async def destino(u: Update, c):
    c.user_data["destino"] = u.message.text.upper()
    await u.message.reply_text("📅 Fecha (**AAAA-MM-DD**):")
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
    # Revisar cada 5 minutos (300 segundos)
    c.job_queue.run_repeating(monitor_callback, interval=300, first=10, chat_id=chat_id)
    await u.message.reply_text("✅ **Monitor activado.** Te avisaré por aquí en cuanto detecte vuelos en ese rango.")
    return ConversationHandler.END

async def cancel(u: Update, c):
    await u.message.reply_text("Operación cancelada.")
    return ConversationHandler.END

# --- BLOQUE PRINCIPAL ---
if __name__ == "__main__":
    if not TOKEN:
        logger.error("❌ ERROR: No se ha configurado la variable de entorno TOKEN.")
    else:
        # 1. Lanzar servidor web en un hilo secundario
        Thread(target=run_flask, daemon=True).start()
        
        # 2. Configurar aplicación de Telegram
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
            fallbacks=[CommandHandler("cancel", cancel)]
        )
        
        app.add_handler(CommandHandler("start", start))
        app.add_handler(conv_handler)
        
        logger.info("🚀 Bot arrancando en Render...")
        
        # drop_pending_updates=True es vital para que el bot no se bloquee con mensajes antiguos
        app.run_polling(drop_pending_updates=True)
