"""
Performance metrics and evaluation utilities
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional


class TradingMetrics:
    """Calculate comprehensive trading performance metrics"""
    
    @staticmethod
    def calculate_returns(prices: pd.Series) -> pd.Series:
        """Calculate simple returns"""
        return prices.pct_change()
    
    @staticmethod
    def calculate_log_returns(prices: pd.Series) -> pd.Series:
        """Calculate log returns"""
        return np.log(prices / prices.shift(1))
    
    @staticmethod
    def sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.02) -> float:
        """
        Calculate Sharpe ratio
        
        Args:
            returns: Series of returns
            risk_free_rate: Annual risk-free rate
        
        Returns:
            Annualized Sharpe ratio
        """
        excess_returns = returns - risk_free_rate / 252
        return np.sqrt(252) * excess_returns.mean() / returns.std() if returns.std() > 0 else 0
    
    @staticmethod
    def sortino_ratio(returns: pd.Series, risk_free_rate: float = 0.02) -> float:
        """
        Calculate Sortino ratio
        
        Args:
            returns: Series of returns
            risk_free_rate: Annual risk-free rate
        
        Returns:
            Annualized Sortino ratio
        """
        excess_returns = returns - risk_free_rate / 252
        downside_returns = returns[returns < 0]
        downside_std = downside_returns.std() if len(downside_returns) > 0 else 0.001
        return np.sqrt(252) * excess_returns.mean() / downside_std if downside_std > 0 else 0
    
    @staticmethod
    def max_drawdown(prices: pd.Series) -> float:
        """
        Calculate maximum drawdown
        
        Args:
            prices: Series of prices or portfolio values
        
        Returns:
            Maximum drawdown as a percentage
        """
        cumulative = (1 + prices.pct_change()).cumprod()
        running_max = cumulative.expanding().max()
        drawdown = (cumulative - running_max) / running_max
        return drawdown.min()
    
    @staticmethod
    def calmar_ratio(returns: pd.Series, prices: pd.Series) -> float:
        """
        Calculate Calmar ratio (return / max drawdown)
        
        Args:
            returns: Series of returns
            prices: Series of prices
        
        Returns:
            Calmar ratio
        """
        annual_return = (1 + returns.mean()) ** 252 - 1
        max_dd = abs(TradingMetrics.max_drawdown(prices))
        return annual_return / max_dd if max_dd > 0 else 0
    
    @staticmethod
    def win_rate(trades: List[Dict]) -> float:
        """
        Calculate win rate from trades
        
        Args:
            trades: List of trade dictionaries with 'pnl' key
        
        Returns:
            Win rate as percentage
        """
        if not trades:
            return 0
        winning_trades = sum(1 for trade in trades if trade['pnl'] > 0)
        return winning_trades / len(trades)
    
    @staticmethod
    def profit_factor(trades: List[Dict]) -> float:
        """
        Calculate profit factor (gross profit / gross loss)
        
        Args:
            trades: List of trade dictionaries with 'pnl' key
        
        Returns:
            Profit factor
        """
        if not trades:
            return 0
        gross_profit = sum(trade['pnl'] for trade in trades if trade['pnl'] > 0)
        gross_loss = abs(sum(trade['pnl'] for trade in trades if trade['pnl'] < 0))
        return gross_profit / gross_loss if gross_loss > 0 else float('inf') if gross_profit > 0 else 0
    
    @staticmethod
    def calculate_all_metrics(
        portfolio_values: pd.Series,
        trades: Optional[List[Dict]] = None,
        risk_free_rate: float = 0.02
    ) -> Dict[str, float]:
        """
        Calculate all performance metrics
        
        Args:
            portfolio_values: Series of portfolio values
            trades: Optional list of trades
            risk_free_rate: Annual risk-free rate
        
        Returns:
            Dictionary of all metrics
        """
        returns = TradingMetrics.calculate_returns(portfolio_values)
        
        metrics = {
            'total_return': (portfolio_values.iloc[-1] / portfolio_values.iloc[0] - 1) * 100,
            'annual_return': ((portfolio_values.iloc[-1] / portfolio_values.iloc[0]) ** (252 / len(portfolio_values)) - 1) * 100,
            'sharpe_ratio': TradingMetrics.sharpe_ratio(returns, risk_free_rate),
            'sortino_ratio': TradingMetrics.sortino_ratio(returns, risk_free_rate),
            'max_drawdown': TradingMetrics.max_drawdown(portfolio_values) * 100,
            'calmar_ratio': TradingMetrics.calmar_ratio(returns, portfolio_values),
            'volatility': returns.std() * np.sqrt(252) * 100,
            'skewness': returns.skew(),
            'kurtosis': returns.kurtosis()
        }
        
        if trades:
            metrics['win_rate'] = TradingMetrics.win_rate(trades) * 100
            metrics['profit_factor'] = TradingMetrics.profit_factor(trades)
            metrics['num_trades'] = len(trades)
            metrics['avg_trade_pnl'] = np.mean([t['pnl'] for t in trades]) if trades else 0
        
        return metrics
    
    @staticmethod
    def print_metrics(metrics: Dict[str, float]):
        """Pretty print metrics"""
        print("\n" + "="*50)
        print("PERFORMANCE METRICS")
        print("="*50)
        
        print("\n📈 Returns:")
        print(f"  Total Return:     {metrics.get('total_return', 0):.2f}%")
        print(f"  Annual Return:    {metrics.get('annual_return', 0):.2f}%")
        
        print("\n📊 Risk-Adjusted:")
        print(f"  Sharpe Ratio:     {metrics.get('sharpe_ratio', 0):.3f}")
        print(f"  Sortino Ratio:    {metrics.get('sortino_ratio', 0):.3f}")
        print(f"  Calmar Ratio:     {metrics.get('calmar_ratio', 0):.3f}")
        
        print("\n⚠️ Risk:")
        print(f"  Max Drawdown:     {metrics.get('max_drawdown', 0):.2f}%")
        print(f"  Volatility:       {metrics.get('volatility', 0):.2f}%")
        print(f"  Skewness:         {metrics.get('skewness', 0):.3f}")
        print(f"  Kurtosis:         {metrics.get('kurtosis', 0):.3f}")
        
        if 'num_trades' in metrics:
            print("\n💼 Trading:")
            print(f"  Number of Trades: {metrics.get('num_trades', 0)}")
            print(f"  Win Rate:         {metrics.get('win_rate', 0):.2f}%")
            print(f"  Profit Factor:    {metrics.get('profit_factor', 0):.2f}")
            print(f"  Avg Trade P&L:    ${metrics.get('avg_trade_pnl', 0):.2f}")
