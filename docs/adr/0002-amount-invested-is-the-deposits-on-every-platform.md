---
status: accepted
---

# Amount invested is the Deposits on every Platform

We count the Deposits as the money invested in every Portfolio, on every Platform, so Platforms can be compared on equal terms. A Fee is always paid from Cash and lowers the Value; on J&T Banka and INVESTIKA, a Fee charged on a Purchase is paid from Cash just before the units are bought. Every buy, sell, currency conversion and Fee is a row of its own on every Platform, Portu included. This removes ADR-0001's cost: the inflation hurdle now starts at the Deposit's date, not the Purchase's price date.

The model is ours and the importers translate each export into it, rather than the model following any Platform's structure. J&T Banka reports one portfolio, but it holds one Fund per standing order, each funded by its own Deposit, so its importer makes a Portfolio per Fund and gives each Deposit to the Portfolio of the next Purchase of the same amount a few days later. A Deposit it cannot pair fails the import. This keeps per-Fund Amount invested and Inflation hurdle wherever a Portfolio has one Holding.

## Considered Options

- **Deposits as the money invested on Portu only, Purchases plus their Fees elsewhere** (the first version of this ADR). Portu's buys had no CZK cost to count, so it was the special case. Platforms could not be compared (Portu's invested excluded its Fees, J&T's included them), and valuation needed a second code path.
- **One Portfolio per J&T portfolio, with Deposits earmarked for a Fund.** Keeps the Platform's grouping, but adds a second way of attributing money to a Fund next to the Portfolio.
