from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def utcnow():
    """Naive UTC timestamp (SQLite stores naive datetimes)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_number = db.Column(db.String(10), unique=True, nullable=False)
    holder_name = db.Column(db.String(100), nullable=False)
    # Money is stored as integer cents to avoid floating-point errors.
    balance_cents = db.Column(db.BigInteger, nullable=False, default=0)
    status = db.Column(db.String(10), nullable=False, default="OPEN")  # OPEN | CLOSED
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    last_activity_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    closed_at = db.Column(db.DateTime)


class Transaction(db.Model):
    """Append-only ledger entry. Types: DEPOSIT, WITHDRAWAL, TRANSFER_IN,
    TRANSFER_OUT, LOAN_DISBURSEMENT, LOAN_REPAYMENT."""

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False, index=True)
    type = db.Column(db.String(20), nullable=False)
    amount_cents = db.Column(db.BigInteger, nullable=False)
    balance_after_cents = db.Column(db.BigInteger, nullable=False)
    related_account_id = db.Column(db.Integer, db.ForeignKey("account.id"))
    description = db.Column(db.String(200), default="")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class Loan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False, index=True)
    principal_cents = db.Column(db.BigInteger, nullable=False)
    outstanding_cents = db.Column(db.BigInteger, nullable=False)
    status = db.Column(db.String(10), nullable=False, default="ACTIVE")  # ACTIVE | PAID
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
