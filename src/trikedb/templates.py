"""Starting graphs, so the first thing you see is not an empty file.

The hardest part of adopting a knowledge graph is not the API, it is the
blank page: nothing about `triples: []` suggests what belongs in it. Each
template here is a small, *complete* graph of the shape people actually
build — declared predicates, a few facts, node types, and where it earns
it, a dated action with a precondition.

They are meant to be edited down to nothing and replaced. What survives
is the shape: the ontology block at the top, `prov:` on facts that came
from somewhere, and types on the nodes that have them.

Every template is loadable and passes its own ontology guard; a test
proves it, because a starter graph that does not load is worse than none.
"""

from __future__ import annotations

#: name -> (one-line description, YAML body)
TEMPLATES: dict = {}


def _template(name: str, summary: str, body: str) -> None:
    TEMPLATES[name] = (summary, body.lstrip("\n"))


def names() -> list:
    """Template names, in the order they are offered."""
    return list(TEMPLATES)


def render(name: str) -> str:
    """The YAML text of one template."""
    try:
        return TEMPLATES[name][1]
    except KeyError:
        raise ValueError(
            f"unknown template {name!r}. Available: {', '.join(TEMPLATES)}"
        ) from None


def summary(name: str) -> str:
    return TEMPLATES[name][0]


_template(
    "agent-memory",
    "what your agent keeps getting wrong about your systems",
    """
# What an agent cannot read off the code: which job feeds which table,
# which copy is the live one, who to ask. Point your agent at this file
# and the names it uses are names that exist.
#
#   trikedb ui memory.yaml          # look at it
#   trikedb mcp memory.yaml         # hand it to an agent (needs trikedb[mcp])
#
# Replace these facts with yours. Keep the ontology block: it is what
# stops an agent — or a tired human — from inventing a predicate.

ontology:
  predicates:
    OWNED_BY:    {description: "job or service -> the team accountable for it", domain: [job, service], range: team}
    PROVIDES:    {description: "vendor -> the job that pulls from it", domain: vendor, range: job}
    INGESTS_TO:  {description: "job -> the table it lands in", domain: job, range: table}
    READS:       {description: "service -> a table it depends on", domain: service, range: table}
    REPLACED_BY: {description: "the old thing -> the one to use instead", domain: table, range: table}
    AFFECTED_BY: {description: "table -> something that happened to it", domain: table}

nodes:
  crm-sync-job:      {type: job, label: "CRM sync", schedule: hourly}
  salesflow-crm:     {type: vendor, url: "https://runbook.example/salesflow"}
  RAW_CRM_CONTACTS:  {type: table, pii: true, owner_slack: "#data-platform"}
  LEGACY_DUMP:       {type: table, deprecated: true}
  billing-api:       {type: service}
  data-platform:     {type: team}

triples:
  - {s: salesflow-crm, p: PROVIDES, o: crm-sync-job, prov: "https://runbook.example/salesflow"}
  - {s: crm-sync-job, p: INGESTS_TO, o: RAW_CRM_CONTACTS, schedule: hourly}
  - {s: crm-sync-job, p: OWNED_BY, o: data-platform}
  - {s: billing-api, p: READS, o: RAW_CRM_CONTACTS}
  # The fact that saves an agent from a plausible wrong answer: there are
  # two tables with similar names and only one of them is current.
  - {s: LEGACY_DUMP, p: REPLACED_BY, o: RAW_CRM_CONTACTS, deprecated: true}
  # Something that happened, written with trikedb act — it carries the
  # date, who did it, and the state it left the table in.
  - {s: RAW_CRM_CONTACTS, p: AFFECTED_BY, o: "email column dropped for privacy",
     at: "2026-03-04", by: data-platform, state: applied}
""",
)


