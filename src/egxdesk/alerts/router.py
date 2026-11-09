"""HTTP routes for email alerts."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field

from egxdesk.alerts import service
from egxdesk.alerts.db import init_db, session_scope
from egxdesk.config import settings

router = APIRouter(prefix="/alerts", tags=["Alerts"])

_last_digest_date: str | None = None


class SubscribeBody(BaseModel):
    email: EmailStr
    lang: str = Field(default="en", examples=["en", "ar"])
    digest_on: bool = False


class RuleBody(BaseModel):
    token: str
    target_type: str = Field(examples=["stock", "gold", "index", "fx"])
    target_id: str = Field(examples=["COMI", "gold_21k", "CASE30", "usd_egp"])
    rule_kind: str = Field(examples=["above", "below", "pct_move", "points_move"])
    threshold: float
    cooldown_hours: float | None = None


class TokenBody(BaseModel):
    token: str


class DigestBody(BaseModel):
    token: str
    digest_on: bool


def _require_db() -> None:
    if not settings.alerts_enabled and not settings.database_url:
        # Allow SQLite memory when explicitly enabled in tests via database_url.
        pass
    if settings.alerts_enabled and not settings.database_url:
        raise HTTPException(status_code=503, detail="Alerts database is not configured.")
    init_db()


@router.post("/subscribe")
def subscribe(body: SubscribeBody) -> dict[str, Any]:
    _require_db()
    try:
        with session_scope() as session:
            row = service.subscribe(session, body.email, body.lang, body.digest_on)
            return {
                "ok": True,
                "email": row.email,
                "lang": row.lang,
                "digest_on": row.digest_on,
                "message": "Check your inbox for a confirmation link.",
            }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/confirm")
def confirm(token: Annotated[str, Query(min_length=8)]) -> dict[str, Any]:
    _require_db()
    with session_scope() as session:
        row = service.confirm(session, token)
        if row is None:
            raise HTTPException(status_code=400, detail="Invalid or expired confirmation token.")
        return {
            "ok": True,
            "email": row.email,
            "manage_token": row.manage_token,
            "manage_path": f"/board?alerts={row.manage_token}",
        }


@router.get("/manage")
def manage(token: Annotated[str, Query(min_length=8)]) -> dict[str, Any]:
    _require_db()
    with session_scope() as session:
        payload = service.manage_payload(session, token)
        if payload is None:
            raise HTTPException(status_code=404, detail="Subscriber not found.")
        return payload


@router.post("/rules")
def create_rule(body: RuleBody) -> dict[str, Any]:
    _require_db()
    try:
        with session_scope() as session:
            rule = service.add_rule(
                session,
                body.token,
                target_type=body.target_type,
                target_id=body.target_id,
                rule_kind=body.rule_kind,
                threshold=body.threshold,
                cooldown_hours=body.cooldown_hours,
            )
            return {
                "ok": True,
                "id": rule.id,
                "target_type": rule.target_type,
                "target_id": rule.target_id,
                "rule_kind": rule.rule_kind,
                "threshold": rule.threshold,
            }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/rules/{rule_id}")
def remove_rule(rule_id: str, token: Annotated[str, Query(min_length=8)]) -> dict[str, Any]:
    _require_db()
    with session_scope() as session:
        ok = service.delete_rule(session, token, rule_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Rule not found.")
        return {"ok": True}


@router.post("/digest")
def set_digest(body: DigestBody) -> dict[str, Any]:
    _require_db()
    with session_scope() as session:
        row = service.set_digest(session, body.token, body.digest_on)
        if row is None:
            raise HTTPException(status_code=404, detail="Subscriber not found.")
        return {"ok": True, "digest_on": row.digest_on}


@router.post("/unsubscribe")
@router.get("/unsubscribe")
def unsubscribe(token: Annotated[str, Query(min_length=8)]) -> dict[str, Any]:
    _require_db()
    with session_scope() as session:
        row = service.unsubscribe(session, token)
        if row is None:
            raise HTTPException(status_code=404, detail="Subscriber not found.")
        return {"ok": True, "email": row.email}


@router.post("/tick")
def tick(
    authorization: Annotated[str | None, Header()] = None,
    x_alerts_secret: Annotated[str | None, Header()] = None,
    force_digest: bool = False,
    force_alerts: bool = False,
) -> dict[str, Any]:
    """Evaluate alerts / digests. Protect with ALERTS_TICK_SECRET when set."""
    global _last_digest_date
    secret = settings.alerts_tick_secret.strip()
    if secret:
        provided = (x_alerts_secret or "").strip()
        if not provided and authorization and authorization.lower().startswith("bearer "):
            provided = authorization[7:].strip()
        if provided != secret:
            raise HTTPException(status_code=401, detail="Invalid tick secret.")
    if not settings.alerts_enabled and not force_alerts and not force_digest:
        return {"ok": True, "skipped": True, "reason": "alerts disabled"}
    _require_db()
    with session_scope() as session:
        result = service.run_tick(
            session,
            force_digest=force_digest,
            force_alerts=force_alerts,
            last_digest_date=_last_digest_date,
        )
    if result.get("digest_date"):
        _last_digest_date = str(result["digest_date"])
    return {"ok": True, **result}
