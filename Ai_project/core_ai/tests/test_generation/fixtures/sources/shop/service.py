from .models import Cart, Product, format_price


class Checkout:
    def __init__(self, cart: Cart):
        self.cart = cart

    def add_product(self, cart: Cart, product: Product) -> int:
        return cart.add(product)

    def receipt(self, cart: Cart) -> str:
        amount = cart.total()
        return format_price(amount)


def new_cart() -> Cart:
    return Cart()
