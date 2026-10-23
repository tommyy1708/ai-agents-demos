"""The shop's data: the same made-up customers and orders as the Week 4 support agent (c4-secure-support-agent).

It's copied, not imported: c4 runs on Google ADK and this demo on LiveKit Agents, and the two pin incompatible
versions of OpenTelemetry. Every benchmark run gets its own in-memory database, so an action logged in one run
can't change the answer in the next.

Everything here is fictional. Emails use example.com and phone numbers use the 555-01xx range.
"""

import sqlite3
from datetime import datetime, timezone

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


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE customers (email TEXT PRIMARY KEY, name TEXT, phone TEXT, premium INTEGER);
        CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_email TEXT, status TEXT, placed_on TEXT, shipping_address TEXT);
        CREATE TABLE order_items (order_id INTEGER, product TEXT, quantity INTEGER, price REAL);
        CREATE TABLE action_log (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_email TEXT, order_id INTEGER,
                                 action TEXT, note TEXT, logged_at TEXT);
        """
    )
    conn.executemany("INSERT INTO customers VALUES (?, ?, ?, ?)", CUSTOMERS)
    for order_id, email, status, placed_on, items in ORDERS:
        conn.execute("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", (order_id, email, status, placed_on, ADDRESSES[email]))
        conn.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?)", [(order_id, p, q, price) for p, q, price in items])
    return conn


def owner_of(conn: sqlite3.Connection, order_id: int) -> str | None:
    row = conn.execute("SELECT customer_email FROM orders WHERE id = ?", (order_id,)).fetchone()
    return row[0] if row else None


def order(conn: sqlite3.Connection, order_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not row:
        return None
    items = conn.execute("SELECT product, quantity, price FROM order_items WHERE order_id = ?", (order_id,)).fetchall()
    return {
        "order_id": row["id"],
        "status": row["status"],
        "placed_on": row["placed_on"],
        "items": [dict(i) for i in items],
        "total": round(sum(i["quantity"] * i["price"] for i in items), 2),
        "customer_email": row["customer_email"],
        "shipping_address": row["shipping_address"],
    }


def customer_orders(conn: sqlite3.Connection, email: str) -> list[dict]:
    ids = conn.execute("SELECT id FROM orders WHERE customer_email = ? ORDER BY placed_on", (email,)).fetchall()
    return [order(conn, i[0]) for i in ids]


def log_action(conn: sqlite3.Connection, email: str, action: str, note: str, order_id: int | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO action_log (customer_email, order_id, action, note, logged_at) VALUES (?, ?, ?, ?, ?)",
        (email, order_id, action, note, datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )
    return cur.lastrowid
