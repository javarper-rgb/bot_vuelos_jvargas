import os
import asyncio
import requests
import logging
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ConversationHandler, MessageHandler, ContextTypes, filters

# --- LOGS ---
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURACIÓN ---
TOKEN = "8634912458:AAGEXyCQs0l_SV1PxttJ9bXxEo11GesWaGw"
# Intentará leer la clave de Render, si no, usa la que pongas aquí
SERP_API_KEY = os.environ.get("SERP_API_KEY", "TU_CLAVE_AQUI_SI_NO_USAS_RENDER_VARS")

# --- SERVIDOR AUXILIAR ---
app_flask = Flask(__name__)
@app_flask.route('/')
def health(): return "Bot Binter API Online", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host='0.0.0.0', port=port)

# --- BÚSQUEDA PROFESIONAL (SerpApi) ---
def buscar_vuelos_serp(b):
    vuelos_validos = []
    try:
        params = {
            "engine": "google_flights",
            "departure_id": b['origen'],
            "arrival_id": b['destino'],
            "outbound_date": b['fecha'],
            "currency": "EUR",
            "hl": "es",
            "api_key": SERP_API_KEY
        }
        logger.info(f"Consultando SerpApi para {b['origen']}->{b['destino']}")
        response = requests.get("https://serpapi.com", params=params, timeout=30)
        data = response.json()
        
        # Google Flights devuelve los resultados en estas dos listas
        resultados = data.get("best_flights", []) + data.get("other_flights", [])
        
        for itinerario in resultados:
            for vuelo in itinerario.get("flights", []):
                # Filtramos por Binter
                if "Binter" in vuelo.get("airline", ""):
                    # La hora viene como '2025-03-20 14:30'
                    full_departure = vuelo.get("departure_airport", {}).get("time", "")
                    if full_departure:
                        hora_solo = full_departure.split(" ")[1] # Extrae '14:30'
                        if b['hora_ini'] <= hora_solo <= b['hora_fin']:
                            vuelos_validos.append(hora_solo)
                            
    except Exception as e:
        logger.error(f"Error consultando SerpApi: {e}")
    
    return sorted(list(set(vuelos_validos)))

# --- BOT HANDLERS ---
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
        logger.info(f"Monitor: Sin vuelos para {chat_id} todavía.")

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
        "fecha": c.user_data["fecha"], "hora_ini": c.user_data["hora_ini"], "hora_fin": u.message.text
    }
    c.job_queue.run_repeating(monitor_callback, interval=300, first=5, chat_id=chat_id)
    await u.message.reply_text("✅ **Monitor activado.** Te avisaré en cuanto aparezca un vuelo.")
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
    logger.info("🚀 Bot arrancando con SerpApi...")
    app.run_polling(drop_pending_updates=True)
