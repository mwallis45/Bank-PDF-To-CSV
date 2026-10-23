import pdfplumber
import pandas as pd
import re
import numpy as np
from datetime import datetime
from ast import parse


def identify_bank(first_page_text: str) -> str:
    """Inspects text from page 1 to determine the issuing bank."""
    text_lower = first_page_text.lower()

    if "lloyds bank" in text_lower or "llyods" in text_lower:
        return "LLOYDS"
    elif "barclays" in text_lower:
        return "BARCLAYS"
    elif "hsbc" in text_lower:
        return "HSBC"
    elif "natwest" in text_lower:
        return "NATWEST"
    elif "monzo" in text_lower:
        return "MONZO"
    else:
        return "UNKNOWN"


def fix_shifted_chars(text: str) -> str:
    """
    Fixes PDF OCR artifacts where the first character of a word 
    is shifted to the second position of the preceding word.
    
    Example: 
    'CDolumn ate' -> 'Column Date'
    'D0ate 2' -> 'Date 02'
    'DBescription OOTS' -> 'Description BOOTS'
    """
    # Group 1: The true first letter of Word 1 (Uppercase)
    # Group 2: The displaced first letter/digit of Word 2
    # Group 3: The rest of Word 1 (Lowercase letters)
    # Group 4: The visible remainder of Word 2
    pattern = re.compile(r'\b([A-Z])([A-Z0-9])([a-z]{2,})\s+([A-Za-z0-9]+)\b')
    
    # Rearrange the groups to put the displaced character back on Word 2
    return pattern.sub(r'\1\3 \2\4', text)
    

def fix_monzo_split_lines(lines: list) -> list:
    """
    Fixes Monzo PDF formatting where the first half of a description 
    appears on the line above a date-only transaction line.
    """
    fixed_lines = []
    
    # Matches a line that starts with a date and is followed ONLY by amounts (no text)
    # e.g., "20/09/2026 3.00 103.00"
    date_only_pattern = re.compile(r'^\d{2}/\d{2}/\d{4}(?:\s+-?[\d,]+\.\d{2})+$')
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Check if we have a next line to look at
        if i + 1 < len(lines):
            next_line = lines[i+1]
            
            # If the next line is Date + Amounts ONLY, and current line is NOT a date line
            if date_only_pattern.match(next_line) and not re.match(r'^\d{2}/\d{2}/\d{4}', line):
                # Swap them: emit the Date line first, then the text line
                fixed_lines.append(next_line)
                fixed_lines.append(line)
                i += 2
                continue
                
        # Otherwise, keep the line in its original place
        fixed_lines.append(line)
        i += 1
        
    return fixed_lines

