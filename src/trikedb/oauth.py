"""OAuth 2.1 for ``trikedb serve`` — verify tokens, never issue them.

trikedb is a resource server and nothing more. It does not run an
authorization server, store passwords, or mint tokens: it delegates all of
that to an IdP you already operate (Auth0, Okta, Entra, Keycloak) and only
checks the signature, issuer, audience and expiry of the JWTs that IdP
signed. That single function is the whole of what this module adds — the
MCP SDK already implements the rest of the flow (RFC 9728 discovery, the
401 challenge, scope enforcement), which is what lets claude.ai and the
ChatGPT UI connect to a served graph as a normal remote connector.

    trikedb serve graph.yaml --public-url https://kg.example.com \\
        --oauth-issuer https://idp.example.com/ --required-scope kg:read

The audience defaults to the canonical MCP URL (``https://kg.example.com/mcp``)
and is checked on every request: the IdP must issue tokens carrying that
exact ``aud`` (RFC 8707 resource indicators, or an Auth0 "API identifier").
Skipping that check would let a token minted for some *other* service open
your graph, so a token without the right audience is simply rejected.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

_DISCOVERY_PATHS = (
    ".well-known/openid-configuration",
    ".well-known/oauth-authorization-server",
)

_DEFAULT_ALGORITHMS = ("RS256", "RS384", "RS512", "ES256", "ES384", "PS256")


def _scopes_of(claims: dict) -> list[str]:
    """Scopes, however this IdP spells them.

    ``scope`` is the OAuth standard (space-delimited), ``scp`` is Entra's
    list form, and Auth0 puts RBAC grants in ``permissions``.
    """
    raw = claims.get("scope") or claims.get("scp") or []
    scopes = raw.split() if isinstance(raw, str) else list(raw)
    for permission in claims.get("permissions") or []:
        if permission not in scopes:
            scopes.append(permission)
    return scopes


class JWKSVerifier:
    """An MCP ``TokenVerifier`` backed by the IdP's published JWKS.

    Discovery happens once, lazily, on the first request: the issuer's
    metadata document gives us ``jwks_uri``, and PyJWT caches the signing
    keys from there (re-fetching when a token arrives with an unseen kid).
    """

    def __init__(
        self,
        issuer: str,
        audience: str,
        algorithms: Optional[Sequence[str]] = None,
    ) -> None:
        try:
            import jwt  # noqa: F401
        except ImportError:  # pragma: no cover
            raise ImportError(
                "OAuth support requires PyJWT — pip install 'trikedb[oauth]'"
            ) from None
        self.issuer = issuer
        self.audience = audience
        self.algorithms = list(algorithms or _DEFAULT_ALGORITHMS)
        self._client: Any = None
        self._issuer_claim = issuer

    async def _signing_keys(self):
        if self._client is None:
            import httpx
            from jwt import PyJWKClient

            base = self.issuer.rstrip("/")
            metadata = None
            async with httpx.AsyncClient(timeout=10.0) as http:
                for path in _DISCOVERY_PATHS:
                    response = await http.get(f"{base}/{path}")
                    if response.status_code == 200 and "jwks_uri" in response.json():
                        metadata = response.json()
                        break
            if metadata is None:
                raise RuntimeError(
                    f"no OAuth metadata under {base} — check --oauth-issuer"
                )
            # The metadata's own issuer is authoritative for the `iss` claim:
            # Auth0 issues `https://tenant.auth0.com/` with the trailing slash
            # and JWT validation is an exact string comparison.
            self._issuer_claim = metadata.get("issuer", self.issuer)
            if str(self._issuer_claim).rstrip("/") != base:
                raise RuntimeError(
                    f"issuer mismatch: {base} advertises {self._issuer_claim}"
                )
            self._client = PyJWKClient(metadata["jwks_uri"], cache_keys=True)
        return self._client

    async def verify_token(self, token: str):
        """Return an ``AccessToken`` for a valid JWT, or None to trigger a 401."""
        import anyio.to_thread
        import jwt

        from mcp.server.auth.provider import AccessToken

        try:
            client = await self._signing_keys()
            key = await anyio.to_thread.run_sync(client.get_signing_key_from_jwt, token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=self.algorithms,
                audience=self.audience,
                issuer=self._issuer_claim,
                options={"require": ["exp", "iss", "aud"]},
            )
        except Exception:
            return None  # expired, wrong audience, bad signature — all one answer
        return AccessToken(
            token=token,
            client_id=claims.get("azp") or claims.get("client_id") or claims.get("sub", ""),
            scopes=_scopes_of(claims),
            expires_at=int(claims["exp"]),
            resource=self.audience,
            subject=claims.get("sub"),
            claims=claims,
        )


def build_auth(
    issuer: str,
    resource: str,
    audience: Optional[str] = None,
    required_scopes: Optional[Sequence[str]] = None,
):
    """(AuthSettings, verifier) for FastMCP — the resource-server half of OAuth.

    ``resource`` is the canonical MCP URL clients send as the RFC 8707
    ``resource`` parameter, and is also where the protected resource
    metadata is advertised (``/.well-known/oauth-protected-resource/mcp``).
    """
    try:
        from mcp.server.auth.settings import AuthSettings
    except ImportError:  # pragma: no cover
        raise ImportError(
            "OAuth support requires the mcp package — pip install 'trikedb[serve]'"
        ) from None

    settings = AuthSettings(
        issuer_url=issuer,
        resource_server_url=resource,
        required_scopes=list(required_scopes or []),
    )
    return settings, JWKSVerifier(issuer, audience or resource)


def resource_metadata_url(resource: str) -> str:
    """Where the RFC 9728 document for ``resource`` lives — for 401 challenges."""
    from mcp.server.auth.routes import build_resource_metadata_url

    return str(build_resource_metadata_url(resource))
