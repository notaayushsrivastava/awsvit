import enum
import uuid
from datetime import datetime, timezone

from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class AuctionStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


class Auction(db.Model):
    __tablename__ = "auctions"

    id = db.Column(db.Uuid, primary_key=True, default=uuid.uuid4)
    title = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, default="")
    starting_bid = db.Column(db.Integer, nullable=False)
    minimum_increment = db.Column(db.Integer, nullable=False)
    current_bid = db.Column(db.Integer, nullable=False)
    highest_bidder_id = db.Column(db.Uuid, db.ForeignKey("bidders.id"), nullable=True)
    status = db.Column(
        db.Enum(AuctionStatus, name="auction_status"),
        nullable=False,
        default=AuctionStatus.LIVE,
    )
    starts_at = db.Column(db.DateTime(timezone=True), nullable=True)
    ends_at = db.Column(db.DateTime(timezone=True), nullable=False)
    version = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    bids = db.relationship(
        "Bid", backref="auction", lazy="selectin", order_by="Bid.created_at.desc()"
    )
    highest_bidder = db.relationship("Bidder", foreign_keys=[highest_bidder_id])

    def to_dict(self, include_bids=False):
        data = {
            "id": str(self.id),
            "title": self.title,
            "description": self.description,
            "starting_bid": self.starting_bid,
            "minimum_increment": self.minimum_increment,
            "current_bid": self.current_bid,
            "minimum_valid_bid": self.current_bid + self.minimum_increment,
            "highest_bidder": self.highest_bidder.display_name
            if self.highest_bidder
            else None,
            "status": self.status.value,
            "ends_at": self.ends_at.isoformat(),
            "version": self.version,
        }
        if include_bids:
            data["bids"] = [
                {
                    "amount": b.amount,
                    "bidder": b.bidder.display_name,
                    "accepted": b.accepted,
                    "reason": b.rejection_reason,
                    "created_at": b.created_at.isoformat(),
                }
                for b in self.bids
            ]
        return data


class Bidder(db.Model):
    __tablename__ = "bidders"

    id = db.Column(db.Uuid, primary_key=True, default=uuid.uuid4)
    display_name = db.Column(db.Text, nullable=False, unique=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    def to_dict(self):
        return {"id": str(self.id), "display_name": self.display_name}


class AuctionParticipant(db.Model):
    __tablename__ = "auction_participants"

    id = db.Column(db.Uuid, primary_key=True, default=uuid.uuid4)
    auction_id = db.Column(
        db.Uuid, db.ForeignKey("auctions.id"), nullable=False, index=True
    )
    bidder_id = db.Column(
        db.Uuid, db.ForeignKey("bidders.id"), nullable=False, index=True
    )
    joined_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    last_seen_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (db.UniqueConstraint("auction_id", "bidder_id"),)


class Bid(db.Model):
    __tablename__ = "bids"

    id = db.Column(db.Uuid, primary_key=True, default=uuid.uuid4)
    auction_id = db.Column(
        db.Uuid, db.ForeignKey("auctions.id"), nullable=False, index=True
    )
    bidder_id = db.Column(db.Uuid, db.ForeignKey("bidders.id"), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    request_id = db.Column(db.Text, nullable=True, unique=True, index=True)
    accepted = db.Column(db.Boolean, nullable=False, default=False)
    rejection_reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    bidder = db.relationship("Bidder")

    def to_dict(self):
        return {
            "id": str(self.id),
            "amount": self.amount,
            "bidder": self.bidder.display_name,
            "accepted": self.accepted,
            "reason": self.rejection_reason,
            "request_id": self.request_id,
            "created_at": self.created_at.isoformat(),
        }


class AuctionEvent(db.Model):
    __tablename__ = "auction_events"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    auction_id = db.Column(
        db.Uuid, db.ForeignKey("auctions.id"), nullable=False, index=True
    )
    event_type = db.Column(db.Text, nullable=False)
    payload = db.Column(db.JSON, nullable=False, default=dict)
    sequence = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (db.UniqueConstraint("auction_id", "sequence"),)


class ChatMessage(db.Model):
    __tablename__ = "chat_messages"

    id = db.Column(db.Uuid, primary_key=True, default=uuid.uuid4)
    auction_id = db.Column(
        db.Uuid, db.ForeignKey("auctions.id"), nullable=False, index=True
    )
    bidder_id = db.Column(db.Uuid, db.ForeignKey("bidders.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    bidder = db.relationship("Bidder")

    def to_dict(self):
        return {
            "id": str(self.id),
            "bidder": self.bidder.display_name,
            "body": self.body,
            "created_at": self.created_at.isoformat(),
        }
