---
status: superseded by ADR-0003
---

# Portu: the money invested is the Deposit, not the buys

Portu is a Managed Account: you deposit CZK, and Portu converts it to EUR/USD, buys and sells ETFs to rebalance, hedges currency with swaps and forwards, and takes a monthly fee from cash. We count each Deposit as the money invested, with its inflation hurdle starting on the deposit date, and value the Account as its holdings at market prices plus its cash. Portu's buys and sells move units and cash inside the Account but are not Purchases.

## Considered Options

- **Each buy as a Purchase, plus a Sale concept.** No row gives a buy's CZK cost; it would have to be pieced together from same-day forex rows, hedging legs have no buy to attach to, monthly fees would need spreading across funds, and sells would need a cost-basis rule (FIFO or average). Per-fund "invested" lines would be an invention, since you never chose to put money into any one fund.
- **Buys as Purchases, sells ignored.** Units held would be overstated.

## Consequences

Portu's funds have no per-fund amount invested or inflation hurdle; those exist only for the Account as a whole.
