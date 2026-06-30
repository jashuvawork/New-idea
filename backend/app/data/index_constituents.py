"""Index constituent weights and Upstox instrument keys (NSE/BSE ISIN)."""

from typing import TypedDict


class ConstituentDef(TypedDict):
    symbol: str
    name: str
    weight: float
    isin: str
    exchange: str  # NSE_EQ or BSE_EQ


# NIFTY 50 — approximate free-float weights (%), ISINs for Upstox quotes
NIFTY50: list[ConstituentDef] = [
    {"symbol": "HDFCBANK", "name": "HDFC Bank", "weight": 12.8, "isin": "INE040A01034", "exchange": "NSE_EQ"},
    {"symbol": "RELIANCE", "name": "Reliance", "weight": 10.2, "isin": "INE002A01018", "exchange": "NSE_EQ"},
    {"symbol": "ICICIBANK", "name": "ICICI Bank", "weight": 8.4, "isin": "INE090A01021", "exchange": "NSE_EQ"},
    {"symbol": "INFY", "name": "Infosys", "weight": 6.1, "isin": "INE009A01021", "exchange": "NSE_EQ"},
    {"symbol": "ITC", "name": "ITC", "weight": 4.8, "isin": "INE154A01025", "exchange": "NSE_EQ"},
    {"symbol": "TCS", "name": "TCS", "weight": 4.5, "isin": "INE467B01029", "exchange": "NSE_EQ"},
    {"symbol": "LT", "name": "L&T", "weight": 3.9, "isin": "INE018A01030", "exchange": "NSE_EQ"},
    {"symbol": "AXISBANK", "name": "Axis Bank", "weight": 3.5, "isin": "INE238A01034", "exchange": "NSE_EQ"},
    {"symbol": "KOTAKBANK", "name": "Kotak Bank", "weight": 3.3, "isin": "INE237A01028", "exchange": "NSE_EQ"},
    {"symbol": "HINDUNILVR", "name": "HUL", "weight": 3.1, "isin": "INE030A01027", "exchange": "NSE_EQ"},
    {"symbol": "SBIN", "name": "SBI", "weight": 2.9, "isin": "INE062A01020", "exchange": "NSE_EQ"},
    {"symbol": "BHARTIARTL", "name": "Bharti Airtel", "weight": 2.8, "isin": "INE397D01024", "exchange": "NSE_EQ"},
    {"symbol": "BAJFINANCE", "name": "Bajaj Finance", "weight": 2.7, "isin": "INE296A01024", "exchange": "NSE_EQ"},
    {"symbol": "ASIANPAINT", "name": "Asian Paints", "weight": 2.4, "isin": "INE021A01026", "exchange": "NSE_EQ"},
    {"symbol": "MARUTI", "name": "Maruti", "weight": 2.3, "isin": "INE585B01010", "exchange": "NSE_EQ"},
    {"symbol": "TITAN", "name": "Titan", "weight": 2.1, "isin": "INE280A01028", "exchange": "NSE_EQ"},
    {"symbol": "SUNPHARMA", "name": "Sun Pharma", "weight": 2.0, "isin": "INE044A01036", "exchange": "NSE_EQ"},
    {"symbol": "HCLTECH", "name": "HCL Tech", "weight": 1.9, "isin": "INE860A01027", "exchange": "NSE_EQ"},
    {"symbol": "NTPC", "name": "NTPC", "weight": 1.8, "isin": "INE733E01010", "exchange": "NSE_EQ"},
    {"symbol": "ULTRACEMCO", "name": "UltraTech", "weight": 1.7, "isin": "INE481G01011", "exchange": "NSE_EQ"},
    {"symbol": "ONGC", "name": "ONGC", "weight": 1.6, "isin": "INE213A01029", "exchange": "NSE_EQ"},
    {"symbol": "NESTLEIND", "name": "Nestle", "weight": 1.5, "isin": "INE239A01024", "exchange": "NSE_EQ"},
    {"symbol": "TMPV", "name": "Tata Motors PV", "weight": 1.4, "isin": "INE155A01022", "exchange": "NSE_EQ"},
    {"symbol": "POWERGRID", "name": "Power Grid", "weight": 1.3, "isin": "INE752E01010", "exchange": "NSE_EQ"},
    {"symbol": "WIPRO", "name": "Wipro", "weight": 1.2, "isin": "INE075A01022", "exchange": "NSE_EQ"},
    {"symbol": "JSWSTEEL", "name": "JSW Steel", "weight": 1.2, "isin": "INE019A01038", "exchange": "NSE_EQ"},
    {"symbol": "COALINDIA", "name": "Coal India", "weight": 1.1, "isin": "INE522F01014", "exchange": "NSE_EQ"},
    {"symbol": "TATASTEEL", "name": "Tata Steel", "weight": 1.1, "isin": "INE081A01020", "exchange": "NSE_EQ"},
    {"symbol": "INDUSINDBK", "name": "IndusInd Bank", "weight": 1.0, "isin": "INE095A01012", "exchange": "NSE_EQ"},
    {"symbol": "BAJAJFINSV", "name": "Bajaj Finserv", "weight": 1.0, "isin": "INE918I01026", "exchange": "NSE_EQ"},
    {"symbol": "HINDALCO", "name": "Hindalco", "weight": 0.95, "isin": "INE038A01020", "exchange": "NSE_EQ"},
    {"symbol": "GRASIM", "name": "Grasim", "weight": 0.9, "isin": "INE047A01021", "exchange": "NSE_EQ"},
    {"symbol": "TECHM", "name": "Tech Mahindra", "weight": 0.85, "isin": "INE669F01031", "exchange": "NSE_EQ"},
    {"symbol": "CIPLA", "name": "Cipla", "weight": 0.8, "isin": "INE059A01026", "exchange": "NSE_EQ"},
    {"symbol": "DRREDDY", "name": "Dr Reddy's", "weight": 0.75, "isin": "INE089A01031", "exchange": "NSE_EQ"},
    {"symbol": "APOLLOHOSP", "name": "Apollo Hospitals", "weight": 0.7, "isin": "INE437A01024", "exchange": "NSE_EQ"},
    {"symbol": "EICHERMOT", "name": "Eicher", "weight": 0.65, "isin": "INE066A01021", "exchange": "NSE_EQ"},
    {"symbol": "HEROMOTOCO", "name": "Hero MotoCorp", "weight": 0.6, "isin": "INE158A01026", "exchange": "NSE_EQ"},
    {"symbol": "BPCL", "name": "BPCL", "weight": 0.55, "isin": "INE029A01011", "exchange": "NSE_EQ"},
    {"symbol": "BRITANNIA", "name": "Britannia", "weight": 0.5, "isin": "INE216A01030", "exchange": "NSE_EQ"},
    {"symbol": "TATACONSUM", "name": "Tata Consumer", "weight": 0.5, "isin": "INE192A01025", "exchange": "NSE_EQ"},
    {"symbol": "ADANIPORTS", "name": "Adani Ports", "weight": 0.48, "isin": "INE742F01042", "exchange": "NSE_EQ"},
    {"symbol": "SBILIFE", "name": "SBI Life", "weight": 0.45, "isin": "INE123W01016", "exchange": "NSE_EQ"},
    {"symbol": "HDFCLIFE", "name": "HDFC Life", "weight": 0.45, "isin": "INE127F01025", "exchange": "NSE_EQ"},
    {"symbol": "BAJAJ-AUTO", "name": "Bajaj Auto", "weight": 0.42, "isin": "INE917I01010", "exchange": "NSE_EQ"},
    {"symbol": "SHRIRAMFIN", "name": "Shriram Finance", "weight": 0.4, "isin": "INE721A01047", "exchange": "NSE_EQ"},
    {"symbol": "TRENT", "name": "Trent", "weight": 0.38, "isin": "INE849A01020", "exchange": "NSE_EQ"},
    {"symbol": "BEL", "name": "BEL", "weight": 0.35, "isin": "INE263A01024", "exchange": "NSE_EQ"},
    {"symbol": "HAL", "name": "HAL", "weight": 0.33, "isin": "INE066F01020", "exchange": "NSE_EQ"},
    {"symbol": "ADANIENT", "name": "Adani Enterprises", "weight": 0.3, "isin": "INE423A01024", "exchange": "NSE_EQ"},
    {"symbol": "DIVISLAB", "name": "Divi's Labs", "weight": 0.28, "isin": "INE361B01024", "exchange": "NSE_EQ"},
    {"symbol": "LTIM", "name": "LTIMindtree", "weight": 0.25, "isin": "INE214T01019", "exchange": "NSE_EQ"},
]

