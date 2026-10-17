"""contactclean: clean a contacts CSV export and report unusable rows."""
import argparse
import csv
import json
import re
import sys
from datetime import date

FIELDS = ["name", "email", "phone", "birthday", "country"]
OUT_FIELDS = FIELDS + ["phone_status"]

# country -> (calling code, strips national trunk "0", valid national lengths)
COUNTRIES = {
    "US": ("1", False, {10}),
    "GB": ("44", True, {10}),
    "DE": ("49", True, set(range(6, 14))),
    "FR": ("33", True, {9}),
}
EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


class Invalid(Exception):
    pass


def norm_email(v):
    v = v.lower()
    if not EMAIL_RE.match(v):
        raise Invalid(f"invalid email: {v!r}")
    return v


def norm_phone(v, country):
    """Return (phone, status); status is 'verified' or 'unverified'."""
    if not re.fullmatch(r"\+?[\d\s().\-/]+", v):
        raise Invalid(f"invalid phone: {v!r}")
    digits = re.sub(r"\D", "", v)
    if not 4 <= len(digits) <= 15:
        raise Invalid(f"invalid phone length: {v!r}")
    if v.startswith("+"):
        if len(digits) < 8:
            raise Invalid(f"invalid phone length: {v!r}")
        return "+" + digits, "verified"
    if country in COUNTRIES:
        cc, trunk, lengths = COUNTRIES[country]
        national = digits
        if country == "US" and len(national) == 11 and national[0] == "1":
            national = national[1:]
        elif trunk and national.startswith("0"):
            national = national[1:]
        if len(national) not in lengths:
            raise Invalid(f"invalid {country} phone number: {v!r}")
        return "+" + cc + national, "verified"
    return digits, "unverified"


def norm_birthday(v):
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", v)
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", v)
        if not m:
            raise Invalid(f"invalid birthday format: {v!r}")
        a, b, y = map(int, m.groups())
        if a > 12 or a == b:
            d, mo = a, b  # DD/MM/YYYY
        elif b > 12:
            mo, d = a, b  # MM/DD/YYYY
        else:
            raise Invalid(f"ambiguous birthday: {v!r}")
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        raise Invalid(f"invalid birthday date: {v!r}") from None


def completeness(rec):
    return sum(1 for f in FIELDS if rec[f])


def merge(records):
    """records: list of (row, rec). Union rows sharing an email or verified phone."""
    parent = list(range(len(records)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    seen = {}
    for i, (_, rec) in enumerate(records):
        keys = []
        if rec["email"]:
            keys.append(("e", rec["email"]))
        if rec["phone"] and rec["phone_status"] == "verified":
            keys.append(("p", rec["phone"]))
        for k in keys:
            if k in seen:
                parent[find(i)] = find(seen[k])
            else:
                seen[k] = i
    groups = {}
    for i in range(len(records)):
        groups.setdefault(find(i), []).append(i)

    merged, merges = [], []
    for idxs in sorted(groups.values(), key=min):
        if len(idxs) == 1:
            merged.append(records[idxs[0]])
            continue
        # most complete wins; ties go to the earliest row
        best = max(idxs, key=lambda i: (completeness(records[i][1]), -i))
        out = dict(records[best][1])
        for i in sorted(idxs):
            for f in FIELDS:
                if not out[f] and records[i][1][f]:
                    out[f] = records[i][1][f]
                    if f == "phone":
                        out["phone_status"] = records[i][1]["phone_status"]
        merged.append((records[best][0], out))
        merges.append({
            "kept_row": records[best][0],
            "merged_rows": sorted(records[i][0] for i in idxs),
            "reason": "same email or verified phone",
        })
    merged.sort(key=lambda t: t[0])
    return merged, merges


def clean(rows):
    """rows: iterable of (row_number, dict). Returns (records, rejected, issues, merges)."""
    records, rejected, issues = [], [], []
    for n, raw in rows:
        r = {f: (raw.get(f) or "").strip() for f in FIELDS}
        if not r["name"]:
            rejected.append({"row": n, "reason": "missing name"})
            continue
        country = r["country"].upper()
        if country and not re.fullmatch(r"[A-Z]{2}", country):
            issues.append({"row": n, "field": "country", "reason": f"invalid country: {r['country']!r}"})
            country = ""
        r["country"] = country
        r["phone_status"] = ""
        for field, fn in (("email", norm_email), ("birthday", norm_birthday)):
            if r[field]:
                try:
                    r[field] = fn(r[field])
                except Invalid as e:
                    issues.append({"row": n, "field": field, "reason": str(e)})
                    r[field] = ""
        if r["phone"]:
            try:
                r["phone"], r["phone_status"] = norm_phone(r["phone"], country)
            except Invalid as e:
                issues.append({"row": n, "field": "phone", "reason": str(e)})
                r["phone"] = ""
        records.append((n, r))
    merged, merges = merge(records)
    return merged, rejected, issues, merges


def main(argv=None):
    p = argparse.ArgumentParser(prog="contactclean")
    p.add_argument("input")
    p.add_argument("--output", required=True)
    p.add_argument("--report", required=True)
    args = p.parse_args(argv)
    try:
        with open(args.input, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames:
                raise ValueError("empty input")
            reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]
            if "name" not in reader.fieldnames:
                raise ValueError("missing required column: name")
            # row numbers are file line numbers (header is row 1)
            rows = [(i, row) for i, row in enumerate(reader, start=2)]
    except (OSError, UnicodeDecodeError, ValueError, csv.Error) as e:
        print(f"contactclean: cannot read {args.input}: {e}", file=sys.stderr)
        return 2

    merged, rejected, issues, merges = clean(rows)
    with open(args.output, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, OUT_FIELDS)
        w.writeheader()
        for _, rec in merged:
            w.writerow(rec)
    report = {"rejected": rejected, "invalid_fields": issues, "merged": merges}
    with open(args.report, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    return 1 if rejected or issues else 0


if __name__ == "__main__":
    sys.exit(main())
