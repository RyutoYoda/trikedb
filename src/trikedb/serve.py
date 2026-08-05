"""trikedb serve — one process, three doors onto the same graph.

    trikedb serve graph.yaml --port 8080 --token $SECRET

- ``/``        the interactive workbench UI (always current, humans)
- ``/sparql``  minimal REST: POST {"query": "..."} -> JSON (apps)
- ``/mcp``     MCP over Streamable HTTP (agents; same 9 tools as stdio)

The graph can be a local file, a remote URL (s3://...), or a workspace
union. Auth is a single static Bearer token for v1 — pass --token and
clients send ``Authorization: Bearer <token>``. Workspace unions serve
read-only; write tools report the member graphs to write to instead.
"""

from __future__ import annotations

import json


def build_app(path, token=None, with_mcp: bool = True):
    from starlette.applications import Starlette
    from starlette.responses import HTMLResponse, JSONResponse, Response
    from starlette.routing import Mount, Route

    from .db import TrikeDB

    def denied():
        return Response("unauthorized", status_code=401)

    def authorized(request) -> bool:
        if token is None:
            return True
        return request.headers.get("authorization") == f"Bearer {token}"

    async def home(request):
        if not authorized(request):
            return denied()
        db = TrikeDB(path)
        return HTMLResponse(db.to_html(title=f"trikedb — {path}"))

    async def sparql(request):
        if not authorized(request):
            return denied()
        try:
            body = await request.json()
            query = body["query"]
        except Exception:
            return JSONResponse({"error": 'expected {"query": "..."}'}, status_code=400)
        db = TrikeDB(path)
        try:
            result = db.sparql(query)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if isinstance(result, bool):
            return JSONResponse({"ask": result})
        if isinstance(result, int):  # update form — persist it
            db.save()
            return JSONResponse({"delta": result, "triples": len(db)})
        return JSONResponse({"rows": result})

    routes = [Route("/", home), Route("/sparql", sparql, methods=["POST"])]
    lifespan = None
    if with_mcp:
        from .mcp_server import build_server

        server = build_server(path)
        routes.append(Mount("/", app=server.streamable_http_app()))

        def lifespan(app):  # noqa: ANN001 - starlette lifespan signature
            return server.session_manager.run()

    app = Starlette(routes=routes, lifespan=lifespan)

    if token is not None:
        inner = app

        async def gate(scope, receive, send):
            if scope["type"] == "http":
                headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
                if headers.get("authorization") != f"Bearer {token}":
                    body = json.dumps({"error": "unauthorized"}).encode()
                    await send({"type": "http.response.start", "status": 401,
                                "headers": [(b"content-type", b"application/json")]})
                    await send({"type": "http.response.body", "body": body})
                    return
            await inner(scope, receive, send)

        return gate
    return app


def serve(path, host: str = "127.0.0.1", port: int = 8000, token=None) -> None:
    """Blocking entry point used by ``trikedb serve``."""
    try:
        import uvicorn
    except ImportError:  # pragma: no cover
        raise ImportError(
            "serving requires uvicorn — pip install 'trikedb[serve]'"
        ) from None

    app = build_app(path, token=token)
    uvicorn.run(app, host=host, port=port)