def pre_process_barclays_lines(lines: list) -> list:
    """
    Combines broken Barclays transaction lines and trailing date fragments
    without merging distinct transactions together.
    """
    fixed_lines = []
    line_date_pattern = re.compile(r'^(\d{2}\s+[A-Za-z]{3})\b')
    date_only_pattern = re.compile(r'^\d{2}\s+[A-Za-z]{3}$')
    amount_pattern = re.compile(r'[\d,]+\.\d{2}')

    # Word-boundary regex matching transaction starters anywhere near line start
    tx_start_pattern = re.compile(
        r'^\s*(Card Payment|Direct Debit|Standing Order|Faster Payment|Received From|Transfer|ATM|Commission)\b', 
        re.IGNORECASE
    )

    current_date = None

    for raw_line in lines:
        line_str = re.sub(r'\s+', ' ', raw_line).strip()
        if not line_str:
            continue

        # Track active date (e.g. "20 May")
        m = line_date_pattern.match(line_str)
        if m:
            current_date = m.group(1)

        # -------------------------------------------------------------
        # CHECK 1: Date fragment line (e.g., "19 May")
        # -------------------------------------------------------------
        if date_only_pattern.match(line_str) and fixed_lines:
            prev_line = fixed_lines[-1]
            amounts = amount_pattern.findall(prev_line)

            if amounts:
                first_amt_idx = prev_line.find(amounts[0])
                merged = f"{prev_line[:first_amt_idx].strip()} {line_str} {prev_line[first_amt_idx:].strip()}"
                fixed_lines[-1] = merged
            else:
                fixed_lines[-1] = f"{prev_line} {line_str}"
            continue

        # -------------------------------------------------------------
        # CHECK 2: Distinct transaction without explicit line-start date
        # (e.g., "Card Payment to Amznmktplace On 12.94 1,284.75")
        # -------------------------------------------------------------
        is_tx_start = bool(tx_start_pattern.search(line_str))

        if not m and is_tx_start and current_date:
            # Prepend active date so it stands as an independent transaction row
            line_str = f"{current_date} {line_str}"
            fixed_lines.append(line_str)
            continue

        # -------------------------------------------------------------
        # CHECK 3: Text continuation line (e.g., "Ireland On 17 May", "Ref: Grandma")
        # -------------------------------------------------------------
        is_summary = any(skip in line_str for skip in ["Start balance", "End balance", "Statement date"])
        
        if not m and not is_tx_start and not is_summary and fixed_lines:
            prev_line = fixed_lines[-1]
            prev_amounts = amount_pattern.findall(prev_line)

            if prev_amounts:
                first_amt_idx = prev_line.find(prev_amounts[0])
                merged = f"{prev_line[:first_amt_idx].strip()} {line_str} {prev_line[first_amt_idx:].strip()}"
                fixed_lines[-1] = merged
            else:
                fixed_lines[-1] = f"{prev_line} {line_str}"
            continue

        # Standalone transaction or summary line
        fixed_lines.append(line_str)

    return fixed_lines

def example_parser(pdf) -> list:
    parsed_rows = []

    # Matching inline dates like "15 Mar" or "15 Mar 2024"
    date_pattern = re.compile(r'\b(\d{1,2}\s+[A-Za-z]{3}(?:\s+\d{2,4})?)\b')
    amount_pattern = re.compile(r'([\d,]+\.\d{2})')

    # Regex to capture statement period/date headers like "Statement Date: 15 Mar 2024" or "Date: 2024-03-15"
    statement_date_pattern = re.compile(
        r'(?:statement\s+date|date of statement|period ending|date)\s*:?\s*(\d{1,2}\s+[A-Za-z]{3}\s+\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})',
        re.IGNORECASE
    )

    # Step 1: Extract Statement Date (and target fallback year)
    statement_year = None
    statement_date_str = None

    for page in pdf.pages:
        text = page.extract_text() or ""
        stmt_match = statement_date_pattern.search(text)
        if stmt_match:
            statement_date_str = stmt_match.group(1)
            # Find a 4-digit year in the captured statement date string
            year_match = re.search(r'\b(20\d{2}|19\d{2})\b', statement_date_str)
            if year_match:
                statement_year = year_match.group(1)
            break  # Found the statement date, stop searching headers

    # Step 2: Main Transaction Parsing Loop
    for page in pdf.pages:
        text = page.extract_text() or ""
        lines = [line.strip() for line in text.split('\n') if line.strip()]

        current_tx = None  # Buffer for holding multi-line data

        for line in lines:
            # Skip obvious headers/footers
            if "Page " in line or "Balance Carried Forward" in line:
                continue

            date_match = date_pattern.search(line)

            if date_match:
                # Flush the PREVIOUS transaction before starting a new one
                if current_tx:
                    parsed_rows.append(current_tx)

                # Initialize new transaction row
                date_str = date_match.group(1)

                # Check if date_str is missing a year (e.g. "15 Mar") and apply fallback
                has_year = re.search(r'\b\d{2,4}\b', date_str)
                if not has_year and statement_year:
                    date_str = f"{date_str} {statement_year}"

                desc_str = line  # Raw line text

                amounts = amount_pattern.findall(line)
                money_in = amounts[0] if "Credit" in line and amounts else ""
                money_out = amounts[0] if "Credit" not in line and amounts else ""
                balance = amounts[-1] if len(amounts) > 1 else ""

                current_tx = [date_str, desc_str, money_in, money_out, balance]

            elif current_tx:
                # Handle continuation lines
                current_tx[1] += f" {line}"

                extra_amounts = amount_pattern.findall(line)
                if extra_amounts and not current_tx[4]:
                    current_tx[4] = extra_amounts[-1]

        # Flush final transaction of the page
        if current_tx:
            parsed_rows.append(current_tx)

    # Step 3: Clean up descriptions
    for row in parsed_rows:
        row[1] = date_pattern.sub('', row[1])
        row[1] = amount_pattern.sub('', row[1])
        row[1] = re.sub(r'\s+', ' ', row[1]).strip()

    return parsed_rows


