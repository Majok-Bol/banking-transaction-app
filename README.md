# Simple Banking Transaction Interface

A small Flask web app that simulates core banking operations in Kenyan Shillings (KES).

## Features

| # | Function | Where |
|---|----------|-------|
| 1 | Create a bank account (optional opening deposit) | Home page |
| 2 | Deposit funds | Account page |
| 3 | Withdraw funds (overdrafts rejected) | Account page |
| 4 | Transfer funds between accounts (atomic) | Account page |
| 5 | Delete a dormant account | Account page |
| Bonus | Create a loan account and disburse KES 10,000 into the account | Account page |

Every operation is written to a per-account transaction ledger, shown on the account page.

## Run it

```bash
git clone https://github.com/<your-username>/banking-transaction-app.git
cd banking-transaction-app
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000.

Run the tests: `python -m pytest -q`

### Configuration (environment variables)

| Variable | Default | Purpose |
|----------|---------|---------|
| `SECRET_KEY` | random per start | Session/CSRF signing key. Set a fixed value in any real deployment. |
| `DATABASE_URL` | `sqlite:///bank.db` | Any SQLAlchemy URL (e.g. PostgreSQL). |
| `DORMANT_DAYS` | `90` | Days without activity before an account counts as dormant. |

To try the delete feature without waiting 90 days: `DORMANT_DAYS=0 python app.py`.

## Design decisions

- **Money is stored as integer cents**, never floats. Input allows at most 2 decimal places.
- **Dormant** means no transaction for `DORMANT_DAYS` days. A dormant account can be deleted only if its balance is KES 0.00 and it has no outstanding loan, so no customer funds or debts disappear.
- **Delete is a soft delete**: the account is marked `CLOSED` and hidden, but its ledger is kept for auditing.
- **Loan**: one active loan per account. "Create loan" opens a loan record linked to the account and credits KES 10,000 to it as a `LOAN_DISBURSEMENT` transaction. A repayment form is included so loans can be cleared. Interest and credit scoring are out of scope.
- **Atomicity**: each operation runs in one database transaction; a failure rolls everything back (a failed transfer never moves half the money).
- **Security basics**: CSRF protection on all forms, server-side validation, no raw SQL, and Jinja auto-escaping.

## Project layout

```
app.py        Flask routes
services.py   Business logic and validation
models.py     SQLAlchemy models (Account, Transaction, Loan)
templates/    HTML pages
tests/        pytest suite
```

## Limitations

There is no login or user authentication, so this is a demo and must not be exposed publicly with real data.
