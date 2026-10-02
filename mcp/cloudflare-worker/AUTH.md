# Putting real authentication in front of this Worker

The server in this directory ships with a shared bearer token, and that is
enough for a graph you would not mind losing. It is not enough for two
situations that arrive quickly: a graph with anything private in it, and a
client that refuses shared tokens outright.

The second one is not a quality problem you can implement your way out of.
**ChatGPT's custom connectors require OAuth 2.1 with dynamic client
registration (RFC 7591) for any authenticated remote MCP server. There is
no field for a static bearer token.** A server that only speaks bearer
tokens cannot be connected from that client at all, no matter how carefully
the token is handled.

This page is the other route: put Cloudflare Access in front of the Worker
and turn on its Managed OAuth, so the proxy is the OAuth authorization
server and the Worker never implements authorization at all.

```
MCP client ──1. 401 + OAuth discovery──▶  Cloudflare Access
 (ChatGPT /                                     │  2. browser sign-in
  Claude Code /                                 │     against your policy
  VS Code / mcp-remote)                         ▼
                                          this Worker
                                          reads one identity header
```

Server cost stays zero. Zero Trust is free up to 50 users and Managed OAuth
is included. The one unavoidable cost is a domain name, for the reason in
step 1.

Everything below was run against a live deployment on 2026-10-03. Cloudflare
calls Managed OAuth a beta, so treat the specifics as a snapshot rather than
a contract — the shapes will outlive the details.

## Why not a shared token

A shared-token `_authorized()` has three separate problems, and this
sample used to have all three:

```python
token = getattr(self.env, "AUTH_TOKEN", None)
if not token:
    return True                      # open when unset
if header == f"Bearer {token}":
    return True
return f"/{token}" in request.url    # token in the path
```

**Major clients will not speak it.** The incompatibility above. This one is
decisive, because it is a specification mismatch and not something better
code fixes.

**A secret in the path cannot be kept.** The path branch exists because some
connector UIs cannot attach a header, and it puts the secret into access
logs, proxy logs, browser history and referrers. Fine for a demo graph,
unusable as a wall around anything else.

**Open-when-unset fails open at exactly the wrong moment.** `return True`
with no token set is convenient during `pywrangler dev`. It also means that
the moment you put a proxy in front and delete the old token, the server is
open to everyone until the next deploy. [`src/entry.py`](src/entry.py) no
longer does this — it refuses everything unless `AUTH_TOKEN` matches, an
Access identity header is present, or `DEV_OPEN=1` says open on purpose —
but the ordering in step 7 still matters, and the pattern is common enough
to be worth naming.

You do not have to write an authorization server to escape this. Doing so
would mean owning the authorize endpoint, token issuance, PKCE verification,
refresh-token rotation, the DCR endpoint, discovery documents, and key
storage and rotation — for a server with one user. Managed OAuth makes the
proxy you are already running do all of it.

## Step 1 — own the domain, registrar and all

`*.workers.dev` hostnames cannot sit behind Access. A free subdomain is
therefore not merely inelegant here; it is a permanent route around the
proxy, which is the one thing this design cannot tolerate.

Buying through Cloudflare Registrar is the short path: the zone is active
the moment the purchase completes. Moving an **existing** domain in can
deadlock — some site builders refuse to point their domains at external
nameservers, while a registrar transfer wants the zone active on Cloudflare
nameservers first. Neither can go first. Buying a fresh domain is faster
than solving that.

## Step 2 — close the free subdomain

In [`wrangler.toml`](wrangler.toml):

```toml
# Publish on the custom domain only. *.workers.dev cannot sit behind
# Access, so leaving it open leaves a permanent route around the proxy.
workers_dev = false

# custom_domain = true creates the DNS record and certificate too.
[[routes]]
pattern = "mcp.example.com"
custom_domain = true
```

Deploy this **before** any of the Access configuration. Delegating
authorization to a proxy is sound only while no route bypasses the proxy,
and these two lines are what makes that true.

## Step 3 — enable the free Zero Trust plan

Zero Trust, then the $0 / 50-user plan. A card is requested and nothing is
billed. **The Applications screen does not exist until this is done** — the
menu is simply absent, which reads as a missing feature rather than a
missing plan.

## Step 4 — one self-hosted application, one policy

**Access controls → Applications → Add an application → Self-hosted.**

- **Application domain**: the hostname from step 2
- **Path**: leave it **empty**. A path here protects *only* that path and
  leaves everything else open
- **Policy**: a single `Action: Allow` with `Include: Emails == you@example.com`

Two semantics bite here:

- The default is **deny**. Anything not matched by an Allow policy is
  refused, which is what you want.
