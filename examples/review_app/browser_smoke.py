"""Browser checks for draft history and readable relationship labels.

Run against the local Docker example after starting Compose.
"""

import os

from playwright.sync_api import sync_playwright


def overlaps(left, right):
    return (
        left["x"] < right["x"] + right["width"]
        and left["x"] + left["width"] > right["x"]
        and left["y"] < right["y"] + right["height"]
        and left["y"] + left["height"] > right["y"]
    )


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(
            os.environ.get("REVIEW_APP_URL", "http://127.0.0.1:8765/"),
            wait_until="networkidle",
        )
        branch = page.locator(".workflow-flow .flow-column").nth(2)
        assert branch.locator(".step-wrap").count() == 2
        page.wait_for_function(
            "document.querySelectorAll('.workflow-flow .connection-label').length === 3"
        )
        assert page.locator(".workflow-flow marker#workflow-arrowhead").count() == 1
        assert page.locator(".workflow-flow .connection-path[marker-end='url(#workflow-arrowhead)']").count() == 3
        upper, lower = [
            step.bounding_box() for step in branch.locator(".step-wrap").all()
        ]
        assert upper and lower and upper["x"] == lower["x"] and upper["y"] < lower["y"]
        page.evaluate(
            """async () => {
              const state = await (await fetch('/api/state')).json();
              localStorage.setItem('trikedb-review-example', JSON.stringify({
                sha: state.sha,
                operations: [
                  {kind: 'edge', action: 'add', s: 'review-guide', p: 'USES', o: 'order-form'},
                  {kind: 'edge', action: 'add', s: 'review-guide', p: 'DOCUMENTED_IN', o: 'report-table'}
                ]
              }));
            }"""
        )
        page.reload(wait_until="networkidle")
        page.locator("#section-nodes").click()
        page.locator("#list .item").filter(has_text="Review guide").click()
        labels = page.locator(".connection-label")
        page.wait_for_function(
            "document.querySelectorAll('.connection-label').length === 3"
        )
        assert labels.count() == 3
        cards = [card.bounding_box() for card in page.locator(".flow .card").all()]
        for label in labels.all():
            bounds = label.bounding_box()
            assert bounds and all(not overlaps(bounds, card) for card in cards)
            hit = label.evaluate(
                """element => {
                  const box = element.getBoundingClientRect();
                  return element.contains(document.elementFromPoint(
                    box.x + box.width / 2, box.y + box.height / 2));
                }"""
            )
            assert hit, "Relationship label must remain clickable"

        assert page.locator("#change-count").inner_text() == "2"
        page.locator("#title").click()
        page.keyboard.press("Control+z")
        assert page.locator("#change-count").inner_text() == "1"
        page.keyboard.press("Control+y")
        assert page.locator("#change-count").inner_text() == "2"
        page.locator("#undo").click()
        assert page.locator("#change-count").inner_text() == "1"
        page.locator("#redo").click()
        assert page.locator("#change-count").inner_text() == "2"

        page.locator("#section-workflows").click()
        page.locator(".step-wrap .card").first.click()
        dialog = page.locator("#edit-dialog")
        assert dialog.is_visible()
        assert "step-editor-dialog" in dialog.get_attribute("class")
        box = dialog.bounding_box()
        assert box and box["y"] >= 0 and box["y"] + box["height"] <= 900
        assert page.locator(".step-related").is_visible()
        page.locator('[data-close="edit-dialog"]').first.click()

        page.locator("#history-open").click()
        assert page.locator("#history-dialog").is_visible()
        assert "GitHub" in page.locator("#history-body").inner_text()
        assert not errors, errors
        browser.close()


if __name__ == "__main__":
    main()
