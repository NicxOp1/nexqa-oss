"""
Request authentication for the webhook server.

Retell signs every custom-function request with the API key that has the
webhook badge. The `X-Retell-Signature` header looks like `v=<ms>,d=<hex>`,
where `<hex>` is HMAC-SHA256(key, raw_body + <ms>). This mirrors
`retell.lib.webhook_auth.verify` without pulling in the Retell SDK.
"""

import hashlib
import hmac
import re
import time
from typing import Optional

from fastapi import HTTPException, Request

from webhook_server.config import settings

SIGNATURE_TTL_MS = 5 * 60 * 1000
_SIGNATURE_RE = re.compile(r"v=(\d+),d=([0-9a-f]{64})")


def verify_retell_signature(
    raw_body: str,
    signature: Optional[str],
    key: str,
    now_ms: Optional[int] = None,
) -> bool:
    """Return True when `signature` is a fresh, valid Retell signature."""
    if not signature or not key:
        return False
    match = _SIGNATURE_RE.fullmatch(signature.strip())
    if not match:
        return False
    timestamp = int(match.group(1))
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    if abs(now_ms - timestamp) > SIGNATURE_TTL_MS:
        return False
    expected = hmac.new(
        key.encode(), (raw_body + str(timestamp)).encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, match.group(2))


async def read_verified_body(request: Request) -> str:
    """Read the raw body and reject requests Retell did not sign."""
    raw = (await request.body()).decode("utf-8")
    if not settings.verify_signatures:
        return raw

    key = settings.retell_webhook_key or settings.retell_api_key
    if not key:
        raise HTTPException(
            status_code=503,
            detail=(
                "Signature verification is on but no Retell key is set. "
                "Set RETELL_API_KEY (or RETELL_WEBHOOK_KEY), or VERIFY_SIGNATURES=false "
                "for local testing."
            ),
        )
    if not verify_retell_signature(raw, request.headers.get("x-retell-signature"), key):
        raise HTTPException(status_code=401, detail="Invalid or missing Retell signature")
    return raw


def require_admin(request: Request) -> None:
    """Protect admin endpoints with ADMIN_TOKEN (disabled when unset)."""
    token = settings.admin_token
    if not token:
        raise HTTPException(status_code=404, detail="Not found")
    supplied = request.headers.get("authorization", "")
    if not hmac.compare_digest(supplied, f"Bearer {token}"):
        raise HTTPException(status_code=401, detail="Unauthorized")
