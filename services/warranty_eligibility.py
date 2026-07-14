"""Central warranty eligibility rules based on company dispatch date."""

from datetime import datetime

WARRANTY_COMPANY_BILL_CUTOFF = datetime(2025, 4, 1)
INELIGIBLE_MESSAGE = (
    "This product is not eligible for online warranty registration because its "
    "company bill date is before April 1, 2025. You can still raise an enquiry "
    "and the Safrina team will handle it manually."
)


def is_warranty_eligible(product: dict) -> bool:
    bill_date = product.get("bill_date")
    return bool(bill_date and bill_date >= WARRANTY_COMPANY_BILL_CUTOFF)
