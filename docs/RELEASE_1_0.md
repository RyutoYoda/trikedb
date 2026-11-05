# TrikeDB 1.0 release gates

The 1.0 label means a stable contract for a small, curated, single-document
knowledge graph. It does not imply a distributed RDF dataset server or
unbounded scale. Do not bump the version until every gate below has evidence.

| Gate | Evidence required | Current state |
|---|---|---|
| File/API compatibility | Frozen YAML and Python API examples; round-trip fixtures across the last supported release and 1.0 | Partial; published 0.48.1 YAML fixture is tested by current main; 1.0 round trip remains |
| RDF interoperability | Turtle, N-Triples and JSON-LD round trips checked by an independent RDF parser, including IRIs, literals, language tags, blank nodes and metadata | The full projected graph passes isomorphic round trips in all three formats; final 1.0 artifact check remains |
| SHACL behavior | Standard Turtle shapes and reports compared with pySHACL on valid and invalid fixtures | Four Core constraints plus class and SPARQL shapes pass through the CLI; broader conformance corpus remains |
| Safe local edits | Two processes cannot silently overwrite each other; MCP/REST see external local edits; malformed reload never turns into an empty graph | Implemented; PR #34 passed Linux, macOS and Windows CI |
| Manual YAML validation | A documented strict load/check mode rejects undeclared or contradictory facts without preventing repair of historical files | Implemented as opt-in `validate_on_load` plus audit; PR #35 CI passed |
| Remote safety | S3 and SQL conflict tests; explicit limitations for other remote backends; live integration evidence where credentials exist | Fake S3/SQL conflict tests and an S3 API integration smoke pass; a real cloud or warehouse integration has not been run |
| Offline graph export | A private graph can be opened without CDN requests; browser smoke checks the exported file offline | Implemented; PR #36 browser CI passed with network disabled |
| Release provenance | CI for supported Python versions, typed package marker, signed or otherwise verifiable release artifact, GitHub release notes and PyPI publishing without a long-lived token | PyPI Trusted Publisher is configured; the no-upload OIDC check passed in [run 42007538418](https://github.com/RyutoYoda/trikedb/actions/runs/42007538418). A real release and artifact verification remain unverified; issue #3 |
| Scale and adoption | Published performance envelope and at least one independent installation/use report | Measured envelope and a private independent installation report exist; public external adoption remains unverified |

The gates are release criteria, not a reason to publish an intermediate package
after each fix. Merge compatible improvements into `main`, then perform one
versioned release after the complete gate review.

The compatibility fixture in `tests/fixtures/compat_0_48_1.yaml` was written
by the published 0.48.1 Python API. On 2026-11-04, current `main` opened it
in strict mode, edited and saved it; the published 0.48.1 reader then opened
the edited file and saw both triples. The committed test covers the forward
direction in CI. This is a sample compatibility check, not a complete file or
Python API freeze. Repeat the reverse check with the final 1.0 artifact.

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

The workflow has not been run for 1.0. The no-upload OIDC check verifies the
publisher identity but does not prove that a distribution was uploaded,
attested, installed from PyPI, or included in a GitHub Release.

The S3 API smoke runs against a disposable in-memory endpoint with fake test
credentials: `uv run --extra remote --with 'moto[server]' python
benchmarks/s3_conflict_smoke.py`. This checks the actual `s3fs` conditional PUT
path and stale-writer rejection. It does not claim that a particular cloud
account, warehouse or long-running replica was tested.
