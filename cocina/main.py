import base64
import binascii
import logging
import os
import random
import time
from collections import Counter
from datetime import datetime, timezone
from functools import cache

from flask import Flask, request
from google.cloud import firestore

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("cocina")

BASE_DATOS = os.environ.get("BASE_DATOS", "(default)")
TIEMPO_PREPARACION = float(os.environ.get("TIEMPO_PREPARACION", "6"))
PROBABILIDAD_FALLO = float(os.environ.get("PROBABILIDAD_FALLO", "0"))
PLATO_MISTERIOSO = "plato-misterioso"

app = Flask(__name__)


@cache
def db():
    return firestore.Client(database=BASE_DATOS)


def ahora():
    return datetime.now(timezone.utc)


@firestore.transactional
def procesar_pedido(transaction, pedido_ref, cantidades):
    # 1. Leer el estado actual del pedido.
    pedido = pedido_ref.get(transaction=transaction)
    if not pedido.exists:
        return "inexistente"

    estado = (pedido.to_dict() or {}).get("estado")

    # 2. Comprobar si ya fue procesado.
    if estado in ("listo", "rechazado"):
        return estado

    # 3. Leer las existencias necesarias.
    inventario = db().collection("inventario")
    faltan = []
    for producto, cantidad in cantidades.items():
        doc_inv = inventario.document(producto).get(transaction=transaction)
        existencias = (doc_inv.to_dict() or {}).get("existencias", 0)
        # 4. Validar que exista inventario suficiente.
        if existencias < cantidad:
            faltan.append(producto)

    # 5 y 6. Escrituras atómicas (las lecturas ya finalizaron).
    if faltan:
        transaction.update(pedido_ref, {
            "estado": "rechazado",
            "motivo": "Se acabó: " + ", ".join(faltan),
            "actualizado": ahora(),
        })
        return "rechazado"
    else:
        for producto, cantidad in cantidades.items():
            transaction.update(
                inventario.document(producto),
                {"existencias": firestore.Increment(-cantidad)},
            )
        transaction.update(pedido_ref, {
            "estado": "listo",
            "actualizado": ahora(),
        })
        return "listo"


@app.post("/")
def recibir():
    # Pub/Sub entrega un sobre JSON: {"message": {"data": <base64>, ...},
    # "subscription": ..., "deliveryAttempt": n}. El último campo solo viene
    # cuando la suscripción tiene política de mensajes muertos.
    sobre = request.get_json(silent=True)
    try:
        pedido_id = base64.b64decode(sobre["message"]["data"], validate=True).decode()
    except (TypeError, KeyError, binascii.Error, UnicodeDecodeError):
        log.error("Llegó un sobre que no es de Pub/Sub o no trae data: %r", sobre)
        return "sobre inválido", 400

    intento = sobre.get("deliveryAttempt")
    log.info("Pedido %s, intento de entrega %s", pedido_id, intento or "desconocido")

    pedido_ref = db().collection("pedidos").document(pedido_id)
    pedido = pedido_ref.get()
    if not pedido.exists:
        # Se confirma igual: reintentar un pedido que no existe no lo va a crear.
        log.warning("El pedido %s no existe; se descarta el mensaje", pedido_id)
        return "", 204

    datos_pedido = pedido.to_dict() or {}
    estado = datos_pedido.get("estado")
    if estado in ("listo", "rechazado"):
        log.info("El pedido %s ya fue procesado (%s); se descarta la entrega repetida", pedido_id, estado)
        return "", 204

    pedido_ref.update({"estado": "preparando", "actualizado": ahora()})

    cantidades = Counter()
    for item in datos_pedido.get("items", []):
        cantidades[item["producto"]] += item["cantidad"]

    if PLATO_MISTERIOSO in cantidades:
        raise RuntimeError(f"La cocina no tiene receta para el plato misterioso (pedido {pedido_id})")

    time.sleep(TIEMPO_PREPARACION)

    resultado = procesar_pedido(db().transaction(), pedido_ref, cantidades)
    log.info("Pedido %s finalizado con resultado: %s", pedido_id, resultado)

    # Simula que la cocina se cae justo después de terminar y antes de confirmar.
    # Pub/Sub no recibe el 2xx y vuelve a entregar el mismo pedido.
    if random.random() < PROBABILIDAD_FALLO:
        log.warning("Falla simulada en el pedido %s: el trabajo quedó hecho pero no se confirma", pedido_id)
        return "falla simulada", 500

    return "", 204
