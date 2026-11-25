# Scaling a graph

Curated TrikeDB graphs are YAML or JSON files. Keep the definitions and R2RML
mappings in version control. Relational source rows remain in their database
and are queried through the [read-only virtual graph](VIRTUAL_GRAPH.md).

The measurements below were made with `benchmarks/backend_bench.py` on an
Apple-silicon laptop. They are historical medians of three synthetic runs,
not performance guarantees for the current release.

| triples | file format | open | 1-hop | 2-hop join | count all | write 1 fact |
|---|---|---|---|---|---|---|
| 408 | `.yaml` | 5 ms | 0.05 ms | 0.5 ms | 0.1 ms | 11 ms |
| 408 | `.json` | 0.3 ms | 0.04 ms | 0.5 ms | 0.1 ms | 1 ms |
| 40,800 | `.yaml` | 992 ms | 0.04 ms | 55 ms | 11 ms | 1,957 ms |
| 40,800 | `.json` | 57 ms | 0.04 ms | 55 ms | 11 ms | 148 ms |

JSON parses faster; YAML gives reviewers clearer diffs. Queries on a loaded
curated graph run in memory, independent of the file format. Batch larger
changes with `autosave=False` and one `save()`.

For a virtual graph, query latency also depends on the relational source,
its indexes or warehouse execution plan, and network round trips. The file
benchmarks above do not predict virtual graph performance. Keep the R2RML
mapping selective and push row filtering into `rr:sqlQuery` where practical.

## Practical choices

1. For a small curated graph, read the file directly and review changes in git.
2. For more consumers, serve the same file through REST or MCP and use
   `query`, `sparql`, or `search` instead of sending the whole file to agents.
3. For large relational data, leave rows in the source and expose a read-only
   virtual graph via R2RML. Do not copy the entire table into one graph file.

For feature-specific limits and benchmark methodology, see
[benchmarks/README.md](../benchmarks/README.md#where-is-the-ceiling).
