# API del backend y mensaje de Pub/Sub

Todas las respuestas son JSON y llevan `Access-Control-Allow-Origin: *`, así que el frontend las puede llamar desde otro dominio. Los errores tienen la forma `{"error": "mensaje para mostrar"}`.

## Variables de entorno

| Servicio | Variable | Para qué |
|---|---|---|
| backend | `BASE_DATOS` | Nombre de la base de Firestore, por ejemplo `grupo1-cafeteria` |
| backend | `TEMA` | Ruta completa del tema: `projects/<proyecto>/topics/<tema>`. Si está vacía, el pedido se guarda y no se publica |
| cocina | `BASE_DATOS` | La misma base que usa el backend |
| cocina | `TIEMPO_PREPARACION` | Segundos que tarda en preparar un pedido. Por defecto 6 |
| cocina | `PROBABILIDAD_FALLO` | Entre 0 y 1. Con esa probabilidad responde `500` después de terminar el trabajo. Por defecto 0 |
| frontend | `BACKEND_URL` | URL del backend, que `server.py` escribe dentro de la página |

Cloud Run pone además `PORT`, que los tres servicios respetan.

## Endpoints del backend

### `GET /menu`

Los productos con su precio en pesos y las existencias actuales. Si falta algún producto en el inventario, lo crea con las existencias iniciales.

```json
[
  {"producto": "tinto", "nombre": "Tinto", "precio": 1500, "existencias": 18},
  {"producto": "plato-misterioso", "nombre": "Plato misterioso", "precio": 9900, "existencias": 5}
]
```

Productos: `tinto`, `cafe-con-leche`, `empanada`, `pastel-de-pollo`, `arepa-con-queso`, `jugo-natural` y `plato-misterioso`. La cocina no tiene receta para el último y siempre falla al prepararlo.

### `POST /pedidos`

```json
{"cliente": "Laura", "items": [{"producto": "empanada", "cantidad": 2}, {"producto": "tinto", "cantidad": 1}]}
```

Reglas: `cliente` no puede estar vacío y tiene como máximo 40 caracteres; `items` trae entre 1 y 10 líneas; cada `producto` debe estar en el menú y cada `cantidad` es un entero entre 1 y 10. Si algo no cumple, responde `400`.

El backend no revisa existencias: eso lo hace la cocina cuando le llega el pedido. Guarda el pedido con estado `recibido` y un número consecutivo, publica el mensaje y responde `201` sin esperar a la cocina:

```json
{
  "id": "Xk3v9TQ2bq0pLm7aZr1c",
  "numero": 11,
  "cliente": "Laura",
  "items": [
    {"producto": "empanada", "nombre": "Empanada", "precio": 2000, "cantidad": 2},
    {"producto": "tinto", "nombre": "Tinto", "precio": 1500, "cantidad": 1}
  ],
  "total": 5500,
  "estado": "recibido",
  "motivo": null,
  "creado": "2026-10-18T21:40:12.512345+00:00",
  "actualizado": "2026-10-18T21:40:12.512345+00:00"
}
```

Si la publicación falla (por ejemplo, por falta de permiso sobre el tema), el pedido ya quedó guardado: el backend responde `201` igual y deja el error en sus logs. El pedido se queda en `recibido`.

### `GET /pedidos/<id>`

El pedido con la misma forma de arriba, o `404` si no existe. `motivo` solo tiene texto cuando el estado es `rechazado`.

### `GET /pedidos`

Los últimos 20 pedidos, del más reciente al más antiguo. Es lo que usa la pantalla de la cafetería.

### `POST /inventario/reiniciar`

Devuelve todas las existencias a sus valores iniciales y responde lo mismo que `GET /menu`. Sirve para reponer el inventario durante una demostración.

## El mensaje de Pub/Sub

El backend publica un mensaje por pedido. El contenido (`data`) es el identificador del documento del pedido en Firestore, en UTF-8, sin JSON alrededor y sin atributos:

```
Xk3v9TQ2bq0pLm7aZr1c
```

El mensaje lleva solo el identificador porque el pedido completo ya está en Firestore; así la cocina siempre lee la versión guardada.

## Lo que recibe la cocina

Con una suscripción push, Pub/Sub hace un `POST` a la URL de la cocina con este sobre. `data` va en base64:

```json
{
  "message": {
    "data": "WGszdjlUUTJicTBwTG03YVpyMWM=",
    "messageId": "13412348019231",
    "publishTime": "2026-10-18T21:40:12.601Z",
    "attributes": {}
  },
  "subscription": "projects/<proyecto>/subscriptions/<suscripcion>",
  "deliveryAttempt": 1
}
```

`deliveryAttempt` solo aparece cuando la suscripción tiene política de mensajes muertos. La cocina lo escribe en sus logs cuando viene.

| La cocina responde | Cuándo | Qué hace Pub/Sub |
|---|---|---|
| `204` | Pedido terminado (`listo` o `rechazado`), o el pedido no existe | Lo da por entregado |
| `400` | El cuerpo no es un sobre de Pub/Sub | Reintenta |
| `500` | Plato misterioso, o falla simulada con `PROBABILIDAD_FALLO` | Reintenta |

Cualquier respuesta que no sea 2xx, o ninguna respuesta dentro del plazo de confirmación, hace que Pub/Sub vuelva a entregar el mismo mensaje más tarde.
