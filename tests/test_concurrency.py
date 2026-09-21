import threading

import pytest

from app.extensions import db
from app.models import Bid
from app.services import auction_service as svc
from app.services.auction_service import RejectedBid


def _make_auction_with_bidders(n_bidders, starting=1000, increment=100, duration=600):
    a = svc.create_auction("Race", "", starting, increment, duration)
    ids = []
    for i in range(n_bidders):
        _, bidder = svc.join_auction(a.id, f"Bidder {i}")
        ids.append(bidder.id)
    return a, ids


def _concurrent_bids(app, auction_id, jobs):
    """jobs: list of (bidder_id, amount, request_id). Run all simultaneously."""
    barrier = threading.Barrier(len(jobs))
    results = [None] * len(jobs)

    def worker(i, bidder_id, amount, request_id):
        with app.app_context():
            barrier.wait()
            try:
                bid = svc.place_bid(auction_id, bidder_id, amount, request_id)
                # extract plain values before the app context closes
                results[i] = ("ok", bid.amount, str(bid.id))
            except RejectedBid as e:
                results[i] = ("rejected", e.reason)
            except Exception as e:  # noqa: BLE001
                results[i] = ("error", str(e))

    threads = [
        threading.Thread(target=worker, args=(i, *job))
        for i, job in enumerate(jobs)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


@pytest.mark.parametrize("n", [10, 50])
def test_concurrent_increasing_bids(app, n):
    with app.app_context():
        a, ids = _make_auction_with_bidders(n)
        # everyone bids a distinct amount; the highest must win
        jobs = [(ids[i], 2000 + (i + 1) * 100, f"req-{i}") for i in range(n)]
        results = _concurrent_bids(app, a.id, jobs)
        accepted = [r[1] for r in results if r[0] == "ok"]
        state = svc.get_state(a.id)
        assert state["current_bid"] == max(accepted)
        with app.app_context():
            count = db.session.query(Bid).filter_by(accepted=True).count()
        assert count == len(accepted)


def test_concurrent_bids_final_equals_max_accepted(app):
    with app.app_context():
        a, ids = _make_auction_with_bidders(20)
        amounts = [1100, 1200, 1300, 1400, 1500, 1600, 1700, 1800, 1900, 2000] * 2
        jobs = [(ids[i], amounts[i], f"req-{i}") for i in range(20)]
        _concurrent_bids(app, a.id, jobs)
        state = svc.get_state(a.id)
        max_accepted = (
            db.session.query(db.func.max(Bid.amount))
            .filter_by(accepted=True, auction_id=a.id)
            .scalar()
        )
        assert state["current_bid"] == max_accepted
        # no stale lower bid overwrote the highest
        highest_bid = (
            db.session.query(Bid).filter_by(amount=max_accepted, accepted=True).first()
        )
        assert highest_bid is not None
        assert str(state["id"]) == str(a.id)


def test_simultaneous_equal_bids_exactly_one_wins(app):
    with app.app_context():
        a, ids = _make_auction_with_bidders(10)
        jobs = [(ids[i], 1100, "same-amount") for i in range(10)]
        # distinct request ids, same amount: only the first commit wins
        jobs = [(ids[i], 1100, f"req-{i}") for i in range(10)]
        results = _concurrent_bids(app, a.id, jobs)
        accepted = [r for r in results if r[0] == "ok"]
        assert len(accepted) == 1
        assert svc.get_state(a.id)["current_bid"] == 1100


def test_duplicate_request_ids_never_double_bid(app):
    with app.app_context():
        a, ids = _make_auction_with_bidders(10)
        # everyone reuses the SAME request id with the same amount:
        # exactly one accepted bid may exist.
        jobs = [(ids[i], 1100, "shared-req") for i in range(10)]
        results = _concurrent_bids(app, a.id, jobs)
        with app.app_context():
            n = db.session.query(Bid).filter_by(request_id="shared-req", accepted=True).count()
        assert n <= 1
        assert svc.get_state(a.id)["current_bid"] == 1100


def test_bid_vs_close_race(app):
    with app.app_context():
        a, ids = _make_auction_with_bidders(5, duration=2)
        jobs = [(ids[i], 1100 + i * 100, f"req-{i}") for i in range(5)]
        import time

        time.sleep(2.1)  # deadline passes; bids must all fail
        results = _concurrent_bids(app, a.id, jobs)
        assert all(r[0] == "rejected" and r[1] == "AUCTION_ENDED" for r in results)
        state = svc.get_state(a.id)
        assert state["status"] == "ENDED"
        assert state["current_bid"] == 1000  # starting bid, nothing accepted
