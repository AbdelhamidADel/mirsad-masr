"""SQLAlchemy models for alert subscribers and rules."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class Subscriber(Base):
    __tablename__ = "subscribers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    lang: Mapped[str] = mapped_column(String(8), default="en")
    digest_on: Mapped[bool] = mapped_column(Boolean, default=False)
    confirm_token: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    confirm_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    manage_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    rules: Mapped[list[AlertRule]] = relationship(
        back_populates="subscriber", cascade="all, delete-orphan"
    )


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    subscriber_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subscribers.id", ondelete="CASCADE")
    )
    target_type: Mapped[str] = mapped_column(String(16))  # stock | gold | index | fx
    target_id: Mapped[str] = mapped_column(String(64))
    rule_kind: Mapped[str] = mapped_column(String(16))  # above | below | pct_move | points_move
    threshold: Mapped[float] = mapped_column(Float)
    cooldown_hours: Mapped[float] = mapped_column(Float, default=6.0)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    subscriber: Mapped[Subscriber] = relationship(back_populates="rules")
    events: Mapped[list[AlertEvent]] = relationship(
        back_populates="rule", cascade="all, delete-orphan"
    )


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    rule_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("alert_rules.id", ondelete="CASCADE")
    )
    fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    previous: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[str] = mapped_column(Text, default="")

    rule: Mapped[AlertRule] = relationship(back_populates="events")
