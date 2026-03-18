import sys
import re
import requests
import asyncio
import os
from threading import Thread
from datetime import datetime
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ConversationHandler, MessageHandler, ContextTypes, filters

# --- SERVIDOR AUXILIAR PARA RENDER ---
# Render necesita un puerto abierto para no matar el proceso
app_flask = Flask(__name__)
@app_flask.route('/')
def health_check(): return "Bot Vivo", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app_flask.run(host='0.0.0.0', port=port)

# --- CONFIGURACIÓN BOT ---
TOKEN = os.environ.get("TOKEN", "8634912458:AAHVJBE8vXTP9aLcfSQ3RbfcRRf2_qXVQl8")
ORIGEN, DESTINO, FECHA, HORA_INI, HORA_FIN = range(5)
busquedas_activas = {}

def buscar_vuelos_directo(b):
    vuelos_validos = []
    url_base = "https://google.com" # URL Corregida
    parametros = {
        "q": f"vuelos binter {b['origen']} a {b['destino']} {b['fecha']}",
        "hl": "es", "gl": "es"
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url_base, params=parametros, headers=headers, timeout=20)
        texto = response.text
        patrones_hora = re.findall(r'\b(?:[0-1]?[0-9]|2[0-3])[:\.\-][0-5][0-9]\b', texto)
        horas_limpias = [h.replace('.', ':').replace('-', ':').zfill(5) for h in patrones_hora]
        if any(x in texto for x in ["Binter", "Canarias", "NT"]):
            for h in set(horas_limpias):
                if b['hora_ini'] <= h <= b['hora_fin']:
                    vuelos_validos.append(h)
    except Exception as e:
        print(f"Error consulta: {e}")
    return sorted(list(set(vuelos_validos)))

async def monitor_callback(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    if chat_id not in busquedas_activas: return
    b = busquedas_activas[chat_id]
    vuelos = await asyncio.to_thread(buscar_vuelos_directo, b)
    if vuelos:
        msg = f"✈️ **¡VUELOS ENCONTRADOS!**\n{b['origen']} ➔ {b['destino']} ({b['fecha']})\n\n🕒 **Horas:**\n✅ " + "\n✅ ".join(vuelos)
        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
        context.job.schedule_removal()
        del busquedas_activas[chat_id]

# --- HANDLERS TELEGRAM ---
async def start(u, c): await u.message.reply_text("✈️ Monitor Binter Cloud.\nUsa /buscar.")
async def buscar(u, c): await u.message.reply_text("📍 Origen (LPA):"); return ORIGEN
async def origen(u, c): c.user_data["origen"] = u.message.text.upper(); await u.message.reply_text("🏁 Destino (TFN):"); return DESTINO
async def destino(u, c): c.user_data["destino"] = u.message.text.upper(); await u.message.reply_text("📅 Fecha (AAAA-MM-DD):"); return FECHA
async def fecha(u, c): c.user_data["fecha"] = u.message.text; await u.message.reply_text("🕒 Hora inicio (12:00):"); return HORA_INI
async def hora_ini(u, c): c.user_data["hora_ini"] = u.message.text; await u.message.reply_text("🕒 Hora fin (20:00):"); return HORA_FIN
async def hora_fin(u, c):
    c.user_data["hora_fin"] = u.message.text
    chat_id = u.effective_chat.id
    busquedas_activas[chat_id] = {
        "origen": c.user_data["origen"], "destino": c.user_data["destino"],
        "fecha": c.user_data["fecha"], "hora_ini": c.user_data["hora_ini"].zfill(5),
        "hora_fin": c.user_data["hora_fin"].zfill(5)
    }
    c.job_queue.run_repeating(monitor_callback, interval=180, first=5, chat_id=chat_id)
    await u.message.reply_text("✅ Monitor activado en la nube. Te avisaré por aquí.")
    return ConversationHandler.END

if __name__ == "__main__":
    # Lanzar servidor web en segundo plano
    Thread(target=run_flask).start()
    
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
    print("🚀 BOT NATIVO CLOUD LISTO")
    app.run_polling()
