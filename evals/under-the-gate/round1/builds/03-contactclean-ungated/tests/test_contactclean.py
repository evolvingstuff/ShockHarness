import csv, json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import contactclean as cc


def run(text):
    d = tempfile.mkdtemp()
    i, o, r = (os.path.join(d, x) for x in ("in.csv", "out.csv", "rep.json"))
    with open(i, "w") as f:
        f.write(text)
    code = cc.main([i, "--output", o, "--report", r])
    out = list(csv.DictReader(open(o))) if os.path.exists(o) else None
    rep = json.load(open(r)) if os.path.exists(r) else None
    return code, out, rep


H = "name,email,phone,birthday,country\n"


class Tests(unittest.TestCase):
    def test_clean_ok(self):
        code, out, rep = run(H + " Ann , ANN@X.COM ,(212) 555-0100,1990-01-31,us\n")
        self.assertEqual(code, 0)
        self.assertEqual(out[0]["email"], "ann@x.com")
        self.assertEqual(out[0]["phone"], "+12125550100")
        self.assertEqual(out[0]["phone_status"], "verified")
        self.assertEqual(out[0]["name"], "Ann")

    def test_phones(self):
        self.assertEqual(cc.norm_phone("020 7946 0958", "GB"), ("+442079460958", "verified"))
        self.assertEqual(cc.norm_phone("01 23 45 67 89", "FR"), ("+33123456789", "verified"))
        self.assertEqual(cc.norm_phone("030 123456", "DE")[0], "+4930123456")
        self.assertEqual(cc.norm_phone("555-0100", ""), ("5550100", "unverified"))
        self.assertEqual(cc.norm_phone("+44 20 7946 0958", ""), ("+442079460958", "verified"))
        with self.assertRaises(cc.Invalid):
            cc.norm_phone("abc", "US")
        with self.assertRaises(cc.Invalid):
            cc.norm_phone("123", "US")

    def test_birthdays(self):
        self.assertEqual(cc.norm_birthday("25/12/1990"), "1990-12-25")
        self.assertEqual(cc.norm_birthday("12/25/1990"), "1990-12-25")
        self.assertEqual(cc.norm_birthday("05/05/1990"), "1990-05-05")
        for bad in ("03/04/1990", "31/02/1990", "1990-13-01", "yesterday"):
            with self.assertRaises(cc.Invalid):
                cc.norm_birthday(bad)

    def test_empty_vs_invalid(self):
        code, out, rep = run(H + "Ann,,,,\nBob,bad,,03/04/1990,US\n")
        self.assertEqual(code, 1)
        self.assertEqual(out[0]["email"], "")
        self.assertEqual(out[1]["email"], "")
        self.assertEqual(out[1]["birthday"], "")
        fields = {(i["row"], i["field"]) for i in rep["invalid_fields"]}
        self.assertEqual(fields, {(3, "email"), (3, "birthday")})

    def test_missing_name(self):
        code, out, rep = run(H + ",a@b.co,,,\n")
        self.assertEqual(code, 1)
        self.assertEqual(out, [])
        self.assertEqual(rep["rejected"][0]["row"], 2)

    def test_merge_email_and_phone(self):
        code, out, rep = run(
            H + "Ann,A@x.com,,,\nAnn B,a@x.com,2125550100,1990-01-01,US\nAnn C,,(212) 555-0100,,US\nZed,z@x.com,,,\n")
        self.assertEqual(code, 0)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["name"], "Ann B")
        self.assertEqual(rep["merged"][0]["merged_rows"], [2, 3, 4])

    def test_unverified_phone_not_merged(self):
        _, out, rep = run(H + "A,,555-0100,,\nB,,555-0100,,\n")
        self.assertEqual(len(out), 2)
        self.assertEqual(rep["merged"], [])

    def test_unreadable(self):
        self.assertEqual(cc.main(["/nonexistent.csv", "--output", "/tmp/x", "--report", "/tmp/y"]), 2)
        code, _, _ = run("email\na@b.co\n")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
