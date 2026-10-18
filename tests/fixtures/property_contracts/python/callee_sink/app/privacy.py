from app.vendor.contracts import produces


def evaluate(messages):
    return produces(list(messages), "cloud_disclosable")