- **Multiple `Include` rules are OR.** Writing "email matches" and "country
  is X" as two `Include` rules means *either* one admits you — a hole, not a
  tightening. AND is spelled `Require`.

## Step 5 — turn on Managed OAuth

Edit the application → **Additional settings** tab → **OAuth** pill →
**Managed OAuth (Beta)** → Save. No confirmation appears; it is in effect.

Two navigation notes, both of which cost real time:

- Cloudflare's documentation calls this tab **Advanced settings**. The UI
  labels it **Additional settings**, and an in-page search for "advance"
  returns nothing — so looking for it by name fails.
- The tab is subdivided into pills (All / App launcher settings / Tags /
  … / OAuth). **The OAuth settings do not render until the OAuth pill is
  selected.**

What the switch actually changes is the unauthenticated response, and that
is the whole feature:

| | OFF | ON |
|---|---|---|
| Unauthenticated HTTP response | **302** to a sign-in page | **401** |
| `WWW-Authenticate` | absent | `Bearer realm="OAuth" … resource_metadata=…` |
| Discovery documents | absent | present |

**A 302 cannot be followed by an MCP client.** A programmatic client that
reaches an HTML login page has nowhere to go and reports a failed
connection. A 401 carrying discovery metadata tells it, mechanically, where
to authenticate. That difference is the entire reason Managed OAuth is
required rather than optional.

Three endpoints appear, all returning 200 once it is on:

```
/.well-known/oauth-protected-resource        authorization server location (RFC 9728)
/.well-known/oauth-protected-resource/mcp    the per-path variant clients actually read
/.well-known/oauth-authorization-server      authorize / token / registration / revoke
```

The last one advertises a `registration_endpoint` and `S256` in
`code_challenge_methods_supported`.

## Step 6 — write the redirect-URI allowlist

**This is where it stops, and the error does not say so.**

With the allowlist empty — the default — every dynamic client registration
is rejected. ChatGPT reports only "Couldn't create the MCP app. Please try
again." Hitting the registration endpoint directly is what produces a
diagnosis:

```bash
curl -i -X POST https://<team-name>.cloudflareaccess.com/cdn-cgi/access/oauth/registration \
  -H 'content-type: application/json' \
  -d '{"client_name":"probe",
       "redirect_uris":["https://chatgpt.com/connector_platform_oauth_redirect"],
       "grant_types":["authorization_code","refresh_token"],
       "response_types":["code"],
       "token_endpoint_auth_method":"none"}'
```

```
HTTP/2 400
{"error":"invalid_client_metadata",
 "error_description":"redirect_uri is not allowed by the account configuration"}
```

The allowlist exists because dynamic registration lets anyone self-declare
where to be redirected after authorization. Trusting that declaration lets
an attacker register their own server and collect authorization codes, so
the default is empty and rejects everything. Defaulting closed is correct;
the cost is that the client-side error says nothing about why.

**Expand the `>` arrow next to Managed OAuth (Beta)** — switching it on does
not reveal the fields — and fill in **Allowed redirect URIs**. ChatGPT needs
**two** lines:

```
https://chatgpt.com/connector_platform_oauth_redirect
https://chatgpt.com/connector/oauth/*
```

It picks between them based on whether your authorization server satisfies
RFC 9207 issuer identification. Listing only one produces the same opaque
400 when it chooses the other. Trailing `/*` is supported and matches
subpaths.

The same panel holds three more settings that matter:

| Setting | Why it matters |
|---|---|
| **Allow localhost clients** | Claude Code, VS Code and `mcp-remote` redirect to `http://localhost:<port>/callback`. Off means they cannot connect |
| **Allow loopback clients** | A **separate** switch for `127.0.0.1`. Clients differ in which they use, so turn on both |
| **Access token lifetime** / **Grant session duration** | See below |

The last pair interacts in a way worth getting right. **Policy is
re-evaluated each time an access token is refreshed.** Short access tokens
(the 15-minute default is fine) with a long grant session therefore give you
both halves: nobody is asked to sign in again, and a policy you tighten
later takes effect on connections that already exist. Reversed, existing
connections keep passing an old decision.

The API field, if you configure this outside the dashboard, is
`oauth_configuration.dynamic_client_registration.allowed_uris`.

### Check that the allowlist is not wider than it reads

| Registered redirect URI | Result |
|---|---|
| ChatGPT fixed URI | 201 |
| `https://chatgpt.com/connector/oauth/abc123` | 201 — the `/*` works |
| `http://localhost:51000/callback` | 201 |
| `http://127.0.0.1:51000/callback` | 201 |
| `https://evil.example.com/callback` | **400** |
| `https://chatgpt.com.evil.example/…` | **400** — no prefix-matching hole |