def parse_monzo(pdf) -> list:
    """
    Parses Monzo bank statement PDFs.

    Quirks handled:
    - Signed amounts in a single column (-amount = money_out, +/unsigned = money_in)
    - Multi-line description strings spanning above or below the transaction line
    - Headers/Footers containing registration metadata or Pot totals
    """
    parsed_rows = []

    # Matches DD/MM/YYYY
    date_pattern = re.compile(r'^\b(\d{2}/\d{2}/\d{4})\b')
    # Matches optional negative sign followed by float/decimal amount
    amount_pattern = re.compile(r'(-?[\d,]+\.\d{2})')

    for page in pdf.pages:
        text = page.extract_text() or ""
        lines = [line.strip() for line in text.split('\n') if line.strip()]

        lines = fix_monzo_split_lines(lines)

        current_tx = None

        for line in lines:
            # Skip header, footer, registration, and summary info
            if any(skip in line for skip in [
                "Personal Account", "Total balance", "Sort code:", "Account number:",
                "Date Description", "Monzo Bank Limited", "Registered Office",
                "Total outgoings", "Total deposits", "Balance in Pots", "https://monzo.com",
                "Pot statement", "Register number is 730427", "Monzo Bank Ltd is authorised",
                "Pot balance", "Pot name", "Regular Pot provided by Monzo", "Pot type",
                "no transactions during this period"
            ]):
                continue

            date_match = date_pattern.match(line)

            if date_match:
                # Flush existing transaction
                if current_tx:
                    parsed_rows.append(current_tx)

                raw_date = date_match.group(1)
                
                # Standardize date format to YYYY-MM-DD (adjust format if needed)
                try:
                    formatted_date = datetime.strptime(raw_date, "%d/%m/%Y").strftime("%d %b %Y")
                except ValueError:
                    formatted_date = raw_date
                
                remainder = line[date_match.end():].strip()

                # Extract all numeric values (Amount and Balance)
                amounts = amount_pattern.findall(remainder)

                money_in, money_out, balance = "", "", ""

                if len(amounts) >= 2:
                    raw_amount = amounts[-2]
                    balance = amounts[-1]
                elif len(amounts) == 1:
                    raw_amount = amounts[0]
                else:
                    raw_amount = None

                if raw_amount:
                    if raw_amount.startswith('-'):
                        money_out = raw_amount.replace('-', '')
                    else:
                        money_in = raw_amount.replace('+', '')

                # Initial description line with amounts stripped out
                desc_str = remainder
                for amt in amounts:
                    desc_str = desc_str.replace(amt, '')
                desc_str = re.sub(r'\s+', ' ', desc_str).strip()

                current_tx = [formatted_date, desc_str, money_in, money_out, balance]

            elif current_tx:
                # Append description continuation lines
                # Skip standalone amount lines or extraneous footers
                if not re.match(r'^-?[\d,]+\.\d{2}$', line):
                    current_tx[1] += f" {line}"

        if current_tx:
            parsed_rows.append(current_tx)

    # Post-process cleanup
    for row in parsed_rows:
        row[1] = re.sub(r'\s+', ' ', row[1]).strip()

    return parsed_rows


