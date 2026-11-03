"""Import manually downloaded cash-market daily CSVs; no NSE network calls.

Accept legacy bhavcopy and UDiFF layouts; filter the EQ series. Date-only
exchange fields denote midnight Asia/Kolkata. Preserve known auxiliary fields
only as source-file provenance, not prices; reject unknown column names.
"""

import pandas as pd

from autopsy.data.schedule import combine_prices, with_schedule


_OLD = dict(zip(("SYMBOL", "OPEN", "HIGH", "LOW", "CLOSE", "TOTTRDQTY", "TIMESTAMP"),
                ("symbol", "open", "high", "low", "close", "volume", "time")))
_NEW = dict(zip(("TckrSymb", "OpnPric", "HghPric", "LwPric", "ClsPric", "TtlTradgVol", "TradDt"),
                ("symbol", "open", "high", "low", "close", "volume", "time")))
_OLD_EXTRA = {"SERIES", "LAST", "PREVCLOSE", "TOTTRDVAL", "TOTALTRADES", "ISIN"}
_NEW_EXTRA = set("BizDt Sgmt Src FinInstrmTp FinInstrmId ISIN SctySrs XpryDt FininstrmActlXpryDt "
                 "StrkPric OptnTp FinInstrmNm LastPric PrvsClsgPric UndrlygPric SttlmPric OpnIntrst "
                 "ChngInOpnIntrst TtlTrfVal TtlNbOfTxsExctd SsnId NewBrdLotQty Rmks Rsvd1 Rsvd2 "
                 "Rsvd3 Rsvd4".split())


def load_bhavcopy(paths):
    frames = []
    for path in paths:
        table = pd.read_csv(path)
        table.columns = table.columns.str.strip()
        # Legacy downloads may end each row with a trailing delimiter.
        table = table.drop(columns=[c for c in table if c.startswith("Unnamed:") and table[c].isna().all()])
        mapping, extra, series, date_format = ((_NEW, _NEW_EXTRA, "SctySrs", "%Y-%m-%d")
            if "TckrSymb" in table else (_OLD, _OLD_EXTRA, "SERIES", "%d-%b-%Y"))
        unknown = set(table) - set(mapping) - extra
        missing = set(mapping) - set(table)
        if unknown or missing or not table.columns.is_unique:
            raise ValueError(f"bhavcopy columns: unknown={sorted(unknown)}, missing={sorted(missing)}")
        if series in table:
            table = table[table[series].astype(str).str.strip() == "EQ"]
        frame = table[list(mapping)].rename(columns=mapping)
        dates = pd.to_datetime(frame.pop("time").astype(str).str.strip(), format=date_format)
        frame.index = pd.DatetimeIndex(dates).tz_localize("Asia/Kolkata").rename("time")
        frame["symbol"] = frame.symbol.astype(str).str.strip()
        for name in ("open", "high", "low", "close", "volume"):
            frame[name] = pd.to_numeric(frame[name], errors="raise")
        frames.append(with_schedule(frame, "1D"))
    return combine_prices(frames)
