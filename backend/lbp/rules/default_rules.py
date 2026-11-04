"""Starter SSE business rule set (22 rules) expressed as JSON Logic.

These replace a representative slice of the ~100 T-SQL stored-procedure rules invoked by
Hangfire today. Expression semantics: evaluates truthy => PASS. Each rule carries owner,
effective_from, regulatory_tag and embedded test cases, so it can't be activated without
its tests passing.
"""
from __future__ import annotations

V = lambda f, d=None: {"var": f} if d is None else {"var": [f, d]}  # noqa: E731

BASE_LOAN = {
    "loan_number": "PCG00000001", "borrower_first_name": "Maria", "borrower_last_name": "Garcia", "borrower_ssn": "123456789",
    "property_address_line1": "12 Oak St", "property_state": "CA", "property_zip": "91361", "interest_rate": 6.5,
    "original_term_months": 360, "original_loan_amount": 400000.0, "current_principal_balance": 395000.0,
    "note_date": "2024-01-15", "first_payment_date": "2024-03-01", "maturity_date": "2054-02-01",
    "next_payment_due_date": "2026-12-01", "principal_interest_payment": 2528.27, "borrower_fico": 740, "ltv_ratio": 80.0,
    "dti_ratio": 36.0, "occupancy_type": "P", "loan_type": "CNV", "investor_category": "FNMA", "escrow_flag": True,
    "escrow_balance": 1500.0, "ofac_check_status": "C", "fraud_alert_flag": False, "servicing_fee_rate": 0.25,
    "transfer_effective_date": "2026-11-01", "property_type": "SFR", "number_of_units": 1, "lien_position": 1,
}


def t(overrides: dict, expect: bool) -> dict:
    return {"record": {**BASE_LOAN, **overrides}, "expect": expect}


def _r(rule_id, name, description, expr, field, category, severity="FAIL", reg=None, owner="loan-boarding-sme", tests=None, message=None):
    return {
        "rule_id": rule_id, "name": name, "description": description, "expression": expr, "field": field,
        "fields": sorted({field} | set()), "category": category, "severity": severity, "regulatory_tag": reg,
        "owner": owner, "effective_from": "2026-11-01", "message": message or name,
        "tests": tests or [t({}, True)],
    }


