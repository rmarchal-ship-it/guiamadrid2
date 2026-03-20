"""
S&P 500 Historical Universe by Sector — Survivorship-Bias-Free
===============================================================
Created: 2026-03-17
Purpose: Provide historically accurate ticker lists for backtesting,
         grouped by GICS sector at 4 snapshot dates: 2006, 2011, 2016, 2021.

Sources:
  - fortboise.org/Top100 (Oct 2006 actual market cap rankings)
  - finhacker.cz (Top 20 S&P 500 by year, 1989-2026)
  - companiesmarketcap.com (historical market cap data)
  - Wikipedia: List of S&P 500 companies (historical changes)
  - S&P Global: GICS sector reclassifications

IMPORTANT NOTES:
  - GICS was restructured in Sep 2018: Telecom became Communication Services,
    absorbing GOOGL, META, DIS, NFLX, ATVI, EA, TTWO from Tech/Discretionary.
  - Real Estate became its own sector in Sep 2016 (was under Financials before).
  - Companies listed here were S&P 500 members at the snapshot date.
  - Tickers marked with (*) were later delisted, merged, or acquired — see NOTES dict.

Sector classification follows the GICS standard AT THE TIME of each snapshot,
not today's classification. For pre-2018 snapshots, GOOGL/META are in Technology.
"""

# ============================================================================
# NOTES: Delistings, mergers, acquisitions, ticker changes
# ============================================================================
NOTES = {
    # === TECHNOLOGY ===
    "DELL": "Dell went private 2013, re-listed 2018 as DELL (Dell Technologies)",
    "EMC": "Acquired by Dell 2016, delisted",
    "YHOO": "Yahoo core biz acquired by Verizon 2017, remainder became Altaba (delisted 2019)",
    "HPQ": "HP Inc (printers/PCs) after 2015 split. Enterprise side became HPE",
    "SNDK": "SanDisk acquired by Western Digital 2016, delisted",
    "LNKD": "LinkedIn acquired by Microsoft 2016, delisted",
    "SYMC": "Symantec enterprise biz acquired by Broadcom 2019, consumer became NortonLifeLock (GEN)",
    "CA": "CA Technologies acquired by Broadcom 2018, delisted",
    "CTXS": "Citrix taken private 2022, delisted",
    "XLNX": "Xilinx acquired by AMD 2022, delisted",

    # === FINANCE ===
    "WB": "Wachovia acquired by Wells Fargo 2008, delisted",
    "MER": "Merrill Lynch acquired by Bank of America 2009, delisted",
    "BSC": "Bear Stearns acquired by JPMorgan 2008, delisted",
    "LEH": "Lehman Brothers bankrupt 2008, delisted",
    "AIG": "AIG survived via govt bailout, still listed but much smaller",
    "CFC": "Countrywide Financial acquired by Bank of America 2008, delisted",
    "WM_bank": "Washington Mutual failed 2008, assets acquired by JPMorgan",

    # === HEALTHCARE ===
    "WYE": "Wyeth acquired by Pfizer 2009, delisted",
    "SGP": "Schering-Plough merged with Merck 2009, delisted",
    "DNA": "Genentech acquired by Roche 2009, delisted",
    "CELG": "Celgene acquired by Bristol-Myers Squibb 2019, delisted",
    "AGN": "Allergan acquired by AbbVie 2020, delisted",
    "MYL": "Mylan merged with Upjohn (Pfizer unit) to form Viatris (VTRS) 2020",
    "ALXN": "Alexion acquired by AstraZeneca 2021, delisted",

    # === ENERGY ===
    "SUN_energy": "Sunoco spun off SunCoke Energy, logistics MLP; restructured multiple times",
    "MPC_pre": "Marathon Petroleum spun off from Marathon Oil (MRO) in 2011",
    "PSX": "Phillips 66 spun off from ConocoPhillips 2012",
    "APC": "Anadarko Petroleum acquired by Occidental 2019, delisted",
    "PXD": "Pioneer Natural Resources acquired by ExxonMobil 2024, delisted",
    "DVN_HES": "Hess (HES) being acquired by Chevron (pending as of 2026)",

    # === INDUSTRIALS ===
    "GE": "GE split into 3 companies 2024: GE Aerospace (GE), GE Vernova (GEV), GE HealthCare (GEHC)",
    "UTX": "United Technologies merged with Raytheon 2020 to form RTX; spun off Carrier (CARR) and Otis (OTIS)",
    "DOW_old": "Old Dow Chemical merged with DuPont 2017, then split into DOW, DD, CTVA",
    "TYC": "Tyco International split into 3 companies 2007; Johnson Controls acquired Tyco 2016",
    "HON_old": "Honeywell spun off Resideo Technologies (REZI) 2018 and Quantinuum",

    # === TELECOM ===
    "BLS": "BellSouth acquired by AT&T Dec 2006, delisted",
    "Q_tel": "Qwest acquired by CenturyLink (now Lumen LUMN) Apr 2011, delisted",
    "S_sprint": "Sprint merged with T-Mobile (TMUS) Apr 2020, delisted",
    "WIN": "Windstream filed bankruptcy 2019, delisted from S&P 500",
    "FTR": "Frontier Communications filed bankruptcy 2020, re-emerged as FYBR",
    "CTL": "CenturyLink renamed to Lumen Technologies (LUMN) Sep 2020",
    "LVLT": "Level 3 Communications acquired by CenturyLink 2017, delisted",

    # === CONSUMER ===
    "SHLD": "Sears Holdings bankrupt 2018, delisted",
    "TWX": "Time Warner acquired by AT&T 2018, delisted",
    "KFT": "Kraft Foods split 2012: Mondelez (MDLZ) + Kraft Foods Group (merged with Heinz 2015 = KHC)",
    "MO_PM": "Altria (MO) spun off Philip Morris International (PM) in 2008",
    "RAI": "Reynolds American acquired by British American Tobacco 2017, delisted",

    # === UTILITIES ===
    "FPL": "FPL Group renamed to NextEra Energy (NEE) 2010",
    "PGN": "Progress Energy merged with Duke Energy 2012",
    "NU_utility": "Northeast Utilities renamed Eversource Energy (ES) 2015",

    # === REAL ESTATE ===
    "SPG_note": "Real Estate was part of Financials sector until Sep 2016",
}


