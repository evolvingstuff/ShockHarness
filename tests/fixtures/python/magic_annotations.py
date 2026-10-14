from typing import Annotated, Literal


def f(x: Literal[2], y: Annotated[int, 3]) -> Literal[4]:
    return 1


z: Literal[5] = 1
