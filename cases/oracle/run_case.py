"""Reproduce Oracle's accounting, feature leakage and drawdown bugs offline.

Run from the repository root: .venv/bin/python -m cases.oracle.run_case
"""

import ast
from dataclasses import asdict
from functools import lru_cache
import json
from pathlib import Path
import warnings

import numpy as np
import pandas as pd

from autopsy.adapters.gym import record_gym_run
from autopsy.checks.ledger_check import check_ledger
from autopsy.checks.lookahead import check_lookahead
from autopsy.ledger import replay
from autopsy.types import Fill


def flat_prices() -> pd.DataFrame:
    """Invented daily OHLCV; no exchange data or market calendar claims."""
    return pd.DataFrame({
        "symbol": "ORACLE_SYNTH", "open": 100.0, "high": 100.0,
        "low": 100.0, "close": 100.0, "volume": 1000.0,
    }, index=pd.date_range("2025-01-01", periods=500, freq="D", tz="Asia/Kolkata"))


@lru_cache(maxsize=1)
def _target_code():
    """Compile original assignments, not a reimplementation of the target.

    The copied method also builds unrelated pandas_ta indicators. Its target
    depends solely on Close -> log_return -> target_volatility_5d. Execute that
    exact dependency slice without importing the ingestion module/pandas_ta.
    Fail closed if the two expected assignments are absent or duplicated.
    """
    path = Path(__file__).parent / "original" / "features.py"
    tree = ast.parse(path.read_text(), filename=str(path))
    method = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == "add_alpha_factors")
    names = ["log_return", "target_volatility_5d"]
    assignments = []
    for name in names:
        matches = [node for node in method.body if isinstance(node, ast.Assign)
                   and len(node.targets) == 1
                   and isinstance(node.targets[0], ast.Subscript)
                   and isinstance(node.targets[0].value, ast.Name)
                   and node.targets[0].value.id == "df"
                   and isinstance(node.targets[0].slice, ast.Constant)
                   and node.targets[0].slice.value == name]
        if len(matches) != 1:
            raise ValueError(f"expected one original assignment to {name}")
        assignments.extend(matches)
    return compile(ast.Module(body=assignments, type_ignores=[]), str(path), "exec")


def oracle_features(prices: pd.DataFrame) -> pd.DataFrame:
    """Run the copied target dependency slice, preserving NaNs for the audit."""
    df = prices.rename(columns={name: name.title() for name in
                               ("open", "high", "low", "close", "volume")}).copy()
    exec(_target_code(), {"np": np, "df": df})
    return df[["log_return", "target_volatility_5d"]]


def scripted_policy(_observation, step: int) -> int:
    """Three longs, then one short; each closes exactly ten bars after entry."""
    if step in (0, 20, 40):
        return 1  # Buy
    if step in (10, 30, 50):
        return 2  # Sell/close long
    if step == 60:
        return 3  # Short
    if step == 70:
        return 4  # Cover
    return 0  # Hold


class OracleFillExtractor:
    """Read actual Trade records, including forced exits and same-bar reversals.

    Never derive executions from requested actions or broken balance deltas.
    Reject fractional quantities instead of silently rounding foreign fills.
    """

    def __init__(self):
        self.entries = set()
        self.exits = set()

    def __call__(self, env, _info) -> list[Fill]:
        fills = []
        trades = list(env.trades)
        if env.current_trade is not None:
            trades.append(env.current_trade)
        for trade in trades:
            key = id(trade)
            qty = float(trade.position_size)
            if not np.isfinite(qty) or not qty.is_integer() or qty <= 0:
                raise ValueError("Oracle fill quantity must be positive whole shares; no rounding")
            long = trade.trade_type == "long"
            exit_fee = (qty * trade.exit_price * env.commission
                        if trade.exit_time is not None else 0.0)
            if key not in self.entries:
                fills.append(Fill(env.df.index[trade.entry_time], "ORACLE_SYNTH",
                                  "BUY" if long else "SELL", int(qty), trade.entry_price,
                                  trade.commission_paid - exit_fee))
                self.entries.add(key)
            if trade.exit_time is not None and key not in self.exits:
                fills.append(Fill(env.df.index[trade.exit_time], "ORACLE_SYNTH",
                                  "SELL" if long else "BUY", int(qty), trade.exit_price, exit_fee))
                self.exits.add(key)
        return fills


def oracle_equity(env, _info) -> tuple[pd.Timestamp, float]:
    # step() values equity before incrementing current_step. After reset this
    # names the final warmup bar, on which the account is still at start cash.
    return env.df.index[env.current_step - 1], float(env.equity)


def run_oracle_case() -> dict:
    # Oracle installs a global ignore-warnings filter on import. Preserve its
    # bytes without letting that import hide warnings in Autopsy or its tests.
    with warnings.catch_warnings():
        from cases.oracle.original.oracle_env import OracleTradingEnv
    from cases.oracle.original.metrics import TradingMetrics

    prices = flat_prices()
    features = oracle_features(prices)
    frame = prices.rename(columns={name: name.title() for name in
                                   ("open", "high", "low", "close", "volume")})
    frame = frame.join(features)
    # Placeholder TFT context: no model, training or downloaded weights.
    frame["ctx_0"] = 0.0
    frame["ctx_1"] = 0.0
    env = OracleTradingEnv(frame, initial_balance=10_000.0, lookback_window=30,
                           commission=0.0, slippage=0.0, max_position_size=1.0,
                           reward_type="simple")
    env.audit_prices = prices
    try:
        record = record_gym_run(env, scripted_policy, OracleFillExtractor(), oracle_equity)
        observation_features = list(env.feature_cols)
    finally:
        env.close()

    # A separate declining probe exposes the metric bug; a flat probe cannot.
    # Keep the local formula here until the statistics module in Task 7 exists.
    drawdown_probe = pd.Series([100.0, 90.0, 80.0])
    return {
        "ledger": check_ledger(record),
        "lookahead": check_lookahead(oracle_features, prices),
        "oracle_drawdown": float(TradingMetrics.max_drawdown(drawdown_probe)),
        "true_drawdown": float((drawdown_probe / drawdown_probe.cummax() - 1).min()),
        "record": record,
        "input_prices": prices,
        "reference_equity": replay(record.fills, record.prices, record.start_cash).equity,
        "observation_features": observation_features,
    }


if __name__ == "__main__":
    case = run_oracle_case()
    print(json.dumps({
        "start_equity": case["record"].start_cash,
        "reported_final_equity": float(case["record"].reported_equity.iloc[-1]),
        "reference_final_equity": float(case["reference_equity"].iloc[-1]),
        "ledger": asdict(case["ledger"]),
        "lookahead": asdict(case["lookahead"]),
        "oracle_drawdown": case["oracle_drawdown"],
        "true_drawdown": case["true_drawdown"],
    }, default=str, indent=2))
