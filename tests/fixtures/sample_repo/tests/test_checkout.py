from checkout.service import checkout


def test_checkout_with_items():
    cart = [{"sku": "ABC", "price": 10, "quantity": 2}]
    result = checkout(cart)
    assert result == {"item_count": 1, "primary_sku": "ABC", "total": 20}
