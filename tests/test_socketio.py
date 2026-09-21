from app.extensions import socketio
from app.services import auction_service as svc


def make_client(app, name, auction_id=None):
    """A logged-in participant: HTTP join (sets session cookie) + socket client."""
    http = app.test_client()
    a = svc.create_auction(f"Auction for {name}", "", 1000, 100)
    target = auction_id or a.id
    http.post(f"/auction/{target}/join", data={"display_name": name})
    ws = socketio.test_client(app, flask_test_client=http)
    return a, http, ws


def _recv(ws, name):
    return [r for r in ws.get_received() if r["name"] == name]


def test_join_receives_state_and_bids_broadcast(app):
    with app.app_context():
        a, _, ws = make_client(app, "Alice")
        ws.emit("join_auction", {"auction_id": str(a.id)})
        state = _recv(ws, "auction_state")
        assert len(state) == 1
        assert state[0]["args"][0]["current_bid"] == 1000

        _, _, ws2 = make_client(app, "Bob", auction_id=a.id)
        ws2.emit("join_auction", {"auction_id": str(a.id)})
        _recv(ws2, "auction_state")
        ws2.emit("place_bid", {"auction_id": str(a.id), "amount": 1100})
        assert len(_recv(ws2, "bid_accepted")) == 1
        # Alice (same room) also receives the broadcast
        assert len(_recv(ws, "bid_accepted")) == 1


def test_bid_rejected_returns_reason(app):
    with app.app_context():
        a, _, ws = make_client(app, "Alice")
        ws.emit("join_auction", {"auction_id": str(a.id)})
        _recv(ws, "auction_state")
        ws.emit("place_bid", {"auction_id": str(a.id), "amount": 1050})
        rejected = _recv(ws, "bid_rejected")
        assert len(rejected) == 1
        payload = rejected[0]["args"][0]
        assert payload["reason"] == "BID_TOO_LOW"
        assert payload["current_bid"] == 1000
        assert payload["minimum_valid_bid"] == 1100


def test_non_participant_cannot_join_room(app):
    with app.app_context():
        a, _, ws = make_client(app, "Alice")
        ws.emit("join_auction", {"auction_id": str(a.id)})
        _recv(ws, "auction_state")

        other = svc.create_auction("Other", "", 1000, 100)
        ws.emit("join_auction", {"auction_id": str(other.id)})
        errors = _recv(ws, "server_error")
        assert len(errors) == 1
        assert errors[0]["args"][0]["error"] == "NOT_A_PARTICIPANT"


def test_rooms_are_isolated(app):
    with app.app_context():
        a1, _, ws1 = make_client(app, "Alice")
        ws1.emit("join_auction", {"auction_id": str(a1.id)})
        _recv(ws1, "auction_state")
        a2, _, ws2 = make_client(app, "Bob")
        ws2.emit("join_auction", {"auction_id": str(a2.id)})
        _recv(ws2, "auction_state")

        ws2.emit("place_bid", {"auction_id": str(a2.id), "amount": 1100})
        assert _recv(ws2, "bid_accepted")
        assert _recv(ws1, "bid_accepted") == []


def test_reconnect_recovers_authoritative_state(app):
    with app.app_context():
        a, _, ws = make_client(app, "Alice")
        ws.emit("join_auction", {"auction_id": str(a.id)})
        _recv(ws, "auction_state")
        ws.emit("place_bid", {"auction_id": str(a.id), "amount": 1100})
        _recv(ws, "bid_accepted")

        # reconnect flow: rejoin the room, receive the authoritative snapshot
        ws.emit("join_auction", {"auction_id": str(a.id)})
        state = _recv(ws, "auction_state")
        assert state[0]["args"][0]["current_bid"] == 1100
        assert state[0]["args"][0]["sequence"] == 1


def test_disconnect_does_not_lose_committed_bid(app):
    with app.app_context():
        a, _, ws = make_client(app, "Alice")
        ws.emit("join_auction", {"auction_id": str(a.id)})
        _recv(ws, "auction_state")
        ws.emit("place_bid", {"auction_id": str(a.id), "amount": 1100})
        _recv(ws, "bid_accepted")
        socketio.sleep(0.05)
        ws.disconnect()  # the committed bid survives the disconnect
        state = svc.get_state(a.id)
        assert state["current_bid"] == 1100
        assert state["highest_bidder"] == "Alice"
