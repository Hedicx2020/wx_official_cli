"""(module, method) -> parquet 文件名 映射。

直接搬自 gh_quant_ui/api/main.py 的 PARQUET_NAME_MAP + _resolve_parquet。
"""

from __future__ import annotations


PARQUET_NAME_MAP: dict[tuple[str, str], str] = {
    ("stock", "stock_code"):              "ashare_stock.parquet",
    ("stock", "stock_price"):             "ashare_stock_price.parquet",
    ("stock", "stock_price_forward"):     "ashare_stock_price_forward.parquet",
    ("stock", "stock_price_backward"):    "ashare_stock_price_backward.parquet",
    ("stock", "stock_trade"):             "ashare_stock_trade.parquet",
    ("stock", "stock_value"):             "ashare_stock_value.parquet",
    ("stock", "stock_limit"):             "ashare_stock_limit.parquet",
    ("stock", "stock_st"):                "ashare_stock_st.parquet",
    ("stock", "stock_suspend"):           "ashare_stock_suspend.parquet",
    ("stock", "stock_industry"):          "ashare_stock_industry.parquet",
    ("stock", "hk_stock_quote"):          "hkshare_stock_quote.parquet",
    ("stock", "us_stock_quote"):          "usshare_stock_quote.parquet",
    ("stock", "stock_balance"):           "ashare_stock_balance.parquet",
    ("stock", "stock_income"):            "ashare_stock_income.parquet",
    ("stock", "stock_income_q"):          "ashare_stock_income_q.parquet",
    ("stock", "stock_cashflow"):          "ashare_stock_cashflow.parquet",
    ("stock", "stock_cashflow_q"):        "ashare_stock_cashflow_q.parquet",
    ("stock", "stock_equity"):            "ashare_stock_equity.parquet",
    ("index", "index_code"):              "ashare_index.parquet",
    ("index", "index_price"):             "ashare_index_price.parquet",
    ("index", "index_trade"):             "ashare_index_trade.parquet",
    ("index", "index_value"):             "ashare_index_value.parquet",
    ("index", "index_components"):        "ashare_index_components.parquet",
    ("index", "index_basicinfo"):         "ashare_index_basicinfo.parquet",
    ("index", "csiindex_trade"):          "ashare_csiindex_trade.parquet",
    ("index", "industry_index"):          "ashare_index_industry.parquet",
    ("index", "index_innercode"):         "ashare_index_innercode.parquet",
    ("index", "osindex_price"):           "osshare_index_price.parquet",
    ("index", "hkindex_price"):           "hkshare_index_price.parquet",
    ("fund", "fund_code"):                "fund_code.parquet",
    ("fund", "fund_netvalue"):            "fund_netvalue.parquet",
    ("fund", "fund_stock_portfolio"):     "fund_stock_portfolio.parquet",
    ("fund", "fund_keystock"):            "fund_keystock.parquet",
    ("fund", "fund_assetallocation"):     "fund_assetallocation.parquet",
    ("fund", "fund_alpha"):               "fund_alpha.parquet",
    ("fund", "fund_sharperatio"):         "fund_sharperatio.parquet",
    ("fund", "fund_maxdrawdown"):         "fund_maxdrawdown.parquet",
    ("fund", "fund_managernew"):          "fund_managernew.parquet",
    ("fund", "fund_benchmarkgrowthrate"): "fund_benchmarkgrowthrate.parquet",
    ("fund", "fund_bond_portfolio"):      "fund_bond_portfolio.parquet",
    ("fund", "fund_chargerate"):          "fund_chargerate.parquet",
    ("fund", "fund_tradeinfo"):           "fund_tradeinfo.parquet",
    ("fund", "fund_announcement"):        "fund_announcement.parquet",
    ("fund", "fund_carhartperfatrb"):     "fund_carhartperfatrb.parquet",
    ("fund", "fund_etf_price"):           "fund_etf_price.parquet",
    ("fund", "fund_etf_iopv"):            "fund_etf_iopv.parquet",
    ("fund", "fund_qdii_portfolio"):      "fund_qdii_portfolio.parquet",
    ("fund", "fund_qdii_asset_allocation"): "fund_qdii_asset_allocation.parquet",
    ("future", "futures_contract"):       "futures_contract.parquet",
    ("future", "commodity_future_price"): "commodity_future_price.parquet",
    ("future", "financial_future_price"): "financial_future_price.parquet",
    ("future", "member_rank"):            "member_rank.parquet",
    ("bond", "bond_code"):                "bond_code.parquet",
    ("bond", "bond_basic_info"):          "bond_basic_info.parquet",
    ("bond", "bond_yield_curve"):         "bond_yield_curve.parquet",
    ("bond", "bond_shibor"):              "bond_shibor.parquet",
    ("bond", "bond_exchange_quote"):      "bond_exchange_quote.parquet",
    ("bond", "bond_interbank_quote"):     "bond_interbank_quote.parquet",
    ("bond", "bond_otc_quote"):           "bond_otc_quote.parquet",
    ("bond", "bond_cb_valuation"):        "bond_cb_valuation.parquet",
    ("bond", "bond_csi_valuation"):       "bond_csi_valuation.parquet",
    ("bond", "bond_shch_valuation"):      "bond_shch_valuation.parquet",
    ("bond", "bond_cashflow"):            "bond_cashflow.parquet",
    ("bond", "convertible_bond_basic"):   "convertible_bond_basic.parquet",
    ("bond", "convertible_bond_quote"):   "convertible_bond_quote.parquet",
    ("bond", "convertible_bond_convert_info"):  "convertible_bond_convert_info.parquet",
    ("bond", "convertible_bond_convert_price"): "convertible_bond_convert_price.parquet",
    ("bond", "bond_index_info"):          "bond_index_info.parquet",
    ("bond", "bond_index_quote"):         "bond_index_quote.parquet",
    ("bond", "bond_index_component"):     "bond_index_component.parquet",
    ("bond", "bond_rating"):              "bond_rating.parquet",
    ("bond", "bond_issuer_rating"):       "bond_issuer_rating.parquet",
    ("bond", "bond_default"):             "bond_default.parquet",
    ("bond", "bond_announcement"):        "bond_announcement.parquet",
    ("macro", "indicator_main"):          "macro_indicator_main.parquet",
    ("macro", "indicator"):               "macro_indicator.parquet",
    ("macro", "cpi"):                     "macro_cpi.parquet",
    ("macro", "ppi"):                     "macro_ppi.parquet",
    ("macro", "gdp"):                     "macro_gdp.parquet",
    ("macro", "pmi"):                     "macro_pmi.parquet",
    ("macro", "money_supply"):            "macro_money_supply.parquet",
    ("macro", "social_financing"):        "macro_social_financing.parquet",
    ("macro", "lpr"):                     "macro_lpr.parquet",
    ("macro", "trade"):                   "macro_trade.parquet",
    ("macro", "industrial_production"):   "macro_industrial_production.parquet",
    ("macro", "fixed_asset_investment"):  "macro_fixed_asset_investment.parquet",
}


def resolve_parquet_name(module: str, method: str, params: dict | None = None) -> str:
    """复刻 main.py 的 _resolve_parquet：stock_price 按 adj_type 走不同文件、
    trade/trade_date 按 market 走 {market}_tradeday.parquet。
    """
    params = params or {}
    if module == "stock" and method == "stock_price":
        adj = params.get("adj_type")
        if adj == "forward":
            return "ashare_stock_price_forward.parquet"
        if adj == "backward":
            return "ashare_stock_price_backward.parquet"
        return "ashare_stock_price.parquet"
    if module == "trade" and method == "trade_date":
        market = params.get("market") or "ashare"
        return f"{market}_tradeday.parquet"
    return PARQUET_NAME_MAP.get((module, method), "")


def known_modules() -> list[str]:
    return sorted({m for m, _ in PARQUET_NAME_MAP} | {"trade"})


def known_methods(module: str) -> list[str]:
    methods = {meth for mod, meth in PARQUET_NAME_MAP if mod == module}
    if module == "trade":
        methods.add("trade_date")
    return sorted(methods)
