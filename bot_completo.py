import sys
import asyncio
import httpx
import os
import re
from datetime import datetime

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    ContextTypes,
    filters
)

print(f"Ejecutando con Python {sys.version}")

# --- TOKEN ---
TOKEN = os.environ.get("TOKEN")

if not TOKEN:
    raise ValueError("No se encontró el TOKEN en las variables de entorno")

# --- Conversación ---
ORIGEN, DESTINO, FECHA, HORA_INI, HORA_FIN = range(5)

# --- búsquedas activas ---
busquedas = []

# ---------------------------
# COMANDOS TELEGRAM
# ---------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✈️ Bot buscador de vuelos directos Binter\nUsa /buscar para iniciar."
    )

async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Ejemplo:\nLPA TFN 2026-03-14 15:00 18:00"
    )

async def buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Origen (ej: LPA)")
    return ORIGEN

async def origen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["origen"] = update.message.text.upper()
    await update.message.reply_text("Destino (ej: TFN)")
    return DESTINO

async def destino(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["destino"] = update.message.text.upper()
    await update.message.reply_text("Fecha (AAAA-MM-DD)")
    return FECHA

async def fecha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["fecha"] = update.message.text
    await update.message.reply_text("Hora inicio (HH:MM)")
    return HORA_INI

async def hora_ini(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["hora_ini"] = update.message.text
    await update.message.reply_text("Hora fin (HH:MM)")
    return HORA_FIN

async def hora_fin(update: Update, context: ContextTypes.DEFAULT_TYPE):

    context.user_data["hora_fin"] = update.message.text

    busquedas.append({
        "chat_id": update.effective_chat.id,
        **context.user_data
    })

    await update.message.reply_text(
        f"✅ Búsqueda activada\n"
        f"{context.user_data['origen']} → {context.user_data['destino']}\n"
        f"{context.user_data['fecha']}\n"
        f"{context.user_data['hora_ini']} a {context.user_data['hora_fin']}"
    )

    return ConversationHandler.END

# ---------------------------
# BUSCAR VUELOS
# ---------------------------

async def buscar_vuelos(origen, destino, fecha):

    vuelos = []

    url = "https://www.bintercanarias.com/es/reserva-vuelos/"

    params = {
        "departure": origen,
        "arrival": destino,
        "departureDate": fecha
    }

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url, params=params)

    texto = r.text

    horas = re.findall(r"\d{2}:\d{2}", texto)

    for h in horas:
        vuelos.append(h)

    return list(set(vuelos))

# ---------------------------
# MONITOR
# ---------------------------

async def monitor(context: ContextTypes.DEFAULT_TYPE):

    app = context.application

    for b in list(busquedas):

        try:

            vuelos = await buscar_vuelos(
                b["origen"],
                b["destino"],
                b["fecha"]
            )

            hora_ini = datetime.strptime(b["hora_ini"], "%H:%M")
            hora_fin = datetime.strptime(b["hora_fin"], "%H:%M")

            for v in vuelos:

                hora_v = datetime.strptime(v, "%H:%M")

                if hora_ini <= hora_v <= hora_fin:

                    await app.bot.send_message(
                        chat_id=b["chat_id"],
                        text=f"🚨 Vuelo encontrado {b['origen']} → {b['destino']} a las {v}"
                    )

                    busquedas.remove(b)
                    break

        except Exception as e:
            print("Error monitor:", e)

# ---------------------------
# MAIN
# ---------------------------

def main():

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
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(conv_handler)

    # monitor cada 5 minutos
    app.job_queue.run_repeating(monitor, interval=300, first=10)

    print("Bot funcionando...")

    app.run_polling()

if __name__ == "__main__":
    main()