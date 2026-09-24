import sys
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import services as bank
from app import create_app
from models import Account, Transaction, db, utcnow


@pytest.fixture()
def app():
    app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DORMANT_DAYS": 90,
    })
    with app.app_context():
        yield app


def make_dormant(account):
    account.last_activity_at = utcnow() - timedelta(days=91)
    db.session.commit()


def test_create_account(app):
    account = bank.create_account("  Jane   Doe ", "1,500.50")
    assert account.holder_name == "Jane Doe"
    assert len(account.account_number) == 10
    assert account.balance_cents == 150050


def test_create_account_rejects_bad_input(app):
    with pytest.raises(bank.BankError):
        bank.create_account("A")
    with pytest.raises(bank.BankError):
        bank.create_account("Jane", "-5")


def test_deposit_and_withdraw(app):
    a = bank.create_account("Jane Doe")
    bank.deposit(a.id, "1000")
    bank.withdraw(a.id, "250.25")
    assert a.balance_cents == 74975
    assert db.session.query(Transaction).filter_by(account_id=a.id).count() == 2


@pytest.mark.parametrize("bad", ["", "0", "-1", "abc", "1.234", "NaN", "Infinity", "99999999999"])
def test_invalid_amounts_rejected(app, bad):
    a = bank.create_account("Jane Doe")
    with pytest.raises(bank.BankError):
        bank.deposit(a.id, bad)
    assert a.balance_cents == 0


def test_cannot_overdraw(app):
    a = bank.create_account("Jane Doe", "100")
    with pytest.raises(bank.BankError, match="Insufficient"):
        bank.withdraw(a.id, "100.01")
    assert a.balance_cents == 10000


def test_transfer(app):
    a = bank.create_account("Jane Doe", "500")
    b = bank.create_account("John Roe")
    bank.transfer(a.id, b.id, "200")
    assert (a.balance_cents, b.balance_cents) == (30000, 20000)


def test_transfer_failures_change_nothing(app):
    a = bank.create_account("Jane Doe", "100")
    b = bank.create_account("John Roe")
    with pytest.raises(bank.BankError):
        bank.transfer(a.id, b.id, "500")
    with pytest.raises(bank.BankError):
        bank.transfer(a.id, a.id, "10")
    with pytest.raises(bank.BankError):
        bank.transfer(a.id, 9999, "10")
    assert (a.balance_cents, b.balance_cents) == (10000, 0)


def test_cannot_delete_active_account(app):
    a = bank.create_account("Jane Doe")
    with pytest.raises(bank.BankError, match="still active"):
        bank.delete_dormant_account(a.id)


def test_cannot_delete_dormant_account_with_balance(app):
    a = bank.create_account("Jane Doe", "50")
    make_dormant(a)
    with pytest.raises(bank.BankError, match="Balance"):
        bank.delete_dormant_account(a.id)


def test_delete_dormant_zero_balance_account(app):
    a = bank.create_account("Jane Doe")
    make_dormant(a)
    bank.delete_dormant_account(a.id)
    assert a.status == "CLOSED"
    with pytest.raises(bank.BankError):
        bank.deposit(a.id, "10")


def test_loan_disbursement(app):
    a = bank.create_account("Jane Doe")
    bank.create_loan_and_disburse(a.id)
    assert a.balance_cents == 1_000_000
    assert bank.active_loan(a.id).outstanding_cents == 1_000_000
    with pytest.raises(bank.BankError, match="already has an active loan"):
        bank.create_loan_and_disburse(a.id)


def test_loan_repayment_and_delete_blocked_until_paid(app):
    a = bank.create_account("Jane Doe")
    bank.create_loan_and_disburse(a.id)
    make_dormant(a)
    bank.repay_loan(a.id, "4000")
    with pytest.raises(bank.BankError):
        bank.delete_dormant_account(a.id)
    bank.repay_loan(a.id, "6000")
    assert bank.active_loan(a.id) is None
    make_dormant(a)  # the repayment counted as activity, so let it go dormant again
    bank.delete_dormant_account(a.id)
    assert a.status == "CLOSED"


def test_web_flow(app):
    client = app.test_client()
    response = client.post("/accounts", data={"holder_name": "Jane Doe", "opening_deposit": "100"})
    assert response.status_code == 302
    account = db.session.scalars(db.select(Account)).first()
    client.post(f"/accounts/{account.id}/deposit", data={"amount": "50"})
    page = client.get(f"/accounts/{account.id}")
    assert b"KES 150.00" in page.data
    assert client.get("/").status_code == 200
    assert client.get("/accounts/999").status_code == 404
