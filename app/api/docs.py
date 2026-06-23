"""
app/api/docs.py
===============
Public documentation endpoints for the ``/api/v1`` API:

* ``GET /api/v1/openapi.json`` — the generated OpenAPI 3 document.
* ``GET /api/v1/docs``        — Swagger UI (loaded from a CDN) bound to the spec.
* ``GET /api/v1/``            — a tiny landing page linking to the docs.

These are intentionally unauthenticated so integrators can explore the API and
authorize interactively from within Swagger UI.
"""

from __future__ import annotations

from flask import jsonify, url_for

from . import api_v1_bp, public
from .openapi import build_spec

_SWAGGER_VERSION = "5.17.14"


@api_v1_bp.route("/openapi.json", methods=["GET"])
@public
def openapi_json():
    return jsonify(build_spec())


@api_v1_bp.route("/docs", methods=["GET"])
@public
def swagger_ui():
    spec_url = url_for("api_v1.openapi_json")
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Hackathon Management API — Reference</title>
  <link rel="stylesheet"
        href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@{_SWAGGER_VERSION}/swagger-ui.css" />
  <style>
    body {{ margin: 0; background: #fafafa; }}
    .topbar {{ display: none; }}
  </style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@{_SWAGGER_VERSION}/swagger-ui-bundle.js"
          crossorigin></script>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@{_SWAGGER_VERSION}/swagger-ui-standalone-preset.js"
          crossorigin></script>
  <script>
    window.onload = function () {{
      window.ui = SwaggerUIBundle({{
        url: "{spec_url}",
        dom_id: "#swagger-ui",
        deepLinking: true,
        persistAuthorization: true,
        presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
        layout: "StandaloneLayout",
      }});
    }};
  </script>
</body>
</html>"""
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@api_v1_bp.route("/", methods=["GET"])
@public
def api_index():
    return jsonify({
        "ok": True,
        "name": "Hackathon Management API",
        "version": "1.0.0",
        "docs": url_for("api_v1.swagger_ui"),
        "openapi": url_for("api_v1.openapi_json"),
    })
