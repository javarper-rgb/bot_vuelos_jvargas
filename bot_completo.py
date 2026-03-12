import sys
import asyncio
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
import os
from playwright.async_api import async_playwright

# --- DEBUG: Comprobar versión de Python ---
print(f"Ejecutando con Python {sys.version}")
REQUIRED_PYTHON = (3, 12, 16)
if sys.version_info < REQUIRED_PYTHON:
    raise RuntimeError(
        f"ERROR: Necesitas Python >= {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}.{REQUIRED_PYTHON[2]}, "
        f"pero estás usando {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )

# Obtener el token de la variable de entorno
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise ValueError(
        "No se encontró el TOKEN en las variables de entorno. "
        "Asegúrate de configurarlo en Render."
    )

# Variables para el manejo de conversaciones en Telegram
ORIGEN, DESTINO, FECHA, HORA_INI, HORA_FIN = range(5)

# Lista donde se guardarán las búsquedas activas
busquedas = []

# --- Funciones de conversación ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✈️ Bot buscador de vuelos directos Binter\nUsa /buscar para iniciar búsqueda."
    )

async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Ejemplo: LPA TFN 2026-03-14 15:00 16:00"
    )

async def buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Origen (ejemplo: LPA)")
    return ORIGEN

async def origen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["origen"] = update.message.text.upper()
    await update.message.reply_text("Destino (ejemplo: TFN)")
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
        f"✅ Búsqueda activada:\n"
        f"{context.user_data['origen']} → {context.user_data['destino']}\n"
        f"📅 {context.user_data['fecha']}\n"
        f"🕒 {context.user_data['hora_ini']} a {context.user_data['hora_fin']}\n"
        f"Te avisaré si hay vuelos directos."
    )
    return ConversationHandler.END

# --- Función de búsqueda en Binter ---
async def buscar_vuelos(origen, destino, fecha):
    vuelos_disponibles = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://www.bintercanarias.com/es/reserva-vuelos/")
        await page.fill('input[name="departure"]', origen)
        await page.fill('input[name="arrival"]', destino)
        await page.fill('input[name="departureDate"]', fecha)
        await page.click('button[type="submit"]')
        await page.wait_for_selector(".flight-result")  # Ajustar según la web
        vuelos = await page.query_selector_all(".flight-result .flight-time")
        for v in vuelos:
            hora = await v.inner_text()
            vuelos_disponibles.append(hora.strip())
        await browser.close()
    return vuelos_disponibles

# --- Monitor con job_queue ---
async def monitor(context: ContextTypes.DEFAULT_TYPE):
    app = context.application
    for b in list(busquedas):
        try:
            vuelos = await buscar_vuelos(b["origen"], b["destino"], b["fecha"])
            hora_ini = datetime.strptime(b["hora_ini"], "%H:%M")
            hora_fin = datetime.strptime(b["hora_fin"], "%H:%M")
            for v in vuelos:
                hora_v = datetime.strptime(v, "%H:%M")
                if hora_ini <= hora_v <= hora_fin:
                    await app.bot.send_message(
                        chat_id=b["chat_id"],
                        text=f"🚨 Vuelo directo disponible: {b['origen']} → {b['destino']} a las {v}"
                    )
                    busquedas.remove(b)
                    break
        except Exception as e:
            print("Error monitor:", e)

# --- MAIN ---
def main():
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

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

    # --- Job queue para monitor ---
    app.job_queue.run_repeating(monitor, interval=300, first=10)  # cada 5 minutos

    print("Bot @vuelos_jvargas_bot funcionando...")
    app.run_polling()

if __name__ == "__main__":
    main()