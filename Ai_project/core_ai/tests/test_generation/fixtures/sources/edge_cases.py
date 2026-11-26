from abc import ABC, abstractmethod


def _helper(value):
    return value * 2


def double(value):
    return _helper(value)


def not_done_yet():
    pass


def only_documented():
    """This function has a docstring and nothing else."""


def ellipsis_body():
    ...


class Shape(ABC):
    @abstractmethod
    def area(self):
        raise NotImplementedError

    def describe(self):
        return f"shape with area {self.area()}"

    def _internal(self):
        return 1

    def __str__(self):
        return self.describe()


class Base:
    def validate(self, item):
        return item is not None


class Child(Base):
    def save(self, item):
        if self.validate(item):
            return True
        return False
