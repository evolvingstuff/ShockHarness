"""Merge contacts that share an email (case-insensitive) or a verified phone."""

from dataclasses import dataclass

from contactclean.model import EMPTY, PHONE_VERIFIED, Contact, Merge


@dataclass(frozen=True)
class MergeResult:
    contacts: tuple[Contact, ...]
    merges: tuple[Merge, ...]


def _match_keys(contact: Contact) -> tuple[tuple[str, str], ...]:
    keys = []
    if contact.email != EMPTY:
        keys.append(("email", contact.email.lower()))
    if contact.phone_status == PHONE_VERIFIED:
        keys.append(("phone", contact.phone))
    return tuple(keys)


def _find(parent: dict[int, int], index: int) -> int:
    root = index
    while parent[root] != root:
        root = parent[root]
    return root


def merge_contacts(contacts: tuple[Contact, ...]) -> MergeResult:
    """Group contacts by shared keys; each group keeps its most complete record, ties going to the earliest row."""
    parent = {index: index for index in range(len(contacts))}
    owner_of_key: dict[tuple[str, str], int] = {}
    reasons_by_index: dict[int, set[str]] = {index: set() for index in range(len(contacts))}
    for index, contact in enumerate(contacts):
        for key in _match_keys(contact):
            if key not in owner_of_key:
                owner_of_key[key] = index
                continue
            first, second = _find(parent, owner_of_key[key]), _find(parent, index)
            root, child = min(first, second), max(first, second)
            parent[child] = root
            reasons_by_index[root] |= reasons_by_index[child]
            reasons_by_index[root].add(f"same {key[0]}")

    groups: dict[int, list[Contact]] = {}
    for index, contact in enumerate(contacts):
        groups.setdefault(_find(parent, index), []).append(contact)

    kept = []
    merges = []
    for root in sorted(groups):
        members = groups[root]
        best = max(members, key=lambda member: (member.filled_fields(), -member.row_number))
        kept.append(best)
        if len(members) > 1:
            merges.append(
                Merge(
                    kept_row=best.row_number,
                    merged_rows=tuple(member.row_number for member in members if member is not best),
                    reasons=tuple(sorted(reasons_by_index[root])),
                )
            )
    if len(kept) + sum(len(merge.merged_rows) for merge in merges) != len(contacts):
        raise AssertionError("merging lost or duplicated a contact")
    return MergeResult(contacts=tuple(kept), merges=tuple(merges))
