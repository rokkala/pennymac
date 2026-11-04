"""SSE (Loan Servicing System) target schema: ~100 attributes across 5 modules.

Each attribute carries the metadata the rest of the platform needs:
  * dtype / length       -> type casting + format validation
  * required             -> completeness rules + DQ scoring
  * risk                 -> exception routing hard gate (low | medium | high | critical)
  * synonyms             -> seeds the AI mapping engine
  * codes                -> allowed code list (lookup validation)

Replace or extend this file with the confirmed SSE data dictionary from PennyMac.
"""
from __future__ import annotations

from dataclasses import dataclass

MODULES = ["LOAN", "BORROWER", "PROPERTY", "ESCROW", "INVESTOR"]

US_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS",
    "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC",
    "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "PR", "GU", "VI",
]


@dataclass(frozen=True)
class TargetAttribute:
    name: str
    module: str
    dtype: str  # string | int | decimal | date | code | bool
    length: int | None = None
    required: bool = False
    risk: str = "low"  # low | medium | high | critical
    synonyms: tuple[str, ...] = ()
    description: str = ""
    codes: tuple[str, ...] = ()
    pii: bool = False


def _a(name, module, dtype, length=None, required=False, risk="low", synonyms=(), description="", codes=(), pii=False):
    return TargetAttribute(name, module, dtype, length, required, risk, tuple(synonyms), description, tuple(codes), pii)


