from __future__ import annotations

from jira_agent.models import Ticket

DEMO_BUG_TICKET = Ticket(
    id="DEMO-1",
    project_key="DEMO",
    issue_type="Bug",
    summary="Checkout crashes when cart is empty",
    description=(
        "Steps to reproduce:\n"
        "1. Start checkout with an empty cart (no items added).\n"
        "2. Observe the request fails instead of showing a validation error.\n\n"
        "Expected: a clear 'cart is empty' error.\n"
        "Actual: an unhandled exception."
    ),
    url="https://example.atlassian.net/browse/DEMO-1",
)

UNCLEAR_BUG_TICKET = Ticket(
    id="DEMO-2",
    project_key="DEMO",
    issue_type="Bug",
    summary="Checkout sometimes doesn't work right",
    description="It just breaks sometimes, not sure why.",
    url="https://example.atlassian.net/browse/DEMO-2",
)

FEATURE_TICKET = Ticket(
    id="DEMO-3",
    project_key="DEMO",
    issue_type="Bug",
    summary="Add support for gift cards at checkout",
    description="We should let customers redeem gift cards during checkout. No bug, just a new capability.",
    url="https://example.atlassian.net/browse/DEMO-3",
)
