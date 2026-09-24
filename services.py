"""Banking business logic, kept separate from the Flask routes so it is easy to test."""
import secrets
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from flask import current_app

from models import Account, Loan, Transaction, db, utcnow

LOAN_AMOUNT_CENTS = 10_000 * 100  # fixed KES 10,000 loan
MAX_AMOUNT_CENTS = 10_000_000 * 100  # KES 10,000,000 per operation


class BankError(Exception):
    """A user-facing validation or business-rule error."""


# ---------- helpers ----------

def format_kes(cents):
    return f"KES {Decimal(cents) / 100:,.2f}"


def parse_amount(raw, allow_blank_as_zero=False):
    """Convert user input like '1,250.50' to integer cents, or raise BankError."""
    text = (raw or "").strip().replace(",", "")
    if not text:
        if allow_blank_as_zero:
            return 0
        raise BankError("Enter an amount.")
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise BankError("Enter a valid amount.")
    if not value.is_finite():
        raise BankError("Enter a valid amount.")
    if value.as_tuple().exponent < -2:
        raise BankError("Amount can have at most 2 decimal places.")
    cents = int(value * 100)
    if cents <= 0:
        raise BankError("Amount must be greater than zero.")
    if cents > MAX_AMOUNT_CENTS:
        raise BankError("Amount exceeds the per-transaction limit of KES 10,000,000.")
    return cents


@contextmanager
def _atomic():
    """Commit on success, roll everything back on any error."""
    try:
        yield
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def _get_open_account(account_id):
    account = db.session.get(Account, account_id, with_for_update=True)
    if account is None or account.status != "OPEN":
        raise BankError("Account not found.")
    return account


def _record(account, type_, amount_cents, related=None, description=""):
    account.last_activity_at = utcnow()
    db.session.add(
        Transaction(
            account_id=account.id,
            type=type_,
            amount_cents=amount_cents,
            balance_after_cents=account.balance_cents,
            related_account_id=related.id if related else None,
            description=description,
        )
    )


def active_loan(account_id):
    return db.session.scalars(
        db.select(Loan).filter_by(account_id=account_id, status="ACTIVE")
    ).first()


# ---------- 1. create account ----------

def create_account(holder_name, opening_deposit_raw=""):
    name = " ".join((holder_name or "").split())
    if not 2 <= len(name) <= 100:
        raise BankError("Account holder name must be 2-100 characters.")
    opening = parse_amount(opening_deposit_raw, allow_blank_as_zero=True)

    with _atomic():
        while True:
            number = f"{secrets.randbelow(10**10):010d}"
            if not db.session.scalars(db.select(Account).filter_by(account_number=number)).first():
                break
        account = Account(account_number=number, holder_name=name, balance_cents=opening)
        db.session.add(account)
        db.session.flush()
        if opening:
            _record(account, "DEPOSIT", opening, description="Opening deposit")
    return account


# ---------- 2. deposit ----------

def deposit(account_id, raw_amount):
    amount = parse_amount(raw_amount)
    with _atomic():
        account = _get_open_account(account_id)
        account.balance_cents += amount
        _record(account, "DEPOSIT", amount, description="Cash deposit")
    return account


# ---------- 3. withdraw ----------

def withdraw(account_id, raw_amount):
    amount = parse_amount(raw_amount)
    with _atomic():
        account = _get_open_account(account_id)
        if amount > account.balance_cents:
            raise BankError("Insufficient funds.")
        account.balance_cents -= amount
        _record(account, "WITHDRAWAL", amount, description="Cash withdrawal")
    return account


# ---------- 4. transfer ----------

def transfer(from_id, to_id, raw_amount):
    amount = parse_amount(raw_amount)
    if to_id is None:
        raise BankError("Choose a destination account.")
    if from_id == to_id:
        raise BankError("Cannot transfer to the same account.")
    with _atomic():
        # Lock in a consistent order (by id) to avoid deadlocks on databases that support row locks.
        accounts = {i: _get_open_account(i) for i in sorted((from_id, to_id))}
        source, target = accounts[from_id], accounts[to_id]
        if amount > source.balance_cents:
            raise BankError("Insufficient funds.")
        source.balance_cents -= amount
        target.balance_cents += amount
        _record(source, "TRANSFER_OUT", amount, related=target, description=f"To {target.account_number}")
        _record(target, "TRANSFER_IN", amount, related=source, description=f"From {source.account_number}")
    return source, target


# ---------- 5. delete a dormant account ----------

def is_dormant(account):
    days = current_app.config["DORMANT_DAYS"]
    return utcnow() - account.last_activity_at >= timedelta(days=days)


def deletion_blockers(account):
    reasons = []
    if not is_dormant(account):
        reasons.append(
            f"Account is still active (it becomes dormant after {current_app.config['DORMANT_DAYS']} days without activity)."
        )
    if account.balance_cents != 0:
        reasons.append("Balance must be KES 0.00 (withdraw or transfer the funds first).")
    if active_loan(account.id):
        reasons.append("The outstanding loan must be repaid first.")
    return reasons


def delete_dormant_account(account_id):
    """Closes the account (soft delete) so the audit trail of transactions is preserved."""
    with _atomic():
        account = _get_open_account(account_id)
        blockers = deletion_blockers(account)
        if blockers:
            raise BankError(" ".join(blockers))
        account.status = "CLOSED"
        account.closed_at = utcnow()
    return account


# ---------- bonus: loan ----------

def create_loan_and_disburse(account_id):
    """Create a loan account for this account and disburse KES 10,000 into it."""
    with _atomic():
        account = _get_open_account(account_id)
        if active_loan(account.id):
            raise BankError("This account already has an active loan.")
        db.session.add(
            Loan(
                account_id=account.id,
                principal_cents=LOAN_AMOUNT_CENTS,
                outstanding_cents=LOAN_AMOUNT_CENTS,
            )
        )
        account.balance_cents += LOAN_AMOUNT_CENTS
        _record(account, "LOAN_DISBURSEMENT", LOAN_AMOUNT_CENTS, description="Loan disbursed")
    return account


def repay_loan(account_id, raw_amount):
    amount = parse_amount(raw_amount)
    with _atomic():
        account = _get_open_account(account_id)
        loan = active_loan(account.id)
        if not loan:
            raise BankError("No active loan on this account.")
        if amount > loan.outstanding_cents:
            raise BankError("Amount is more than the outstanding loan balance.")
        if amount > account.balance_cents:
            raise BankError("Insufficient funds.")
        account.balance_cents -= amount
        loan.outstanding_cents -= amount
        if loan.outstanding_cents == 0:
            loan.status = "PAID"
        _record(account, "LOAN_REPAYMENT", amount, description="Loan repayment")
    return account
