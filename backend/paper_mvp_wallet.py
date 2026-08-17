from __future__ import annotations

import uuid
from typing import Any, Dict, List

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from . import paper_mvp_persistent as base
from . import paper_mvp_storage_compat as compat
from .paper_mvp_auto_close import app

WALLET_TABLE = "wallet_transactions_agent"

WALLET_TRANSACTIONS: List[Dict[str, Any]] = []


class WalletTransactionIn(BaseModel):
    amount: float
    note: str = ""


def _ensure_wallet_table() -> bool:
    if not base.DATABASE_URL:
        return False
    try:
        with base.db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {WALLET_TABLE} (
                        id TEXT PRIMARY KEY,
                        user_name TEXT NOT NULL,
                        type TEXT NOT NULL,
                        amount REAL NOT NULL,
                        note TEXT,
                        created_at TEXT NOT NULL
                    )
                    """
                )
        base._DB_OK = True
        return True
    except Exception:
        base._DB_OK = False
        return False


def wallet_storage_mode() -> str:
    return "postgres" if _ensure_wallet_table() else "memory"


def list_wallet_transactions(user: str) -> List[Dict[str, Any]]:
    if not _ensure_wallet_table():
        rows = [t for t in WALLET_TRANSACTIONS if t.get("user_name") == user]
        return sorted(rows, key=lambda x: x.get("created_at", ""), reverse=True)
    with base.db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT id, type, amount, note, created_at FROM {WALLET_TABLE} WHERE user_name=%s ORDER BY created_at DESC",
                (user,),
            )
            rows = cur.fetchall()
    return [{"id": r[0], "type": r[1], "amount": float(r[2]), "note": r[3] or "", "created_at": r[4]} for r in rows]


def add_wallet_transaction(user: str, tx_type: str, amount: float, note: str = "") -> Dict[str, Any]:
    item = {
        "id": str(uuid.uuid4()),
        "user_name": user,
        "type": tx_type,
        "amount": round(float(amount), 2),
        "note": note,
        "created_at": base.now(),
    }
    if not _ensure_wallet_table():
        WALLET_TRANSACTIONS.append(item)
        return item
    with base.db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {WALLET_TABLE} (id,user_name,type,amount,note,created_at) VALUES (%s,%s,%s,%s,%s,%s)",
                (item["id"], user, tx_type, item["amount"], note, item["created_at"]),
            )
    return item


def wallet_summary(user: str) -> Dict[str, Any]:
    transactions = list_wallet_transactions(user)
    total_deposits = round(sum(t["amount"] for t in transactions if t["type"] == "deposit"), 2)
    total_withdrawals = round(sum(t["amount"] for t in transactions if t["type"] == "withdraw"), 2)
    cash_balance = round(base.START_BALANCE + total_deposits - total_withdrawals, 2)
    closed_trades = compat.compat_list_trades(user, "closed")
    realised_pnl = round(sum(float(t.get("result_money") or 0) for t in closed_trades), 2)
    balance = round(cash_balance + realised_pnl, 2)
    return {
        "starting_balance": base.START_BALANCE,
        "total_deposits": total_deposits,
        "total_withdrawals": total_withdrawals,
        "cash_balance": cash_balance,
        "realised_pnl": realised_pnl,
        "balance": balance,
        "currency": "GBP",
        "transactions": transactions[:50],
        "storage_mode": wallet_storage_mode(),
        "live_trading_locked": True,
    }


@app.get("/api/agent/wallet")
async def get_wallet(user: str = Depends(base.current_user)):
    return wallet_summary(user)


@app.post("/api/agent/wallet/deposit")
async def deposit_wallet(req: WalletTransactionIn, user: str = Depends(base.current_user)):
    if req.amount <= 0:
        raise HTTPException(status_code=422, detail="Deposit amount must be greater than zero.")
    add_wallet_transaction(user, "deposit", req.amount, req.note)
    try:
        compat.compat_add_audit(user, "wallet_deposit", "deposited", f"Deposited {req.amount:.2f} to paper wallet.", "", None)
    except Exception:
        pass
    return wallet_summary(user)


@app.post("/api/agent/wallet/withdraw")
async def withdraw_wallet(req: WalletTransactionIn, user: str = Depends(base.current_user)):
    if req.amount <= 0:
        raise HTTPException(status_code=422, detail="Withdrawal amount must be greater than zero.")
    current = wallet_summary(user)
    if req.amount > current["balance"]:
        raise HTTPException(status_code=422, detail=f"Withdrawal exceeds available balance ({current['balance']:.2f}).")
    add_wallet_transaction(user, "withdraw", req.amount, req.note)
    try:
        compat.compat_add_audit(user, "wallet_withdraw", "withdrawn", f"Withdrew {req.amount:.2f} from paper wallet.", "", None)
    except Exception:
        pass
    return wallet_summary(user)