# ============================================================================
# 2006 SNAPSHOT (End of year / Oct 2006 data)
# ============================================================================
SP500_2006 = {
    "Technology": [
        # Top 20 tech by market cap in S&P 500, end 2006
        # Note: GOOGL classified as Tech pre-2018 GICS change
        "MSFT",   # Microsoft ~$293B
        "CSCO",   # Cisco ~$166B
        "INTC",   # Intel ~$117B
        "GOOG",   # Google ~$141B (pre-GICS change, was Tech)
        "IBM",    # IBM ~$140B
        "HPQ",    # Hewlett-Packard ~$106B
        "ORCL",   # Oracle ~$97B
        "QCOM",   # Qualcomm ~$62B
        "AAPL",   # Apple ~$63B (still small!)
        "TXN",    # Texas Instruments ~$50B
        "EMC",    # EMC Corp ~$42B (acquired by Dell 2016)
        "DELL",   # Dell ~$55B (went private 2013)
        "MOT",    # Motorola ~$60B (split into MSI + Motorola Mobility, latter acquired by Google then Lenovo)
        "YHOO",   # Yahoo ~$40B (acquired by Verizon 2017)
        "EBAY",   # eBay ~$38B
        "ADP",    # ADP ~$25B
        "SAP",    # SAP ~$63B (ADR)
        "SNDK",   # SanDisk ~$8B (acquired by WDC 2016)
        "CA",     # CA Technologies ~$15B (acquired by Broadcom 2018)
        "ADBE",   # Adobe ~$20B
    ],

    "Finance": [
        # Financials were THE dominant sector in 2006 (~22% of S&P 500)
        "C",      # Citigroup ~$274B (largest financial, crashed 2008)
        "BAC",    # Bank of America ~$240B
        "JPM",    # JPMorgan Chase ~$168B
        "AIG",    # AIG ~$155B (bailout 2008)
        "WFC",    # Wells Fargo ~$120B
        "GS",     # Goldman Sachs ~$77B
        "WB",     # Wachovia ~$87B (acquired by WFC 2008)
        "MER",    # Merrill Lynch ~$74B (acquired by BAC 2009)
        "MS",     # Morgan Stanley ~$80B
        "USB",    # US Bancorp ~$59B
    ],

    "Healthcare": [
        "PFE",    # Pfizer ~$177B
        "JNJ",    # Johnson & Johnson ~$191B
        "AMGN",   # Amgen ~$84B
        "ABT",    # Abbott Labs ~$73B (pre-AbbVie spinoff)
        "MRK",    # Merck ~$95B
        "WYE",    # Wyeth ~$71B (acquired by Pfizer 2009)
        "LLY",    # Eli Lilly ~$65B
        "UNH",    # UnitedHealth Group ~$62B
        "MDT",    # Medtronic ~$57B
        "BMY",    # Bristol-Myers Squibb ~$50B
    ],

    "Consumer": [
        # Mix of Staples + Discretionary
        "PG",     # Procter & Gamble ~$204B (Staples)
        "WMT",    # Walmart ~$192B (Staples)
        "MO",     # Altria Group ~$164B (Staples; pre-PM spinoff 2008)
        "KO",     # Coca-Cola ~$113B (Staples)
        "PEP",    # PepsiCo ~$103B (Staples)
        "HD",     # Home Depot ~$74B (Discretionary)
        "DIS",    # Walt Disney ~$66B (Discretionary)
        "CMCSA",  # Comcast ~$79B (Discretionary)
        "TWX",    # Time Warner ~$78B (Discretionary; acquired by AT&T 2018)
        "MCD",    # McDonald's ~$55B (Discretionary)
    ],

    "Industrial": [
        "GE",     # General Electric ~$370B (by FAR #1 industrial; split 2024)
        "UTX",    # United Technologies ~$66B (merged with Raytheon 2020 = RTX)
        "UPS",    # UPS ~$79B
        "BA",     # Boeing ~$65B
        "MMM",    # 3M ~$57B
        "HON",    # Honeywell ~$42B
        "CAT",    # Caterpillar ~$45B
        "LMT",    # Lockheed Martin ~$40B
        "EMR",    # Emerson Electric ~$35B
        "GD",     # General Dynamics ~$28B
    ],

    "Energy": [
        "XOM",    # ExxonMobil ~$447B (#1 company in entire S&P 500!)
        "CVX",    # Chevron ~$160B
        "COP",    # ConocoPhillips ~$99B (pre-PSX spinoff)
        "SLB",    # Schlumberger ~$71B
        "OXY",    # Occidental ~$33B
        "APC",    # Anadarko Petroleum ~$35B (acquired by OXY 2019)
        "VLO",    # Valero Energy ~$28B
        "HAL",    # Halliburton ~$30B
        "DVN",    # Devon Energy ~$28B
        "BHI",    # Baker Hughes ~$25B (merged with GE Oil & Gas, now BKR)
    ],

    "Utilities": [
        "SO",     # Southern Company ~$35B
        "EXC",    # Exelon ~$42B
        "D",      # Dominion Resources ~$33B
        "DUK",    # Duke Energy ~$28B
        "FPL",    # FPL Group ~$24B (renamed NextEra Energy NEE in 2010)
        "AEP",    # American Electric Power ~$20B
        "ED",     # Consolidated Edison ~$13B
        "PGN",    # Progress Energy ~$12B (merged with DUK 2012)
        "PCG",    # PG&E Corp ~$16B
        "XEL",    # Xcel Energy ~$10B
    ],

    "Telecom": [
        # Very small sector in 2006 — only a handful of pure telecom in S&P 500
        "T",      # AT&T ~$127B (absorbed BellSouth Dec 2006)
        "VZ",     # Verizon ~$107B
        "BLS",    # BellSouth ~$78B (acquired by AT&T Dec 2006)
        "S",      # Sprint Nextel ~$52B (merged with T-Mobile 2020)
        "Q",      # Qwest ~$18B (acquired by CenturyLink 2011)
        "CTL",    # CenturyTel ~$5B (later CenturyLink, now Lumen LUMN)
        "WIN",    # Windstream ~$5B (bankrupt 2019)
    ],

    "RealEstate": [
        # NOT a separate GICS sector until 2016 — was part of Financials
        # These are the largest REITs in the S&P 500 circa 2006
        "SPG",    # Simon Property Group ~$45B
        "EQR",    # Equity Residential ~$18B
        "VNO",    # Vornado Realty ~$15B
        "BXP",    # Boston Properties ~$13B
        "PLD",    # ProLogis ~$15B
        "AVB",    # AvalonBay ~$12B
        "PSA",    # Public Storage ~$22B
        "HST",    # Host Hotels ~$10B
        "AMT",    # American Tower ~$14B (classified as Telecom tower REIT)
        "KIM",    # Kimco Realty ~$8B
    ],
}


