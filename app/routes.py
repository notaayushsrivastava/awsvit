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


@bp.get("/health")
def health():
    db.session.execute(db.text("SELECT 1"))
    return {"status": "ok"}


@bp.get("/")
def index():
    return render_template("index.html")


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
    return render_template("auction/live.html", state=state)


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
