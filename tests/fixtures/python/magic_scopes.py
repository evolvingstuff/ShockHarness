top = 2


def outer():
    inner_value = 3

    def inner():
        return 4

    return inner


class Shape:
    SIDES = 5

    def area(self):
        return 6

    async def fetch(self):
        return 7


square = lambda x: x * 8  # noqa: E731


def matcher(value):
    match value:
        case 9:
            return 0
        case -10:
            return 1
    return 0
