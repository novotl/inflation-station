# inflation-station

Tracks money put into investment platforms and whether its value keeps up with inflation.

## Language

**Platform**:
A company you invest through and whose exports we import: J&T Banka, INVESTIKA, Portu.
_Avoid_: broker, provider, source

**Portfolio**:
One pot of money we track on its own, on one Platform. Deposits go into its Cash, Fees are paid from its Cash, and its Cash buys its Holdings. It has its own Amount invested, Value and Inflation hurdle. How a Platform's export maps onto Portfolios is the importer's choice, not the Platform's: one J&T Banka portfolio becomes a Portfolio per Fund bought in it.
_Avoid_: account (your login at a Platform, which we don't track; say Platform), contract; and a Platform's own "portfolio" or "contract", which is only importer input

**Platform total**:
All your Portfolios on one Platform, with their Amounts invested, Values and Inflation hurdles added together.
_Avoid_: platform portfolio

**Whole Portfolio**:
All your Portfolios on all Platforms, with their Values added together.
_Avoid_: total, everything, overall

**Purchase**:
A buy of a Fund's units, paid from Cash in the currency the units are priced in.
_Avoid_: trade, order, transaction

**Sale**:
A sell of a Fund's units, paid into Cash.
_Avoid_: trade, redemption

**Conversion**:
Cash changed from one currency to another within a Portfolio.
_Avoid_: forex, exchange, FX trade

**Fee**:
Money a Platform charges you, in the currency it is charged in. It is always paid from Cash, so it lowers the Value; it is never money invested. A Fee charged on a Purchase is paid from Cash just before the units are bought.
_Avoid_: charge, commission, poplatek

**Managed Portfolio**:
A Portfolio where you only make Deposits and the Platform decides its Purchases, Sales, Conversions and Fees (Portu). It is tracked like any other Portfolio.
_Avoid_: robo-advisor portfolio, managed account

**Deposit**:
Money you moved into a Portfolio's Cash, in the currency you moved it in (so far always CZK). It is the money invested, on every Platform, and its date is when its inflation hurdle starts.
_Avoid_: contribution, top-up, vklad

**Fund**:
A fund whose units you hold, identified by its ISIN. The same Fund on two Platforms is one Fund.
_Avoid_: security, instrument, product

**Holding**:
The units of one Fund held in one Portfolio. The same fund in two Portfolios is two Holdings, even when one is in a Managed Portfolio and the other is not.
_Avoid_: position

**Cash**:
Money in a Portfolio not yet in Funds, in each currency it is held in. It is part of the Portfolio's Value; Fees are paid from it.
_Avoid_: balance

**Price source**:
Who publishes a fund's daily prices, which `fetch-prices` downloads and the price check compares against: Conseq for the funds it sells, Yahoo Finance for exchange-traded ones. Each fund has exactly one, set in a hand-edited mapping file.
_Avoid_: publisher, price provider

**Value**:
What Holdings and Cash are worth in CZK on a day, at the last known fund price and ČNB rate.

**Amount invested**:
The CZK you put in on or before a day: the Deposits.

**Inflation hurdle**:
What the amount invested would need to be worth on a day to keep its purchasing power, by one price index, with each Deposit grown from its own date.