_template(
    "service-map",
    "who calls whom, who owns it, and which one is deprecated",
    """
# A map of running things. The question it answers on a bad day is
# "if this is down, what else is": one query away, instead of three
# people in a thread.
#
#   trikedb query svc.yaml -w "?caller CALLS ?svc" -w "?svc OWNED_BY ?team"

ontology:
  predicates:
    CALLS:       {description: "service -> a service it depends on at runtime", domain: service, range: service}
    OWNED_BY:    {description: "service -> the team accountable for it", domain: service, range: team}
    RUNS_IN:     {description: "service -> where it is deployed", domain: service, range: environment}
    ON_CALL_IS:  {description: "team -> the rotation to page", domain: team, range: rotation}
    REPLACED_BY: {description: "the retired service -> the one to use instead", domain: service, range: service}

nodes:
  checkout-api:   {type: service, repo: "https://github.com/example/checkout-api"}
  billing-api:    {type: service, repo: "https://github.com/example/billing-api"}
  billing-legacy: {type: service, deprecated: true}
  notifier:       {type: service}
  payments:       {type: team}
  growth:         {type: team}
  prod:           {type: environment}
  payments-primary: {type: rotation}

triples:
  - {s: checkout-api, p: CALLS, o: billing-api}
  - {s: checkout-api, p: CALLS, o: notifier}
  - {s: billing-api, p: OWNED_BY, o: payments}
  - {s: checkout-api, p: OWNED_BY, o: growth}
  - {s: billing-api, p: RUNS_IN, o: prod}
  - {s: payments, p: ON_CALL_IS, o: "payments-primary"}
  # The one everybody wastes twenty minutes on.
  - {s: billing-legacy, p: REPLACED_BY, o: billing-api, deprecated: true}
""",
)


_template(
    "decision-log",
    "changes that cannot be recorded unless they were approved first",
    """
# A log where the rules are enforced rather than remembered. DEPLOYED_TO
# requires an APPROVED_BY on the same change and must be signed by a
# person — so "deployed, approved by nobody" is not a thing you can
# write down, even by accident.
#
#   trikedb act decisions.yaml CHG-0002 APPROVED_BY sam --by sam --state approved
#   trikedb history decisions.yaml CHG-0002
#   trikedb audit decisions.yaml        # re-checks the finished file

ontology:
  predicates:
    PROPOSED_BY: {description: "change -> who raised it", domain: change, range: person, by: person}
    APPROVED_BY: {description: "change -> who signed it off", domain: change, range: person, by: person}
    DEPLOYED_TO:
      description: "change -> where it went live"
      domain: change
      range: environment
      requires: APPROVED_BY    # refused outright if nobody approved it
      by: person               # and an unsigned deploy is refused too
    SUPERSEDES:  {description: "change -> the decision it overturns", domain: change, range: change}

nodes:
  CHG-0001: {type: change, label: "Drop the email column from RAW_CRM_CONTACTS"}
  CHG-0002: {type: change, label: "Move the CRM sync to hourly"}
  CHG-0003: {type: change, label: "Keep the email column, hashed"}
  prod:     {type: environment}
  sam:      {type: person}
  rin:      {type: person}

triples:
  - {s: CHG-0001, p: PROPOSED_BY, o: rin, at: "2026-03-01", by: rin, state: proposed}
  - {s: CHG-0001, p: APPROVED_BY, o: sam, at: "2026-03-03", by: sam, state: approved}
  - {s: CHG-0001, p: DEPLOYED_TO, o: prod, at: "2026-03-04", by: rin, state: live}
  # CHG-0002 is proposed and not approved. Try to deploy it and the write
  # is refused, with the reason — that is the whole point of the file.
  - {s: CHG-0002, p: PROPOSED_BY, o: sam, at: "2026-03-05", by: sam, state: proposed}
  # A decision is rarely deleted; it is overturned by a later one.
  - {s: CHG-0003, p: SUPERSEDES, o: CHG-0001}
  - {s: CHG-0003, p: PROPOSED_BY, o: rin, at: "2026-03-06", by: rin, state: proposed}
  - {s: CHG-0003, p: APPROVED_BY, o: sam, at: "2026-03-07", by: sam, state: approved}
  - {s: CHG-0003, p: DEPLOYED_TO, o: prod, at: "2026-03-08", by: rin, state: live}
""",
)


_template(
    "minimal",
    "three facts and nothing else, to build up from",
    """
# The smallest thing that is still a graph. Add facts; when a predicate
# has earned a rule, move it into an ontology block:
#
#   ontology:
#     predicates:
#       INGESTS_TO: {description: "job -> table", domain: job, range: table}

triples:
  - {s: salesflow-crm, p: PROVIDES, o: crm-sync-job}
  - {s: crm-sync-job, p: INGESTS_TO, o: RAW_CRM_CONTACTS, schedule: hourly}
  - {s: LEGACY_DUMP, p: REPLACED_BY, o: RAW_CRM_CONTACTS, deprecated: true}
""",
)