The last row is the one to re-run yourself. An allowlist matched by prefix
would admit a lookalike host that merely starts with the string you trusted.

A registered client still reads nothing. What may be read is decided by the
step 4 policy; registration only grants the right to *ask*.

### Registered clients cannot be deleted, or listed

Measured, because probing creates them:

| Attempt | Result |
|---|---|
| `registration_access_token` in the 201 response | absent — RFC 7592 management is not implemented |
| `DELETE …/oauth/registration/<client_id>` | 404 |
| `DELETE …/oauth/registration?client_id=<id>` | 404 |
| Dashboard list / delete UI | not in the docs, changelog, or announcement |

"Connected Applications" under account settings is a different thing — it
lists third-party apps *you* authorized against your Cloudflare account, not
clients registered against your Access application. Easy to confuse.

The exposure is small: what persists is a `client_id`, with no secret
(`token_endpoint_auth_method: none`). Obtaining a token still requires
passing the browser sign-in, matching the policy, and consenting. But
**diagnostic registrations are permanent**, so give probes a `client_name`
that says what they were for. The only levers afterwards are Grant session
duration and the allowlist.

## Step 7 — hand over to Access, in this order

Access passes an identity header on requests it admitted, and
[`src/entry.py`](src/entry.py) already reads it, so there is no code to
write at this step:

```python
email = request.headers.get("cf-access-authenticated-user-email")
if email:
    allowed = getattr(self.env, "ALLOWED_EMAIL", None)
    return not allowed or email.strip().lower() == allowed.strip().lower()
```

Set `ALLOWED_EMAIL` if you want the Worker to check the identity itself as
well as the policy; leave it unset to accept anyone Access admitted. The
health check is behind the same gate — a triple count is small, but it is
exactly what leaks first when the proxy comes off, so "only POST needs
auth" is the wrong line to draw.

**No header means no.** That is the whole point of the arrangement: when
the proxy is removed or a second hostname appears, the graph becomes
unreadable rather than public.

The order still matters:

1. Deploy `workers_dev = false` (step 2)
2. Configure Access, the policy, and Managed OAuth (steps 4–6)
3. **Last**, delete the `AUTH_TOKEN` secret — and `DEV_OPEN`, if you ever
   set it

Deleting the token first costs you nothing now that the Worker fails
closed; it only makes the server unreachable until Access is in front. On
any server that still treats an unset token as open, that same order is
what publishes the graph.

### Why not verify the JWT in the Worker

Access also passes a signed JWT, and verifying it in the Worker is the
stricter design. It is not worth it here:

- Step 2 left exactly one route to the Worker, so there is no path that
  reaches it without passing the proxy
