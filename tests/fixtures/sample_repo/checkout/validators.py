def validate_cart(cart_items: list[dict]) -> None:
    """Raises ValueError if the cart is not valid for checkout."""
    for item in cart_items:
        if item["quantity"] <= 0:
            raise ValueError(f"Invalid quantity for {item['sku']}")
    # BUG: an empty cart is never rejected here, so checkout() below blindly
    # assumes at least one item exists.
