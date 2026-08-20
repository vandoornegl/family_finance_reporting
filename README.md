# Family finance reporting

Create an app for visualising current and budgeted expenses.

Create and activate a virtual environment, then install the dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Start the web app from the repository root:

```powershell
python -m uvicorn reporting.app.main:app --reload
```

Open `http://localhost:8000/accounts` to manage bank, credit-card, savings, and
meal-voucher accounts. Accounts with imported history cannot be deleted.

Open `http://localhost:8000/transactions` to review transactions and assign
categories.
