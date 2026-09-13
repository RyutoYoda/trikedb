"""Run with python tests/browser_smoke.py; requires Playwright + Chromium.

Uses a fresh browser context, generated temporary pages, and no user profile.
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import sync_playwright
from trikedb import TrikeDB


def run():
    with TemporaryDirectory(prefix="trikedb-browser-") as root, sync_playwright() as pw:
        chrome = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
        browser = pw.chromium.launch(headless=True, **(
            {"executable_path": str(chrome)} if chrome.exists() else {}))
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(e.stack))
        db = TrikeDB()
        db.add("CRM", "INGESTS_TO", "CUSTOMERS", schedule="hourly")
        db.set_node("CUSTOMERS", type="table", pii=True)
        normal = Path(root) / "normal.html"
        db.to_html(normal)
        page.goto(normal.as_uri(), wait_until="networkidle")
        page.wait_for_selector("canvas")
        page.locator("#btn-sparql").click()
        page.locator("#sparql-input").fill("SELECT ?s WHERE {?s t:INGESTS_TO t:CUSTOMERS}")
        page.locator("#btn-run").click()
        page.wait_for_function("document.querySelector('#results').textContent.includes('CRM')")
        assert not errors, errors
        page.locator("#btn-sparql").click()
        page.evaluate("showDetail('CUSTOMERS')")
        assert "pii: true" in page.locator("#detail-body").inner_text()

        # --- action layer: an event belongs to the node it happened to ----
        ops = TrikeDB()
        ops.add("RAW_SPEND", "AFFECTED_BY", "units changed to micros",
                at="2025-04-01", by="adastra", state="applied")
        ops.add("RAW_SPEND", "AFFECTED_BY", "backfill sheet superseded",
                at="2025-07-02", by="data-platform", state="pending-review")
        ops.add("Baltic states", "EVENTS", "Operation Bagration", at="1944-06-22")
        ops.add("Operation Bagration", "PART_OF", "WWII")
        ops.set_node("RAW_SPEND", type="table")
        actions = Path(root) / "actions.html"
        ops.to_html(actions)
        page.goto(actions.as_uri(), wait_until="networkidle")
        page.wait_for_selector("canvas")
        # the node wears the state the last event left it in
        assert page.evaluate("currentState('RAW_SPEND')") == "pending-review"
        assert page.evaluate("eventsOf['RAW_SPEND'].length") == 2
        assert page.evaluate("timeOf(eventsOf['RAW_SPEND'][0])") == "2025-07-02"  # newest first
        # a real node that an event points at is still a real node
        assert page.evaluate("eventNodes.has('Operation Bagration')") is False
        assert page.evaluate("eventNodes.has('units changed to micros')") is True
        assert "\u25b8 pending-review" in page.evaluate(
            "nodes.get(nodeIds.get('RAW_SPEND')).label").lower()
        # and the history reads off the node, newest first, with its state
        page.evaluate("showDetail('RAW_SPEND')")
        detail = page.locator("#detail-body").inner_text()
        assert "events" in detail.lower()   # the h3 is uppercased by CSS
        assert "pending-review" in detail and "2025-07-02" in detail
        assert detail.index("2025-07-02") < detail.index("2025-04-01")
        # the event is drawn on the LINE between the two objects: its label
        # is the date and the state it left behind, not the predicate name
        ev = page.evaluate(
            "edges.get(TRIPLES.findIndex(t => t.o === 'backfill sheet superseded'))")
        assert ev["label"] == "2025-07-02  \u25b8 pending-review"
        assert ev["font"]["color"] == "#f7784f"
        assert page.evaluate("eventEdgeIds.length") == 3
        # clicking a line opens the node it hangs off — it used to do nothing
        page.evaluate("network.selectEdges([0]); focusNode(TRIPLES[0].s)")
        assert page.locator("#detail").is_visible()
        # the strip along the bottom is the same events in time order, which
        # is the reading the graph cannot give: it is up without being asked,
        # newest first, and clicking one opens the node it happened to
        assert page.locator("#strip").is_visible()
        assert page.locator("#striprail .tick").count() == 3
        ticks = page.locator("#striprail").inner_text()
        assert ticks.index("2025-07-02") < ticks.index("2025-04-01")
        # a date and an id is not a log line: without the predicate a tick
        # reading "2025-07-02  RAW_SPEND" does not say what was done to it
        first = page.locator("#striprail .tick").first
        assert "AFFECTED_BY" in first.inner_text()
        assert "RAW_SPEND" in first.inner_text()
        first.click()
        assert "RAW_SPEND" in page.locator("#detail-body").inner_text()
        # the header button folds the strip away and back
        page.click("#btn-events")
        assert not page.locator("#strip").is_visible()
        page.click("#btn-events")
        assert page.locator("#strip").is_visible()
        # and the whole log still opens in the panel, from the strip's label
        page.click("#btn-fulllog")
        log = page.locator("#detail-body").inner_text()
        assert "action log" in log and "3 events" in log.lower()  # the h3 is uppercased by CSS
        assert log.index("2025-07-02") < log.index("2025-04-01")
        assert "AFFECTED_BY" in log and "backfill sheet superseded" in log
        assert not errors, errors

        # --- which event is "the latest" when the dates do not settle it --
        order = TrikeDB()
        order.add("JOB", "AFFECTED_BY", "first write of the day",
                  at="2025-05-09", state="applied")
        order.add("JOB", "AFFECTED_BY", "second write, same day",
                  at="2025-05-09", state="rolled-back")
        # unpadded, so a plain string compare ranks "4" after "12"
        order.add("PAD", "AFFECTED_BY", "December", at="2025-12-1",
                  state="applied")
        order.add("PAD", "AFFECTED_BY", "April", at="2025-4-1",
                  state="superseded")
        ordered = Path(root) / "ordering.html"
        order.to_html(ordered)
        page.goto(ordered.as_uri(), wait_until="networkidle")
        page.wait_for_selector("canvas")
        # a tie on the day is broken by file order: appended later, later
        assert page.evaluate("currentState('JOB')") == "rolled-back"
        assert page.evaluate("timeOf(eventsOf['JOB'][0])") == "2025-05-09"
        # December beats April however sloppily the two are written
        assert page.evaluate("currentState('PAD')") == "applied"
        assert page.evaluate("timeOf(eventsOf['PAD'][0])") == "2025-12-1"
        assert page.evaluate("timeOf(timeline[0])") == "2025-12-1"
        assert not errors, errors

        # --- act(): the node really changed, and the log kept both runs ---
        acted = TrikeDB(ontology={"AFFECTED_BY": {"description": "table -> change",
                                                  "domain": "table"}})
        acted.set_node("PIPELINE", type="table")
        acted.act("PIPELINE", "AFFECTED_BY", "restarted after failure",
                  at="2025-04-01", by="alice", state="applied")
        acted.act("PIPELINE", "AFFECTED_BY", "restarted after failure",
                  at="2025-09-12", by="bob", state="rolled-back")
        run = Path(root) / "acted.html"
        acted.to_html(run)
        page.goto(run.as_uri(), wait_until="networkidle")
        page.wait_for_selector("canvas")
        # the same sentence twice is two things that happened, not one fact
        assert page.evaluate("eventsOf['PIPELINE'].length") == 2
        # the state act() wrote onto the node is what the page shows
        assert page.evaluate("NODES_META['PIPELINE'].state") == "rolled-back"
        assert page.evaluate("currentState('PIPELINE')") == "rolled-back"
        assert "\u25b8 rolled-back" in page.evaluate(
            "nodes.get(nodeIds.get('PIPELINE')).label").lower()
        page.evaluate("showDetail('PIPELINE')")
        detail = page.locator("#detail-body").inner_text()
        assert "alice" in detail and "bob" in detail
        assert detail.index("2025-09-12") < detail.index("2025-04-01")
        assert not errors, errors

        # --- the declarations are on the page, not only in the file ------
        onto = TrikeDB(ontology={
            "PLACED_BY": {"description": "order -> customer who placed it",
                          "domain": "order", "range": "customer"},
            "SHIPPED_FROM": {"description": "order -> warehouse it left from",
                             "domain": "order", "range": "warehouse",
                             "requires": "PLACED_BY", "by": "picker"},
            "NOTE": "free text about anything",
        })
        onto.set_node("ORD-1", type="order")
        onto.set_node("C-1", type="customer")
        onto.set_node("WH-1", type="warehouse")
        onto.set_node("pat", type="picker")
        onto.add("ORD-1", "PLACED_BY", "C-1", at="2025-01-01")
        onto.act("ORD-1", "SHIPPED_FROM", "WH-1", at="2025-01-02", by="pat")
        rules_page = Path(root) / "rules.html"
        onto.to_html(rules_page)
        page.goto(rules_page.as_uri(), wait_until="networkidle")
        page.wait_for_selector("canvas")
        page.click("#btn-onto")
        shown = page.locator("#detail-body").inner_text().lower()
        # every predicate, whether or not anything is declared about it
        assert "3 predicates" in shown and "2 enforced" in shown
        assert "nothing declared" in shown            # NOTE, and it says so
        assert "must have happened first: placed_by" in shown
        assert "may only be done by: picker" in shown
        assert "subject must be: order" in shown
        # and a predicate chip beside a fact opens that predicate's own rule
        page.evaluate("showDetail('ORD-1')")
        page.locator("#detail-body .pred[data-pred='SHIPPED_FROM']").first.click()
        one = page.locator("#detail-body").inner_text()
        assert page.locator("#detail-body h2").inner_text() == "SHIPPED_FROM"
        assert "PLACED_BY" in one and "picker" in one
        assert "NOTE" not in one                       # this predicate alone
        assert not errors, errors

        # --- a node reads as what it is, and keeps its id ----------------
        named = TrikeDB(ontology={"RAISED_BY": {"description": "incident -> who raised it"},
                                  "AFFECTED": "incident -> service"})
        named.set_node("INC-7", type="incident",
                       summary="checkout 5xx spike during the spring sale")
        named.set_node("SVC-1", type="service", name="checkout-api")
        named.set_node("ORD-9", type="order")            # no words of its own
        named.add("INC-7", "AFFECTED", "SVC-1")
        named.add("INC-7", "RAISED_BY", "ORD-9", at="2025-01-20", state="open")
        names_page = Path(root) / "names.html"
        named.to_html(names_page)
        page.goto(names_page.as_uri(), wait_until="networkidle")
        page.wait_for_selector("canvas")
        page.evaluate("showDetail('INC-7')")
        head = page.locator("#detail-body h2").inner_text()
        assert head == "checkout 5xx spike during the spring sale", head
        assert page.locator("#detail-body .nodeid").inner_text() == "INC-7"
        # the words came from summary:, so the panel does not print it twice
        body = page.locator("#detail-body").inner_text()
        assert body.count("checkout 5xx spike during the spring sale") == 1, body
        # a link shows the name and still carries the id to open
        link = page.locator("#detail-body a.nodelink[data-node='SVC-1']").first
        assert link.inner_text() == "checkout-api"
        assert link.get_attribute("title") == "SVC-1"
        # a node with nothing to say stays its id, heading and link alike
        assert page.locator("#detail-body a.nodelink[data-node='ORD-9']").first.inner_text() == "ORD-9"
        page.evaluate("showDetail('ORD-9')")
        assert page.locator("#detail-body h2").inner_text() == "ORD-9"
        assert page.locator("#detail-body .nodeid").count() == 0
        # and the log reads in words too
        page.evaluate("showTimeline()")
        assert "checkout 5xx spike during the spring sale" in page.locator("#detail-body").inner_text()
        assert not errors, errors

        attack = TrikeDB()
        payload = '<img src=x onerror=document.documentElement.dataset.reviewInjected=1>'
        script = '</script><script>document.documentElement.dataset.reviewInjected=1</script>'
        tricky = 'name" onmouseover=document.documentElement.dataset.reviewInjected=1 x="'
        for name in ("__proto__", "constructor", "toString", "__NT__", "__FLOW_DEFAULT__", "__CONTENT_HASH__", "日本語", tricky):
            attack.add(name, payload, "target", graph=payload, note=script)
            attack.set_node(name, type=payload, description=script,
                            url='https://example.invalid/?a=1&b=2" onmouseover=bad')
        attack.set_node("__proto__", nonfinite=[float("nan"), float("inf"), -float("inf")])
        bad = Path(root) / "untrusted.html"
        attack.to_html(bad, title=script)
        page.goto(bad.as_uri(), wait_until="networkidle")
        page.wait_for_selector("canvas")
        for name in ("__proto__", "constructor", "__NT__", tricky):
            page.evaluate("name => showDetail(name)", name)
            assert name in page.locator("#detail-body h2").inner_text()
        page.evaluate("showDetail('target')")
        link = page.locator("a.nodelink").filter(has_text=tricky)
        assert link.count() == 1
        assert link.get_attribute("data-node") == tricky
        link.hover()
        link.click()
        assert page.locator("#detail-body h2").inner_text() == tricky
        assert page.locator("#detail-body a[href]").first.get_attribute("href") == 'https://example.invalid/?a=1&b=2'
        assert not page.locator("[onerror], [onmouseover]").count()
        assert not page.locator("html").get_attribute("data-review-injected")
        assert page.title() == script
        assert page.evaluate("Object.keys(NODES_META).includes('__proto__')")
        assert page.evaluate("TRIPLES.some(t => t.s === '__FLOW_DEFAULT__')")
        page.evaluate("showOntology()")   # predicate names are untrusted too
        assert not page.locator("[onerror], [onmouseover]").count()
        assert not page.locator("html").get_attribute("data-review-injected")
        assert not errors, errors

        # --- a filter re-frames what is left, and only when it must ------
        # Hiding a member graph used to leave the camera at the zoom chosen
        # for the whole workspace, so the part you asked to see stayed a
        # speck in whichever corner the layout had put it. Toggling a
        # predicate hides edges and moves no node, and re-framing for that
        # would be the jarring kind of help — so both halves are asserted.
        ws_dir = Path(root) / "ws"
        ws_dir.mkdir()
        for member, prefix in (("left", "L"), ("right", "R")):
            part = TrikeDB(ws_dir / (member + ".yaml"))
            with part.batch():
                for i in range(12):
                    part.add(prefix + str(i), "NEAR", prefix + str(i + 1))
        (ws_dir / "ws.yaml").write_text(
            "graphs:\n  left: left.yaml\n  right: right.yaml\n")
        ws_page = Path(root) / "ws.html"
        TrikeDB(ws_dir / "ws.yaml").to_html(ws_page)
        page.goto(ws_page.as_uri(), wait_until="networkidle")
        page.wait_for_selector("canvas")
        page.wait_for_timeout(1500)                      # let the layout settle
        view = lambda: page.evaluate(
            "() => [network.getScale(), network.getViewPosition().x,"
            "       network.getViewPosition().y]")

        def moved(a, b):
            return (abs(a[0] - b[0]) > a[0] * 0.02
                    or abs(a[1] - b[1]) > 5 or abs(a[2] - b[2]) > 5)

        assert page.evaluate("Object.keys(graphChips)") == ["left", "right"]
        before = view()
        page.evaluate("graphChips['right'].click()")
        page.wait_for_timeout(2500)                      # fit() animates
        assert moved(before, view()), (
            "hiding a member graph left the camera where it was", before, view())
        steady = view()
        page.evaluate("hiddenPreds.add('NEAR'); refreshVisibility();")
        page.wait_for_timeout(2000)
        assert not moved(steady, view()), (
            "a predicate toggle hides no node, but the camera moved anyway",
            steady, view())
        assert not errors, errors

        browser.close()
        print(json.dumps({"normal_graph": "passed", "sparql": "passed",
                          "action_layer": "passed", "act_and_log": "passed",
                          "declarations": "passed", "human_names": "passed",
                          "html_injection_and_special_names": "passed",
                          "workspace_filter_reframes": "passed"}))


if __name__ == '__main__':
    run()
