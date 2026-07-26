from __future__ import annotations

import logging

_log = logging.getLogger("conductor.auth")


def id_token_for_cloud_run(url: str) -> str | None:
    """Return a Google identity token for a Cloud Run service URL.

    Cloud Run IAM uses this in the ``Authorization: Bearer <token>`` header to
    authenticate service-to-service requests. Localhost URLs return ``None`` so
    the caller only sends the application-level ``X-Internal-Token``.
    """
    if not url or ".run.app" not in url:
        return None
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.id_token import fetch_id_token

        audience = url.rstrip("/")
        return fetch_id_token(Request(), audience=audience)
    except Exception as exc:
        _log.warning("could not fetch Cloud Run identity token for %s: %s", url, exc)
        return None
