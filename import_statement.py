"""
PDF Import Script for 'Am I Cooked?'
Extracts transactions from GPay PDF statements and logs them to the DB.
"""
import os
import re
from datetime import datetime
from pypdf import PdfReader

import db

# Set the DB URL for the script
os.environ["DATABASE_URL"] = os.getenv("DATABASE_URL")

PDF_PATH = "gpay_statement_20260801_20260831.pdf"

def parse_statement():
    if not os.path.exists(PDF_PATH):
        print(f"Error: {PDF_PATH} not found.")
        return

    print(f"Reading {PDF_PATH}...")
    reader = PdfReader(PDF_PATH)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"

    # The PDF layout is multi-line. We need to find the date, then search until we find an amount.
    # Example:
    # 02Aug,2026
    # 03:18PM
    # PaidtoCHANGEPAYMMSTECHNOLOGIESPRIVATELIMITED
    # UPITransactionID:621452590547
    # PaidbyICICIBank1191
    # ₹105

    # Split by date pattern to isolate transaction blocks
    blocks = re.split(r"(\d{2}[A-Za-z]{3},\d{4})", text)

    db.init_db()
    count = 0

    # blocks[0] is header, then blocks[1] is date, blocks[2] is content...
    for i in range(1, len(blocks), 2):
        date_str = blocks[i]
        content = blocks[i+1] if i+1 < len(blocks) else ""

        # Find the amount (₹ followed by digits)
        amt_match = re.search(r"₹([\d,.]+)", content)
        if not amt_match:
            continue

        amount = float(amt_match.group(1).replace(",", ""))

        # Determine direction and merchant
        direction = "debit"
        merchant = "Unknown"

        if "Receivedfrom" in content:
            direction = "credit"
            # Extract merchant between 'Receivedfrom' and the next field (usually UPITransactionID)
            m_match = re.search(r"Receivedfrom(.*?)(?=UPITransactionID|$)", content, re.DOTALL)
            if m_match:
                merchant = m_match.group(1).strip()
        elif "Paidto" in content:
            direction = "debit"
            # Extract merchant between 'Paidto' and the next field
            m_match = re.search(r"Paidto(.*?)(?=UPITransactionID|$)", content, re.DOTALL)
            if m_match:
                merchant = m_match.group(1).strip()

        # Extract UPI Ref if available
        upi_ref = None
        upi_match = re.search(r"UPITransactionID:(\d+)", content)
        if upi_match:
            upi_ref = upi_match.group(1)

        try:
            dt = datetime.strptime(date_str, "%d%b,%Y").date()
        except ValueError:
            continue

        if db.add_transaction(dt, merchant, amount, direction=direction, upi_ref=upi_ref):
            count += 1

    print(f"Successfully imported {count} unique transactions.")

if __name__ == "__main__":
    parse_statement()
