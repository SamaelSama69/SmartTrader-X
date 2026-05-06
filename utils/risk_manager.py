"""
Risk Manager - Enforces risk limits across all trading operations
Reads risk parameters from config and validates every trade
"""
import logging
from typing import Dict, Optional
from datetime import datetime, date, timedelta
from config import (
    MAX_POSITION_PCT, MAX_DRAWDOWN_PCT, INITIAL_CAPITAL,
    TRANSACTION_COST_BPS
)

logger = logging.getLogger(__name__)


class RiskManager:
    """Centralized risk management for all trading operations"""

    def __init__(self, initial_capital: float = None):
        self.initial_capital = initial_capital or INITIAL_CAPITAL
        self.current_capital = self.initial_capital
        self.max_position_pct = MAX_POSITION_PCT
        self.max_drawdown_pct = MAX_DRAWDOWN_PCT
        self.daily_loss_limit_pct = 0.02  # 2% daily loss limit
        self.max_open_positions = 10
        self.max_sector_exposure_pct = 0.25 # Max 25% per sector

        self.daily_start_capital = self.current_capital
        self.last_reset_date = date.today()
        self.open_positions = {}  # ticker -> {shares, entry_price, side, sector}
        self.trade_history = []   # rolling history for circuit breakers
        self.peak_capital = self.initial_capital
        self.trading_enabled = True

    def sync_with_manager(self, paper_mgr_positions: List[Dict]):
        """Synchronize risk monitor state with actual open paper trades"""
        self.open_positions = {}
        for pos in paper_mgr_positions:
            self.open_positions[pos['ticker']] = {
                'shares': pos['shares'],
                'entry_price': pos['entry_price'],
                'side': pos['signal'],
                'sector': pos.get('sector', 'UNKNOWN')
            }
        # Recalculate current capital based on initial minus invested
        invested = sum(p['shares'] * p['entry_price'] for p in self.open_positions.values())
        # Simplified: assumes cash = initial - invested (in production, track cash explicitly)
        self.current_capital = self.initial_capital - invested 
        logger.info(f"Risk Monitor synced: {len(self.open_positions)} positions tracked.")

    def check_trade(self, ticker: str, shares: int, price: float, sector: str = "UNKNOWN") -> Dict:
        """Check if a trade is allowed under risk rules"""
        # Daily reset logic
        if date.today() > self.last_reset_date:
            self.daily_start_capital = self.current_capital
            self.last_reset_date = date.today()
            logger.info("Risk Manager: Daily capital baseline reset.")

        result = {'allowed': True, 'reason': '', 'adjusted_shares': shares}

        if not self.trading_enabled:
            return {'allowed': False, 'reason': 'Trading is disabled (kill-switch active)'}

        # Check max positions
        if len(self.open_positions) >= self.max_open_positions and ticker not in self.open_positions:
            return {'allowed': False, 'reason': f'Max positions ({self.max_open_positions}) reached'}

        # Check sector exposure (Correlation Guard)
        if sector and sector != "UNKNOWN":
            sector_value = sum(p['shares'] * p['entry_price'] for p in self.open_positions.values() if p.get('sector') == sector)
            new_trade_value = shares * price
            max_sector_value = self.initial_capital * self.max_sector_exposure_pct
            
            if (sector_value + new_trade_value) > max_sector_value:
                available_room = max_sector_value - sector_value
                if available_room <= 0:
                    return {'allowed': False, 'reason': f'Sector [{sector}] limit reached ({self.max_sector_exposure_pct*100:.0f}%)'}
                
                adjusted = int(available_room / price)
                result['adjusted_shares'] = max(adjusted, 0)
                result['reason'] = f'Sector [{sector}] limit: reduced to {adjusted} shares'

        # Check position size
        position_value = result['adjusted_shares'] * price
        max_position_value = self.current_capital * self.max_position_pct
        if position_value > max_position_value:
            adjusted = int(max_position_value / price)
            result['adjusted_shares'] = max(adjusted, 0)
            result['reason'] = f'Position reduced to {adjusted} shares (max {self.max_position_pct*100:.0f}%)'

        # Check daily loss limit
        daily_pnl = self.current_capital - self.daily_start_capital
        if daily_pnl < -(self.daily_loss_limit_pct * self.initial_capital):
            return {'allowed': False, 'reason': f'Daily loss limit ({self.daily_loss_limit_pct*100:.0f}%) hit'}

        return result

    def record_trade(self, ticker: str, shares: int, price: float, side: str, sector: str = "UNKNOWN"):
        """Record a trade for risk tracking"""
        side = side.upper()
        if side == 'BUY':
            self.open_positions[ticker] = {'shares': shares, 'entry_price': price, 'side': 'LONG', 'sector': sector}
        elif side == 'SHORT':
            self.open_positions[ticker] = {'shares': shares, 'entry_price': price, 'side': 'SHORT', 'sector': sector}
        elif side == 'SELL' and ticker in self.open_positions:
            del self.open_positions[ticker]

        # Update capital (simplified)
        cost = shares * price * (1 + TRANSACTION_COST_BPS / 10000)
        if side in ('BUY', 'SHORT'):
            self.current_capital -= cost
        else:
            self.current_capital += shares * price * (1 - TRANSACTION_COST_BPS / 10000)

        # Update peak
        if self.current_capital > self.peak_capital:
            self.peak_capital = self.current_capital

    def get_drawdown_stats(self) -> Dict:
        """Calculate real-time drawdown statistics."""
        if self.peak_capital == 0:
            return {'drawdown_pct': 0.0, 'status': 'HEALTHY'}
        
        drawdown = (self.peak_capital - self.current_capital) / self.peak_capital
        status = 'HEALTHY'
        if drawdown > 0.05: status = 'CRITICAL'
        elif drawdown > 0.03: status = 'WARNING'
        
        return {
            'drawdown_pct': drawdown * 100,
            'status': status,
            'peak': self.peak_capital,
            'current': self.current_capital
        }

    def check_drawdown(self) -> Dict:
        """Check if max drawdown is exceeded"""
        if self.peak_capital == 0:
            return {'allowed': True}

        drawdown = (self.peak_capital - self.current_capital) / self.peak_capital
        
        # User requested 5% hard limit for alerts
        if drawdown >= 0.05:
            self.trading_enabled = False
            return {
                'allowed': False,
                'reason': f'CRITICAL DRAWDOWN ({drawdown*100:.1f}%) - Trading Halted',
                'drawdown_pct': drawdown * 100
            }
            
        if drawdown > self.max_drawdown_pct:
            self.trading_enabled = False
            return {
                'allowed': False,
                'reason': f'Max drawdown ({self.max_drawdown_pct*100:.0f}%) exceeded: {drawdown*100:.2f}%',
                'drawdown_pct': drawdown * 100
            }
        return {'allowed': True, 'drawdown_pct': drawdown * 100}

    def kill_switch(self):
        """Emergency stop - cancel all trades, disable trading"""
        self.trading_enabled = False
        logger.critical("KILL-SWITCH ACTIVATED - All trading stopped")
        return {'status': 'disabled', 'open_positions': list(self.open_positions.keys())}

    def enable_trading(self, cooldown_minutes: int = 30):
        """Schedule re-enable after cooldown — non-blocking"""
        self._reenable_after = datetime.now() + timedelta(minutes=cooldown_minutes)
        logger.info(f"Trading will re-enable at {self._reenable_after.strftime('%H:%M:%S')} (cooldown: {cooldown_minutes}m)")

    def is_trading_enabled(self) -> bool:
        """Check trading status, auto-unblocking after cooldown"""
        if not self.trading_enabled and hasattr(self, '_reenable_after'):
            if datetime.now() >= self._reenable_after:
                self.trading_enabled = True
                self.daily_start_capital = self.current_capital
                logger.info("Trading re-enabled after cooldown")
        return self.trading_enabled


    def size_position_kelly(self, price: float, confidence: float,
                             win_rate: float = 0.55, avg_win: float = 0.10,
                             avg_loss: float = 0.05) -> int:
        """
        Half-Kelly position sizing — scales investment with signal conviction.
        Returns number of shares to buy (capped at MAX_POSITION_PCT).
        """
        import math
        if price is None or math.isnan(price) or price <= 0:
            return 0
        if confidence is None or math.isnan(confidence):
            confidence = 0.0
            
        kelly_f = (win_rate * avg_win - (1 - win_rate) * avg_loss) / max(avg_win, 1e-9)
        half_kelly = kelly_f * 0.5 * confidence          # Half-Kelly for safety
        position_pct = min(half_kelly, self.max_position_pct)
        position_pct = max(position_pct, 0.01)            # Minimum 1% position
        shares = int(self.current_capital * position_pct / price)
        return max(shares, 0)

    def check_consecutive_losses(self, max_consecutive: int = 3) -> bool:
        """
        Return True if trading should pause after N consecutive losing trades.
        Caller should pause new entries and alert the user.
        """
        if not hasattr(self, 'trade_history'):
            self.trade_history = []
        if len(self.trade_history) < max_consecutive:
            return False
        recent = self.trade_history[-max_consecutive:]
        all_losses = all(t.get('pnl', 0) < 0 for t in recent)
        if all_losses:
            logger.warning(
                f"CIRCUIT BREAKER: {max_consecutive} consecutive losses detected. "
                "Pausing new entries."
            )
        return all_losses

    def record_trade_history(self, ticker: str, side: str, pnl: float):
        """Keep a rolling trade history for circuit breaker logic."""
        if not hasattr(self, 'trade_history'):
            self.trade_history = []
        self.trade_history.append({'ticker': ticker, 'side': side, 'pnl': pnl,
                                    'timestamp': datetime.now().isoformat()})
        self.trade_history = self.trade_history[-50:]   # Keep last 50 trades
