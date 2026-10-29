# Bank PDF to CSV Converter

[**Use the Web Converter**](https://mwallis45.github.io/Bank-PDF-To-CSV/)

A client-side utility that extracts transaction data from bank statement PDFs and converts it into formatted CSV files ready for import into **Xero**, **QuickBooks**, or spreadsheet applications.

---

## How It Works

1. **PDF Parsing:** Uses `pypdf` to extract text streams and flatten structural data from uploaded PDF statements.
2. **Bank-Specific Parsers:** Because each financial institution formats statement tables differently, custom regex and parsing logic clean and structure transactions based on the target bank's layout.
3. **CSV Export:** Standardizes transaction fields (`Date`, `Description`, `Money In`, `Money Out`, `Balance`) into a clean format accepted by accounting platforms.

---

## Supported Banks

- **Monzo**
- **Lloyds Bank**
- **Barclays**

*(Additional bank parsers can be added by implementing custom line-processing logic in the parser scripts).*

---

## Usage

### Option 1: Web Interface (No Installation)
Visit the [Live Converter](https://mwallis45.github.io/Bank-PDF-To-CSV/) to process statements directly in your web browser. All parsing runs locally on your machine meaning your bank statements are never uploaded to a remote server.

### Option 2: Local Setup

1. Clone the repository:
```bash
git clone https://github.com/mwallis45/Bank-PDF-To-CSV.git
cd Bank-PDF-To-CSV
```
2. Install Python dependencies:
``` Bash
pip install pypdf
```
3. Run the conversion script:
``` Bash
python main.py --input path/to/statement.pdf --output statement.csv
```

---

## Privacy & Security

Bank statements contain sensitive financial data. This tool operates 100% client-side when using the web application, ensuring your files never leave your local environment.

---

## License

This project is open-source and available under the **MIT License**.

*Last Updated: October 29, 2026*  