# ==============================================================================
# 2. LLOYDS BANK PARSER
# ==============================================================================
def parse_lloyds(pdf) -> list:
    """
    Parses Lloyds bank statement PDFs.

    Quirks handled:
    - Text prefixes/OCR artifacts ("D0ate", "D2ate", "DBescription", "TDype", "Moneyb Ilna n(k£.)")
    - 2-digit years ("2 Jan 20" -> "02 Jan 2020") derived from statement period header
    - jammed text and labels surrounding transaction values
    """
    parsed_rows = []

    # Matches year range in statement header: "01 January 2020 to 31 January 2020"
    header_year_pattern = re.compile(r'\b\d{1,2}\s+[A-Za-z]+\s+(20\d{2})\b')

    # Matches Lloyds prefix date formats e.g. "D0ate 2 Jan 20" or "D2ate 27 Jan 20"
    date_pattern = re.compile(r'D\d?ate\s+(\d{1,2}\s+[A-Za-z]{3}\s+(\d{2}))', re.IGNORECASE)
    amount_pattern = re.compile(r'([\d,]+\.\d{2})')

    statement_year = None

    # Step 1: Detect 4-digit target year from document header
    for page in pdf.pages:
        text = page.extract_text() or ""
        year_match = header_year_pattern.search(text)
        if year_match:
            statement_year = year_match.group(1)
            break

    # Step 2: Extract transactions
    for page in pdf.pages:
        text = page.extract_text() or ""
        lines = [line.strip() for line in text.split('\n') if line.strip()]

        for line in lines:
            line = fix_shifted_chars(line)

            date_match = date_pattern.search(line)
            if not date_match:
                continue

            raw_date = date_match.group(1) # e.g. "2 Jan 20"
            yy = date_match.group(2)       # e.g. "20"

            # Format 4-digit year
            full_year = f"20{yy}" if statement_year is None else statement_year
            formatted_date = re.sub(r'\b\d{2}\b$', full_year, raw_date)

            # Extract Description between "DBescription"/"DTescription" and "TDype"/"TCype"
            desc_match = re.search(r'D[a-z]?escription\s+(.*?)\s+T[a-z]?ype', line, re.IGNORECASE)
            description = desc_match.group(1).strip() if desc_match else ""

            # Classify Money In vs Money Out based on key location in text
            money_in, money_out, balance = "", "", ""

            # Extract all amounts in line
            amounts = amount_pattern.findall(line)

            if "Money In" in line or "Money In (£)" in line or "Moneyb Ilna" in line and "Money In" in line:
                # Indicates credit transaction
                if len(amounts) >= 2:
                    money_in = amounts[-2]
                    balance = amounts[-1]
                elif len(amounts) == 1:
                    money_in = amounts[0]
            else:
                # Default to debit/Money Out
                if len(amounts) >= 2:
                    money_out = amounts[-2]
                    balance = amounts[-1]
                elif len(amounts) == 1:
                    money_out = amounts[0]
            parsed_rows.append([formatted_date, description, money_in, money_out, balance])

    return parsed_rows


