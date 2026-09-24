import os
import secrets

from flask import Flask, abort, flash, redirect, render_template, request, url_for
from flask_wtf.csrf import CSRFProtect

import services as bank
from models import Account, Transaction, db


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", "sqlite:///bank.db"),
        DORMANT_DAYS=int(os.environ.get("DORMANT_DAYS", "90")),
    )
    if config:
        app.config.update(config)

    db.init_app(app)
    CSRFProtect(app)
    with app.app_context():
        db.create_all()

    app.jinja_env.filters["kes"] = bank.format_kes
    app.jinja_env.globals["is_dormant"] = bank.is_dormant

    def handle(action, success_message, target, *args):
        try:
            action(*args)
        except bank.BankError as error:
            flash(str(error), "error")
            return redirect(request.referrer or url_for("index"))
        flash(success_message, "success")
        return redirect(target)

    def open_account_or_404(account_id):
        account = db.session.get(Account, account_id)
        if account is None or account.status != "OPEN":
            abort(404)
        return account

    @app.get("/")
    def index():
        accounts = db.session.scalars(
            db.select(Account).filter_by(status="OPEN").order_by(Account.id.desc())
        ).all()
        return render_template("index.html", accounts=accounts)

    @app.get("/accounts/<int:account_id>")
    def account_detail(account_id):
        account = open_account_or_404(account_id)
        transactions = db.session.scalars(
            db.select(Transaction)
            .filter_by(account_id=account.id)
            .order_by(Transaction.id.desc())
            .limit(50)
        ).all()
        others = db.session.scalars(
            db.select(Account).filter(Account.status == "OPEN", Account.id != account.id)
        ).all()
        return render_template(
            "account.html",
            account=account,
            transactions=transactions,
            other_accounts=others,
            loan=bank.active_loan(account.id),
            blockers=bank.deletion_blockers(account),
            loan_amount=bank.LOAN_AMOUNT_CENTS,
        )

    @app.post("/accounts")
    def create_account():
        try:
            account = bank.create_account(
                request.form.get("holder_name"), request.form.get("opening_deposit")
            )
        except bank.BankError as error:
            flash(str(error), "error")
            return redirect(url_for("index"))
        flash(f"Account {account.account_number} created.", "success")
        return redirect(url_for("account_detail", account_id=account.id))

    @app.post("/accounts/<int:account_id>/deposit")
    def deposit(account_id):
        return handle(bank.deposit, "Deposit successful.",
                      url_for("account_detail", account_id=account_id),
                      account_id, request.form.get("amount"))

    @app.post("/accounts/<int:account_id>/withdraw")
    def withdraw(account_id):
        return handle(bank.withdraw, "Withdrawal successful.",
                      url_for("account_detail", account_id=account_id),
                      account_id, request.form.get("amount"))

    @app.post("/accounts/<int:account_id>/transfer")
    def transfer(account_id):
        return handle(bank.transfer, "Transfer successful.",
                      url_for("account_detail", account_id=account_id),
                      account_id, request.form.get("to_account_id", type=int),
                      request.form.get("amount"))

    @app.post("/accounts/<int:account_id>/loan")
    def loan(account_id):
        return handle(bank.create_loan_and_disburse, "Loan account created and KES 10,000.00 disbursed.",
                      url_for("account_detail", account_id=account_id), account_id)

    @app.post("/accounts/<int:account_id>/loan/repay")
    def repay(account_id):
        return handle(bank.repay_loan, "Loan repayment successful.",
                      url_for("account_detail", account_id=account_id),
                      account_id, request.form.get("amount"))

    @app.post("/accounts/<int:account_id>/delete")
    def delete(account_id):
        return handle(bank.delete_dormant_account, "Dormant account deleted.",
                      url_for("index"), account_id)

    return app


if __name__ == "__main__":
    create_app().run(debug=os.environ.get("FLASK_DEBUG") == "1")
