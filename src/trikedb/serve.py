"""trikedb serve — one process, three doors onto the same graph.

    trikedb serve graph.yaml --port 8080 --token $SECRET

- ``/``        the interactive workbench UI (always current, humans)
- ``/sparql``  minimal REST: POST {"query": "..."} -> JSON (apps)
- ``/mcp``     MCP over Streamable HTTP (agents; same eleven tools as stdio)

The graph can be a local file, a remote URL (s3://...), or a workspace
union. Two ways to authenticate, and they compose:

- ``--token SECRET`` — one static Bearer token. Fine for a script or a
  CI job; there is no user identity behind it.
- ``--oauth-issuer https://idp.example.com/`` — OAuth 2.1 against your own
  IdP, which is what claude.ai and the ChatGPT UI speak. trikedb only
  verifies the JWTs (see ``oauth.py``); it never issues them.

All three doors are protected by whichever you configure. Workspace unions
serve read-only; write tools report the member graphs to write to instead.
"""

from __future__ import annotations

import json


def build_app(
    path,
    token=None,
    with_mcp: bool = True,
    oauth_issuer=None,
    public_url=None,
    oauth_audience=None,
    required_scopes=None,
    stateless: bool = False,
):
    from starlette.applications import Starlette
    from starlette.responses import HTMLResponse, JSONResponse, Response
    from starlette.routing import Mount, Route

    from .db import TrikeDB

    auth = challenge = None
    if oauth_issuer:
        if not public_url:
            raise ValueError(
                "--oauth-issuer needs --public-url: OAuth binds tokens to this "
                "server's public HTTPS URL (the RFC 8707 audience)"
            )
        from .oauth import build_auth, resource_metadata_url

        resource = f"{str(public_url).rstrip('/')}/mcp"
        auth = build_auth(oauth_issuer, resource, oauth_audience, required_scopes)
        challenge = f'resource_metadata="{resource_metadata_url(resource)}"'

    def denied(status: int = 401, error: str = "invalid_token", scope=None):
        headers = {}
        if challenge:
            parts = [f'Bearer error="{error}"']
            if scope:
                parts.append(f'scope="{" ".join(scope)}"')
            parts.append(challenge)
            headers["WWW-Authenticate"] = ", ".join(parts)
        return Response("unauthorized", status_code=status, headers=headers or None)

    async def refuse(request):
        """None if the request may proceed, otherwise the response to send back.

        Scopes are enforced here as well as on /mcp (where the MCP SDK does
        it), so one ``--required-scope`` covers all three doors alike.
        """
        header = request.headers.get("authorization", "")
        if token is not None and header == f"Bearer {token}":
            return None
        if auth is None:
            return None if token is None else denied()
        verified = (
            await auth[1].verify_token(header[7:])
            if header[:7].lower() == "bearer "
            else None
        )
        if verified is None:
            return denied()
        missing = [s for s in (required_scopes or []) if s not in verified.scopes]
        if missing:
            return denied(403, "insufficient_scope", missing)
        return None

    async def home(request):
        if (refusal := await refuse(request)) is not None:
            return refusal
        try:
            db = TrikeDB(path)
            return HTMLResponse(db.to_html(title=f"trikedb — {path}"))
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    async def sparql(request):
        if (refusal := await refuse(request)) is not None:
            return refusal
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

        server = build_server(
            path, auth=auth, public_url=public_url, stateless=stateless
        )
        routes.append(Mount("/", app=server.streamable_http_app()))

        def lifespan(app):  # noqa: ANN001 - starlette lifespan signature
            return server.session_manager.run()

    app = Starlette(routes=routes, lifespan=lifespan)

    # The static token is enforced as a blanket ASGI gate so it covers /mcp
    # too. Under OAuth we cannot do that: the discovery documents and the 401
    # challenge on /mcp have to stay reachable for a client to authenticate at
    # all, so the MCP layer guards itself and the routes above guard themselves.
    if token is not None and auth is None:
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


def serve(
    path,
    host: str = "127.0.0.1",
    port: int = 8000,
    token=None,
    oauth_issuer=None,
    public_url=None,
    oauth_audience=None,
    required_scopes=None,
    stateless: bool = False,
) -> None:
    """Blocking entry point used by ``trikedb serve``."""
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "serving requires uvicorn - pip install 'trikedb[serve]'"
        ) from exc

    app = build_app(
        path,
        token=token,
        oauth_issuer=oauth_issuer,
        public_url=public_url,
        oauth_audience=oauth_audience,
        required_scopes=required_scopes,
        stateless=stateless,
    )
    uvicorn.run(app, host=host, port=port)
