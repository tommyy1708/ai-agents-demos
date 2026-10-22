"""The online shop's data: a SQLite file seeded with made-up customers and orders.

Everything here is fictional. Emails use example.com and phone numbers use the 555-01xx range, which are reserved
for examples and never belong to real people.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
  email    TEXT PRIMARY KEY,
  name     TEXT NOT NULL,
  phone    TEXT NOT NULL,
  premium  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS orders (
  id              INTEGER PRIMARY KEY,
  customer_email  TEXT NOT NULL REFERENCES customers(email),
  status          TEXT NOT NULL,
  placed_on       TEXT NOT NULL,
  shipping_address TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS order_items (
  order_id  INTEGER NOT NULL REFERENCES orders(id),
  product   TEXT NOT NULL,
  quantity  INTEGER NOT NULL,
  price     REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS action_log (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_email  TEXT NOT NULL,
  order_id        INTEGER,
  action          TEXT NOT NULL,
  note            TEXT NOT NULL,
  logged_at       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memory (
  customer_email  TEXT NOT NULL,
  noted_at        TEXT NOT NULL,
  note            TEXT NOT NULL
);
"""

CUSTOMERS = [
    ("maya.chen@example.com", "Maya Chen", "+1 555-0142", 1),
    ("leo.garcia@example.com", "Leo Garcia", "+1 555-0167", 0),
    ("ines.novak@example.com", "Ines Novak", "+1 555-0118", 0),
    ("sam.okafor@example.com", "Sam Okafor", "+1 555-0193", 1),
]

ADDRESSES = {
    "maya.chen@example.com": "12 Harbor Lane, Springfield",
    "leo.garcia@example.com": "48 Orchard Street, Riverton",
    "ines.novak@example.com": "7 Mill Road, Lakeside",
    "sam.okafor@example.com": "301 Cedar Avenue, Hillcrest",
}

# (order id, customer, status, placed on, [(product, quantity, unit price)])
ORDERS = [
    (1, "maya.chen@example.com", "delivered", "2026-08-02", [("Wireless headphones", 1, 89.00)]),
    (2, "maya.chen@example.com", "shipped", "2026-10-14", [("Desk lamp", 1, 34.50), ("LED bulbs (4-pack)", 2, 9.99)]),
    (3, "maya.chen@example.com", "processing", "2026-10-20", [("Coffee grinder", 1, 59.00)]),
    (4, "leo.garcia@example.com", "delivered", "2026-07-11", [("Running shoes", 1, 120.00)]),
    (5, "leo.garcia@example.com", "shipped", "2026-10-16", [("Rain jacket", 1, 75.00), ("Travel mug", 1, 18.00)]),
    (6, "ines.novak@example.com", "processing", "2026-10-19", [("Yoga mat", 1, 29.00)]),
    (7, "ines.novak@example.com", "delivered", "2026-09-03", [("Bookshelf", 1, 140.00)]),
    (8, "sam.okafor@example.com", "shipped", "2026-10-12", [("Monitor stand", 1, 45.00)]),
    (9, "sam.okafor@example.com", "cancelled", "2026-09-21", [("Bluetooth speaker", 1, 55.00)]),
    (10, "maya.chen@example.com", "delivered", "2026-06-25", [("Plant pot set", 1, 24.00)]),
]

# Allowed status changes. Anything else is refused, whoever asks.
TRANSITIONS = {
    "processing": {"shipped", "cancelled"},
    "shipped": {"delivered"},
    "delivered": {"returned"},
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path) -> sqlite3.Connection:
    """Opens the shop database, creating and seeding it on first use."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0:
        seed(conn)
    return conn


def seed(conn: sqlite3.Connection) -> None:
    conn.executemany("INSERT INTO customers VALUES (?, ?, ?, ?)", CUSTOMERS)
    for order_id, email, status, placed_on, items in ORDERS:
        conn.execute("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", (order_id, email, status, placed_on, ADDRESSES[email]))
        conn.executemany(
            "INSERT INTO order_items VALUES (?, ?, ?, ?)", [(order_id, p, q, price) for p, q, price in items]
        )
    conn.commit()


def customer(conn: sqlite3.Connection, email: str) -> dict | None:
    row = conn.execute("SELECT * FROM customers WHERE email = ?", (email.lower(),)).fetchone()
    return dict(row) if row else None


def owner_of(conn: sqlite3.Connection, order_id: int) -> str | None:
    row = conn.execute("SELECT customer_email FROM orders WHERE id = ?", (order_id,)).fetchone()
    return row[0] if row else None


def order(conn: sqlite3.Connection, order_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not row:
        return None
    items = conn.execute("SELECT product, quantity, price FROM order_items WHERE order_id = ?", (order_id,)).fetchall()
    total = round(sum(i["quantity"] * i["price"] for i in items), 2)
    return {
        "order_id": row["id"],
        "status": row["status"],
        "placed_on": row["placed_on"],
        "items": [dict(i) for i in items],
        "total": total,
        "customer_email": row["customer_email"],
        "shipping_address": row["shipping_address"],
    }


def customer_orders(conn: sqlite3.Connection, email: str) -> list[dict]:
    ids = conn.execute("SELECT id FROM orders WHERE customer_email = ? ORDER BY placed_on", (email.lower(),)).fetchall()
    return [order(conn, i[0]) for i in ids]


def log_action(conn: sqlite3.Connection, email: str, action: str, note: str, order_id: int | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO action_log (customer_email, order_id, action, note, logged_at) VALUES (?, ?, ?, ?, ?)",
        (email.lower(), order_id, action, note, now()),
    )
    conn.commit()
    return cur.lastrowid


def update_status(conn: sqlite3.Connection, order_id: int, status: str) -> dict:
    """Changes an order's status if the business rules allow it. Note what it does NOT check: who is asking."""
    current = order(conn, order_id)
    if not current:
        return {"error": f"Order {order_id} not found"}
    if status not in TRANSITIONS.get(current["status"], set()):
        return {"error": f"An order that is {current['status']} can't become {status}"}
    conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    conn.commit()
    return {"order_id": order_id, "status": status, "previous_status": current["status"]}


def remember(conn: sqlite3.Connection, email: str, note: str) -> None:
    conn.execute("INSERT INTO memory VALUES (?, ?, ?)", (email.lower(), now(), note))
    conn.commit()


def recall(conn: sqlite3.Connection, email: str, limit: int = 5) -> list[str]:
    rows = conn.execute(
        "SELECT note FROM memory WHERE customer_email = ? ORDER BY rowid DESC LIMIT ?", (email.lower(), limit)
    ).fetchall()
    return [r[0] for r in reversed(rows)]
