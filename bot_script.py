from fastapi import FastAPI, Request
import os
import requests
from openai import OpenAI

app = FastAPI()

# --- Validación de variables de entorno ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

if not OPENAI_API_KEY:
    raise ValueError("Falta la variable de entorno OPENAI_API_KEY")
if not TELEGRAM_TOKEN:
    raise ValueError("Falta la variable de entorno TELEGRAM_TOKEN")

# --- Configuración de clientes y URLs ---
client = OpenAI(api_key=OPENAI_API_KEY)
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

# --- Información del negocio ---
system_prompt = """
Eres un asistente virtual de Go Waffles. Solo responde preguntas sobre el negocio usando la información disponible.
Habla de manera juvenil y cercana, usando emojis donde sea apropiado.
No inventes precios, horarios, promociones ni contactos que no estén en la información proporcionada.
Tu objetivo es responder de forma clara, humana y divertida.
"""

info_negocio = {
    "ubicacion": "El local se encuentra ubicado en Avenida Gabriel González Videla 3170, La Serena.",
    "horarios": "De lunes a viernes entre las 16:00 y 21:00. Sábado y domingo entre 15:30 y 21:30.",
    "promociones": "15% de descuento usando el cupón PRIMERACOMPRA en gowaffles.cl",
    "canales_venta": "Puedes comprar en tu delivery app favorita (UberEats, PedidosYa o Rappi) o a través de nuestra página web gowaffles.cl",
    "carta": "Encuentra todos nuestros productos en gowaffles.cl/pedir",
    "trabajo": "Si quieres trabajar con nosotros, puedes escribir a contacto@gowaffles.cl o rellenar el formulario en gowaffles.cl/nosotros",
    "problemas": "Si tuviste algún inconveniente con tu pedido escríbenos a contacto@gowaffles.cl",
    "ejecutivo": "Si necesitas hablar con un encargado del local, comunícate al https://wa.me/56953717707"
}

def generar_contexto(info):
    contexto = "Aquí tienes información de referencia sobre Go Waffles que puedes usar para responder:\n"
    for clave, valor in info.items():
        contexto += f"- {clave.capitalize()}: {valor}\n"
    contexto += "\nUsa esta información solo si aplica a la pregunta del usuario.\n"
    return contexto

def responder_pregunta(pregunta):
    contexto = generar_contexto(info_negocio)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"{contexto}\nPregunta del usuario: {pregunta}"}
    ]

    respuesta = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=messages,
        temperature=0.3
    )

    return respuesta.choices[0].message.content

# --- ENDPOINT TELEGRAM ---
@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    data = await request.json()
    print("Recibido de Telegram:", data)  # útil para logs en Railway

    try:
        mensaje = data["message"]["text"]
        chat_id = data["message"]["chat"]["id"]
    except KeyError:
        print("Mensaje no contiene texto o chat_id. Ignorado.")
        return {"status": "ignored"}

    try:
        respuesta = responder_pregunta(mensaje)
        print(f"Respondiendo a {chat_id}: {respuesta}")
    except Exception as e:
        print(f"Error al generar respuesta con OpenAI: {e}")
        respuesta = "¡Ups! Tuve un pequeño problema, pero ya lo estoy resolviendo. ¿Puedes repetir tu pregunta? 🧇"

    try:
        response = requests.post(TELEGRAM_URL, json={"chat_id": chat_id, "text": respuesta})
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error al enviar mensaje a Telegram: {e}")
        return {"status": "error", "detalle": str(e)}

    return {"status": "ok"}

# --- ENDPOINT WEB (para pruebas o frontend) ---
@app.post("/webhook/web")
async def web_webhook(request: Request):
    data = await request.json()
    try:
        mensaje = data["mensaje"]
    except KeyError:
        return {"status": "error", "detalle": "no se recibió 'mensaje'"}

    try:
        respuesta = responder_pregunta(mensaje)
        return {"respuesta": respuesta}
    except Exception as e:
        return {"status": "error", "detalle": str(e)}

# --- Endpoints de salud (opcional pero útil en Railway) ---
@app.get("/health")
async def health_check():
    return {"status": "ok"}
