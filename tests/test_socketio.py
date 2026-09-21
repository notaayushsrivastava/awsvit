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


def test_leaderboard_lists_non_bidders_greyed_last(app):
    with app.app_context():
        a = svc.create_auction("Keyboard", "", 1000, 100)
        _, alice = svc.join_auction(a.id, "Alice")
        svc.join_auction(a.id, "Bob")  # joined but never bids
        svc.place_bid(a.id, alice.id, 1100)
        board = svc.get_leaderboard(a.id)
        assert [(r["bidder"], r["top_bid"]) for r in board] == [
            ("Alice", 1100),
            ("Bob", None),
        ]
        assert board[1]["rank"] == 2
        assert board[1]["bids"] == 0
        assert board[0]["rank"] == 1


def test_leaderboard_ranks_by_highest_accepted_bid(app):
    with app.app_context():
        a = svc.create_auction("Keyboard", "", 1000, 100)
        _, alice = svc.join_auction(a.id, "Alice")
        _, bob = svc.join_auction(a.id, "Bob")
        svc.place_bid(a.id, alice.id, 1100)
        svc.place_bid(a.id, bob.id, 1200)
        svc.place_bid(a.id, alice.id, 1300)
        board = svc.get_leaderboard(a.id)
        assert [r["bidder"] for r in board] == ["Alice", "Bob"]
        assert board[0]["top_bid"] == 1300
        assert board[0]["bids"] == 2
        assert board[0]["rank"] == 1


def test_leaderboard_excludes_rejected_bids(app):
    with app.app_context():
        a = svc.create_auction("Keyboard", "", 1000, 100)
        _, alice = svc.join_auction(a.id, "Alice")
        _, bob = svc.join_auction(a.id, "Bob")
        svc.place_bid(a.id, alice.id, 1100)
        try:
            svc.place_bid(a.id, bob.id, 1150)  # too low
        except svc.RejectedBid:
            pass
        board = svc.get_leaderboard(a.id)
        # both joined; Bob rejected bid still shows him as waiting
        assert [(r["bidder"], r["top_bid"]) for r in board] == [
            ("Alice", 1100),
            ("Bob", None),
        ]


def test_live_auctions_lists_only_joinable(app):
    with app.app_context():
        from app.extensions import db as _db
        from app.models import AuctionStatus

        open_a = svc.create_auction("Open", "", 1000, 100, duration_seconds=600)
        closed = svc.create_auction("Closed", "", 1000, 100, duration_seconds=600)
        closed.status = AuctionStatus.ENDED
        _db.session.commit()
        rows = svc.list_live_auctions()
        ids = [r["id"] for r in rows]
        assert str(open_a.id) in ids
        assert str(closed.id) not in ids
        assert rows[0]["participants"] == 0


def test_chat_persists_and_validates(app):
    with app.app_context():
        a = svc.create_auction("Keyboard", "", 1000, 100)
        _, alice = svc.join_auction(a.id, "Alice")
        svc.post_chat(a.id, alice.id, "  going once  ")
        msgs = svc.get_chat(a.id)
        assert len(msgs) == 1
        assert msgs[0]["body"] == "going once"
        assert msgs[0]["bidder"] == "Alice"

        for bad in ("", "   ", "x" * 501):
            try:
                svc.post_chat(a.id, alice.id, bad)
                assert False, "should reject"
            except ValueError:
                pass
        # strangers cannot chat
        try:
            svc.post_chat(a.id, "00000000-0000-0000-0000-000000000001", "hi")
            assert False, "should reject"
        except PermissionError:
            pass


def test_state_snapshot_includes_leaderboard_and_chat(app):
    with app.app_context():
        a, _, _ = make_client(app, "Alice")
        _, alice = svc.join_auction(a.id, "Alice")
        svc.place_bid(a.id, alice.id, 1100)
        svc.post_chat(a.id, alice.id, "hello")
        state = svc.get_state(a.id)
        assert state["leaderboard"][0]["bidder"] == "Alice"
        assert state["chat"][0]["body"] == "hello"


