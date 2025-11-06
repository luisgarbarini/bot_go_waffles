from datetime import datetime
import pytz
from fastapi import FastAPI, Request
import os
import requests
import time
from openai import OpenAI
from fuzzywuzzy import process

app = FastAPI()

# Configuración de Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage" if TELEGRAM_TOKEN else ""

# Caché del menú
_menu_cache = None
_menu_last_fetch = 0

# Tu info de negocio (sin cambios)
info_negocio = {
    "ubicacion": "Estamos ubicados en Avenida Gabriel González Videla 3170, La Serena. También puedes encontrarnos en google maps como 'Go Waffles'.",
    "horarios": "De lunes a viernes entre las 16:00 y 21:00. Sábado y domingo entre 15:30 y 21:30.",
    "promociones": "Tenemos un 15% de descuento usando el cupón PRIMERACOMPRA en gowaffles.cl",
    "canales_venta": "Puedes comprar en tu delivery app favorita (UberEats, PedidosYa o Rappi) o a través de nuestra página web gowaffles.cl",
    "carta": "Encuentra todos nuestros productos en gowaffles.cl/pedir",
    "trabajo": "Si quieres trabajar con nosotros, puedes escribir a contacto@gowaffles.cl o rellenar el formulario en gowaffles.cl/nosotros",
    "problemas": "Si tuviste algún inconveniente con tu pedido escríbenos a contacto@gowaffles.cl",
    "ejecutivo": "Si necesitas hablar con un encargado del local, comunícate al https://wa.me/56953717707",
    "redes_sociales": "Encuentranos en instagram o tiktok como @gowaffles.cl",
    "categorías": "Tenemos waffles dulces, salados y personalizados. También tenemos milkshakes, frappes, limonadas, Mini Go, helados y bebidas",
    "zona_delivery": "Cada delivery app tiene su propio radio de despacho. En gowaffles.cl/local puedes ver la cobertura de despacho para las ventas de nuestro sitio web"
}

system_prompt = """
Eres el asistente virtual de Go Waffles 🍓.
Responde solo preguntas relacionadas con el negocio usando la información disponible.
Habla con un tono juvenil y cercano, usando emojis cuando quede bien 😄.
No inventes precios, horarios, promociones ni contactos que no estén en los datos que tienes.
Si no sabes algo, responde con amabilidad y sugiere escribir a contacto@gowaffles.cl ✉️.
No alteres los enlaces web ni cambies su formato. Respétalos exactamente como aparecen porque necesito que sean clickeables.
Tu meta es sonar natural, claro y buena onda. Evita responder igual ante la misma pregunta para no parecer un bot.
"""

def generar_contexto(info):
    contexto = "Aquí tienes información de referencia sobre Go Waffles que puedes usar para responder:\n"
    for clave, valor in info.items():
        contexto += f"- {clave.capitalize()}: {valor}\n"
    contexto += "\nUsa esta información solo si aplica a la pregunta del usuario.\n"
    return contexto

# ─── FUNCIONES DE MENÚ ───────────────────────────────────────

def obtener_menu():
    global _menu_cache, _menu_last_fetch
    ahora = time.time()
    if ahora - _menu_last_fetch > 300 or _menu_cache is None:  # cada 5 minutos
        try:
            url = "https://webdatacdn.getjusto.com/v1/websites/LeH4tbZj5znjrm8wD/menus/5XXLP6masht3zN6ko"
            response = requests.get(url, timeout=5)
            data = response.json()
            _menu_cache = data["data"]["products"]
            _menu_last_fetch = ahora
        except Exception as e:
            print(f"❌ Error al cargar menú: {e}")
            return {}
    return _menu_cache

def buscar_en_menu(consulta: str, umbral=60):
    products = obtener_menu()
    if not products:
        return []
    nombres = [p.get("name", "") for p in products.values()]
    coincidencias = process.extract(consulta, nombres, limit=3)
    resultados = []
    for nombre_coincidencia, score, idx in coincidencias:
        if score >= umbral:
            p = list(products.values())[idx]
            price = (
                p.get("availabilityAt", {}).get("finalPrice")
                or p.get("availabilityAt", {}).get("basePrice")
                or "N/D"
            )
            resultados.append({
                "nombre": p.get("name"),
                "precio": int(price) if isinstance(price, (int, float)) else price,
                "descripcion": p.get("description", "")
            })
    return resultados

# ─── DETECCIÓN DE INTENCIÓN CON OPENAI (CLASIFICACIÓN LIGERA) ─────