ATTRIBUTES: list[TargetAttribute] = [
    # ---------------- LOAN (core terms) ----------------
    _a("loan_number", "LOAN", "string", 20, True, "high", ["loan id", "loan no", "loan num", "ln nbr", "account number", "acct no", "servicer loan id", "loan identifier"], "Servicer loan identifier"),
    _a("prior_servicer_loan_number", "LOAN", "string", 20, False, "low", ["prior loan number", "old loan id", "previous servicer loan", "legacy loan no", "seller loan id"]),
    _a("mers_min", "LOAN", "string", 18, False, "medium", ["min", "mers id", "mers number", "mortgage identification number"]),
    _a("loan_type", "LOAN", "code", 4, True, "medium", ["product type", "loan program type", "mortgage type", "agency type"], codes=["CNV", "FHA", "VA", "USDA"]),
    _a("loan_purpose", "LOAN", "code", 3, True, "medium", ["purpose", "purpose code", "loan purpose type"], codes=["PUR", "REF", "CSH"]),
    _a("lien_position", "LOAN", "int", 1, True, "medium", ["lien", "lien pos", "lien priority"]),
    _a("amortization_type", "LOAN", "code", 3, True, "medium", ["amort type", "rate type", "fixed or arm", "amortization"], codes=["FRM", "ARM"]),
    _a("original_loan_amount", "LOAN", "decimal", None, True, "high", ["orig amount", "original balance", "orig bal", "loan amount", "original principal", "note amount", "orig upb"]),
    _a("current_principal_balance", "LOAN", "decimal", None, True, "high", ["upb", "unpaid principal balance", "current balance", "curr bal", "principal balance", "cur upb"]),
    _a("interest_rate", "LOAN", "decimal", None, True, "high", ["note rate", "rate", "current rate", "int rate", "coupon", "interest rt"]),
    _a("original_interest_rate", "LOAN", "decimal", None, False, "high", ["orig rate", "original note rate", "initial rate"]),
    _a("original_term_months", "LOAN", "int", 3, True, "high", ["term", "orig term", "loan term", "term months", "amortization term"]),
    _a("remaining_term_months", "LOAN", "int", 3, False, "medium", ["remaining term", "rem term", "months remaining"]),
    _a("note_date", "LOAN", "date", None, True, "medium", ["note dt", "origination date", "orig date", "closing date", "funding date"]),
    _a("first_payment_date", "LOAN", "date", None, True, "medium", ["first pmt date", "first due date", "fpd", "first payment due"]),
    _a("maturity_date", "LOAN", "date", None, True, "medium", ["maturity", "mat date", "final payment date"]),
    _a("next_payment_due_date", "LOAN", "date", None, True, "medium", ["next due date", "due date", "nxt pmt dt", "paid through next", "next due"]),
    _a("last_paid_installment_date", "LOAN", "date", None, False, "low", ["last paid date", "ltd paid", "paid to date", "last payment date"]),
    _a("principal_interest_payment", "LOAN", "decimal", None, True, "high", ["p&i", "pi payment", "p and i", "monthly pi", "pi amt", "principal and interest"]),
    _a("total_monthly_payment", "LOAN", "decimal", None, False, "medium", ["piti", "total payment", "monthly payment", "total pmt"]),
    _a("ltv_ratio", "LOAN", "decimal", None, False, "high", ["ltv", "loan to value", "orig ltv"]),
    _a("cltv_ratio", "LOAN", "decimal", None, False, "high", ["cltv", "combined ltv", "combined loan to value"]),
    _a("dti_ratio", "LOAN", "decimal", None, False, "high", ["dti", "debt to income", "back end dti", "debt ratio"]),
    _a("occupancy_type", "LOAN", "code", 1, True, "medium", ["occupancy", "occ type", "occupancy status"], codes=["P", "S", "I"]),
    _a("documentation_type", "LOAN", "code", 3, False, "low", ["doc type", "documentation level"], codes=["FUL", "ALT", "STD", "NDC"]),
    _a("channel", "LOAN", "code", 3, False, "low", ["origination channel", "orig channel", "source channel"], codes=["RET", "COR", "BRK"]),
    _a("delinquency_status", "LOAN", "code", 3, False, "medium", ["dlq status", "delinquency", "days delinquent bucket", "mba status"], codes=["CUR", "30", "60", "90", "120", "FCL", "BK", "REO"]),
    _a("days_delinquent", "LOAN", "int", 4, False, "medium", ["dpd", "days past due", "days delq"]),
    _a("prepayment_penalty_flag", "LOAN", "bool", None, False, "low", ["prepay penalty", "ppp flag", "prepayment penalty"]),
    _a("interest_only_flag", "LOAN", "bool", None, False, "medium", ["io flag", "interest only", "io indicator"]),
    _a("balloon_flag", "LOAN", "bool", None, False, "low", ["balloon", "balloon indicator"]),
    _a("arm_index", "LOAN", "code", 6, False, "medium", ["index", "arm index type", "rate index"], codes=["SOFR", "CMT1Y", "LIBOR", "PRIME"]),
    _a("arm_margin", "LOAN", "decimal", None, False, "high", ["margin", "gross margin", "arm margin rate"]),
    _a("arm_next_rate_change_date", "LOAN", "date", None, False, "medium", ["next rate change", "rate reset date", "next adj date"]),
    _a("arm_lifetime_cap", "LOAN", "decimal", None, False, "medium", ["life cap", "lifetime cap", "max rate"]),
    _a("arm_periodic_cap", "LOAN", "decimal", None, False, "medium", ["periodic cap", "adj cap", "subsequent cap"]),
    _a("mi_coverage_pct", "LOAN", "decimal", None, False, "medium", ["mi coverage", "mortgage insurance pct", "pmi coverage"]),
    _a("mi_company", "LOAN", "string", 40, False, "low", ["mi provider", "pmi company", "mortgage insurer"]),
    _a("mi_certificate_number", "LOAN", "string", 20, False, "low", ["mi cert", "pmi cert number"]),
    _a("fha_case_number", "LOAN", "string", 15, False, "medium", ["fha case no", "agency case number", "case number"]),
    _a("va_guaranty_pct", "LOAN", "decimal", None, False, "medium", ["va guaranty", "va guarantee percent"]),
    _a("late_charge_pct", "LOAN", "decimal", None, False, "low", ["late fee pct", "late charge percent", "late charge rate"]),
    _a("late_charge_grace_days", "LOAN", "int", 2, False, "low", ["grace days", "grace period", "late grace"]),
    _a("hmda_rate_spread", "LOAN", "decimal", None, False, "high", ["rate spread", "hmda spread", "apr spread"]),
    _a("hmda_hoepa_status", "LOAN", "code", 1, False, "high", ["hoepa", "hoepa status", "high cost flag"], codes=["1", "2", "3"]),
    _a("apr", "LOAN", "decimal", None, False, "high", ["annual percentage rate", "apr rate"]),
    # ---------------- BORROWER ----------------
    _a("borrower_first_name", "BORROWER", "string", 40, True, "high", ["first name", "brw first name", "b1 first", "primary first name", "fname"], pii=True),
    _a("borrower_middle_name", "BORROWER", "string", 40, False, "low", ["middle name", "brw middle", "mname"], pii=True),
    _a("borrower_last_name", "BORROWER", "string", 60, True, "high", ["last name", "surname", "brw last name", "b1 last", "lname"], pii=True),
    _a("borrower_ssn", "BORROWER", "string", 9, True, "high", ["ssn", "social security", "tax id", "tin", "brw ssn", "social security number"], pii=True),
    _a("borrower_dob", "BORROWER", "date", None, False, "high", ["date of birth", "dob", "birth date", "brw dob"], pii=True),
    _a("borrower_email", "BORROWER", "string", 100, False, "medium", ["email", "email address", "e-mail", "brw email"], pii=True),
    _a("borrower_home_phone", "BORROWER", "string", 10, False, "medium", ["home phone", "phone", "phone number", "primary phone"], pii=True),
    _a("borrower_cell_phone", "BORROWER", "string", 10, False, "medium", ["cell phone", "mobile", "mobile phone"], pii=True),
    _a("borrower_fico", "BORROWER", "int", 3, False, "high", ["fico", "credit score", "fico score", "orig fico", "brw fico"]),
    _a("borrower_language_pref", "BORROWER", "code", 2, False, "low", ["language", "preferred language", "lang"], codes=["EN", "ES", "ZH", "VI", "KO", "TL"]),
    _a("coborrower_first_name", "BORROWER", "string", 40, False, "medium", ["co borrower first name", "cb first name", "b2 first"], pii=True),
    _a("coborrower_last_name", "BORROWER", "string", 60, False, "medium", ["co borrower last name", "cb last name", "b2 last"], pii=True),
    _a("coborrower_ssn", "BORROWER", "string", 9, False, "high", ["co borrower ssn", "cb ssn", "b2 ssn"], pii=True),
    _a("coborrower_fico", "BORROWER", "int", 3, False, "high", ["co borrower fico", "cb fico"]),
    _a("mailing_address_line1", "BORROWER", "string", 100, True, "medium", ["mailing address", "mail addr", "mail address 1", "borrower address"], pii=True),
    _a("mailing_address_line2", "BORROWER", "string", 100, False, "low", ["mail address 2", "mail addr2", "mailing unit"], pii=True),
    _a("mailing_city", "BORROWER", "string", 40, True, "medium", ["mail city", "mailing city name"]),
    _a("mailing_state", "BORROWER", "code", 2, True, "low", ["mail state", "mailing st"], codes=US_STATES),
    _a("mailing_zip", "BORROWER", "string", 9, True, "low", ["mail zip", "mailing zip code", "mail postal"]),
    _a("military_status_flag", "BORROWER", "bool", None, False, "high", ["scra", "military", "servicemember flag", "active duty"]),
    _a("bankruptcy_flag", "BORROWER", "bool", None, False, "high", ["bk flag", "in bankruptcy", "bankruptcy indicator"]),
    _a("ofac_check_status", "BORROWER", "code", 1, False, "critical", ["ofac", "ofac status", "sanctions screen"], codes=["C", "H", "P"]),
    _a("fraud_alert_flag", "BORROWER", "bool", None, False, "critical", ["fraud flag", "fraud alert", "fraud indicator"]),
    # ---------------- PROPERTY ----------------
    _a("property_address_line1", "PROPERTY", "string", 100, True, "medium", ["property address", "prop addr", "subject address", "property street", "collateral address"], pii=True),
    _a("property_address_line2", "PROPERTY", "string", 100, False, "low", ["prop addr2", "property unit", "unit"], pii=True),
    _a("property_city", "PROPERTY", "string", 40, True, "medium", ["prop city", "subject city", "city"]),
    _a("property_state", "PROPERTY", "code", 2, True, "medium", ["prop state", "subject state", "state", "st"], codes=US_STATES),
    _a("property_zip", "PROPERTY", "string", 9, True, "medium", ["prop zip", "zip", "zip code", "postal code", "subject zip"]),
    _a("property_county", "PROPERTY", "string", 40, False, "low", ["county", "prop county", "county name"]),
    _a("property_fips_code", "PROPERTY", "string", 5, False, "high", ["fips", "fips code", "county fips"]),
    _a("property_census_tract", "PROPERTY", "string", 11, False, "high", ["census tract", "tract"]),
    _a("property_type", "PROPERTY", "code", 3, True, "medium", ["prop type", "dwelling type", "property kind"], codes=["SFR", "CON", "PUD", "MFR", "MAN", "COP"]),
    _a("number_of_units", "PROPERTY", "int", 1, True, "medium", ["units", "unit count", "no of units", "num units"]),
    _a("appraised_value", "PROPERTY", "decimal", None, True, "high", ["appraisal value", "orig appraised value", "property value", "appraisal amt"]),
    _a("sales_price", "PROPERTY", "decimal", None, False, "medium", ["purchase price", "sale price", "contract price"]),
    _a("year_built", "PROPERTY", "int", 4, False, "low", ["yr built", "construction year"]),
    _a("flood_zone", "PROPERTY", "string", 4, False, "medium", ["flood zone code", "fema zone", "flood"]),
    _a("flood_insurance_required", "PROPERTY", "bool", None, False, "medium", ["flood ins required", "flood required"]),
    _a("hoa_flag", "PROPERTY", "bool", None, False, "low", ["hoa", "homeowners association", "has hoa"]),
    # ---------------- ESCROW ----------------
    _a("escrow_flag", "ESCROW", "bool", None, True, "medium", ["escrowed", "escrow indicator", "impound flag", "escrow waived inverse"]),
    _a("escrow_balance", "ESCROW", "decimal", None, False, "medium", ["escrow bal", "impound balance", "esc balance"]),
    _a("escrow_payment", "ESCROW", "decimal", None, False, "medium", ["escrow pmt", "monthly escrow", "t&i", "ti payment"]),
    _a("tax_annual_amount", "ESCROW", "decimal", None, False, "low", ["annual taxes", "tax amount", "property tax"]),
    _a("tax_next_due_date", "ESCROW", "date", None, False, "low", ["tax due date", "next tax due"]),
    _a("hazard_insurance_annual_premium", "ESCROW", "decimal", None, False, "low", ["hazard premium", "hoi premium", "insurance premium"]),
    _a("hazard_insurance_carrier", "ESCROW", "string", 60, False, "low", ["insurance company", "hoi carrier", "hazard carrier"]),
    _a("hazard_policy_number", "ESCROW", "string", 30, False, "low", ["policy number", "hoi policy", "insurance policy no"]),
    _a("hazard_policy_expiration_date", "ESCROW", "date", None, False, "low", ["policy expiration", "hoi exp date"]),
    _a("flood_insurance_annual_premium", "ESCROW", "decimal", None, False, "low", ["flood premium"]),
    _a("mi_monthly_premium", "ESCROW", "decimal", None, False, "low", ["mi premium", "pmi payment", "mi monthly"]),
    _a("suspense_balance", "ESCROW", "decimal", None, False, "medium", ["suspense", "unapplied funds", "suspense bal"]),
    _a("restricted_escrow_balance", "ESCROW", "decimal", None, False, "low", ["restricted escrow", "restricted funds"]),
    # ---------------- INVESTOR ----------------
    _a("investor_code", "INVESTOR", "string", 6, True, "medium", ["investor", "investor id", "inv code", "investor number"]),
    _a("investor_category", "INVESTOR", "code", 5, True, "medium", ["investor type", "inv category", "agency"], codes=["FNMA", "FHLMC", "GNMA", "PVT", "PORT"]),
    _a("pool_number", "INVESTOR", "string", 12, False, "medium", ["pool", "pool id", "pool no"]),
    _a("investor_loan_number", "INVESTOR", "string", 20, False, "medium", ["investor loan id", "inv loan no", "agency loan number"]),
    _a("servicing_fee_rate", "INVESTOR", "decimal", None, True, "high", ["service fee", "servicing fee", "svc fee rate", "sf rate"]),
    _a("guaranty_fee_rate", "INVESTOR", "decimal", None, False, "medium", ["g fee", "guarantee fee", "gfee"]),
    _a("pass_through_rate", "INVESTOR", "decimal", None, False, "high", ["net rate", "pass thru rate", "investor rate"]),
    _a("remittance_type", "INVESTOR", "code", 3, False, "medium", ["remit type", "remittance", "reporting type"], codes=["AA", "SS", "SA"]),
    _a("transfer_effective_date", "INVESTOR", "date", None, True, "medium", ["transfer date", "boarding date", "servicing transfer date", "sale date", "effective date"]),
    _a("prior_servicer_name", "INVESTOR", "string", 60, False, "low", ["prior servicer", "seller name", "transferor", "previous servicer"]),
    _a("source_system", "INVESTOR", "code", 4, False, "low", ["source", "boarding source", "acquisition channel"], codes=["PCGR", "BULK", "SUBS", "CORR"]),
]

