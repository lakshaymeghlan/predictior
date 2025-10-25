# scripts/print_routes.py
from importlib import import_module
import json

# import your FastAPI app
app_mod = import_module("backend.api.app")
app = getattr(app_mod, "app")

routes = []
for r in app.routes:
    routes.append({
        "path": getattr(r, "path", None),
        "name": getattr(r, "name", None),
        "methods": list(getattr(r, "methods", []))
    })

print(json.dumps(routes, indent=2, ensure_ascii=False))
