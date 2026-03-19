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

TOKEN = os.environ.get("TOKEN")
SERP_API_KEY = os.environ.get("SERP_API_KEY")

app_flask = Flask(__name__)
@app_flask.route('/')
def health(): return "Bot Binter API Online", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host='0.0.0.0', port=port)

def buscar_vuelos_serp(b):
    vuelos_validos = []
    if not SERP_API_KEY:
        logger.error("❌ FALTA SERP_API_KEY")
        return []

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
        
        response = requests.get("https://serpapi.com", params=params, timeout=30)
        
        # DEBUG: Ver qué responde la API si falla
        if response.status_code != 200:
            logger.error(f"❌ Error API ({response.status_code}): {response.text}")
            return []

        data = response.json()
        itinerarios = data.get("best_flights", []) + data.get("other_flights", [])
        
        if not itinerarios:
            logger.info("ℹ️ No hay vuelos en Google Flights para esta fecha.")

        for iti in itinerarios:
            for vuelo in iti.get("flights", []):
                if "Binter" in vuelo.get("airline", ""):
                    salida = vuelo.get("departure_airport", {}).get("time", "")
                    if salida:
                        hora_solo = salida.split(" ")[-1]
                        if b['hora_ini'] <= hora_solo <= b['hora_fin']:
                            vuelos_validos.append(hora_solo)
                            
    except Exception as e:
        logger.error(f"❌ Error crítico: {e}")
    
    return sorted(list(set(vuelos_validos)))

# --- RESTO DEL CÓDIGO (Igual al anterior) ---
ORIGEN, DESTINO, FECHA, HORA_INI, HORA_FIN = range(5)
busquedas_activas = {}

async def monitor_callback(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    if chat_id not in busquedas_activas: return
    vuelos = await asyncio.to_thread(buscar_vuelos_serp, busquedas_activas[chat_id])
    if vuelos:
        msg = f"✈️ **¡VUELOS!**\n{busquedas_activas[chat_id]['origen']}➔{busquedas_activas[chat_id]['destino']}\n✅ " + "\n✅ ".join(vuelos)
        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
        context.job.schedule_removal()
        del busquedas_activas[chat_id]

async def start(u, c): await u.message.reply_text("✈️ Monitor Binter.\nUsa /buscar.")
async def buscar(u, c): await u.message.reply_text("📍 Origen:"); return ORIGEN
async def origen(u, c): c.user_data["origen"] = u.message.text.upper(); await u.message.reply_text("🏁 Destino:"); return DESTINO
async def destino(u, c): c.user_data["destino"] = u.message.text.upper(); await u.message.reply_text("📅 Fecha (AAAA-MM-DD):"); return FECHA
async def fecha(u, c): c.user_data["fecha"] = u.message.text; await u.message.reply_text("🕒 Hora inicio (08:00):"); return HORA_INI
async def hora_ini(u, c): c.user_data["hora_ini"] = u.message.text; await u.message.reply_text("🕒 Hora fin (22:00):"); return HORA_FIN
async def hora_fin(u, c):
    busquedas_activas[u.effective_chat.id] = {
        "origen": c.user_data["origen"], "destino": c.user_data["destino"],
        "fecha": c.user_data["fecha"], "hora_ini": c.user_data["hora_ini"], "hora_fin": u.message.text
    }
    c.job_queue.run_repeating(monitor_callback, interval=300, first=5, chat_id=u.effective_chat.id)
    await u.message.reply_text("✅ Monitor activado.")
    return ConversationHandler.END

if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("buscar", buscar)],
        states={ORIGEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, origen)], DESTINO: [MessageHandler(filters.TEXT & ~filters.COMMAND, destino)], FECHA: [MessageHandler(filters.TEXT & ~filters.COMMAND, fecha)], HORA_INI: [MessageHandler(filters.TEXT & ~filters.COMMAND, hora_ini)], HORA_FIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, hora_fin)]},
        fallbacks=[]
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.run_polling(drop_pending_updates=True)
