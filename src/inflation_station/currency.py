"""Currency codes: the ISO 4217 list, so a typo or a column mix-up in an export or a download is never a currency."""

# The currency amounts are valued in.
CZK = "CZK"

# Every active ISO 4217 code, including funds codes (e.g. CLF) and the X codes (precious metals, SDR, XXX).
CODES = frozenset(
    """
    AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BOV BRL BSD BTN BWP BYN BZD CAD CDF
    CHE CHF CHW CLF CLP CNY COP COU CRC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF
    GTQ GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD
    LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MXV MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP
    PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SLL SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND
    TOP TRY TTD TWD TZS UAH UGX USD USN UYI UYU UYW UZS VED VES VND VUV WST XAF XAG XAU XBA XBB XBC XBD XCD XCG XDR
    XOF XPD XPF XPT XSU XTS XUA XXX YER ZAR ZMW ZWG ZWL
    """.split()  # noqa: SIM905 - a block of codes reads like the standard's table
)


def code(text: str) -> str:
    """`text` if it is an ISO 4217 currency code; raises ValueError naming it otherwise."""
    if text not in CODES:
        msg = f"{text!r} is not an ISO 4217 currency code"
        raise ValueError(msg)
    return text
