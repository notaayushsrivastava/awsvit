"""Socket.IO event handlers. Thin transport layer: validate, call
AuctionService, then broadcast — always after the transaction has committed.
"""

from flask import session
from flask_socketio import emit, join_room, leave_room

from app.extensions import db, socketio
from app.services import auction_service as svc
from app.models import AuctionParticipant, utcnow

ROOM_PREFIX = "auction:"


def _room(auction_id):
    return f"{ROOM_PREFIX}{auction_id}"


def _bidder_id():
    return session.get("bidder_id")


@socketio.on("join_auction")
def on_join_auction(data):
    auction_id = data.get("auction_id")
    try:
        state = svc.get_state(auction_id)
    except LookupError:
        emit("server_error", {"error": "AUCTION_NOT_FOUND"})
        return
    if not svc.is_participant(auction_id, _bidder_id()):
        emit("server_error", {"error": "NOT_A_PARTICIPANT"})
        return
    # presence is informational only
    db.session.execute(
        AuctionParticipant.__table__.update()
        .where(
            AuctionParticipant.auction_id == auction_id,
            AuctionParticipant.bidder_id == _bidder_id(),
        )
        .values(last_seen_at=utcnow())
    )
    db.session.commit()

    join_room(_room(auction_id))
    emit("auction_state", state)  # authoritative snapshot for this client
    emit(
        "participant_joined",
        {"bidder": _bidder_id()},
        to=_room(auction_id),
        include_self=False,
    )


@socketio.on("request_state")
def on_request_state(data):
    try:
        emit("auction_state", svc.get_state(data.get("auction_id")))
    except LookupError:
        emit("server_error", {"error": "AUCTION_NOT_FOUND"})


@socketio.on("leave_auction")
def on_leave_auction(data):
    leave_room(_room(data.get("auction_id")))


@socketio.on("place_bid")
def on_place_bid(data):
    auction_id = data.get("auction_id")
    amount = data.get("amount")
    request_id = data.get("request_id")

    try:
        bid = svc.place_bid(auction_id, _bidder_id(), amount, request_id)
    except svc.RejectedBid as e:
        payload = {
            "event": "bid_rejected",
            "request_id": request_id,
            "auction_id": str(auction_id),
            "accepted": False,
            "reason": e.reason,
            "current_bid": e.current_bid,
            "minimum_valid_bid": e.minimum_valid_bid,
        }
        emit("bid_rejected", payload)  # only to the submitting client
        return

    payload = {
        "event": "bid_accepted",
        "request_id": bid.request_id,
        "auction_id": str(auction_id),
        "bid_amount": bid.amount,
        "current_bid": bid.amount,
        "bidder": bid.bidder.display_name,
        "sequence": svc.get_state(auction_id, include_bids=False)["sequence"],
    }
    # Committed before this point — safe to broadcast.
    emit("bid_accepted", payload, to=_room(auction_id))
