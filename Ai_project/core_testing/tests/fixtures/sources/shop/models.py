class Product:
    def __init__(self, name: str, price: float):
        self.name = name
        self.price = price

    def discounted(self, percent: float) -> float:
        return self.price * (1 - percent / 100)


class Cart:
    def __init__(self):
        self.items = []

    def add(self, product: Product) -> int:
        self.items.append(product)
        return len(self.items)

    def total(self) -> float:
        return sum(p.price for p in self.items)


def format_price(value: float) -> str:
    return f"{value:.2f}"
