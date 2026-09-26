"""Four ways to hand trikedb a model, none of which trikedb depends on.

`db.extract(text, llm=...)` takes a callable: prompt in, text out. That is
the whole contract, and it is the reason this file lives in `examples/`
rather than in `src/`. trikedb never imports a vendor SDK, never reads an
API key, and never calls a model: the extraction path opens no socket at
all, and no release of it can break because a provider renamed a keyword
argument. (One optional extra does reach the network — `[semantic]` fetches
its embedding model the first time you search, about 1 GB. It is documented
under "The embedding model" in docs/REFERENCE.md, and nothing on this page
uses it.) You already have a model you pay for — bring it.

Each function below is the adapter for one provider, and each is three
lines of real work. Copy the one you use into your own code; there is
nothing to import from here.

    from trikedb import TrikeDB
    db = TrikeDB("graph.yaml")
    rows = db.extract(open("report.md").read(), llm=anthropic())
    for f in db.preview(rows):
        print(f["verdict"], f["triple"], f["detail"])

The prompt is built from `graph.yaml` itself — its declared predicates
and the node names already in it — so a model that gets it cannot answer
with a predicate the ontology would reject or a second spelling of a
company already in the file. Nothing is written until you write it.

Run this file to see the whole path against a temporary graph, with a
stand-in model and no network:

    python examples/extract_providers.py
"""


def openai(model: str = "gpt-5"):
    """OPENAI_API_KEY in the environment. `pip install openai`."""
    from openai import OpenAI

    client = OpenAI()

    def llm(prompt: str) -> str:
        reply = client.responses.create(model=model, input=prompt)
        return reply.output_text

    return llm


def anthropic(model: str = "claude-sonnet-5"):
    """ANTHROPIC_API_KEY in the environment. `pip install anthropic`."""
    import anthropic as sdk

    client = sdk.Anthropic()

    def llm(prompt: str) -> str:
        reply = client.messages.create(
            model=model, max_tokens=4096,
            messages=[{"role": "user", "content": prompt}])
        return "".join(block.text for block in reply.content
                       if block.type == "text")

    return llm


def gemini(model: str = "gemini-2.5-pro"):
    """GEMINI_API_KEY in the environment. `pip install google-genai`."""
    from google import genai

    client = genai.Client()

    def llm(prompt: str) -> str:
        return client.models.generate_content(model=model, contents=prompt).text

    return llm


def litellm(model: str = "gpt-5"):
    """Any of a hundred providers behind one name. `pip install litellm`.

    Worth knowing that this is a choice you make, not one trikedb makes
    for you: an abstraction layer is a dependency with its own release
    schedule, and the callable above is the seam it would otherwise own.
    """
    from litellm import completion

    def llm(prompt: str) -> str:
        reply = completion(model=model,
                           messages=[{"role": "user", "content": prompt}])
        return reply.choices[0].message.content

    return llm


def transcript(path: str):
    """The model is a person, and this is what they pasted back.

    Not a joke, and not only for tests: it is how you check a prompt
    against a model you have no API for, and how an extraction stays
    reproducible in review — the answer is a file someone can read, diff
    and correct. `trikedb extract` and `trikedb import --dry-run` are the
    same two halves from a shell.
    """
    def llm(prompt: str) -> str:
        return open(path, encoding="utf-8").read()

    return llm


def _demo() -> None:
    """The whole path on a temporary graph, with no model and no network."""
    import tempfile
    from pathlib import Path

    from trikedb import TrikeDB

    tmp = Path(tempfile.mkdtemp()) / "company.yaml"
    db = TrikeDB(tmp, ontology={"WORKS_AT": "who a person works for",
                                "BASED_IN": "where a company is"})
    db.declare_link("WORKS_AT", domain="person", range="company")
    db.declare("WORKS_AT", "functional")      # one employer at a time
    db.set_node("Acme", type="company")
    db.set_node("Tanaka", type="person")
    db.add("Tanaka", "WORKS_AT", "Acme", prov="the 2025 filing")

    document = ("Acme Corp. has moved its head office to Osaka. Sato joined "
                "the company in April 2026. Tanaka has left for Globex.")

    def stand_in(prompt: str) -> str:
        """What a model answers when the prompt carries the vocabulary."""
        assert "`WORKS_AT`" in prompt          # the predicates it may use
        assert "- Acme  (company)" in prompt   # the spellings it must reuse
        return ("| s | p | o | at | prov |\n|---|---|---|---|---|\n"
                "| Acme | BASED_IN | Osaka | | moved its head office to Osaka |\n"
                "| Sato | WORKS_AT | Acme | 2026-04-01 | Sato joined the company |\n"
                "| Tanaka | WORKS_AT | Globex | | Tanaka has left for Globex |\n")

    prompt = db.extract_prompt(document)
    print(f"{len(prompt)} characters of prompt, carrying "
          f"{len(db.ontology)} declared predicates and the entity names "
          f"already in the graph\n")

    rows = db.extract(document, llm=stand_in)
    for f in db.preview(rows):
        t = f["triple"]
        print(f"  {f['verdict']:9} {t['s']} {t['p']} {t['o']}")
        if f["detail"] != "new fact":
            print(f"  {'':9} └ {f['detail']}")

    print("\nNothing is written yet. Two rows are plainly new; the third says "
          "\nTanaka works somewhere else, which the graph has been told cannot "
          "\nbe true at the same time as what it already holds. That is a "
          "\nquestion for a person, and it is being asked before the write "
          "\nrather than found in a diff afterwards.")


if __name__ == "__main__":
    _demo()