def es_pregunta_de_menu(mensaje: str) -> bool:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        # Fallback básico por si falla OpenAI
        palabras = ["waffle", "helado", "milkshake", "frappe", "limonada", "mini", "banana", "plátano", "frutilla", "dulce", "salado", "precio", "cuesta", "tienen", "ingredientes"]
        return any(p in mensaje.lower() for p in palabras)

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Eres un clasificador. Responde SOLO 'sí' o 'no'."},
                {"role": "user", "content": f"¿La siguiente pregunta está relacionada con pedir, comprar, precios, ingredientes, productos o menú de un local de comida? Pregunta: '{mensaje}'"}
            ],
            temperature=0,
            max_tokens=5,
            timeout=5
        )
        return "sí" in response.choices[0].message.content.lower()
    except:
        # Si falla OpenAI, usamos fallback
        return False

# ─── RESPONDER PREGUNTA (FLUJO PRINCIPAL) ─────────────────────

def responder_pregunta(pregunta):
    # ✅ Paso 1: ¿Es sobre el menú?
    if es_pregunta_de_menu(pregunta):
        resultados = buscar_en_menu(pregunta)
        if resultados:
            productos_txt = "\n".join([
                f"- {r['nombre']}: ${r['precio']} {r['descripcion']}".strip()
                for r in resultados
            ])
            contexto_final = f"Información de productos relevantes:\n{productos_txt}\n\nResponde con tono amable y juvenil, usando emojis si queda bien."
        else:
            contexto_final = "No se encontraron productos relacionados con la consulta del usuario. Sugiere visitar gowaffles.cl/pedir para ver todo el menú."

        # Usa OpenAI SOLO con esta info acotada
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return "⚠️ Ups, no tengo acceso a mi cerebro. Por favor avisa al equipo de Go Waffles."

        client = OpenAI(api_key=api_key)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{contexto_final}\n\nPregunta del usuario: {pregunta}"}
        ]
    else:
        # Flujo original: info de negocio + hora
        chile_tz = pytz.timezone("America/Santiago")
        ahora = datetime.now(chile_tz)
        hora_actual = ahora.strftime("%H:%M")

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return "⚠️ Ups, no tengo acceso a mi cerebro. Por favor avisa al equipo de Go Waffles."

        client = OpenAI(api_key=api_key)
        contexto = generar_contexto(info_negocio)
        contexto += f"\nHora actual en La Serena, Chile: {hora_actual}\n"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{contexto}\nPregunta del usuario: {pregunta}"}
        ]

    # Llamada común a OpenAI
    try:
        respuesta = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            temperature=0.3,
            timeout=10
        )
        return respuesta.choices[0].message.content
    except Exception as e:
        print(f"❌ Error al llamar a OpenAI: {e}")
        return "¡Ups! Tuve un pequeño error al pensar mi respuesta. ¿Puedes repetirme tu pregunta? 🧇"

# ─── ENDPOINTS ───────────────────────────────────────────────

@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    if not TELEGRAM_TOKEN or not TELEGRAM_URL:
        print("❌ TELEGRAM_TOKEN no está definido.")
        return {"status": "error", "detalle": "Token de Telegram no configurado"}

    data = await request.json()
    print("📥 Recibido de Telegram:", data)

    try:
        mensaje = data["message"]["text"]
        chat_id = data["message"]["chat"]["id"]
    except KeyError:
        print("⚠️ Mensaje sin texto o chat_id. Ignorado.")
        return {"status": "ignored"}

    respuesta = responder_pregunta(mensaje)
    print(f"📤 Respondiendo a {chat_id}: {respuesta}")

    try:
        response = requests.post(TELEGRAM_URL, json={"chat_id": chat_id, "text": respuesta}, timeout=5)
        response.raise_for_status()
    except Exception as e:
        print(f"❌ Error al enviar a Telegram: {e}")
        return {"status": "error", "detalle": str(e)}

    return {"status": "ok"}

@app.post("/webhook/web")
async def web_webhook(request: Request):
    data = await request.json()
    try:
        mensaje = data["mensaje"]
    except KeyError:
        return {"status": "error", "detalle": "Falta el campo 'mensaje'"}
    respuesta = responder_pregunta(mensaje)
    return {"respuesta": respuesta}

@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
        "telegram_configured": bool(os.getenv("TELEGRAM_TOKEN")),
        "webhook_url": "https://go-waffles-bot.up.railway.app/webhook/telegram"
    }