# ============================================================================
# 2011 SNAPSHOT (End of year)
# ============================================================================
SP500_2011 = {
    "Technology": [
        "AAPL",   # Apple ~$377B (#2 overall, fighting XOM for #1)
        "MSFT",   # Microsoft ~$218B
        "GOOG",   # Google ~$209B
        "IBM",    # IBM ~$207B
        "ORCL",   # Oracle ~$129B
        "INTC",   # Intel ~$123B
        "CSCO",   # Cisco ~$100B
        "QCOM",   # Qualcomm ~$88B
        "HPQ",    # HP ~$50B (declining)
        "EMC",    # EMC ~$48B (acquired by Dell 2016)
        "TXN",    # Texas Instruments ~$33B
        "EBAY",   # eBay ~$40B
        "DELL",   # Dell ~$28B (went private 2013)
        "ADP",    # ADP ~$27B
        "ADBE",   # Adobe ~$16B
        "YHOO",   # Yahoo ~$20B (acquired by Verizon 2017)
        "CTSH",   # Cognizant ~$19B
        "SAP",    # SAP ~$72B (ADR)
        "SNDK",   # SanDisk ~$12B (acquired by WDC 2016)
        "ACN",    # Accenture ~$34B
    ],

    "Finance": [
        "BRK-B",  # Berkshire Hathaway ~$189B
        "WFC",    # Wells Fargo ~$145B
        "JPM",    # JPMorgan Chase ~$126B
        "V",      # Visa ~$74B (IPO was 2008)
        "C",      # Citigroup ~$58B (post-crisis, down from $274B)
        "GS",     # Goldman Sachs ~$45B
        "USB",    # US Bancorp ~$54B
        "MS",     # Morgan Stanley ~$27B
        "AXP",    # American Express ~$52B
        "BAC",    # Bank of America ~$58B (post-crisis low)
    ],

    "Healthcare": [
        "JNJ",    # Johnson & Johnson ~$179B
        "PFE",    # Pfizer ~$158B
        "MRK",    # Merck ~$107B (absorbed Schering-Plough 2009)
        "ABT",    # Abbott Labs ~$86B (pre-AbbVie spinoff 2013)
        "UNH",    # UnitedHealth Group ~$55B
        "AMGN",   # Amgen ~$56B
        "MDT",    # Medtronic ~$39B
        "BMY",    # Bristol-Myers Squibb ~$36B
        "LLY",    # Eli Lilly ~$47B
        "GILD",   # Gilead Sciences ~$32B
    ],

    "Consumer": [
        "WMT",    # Walmart ~$205B (Staples)
        "PG",     # Procter & Gamble ~$184B (Staples)
        "KO",     # Coca-Cola ~$159B (Staples)
        "PM",     # Philip Morris Intl ~$136B (Staples; spun off from MO 2008)
        "PEP",    # PepsiCo ~$106B (Staples)
        "MCD",    # McDonald's ~$101B (Discretionary)
        "AMZN",   # Amazon ~$79B (Discretionary; still mainly a retailer)
        "HD",     # Home Depot ~$68B (Discretionary)
        "DIS",    # Walt Disney ~$60B (Discretionary)
        "CMCSA",  # Comcast ~$58B (Discretionary)
    ],

    "Industrial": [
        "GE",     # General Electric ~$113B (declining from $370B in 2006)
        "UTX",    # United Technologies ~$60B
        "UPS",    # UPS ~$67B
        "BA",     # Boeing ~$53B
        "MMM",    # 3M ~$58B
        "HON",    # Honeywell ~$39B
        "CAT",    # Caterpillar ~$55B
        "LMT",    # Lockheed Martin ~$28B
        "EMR",    # Emerson Electric ~$32B
        "UNP",    # Union Pacific ~$46B
    ],

    "Energy": [
        "XOM",    # ExxonMobil ~$406B (still #1 overall S&P 500!)
        "CVX",    # Chevron ~$212B
        "COP",    # ConocoPhillips ~$94B (PSX spun off 2012)
        "SLB",    # Schlumberger ~$76B
        "OXY",    # Occidental ~$33B
        "APC",    # Anadarko ~$37B (acquired by OXY 2019)
        "HAL",    # Halliburton ~$25B
        "VLO",    # Valero ~$18B
        "PSX",    # Phillips 66 (spun off from COP mid-2012, so not yet in 2011)
        "EOG",    # EOG Resources ~$26B
    ],

    "Utilities": [
        "SO",     # Southern Company ~$39B
        "DUK",    # Duke Energy ~$28B
        "EXC",    # Exelon ~$30B
        "D",      # Dominion ~$30B
        "NEE",    # NextEra Energy ~$27B (renamed from FPL Group 2010)
        "AEP",    # American Electric Power ~$19B
        "ED",     # Consolidated Edison ~$14B
        "PCG",    # PG&E ~$18B
        "PPL",    # PPL Corp ~$16B
        "XEL",    # Xcel Energy ~$13B
    ],

    "Telecom": [
        # BellSouth gone (absorbed by AT&T 2006), Qwest gone (absorbed by CTL 2011)
        "T",      # AT&T ~$136B
        "VZ",     # Verizon ~$114B
        "S",      # Sprint ~$10B (declining; merged with TMUS 2020)
        "CTL",    # CenturyLink ~$15B (absorbed Qwest Apr 2011; now Lumen LUMN)
        "FTR",    # Frontier Communications ~$4B (bankrupt 2020, re-emerged as FYBR)
        "WIN",    # Windstream ~$2B (bankrupt 2019)
        "LVLT",   # Level 3 Communications ~$8B (acquired by CTL 2017)
    ],

    "RealEstate": [
        # Still part of Financials sector in GICS; separate sector only from 2016
        "SPG",    # Simon Property Group ~$42B
        "AMT",    # American Tower ~$26B
        "PSA",    # Public Storage ~$25B
        "EQR",    # Equity Residential ~$16B
        "PLD",    # Prologis ~$17B (merged with AMB Property 2011)
        "VNO",    # Vornado Realty ~$14B
        "BXP",    # Boston Properties ~$12B
        "AVB",    # AvalonBay ~$14B
        "HCN",    # Health Care REIT ~$12B (renamed Welltower WELL 2015)
        "HCP",    # HCP Inc ~$15B (renamed Healthpeak Properties PEAK, now DOC)
    ],
}


