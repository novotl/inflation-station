# Made-up INVESTIKA statements

Real statements carry personal data (birth number, address, contract number), so none are committed. Everything here is made up, laid out like the real statements of 2026-10-11, contract `1234567890`.

- `cash.pdf` and `holdings.pdf`: a statement pair for the end-to-end import test, with Czech diacritics and wrapped holdings rows, and a pending payment (`01.10.2026`) that has no issue yet. Written by `make_pdfs.py`, which needs a TTF font with Czech glyphs, e.g. DejaVu Sans:

  ```sh
  uv run python tests/fixtures/investika/make_pdfs.py path/to/DejaVuSans.ttf
  ```

- `*.txt`: made-up text, laid out the way pypdf's layout mode extracts a real statement, with columns separated by runs of spaces and, sometimes, a blank line inside a holdings row. `cash.txt` and `holdings.txt` are a matching pair; each other file changes one of them for one edge case:
  - `cash_pending_payment.txt`: a payment with no issue yet
  - `holdings_unmatched_issue.txt`: an issue with no payment on its order date
  - `cash_two_payments.txt`: two payments on one order date
  - `cash_unknown_type.txt`, `holdings_unknown_type.txt`: a transaction type the import doesn't know
  - `holdings_other_contract.txt`: a different `Číslo smlouvy`
