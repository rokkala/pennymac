"""Synthetic loan file generator for the four PennyMac boarding sources.

Every source deliberately differs in format, field names, date formats, units and codes,
which is the heterogeneity described in the PoV deck:

  PCG Retail       CSV    camel-case names, ISO dates, rates as percent
  Bulk Acquisition Excel  spaced names, MM/DD/YYYY, rates as decimals, full state names
  Sub-Servicing    TXT    pipe-delimited, cryptic abbreviations, YYYYMMDD dates, amounts in cents
  Correspondent    CSV    composite "LAST, FIRST" names, single-line address, mixed code values

About 6% of rows carry realistic defects (missing values, invalid codes, bad dates, out-of-range
rates, FICO typos) so the rule engine and exception manager have something to do.
All data is fake. No real borrower information.
"""
from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

FIRST = ["James", "Maria", "Robert", "Linda", "Michael", "Patricia", "David", "Jennifer", "John", "Elizabeth",
         "Carlos", "Priya", "Wei", "Aisha", "Daniel", "Sofia", "Kevin", "Grace", "Luis", "Emily", "Andre", "Mei"]
LAST = ["Smith", "Johnson", "Garcia", "Nguyen", "Brown", "Martinez", "Lee", "Patel", "Davis", "Lopez",
        "Wilson", "Anderson", "Thomas", "Kim", "Clark", "Lewis", "Walker", "Hall", "Young", "Allen"]
STREETS = ["Oak St", "Maple Ave", "Cedar Ln", "Pine Rd", "Elm Dr", "Sunset Blvd", "Lakeview Ct", "Hillcrest Way",
           "Park Pl", "Ridge Rd", "Willow St", "Highland Ave"]
CITIES = [("Westlake Village", "CA", "California", "91361", "Los Angeles"), ("Plano", "TX", "Texas", "75024", "Collin"),
          ("Tampa", "FL", "Florida", "33602", "Hillsborough"), ("Phoenix", "AZ", "Arizona", "85004", "Maricopa"),
          ("Denver", "CO", "Colorado", "80202", "Denver"), ("Charlotte", "NC", "North Carolina", "28202", "Mecklenburg"),
          ("Atlanta", "GA", "Georgia", "30303", "Fulton"), ("Seattle", "WA", "Washington", "98101", "King"),
          ("Columbus", "OH", "Ohio", "43215", "Franklin"), ("Las Vegas", "NV", "Nevada", "89101", "Clark")]
INVESTORS = [("FN001", "FNMA"), ("FH002", "FHLMC"), ("GN003", "GNMA"), ("PV004", "PVT")]


