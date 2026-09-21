from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from app.extensions import db
from app.models import Bidder
from app.services import auction_service as svc

bp = Blueprint("main", __name__)


def current_bidder():
    bidder_id = session.get("bidder_id")
    if bidder_id is None:
        return None
    return db.session.get(Bidder, bidder_id)


@bp.post("/auction/<auction_id>/bid")
def http_bid(auction_id):
    """HTTP fallback for bid submission — calls the exact same service as
    Socket.IO. Returns JSON either way."""
    bidder = current_bidder()
    data = request.get_json(silent=True) or request.form
    try:
        bid = svc.place_bid(
            auction_id, bidder.id if bidder else None,
            int(data.get("amount", 0)),
            data.get("request_id"),
        )
    except svc.RejectedBid as e:
        return jsonify({
            "accepted": False,
            "reason": e.reason,
            "current_bid": e.current_bid,
            "minimum_valid_bid": e.minimum_valid_bid,
        }), 409
    # committed — now broadcast to socket clients in the room
    from app.sockets import broadcast_bid

    broadcast_bid(auction_id, bid)
    return jsonify({"accepted": True, "amount": bid.amount})


@bp.get("/auction/<auction_id>/results")
def results(auction_id):
    try:
        state = svc.get_state(auction_id, include_bids=False)
        history = svc.get_bid_history(auction_id)
    except LookupError:
        return render_template("auction/missing.html", auction_id=auction_id), 404
    return render_template("auction/results.html", state=state, history=history)


def broadcast_bid(auction_id, bid):
    """Broadcast a committed bid. Call only after the transaction commits."""
    from app.sockets import broadcast_bid as _broadcast

    _broadcast(auction_id, bid)


@bp.get("/health")
def health():
    db.session.execute(db.text("SELECT 1"))
    return {"status": "ok"}


@bp.get("/")
def index():
    return render_template("index.html", auctions=svc.list_live_auctions())


@bp.route("/auction/new", methods=["GET", "POST"])
def new_auction():
    if request.method == "POST":
        auction = svc.create_auction(
            title=request.form["title"],
            description=request.form.get("description", ""),
            starting_bid=int(request.form.get("starting_bid", 1000)),
            minimum_increment=int(request.form.get("minimum_increment", 100)),
            duration_seconds=int(request.form.get("duration_seconds", 600)),
        )
        return redirect(url_for("main.auction_page", auction_id=auction.id))
    return render_template("auction/new.html")


@bp.get("/auction/<auction_id>")
def auction_page(auction_id):
    try:
        state = svc.get_state(auction_id)
    except LookupError:
        return render_template("auction/missing.html", auction_id=auction_id), 404
    bidder = current_bidder()
    joined = bidder is not None and svc.is_participant(auction_id, bidder.id)
    return render_template(
        "auction/live.html",
        state=state,
        joined=joined,
        me=bidder.display_name if bidder else None,
    )


@bp.post("/auction/<auction_id>/join")
def join(auction_id):
    display_name = request.form.get("display_name") or request.get_json(silent=True) or None
    if not display_name:
        display_name = f"Bidder {session.get('display_seq', 1)}"
        session["display_seq"] = session.get("display_seq", 1) + 1
    auction, bidder = svc.join_auction(auction_id, display_name)
    session["bidder_id"] = str(bidder.id)
    return redirect(url_for("main.auction_page", auction_id=auction.id))


@bp.get("/auction/<auction_id>/state")
def state(auction_id):
    try:
        return jsonify(svc.get_state(auction_id))
    except LookupError:
        return jsonify({"error": "auction not found"}), 404


@bp.get("/auction/<auction_id>/bids")
def bid_history(auction_id):
    return jsonify(svc.get_bid_history(auction_id))