BANKNIFTY: list[ConstituentDef] = [
    {"symbol": "HDFCBANK", "name": "HDFC Bank", "weight": 27.0, "isin": "INE040A01034", "exchange": "NSE_EQ"},
    {"symbol": "ICICIBANK", "name": "ICICI Bank", "weight": 23.0, "isin": "INE090A01021", "exchange": "NSE_EQ"},
    {"symbol": "AXISBANK", "name": "Axis Bank", "weight": 12.0, "isin": "INE238A01034", "exchange": "NSE_EQ"},
    {"symbol": "KOTAKBANK", "name": "Kotak Bank", "weight": 11.0, "isin": "INE237A01028", "exchange": "NSE_EQ"},
    {"symbol": "SBIN", "name": "SBI", "weight": 10.0, "isin": "INE062A01020", "exchange": "NSE_EQ"},
    {"symbol": "INDUSINDBK", "name": "IndusInd Bank", "weight": 6.0, "isin": "INE095A01012", "exchange": "NSE_EQ"},
    {"symbol": "BANKBARODA", "name": "Bank of Baroda", "weight": 3.5, "isin": "INE028A01039", "exchange": "NSE_EQ"},
    {"symbol": "PNB", "name": "PNB", "weight": 2.5, "isin": "INE160A01022", "exchange": "NSE_EQ"},
    {"symbol": "FEDERALBNK", "name": "Federal Bank", "weight": 2.0, "isin": "INE171A01029", "exchange": "NSE_EQ"},
    {"symbol": "IDFCFIRSTB", "name": "IDFC First", "weight": 1.8, "isin": "INE092T01019", "exchange": "NSE_EQ"},
    {"symbol": "AUBANK", "name": "AU Bank", "weight": 1.2, "isin": "INE949L01017", "exchange": "NSE_EQ"},
    {"symbol": "BANDHANBNK", "name": "Bandhan Bank", "weight": 0.8, "isin": "INE545U01014", "exchange": "NSE_EQ"},
]

