import pdfplumber
import pandas as pd
import re

def extract_bank_statement_table(pdf_path: str, output_excel: str="transactions.xlsx", output_csv: str="transactions.csv"):
    """
    Extracts transaction table from a bank statement PDF and exports to Excel/CSV.
    
    Parameters:
        pdf_path (str): Path to the input PDF file.
        output_excel (str, optional): Output Excel file path.
        output_csv (str, optional): Output CSV file path.
    
    Returns:
        pd.DataFrame: Cleaned Pandas DataFrame containing the transaction data.
    """
    all_rows: list[list[str]] = []
    
    # Common standard header keywords to identify the main transaction table
    target_headers = ["date", "description", "ref", "money in", "money out", "deposit", "withdrawal", "balance", "amount"]

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            # Extract all tables found on the page
            tables = page.extract_tables()
            
            for table in tables:
                for row in table:
                    # Clean up empty cells / trailing newlines in each cell
                    cleaned_row: list[str] = [str(cell).strip().replace('\n', ' ') if cell else '' for cell in row]
                    
                    # Ignore completely empty rows
                    if not any(cleaned_row):
                        continue
                    
                    all_rows.append(cleaned_row)

    if not all_rows:
        print("No tables found in the PDF.")
        return None

    # Find the header row by checking which row contains typical table header keywords
    header_idx = None
    for idx, row in enumerate(all_rows):
        row_str = " ".join(row).lower()
        # If at least 2 target header terms are in the row, mark it as the header
        matches = sum(1 for keyword in target_headers if keyword in row_str)
        if matches >= 2:
            header_idx = idx
            break

    # If no header was dynamically matched, fall back to using the first row
    if header_idx is not None:
        headers = all_rows[header_idx]
        data_rows = all_rows[header_idx + 1:]
    else:
        headers = [f"Column_{i+1}" for i in range(len(all_rows[0]))]
        data_rows = all_rows

    # Create DataFrame
    df = pd.DataFrame(data_rows, columns=headers)

    # Filter out repeating headers across multi-page statements
    df = df[~df.apply(lambda row: row.astype(str).str.lower().tolist() == [h.lower() for h in headers], axis=1)]

    # Basic cleanup: remove rows that don't look like valid transaction lines (e.g. metadata or blank rows)
    # Most transaction rows start with a date pattern (e.g., DD/MM/YYYY or MM/DD/YY)
    date_pattern = r'\d{1,4}[-/\.]\d{1,2}[-/\.]\d{1,4}'
    first_col = df.columns[0]
    
    # Keep rows where the first column has a date, or retain rows if strict date filtering isn't desired
    valid_data_df = df[df[first_col].str.contains(date_pattern, na=False, regex=True)].copy()

    # Fall back to full DataFrame if date filtering removed all rows
    final_df = valid_data_df if not valid_data_df.empty else df

    # Export to Excel and CSV
    if output_excel:
        final_df.to_excel(output_excel, index=False)
        print(f"Exported to Excel: {output_excel}")
        
    if output_csv:
        final_df.to_csv(output_csv, index=False)
        print(f"Exported to CSV: {output_csv}")

    return final_df


# --- Example Usage ---
if __name__ == "__main__":
    df = extract_bank_statement_table(
        pdf_path="bank_statement.pdf",
        output_excel="bank_statement_output.xlsx",
        output_csv="bank_statement_output.csv"
    )
    # print("\nExtracted Data Sample:")
    # print(df.head())