"""Auction domain service (part 1): reads and state helpers. All auction
logic lives here; HTTP and Socket.IO handlers call this service.

Concurrency discipline: every mutation re-validates against authoritative
state while holding a row-level lock (SELECT ... FOR UPDATE) on the auction
row, and nothing is broadcast until the transaction commits.
"""

import uuid
from datetime import timedelta

from sqlalchemy import select, func

from app.extensions import db
from app.models import (
    Auction,
    AuctionEvent,
    AuctionParticipant,
    AuctionStatus,
    Bid,
    Bidder,
    utcnow,
)


class RejectedBid(Exception):
    def __init__(self, reason, current_bid=None, minimum_valid_bid=None):
        super().__init__(reason)
        self.reason = reason
        self.current_bid = current_bid
        self.minimum_valid_bid = minimum_valid_bid


def create_auction(
    title, description="", starting_bid=1000, minimum_increment=100, duration_seconds=600
):
    auction = Auction(
        title=title,
        description=description,
        starting_bid=starting_bid,
        minimum_increment=minimum_increment,
        current_bid=starting_bid,
        status=AuctionStatus.LIVE,
        ends_at=utcnow() + timedelta(seconds=duration_seconds),
    )
    db.session.add(auction)
    db.session.commit()
    return auction


def join_auction(auction_id, display_name):
    """Get-or-create a bidder and add them as a participant."""
    auction = db.session.get(Auction, auction_id)
    if auction is None:
        raise LookupError("auction not found")
    bidder = db.session.scalar(
        select(Bidder).where(Bidder.display_name == display_name)
    )
    if bidder is None:
        bidder = Bidder(display_name=display_name)
        db.session.add(bidder)
        db.session.flush()
    participant = db.session.scalar(
        select(AuctionParticipant).where(
            AuctionParticipant.auction_id == auction_id,
            AuctionParticipant.bidder_id == bidder.id,
        )
    )
    if participant is None:
        db.session.add(AuctionParticipant(auction_id=auction_id, bidder_id=bidder.id))
    db.session.commit()
    return auction, bidder


def is_participant(auction_id, bidder_id):
    if bidder_id is None:
        return False
    return (
        db.session.scalar(
            select(func.count()).select_from(AuctionParticipant).where(
                AuctionParticipant.auction_id == auction_id,
                AuctionParticipant.bidder_id == bidder_id,
            )
        )
        > 0
    )


def get_state(auction_id, include_bids=True):
    """Authoritative state snapshot. Also lazily closes expired auctions."""
    db.session.expire_all()  # never serve identity-map-cached auction state
    auction = _maybe_close(db.session.get(Auction, auction_id))
    if auction is None:
        raise LookupError("auction not found")
    seq = (
        db.session.scalar(
            select(func.max(AuctionEvent.sequence)).where(
                AuctionEvent.auction_id == auction_id
            )
        )
        or 0
    )
    data = auction.to_dict(include_bids=include_bids)
    data["sequence"] = seq
    data["participants"] = (
        db.session.scalar(
            select(func.count()).select_from(AuctionParticipant).where(
                AuctionParticipant.auction_id == auction_id
            )
        )
        or 0
    )
    return data


def get_bid_history(auction_id):
    return [
        b.to_dict()
        for b in db.session.scalars(
            select(Bid)
            .where(Bid.auction_id == auction_id)
            .order_by(Bid.created_at.desc())
        )
    ]