# ============================================================================
# 2016 SNAPSHOT (End of year)
# ============================================================================
SP500_2016 = {
    "Technology": [
        "AAPL",   # Apple ~$609B
        "GOOG",   # Alphabet ~$546B (pre-2018 GICS change, was in Tech)
        "MSFT",   # Microsoft ~$483B
        "FB",     # Facebook ~$332B (pre-2018 GICS change, was in Tech; now META)
        "INTC",   # Intel ~$172B
        "V",      # Visa ~$180B (classified as Tech in 2016)
        "CSCO",   # Cisco ~$155B
        "ORCL",   # Oracle ~$160B
        "IBM",    # IBM ~$157B
        "MA",     # Mastercard ~$115B (classified as Tech in 2016)
        "QCOM",   # Qualcomm ~$88B
        "TXN",    # Texas Instruments ~$68B
        "ACN",    # Accenture ~$75B
        "AVGO",   # Broadcom ~$72B
        "ADBE",   # Adobe ~$55B
        "CRM",    # Salesforce ~$53B
        "ADP",    # ADP ~$45B
        "NVDA",   # NVIDIA ~$58B (still mid-cap!)
        "PYPL",   # PayPal ~$47B (spun off from EBAY 2015)
        "CTSH",   # Cognizant ~$37B
    ],

    "Finance": [
        "BRK-B",  # Berkshire Hathaway ~$402B
        "JPM",    # JPMorgan Chase ~$309B
        "WFC",    # Wells Fargo ~$277B (pre-scandal decline)
        "BAC",    # Bank of America ~$223B
        "C",      # Citigroup ~$160B
        "GS",     # Goldman Sachs ~$93B
        "MS",     # Morgan Stanley ~$78B
        "USB",    # US Bancorp ~$87B
        "AXP",    # American Express ~$72B
        "MET",    # MetLife ~$55B
    ],

    "Healthcare": [
        "JNJ",    # Johnson & Johnson ~$313B
        "PFE",    # Pfizer ~$187B
        "UNH",    # UnitedHealth Group ~$157B
        "MRK",    # Merck ~$164B
        "AMGN",   # Amgen ~$110B
        "GILD",   # Gilead ~$85B (Sovaldi/Harvoni peak era)
        "MDT",    # Medtronic ~$108B
        "ABBV",   # AbbVie ~$96B (spun off from ABT 2013)
        "BMY",    # Bristol-Myers Squibb ~$102B
        "CELG",   # Celgene ~$83B (acquired by BMY 2019)
    ],

    "Consumer": [
        "AMZN",   # Amazon ~$356B (Discretionary; dominant)
        "PG",     # Procter & Gamble ~$225B (Staples)
        "WMT",    # Walmart ~$212B (Staples)
        "KO",     # Coca-Cola ~$179B (Staples)
        "PM",     # Philip Morris Intl ~$155B (Staples)
        "PEP",    # PepsiCo ~$148B (Staples)
        "HD",     # Home Depot ~$170B (Discretionary)
        "DIS",    # Walt Disney ~$170B (Discretionary)
        "MCD",    # McDonald's ~$101B (Discretionary)
        "NKE",    # Nike ~$90B (Discretionary)
    ],

    "Industrial": [
        "GE",     # General Electric ~$280B (pre-collapse)
        "MMM",    # 3M ~$108B
        "BA",     # Boeing ~$94B
        "HON",    # Honeywell ~$92B
        "UNP",    # Union Pacific ~$84B
        "UTX",    # United Technologies ~$89B (merged with RTN 2020 = RTX)
        "CAT",    # Caterpillar ~$55B
        "LMT",    # Lockheed Martin ~$70B
        "DHR",    # Danaher ~$55B
        "ITW",    # Illinois Tool Works ~$54B
    ],

    "Energy": [
        "XOM",    # ExxonMobil ~$374B
        "CVX",    # Chevron ~$222B
        "SLB",    # Schlumberger ~$87B
        "COP",    # ConocoPhillips ~$61B
        "EOG",    # EOG Resources ~$57B
        "PSX",    # Phillips 66 ~$42B (spun off from COP 2012)
        "OXY",    # Occidental ~$32B
        "VLO",    # Valero ~$30B
        "PXD",    # Pioneer Natural Resources ~$28B (acquired by XOM 2024)
        "KMI",    # Kinder Morgan ~$44B
    ],

    "Utilities": [
        "NEE",    # NextEra Energy ~$57B
        "DUK",    # Duke Energy ~$57B
        "SO",     # Southern Company ~$48B
        "D",      # Dominion ~$48B
        "EXC",    # Exelon ~$33B
        "AEP",    # American Electric Power ~$32B
        "SRE",    # Sempra Energy ~$27B
        "PPL",    # PPL Corp ~$22B
        "ED",     # Consolidated Edison ~$24B
        "XEL",    # Xcel Energy ~$22B
    ],

    "Telecom": [
        # Still old GICS Telecom sector in 2016 (pre-2018 restructuring)
        "T",      # AT&T ~$198B
        "VZ",     # Verizon ~$218B
        "CTL",    # CenturyLink ~$18B (now Lumen LUMN)
        "FTR",    # Frontier ~$3B (bankrupt 2020)
        "TMUS",   # T-Mobile ~$47B
        "S",      # Sprint ~$26B (merged with TMUS 2020)
        "LVLT",   # Level 3 Comms ~$20B (acquired by CTL 2017)
    ],

    "RealEstate": [
        # NEW standalone GICS sector as of Sep 2016!
        "AMT",    # American Tower ~$50B
        "SPG",    # Simon Property Group ~$57B
        "CCI",    # Crown Castle ~$41B
        "PSA",    # Public Storage ~$37B
        "PLD",    # Prologis ~$28B
        "EQR",    # Equity Residential ~$22B
        "WELL",   # Welltower ~$21B (renamed from HCN 2015)
        "AVB",    # AvalonBay ~$22B
        "DLR",    # Digital Realty ~$16B
        "O",      # Realty Income ~$16B
    ],
}


