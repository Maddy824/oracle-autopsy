# ADDED HEADER (2026-11-02): minimal imports and class shell for the verbatim
# add_alpha_factors method below. Full execution needs optional pandas_ta;
# run_case.py executes only the original target's dependency slice via AST.
import logging
import numpy as np
import pandas as pd
import pandas_ta as ta

logger = logging.getLogger(__name__)


class AlphaDataPipeline:
    def add_alpha_factors(self, df: pd.DataFrame, ticker: str) -> pd.DataFrame:
        """
        Feature Engineering: Create the Alpha Factors that give us edge
        These are the signals that separate profitable bots from losers
        
        Args:
            df: Raw OHLCV data
            ticker: Symbol for context-specific features
        
        Returns:
            DataFrame with Alpha Factors added
        """
        logger.info(f"Engineering Alpha Factors for {ticker}...")
        
        # Store original columns
        original_cols = df.columns.tolist()
        
        # ============================================
        # 1. PRICE TRANSFORMATIONS (Stationarity)
        # ============================================
        
        # Log Returns - The foundation of quantitative finance
        df['log_return'] = np.log(df['Close'] / df['Close'].shift(1))
        
        # Multi-period returns for momentum detection
        for period in [5, 10, 20, 60]:
            df[f'return_{period}d'] = df['Close'].pct_change(period)
            df[f'log_return_{period}d'] = np.log(df['Close'] / df['Close'].shift(period))
        
        # Overnight and intraday returns (market microstructure)
        df['overnight_return'] = np.log(df['Open'] / df['Close'].shift(1))
        df['intraday_return'] = np.log(df['Close'] / df['Open'])
        
        # ============================================
        # 2. VOLATILITY INDICATORS (Risk Management)
        # ============================================
        
        # ATR - Average True Range
        df['atr'] = ta.atr(df['High'], df['Low'], df['Close'], 
                           length=self.config['indicators']['atr']['length'])
        
        # Normalized ATR (percentage of price)
        df['atr_percent'] = df['atr'] / df['Close'] * 100
        
        # Historical Volatility (different windows)
        for period in [5, 10, 20, 60]:
            df[f'volatility_{period}d'] = df['log_return'].rolling(window=period).std() * np.sqrt(252)
        
        # Parkinson Volatility (using high-low, more accurate)
        df['parkinson_vol'] = np.sqrt(
            252 * df.apply(lambda x: np.log(x['High']/x['Low'])**2 if x['Low'] > 0 else 0, axis=1)
            .rolling(20).mean() / (4 * np.log(2))
        )
        
        # ============================================
        # 3. TREND INDICATORS
        # ============================================
        
        # RSI - Relative Strength Index
        df['rsi'] = ta.rsi(df['Close'], length=self.config['indicators']['rsi']['length'])
        
        # MACD
        macd = ta.macd(df['Close'], 
                      fast=self.config['indicators']['macd']['fast'],
                      slow=self.config['indicators']['macd']['slow'],
                      signal=self.config['indicators']['macd']['signal'])
        if macd is not None and not macd.empty:
            df = pd.concat([df, macd], axis=1)
        
        # Bollinger Bands
        bbands = ta.bbands(df['Close'], 
                          length=self.config['indicators']['bollinger']['length'],
                          std=self.config['indicators']['bollinger']['std_dev'])
        if bbands is not None and not bbands.empty:
            df = pd.concat([df, bbands], axis=1)
            # Add Bollinger Band position (0 = lower band, 1 = upper band)
            df['bb_position'] = (df['Close'] - df[f"BBL_{self.config['indicators']['bollinger']['length']}_{float(self.config['indicators']['bollinger']['std_dev'])}"]) / \
                               (df[f"BBU_{self.config['indicators']['bollinger']['length']}_{float(self.config['indicators']['bollinger']['std_dev'])}"] - 
                                df[f"BBL_{self.config['indicators']['bollinger']['length']}_{float(self.config['indicators']['bollinger']['std_dev'])}"])
        
        # Moving Averages
        df['sma_20'] = ta.sma(df['Close'], length=self.config['indicators']['sma']['short'])
        df['sma_50'] = ta.sma(df['Close'], length=self.config['indicators']['sma']['medium'])
        df['sma_200'] = ta.sma(df['Close'], length=self.config['indicators']['sma']['long'])
        
        # Price relative to moving averages
        df['price_to_sma20'] = df['Close'] / df['sma_20'] - 1
        df['price_to_sma50'] = df['Close'] / df['sma_50'] - 1
        df['price_to_sma200'] = df['Close'] / df['sma_200'] - 1
        
        # ============================================
        # 4. VOLUME INDICATORS (Smart Money Flow)
        # ============================================
        
        if self.config['indicators']['obv']['enabled']:
            df['obv'] = ta.obv(df['Close'], df['Volume'])
            df['obv_sma'] = df['obv'].rolling(20).mean()
            df['obv_divergence'] = df['obv'] / df['obv_sma'] - 1
        
        if self.config['indicators']['vwap']['enabled']:
            df['vwap'] = ta.vwap(df['High'], df['Low'], df['Close'], df['Volume'])
            df['price_to_vwap'] = df['Close'] / df['vwap'] - 1
        
        # Volume patterns
        df['volume_sma'] = df['Volume'].rolling(20).mean()
        df['volume_ratio'] = df['Volume'] / df['volume_sma']
        df['dollar_volume'] = df['Volume'] * df['Close']
        
        # ============================================
        # 5. MARKET MICROSTRUCTURE (HFT Signals)
        # ============================================
        
        # High-Low spread (volatility proxy)
        df['hl_spread'] = (df['High'] - df['Low']) / df['Close']
        
        # Close position in daily range
        df['close_position'] = (df['Close'] - df['Low']) / (df['High'] - df['Low'] + 1e-10)
        
        # Gap indicators
        df['gap'] = df['Open'] / df['Close'].shift(1) - 1
        df['gap_filled'] = ((df['Low'] <= df['Close'].shift(1)) & (df['gap'] > 0)) | \
                          ((df['High'] >= df['Close'].shift(1)) & (df['gap'] < 0))
        
        # ============================================
        # 6. PATTERN RECOGNITION (Price Action)
        # ============================================
        
        # Candlestick patterns
        df['body'] = abs(df['Close'] - df['Open']) / df['Open']
        df['upper_shadow'] = (df['High'] - df[['Close', 'Open']].max(axis=1)) / df['Open']
        df['lower_shadow'] = (df[['Close', 'Open']].min(axis=1) - df['Low']) / df['Open']
        
        # Doji detection (indecision)
        df['is_doji'] = (df['body'] < 0.001).astype(int)
        
        # Hammer/Shooting Star
        df['is_hammer'] = ((df['lower_shadow'] > 2 * df['body']) & 
                          (df['upper_shadow'] < df['body'])).astype(int)
        
        # ============================================
        # 7. REGIME DETECTION (Market State)
        # ============================================
        
        # Volatility regime
        vol_percentile = df['volatility_20d'].rolling(252).rank(pct=True)
        df['vol_regime'] = pd.cut(vol_percentile, bins=[0, 0.33, 0.67, 1.0], 
                                  labels=['low_vol', 'medium_vol', 'high_vol'])
        
        # Trend regime
        df['trend_strength'] = (df['sma_20'] - df['sma_50']) / df['sma_50']
        df['is_uptrend'] = (df['sma_20'] > df['sma_50']).astype(int)
        
        # ============================================
        # 8. CYCLICAL FEATURES (Time Patterns)
        # ============================================
        
        # Day of week (some assets have patterns)
        df['day_of_week'] = df.index.dayofweek
        df['is_monday'] = (df['day_of_week'] == 0).astype(int)
        df['is_friday'] = (df['day_of_week'] == 4).astype(int)
        
        # Month patterns
        df['month'] = df.index.month
        df['is_month_end'] = df.index.is_month_end.astype(int)
        df['is_quarter_end'] = df.index.is_quarter_end.astype(int)
        
        # ============================================
        # 9. TARGET VARIABLES (What we predict)
        # ============================================
        
        # Future returns (for supervised learning)
        df['target_return_1d'] = df['log_return'].shift(-1)
        df['target_return_5d'] = df['log_return'].rolling(5).mean().shift(-5)
        
        # Future volatility (for risk prediction)
        df['target_volatility_5d'] = df['log_return'].rolling(5).std().shift(-5) * np.sqrt(252)
        
        # Classification targets
        df['target_direction_1d'] = (df['target_return_1d'] > 0).astype(int)
        df['target_direction_5d'] = (df['target_return_5d'] > 0).astype(int)
        
        # ============================================
        # 10. FEATURE QUALITY CHECKS
        # ============================================
        
        # Check for infinite values
        inf_cols = df.columns[df.isin([np.inf, -np.inf]).any()].tolist()
        if inf_cols:
            logger.warning(f"Infinite values found in columns: {inf_cols}")
            df = df.replace([np.inf, -np.inf], np.nan)
        
        # Log feature statistics
        logger.info(f"✓ Created {len(df.columns) - len(original_cols)} Alpha Factors")
        logger.info(f"  Total features: {len(df.columns)}")
        logger.info(f"  NaN percentage: {df.isna().sum().sum() / (len(df) * len(df.columns)) * 100:.2f}%")
        
        return df