def test_chat_broadcasts_to_room(app):
    with app.app_context():
        a, _, ws = make_client(app, "Alice")
        ws.emit("join_auction", {"auction_id": str(a.id)})
        _recv(ws, "auction_state")
        _, _, ws2 = make_client(app, "Bob", auction_id=a.id)
        ws2.emit("join_auction", {"auction_id": str(a.id)})
        _recv(ws2, "auction_state")

        ws2.emit("send_chat", {"auction_id": str(a.id), "body": "anyone bidding?"})
        assert _recv(ws2, "chat_message")[0]["args"][0]["message"]["body"] == "anyone bidding?"
        # Alice is in the same room and sees it too
        assert _recv(ws, "chat_message")[0]["args"][0]["message"]["bidder"] == "Bob"


def test_chat_from_non_participant_is_rejected(app):
    with app.app_context():
        a, _, ws = make_client(app, "Alice")
        ws.emit("join_auction", {"auction_id": str(a.id)})
        _recv(ws, "auction_state")
        other = svc.create_auction("Other", "", 1000, 100)
        ws.emit("send_chat", {"auction_id": str(other.id), "body": "hello?"})
        errors = _recv(ws, "server_error")
        assert errors and errors[0]["args"][0]["error"] == "CHAT_REJECTED"
        assert svc.get_chat(other.id) == []


def test_bid_broadcasts_leaderboard(app):
    with app.app_context():
        a, _, ws = make_client(app, "Alice")
        ws.emit("join_auction", {"auction_id": str(a.id)})
        _recv(ws, "auction_state")
        ws.emit("place_bid", {"auction_id": str(a.id), "amount": 1100})
        boards = _recv(ws, "leaderboard_updated")
        assert boards and boards[0]["args"][0]["leaderboard"][0]["bidder"] == "Alice"


def test_http_bid_fallback_uses_same_service_and_broadcasts(app):
    """The HTTP fallback must commit through the same service and broadcast
    the accepted bid to socket clients in the room."""
    with app.app_context():
        a, _, ws = make_client(app, "Alice")
        ws.emit("join_auction", {"auction_id": str(a.id)})
        _recv(ws, "auction_state")

        http = app.test_client()
        http.post(f"/auction/{a.id}/join", data={"display_name": "Carol"})
        res = http.post(f"/auction/{a.id}/bid", json={"amount": 1100})
        assert res.status_code == 200
        assert res.get_json()["accepted"] is True

        # socket watcher received both broadcasts (note: get_received drains)
        events = ws.get_received()
        names = [e["name"] for e in events]
        assert "bid_accepted" in names
        assert "leaderboard_updated" in names
        accepted = next(e for e in events if e["name"] == "bid_accepted")
        assert accepted["args"][0]["bid_amount"] == 1100
        board = next(e for e in events if e["name"] == "leaderboard_updated")
        assert board["args"][0]["leaderboard"][0]["bidder"] == "Carol"
        assert svc.get_state(a.id)["current_bid"] == 1100

        # a too-low HTTP bid is rejected with the reason and current state
        low = http.post(f"/auction/{a.id}/bid", json={"amount": 1150})
        assert low.status_code == 409
        body = low.get_json()
        assert body["reason"] == "BID_TOO_LOW"
        assert body["current_bid"] == 1100
        assert body["minimum_valid_bid"] == 1200


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


def test_spectator_can_watch_but_not_bid_or_chat(app):
    with app.app_context():
        a, _, ws = make_client(app, "Alice")
        ws.emit("join_auction", {"auction_id": str(a.id)})
        _recv(ws, "auction_state")

        # a visitor who never joined: can watch other auctions...
        other = svc.create_auction("Other", "", 1000, 100)
        ws.emit("join_auction", {"auction_id": str(other.id)})
        assert len(_recv(ws, "auction_state")) == 1
        assert _recv(ws, "server_error") == []

        # ...but cannot bid or chat there
        ws.emit("place_bid", {"auction_id": str(other.id), "amount": 1100})
        assert _recv(ws, "bid_rejected")[0]["args"][0]["reason"] == "NOT_A_PARTICIPANT"
        ws.emit("send_chat", {"auction_id": str(other.id), "body": "hi"})
        assert _recv(ws, "server_error")[0]["args"][0]["error"] == "CHAT_REJECTED"


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
