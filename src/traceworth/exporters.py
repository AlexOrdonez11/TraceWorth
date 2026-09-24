"""Optional HTTP delivery using the standard library; SDK remains backend-independent."""
import ipaddress
import json
import math
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        # Never forward ingestion credentials to a redirected destination.
        return None


class HttpExporter:
    """Send each queued event to a scoped TraceWorth ingestion endpoint.

    Transport errors propagate to the SDK export worker, where they increment
    export_errors without interrupting the application. This is best-effort
    delivery: there is no retry or durable spool in this version.
    """

    def __init__(self, endpoint: str, api_key: str, *, timeout: float = 5.0):
        if not isinstance(endpoint, str):
            raise ValueError("endpoint must be an HTTP URL")
        parsed = urlsplit(endpoint)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname:
            raise ValueError("endpoint must not contain credentials, a query, or a fragment")
        loopback = parsed.hostname == "localhost"
        try:
            loopback = loopback or ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            pass
        if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
            raise ValueError("Use HTTPS, or HTTP on loopback for local development")
        if not isinstance(api_key, str) or not api_key.strip() or any(c.isspace() for c in api_key):
            raise ValueError("api_key must be a nonempty token without whitespace")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a finite positive number")
        self.endpoint = endpoint
        self._api_key = api_key
        self.timeout = timeout
        self._opener = build_opener(_NoRedirect())

    def __call__(self, event: dict):
        payload = json.dumps({"events": [event]}, allow_nan=False).encode("utf-8")
        request = Request(self.endpoint, data=payload, method="POST", headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {self._api_key}"})
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                result = json.load(response)
        except HTTPError as error:
            error.close()
            raise
        if not isinstance(result, dict) or type(result.get("accepted")) is not int or type(result.get("duplicates")) is not int:
            raise ValueError("Ingestion did not acknowledge the event")
        if result["accepted"] < 0 or result["duplicates"] < 0 or result["accepted"] + result["duplicates"] != 1:
            raise ValueError("Ingestion did not acknowledge exactly one event")
