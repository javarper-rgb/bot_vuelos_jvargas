import os
import asyncio
import requests
import logging
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ConversationHandler, MessageHandler, ContextTypes, filters

# --- LOGS DETALLADOS ---
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- VARIABLES DE ENTORNO ---
TOKEN = os.environ.get("TOKEN")
SERP_API_KEY = os.environ.get("SERP_API_KEY")

# --- SERVIDOR WEB (Para Render) ---
app_flask = Flask(__name__)
@app_flask.route('/')
def health(): return "Bot Binter API Online", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host='0.0.0.0', port=port)

# --- FUNCIÓN DE BÚSQUEDA CON DEPURACIÓN ---
def buscar_vuelos_serp(b):
    vuelos_validos = []
    
    # 1. Verificar si la Key existe en Render
    if not SERP_API_KEY:
        logger.error("❌ ERROR: La variable SERP_API_KEY está VACÍA en las Settings de Render.")
        return []
    
    logger.info(f"🔑 Usando API Key (inicia con): {SERP_API_KEY[:5]}...")

    try:
        # 2. Parámetros y Headers (Simulando navegador para evitar bloqueos)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        params = {
            "engine": "google_flights",
            "departure_id": b['origen'],
            "arrival_id": b['destino'],
            "outbound_date": b['fecha'],
            "currency": "EUR",
            "hl": "es",
            "api_key": SERP_API_KEY
        }
        
        url = "https://serpapi.com"
        logger.info(f"📡 Enviando petición a SerpApi para {b['origen']} ➔ {b['destino']}...")
        
        response = requests.get(url, params=params, headers=headers, timeout=30)
        
        # 3. Capturar errores de respuesta
        if response.status_code != 200:
            logger.error(f"❌ Error API (Status {response.status_code}): {response.text}")
            return []

        # 4. Procesar JSON
        try:
            data = response.json()
        except Exception:
            logger.error(f"❌ La respuesta no es un JSON válido. Texto recibido: {response.text[:200]}")
            return []

        # Unimos vuelos 'Mejores' y 'Otros'
        itinerarios = data.get("best_flights", []) + data.get("other_flights", [])
        
        if not itinerarios:
            logger.info("ℹ️ SerpApi no devolvió vuelos para esta ruta/fecha.")

        for iti in itinerarios:
            for vuelo in iti.get("flights", []):
                # Filtramos por Binter
                if "Binter" in vuelo.get("airline", ""):
                    salida = vuelo.get("departure_airport", {}).get("time", "")
                    if salida:
                        # Extraemos HH:MM (asumiendo formato 'YYYY-MM-DD HH:MM')
                        hora_solo = salida.split(" ")[-1]
                        if b['hora_ini'] <= hora_solo <= b['hora_fin']:
                            vuelos_validos.append(hora_solo)
                            
    except Exception as e:
        logger.error(f"❌ Error crítico en la petición: {str(e)}")
    
    return sorted(list(set(vuelos_validos)))

# --- LÓGICA DEL BOT ---
ORIGEN, DESTINO, FECHA, HORA_INI, HORA_FIN = range(5)
busquedas_activas = {}

async def monitor_callback(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    if chat_id not in busquedas_activas: return
    
    b = busquedas_activas[chat_id]
    vuelos = await asyncio.to_thread(buscar_vuelos_serp, b)
    
    if vuelos:
        msg = f"✈️ **¡VUELOS ENCONTRADOS!**\n{b['origen']} ➔ {b['destino']} ({b['fecha']})\n\n✅ " + "\n✅ ".join(vuelos)
        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
        context.job.schedule_removal()
        del busquedas_activas[chat_id]
    else:
        logger.info(f"Monitor: Sin resultados aún para el chat {chat_id}")

# --- HANDLERS ---
async def start(u, c): await u.message.reply_text("✈️ Monitor Binter Cloud.\nUsa /buscar.")
async def buscar(u, c): await u.message.reply_text("📍 Origen (LPA):"); return ORIGEN
async def origen(u, c): c.user_data["origen"] = u.message.text.upper(); await u.message.reply_text("🏁 Destino (TFN):"); return DESTINO
async def destino(u, c): c.user_data["destino"] = u.message.text.upper(); await u.message.reply_text("📅 Fecha (AAAA-MM-DD):"); return FECHA
async def fecha(u, c): c.user_data["fecha"] = u.message.text; await u.message.reply_text("🕒 Hora inicio (08:00):"); return HORA_INI
async def hora_ini(u, c): c.user_data["hora_ini"] = u.message.text; await u.message.reply_text("🕒 Hora fin (22:00):"); return HORA_FIN
async def hora_fin(u, c):
    chat_id = u.effective_chat.id
    busquedas_activas[chat_id] = {
        "origen": c.user_data["origen"], "destino": c.user_data["destino"],
        "fecha": c.user_data["fecha"], "hora_ini": c.user_data["hora_ini"],
        "hora_fin": u.message.text
    }
    c.job_queue.run_repeating(monitor_callback, interval=300, first=5, chat_id=chat_id)
    await u.message.reply_text("✅ **Monitor activado.** Te avisaré en cuanto haya vuelos disponibles.")
    return ConversationHandler.END

if __name__ == "__main__":
    if not TOKEN:
        logger.error("❌ ERROR: Falta la variable TOKEN en Render.")
        exit(1)

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
