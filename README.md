# Family finance reporting

Create an app for visualising current and budgeted expenses.

Run the web app with:

```powershell
uvicorn reporting.app.main:app --reload
```

Open `http://localhost:8000/accounts` to manage bank, credit-card, savings, and
meal-voucher accounts. Accounts with imported history cannot be deleted.
