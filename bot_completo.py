import os
import requests
import logging
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ConversationHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURACIÓN ---
TOKEN = "8634912458:AAGEXyCQs0l_SV1PxttJ9bXxEo11GesWaGw"
SERP_API_KEY = "TU_API_KEY_AQUI" # <--- PEGA AQUÍ TU KEY DE SERPAPI

app_flask = Flask(__name__)
@app_flask.route('/')
def health(): return "Bot Binter Online", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host='0.0.0.0', port=port)

# --- BÚSQUEDA MEDIANTE SERPAPI (No se bloquea) ---
def buscar_vuelos_serp(b):
    vuelos_encontrados = []
    try:
        # Consultamos a Google Flights a través de SerpApi
        params = {
            "engine": "google_flights",
            "departure_id": b['origen'],
            "arrival_id": b['destino'],
            "outbound_date": b['fecha'],
            "currency": "EUR",
            "hl": "es",
            "api_key": SERP_API_KEY
        }
        response = requests.get("https://serpapi.com", params=params, timeout=20)
        data = response.json()
        
        # Filtramos los vuelos de Binter en el rango horario
        flights = data.get("best_flights", []) + data.get("other_flights", [])
        
        for flight in flights:
            for flight_info in flight.get("flights", []):
                # Verificamos si es Binter
                if "Binter" in flight_info.get("airline", ""):
                    # Extraemos la hora de salida (formato "YYYY-MM-DD HH:MM")
                    departure_time = flight_info.get("departure_airport", {}).get("time", "")
                    hora = departure_time.split(" ")[1] # Obtenemos HH:MM
                    
                    if b['hora_ini'] <= hora <= b['hora_fin']:
                        vuelos_encontrados.append(hora)
    except Exception as e:
        logger.error(f"Error en SerpApi: {e}")
    
    return sorted(list(set(vuelos_encontrados)))

# --- LÓGICA BOT ---
ORIGEN, DESTINO, FECHA, HORA_INI, HORA_FIN = range(5)
busquedas_activas = {}

async def monitor_callback(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    b = busquedas_activas.get(chat_id)
    if not b: return
    
    # Ejecutamos la búsqueda en un hilo para no bloquear el bot
    vuelos = await asyncio.to_thread(buscar_vuelos_serp, b)
    
    if vuelos:
        msg = f"✈️ **¡VUELOS ENCONTRADOS!**\n{b['origen']} ➔ {b['destino']} ({b['fecha']})\n\n✅ " + "\n✅ ".join(vuelos)
        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
        context.job.schedule_removal()
        del busquedas_activas[chat_id]

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
        "fecha": c.user_data["fecha"], "hora_ini": c.user_data["hora_ini"], "hora_fin": u.message.text
    }
    c.job_queue.run_repeating(monitor_callback, interval=300, first=5, chat_id=chat_id)
    await u.message.reply_text("✅ Monitor activado con API. Te avisaré pronto.")
    return ConversationHandler.END

if __name__ == "__main__":
    import asyncio
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