BY_NAME: dict[str, TargetAttribute] = {a.name: a for a in ATTRIBUTES}


def validate_schema() -> list[str]:
    """Self-consistency of the target dictionary (run at import and in CI)."""
    problems = []
    if len(BY_NAME) != len(ATTRIBUTES):
        problems.append("duplicate attribute names")
    for a in ATTRIBUTES:
        if a.module not in MODULES:
            problems.append(f"{a.name}: unknown module {a.module}")
        if a.risk not in ("low", "medium", "high", "critical"):
            problems.append(f"{a.name}: bad risk {a.risk}")
        if a.codes and a.length and max(len(c) for c in a.codes) > a.length:
            problems.append(f"{a.name}: code '{max(a.codes, key=len)}' longer than column length {a.length}")
        if a.dtype in ("string", "code") and not a.length:
            problems.append(f"{a.name}: string/code attribute needs a length")
    return problems


_problems = validate_schema()
if _problems:
    raise RuntimeError("SSE schema invalid: " + "; ".join(_problems))


def attributes_for(module: str) -> list[TargetAttribute]:
    return [a for a in ATTRIBUTES if a.module == module]


def risk_of(field_name: str) -> str:
    attr = BY_NAME.get(field_name)
    return attr.risk if attr else "medium"


def as_dicts() -> list[dict]:
    return [
        {
            "name": a.name, "module": a.module, "dtype": a.dtype, "length": a.length, "required": a.required,
            "risk": a.risk, "synonyms": list(a.synonyms), "description": a.description, "codes": list(a.codes), "pii": a.pii,
        }
        for a in ATTRIBUTES
    ]