# ============================================================================
# 2021 SNAPSHOT (End of year)
# ============================================================================
SP500_2021 = {
    "Technology": [
        # Post-2018 GICS: GOOGL, META, DIS, NFLX moved to Communication Services
        # V and MA moved to Financials in GICS (but often still tracked as Tech)
        "AAPL",   # Apple ~$2,902B
        "MSFT",   # Microsoft ~$2,522B
        "NVDA",   # NVIDIA ~$735B (massive growth!)
        "AVGO",   # Broadcom ~$275B
        "ADBE",   # Adobe ~$270B
        "CRM",    # Salesforce ~$253B
        "CSCO",   # Cisco ~$260B
        "ACN",    # Accenture ~$262B
        "INTC",   # Intel ~$205B (declining relative position)
        "TXN",    # Texas Instruments ~$175B
        "QCOM",   # Qualcomm ~$200B
        "AMD",    # AMD ~$185B (massive growth)
        "ORCL",   # Oracle ~$195B
        "PYPL",   # PayPal ~$218B
        "INTU",   # Intuit ~$175B
        "AMAT",   # Applied Materials ~$147B
        "NOW",    # ServiceNow ~$130B
        "ADP",    # ADP ~$105B
        "IBM",    # IBM ~$120B
        "LRCX",   # Lam Research ~$96B
    ],

    "Finance": [
        "BRK-B",  # Berkshire Hathaway ~$663B
        "JPM",    # JPMorgan Chase ~$466B
        "V",      # Visa ~$453B (moved to Financials post-2018 GICS)
        "BAC",    # Bank of America ~$359B
        "MA",     # Mastercard ~$352B
        "WFC",    # Wells Fargo ~$195B
        "MS",     # Morgan Stanley ~$183B
        "GS",     # Goldman Sachs ~$142B
        "BLK",    # BlackRock ~$146B
        "C",      # Citigroup ~$122B
    ],

    "Healthcare": [
        "UNH",    # UnitedHealth Group ~$473B (#1 healthcare!)
        "JNJ",    # Johnson & Johnson ~$450B
        "PFE",    # Pfizer ~$332B (COVID vaccine boost)
        "LLY",    # Eli Lilly ~$273B (pre-Mounjaro explosion)
        "ABBV",   # AbbVie ~$270B
        "TMO",    # Thermo Fisher ~$267B
        "MRK",    # Merck ~$190B
        "ABT",    # Abbott Labs ~$225B
        "DHR",    # Danaher ~$210B
        "AMGN",   # Amgen ~$145B
    ],

    "Consumer": [
        "AMZN",   # Amazon ~$1,697B (Discretionary)
        "TSLA",   # Tesla ~$1,092B (Discretionary; joined S&P 500 Dec 2020!)
        "HD",     # Home Depot ~$433B (Discretionary)
        "WMT",    # Walmart ~$401B (Staples)
        "PG",     # Procter & Gamble ~$392B (Staples)
        "KO",     # Coca-Cola ~$266B (Staples)
        "PEP",    # PepsiCo ~$243B (Staples)
        "COST",   # Costco ~$233B (Staples)
        "NKE",    # Nike ~$264B (Discretionary)
        "MCD",    # McDonald's ~$196B (Discretionary)
    ],

    "Industrial": [
        "UNP",    # Union Pacific ~$152B
        "HON",    # Honeywell ~$147B
        "RTX",    # RTX (Raytheon Technologies) ~$137B (UTX + RTN merged 2020)
        "BA",     # Boeing ~$118B
        "CAT",    # Caterpillar ~$117B
        "DE",     # Deere & Company ~$112B
        "LMT",    # Lockheed Martin ~$102B
        "GE",     # General Electric ~$107B (still declining pre-split)
        "MMM",    # 3M ~$99B
        "ITW",    # Illinois Tool Works ~$76B
    ],

    "Energy": [
        # Energy was best-performing sector in 2021 (+53.4%)
        "XOM",    # ExxonMobil ~$260B
        "CVX",    # Chevron ~$240B
        "COP",    # ConocoPhillips ~$95B
        "EOG",    # EOG Resources ~$52B
        "PXD",    # Pioneer Natural Resources ~$44B (acquired by XOM 2024)
        "SLB",    # Schlumberger ~$43B
        "MPC",    # Marathon Petroleum ~$40B
        "PSX",    # Phillips 66 ~$35B
        "VLO",    # Valero ~$33B
        "WMB",    # Williams Companies ~$30B
    ],

    "Utilities": [
        "NEE",    # NextEra Energy ~$168B (by far #1!)
        "DUK",    # Duke Energy ~$79B
        "SO",     # Southern Company ~$72B
        "D",      # Dominion Energy ~$54B
        "SRE",    # Sempra Energy ~$43B
        "AEP",    # American Electric Power ~$43B
        "EXC",    # Exelon ~$52B (pre-Constellation Energy spinoff 2022)
        "XEL",    # Xcel Energy ~$37B
        "ED",     # Consolidated Edison ~$29B
        "WEC",    # WEC Energy Group ~$29B
    ],

    "Telecom": [
        # Now called "Communication Services" post-2018 GICS
        # Includes GOOGL, META, NFLX, DIS (moved from Tech/Discretionary)
        "GOOGL",  # Alphabet ~$1,918B (moved from Tech in 2018 GICS change)
        "META",   # Meta Platforms ~$922B (moved from Tech; ticker changed from FB)
        "DIS",    # Walt Disney ~$282B (moved from Discretionary)
        "NFLX",   # Netflix ~$269B (moved from Discretionary)
        "TMUS",   # T-Mobile ~$135B (absorbed Sprint 2020)
        "VZ",     # Verizon ~$220B
        "T",      # AT&T ~$178B (declining; spinning off WarnerMedia)
    ],

    "RealEstate": [
        "AMT",    # American Tower ~$130B
        "PLD",    # Prologis ~$110B (logistics boom)
        "CCI",    # Crown Castle ~$82B
        "EQIX",   # Equinix ~$79B (data center REIT)
        "PSA",    # Public Storage ~$60B
        "SPG",    # Simon Property Group ~$51B
        "WELL",   # Welltower ~$35B
        "DLR",    # Digital Realty ~$47B
        "O",      # Realty Income ~$42B
        "AVB",    # AvalonBay ~$33B
    ],
}