# ==============================================================================
# 3. BARCLAYS PARSER
# ==============================================================================
def parse_barclays(pdf) -> list:
    """
    Parses Barclays bank statement PDFs.
    """
    parsed_rows = []

    header_year_pattern = re.compile(r'\b\d{1,2}\s+[A-Za-z]{3}\s+(20\d{2})\b')
    line_date_pattern = re.compile(r'^(\d{2}\s+[A-Za-z]{3})\b')
    amount_pattern = re.compile(r'([\d,]+\.\d{2})')

    statement_year = None

    # Step 1: Detect statement year
    for page in pdf.pages:
        text = page.extract_text() or ""
        year_match = header_year_pattern.search(text)
        if year_match:
            statement_year = year_match.group(1)
            break

    # Step 2: Parse transaction lines
    for page in pdf.pages:
        text = page.extract_text() or ""
        raw_lines = [line.strip() for line in text.split('\n') if line.strip()]

        # Apply pre-processor to fix wrapped lines & sticky dates
        lines = pre_process_barclays_lines(raw_lines)

        current_tx = None

        for line in lines:
            # Skip non-transaction summary boundaries
            if any(skip in line for skip in ["Start balance", "End balance", "Statement date", "Page ", "Anything Wrong?"]):
                continue

            date_match = line_date_pattern.match(line)

            if date_match:
                # Flush previous transaction
                if current_tx:
                    parsed_rows.append(current_tx)

                raw_date = date_match.group(1)  # e.g. "01 May"
                
                # Format to "DD - MMM - YYYY"
                if statement_year:
                    try:
                        date_str = datetime.strptime(f"{raw_date} {statement_year}", "%d %b %Y").strftime("%d %b %Y")
                    except ValueError:
                        date_str = f"{raw_date} {statement_year}"
                else:
                    date_str = raw_date

                remainder = line[date_match.end():].strip()
                amounts = amount_pattern.findall(remainder)

                money_in, money_out, balance = "", "", ""

                # Distinguish Money In vs Money Out
                if "Received From" in remainder or "Credit" in remainder:
                    if len(amounts) >= 2:
                        money_in = amounts[-2]
                        balance = amounts[-1]
                    elif len(amounts) == 1:
                        money_in = amounts[0]
                else:
                    if len(amounts) >= 2:
                        money_out = amounts[-2]
                        balance = amounts[-1]
                    elif len(amounts) == 1:
                        money_out = amounts[0]

                # Strip amounts out to preserve clean description text
                desc_str = remainder
                for amt in amounts:
                    desc_str = desc_str.replace(amt, '', 1)

                current_tx = [date_str, desc_str.strip(), money_in, money_out, balance]

            elif current_tx:
                # Handle continuation/reference lines (e.g. "Ref: Grandma", "Ireland On 17 May")
                extra_amounts = amount_pattern.findall(line)

                # Backfill balance if omitted on line 1
                if extra_amounts and not current_tx[4]:
                    current_tx[4] = extra_amounts[-1]
                    if not current_tx[3] and not current_tx[2]:
                        current_tx[3] = extra_amounts[0] if len(extra_amounts) > 1 else ""

                clean_line = line
                for amt in extra_amounts:
                    clean_line = clean_line.replace(amt, '', 1)

                if clean_line.strip():
                    current_tx[1] += f" {clean_line.strip()}"

        if current_tx:
            parsed_rows.append(current_tx)

    # Post-process whitespace cleanup
    for row in parsed_rows:
        row[1] = re.sub(r'\s+', ' ', row[1]).strip()

    return parsed_rows

# Map identified banks to their custom parser functions
BANK_PARSERS = {
    "LLOYDS": parse_lloyds,
    "BARCLAYS": parse_barclays,
    "MONZO": parse_monzo
}


def extract_bank_statement_to_csv(pdf_path: str, output_csv_path: str):
    with pdfplumber.open(pdf_path) as pdf:
        if not pdf.pages:
            raise ValueError("PDF file has no pages.")
        # Get Bank
        bank_name = identify_bank(pdf.pages[0].extract_text() or "")
        print(f"Detected Bank: {bank_name}")
        # Bank Parser
        parser = BANK_PARSERS.get(bank_name)
        if not parser:
            raise NotImplementedError(
                f"No parser available for detected bank structure: '{bank_name}'"
            )
        # Apply Parser
        parsed_rows = parser(pdf)

    # Conver into needed format
    df = pd.DataFrame(parsed_rows, columns=["Date", "Description", "Money In", "Money Out", "Balance"])
    if not df.empty:
        # Standardize dates
        df['Date'] = pd.to_datetime(df['Date'], format='%d %b %Y', errors='coerce').dt.strftime('%d/%m/%Y')

    # Export to CSV
    df.to_csv(output_csv_path, index=False)
    print(f"Successfully processed {len(df)} transactions to {output_csv_path}.")

if __name__ == "__main__":
    extract_bank_statement_to_csv("bank_statement_1.pdf", "xero_import_1.csv")
    extract_bank_statement_to_csv("bank_statement_2.pdf", "xero_import_2.csv")
    extract_bank_statement_to_csv("bank_statement_3.pdf", "xero_import_3.csv")