- Fetching JWKS and verifying RS256 inside Pyodide adds startup time and
  dependencies to a server whose startup cost is already the binding
  constraint (see [README](README.md#what-this-server-does-not-do))

With one route, trusting the header and verifying the JWT differ very
little. **The reasoning inverts the moment a second route exists** — if you
ever set `workers_dev = true` again, or add a hostname, add JWT
verification at the same time.

## Verifying it

Everything unauthenticated should be 401:

```bash
for p in / /mcp; do
  printf '%-6s %s\n' "$p" "$(curl -s -o /dev/null -w '%{http_code}' https://mcp.example.com$p)"
done
curl -s -o /dev/null -w 'POST /mcp -> %{http_code}\n' -X POST https://mcp.example.com/mcp \
  -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

A **302 means Managed OAuth is off** — authentication works, MCP clients
still cannot connect.

A spoofed identity header must not pass:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://mcp.example.com/mcp \
  -H 'Cf-Access-Authenticated-User-Email: you@example.com'
```

401. Access strips and rewrites that header before the origin sees it. A 200
here means something reaches the Worker without passing the proxy — go back
to step 2.

Discovery should be three 200s:

```bash
for u in /.well-known/oauth-protected-resource \
         /.well-known/oauth-protected-resource/mcp \
         /.well-known/oauth-authorization-server; do
  printf '%-48s %s\n' "$u" "$(curl -s -o /dev/null -w '%{http_code}' https://mcp.example.com$u)"
done
```

And the old free hostname should be gone — `https://<name>.<subdomain>.workers.dev/mcp`
returns 404, no route at all.

Worth running on every deploy, since the thing being checked is a dashboard
setting that no code change would disturb:

```bash
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$URL/mcp" \
         -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}')
case "$code" in
  401) echo "proxy is in front" ;;
  302) echo "::warning::authenticated but Managed OAuth looks off" ;;
  *)   echo "::error::unauthenticated access was not refused (got: ${code:-no connection})"; exit 1 ;;
esac
```

Do not assert `401` alone. A 302 is a different fault — protected but
unusable — and collapsing the two loses which one you have.

## Registering a client

No token is handed out. The URL is the whole configuration.

```bash
claude mcp add --transport http my-graph https://mcp.example.com/mcp
# browser opens once; refresh tokens keep it connected afterwards

npx -y mcp-remote@latest https://mcp.example.com/mcp   # for clients without OAuth
```

In ChatGPT's custom connector: the URL, authentication "OAuth", client
registration "Dynamic client registration (DCR)". Leave the header field
empty.

> ChatGPT also offers CIMD (client identifier metadata document), which is
> greyed out unless the server advertises support. Cloudflare's Managed
> OAuth does not, so DCR is the choice.

Creating ChatGPT connectors needs a paid plan. The server does not care —
VS Code's built-in MCP client, Claude Code, and `mcp-remote` all speak OAuth
remote MCP at no cost.

## Swapping the identity provider

The default sign-in is a one-time PIN by email. Adding Google is a common
next step, and the structural point is that **it changes nothing above the
proxy**:

```
MCP client ──OAuth 2.1 + DCR──▶ Access ──▶ this Worker
                                   │
                                   ▼  only this layer is swappable
                                 IdP: one-time PIN, Google, GitHub, SAML, OIDC…
```

Dynamic registration, discovery, the allowlist and the Worker's code are all
unchanged. Existing connectors do not need to be recreated. Only the
sign-in screen differs.

1. Google Cloud Console → OAuth 2.0 client, Application type **Web application**
2. Authorized redirect URI:
   `https://<team-name>.cloudflareaccess.com/cdn-cgi/access/callback`
   Authorized JavaScript origin: `https://<team-name>.cloudflareaccess.com`
3. Zero Trust → **Integrations → Identity providers → Add new identity
   provider → Google**, paste the client ID and secret

Google Workspace is not required; ordinary Google accounts work, though
without Workspace there are no groups, so policies are written against email
addresses.

**Adding Google does not remove the one-time PIN.** Both paths satisfy
`Include: Emails == …`. To require Google specifically, disable the PIN
provider or add `Require: Login method = Google` (`Require` is AND).

## When this is the wrong design

Auth-platform services can act as OAuth 2.1 servers with dynamic
registration, some with MCP-specific guides. That is a different
architecture, not a substitute:

| | Access in front (this page) | OAuth server in the app |
|---|---|---|
| Authorization lives | in the proxy; the server just reads a header | in the server; you verify tokens |
| Code to write | none | consent endpoint and verification, yours |
| Who authenticates | people you listed (free tier ~50) | your application's users, unbounded |
| Fits | yourself, or a small closed group | a product with per-user data separation |

The authorization code this page removed from the server comes back in the
right-hand column. For one person that is a straight loss. For a product
where different users must see different subsets of the graph, the proxy
cannot express that and the right-hand column is correct. **Choose on number
of users and data-separation requirements**, not on which sounds stronger.

## What is still weak

- **Deleting the Access application removes the wall.** The Worker fails
  closed, so the graph becomes unreadable rather than public — but nothing
  detects the deletion. The 401 check above is the detector.
- **Trusting a header depends on there being one route.** Add a hostname and
  you owe yourself JWT verification.
- **Managed OAuth is beta.** Behaviour may change.
- **Allowlists rot.** Entries accumulate per client and there is no way to
  find unused ones but to look.
- **Registered clients cannot be deleted or listed** (measured above). Probes
  accumulate permanently; the only levers are grant duration and the
  allowlist.
- **The allowlist cannot be narrow.** Supporting mainstream clients means
  allowing `chatgpt.com` and localhost, so it can never mean "only my
  client". **Who may connect is decided by the policy, and only by the
  policy** — that is the thing to internalise.

## Summary

| Do | Because |
|---|---|
| Own the domain outright | free subdomains cannot sit behind the proxy |
| `workers_dev = false` | leave no route around the proxy — the premise of the design |
| Enable free Zero Trust | the Applications screen does not exist otherwise |
| One Allow policy, empty Path | `Include` is OR; a Path protects only that path |
| Managed OAuth on | turns 302 into 401 + discovery, the only way MCP connects |
| Fill the redirect allowlist | empty is the default and rejects everything, silently |
| Fail closed in the Worker | a missing proxy should read as an outage, not an opening |
| Delete the old token last | any other order opens a window |
