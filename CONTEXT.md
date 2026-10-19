# inflation-station

Tracks money put into investment platforms and whether its value keeps up with inflation.

## Language

**Platform**:
A company you invest through and whose exports we import: J&T Banka, INVESTIKA, Portu.
_Avoid_: broker, provider, source

**Portfolio**:
One pot of money that a Platform reports separately, identified by the Platform's own name or number for it: a portfolio on Portu and J&T Banka, a contract on INVESTIKA. On Portu it is identified by its name, so renaming it there makes it a different Portfolio.
_Avoid_: account (your login at a Platform, which we don't track; say Platform), contract

**Whole Portfolio**:
All your Portfolios on all Platforms, with their Values added together.
_Avoid_: total, everything, overall

**Purchase**:
A buy of fund units that you chose to make, paid in CZK. On Platforms where you pick the funds, each Purchase's gross CZK is money invested.
_Avoid_: trade, order, transaction

**Fee**:
CZK a Platform charged you on a Purchase, outside a Managed Portfolio, on the Holding the Purchase was of. It is money invested but never part of any Value: it is money gone, so it counts against the return. Fees in a Managed Portfolio are paid from its Cash and are not money invested.
_Avoid_: charge, commission, poplatek

**Managed Portfolio**:
A Portfolio where you only put CZK in and the Platform decides what to buy, sell, hedge and charge (Portu). Its buys and sells are not Purchases.
_Avoid_: robo-advisor portfolio, managed account

**Deposit**:
CZK you moved into a Managed Portfolio. It is the money invested there, and its date is when its inflation hurdle starts.
_Avoid_: contribution, top-up, vklad

**Holding**:
The units of one fund held in one Portfolio. The same fund in two Portfolios is two Holdings, even when one is in a Managed Portfolio and the other is not.
_Avoid_: position

**Cash**:
Money in a Managed Portfolio not yet in funds, in each currency it is held in. It is part of the Portfolio's Value; fees are paid from it.
_Avoid_: balance

**Price source**:
Who publishes a fund's daily prices, which `fetch-prices` downloads and the price check compares against: Conseq for the funds it sells, Yahoo Finance for exchange-traded ones. Each fund has exactly one, set in a hand-edited mapping file.
_Avoid_: publisher, price provider

**Value**:
What Holdings and Cash are worth in CZK on a day, at the last known fund price and ČNB rate.

**Amount invested**:
The CZK you put in on or before a day: the gross CZK of Purchases plus the Fees and the Deposits into Managed Portfolios.

**Inflation hurdle**:
What the amount invested would need to be worth on a day to keep its purchasing power, by one price index, with each Purchase, Fee or Deposit grown from its own date.
