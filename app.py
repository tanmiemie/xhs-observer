"""A local-only website with an optional private Google Cloud cache."""
import argparse
import base64
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from urllib.request import urlopen

from core import HOME, SOURCE, canonical, config, empty_archive, load_json

IDENTITY = {"app": "xhs-observer", "schema": 2}
SYNC_LOCK = threading.Lock()


def library():
    path = HOME / "data/archive.json"
    if path.exists():
        return load_json(path), False
    demo = SOURCE / "demo/archive.json"
    return (load_json(demo), True) if demo.exists() else (empty_archive(), True)


def render(archive, demo):
    settings = config()
    payload = {**archive, "embedded_media": {key: "/" + media["path"] for key, media in archive["media"].items()}, "xlsx": None, "xlsx_url": "/exports/library.xlsx", "demo": demo, "cloud_configured": bool(settings["google_cloud"]["project_id"] and settings["google_cloud"]["bucket"]), "app_title": settings["title"]}
    template = (SOURCE / "viewer.html").read_text(encoding="utf-8")
    return template.replace("__ARCHIVE_DATA__", canonical(payload).decode().replace("<", "\\u003c")).encode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get("Host", "").split(":")[0] not in ("127.0.0.1", "localhost"):
            return self.send_error(403)
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self.respond(render(*library()), "text/html; charset=utf-8")
        if path == "/api/health":
            return self.respond(canonical(IDENTITY), "application/json")
        if path == "/exports/library.xlsx":
            try:
                from export import workbook_bytes
                return self.respond(workbook_bytes(library()[0]), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", download=True)
            except ImportError:
                return self.respond(canonical({"error": "Install requirements.txt to enable Excel export."}), "application/json", 503)
        if path.startswith("/assets/"):
            asset = (HOME / path.lstrip("/")).resolve()
            if not asset.is_relative_to((HOME / "assets").resolve()) or not asset.is_file():
                return self.send_error(404)
            return self.respond(asset.read_bytes(), "image/webp")
        self.send_error(404)

    def do_POST(self):
        expected_origin = "http://" + self.headers.get("Host", "")
        if self.path != "/api/sync" or self.headers.get("Host", "").split(":")[0] not in ("localhost", "127.0.0.1") or self.headers.get("Origin") != expected_origin or self.headers.get("X-Observer-Request") != "sync":
            return self.send_error(403)
        if not SYNC_LOCK.acquire(blocking=False):
            return self.respond(canonical({"error": "Sync already in progress."}), "application/json", 409)
        try:
            from cloud import pull
            return self.respond(canonical(pull()), "application/json")
        except Exception as exc:
            # Keep the existing library and expose no tokens or credential details.
            return self.respond(canonical({"error": "Cloud sync failed. Cached data is preserved.", "type": type(exc).__name__}), "application/json", 503)
        finally:
            SYNC_LOCK.release()

    def respond(self, data, content_type, status=200, download=False):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if download:
            self.send_header("Content-Disposition", 'attachment; filename="xhs-library.xlsx"')
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8127)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    url = "http://127.0.0.1:" + str(args.port)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except PermissionError:
        raise
    except OSError:
        try:
            with urlopen(url + "/api/health", timeout=2) as response:
                if json.load(response) != IDENTITY:
                    raise RuntimeError("Port occupied by another app.")
        except Exception as exc:
            raise SystemExit("Port occupied by another app; use --port to choose another port.") from exc
        if args.open:
            webbrowser.open(url)
        raise SystemExit(0)
    print("XHS Observer: " + url, flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
