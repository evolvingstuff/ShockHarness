import asyncio


async def gather(tasks):
    try:
        await asyncio.gather(*tasks)
    except* ValueError as group:
        raise Failed("values") from group
    except* OSError:
        pass
