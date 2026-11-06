import logging
import os
from datetime import datetime, timezone
from functools import cache

from flask import Flask, jsonify, request
from google.api_core.exceptions import AlreadyExists
from google.cloud import firestore, pubsub_v1

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("backend")

BASE_DATOS = os.environ.get("BASE_DATOS", "(default)")
TEMA = os.environ.get("TEMA", "")

# Las existencias iniciales son pequeñas a propósito, para que se agoten en clase.
MENU = {
    "tinto": {"nombre": "Tinto", "precio": 1500, "existencias": 20},
    "cafe-con-leche": {"nombre": "Café con leche", "precio": 2500, "existencias": 12},
    "empanada": {"nombre": "Empanada", "precio": 2000, "existencias": 10},
    "pastel-de-pollo": {"nombre": "Pastel de pollo", "precio": 3500, "existencias": 6},
    "arepa-con-queso": {"nombre": "Arepa con queso", "precio": 4000, "existencias": 8},
    "jugo-natural": {"nombre": "Jugo natural", "precio": 4500, "existencias": 6},
    # La cocina no tiene receta para este plato: siempre falla al prepararlo.
    "plato-misterioso": {"nombre": "Plato misterioso", "precio": 9900, "existencias": 5},
}

app = Flask(__name__)


# Los clientes se crean la primera vez que se usan y no al importar el módulo.
# Así el contenedor arranca aunque no tenga credenciales (por ejemplo, con
# docker run en Cloud Shell) y las rutas que no tocan Firestore siguen sirviendo.
@cache
def db():
    return firestore.Client(database=BASE_DATOS)


@cache
def publicador():
    return pubsub_v1.PublisherClient()


def ahora():
    return datetime.now(timezone.utc)


def preparar_inventario(productos=MENU):
    # create() falla si el documento ya existe. Por eso no importa que varias
    # instancias arranquen a la vez: solo una crea cada producto y nadie pisa
    # las existencias que ya cambió la cocina.
    for producto in productos:
        try:
            db().collection("inventario").document(producto).create(
                {"existencias": MENU[producto]["existencias"]}
            )
        except AlreadyExists:
            pass


try:
    preparar_inventario()
except Exception:
    log.exception("No se pudo preparar el inventario al arrancar; se reintenta en GET /menu")


@app.after_request
def cors(respuesta):
    respuesta.headers["Access-Control-Allow-Origin"] = "*"
    respuesta.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    respuesta.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return respuesta


@app.get("/menu")
def menu():
    existencias = {
        doc.id: doc.to_dict().get("existencias", 0)
        for doc in db().collection("inventario").stream()
    }
    faltantes = [p for p in MENU if p not in existencias]
    if faltantes:
        preparar_inventario(faltantes)
        existencias.update({p: MENU[p]["existencias"] for p in faltantes})
    return jsonify([
        {"producto": p, "nombre": d["nombre"], "precio": d["precio"], "existencias": existencias[p]}
        for p, d in MENU.items()
    ])


def validar(cuerpo):
    """Devuelve (cliente, items) o lanza ValueError con un mensaje para el cliente."""
    if not isinstance(cuerpo, dict):
        raise ValueError("El cuerpo debe ser un objeto JSON")
    cliente = cuerpo.get("cliente")
    if not isinstance(cliente, str) or not cliente.strip():
        raise ValueError("Falta el nombre del cliente")
    cliente = cliente.strip()
    if len(cliente) > 40:
        raise ValueError("El nombre del cliente tiene más de 40 caracteres")
    items = cuerpo.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("El pedido debe tener al menos un producto")
    if len(items) > 10:
        raise ValueError("El pedido tiene más de 10 líneas")
    limpios = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Cada producto debe ser un objeto con producto y cantidad")
        producto, cantidad = item.get("producto"), item.get("cantidad")
        if producto not in MENU:
            raise ValueError(f"No hay {producto!r} en el menú")
        # bool es subclase de int en Python; sin esta exclusión, true contaría como 1.
        if not isinstance(cantidad, int) or isinstance(cantidad, bool) or not 1 <= cantidad <= 10:
            raise ValueError("La cantidad debe ser un entero entre 1 y 10")
        limpios.append({
            "producto": producto,
            "nombre": MENU[producto]["nombre"],
            "precio": MENU[producto]["precio"],
            "cantidad": cantidad,
        })
    return cliente, limpios


# El número sale de un incremento atómico que resuelve el servidor, sin
# bloquear el contador. Con una transacción, muchos pedidos a la vez peleaban
# por el mismo documento y la mayoría fallaba. Si algo falla entre el
# incremento y el guardado, se salta un número, que no le hace daño a nadie.
def siguiente_numero():
    resultado = db().collection("contadores").document("pedidos").set(
        {"valor": firestore.Increment(1)}, merge=True
    )
    return resultado.transform_results[0].integer_value


def publicar(pedido_id):
    if not TEMA:
        log.warning("TEMA está vacío: el pedido %s se guardó pero nadie le avisa a la cocina", pedido_id)
        return
    try:
        # Se espera la confirmación antes de responder. En Cloud Run la CPU se
        # limita al terminar la respuesta y un envío pendiente podría perderse.
        publicador().publish(TEMA, pedido_id.encode()).result(timeout=30)
        log.info("Pedido %s publicado en %s", pedido_id, TEMA)
    except Exception:
        # El pedido ya quedó guardado. Se registra el error y el pedido se
        # queda en "recibido", que es justo lo que hay que ir a diagnosticar.
        log.exception("No se pudo publicar el pedido %s en %s", pedido_id, TEMA)


def como_json(doc_id, datos):
    return {
        "id": doc_id,
        "numero": datos["numero"],
        "cliente": datos["cliente"],
        "items": datos["items"],
        "total": datos["total"],
        "estado": datos["estado"],
        "motivo": datos.get("motivo"),
        "creado": datos["creado"].isoformat(),
        "actualizado": datos["actualizado"].isoformat(),
    }


@app.post("/pedidos")
def crear_pedido():
    try:
        cliente, items = validar(request.get_json(silent=True))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    momento = ahora()
    datos = {
        "cliente": cliente,
        "items": items,
        "total": sum(i["precio"] * i["cantidad"] for i in items),
        "estado": "recibido",
        "creado": momento,
        "actualizado": momento,
    }
    numero = siguiente_numero()
    pedido_ref = db().collection("pedidos").document()
    pedido_ref.set({**datos, "numero": numero})

    publicar(pedido_ref.id)
    return jsonify(como_json(pedido_ref.id, {**datos, "numero": numero})), 201


@app.get("/pedidos/<pedido_id>")
def ver_pedido(pedido_id):
    doc = db().collection("pedidos").document(pedido_id).get()
    if not doc.exists:
        return jsonify({"error": "No existe ese pedido"}), 404
    return jsonify(como_json(doc.id, doc.to_dict()))


@app.get("/pedidos")
def ultimos_pedidos():
    consulta = (
        db().collection("pedidos")
        .order_by("creado", direction=firestore.Query.DESCENDING)
        .limit(20)
    )
    return jsonify([como_json(doc.id, doc.to_dict()) for doc in consulta.stream()])


@app.post("/inventario/reiniciar")
def reiniciar_inventario():
    lote = db().batch()
    for producto, datos in MENU.items():
        lote.set(db().collection("inventario").document(producto), {"existencias": datos["existencias"]})
    lote.commit()
    log.info("Inventario repuesto a los valores iniciales")
    return menu()
