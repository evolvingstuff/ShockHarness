def read(path):
    try:
        return open(path).read()
    except:
        pass


def read_ellipsis(path):
    try:
        return open(path).read()
    except:
        ...