SENSEX30: list[ConstituentDef] = [
    {"symbol": "RELIANCE", "name": "Reliance", "weight": 12.0, "isin": "INE002A01018", "exchange": "BSE_EQ"},
    {"symbol": "HDFCBANK", "name": "HDFC Bank", "weight": 10.0, "isin": "INE040A01034", "exchange": "BSE_EQ"},
    {"symbol": "ICICIBANK", "name": "ICICI Bank", "weight": 8.5, "isin": "INE090A01021", "exchange": "BSE_EQ"},
    {"symbol": "INFY", "name": "Infosys", "weight": 7.0, "isin": "INE009A01021", "exchange": "BSE_EQ"},
    {"symbol": "ITC", "name": "ITC", "weight": 5.5, "isin": "INE154A01025", "exchange": "BSE_EQ"},
    {"symbol": "TCS", "name": "TCS", "weight": 5.0, "isin": "INE467B01029", "exchange": "BSE_EQ"},
    {"symbol": "LT", "name": "L&T", "weight": 4.5, "isin": "INE018A01030", "exchange": "BSE_EQ"},
    {"symbol": "AXISBANK", "name": "Axis Bank", "weight": 4.0, "isin": "INE238A01034", "exchange": "BSE_EQ"},
    {"symbol": "HINDUNILVR", "name": "HUL", "weight": 3.8, "isin": "INE030A01027", "exchange": "BSE_EQ"},
    {"symbol": "BHARTIARTL", "name": "Bharti Airtel", "weight": 3.5, "isin": "INE397D01024", "exchange": "BSE_EQ"},
    {"symbol": "KOTAKBANK", "name": "Kotak Bank", "weight": 3.2, "isin": "INE237A01028", "exchange": "BSE_EQ"},
    {"symbol": "SBIN", "name": "SBI", "weight": 3.0, "isin": "INE062A01020", "exchange": "BSE_EQ"},
    {"symbol": "ASIANPAINT", "name": "Asian Paints", "weight": 2.8, "isin": "INE021A01026", "exchange": "BSE_EQ"},
    {"symbol": "MARUTI", "name": "Maruti", "weight": 2.5, "isin": "INE585B01010", "exchange": "BSE_EQ"},
    {"symbol": "TITAN", "name": "Titan", "weight": 2.3, "isin": "INE280A01028", "exchange": "BSE_EQ"},
    {"symbol": "SUNPHARMA", "name": "Sun Pharma", "weight": 2.2, "isin": "INE044A01036", "exchange": "BSE_EQ"},
    {"symbol": "HCLTECH", "name": "HCL Tech", "weight": 2.0, "isin": "INE860A01027", "exchange": "BSE_EQ"},
    {"symbol": "NTPC", "name": "NTPC", "weight": 1.8, "isin": "INE733E01010", "exchange": "BSE_EQ"},
    {"symbol": "ULTRACEMCO", "name": "UltraTech", "weight": 1.7, "isin": "INE481G01011", "exchange": "BSE_EQ"},
    {"symbol": "TMPV", "name": "Tata Motors PV", "weight": 1.6, "isin": "INE155A01022", "exchange": "BSE_EQ"},
    {"symbol": "POWERGRID", "name": "Power Grid", "weight": 1.5, "isin": "INE752E01010", "exchange": "BSE_EQ"},
    {"symbol": "WIPRO", "name": "Wipro", "weight": 1.4, "isin": "INE075A01022", "exchange": "BSE_EQ"},
    {"symbol": "NESTLEIND", "name": "Nestle", "weight": 1.3, "isin": "INE239A01024", "exchange": "BSE_EQ"},
    {"symbol": "BAJFINANCE", "name": "Bajaj Finance", "weight": 1.2, "isin": "INE296A01024", "exchange": "BSE_EQ"},
    {"symbol": "M&M", "name": "Mahindra", "weight": 1.1, "isin": "INE101A01026", "exchange": "BSE_EQ"},
    {"symbol": "JSWSTEEL", "name": "JSW Steel", "weight": 1.0, "isin": "INE019A01038", "exchange": "BSE_EQ"},
    {"symbol": "TATASTEEL", "name": "Tata Steel", "weight": 0.9, "isin": "INE081A01020", "exchange": "BSE_EQ"},
    {"symbol": "TECHM", "name": "Tech Mahindra", "weight": 0.85, "isin": "INE669F01031", "exchange": "BSE_EQ"},
    {"symbol": "ADANIPORTS", "name": "Adani Ports", "weight": 0.8, "isin": "INE742F01042", "exchange": "BSE_EQ"},
    {"symbol": "INDUSINDBK", "name": "IndusInd Bank", "weight": 0.75, "isin": "INE095A01012", "exchange": "BSE_EQ"},
]

INDEX_CONSTITUENTS: dict[str, list[ConstituentDef]] = {
    "NIFTY": NIFTY50,
    "BANKNIFTY": BANKNIFTY,
    "SENSEX": SENSEX30,
}

INDEX_LABELS: dict[str, str] = {
    "NIFTY": "NIFTY 50",
    "BANKNIFTY": "NIFTY BANK",
    "SENSEX": "SENSEX 30",
}


def instrument_key(c: ConstituentDef) -> str:
    return f"{c['exchange']}|{c['isin']}"


def get_constituents(symbol: str) -> list[ConstituentDef]:
    return INDEX_CONSTITUENTS.get(symbol.upper(), [])
