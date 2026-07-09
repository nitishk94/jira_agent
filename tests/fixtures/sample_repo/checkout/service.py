from checkout.validators import validate_cart


def checkout(cart_items: list[dict]) -> dict:
    validate_cart(cart_items)
    first_item = cart_items[0]
    return {
        "item_count": len(cart_items),
        "primary_sku": first_item["sku"],
        "total": sum(item["price"] * item["quantity"] for item in cart_items),
    }