def place_bid(auction_id, bidder_id, amount, request_id=None):
    """Transactional bid. Returns the accepted Bid. Raises RejectedBid.

    Single transaction:
      1. lock the auction row (SELECT ... FOR UPDATE)
      2. re-validate against authoritative state
         (status, deadline, amount, membership, idempotency)
      3. insert the accepted Bid, update the auction, append an event
      4. commit — the caller may broadcast only after this returns
    """
    if not isinstance(amount, int) or amount <= 0:
        raise RejectedBid("INVALID_AMOUNT")

    # Clear any ambient read-only transaction (e.g. from expired-attribute
    # refreshes) so the explicit transaction below can open cleanly.
    db.session.rollback()

    # Idempotency: a retried request returns its original result.
    if request_id:
        existing = db.session.scalar(select(Bid).where(Bid.request_id == request_id))
        db.session.commit()  # close the implicit transaction before begin()
        if existing is not None:
            if existing.accepted:
                return existing
            raise RejectedBid(existing.rejection_reason)

    try:
        with db.session.begin():
            auction = db.session.execute(
                select(Auction).where(Auction.id == auction_id).with_for_update()
            ).scalar_one_or_none()
            if auction is None:
                raise RejectedBid("AUCTION_NOT_FOUND")
            if not is_participant(auction_id, bidder_id):
                raise RejectedBid("NOT_A_PARTICIPANT")

            now = utcnow()
            if auction.status != AuctionStatus.LIVE:
                raise RejectedBid("AUCTION_NOT_LIVE", auction.current_bid)
            if now >= auction.ends_at:
                _close_locked(auction)
                raise RejectedBid("AUCTION_ENDED", auction.current_bid)

            minimum_valid = auction.current_bid + auction.minimum_increment
            if amount < minimum_valid:
                raise RejectedBid("BID_TOO_LOW", auction.current_bid, minimum_valid)

            bid = Bid(
                auction_id=auction_id,
                bidder_id=bidder_id,
                amount=amount,
                request_id=request_id or f"bid_{uuid.uuid4()}",
                accepted=True,
            )
            db.session.add(bid)
            auction.current_bid = amount
            auction.highest_bidder_id = bidder_id
            auction.version += 1
            _record_event(
                auction_id,
                "bid_accepted",
                {
                    "bid_amount": amount,
                    "current_bid": amount,
                    "bidder_id": str(bidder_id),
                    "request_id": bid.request_id,
                },
            )
        # Transaction committed here.
        return bid
    except RejectedBid:
        _record_rejection(auction_id, bidder_id, amount, request_id)
        raise


def close_auction(auction_id):
    """Authoritative close. Returns (auction, closed_now)."""
    db.session.rollback()  # clear ambient read-only transaction
    with db.session.begin():
        auction = db.session.execute(
            select(Auction).where(Auction.id == auction_id).with_for_update()
        ).scalar_one_or_none()
        if auction is None:
            raise LookupError("auction not found")
        closed_now = False
        if auction.status == AuctionStatus.LIVE and utcnow() >= auction.ends_at:
            _close_locked(auction)
            closed_now = True
    return auction, closed_now


# ---------------------------------------------------------------- internals


def _close_locked(auction):
    """Mark an ENDED auction while the row lock is held. Caller commits."""
    auction.status = AuctionStatus.ENDED
    auction.version += 1
    _record_event(
        auction.id,
        "auction_ended",
        {
            "winner": auction.highest_bidder.display_name
            if auction.highest_bidder
            else None,
            "winning_bid": auction.current_bid,
        },
    )


def _record_event(auction_id, event_type, payload):
    seq = (
        db.session.scalar(
            select(func.max(AuctionEvent.sequence)).where(
                AuctionEvent.auction_id == auction_id
            )
        )
        or 0
    ) + 1
    # Safe: the caller holds the auction row lock, so per-auction sequence
    # allocation is serialized.
    db.session.add(
        AuctionEvent(
            auction_id=auction_id,
            event_type=event_type,
            payload=payload,
            sequence=seq,
        )
    )


def _record_rejection(auction_id, bidder_id, amount, request_id):
    # Best-effort audit trail for rejected bids; failures are swallowed.
    try:
        with db.session.begin():
            db.session.add(
                Bid(
                    auction_id=auction_id,
                    bidder_id=bidder_id or _placeholder_bidder(),
                    amount=amount or 0,
                    request_id=request_id,
                    accepted=False,
                    rejection_reason="BID_REJECTED",
                )
            )
    except Exception:
        db.session.rollback()


def _placeholder_bidder():
    bidder = db.session.scalar(select(Bidder).where(Bidder.display_name == "unknown"))
    if bidder is None:
        bidder = Bidder(display_name="unknown")
        db.session.add(bidder)
        db.session.flush()
    return bidder.id


def _maybe_close(auction):
    if auction is None:
        return None
    if auction.status == AuctionStatus.LIVE and utcnow() >= auction.ends_at:
        closed, _ = close_auction(auction.id)
        return closed
    return auction

