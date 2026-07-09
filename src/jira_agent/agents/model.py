from __future__ import annotations

from google.adk.models import Gemini

from jira_agent.config import Settings


def build_gemini_model(settings: Settings) -> Gemini:
    """Shared Gemini 3 Flash model handle, routed through Vertex AI.

    Both the Triage and Fix-Loop agents use this factory so model/project/
    location configuration lives in exactly one place.
    """
    return Gemini(
        model=settings.gemini_model,
        client_kwargs={
            "vertexai": True,
            "project": settings.google_cloud_project,
            "location": settings.google_cloud_location,
        },
    )