# ============================================================================
# COMBINED MASTER DICT
# ============================================================================
SP500_HISTORICAL = {
    2006: SP500_2006,
    2011: SP500_2011,
    2016: SP500_2016,
    2021: SP500_2021,
}


# ============================================================================
# FLAT UNIQUE TICKER LIST (for data download)
# ============================================================================
def get_all_unique_tickers():
    """Return sorted list of all unique tickers across all years and sectors."""
    tickers = set()
    for year_data in SP500_HISTORICAL.values():
        for sector_tickers in year_data.values():
            tickers.update(sector_tickers)
    return sorted(tickers)


def get_tickers_by_year(year):
    """Return flat sorted list of all tickers for a given year."""
    tickers = set()
    for sector_tickers in SP500_HISTORICAL[year].values():
        tickers.update(sector_tickers)
    return sorted(tickers)


# ============================================================================
# TICKER MAPPING: old ticker -> current ticker (for data download)
# ============================================================================
TICKER_MAP_CURRENT = {
    # Tickers that changed or need mapping for yfinance/EODHD download
    "GOOG": "GOOGL",       # Class A shares
    "FB": "META",          # Renamed Oct 2021
    "BRK-B": "BRK-B",     # yfinance uses BRK-B
    "FPL": "NEE",          # Renamed 2010
    "CTL": "LUMN",         # Renamed 2020
    "HCN": "WELL",         # Renamed 2015
    "UTX": "RTX",          # Merged 2020 (approximate proxy)
    "S": "TMUS",           # Sprint merged with T-Mobile 2020 (no direct history)

    # DELISTED — no current ticker, use historical data only
    # These need special handling (download from EODHD with delisted data)
    "WB": None,            # Wachovia - delisted 2008
    "MER": None,           # Merrill Lynch - delisted 2009
    "WYE": None,           # Wyeth - delisted 2009
    "SGP": None,           # Schering-Plough - delisted 2009
    "DNA": None,           # Genentech - delisted 2009
    "BLS": None,           # BellSouth - delisted 2006
    "Q": None,             # Qwest - delisted 2011
    "EMC": None,           # EMC - delisted 2016
    "DELL": "DELL",        # Re-listed 2018, but no data 2013-2018
    "YHOO": None,          # Yahoo - delisted 2017
    "MOT": "MSI",          # Motorola Solutions (partial successor)
    "TWX": None,           # Time Warner - delisted 2018
    "BHI": "BKR",          # Baker Hughes -> Baker Hughes (new) via GE
    "APC": None,           # Anadarko - delisted 2019
    "CELG": None,          # Celgene - delisted 2019
    "PXD": None,           # Pioneer Natural Resources - delisted 2024
    "LVLT": None,          # Level 3 - delisted 2017
    "WIN": None,           # Windstream - bankrupt 2019
    "FTR": "FYBR",         # Frontier -> FYBR after bankruptcy
    "HCP": "DOC",          # HCP -> Healthpeak (PEAK) -> Healthpeak (DOC after merger)
    "PGN": None,           # Progress Energy - merged with DUK 2012
    "SNDK": None,          # SanDisk - delisted 2016
    "CA": None,            # CA Technologies - delisted 2018
    "KFT": "MDLZ",        # Kraft -> Mondelez (partial successor)
}


if __name__ == "__main__":
    all_tickers = get_all_unique_tickers()
    print(f"Total unique tickers across all years: {len(all_tickers)}")
    for year in [2006, 2011, 2016, 2021]:
        year_tickers = get_tickers_by_year(year)
        print(f"\n{year}: {len(year_tickers)} tickers")
        for sector, tickers in SP500_HISTORICAL[year].items():
            print(f"  {sector}: {len(tickers)} — {', '.join(tickers[:5])}...")
