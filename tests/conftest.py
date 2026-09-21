import os

os.environ.setdefault("TESTING", "1")

import pytest

from app import create_app
from app.extensions import db as _db
from app.models import Auction, AuctionEvent, AuctionParticipant, Bid, Bidder


@pytest.fixture(scope="session")
def app():
    app = create_app("testing")
    with app.app_context():
        _db.create_all()
    yield app


@pytest.fixture(autouse=True)
def clean_tables(app):
    with app.app_context():
        for table in (Bid, AuctionEvent, AuctionParticipant, Auction, Bidder):
            _db.session.query(table).delete()
        _db.session.commit()
    yield


@pytest.fixture
def ctx(app):
    """App context helper for tests that use the service layer."""
    return app