DEFAULT_RULES = [
    _r("R001", "Loan number present and well-formed", "Loan number is required, 6-20 alphanumeric characters.",
       {"matches": [V("loan_number"), "[A-Z0-9-]{6,20}"]}, "loan_number", "completeness", reg="SOX",
       tests=[t({}, True), t({"loan_number": ""}, False), t({"loan_number": "ab"}, False)]),
    _r("R002", "Borrower last name required", "Primary borrower last name must be populated.",
       {"!": {"is_blank": V("borrower_last_name")}}, "borrower_last_name", "completeness", reg="GLBA",
       tests=[t({}, True), t({"borrower_last_name": ""}, False)]),
    _r("R003", "Borrower first name required", "Primary borrower first name must be populated.",
       {"!": {"is_blank": V("borrower_first_name")}}, "borrower_first_name", "completeness",
       tests=[t({}, True), t({"borrower_first_name": None}, False)]),
    _r("R004", "Borrower SSN valid", "SSN required, 9 digits, not 000/666/9xx area.",
       {"matches": [V("borrower_ssn"), "(?!000|666|9)\\d{3}(?!00)\\d{2}(?!0000)\\d{4}"]}, "borrower_ssn", "format", reg="GLBA",
       tests=[t({}, True), t({"borrower_ssn": ""}, False), t({"borrower_ssn": "000123456"}, False)]),
    _r("R005", "Property state is a valid USPS code", "Property state must be a valid 2-letter USPS code.",
       {"in_codes": [V("property_state"), "property_state"]}, "property_state", "format", reg="HMDA",
       tests=[t({}, True), t({"property_state": "XX"}, False), t({"property_state": ""}, False)]),
    _r("R006", "Property ZIP is 5 or 9 digits", "Property ZIP must be 5 digits (or ZIP+4).",
       {"matches": [V("property_zip"), "\\d{5}(\\d{4})?"]}, "property_zip", "format", reg="HMDA",
       tests=[t({}, True), t({"property_zip": "913"}, False)]),
    _r("R007", "Interest rate within range", "Note rate must be between 0.5% and 15%.",
       {"<=": [0.5, V("interest_rate"), 15]}, "interest_rate", "range", reg="TILA",
       tests=[t({}, True), t({"interest_rate": 65.0}, False), t({"interest_rate": None}, False)]),
    _r("R008", "Original term valid", "Original term must be between 60 and 480 months.",
       {"<=": [60, V("original_term_months"), 480]}, "original_term_months", "range",
       tests=[t({}, True), t({"original_term_months": 1000}, False)]),
    _r("R009", "UPB not greater than original amount", "Current UPB must not exceed original loan amount (+5% for neg-am tolerance).",
       {"<=": [V("current_principal_balance"), {"*": [V("original_loan_amount"), 1.05]}]}, "current_principal_balance", "consistency",
       tests=[t({}, True), t({"current_principal_balance": 500000.0}, False)]),
    _r("R010", "Maturity after note date", "Maturity date must be after note date.",
       {">": [{"days_between": [V("note_date"), V("maturity_date")]}, 0]}, "maturity_date", "consistency",
       tests=[t({}, True), t({"maturity_date": "2023-12-01"}, False)]),
    _r("R011", "First payment after note date", "First payment date must be 1-125 days after note date.",
       {"<=": [1, {"days_between": [V("note_date"), V("first_payment_date")]}, 125]}, "first_payment_date", "consistency",
       tests=[t({}, True), t({"first_payment_date": "2023-01-01"}, False)]),
    _r("R012", "FICO within range", "Borrower FICO, when present, must be between 300 and 850.",
       {"or": [{"is_blank": V("borrower_fico")}, {"<=": [300, V("borrower_fico"), 850]}]}, "borrower_fico", "range", reg="ECOA",
       tests=[t({}, True), t({"borrower_fico": 7400}, False), t({"borrower_fico": 0}, False), t({"borrower_fico": None}, True)]),
    _r("R013", "LTV within range", "LTV must be between 1 and 125.",
       {"<=": [1, V("ltv_ratio"), 125]}, "ltv_ratio", "range",
       tests=[t({}, True), t({"ltv_ratio": 180}, False)]),
    _r("R014", "High LTV warning", "LTV above 97% requires MI verification.",
       {"<=": [V("ltv_ratio"), 97]}, "ltv_ratio", "risk", severity="WARN",
       tests=[t({}, True), t({"ltv_ratio": 98.5}, False)]),
    _r("R015", "DTI above guideline", "DTI above 50% flagged for review.",
       {"or": [{"is_blank": V("dti_ratio")}, {"<=": [V("dti_ratio"), 50]}]}, "dti_ratio", "risk", severity="WARN", reg="ATR/QM",
       tests=[t({}, True), t({"dti_ratio": 55}, False)]),
    _r("R016", "Occupancy code valid", "Occupancy must be P, S or I.",
       {"in": [V("occupancy_type"), ["P", "S", "I"]]}, "occupancy_type", "format", reg="HMDA",
       tests=[t({}, True), t({"occupancy_type": "OWNER"}, False)]),
    _r("R017", "Government loan investor consistency", "FHA/VA/USDA loans should be GNMA investor.",
       {"if": [{"in": [V("loan_type"), ["FHA", "VA", "USDA"]]}, {"==": [V("investor_category"), "GNMA"]}, True]},
       "investor_category", "consistency", severity="WARN",
       tests=[t({}, True), t({"loan_type": "FHA", "investor_category": "FNMA"}, False)]),
    _r("R018", "Escrow balance non-negative", "Escrowed loans cannot carry a negative escrow balance.",
       {"if": [V("escrow_flag"), {">=": [V("escrow_balance", 0), 0]}, True]}, "escrow_balance", "range", severity="WARN", reg="RESPA",
       tests=[t({}, True), t({"escrow_balance": -10.0}, False)]),
    _r("R019", "OFAC screening clear", "Borrower must have a clear OFAC screening result.",
       {"==": [V("ofac_check_status"), "C"]}, "ofac_check_status", "compliance", reg="OFAC", owner="compliance",
       tests=[t({}, True), t({"ofac_check_status": "H"}, False)]),
    _r("R020", "No fraud alert", "Loans with an active fraud alert cannot be boarded.",
       {"!": V("fraud_alert_flag")}, "fraud_alert_flag", "fraud", reg="BSA/AML", owner="compliance",
       tests=[t({}, True), t({"fraud_alert_flag": True}, False)]),
    _r("R021", "P&I payment matches amortization", "P&I within 2% of amortized payment from original terms (fixed-rate).",
       {"if": [{"==": [V("amortization_type"), "ARM"]}, True,
               {"<=": [{"abs": {"-": [V("principal_interest_payment"),
                                       {"pmt": [V("interest_rate"), V("original_term_months"), V("original_loan_amount")]}]}},
                       {"*": [{"pmt": [V("interest_rate"), V("original_term_months"), V("original_loan_amount")]}, 0.02]}]}]},
       "principal_interest_payment", "consistency", severity="WARN", reg="TILA",
       tests=[t({}, True), t({"principal_interest_payment": 4000.0}, False)]),
    _r("R022", "Servicing fee within range", "Servicing fee rate must be between 0 and 1%.",
       {"<=": [0, V("servicing_fee_rate"), 1]}, "servicing_fee_rate", "range",
       tests=[t({}, True), t({"servicing_fee_rate": 25}, False)]),
]
