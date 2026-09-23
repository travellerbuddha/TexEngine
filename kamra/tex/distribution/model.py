"""Provider-neutral distribution messages (G-69). Pure — no frappe import.

Money is Decimal; dates are ``date``. A provider adapter translates these to and from
its own wire format; TEX never stores a provider's shape as the truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class AriDay:
	"""What a channel may sell of one mapped room/rate on one day."""
	day: date
	available: int
	closed: bool = False                  # stop sell (any reason: closed inventory, stop-sell restriction)
	cta: bool = False
	ctd: bool = False
	min_los: int | None = None
	max_los: int | None = None
	rates: tuple[tuple[int, Decimal], ...] = ()   # (adults, price of one night) — sorted by adults
	currency: str | None = None

	def fingerprint(self) -> str:
		"""What a push must bring to the channel; equal fingerprints need no push."""
		rates = ",".join(f"{a}:{p.quantize(Decimal('0.01'))}" for a, p in self.rates)
		return (f"{self.available}|{int(self.closed)}|{int(self.cta)}|{int(self.ctd)}|{self.min_los or ''}|"
		        f"{self.max_los or ''}|{self.currency or ''}|{rates}")

	def to_dict(self) -> dict:
		return {"date": self.day.isoformat(), "available": self.available, "closed": self.closed, "cta": self.cta,
		        "ctd": self.ctd, "min_los": self.min_los, "max_los": self.max_los, "currency": self.currency,
		        "rates": [{"adults": a, "price": str(p)} for a, p in self.rates]}


@dataclass(frozen=True, slots=True)
class AriRun:
	"""Consecutive days with identical values: one provider call instead of one per day."""
	room_code: str
	rate_code: str
	date_from: date
	date_to: date                         # inclusive
	values: AriDay                        # its ``day`` is the run's first day

	def to_dict(self) -> dict:
		return {"room_code": self.room_code, "rate_code": self.rate_code, "date_from": self.date_from.isoformat(),
		        "date_to": self.date_to.isoformat(), **{k: v for k, v in self.values.to_dict().items() if k != "date"}}


@dataclass(frozen=True, slots=True)
class PushResult:
	ok: bool
	accepted: int = 0                     # runs the channel accepted
	message: str = ""
	provider_ref: str | None = None
	retryable: bool = True                # a rejected payload (4xx) is not retried as is


@dataclass(frozen=True, slots=True)
class ChannelGuest:
	first_name: str
	last_name: str
	email: str | None = None
	phone: str | None = None
	country: str | None = None


@dataclass(frozen=True, slots=True)
class ChannelRoom:
	"""One room of a channel booking, as the channel sold it."""
	room_code: str
	rate_code: str
	check_in: date
	check_out: date
	adults: int
	children_ages: tuple[int, ...] = ()
	total: Decimal = Decimal(0)           # what the channel sold the room for (its price, not TEX's)
	currency: str = ""
	line_ref: str = ""                    # the channel's id of this room line, stable across modifications


@dataclass(frozen=True, slots=True)
class ChannelReservation:
	"""A booking, modification or cancellation received from a channel (full state)."""
	provider_ref: str                     # the channel's booking id
	status: str                           # "new" | "modified" | "cancelled"
	rooms: tuple[ChannelRoom, ...] = ()
	guest: ChannelGuest | None = None
	channel_name: str = ""                # e.g. the OTA behind the channel manager
	notes: str = ""
	version: str = ""                     # the channel's revision marker, when it sends one

	STATUSES = ("new", "modified", "cancelled")


@dataclass(frozen=True, slots=True)
class Mismatch:
	"""A difference found by reconciliation."""
	kind: str                             # ari_drift | missing_in_tex | missing_in_channel | total_differs | status_differs
	key: str
	detail: dict = field(default_factory=dict)
