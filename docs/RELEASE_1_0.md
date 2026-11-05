# TrikeDB 1.0 release gates

The 1.0 label means a stable contract for a small, curated, single-document
knowledge graph. It does not imply a distributed RDF dataset server or
unbounded scale. Do not bump the version until every gate below has evidence.

| Gate | Evidence required | Current state |
|---|---|---|
| File/API compatibility | Frozen YAML and Python API examples; round-trip fixtures across the last supported release and 1.0 | Published 0.49.0 YAML and 16 public method signatures are frozen in fixtures. Published 1.0.0 passed a clean read/query/write/save smoke, and the published 0.49.0 reader accepted its saved YAML |
| RDF interoperability | Turtle, N-Triples and JSON-LD round trips checked by an independent RDF parser, including IRIs, literals, language tags, blank nodes and metadata | The full projected graph passes isomorphic round trips in all three formats in the 1.0.0 source test suite |
| SHACL behavior | Standard Turtle shapes and reports compared with pySHACL on valid and invalid fixtures | Ten common Core constraints plus class and SPARQL shapes pass through the installed CLI against pySHACL in the 1.0.0 source test suite |
| Safe local edits | Two processes cannot silently overwrite each other; MCP/REST see external local edits; malformed reload never turns into an empty graph | Implemented; PR #34 passed Linux, macOS and Windows CI |
| Manual YAML validation | A documented strict load/check mode rejects undeclared or contradictory facts without preventing repair of historical files | Implemented as opt-in `validate_on_load` plus audit; PR #35 CI passed |
| Remote safety | S3 and SQL conflict tests; explicit limitations for other remote backends; live integration evidence where credentials exist | Fake S3/SQL conflict tests and an isolated S3 API integration smoke pass. Published 1.0.0 passed a live Snowflake write/reload/stale-writer test and SQL view checks in a disposable transient database, which was dropped and verified absent. Live AWS S3 remains unverified because the available session policy explicitly denied bucket creation and access |
| Offline graph export | A private graph can be opened without CDN requests; browser smoke checks the exported file offline | Implemented; PR #36 browser CI passed with network disabled |
| Release provenance | CI for supported Python versions, typed package marker, signed or otherwise verifiable release artifact, GitHub release notes and PyPI publishing without a long-lived token | Version 1.0.0 passed main CI and the complete Trusted Publisher workflow. Both PyPI artifacts passed provenance verification and SHA256 matched the GitHub Release |
| Scale and adoption | Published performance envelope and at least one independent installation/use report | The benchmark documents a measured envelope, and a private independent installation/use report exists. Public adoption is not claimed |

The gates are release criteria, not a reason to publish an intermediate package
after each fix. Merge compatible improvements into `main`, then perform one
versioned release after the complete gate review.

For the 1.0 decision, the stable contract covers the documented single-file
graph and public Python API. S3 and warehouse backends remain optional and
retain the explicit limitations in `docs/REFERENCE.md`. A live Snowflake
test used a dedicated transient database with zero-day retention. Published
1.0.0 created its table and four views, wrote and reloaded a graph, rejected
a stale writer, and exposed two edges through both SQL projection views. The
database was dropped and verified absent. The available AWS session policy
explicitly denied both creation of a disposable bucket and access to the
candidate test buckets, so no live S3 write is claimed. The isolated S3 API
smoke and SQL conflict tests cover their conditional-write behavior.

The compatibility fixture in `tests/fixtures/compat_0_48_1.yaml` was written
by the published 0.48.1 Python API. The newer
`tests/fixtures/compat_0_49_0.yaml` and `public_api_0_49_0.json` were written
from the published 0.49.0 package. The committed tests cover the forward read,
edit, and save direction plus the documented public method signatures. On
2026-11-05, the published 0.49.0 reader also opened a file edited and saved
by the current code. This checks representative public behavior, not every
possible graph or API call. The published 0.49.0 reader also accepted YAML
saved by the published 1.0.0 artifact.

## Release procedure (after every gate passes)

1. Merge the version change and release notes to `main`, then wait for all
   normal CI jobs to pass. Create and push an annotated `vX.Y.Z` tag at that
   exact commit. Do not reuse or move a published tag.
2. Configure PyPI Trusted Publishing for owner `RyutoYoda`, repository
   `trikedb`, workflow `publish.yml`, environment `pypi`. Confirm the GitHub
   environment exists and its protection policy permits a dispatch from main.
3. Run `Publish to PyPI` on `main` with input `version=X.Y.Z`. The workflow
   checks out the existing tag, requires it to be reachable from main, checks
   the version, builds and smokes wheel and sdist, attests both distributions,
   publishes through OIDC, and then creates a GitHub Release with release
   notes, distributions, attestations, and SHA256 checksums.
4. Install the new version from PyPI in a clean environment; verify its
   reported version, packaged assets, a read/query/write round trip, and an
   offline HTML export. Verify the GitHub Release and PyPI attestations before
   marking this gate complete.

The [1.0.0 publish run](https://github.com/RyutoYoda/trikedb/actions/runs/42013000473)
built and smoke-tested wheel and sdist, uploaded both through PyPI Trusted
Publishing, and created the [GitHub Release](https://github.com/RyutoYoda/trikedb/releases/tag/v1.0.0).
Both PyPI artifacts passed `pypi-attestations verify pypi --repository
https://github.com/RyutoYoda/trikedb`, and their PyPI SHA256 digests matched
the GitHub Release checksums. A clean no-cache install from the public PyPI
index passed version, packaged asset, read/query/write/save, and offline HTML
checks. Published 0.49.0 also read a YAML file saved by published 1.0.0.

The S3 API smoke runs against a disposable in-memory endpoint with fake test
credentials: `uv run --extra remote --with 'moto[server]' python
benchmarks/s3_conflict_smoke.py`. This checks the actual `s3fs` conditional PUT
path and stale-writer rejection. It does not claim a live AWS S3 test or a
long-running replica test.
