"""Turn proposals made in the curation screen into a pull request.

Note the direction. Most Snowflake/git plumbing runs git -> Snowflake: the
repository is the source of truth and the warehouse gets a copy. This runs
the other way, Snowflake -> git, and that is the whole point. The graph is
still owned by the repository; a proposal only becomes a fact once somebody
merges it.

    screen     save  = append one row to KG_OUTBOX
    here       drain = read the rows, apply them to the YAML, branch, open PR
    a human    review, merge
    whatever   push -> your existing job projects git -> Snowflake again

The layers:

    domain    Proposal, and the rules for applying one to a graph.
              Depends on trikedb and nothing else.
    ports     The three holes in the outside world (proposal queue, source
              of truth, review request), as Protocols.
    service   The drain use case. Knows only the two above.
    adapters  The implementations: Snowflake, GitHub, YAML codec.

domain and service import no snowflake connector, no HTTP client, nothing
cloud-shaped. The tests swap in fakes for the adapters and run offline.
"""
