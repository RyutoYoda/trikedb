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
        assert page.locator("#events .chip").count() == 3
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
        assert not errors, errors
        browser.close()
        print(json.dumps({"normal_graph": "passed", "sparql": "passed",
                          "action_layer": "passed",
                          "html_injection_and_special_names": "passed"}))


if __name__ == '__main__':
    run()
