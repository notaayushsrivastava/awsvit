"""Background watcher that closes auctions whose deadline has passed and
broadcasts auction_ended. Complements lazy close in get_state.
"""

import threading
import time

from app.extensions import db, socketio
from app.services import auction_service as svc
from app.models import AuctionStatus

_started = False
_lock = threading.Lock()


def start_deadline_watcher(app):
    global _started
    with _lock:
        if _started:
            return
        _started = True
    # Reuse the existing app; calling create_app() again would re-run
    # socketio.init_app and replace the server, dropping all handlers.
    t = threading.Thread(target=_run, args=(app,), daemon=True, name="deadline-watcher")
    t.start()


def _run(app):
    with app.app_context():
        while True:
            try:
                _close_due()
            except Exception:
                db.session.rollback()
            time.sleep(1)


def _close_due():
    from sqlalchemy import select
    from app.models import Auction, utcnow

    with db.session.begin():
        due = db.session.scalars(
            select(Auction).where(
                Auction.status == AuctionStatus.LIVE, Auction.ends_at <= utcnow()
            )
        )
        ended = []
        for auction in due:
            svc._close_locked(auction)
            ended.append(auction)
    for auction in ended:
        socketio.emit(
            "auction_ended",
            {
                "auction_id": str(auction.id),
                "winner": auction.highest_bidder.display_name
                if auction.highest_bidder
                else None,
                "winning_bid": auction.current_bid,
                "leaderboard": svc.get_leaderboard(auction.id),
            },
            to=f"auction:{auction.id}",
        )
