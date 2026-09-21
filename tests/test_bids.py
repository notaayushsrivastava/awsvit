from app.services import auction_service as svc
from app.extensions import db
from app.models import AuctionStatus, Bid
from app.services.auction_service import RejectedBid


def make_participants(auction_id, *names):
    ids = []
    for name in names:
        _, bidder = svc.join_auction(auction_id, name)
        ids.append(bidder.id)
    return ids


def test_create_and_get_state(app):
    with app.app_context():
        a = svc.create_auction("Mechanical Keyboard", "Premium wireless", 1000, 100, 600)
        state = svc.get_state(a.id)
        assert state["current_bid"] == 1000
        assert state["minimum_valid_bid"] == 1100
        assert state["status"] == "LIVE"
        assert state["sequence"] == 0


def test_join_is_idempotent(app):
    with app.app_context():
        a = svc.create_auction("Keyboard", "", 1000, 100)
        a1, b1 = svc.join_auction(a.id, "Alice")
        a2, b2 = svc.join_auction(a.id, "Alice")
        assert b1.id == b2.id
        assert svc.get_state(a.id)["participants"] == 1


def test_valid_bid_and_reject_low_equal(app):
    with app.app_context():
        a = svc.create_auction("Keyboard", "", 1000, 100)
        (alice,) = make_participants(a.id, "Alice")
        bid = svc.place_bid(a.id, alice, 1100)
        assert bid.accepted
        for amount in (1150, 1100, 1200 - 1):
            try:
                svc.place_bid(a.id, alice, amount)
                assert False, "should reject"
            except RejectedBid as e:
                assert e.reason == "BID_TOO_LOW"
                assert e.minimum_valid_bid == 1200
        assert svc.get_state(a.id)["current_bid"] == 1100


def test_non_participant_rejected(app):
    with app.app_context():
        a = svc.create_auction("Keyboard", "", 1000, 100)
        try:
            svc.place_bid(a.id, "00000000-0000-0000-0000-000000000000", 1100)
            assert False
        except RejectedBid as e:
            assert e.reason == "NOT_A_PARTICIPANT"


def test_idempotent_request_id(app):
    with app.app_context():
        a = svc.create_auction("Keyboard", "", 1000, 100)
        (alice,) = make_participants(a.id, "Alice")
        b1 = svc.place_bid(a.id, alice, 1100, request_id="req-1")
        b2 = svc.place_bid(a.id, alice, 1100, request_id="req-1")
        assert b1.id == b2.id
        accepted = db.session.query(Bid).filter_by(accepted=True).count()
        assert accepted == 1


def test_invalid_amount(app):
    with app.app_context():
        a = svc.create_auction("Keyboard", "", 1000, 100)
        (alice,) = make_participants(a.id, "Alice")
        for bad in (0, -5, None, 10.5, "1100"):
            try:
                svc.place_bid(a.id, alice, bad)
                assert False
            except RejectedBid as e:
                assert e.reason == "INVALID_AMOUNT"


def test_expired_auction_rejects_and_closes(app):
    with app.app_context():
        a = svc.create_auction("Keyboard", "", 1000, 100, duration_seconds=1)
        import time

        time.sleep(1.2)
        (alice,) = make_participants(a.id, "Alice")
        try:
            svc.place_bid(a.id, alice, 1100)
            assert False
        except RejectedBid as e:
            assert e.reason == "AUCTION_ENDED"
        assert svc.get_state(a.id)["status"] == "ENDED"