def _loan(rng: random.Random, i: int, prefix: str) -> dict:
    """Canonical (SSE-shaped) loan; each source writer renames/reformats it."""
    note = date(2019, 1, 1) + timedelta(days=rng.randint(0, 2400))
    term = rng.choice([360, 360, 360, 180, 240])
    amount = round(rng.uniform(90_000, 950_000), -2)
    rate = round(rng.uniform(2.5, 7.875) * 8) / 8
    loan_type = rng.choice(["CNV", "CNV", "CNV", "FHA", "VA", "USDA"])
    city, st, st_full, zp, county = rng.choice(CITIES)
    first, last = rng.choice(FIRST), rng.choice(LAST)
    first_pay = (note.replace(day=1) + timedelta(days=62)).replace(day=1)
    elapsed = rng.randint(1, 60)
    upb = round(amount * (1 - elapsed / term * 0.7), 2)
    r = rate / 1200
    pi = round(amount * r / (1 - (1 + r) ** -term), 2)
    appraised = round(amount / rng.uniform(0.55, 0.97), -3)
    inv_code, inv_cat = rng.choice(INVESTORS)
    if loan_type in ("FHA", "VA", "USDA"):
        inv_code, inv_cat = "GN003", "GNMA"
    escrow = rng.random() < 0.8
    ssn_area = rng.randint(100, 665)
    return {
        "loan_number": f"{prefix}{i:08d}",
        "loan_type": loan_type,
        "loan_purpose": rng.choice(["PUR", "REF", "CSH"]),
        "lien_position": 1,
        "amortization_type": rng.choice(["FRM", "FRM", "FRM", "ARM"]),
        "original_loan_amount": amount,
        "current_principal_balance": upb,
        "interest_rate": rate,
        "original_term_months": term,
        "note_date": note,
        "first_payment_date": first_pay,
        "maturity_date": date(first_pay.year + term // 12, first_pay.month, 1) - timedelta(days=0),
        "next_payment_due_date": date(2026, rng.randint(11, 12), 1),
        "principal_interest_payment": pi,
        "ltv_ratio": round(amount / appraised * 100, 2),
        "dti_ratio": round(rng.uniform(18, 49), 2),
        "occupancy_type": rng.choice(["P", "P", "P", "S", "I"]),
        "borrower_first_name": first,
        "borrower_last_name": last,
        "borrower_ssn": f"{ssn_area:03d}{rng.randint(10, 99):02d}{rng.randint(1000, 9999):04d}",
        "borrower_dob": date(rng.randint(1950, 1998), rng.randint(1, 12), rng.randint(1, 28)),
        "borrower_email": f"{first.lower()}.{last.lower()}{i % 997}@example.com",
        "borrower_home_phone": f"{rng.randint(201, 989)}{rng.randint(200, 999)}{rng.randint(1000, 9999)}",
        "borrower_fico": rng.randint(620, 820),
        "property_address_line1": f"{rng.randint(10, 9999)} {rng.choice(STREETS)}",
        "property_city": city, "property_state": st, "_state_full": st_full, "property_zip": zp, "property_county": county,
        "property_type": rng.choice(["SFR", "SFR", "SFR", "CON", "PUD"]),
        "number_of_units": 1,
        "appraised_value": appraised,
        "escrow_flag": escrow,
        "escrow_balance": round(rng.uniform(300, 6000), 2) if escrow else 0.0,
        "investor_code": inv_code, "investor_category": inv_cat,
        "servicing_fee_rate": 0.25,
        "transfer_effective_date": date(2026, 11, 1),
        "ofac_check_status": "C",
        "fraud_alert_flag": False,
    }


def _inject_defect(rng: random.Random, row: dict) -> None:
    kind = rng.choice(["missing_state", "bad_state", "bad_rate", "fico_typo", "missing_ssn", "bad_zip",
                       "maturity_before_note", "upb_gt_orig", "missing_name", "bad_occupancy", "ofac_hit", "fraud"])
    if kind == "ofac_hit" and rng.random() > 0.15:
        kind = "bad_zip"
    if kind == "fraud" and rng.random() > 0.15:
        kind = "fico_typo"
    if kind == "missing_state":
        row["property_state"] = ""
    elif kind == "bad_state":
        row["property_state"] = rng.choice(["XX", "Ca", "C A", "TEX"])
    elif kind == "bad_rate":
        row["interest_rate"] = row["interest_rate"] * 10
    elif kind == "fico_typo":
        row["borrower_fico"] = row["borrower_fico"] * 10 if rng.random() < 0.5 else 0
    elif kind == "missing_ssn":
        row["borrower_ssn"] = ""
    elif kind == "bad_zip":
        row["property_zip"] = row["property_zip"][:3]
    elif kind == "maturity_before_note":
        row["maturity_date"] = row["note_date"] - timedelta(days=30)
    elif kind == "upb_gt_orig":
        row["current_principal_balance"] = row["original_loan_amount"] * 1.2
    elif kind == "missing_name":
        row["borrower_last_name"] = ""
    elif kind == "bad_occupancy":
        row["occupancy_type"] = rng.choice(["Owner", "O", "X"])
    elif kind == "ofac_hit":
        row["ofac_check_status"] = "H"
    elif kind == "fraud":
        row["fraud_alert_flag"] = True


def canonical_loans(n: int, prefix: str, seed: int = 7, defect_rate: float = 0.06, offset: int = 0):
    rng = random.Random(seed)
    for i in range(offset + 1, offset + n + 1):
        row = _loan(rng, i, prefix)
        if rng.random() < defect_rate:
            _inject_defect(rng, row)
        yield row


# ---------------------------------------------------------------- source writers
def write_pcg_retail(path: Path, n: int, seed: int = 11, offset: int = 0) -> Path:
    cols = {
        "LoanID": "loan_number", "LoanType": "loan_type", "LoanPurpose": "loan_purpose", "LienPosition": "lien_position",
        "AmortizationType": "amortization_type", "OriginalLoanAmount": "original_loan_amount",
        "CurrentUPB": "current_principal_balance", "NoteRate": "interest_rate", "OrigTerm": "original_term_months",
        "NoteDate": "note_date", "FirstPaymentDate": "first_payment_date", "MaturityDate": "maturity_date",
        "NextDueDate": "next_payment_due_date", "PIPayment": "principal_interest_payment", "LTV": "ltv_ratio",
        "DTI": "dti_ratio", "Occupancy": "occupancy_type", "BorrowerFirstName": "borrower_first_name",
        "BorrowerLastName": "borrower_last_name", "BorrowerSSN": "borrower_ssn", "BorrowerDOB": "borrower_dob",
        "BorrowerEmail": "borrower_email", "HomePhone": "borrower_home_phone", "FICO": "borrower_fico",
        "PropertyAddress": "property_address_line1", "PropertyCity": "property_city", "PropertyState": "property_state",
        "PropertyZip": "property_zip", "PropertyCounty": "property_county", "PropertyType": "property_type",
        "Units": "number_of_units", "AppraisedValue": "appraised_value", "EscrowIndicator": "escrow_flag",
        "EscrowBalance": "escrow_balance", "InvestorCode": "investor_code", "InvestorType": "investor_category",
        "ServicingFee": "servicing_fee_rate", "TransferDate": "transfer_effective_date", "OFACStatus": "ofac_check_status",
        "FraudFlag": "fraud_alert_flag",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols.keys())
        for r in canonical_loans(n, "PCG", seed, offset=offset):
            out = []
            for c in cols.values():
                v = r[c]
                if isinstance(v, date):
                    v = v.isoformat()
                elif isinstance(v, bool):
                    v = "Y" if v else "N"
                out.append(v)
            w.writerow(out)
    return path


def write_bulk_excel(path: Path, n: int, seed: int = 22, offset: int = 0) -> Path:
    from openpyxl import Workbook

    cols = {
        "Loan No": "loan_number", "Seller Loan ID": None, "Product Type": "loan_type", "Purpose": "loan_purpose",
        "Lien": "lien_position", "Rate Type": "amortization_type", "Orig Bal": "original_loan_amount",
        "Curr Bal": "current_principal_balance", "Int Rate": "interest_rate", "Loan Term": "original_term_months",
        "Orig Date": "note_date", "First Pmt Date": "first_payment_date", "Mat Date": "maturity_date",
        "Next Due": "next_payment_due_date", "P&I": "principal_interest_payment", "Orig LTV": "ltv_ratio",
        "Debt Ratio": "dti_ratio", "Occ Type": "occupancy_type", "First Name": "borrower_first_name",
        "Last Name": "borrower_last_name", "Social Security #": "borrower_ssn", "Date of Birth": "borrower_dob",
        "Email Address": "borrower_email", "Phone Number": "borrower_home_phone", "Credit Score": "borrower_fico",
        "Subject Address": "property_address_line1", "Subject City": "property_city", "Subject State": "property_state",
        "Zip Code": "property_zip", "County": "property_county", "Prop Type": "property_type", "No of Units": "number_of_units",
        "Appraisal Value": "appraised_value", "Escrowed": "escrow_flag", "Escrow Bal": "escrow_balance",
        "Investor": "investor_code", "Agency": "investor_category", "Svc Fee Rate": "servicing_fee_rate",
        "Sale Date": "transfer_effective_date", "Sanctions Screen": "ofac_check_status", "Fraud Indicator": "fraud_alert_flag",
    }
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Loan Tape")
    ws.append(list(cols.keys()))
    for r in canonical_loans(n, "BLK", seed, offset=offset):
        out = []
        for c in cols.values():
            if c is None:
                out.append(f"S-{r['loan_number'][3:]}")
                continue
            v = r[c]
            if c == "property_state" and len(v) == 2 and v.isalpha() and v.isupper():
                v = r["_state_full"]  # full state names -> needs lookup translation
            if c in ("interest_rate", "servicing_fee_rate"):
                v = round(v / 100, 6)  # decimal form -> needs scaling transform
            if c == "amortization_type":
                v = {"FRM": "Fixed", "ARM": "Adjustable"}[v]
            if isinstance(v, date):
                v = v.strftime("%m/%d/%Y")
            elif isinstance(v, bool):
                v = "Yes" if v else "No"
            out.append(v)
        ws.append(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def write_subservicing_txt(path: Path, n: int, seed: int = 33, offset: int = 0) -> Path:
    cols = {
        "LN_NBR": "loan_number", "LN_TYP": "loan_type", "PURP_CD": "loan_purpose", "LIEN_POS": "lien_position",
        "AMRT_TYP": "amortization_type", "ORIG_AMT": "original_loan_amount", "CUR_UPB": "current_principal_balance",
        "INT_RT": "interest_rate", "ORIG_TRM": "original_term_months", "NOTE_DT": "note_date",
        "FRST_PMT_DT": "first_payment_date", "MAT_DT": "maturity_date", "NXT_PMT_DT": "next_payment_due_date",
        "PI_AMT": "principal_interest_payment", "LTV_PCT": "ltv_ratio", "DTI_PCT": "dti_ratio", "OCC_CD": "occupancy_type",
        "B1_FNAME": "borrower_first_name", "B1_LNAME": "borrower_last_name", "B1_TIN": "borrower_ssn",
        "B1_DOB": "borrower_dob", "B1_EMAIL": "borrower_email", "B1_PHONE": "borrower_home_phone", "B1_FICO": "borrower_fico",
        "PROP_ADDR": "property_address_line1", "PROP_CITY": "property_city", "PROP_ST": "property_state",
        "PROP_ZIP": "property_zip", "PROP_CNTY": "property_county", "PROP_TYP": "property_type",
        "NUM_UNITS": "number_of_units", "APPR_VAL": "appraised_value", "ESC_IND": "escrow_flag", "ESC_BAL": "escrow_balance",
        "INV_CD": "investor_code", "INV_CAT": "investor_category", "SVC_FEE": "servicing_fee_rate",
        "XFER_DT": "transfer_effective_date", "OFAC_STS": "ofac_check_status", "FRAUD_IND": "fraud_alert_flag",
    }
    cents = {"original_loan_amount", "current_principal_balance", "principal_interest_payment", "appraised_value", "escrow_balance"}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        f.write("|".join(cols.keys()) + "\n")
        for r in canonical_loans(n, "SUB", seed, offset=offset):
            out = []
            for c in cols.values():
                v = r[c]
                if c in cents:
                    v = int(round(v * 100))  # amounts in cents
                elif isinstance(v, date):
                    v = v.strftime("%Y%m%d")
                elif isinstance(v, bool):
                    v = "1" if v else "0"
                out.append(str(v))
            f.write("|".join(out) + "\n")
    return path


def write_correspondent_csv(path: Path, n: int, seed: int = 44, offset: int = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = ["Correspondent Loan Number", "Loan Program", "Purpose of Loan", "Lien Priority", "Fixed or ARM",
               "Note Amount", "Unpaid Principal Balance", "Current Rate", "Term (Months)", "Closing Date",
               "First Payment Due", "Maturity", "Due Date", "Monthly P and I", "Loan to Value", "Back End DTI",
               "Occupancy Status", "Borrower Name", "Tax ID", "Birth Date", "E-mail", "Primary Phone", "FICO Score",
               "Collateral Address", "Dwelling Type", "Unit Count", "Property Value", "Impound Flag", "Impound Balance",
               "Investor Number", "Investor Type", "Service Fee", "Effective Date", "OFAC", "Fraud Alert"]
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        for r in canonical_loans(n, "COR", seed, offset=offset):
            occ = {"P": "Primary", "S": "Second Home", "I": "Investment"}.get(r["occupancy_type"], r["occupancy_type"])
            addr = f"{r['property_address_line1']}, {r['property_city']}, {r['property_state']} {r['property_zip']}"
            w.writerow([
                r["loan_number"], r["loan_type"], {"PUR": "Purchase", "REF": "Rate/Term Refi", "CSH": "Cash-Out Refi"}[r["loan_purpose"]],
                r["lien_position"], r["amortization_type"], f"${r['original_loan_amount']:,.2f}",
                f"${r['current_principal_balance']:,.2f}", f"{r['interest_rate']}%", r["original_term_months"],
                r["note_date"].strftime("%m/%d/%Y"), r["first_payment_date"].strftime("%m/%d/%Y"),
                r["maturity_date"].strftime("%m/%d/%Y"), r["next_payment_due_date"].strftime("%m/%d/%Y"),
                r["principal_interest_payment"], r["ltv_ratio"], r["dti_ratio"], occ,
                f"{r['borrower_last_name']}, {r['borrower_first_name']}" if r["borrower_last_name"] else r["borrower_first_name"],
                f"{r['borrower_ssn'][:3]}-{r['borrower_ssn'][3:5]}-{r['borrower_ssn'][5:]}" if r["borrower_ssn"] else "",
                r["borrower_dob"].strftime("%m/%d/%Y"), r["borrower_email"],
                f"({r['borrower_home_phone'][:3]}) {r['borrower_home_phone'][3:6]}-{r['borrower_home_phone'][6:]}",
                r["borrower_fico"], addr, r["property_type"], r["number_of_units"], r["appraised_value"],
                "TRUE" if r["escrow_flag"] else "FALSE", r["escrow_balance"], r["investor_code"], r["investor_category"],
                r["servicing_fee_rate"], r["transfer_effective_date"].strftime("%m/%d/%Y"), r["ofac_check_status"],
                "TRUE" if r["fraud_alert_flag"] else "FALSE",
            ])
    return path


SOURCES = {
    "pcg_retail": ("PCG Retail", "csv", write_pcg_retail),
    "bulk_acquisition": ("Bulk Acquisition", "xlsx", write_bulk_excel),
    "sub_servicing": ("Sub-Servicing", "txt", write_subservicing_txt),
    "correspondent": ("Correspondent", "csv", write_correspondent_csv),
}


def generate_all(out_dir: Path, n: int = 500) -> dict[str, Path]:
    out = {}
    for key, (_, ext, fn) in SOURCES.items():
        out[key] = fn(out_dir / f"{key}_sample.{ext}", n)
    return out
