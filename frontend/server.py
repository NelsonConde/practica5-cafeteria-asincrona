import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# La URL del backend se conoce al desplegar y no al construir la imagen.
# Por eso se inyecta aquí, al arrancar, y la misma imagen sirve para cualquier grupo.
BACKEND_URL = os.environ.get("BACKEND_URL", "").rstrip("/")
PAGINA = (
    (Path(__file__).parent / "index.html")
    .read_text(encoding="utf-8")
    .replace("__BACKEND_URL__", BACKEND_URL)
    .encode("utf-8")
)


class Manejador(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] not in ("/", "/index.html"):
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(PAGINA)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(PAGINA)


if __name__ == "__main__":
    puerto = int(os.environ.get("PORT", "8080"))
    print(f"Frontend en el puerto {puerto}, backend en {BACKEND_URL or '(sin configurar)'}", flush=True)
    ThreadingHTTPServer(("", puerto), Manejador).serve_forever()
