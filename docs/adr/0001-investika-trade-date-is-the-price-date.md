# INVESTIKA Purchases are dated by the price date

INVESTIKA's holdings statement gives three dates for each issue of units: the order date (`Datum pokynu`, when the money left the cash account), the price date (`Datum ceny`, the month-end whose price the units were issued at) and the settlement date (`Datum vypořádání`, when the units arrived, about ten days after that month-end).

We use the price date as the Purchase's trade date. The fund is priced only at month-ends, and Conseq's price history has one price per month-end, so the price check compares the statement's `Cena / kus` with Conseq's price on exactly that day and finds them equal. With the order date, the check would compare against the previous month-end's price and warn on nearly every Purchase.

The cost: the inflation hurdle starts at the price date, about a month after the money was paid, so each INVESTIKA Purchase's hurdle is understated by roughly one month of inflation.
