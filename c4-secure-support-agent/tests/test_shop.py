from contextlib import closing

from support_agent import config, shop


def test_status_changes_follow_the_business_rules(fresh_shop):
    with closing(shop.connect(config.SHOP_DB)) as conn:
        assert shop.update_status(conn, 3, "shipped")["status"] == "shipped"
        assert "error" in shop.update_status(conn, 3, "cancelled")  # shipped orders can't be cancelled
        assert "error" in shop.update_status(conn, 99, "shipped")


def test_orders_belong_to_one_customer(fresh_shop):
    with closing(shop.connect(config.SHOP_DB)) as conn:
        assert shop.owner_of(conn, 5) == "leo.garcia@example.com"
        assert [o["order_id"] for o in shop.customer_orders(conn, "maya.chen@example.com")] == [10, 1, 2, 3]


def test_memory_keeps_the_latest_notes_in_order(fresh_shop):
    with closing(shop.connect(config.SHOP_DB)) as conn:
        for i in range(7):
            shop.remember(conn, "maya.chen@example.com", f"note {i}")
        assert shop.recall(conn, "maya.chen@example.com") == [f"note {i}" for i in range(2, 7)]
