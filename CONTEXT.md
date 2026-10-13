# inflation-station

Tracks money put into investment platforms and whether its value keeps up with inflation.

## Language

**Platform**:
A company you invest through and whose exports we import: J&T Banka, INVESTIKA, Portu.
_Avoid_: broker, provider, source

**Account**:
One portfolio or contract on a Platform, identified by the Platform's own name or number for it. On Portu it is the portfolio's name, so renaming a portfolio there makes it a different Account.
_Avoid_: portfolio (except when quoting Portu)

**Purchase**:
A buy of fund units that you chose to make, paid in CZK. On Platforms where you pick the funds, each Purchase's gross CZK is money invested.
_Avoid_: trade, order, transaction

**Managed Account**:
An Account where you only put CZK in and the Platform decides what to buy, sell, hedge and charge (Portu). Its buys and sells are not Purchases.
_Avoid_: robo-advisor account

**Deposit**:
CZK you moved into a Managed Account. It is the money invested there, and its date is when its inflation hurdle starts.
_Avoid_: contribution, top-up, vklad

**Holding**:
The units of one fund held in one Account. The same fund in two Accounts is two Holdings, even when one is in a Managed Account and the other is not.
_Avoid_: position

**Cash**:
Money in a Managed Account not yet in funds, in each currency it is held in. It is part of the Account's value; fees are paid from it.
_Avoid_: balance

**Price source**:
Who publishes a fund's daily prices, which `fetch-prices` downloads and the price check compares against: Conseq for the funds it sells, Yahoo Finance for exchange-traded ones. Each fund has exactly one, set in a hand-edited mapping file.
_Avoid_: publisher, price provider

**Value**:
What Holdings and Cash are worth in CZK on a day, at the last known fund price and ČNB rate.

**Amount invested**:
The CZK you put in on or before a day: the gross CZK of Purchases plus the Deposits into Managed Accounts. Fees count as invested, so they count against the return.

**Inflation hurdle**:
What the amount invested would need to be worth on a day to keep its purchasing power, by one price index, with each Purchase or Deposit grown from its own date.
