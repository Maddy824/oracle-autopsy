"""
Phase 3: The Oracle Trading Environment
Production-grade Gym environment with sophisticated reward engineering
This is where the "Brain" learns to trade without exploiting bugs
"""

import gymnasium as gym
from gymnasium import spaces
import numpy as np
import pandas as pd
from typing import Dict, Tuple, Optional, Any, List
from dataclasses import dataclass, field
import logging
from collections import deque
import warnings
warnings.filterwarnings('ignore')

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    """Record of a single trade"""
    entry_time: int
    entry_price: float
    exit_time: Optional[int] = None
    exit_price: Optional[float] = None
    position_size: float = 0.0
    trade_type: str = "long"  # long or short
    pnl: float = 0.0
    pnl_percent: float = 0.0
    commission_paid: float = 0.0
    slippage_cost: float = 0.0
    holding_period: int = 0
    max_drawdown: float = 0.0
    max_profit: float = 0.0


@dataclass
class MarketRegime:
    """Current market regime detection"""
    volatility_regime: str = "normal"  # low, normal, high, extreme
    trend_regime: str = "neutral"  # bullish, bearish, neutral
    volume_regime: str = "normal"  # low, normal, high
    confidence: float = 0.5


class OracleTradingEnv(gym.Env):
    """
    Professional-grade trading environment with:
    - Realistic market mechanics
    - Sophisticated reward engineering
    - Anti-exploitation measures
    - Risk management constraints
    """
    
    metadata = {'render_modes': ['human', 'ansi']}
    
    def __init__(
        self,
        df: pd.DataFrame,
        initial_balance: float = 10000,
        lookback_window: int = 30,
        # Commission and slippage
        commission: float = 0.001,  # 0.1%
        slippage: float = 0.0005,   # 0.05%
        # Risk management
        max_position_size: float = 0.95,  # Max 95% of capital
        stop_loss: float = 0.02,  # 2% stop loss
        take_profit: float = 0.05,  # 5% take profit
        max_drawdown: float = 0.10,  # 10% max drawdown
        # Reward engineering
        reward_type: str = "sortino_enhanced",
        # Anti-exploitation
        min_holding_period: int = 0,  # Minimum bars to hold
        max_trades_per_episode: int = 100,  # Prevent overtrading
        # Advanced features
        use_context_vectors: bool = True,
        use_market_regime: bool = True,
        render_mode: Optional[str] = None
    ):
        """
        Initialize the Oracle Trading Environment
        
        Args:
            df: DataFrame with price data and features
            initial_balance: Starting capital
            lookback_window: Historical window for observations
            commission: Trading commission (percentage)
            slippage: Slippage cost (percentage)
            max_position_size: Maximum position as fraction of capital
            stop_loss: Stop loss threshold
            take_profit: Take profit threshold
            max_drawdown: Maximum allowed drawdown
            reward_type: Type of reward function
            min_holding_period: Minimum holding period (anti-HFT)
            max_trades_per_episode: Maximum trades allowed
            use_context_vectors: Whether to use TFT context vectors
            use_market_regime: Whether to detect and use market regime
            render_mode: Rendering mode
        """
        super().__init__()
        
        # Data
        self.df = df.fillna(0)
        self.prices = df['Close'].values if 'Close' in df.columns else df['close'].values
        
        # Environment parameters
        self.initial_balance = initial_balance
        self.lookback_window = lookback_window
        self.commission = commission
        self.slippage = slippage
        self.max_position_size = max_position_size
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.max_drawdown = max_drawdown
        self.reward_type = reward_type
        self.min_holding_period = min_holding_period
        self.max_trades_per_episode = max_trades_per_episode
        self.use_context_vectors = use_context_vectors
        self.use_market_regime = use_market_regime
        self.render_mode = render_mode
        
        # Identify feature columns
        self._identify_features()
        
        # Action space: Discrete or Continuous
        # 0: Hold, 1: Buy, 2: Sell, 3: Short, 4: Cover
        self.action_space = spaces.Discrete(5)
        
        # Observation space
        obs_shape = self._get_observation_shape()
        self.observation_space = spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=obs_shape,
            dtype=np.float32
        )
        
        # Episode tracking
        self.reset()
    
    def _identify_features(self):
        """Identify and categorize features in the dataset"""
        all_cols = self.df.columns.tolist()
        
        # Context vector columns
        self.context_cols = [col for col in all_cols if col.startswith('ctx_')]
        
        # Price columns
        price_cols = ['Open', 'High', 'Low', 'Close', 'Volume',
                     'open', 'high', 'low', 'close', 'volume']
        self.price_cols = [col for col in price_cols if col in all_cols]
        
        # Technical indicator columns
        indicator_keywords = ['rsi', 'macd', 'bb', 'atr', 'sma', 'ema', 
                             'volatility', 'momentum', 'obv', 'vwap']
        self.indicator_cols = [col for col in all_cols 
                              if any(keyword in col.lower() 
                                    for keyword in indicator_keywords)]
        
        # Feature columns for observation
        self.feature_cols = []
        
        # Add price features
        self.feature_cols.extend(self.price_cols)
        
        # Add indicators
        self.feature_cols.extend(self.indicator_cols)
        
        # Add context vectors if available
        if self.use_context_vectors and self.context_cols:
            self.feature_cols.extend(self.context_cols)
        
        # Remove duplicates
        self.feature_cols = list(dict.fromkeys(self.feature_cols))
        
        logger.info(f"Identified {len(self.feature_cols)} features")
        logger.info(f"  Context vectors: {len(self.context_cols)}")
        logger.info(f"  Indicators: {len(self.indicator_cols)}")
    
    def _get_observation_shape(self) -> Tuple[int, ...]:
        """Calculate observation space shape"""
        # Base features from data
        n_features = len(self.feature_cols)
        
        # Add position information
        n_features += 5  # position, entry_price, holding_time, unrealized_pnl, position_size
        
        # Add account information  
        n_features += 5  # balance, equity, margin, drawdown, trade_count
        
        # Add market regime if enabled
        if self.use_market_regime:
            n_features += 4  # vol_regime, trend_regime, volume_regime, confidence
        
        return (self.lookback_window, n_features)
    
    def reset(
        self,
        seed: Optional[int] = None,
        options: Optional[dict] = None
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """Reset the environment to initial state"""
        super().reset(seed=seed)
        
        # Account state
        self.balance = self.initial_balance
        self.equity = self.initial_balance
        self.position = 0  # -1: short, 0: flat, 1: long
        self.position_size = 0
        self.entry_price = 0
        self.entry_step = 0
        
        # Episode tracking
        self.current_step = self.lookback_window
        self.done = False
        
        # Performance tracking
        self.trades: List[Trade] = []
        self.current_trade: Optional[Trade] = None
        self.portfolio_values = [self.initial_balance]
        self.returns = []
        self.peak_value = self.initial_balance
        self.max_drawdown_seen = 0
        
        # Anti-exploitation tracking
        self.trade_count = 0
        self.holding_time = 0
        self.last_action = 0
        self.action_history = deque(maxlen=10)
        
        # Market regime
        self.market_regime = self._detect_market_regime()
        
        return self._get_observation(), self._get_info()
    
    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, Dict]:
        """
        Execute one step in the environment
        
        Args:
            action: Trading action to execute
        
        Returns:
            observation, reward, terminated, truncated, info
        """
        # Store previous state
        prev_equity = self.equity
        prev_position = self.position
        
        # Anti-exploitation: Check for rapid trading
        if self._is_exploiting(action):
            action = 0  # Force hold
            exploit_penalty = -0.1
        else:
            exploit_penalty = 0
        
        # Execute action
        trade_reward = self._execute_action(action)
        
        # Update holding time
        if self.position != 0:
            self.holding_time += 1
        else:
            self.holding_time = 0
        
        # Check stop loss and take profit
        self._check_exit_conditions()
        
        # Update equity
        self._update_equity()
        
        # Calculate reward
        step_reward = self._calculate_reward(prev_equity, self.equity)
        total_reward = step_reward + trade_reward + exploit_penalty
        
        # Update tracking
        self.portfolio_values.append(self.equity)
        if prev_equity > 0:
            self.returns.append((self.equity - prev_equity) / prev_equity)
        
        # Update peak and drawdown
        if self.equity > self.peak_value:
            self.peak_value = self.equity
        current_drawdown = (self.peak_value - self.equity) / self.peak_value
        self.max_drawdown_seen = max(self.max_drawdown_seen, current_drawdown)
        
        # Move to next step
        self.current_step += 1
        self.action_history.append(action)
        
        # Check termination conditions
        terminated = self._is_terminated()
        truncated = self.current_step >= len(self.df) - 1
        
        # Update market regime
        if self.current_step % 20 == 0:  # Update every 20 steps
            self.market_regime = self._detect_market_regime()
        
        return self._get_observation(), total_reward, terminated, truncated, self._get_info()
    
    def _execute_action(self, action: int) -> float:
        """
        Execute trading action
        
        Args:
            action: Action to execute
        
        Returns:
            Immediate trade reward
        """
        current_price = self.prices[self.current_step]
        trade_reward = 0
        
        if action == 0:  # Hold
            pass
            
        elif action == 1:  # Buy (Long)
            if self.position <= 0:
                # Close short if exists
                if self.position < 0:
                    trade_reward = self._close_position(current_price)
                
                # Open long
                if self.trade_count < self.max_trades_per_episode:
                    self._open_position(current_price, 1)
                    
        elif action == 2:  # Sell (Close Long)
            if self.position > 0:
                trade_reward = self._close_position(current_price)
                
        elif action == 3:  # Short
            if self.position >= 0:
                # Close long if exists
                if self.position > 0:
                    trade_reward = self._close_position(current_price)
                
                # Open short
                if self.trade_count < self.max_trades_per_episode:
                    self._open_position(current_price, -1)
                    
        elif action == 4:  # Cover (Close Short)
            if self.position < 0:
                trade_reward = self._close_position(current_price)
        
        return trade_reward
    
    def _open_position(self, price: float, direction: int):
        """Open a new position"""
        # Calculate position size with risk management
        max_position_value = self.balance * self.max_position_size
        
        # Adjust for market regime
        if self.market_regime.volatility_regime == "extreme":
            max_position_value *= 0.5  # Half size in extreme volatility
        elif self.market_regime.volatility_regime == "high":
            max_position_value *= 0.75
        
        # Apply slippage
        entry_price = price * (1 + self.slippage * direction)
        
        # Calculate position size
        self.position_size = max_position_value / entry_price
        
        # Pay commission
        commission_cost = max_position_value * self.commission
        self.balance -= commission_cost
        
        # Update state
        self.position = direction
        self.entry_price = entry_price
        self.entry_step = self.current_step
        self.trade_count += 1
        
        # Create trade record
        self.current_trade = Trade(
            entry_time=self.current_step,
            entry_price=entry_price,
            position_size=self.position_size,
            trade_type="long" if direction > 0 else "short",
            commission_paid=commission_cost
        )
    
    def _close_position(self, price: float) -> float:
        """
        Close current position
        
        Returns:
            Trade reward based on P&L
        """
        if self.position == 0 or self.current_trade is None:
            return 0
        
        # Apply slippage
        exit_price = price * (1 - self.slippage * self.position)
        
        # Calculate P&L
        if self.position > 0:  # Long
            pnl = self.position_size * (exit_price - self.entry_price)
        else:  # Short
            pnl = self.position_size * (self.entry_price - exit_price)
        
        pnl_percent = pnl / (self.position_size * self.entry_price)
        
        # Pay commission
        commission_cost = self.position_size * exit_price * self.commission
        pnl -= commission_cost
        
        # Update balance
        self.balance += self.position_size * exit_price - commission_cost
        
        # Record trade
        self.current_trade.exit_time = self.current_step
        self.current_trade.exit_price = exit_price
        self.current_trade.pnl = pnl
        self.current_trade.pnl_percent = pnl_percent
        self.current_trade.holding_period = self.current_step - self.entry_step
        self.current_trade.commission_paid += commission_cost
        
        self.trades.append(self.current_trade)
        
        # Reset position
        self.position = 0
        self.position_size = 0
        self.entry_price = 0
        self.current_trade = None
        self.holding_time = 0
        
        # Calculate trade reward (sophisticated)
        trade_reward = self._calculate_trade_reward(pnl, pnl_percent)
        
        return trade_reward
    
    def _calculate_trade_reward(self, pnl: float, pnl_percent: float) -> float:
        """
        Sophisticated trade reward calculation
        Implements loss aversion and risk-adjusted returns
        """
        if self.reward_type == "simple":
            return pnl_percent * 10
            
        elif self.reward_type == "sortino_enhanced":
            # Base reward
            if pnl > 0:
                # Profit: moderate reward
                base_reward = pnl_percent * 10
                
                # Bonus for good risk/reward
                if pnl_percent > 0.02:  # >2% profit
                    base_reward *= 1.5
                    
            else:
                # Loss: heavy penalty (2x loss aversion)
                base_reward = pnl_percent * 20
                
                # Extra penalty for large losses
                if pnl_percent < -0.01:  # >1% loss
                    base_reward *= 1.5
            
            # Holding period adjustment
            if self.holding_time < 5:
                # Penalty for too quick trades (possible noise trading)
                base_reward *= 0.8
            elif self.holding_time > 50:
                # Small bonus for patience
                base_reward *= 1.1
            
            # Market regime adjustment
            if self.market_regime.volatility_regime == "extreme":
                # In extreme volatility, surviving is rewarded
                if pnl > 0:
                    base_reward *= 1.3
            
            return base_reward
            
        elif self.reward_type == "sharpe":
            # Sharpe-based reward
            if len(self.returns) > 2:
                sharpe = np.mean(self.returns) / (np.std(self.returns) + 1e-10)
                return sharpe + pnl_percent * 5
            else:
                return pnl_percent * 5
        
        else:
            return pnl_percent * 10
    
    def _calculate_reward(self, prev_equity: float, current_equity: float) -> float:
        """
        Calculate step reward based on equity change
        Includes risk penalties and portfolio metrics
        """
        equity_return = (current_equity - prev_equity) / prev_equity if prev_equity > 0 else 0
        
        # Base reward from equity change
        reward = equity_return * 5
        
        # Drawdown penalty
        drawdown_penalty = self.max_drawdown_seen * 10
        reward -= drawdown_penalty
        
        # Volatility penalty (if returns history exists)
        if len(self.returns) > 10:
            recent_vol = np.std(self.returns[-10:])
            vol_penalty = recent_vol * 5
            reward -= vol_penalty
        
        # Survival bonus (not blowing up the account)
        if current_equity > self.initial_balance * 0.9:
            reward += 0.01
        
        return reward
    
    def _check_exit_conditions(self):
        """Check stop loss and take profit conditions"""
        if self.position == 0 or self.current_trade is None:
            return
        
        current_price = self.prices[self.current_step]
        
        # Calculate current P&L
        if self.position > 0:  # Long
            pnl_percent = (current_price - self.entry_price) / self.entry_price
        else:  # Short
            pnl_percent = (self.entry_price - current_price) / self.entry_price
        
        # Check stop loss
        if pnl_percent <= -self.stop_loss:
            self._close_position(current_price)
            
        # Check take profit
        elif pnl_percent >= self.take_profit:
            self._close_position(current_price)
    
    def _update_equity(self):
        """Update current equity value"""
        if self.position != 0 and self.current_trade is not None:
            current_price = self.prices[self.current_step]
            
            if self.position > 0:  # Long
                unrealized_pnl = self.position_size * (current_price - self.entry_price)
            else:  # Short
                unrealized_pnl = self.position_size * (self.entry_price - current_price)
            
            self.equity = self.balance + unrealized_pnl
        else:
            self.equity = self.balance
    
    def _is_exploiting(self, action: int) -> bool:
        """
        Detect exploitation attempts
        Prevents the AI from gaming the system
        """
        # Check for rapid buy-sell patterns
        if len(self.action_history) >= 4:
            recent = list(self.action_history)[-4:]
            # Detect oscillation: buy-sell-buy-sell
            if recent == [1, 2, 1, 2] or recent == [3, 4, 3, 4]:
                return True
        
        # Check minimum holding period
        if self.position != 0 and self.holding_time < self.min_holding_period:
            if action in [2, 4]:  # Trying to close too quickly
                return True
        
        # Check for excessive trading
        if self.trade_count > self.max_trades_per_episode * 0.8:
            if action in [1, 3]:  # Trying to open new positions
                return True
        
        return False
    
    def _detect_market_regime(self) -> MarketRegime:
        """
        Detect current market regime for adaptive behavior
        """
        regime = MarketRegime()
        
        if self.current_step < 60:
            return regime
        
        # Get recent data
        recent_prices = self.prices[max(0, self.current_step-60):self.current_step]
        recent_returns = np.diff(np.log(recent_prices))
        
        # Volatility regime
        vol = np.std(recent_returns) * np.sqrt(252)
        if vol < 0.1:
            regime.volatility_regime = "low"
        elif vol < 0.2:
            regime.volatility_regime = "normal"
        elif vol < 0.4:
            regime.volatility_regime = "high"
        else:
            regime.volatility_regime = "extreme"
        
        # Trend regime
        sma_20 = np.mean(recent_prices[-20:]) if len(recent_prices) >= 20 else recent_prices[-1]
        sma_50 = np.mean(recent_prices[-50:]) if len(recent_prices) >= 50 else sma_20
        
        if sma_20 > sma_50 * 1.02:
            regime.trend_regime = "bullish"
        elif sma_20 < sma_50 * 0.98:
            regime.trend_regime = "bearish"
        else:
            regime.trend_regime = "neutral"
        
        # Confidence based on consistency
        regime.confidence = 1.0 - vol  # Higher vol = lower confidence
        
        return regime
    
    def _is_terminated(self) -> bool:
        """Check if episode should terminate"""
        # Max drawdown exceeded
        if self.max_drawdown_seen > self.max_drawdown:
            logger.info(f"Terminated: Max drawdown {self.max_drawdown_seen:.2%} exceeded")
            return True
        
        # Account blown up
        if self.equity < self.initial_balance * 0.5:
            logger.info(f"Terminated: Account blown up (50% loss)")
            return True
        
        # Bankrupt
        if self.balance <= 0:
            logger.info("Terminated: Bankrupt")
            return True
        
        return False
    
    def _get_observation(self) -> np.ndarray:
        """
        Get current observation
        Includes price data, indicators, context vectors, and account state
        """
        # Get historical window
        start_idx = max(0, self.current_step - self.lookback_window)
        end_idx = self.current_step
        
        # Initialize observation array
        obs_list = []
        
        for i in range(start_idx, end_idx):
            step_obs = []
            
            # Add feature data
            for col in self.feature_cols:
                if col in self.df.columns:
                    step_obs.append(self.df[col].iloc[i])
                else:
                    step_obs.append(0)
            
            # Add position information (constant across lookback)
            if i == end_idx - 1:  # Only current position matters
                step_obs.extend([
                    self.position,
                    self.entry_price / self.prices[i] if self.position != 0 else 0,
                    self.holding_time / 100,  # Normalized
                    self._get_unrealized_pnl() / self.initial_balance,  # Normalized
                    self.position_size / 1000  # Normalized
                ])
            else:
                step_obs.extend([0, 0, 0, 0, 0])
            
            # Add account information
            if i == end_idx - 1:
                step_obs.extend([
                    self.balance / self.initial_balance,
                    self.equity / self.initial_balance,
                    (self.equity - self.balance) / self.initial_balance,  # Margin used
                    self.max_drawdown_seen,
                    self.trade_count / self.max_trades_per_episode
                ])
            else:
                step_obs.extend([1, 1, 0, 0, 0])
            
            # Add market regime
            if self.use_market_regime:
                regime_encoding = [
                    {"low": 0, "normal": 0.5, "high": 0.75, "extreme": 1}[self.market_regime.volatility_regime],
                    {"bearish": -1, "neutral": 0, "bullish": 1}[self.market_regime.trend_regime],
                    {"low": 0, "normal": 0.5, "high": 1}[self.market_regime.volume_regime],
                    self.market_regime.confidence
                ]
                step_obs.extend(regime_encoding)
            
            obs_list.append(step_obs)
        
        # Pad if necessary
        while len(obs_list) < self.lookback_window:
            obs_list.insert(0, obs_list[0] if obs_list else [0] * len(step_obs))
        
        observation = np.array(obs_list, dtype=np.float32)
        
        # Replace NaN and Inf
        observation = np.nan_to_num(observation, nan=0.0, posinf=1e6, neginf=-1e6)
        
        return observation
    
    def _get_unrealized_pnl(self) -> float:
        """Calculate unrealized P&L"""
        if self.position == 0:
            return 0
        
        current_price = self.prices[self.current_step]
        
        if self.position > 0:  # Long
            return self.position_size * (current_price - self.entry_price)
        else:  # Short
            return self.position_size * (self.entry_price - current_price)
    
    def _get_info(self) -> Dict[str, Any]:
        """Get environment info"""
        info = {
            'balance': self.balance,
            'equity': self.equity,
            'position': self.position,
            'total_return': (self.equity - self.initial_balance) / self.initial_balance,
            'max_drawdown': self.max_drawdown_seen,
            'trade_count': self.trade_count,
            'current_step': self.current_step,
            'market_regime': self.market_regime.volatility_regime,
            'holding_time': self.holding_time
        }
        
        # Add trade statistics
        if self.trades:
            winning_trades = [t for t in self.trades if t.pnl > 0]
            losing_trades = [t for t in self.trades if t.pnl <= 0]
            
            info['win_rate'] = len(winning_trades) / len(self.trades)
            info['avg_win'] = np.mean([t.pnl_percent for t in winning_trades]) if winning_trades else 0
            info['avg_loss'] = np.mean([t.pnl_percent for t in losing_trades]) if losing_trades else 0
            info['profit_factor'] = abs(sum(t.pnl for t in winning_trades) / sum(t.pnl for t in losing_trades)) if losing_trades else 0
            
            # Sharpe and Sortino
            if len(self.returns) > 1:
                info['sharpe_ratio'] = np.mean(self.returns) / (np.std(self.returns) + 1e-10) * np.sqrt(252)
                
                downside_returns = [r for r in self.returns if r < 0]
                if downside_returns:
                    downside_std = np.std(downside_returns)
                    info['sortino_ratio'] = np.mean(self.returns) / (downside_std + 1e-10) * np.sqrt(252)
                else:
                    info['sortino_ratio'] = info['sharpe_ratio']
        
        return info
    
    def render(self):
        """Render the environment"""
        if self.render_mode == 'human':
            info = self._get_info()
            print(f"\n{'='*50}")
            print(f"Step: {self.current_step} | Price: ${self.prices[self.current_step]:.2f}")
            print(f"Position: {['Short', 'Flat', 'Long'][self.position+1]} | Holding: {self.holding_time} bars")
            print(f"Balance: ${info['balance']:.2f} | Equity: ${info['equity']:.2f}")
            print(f"Return: {info['total_return']*100:.2f}% | Drawdown: {info['max_drawdown']*100:.2f}%")
            print(f"Trades: {info['trade_count']} | Regime: {info['market_regime']}")
            if 'win_rate' in info:
                print(f"Win Rate: {info['win_rate']*100:.1f}% | Sharpe: {info.get('sharpe_ratio', 0):.2f}")
            print('='*50)
