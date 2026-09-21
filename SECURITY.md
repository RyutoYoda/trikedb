# Security policy

## Supported versions

trikedb is pre-1.0 and fixes land on the latest release. If you are on an older
version, the upgrade is the patch.

## Reporting a vulnerability

Please report privately through GitHub's
[security advisory form](https://github.com/RyutoYoda/trikedb/security/advisories/new)
— not in a public issue, and not in a pull request.

Include what you need to make it reproducible: the version, the smallest graph
or request that triggers it, and what you expected instead. **Do not include real
data.** A report is easier to act on with a three-triple synthetic graph than
with an export of your production file, and nobody wants your production file.

Expect an acknowledgement within a week. Once there is a fix, the advisory is
published with credit unless you would rather not be named.

## What is in scope

- **Parsing a graph file.** A malicious YAML or JSON document must not be able to
  execute code, construct arbitrary Python objects, or escape the parser. Loading
  goes through `yaml.CSafeLoader`/`SafeLoader` only, so tags like
  `!!python/object` are rejected rather than resolved; a way around that is a
  vulnerability.
- **The write guard.** A predicate that is not declared, a link written against
  its declared `domain`/`range`, an action whose `requires` precondition never
  happened, or one signed by an actor outside its `by` type — each of these must
  be refused on *every* write path, including the CLI, the MCP tools and
  `import_source`. A sequence that lands a fact the ontology forbids is a
  vulnerability, not a quirk.
- **The MCP server and `trikedb serve`.** Path traversal out of the served graph,
  a write through a read-only mount, or an OAuth token accepted when it should
  not be (wrong issuer, wrong audience, expired, unsigned).
- **Anything that writes outside the file you named.** `init`, `import_source`
  and the HTML export all take paths; none of them should ever touch another one.

## What is not in scope

- **A SPARQL query that is slow or memory-hungry.** Everything is in memory and
  scans are linear by design. Queries are not sandboxed and are not meant to be —
  running untrusted SPARQL against your own process is the same trust decision as
  running untrusted Python.
- **Exposing a graph over HTTP without authentication.** `trikedb serve` binds
  where you tell it and authenticates when you configure OAuth. An open port is a
  deployment choice.
- **What is in the file.** trikedb stores what you write to it. It does not
  encrypt the graph, and it cannot tell a table name from a secret — so treat the
  YAML as source code, and keep credentials out of it.
- **Dependency advisories with no path to trikedb.** Please report those upstream.

## Two habits worth having

The graph file is a normal file in your repository, which means the usual rules
apply and are usually enough:

1. **Never put a credential in the graph.** Attributes are for provenance,
   schedules and ownership. If a value would be a problem in a public diff, it is
   a problem in the graph.
2. **Review what an agent writes.** MCP writes autosave to the YAML, and that is
   the point: the contribution arrives as a git diff you read before merging. The
   ontology stops an agent from inventing vocabulary; it cannot stop it from being
   confidently wrong inside the vocabulary.
