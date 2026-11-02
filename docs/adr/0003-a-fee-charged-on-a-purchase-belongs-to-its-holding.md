---
status: accepted
---

# A Fee charged on a Purchase belongs to its Holding

Every Fee is in a Portfolio, and a Fee charged on a Purchase (J&T Banka, INVESTIKA) also belongs to that Purchase's Holding. Any other Fee belongs to its Portfolio only: every Portu Fee is a monthly charge on the whole Managed Portfolio, with no Fund in its row. So a Holding's Fees paid are those charged on its Purchases, and a Portfolio's are all its Fees. A Portu Holding shows "No fees" while its Portfolio shows them all, which is what the export says.

A Holding's Fees paid are shown in CZK only, with no share of the amount invested: nothing is invested in a Holding, only in its Portfolio (ADR-0002), so there is nothing to divide by.

## Considered Options

- **Spread each Portu Fee across its Holdings by their Value share on the Fee's day.** Every Holding would have a figure, but an invented one: Portu doesn't charge per Fund, and the split would change with prices.
- **A Holding's Fees paid are its Portfolio's when it is the Portfolio's only Holding.** Needs no link from a Fee to a Holding, but it relies on how importers happen to split Portfolios today, and it is wrong as soon as a Portfolio with Fees charged on Purchases holds two Funds.
- **A Holding's share as its Fees over the cost of its Purchases.** A different base from the Portfolio's, so the two percentages couldn't be compared.
