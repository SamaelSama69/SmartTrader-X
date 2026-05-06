"""
Options Trading Strategies
Analyzes options flow, unusual activity, and generates options strategies
"""

import yfinance as yf
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import json
from config import OPTIONS_MIN_VOLUME, OPTIONS_MIN_OPEN_INTEREST


class OptionsAnalyzer:
    """Options analysis and strategy generation"""

    def __init__(self):
        pass

    def get_options_chain(self, ticker: str) -> Dict:
        """Get options chain data"""
        try:
            stock = yf.Ticker(ticker)
            expirations = stock.options

            if not expirations:
                return {'error': 'No options available'}

            # Get nearest expiration with decent volume
            chain_data = None
            selected_exp = None

            for exp in expirations[:5]:
                chain = stock.option_chain(exp)
                calls = chain.calls
                puts = chain.puts

                # Check for volume
                if not calls.empty and calls['volume'].sum() > 100:
                    chain_data = chain
                    selected_exp = exp
                    break

            if not chain_data:
                return {'error': 'No liquid options found'}

            return {
                'ticker': ticker,
                'expiration': selected_exp,
                'calls': self._process_options(calls, 'call'),
                'puts': self._process_options(puts, 'put'),
            }

        except Exception as e:
            return {'error': str(e)}

    def _process_options(self, df: pd.DataFrame, opt_type: str) -> List[Dict]:
        """Process options data"""
        if df.empty:
            return []

        # Filter for liquid options
        df = df[df['volume'] > OPTIONS_MIN_VOLUME]
        df = df[df['openInterest'] > OPTIONS_MIN_OPEN_INTEREST]

        results = []
        for _, row in df.iterrows():
            results.append({
                'strike': row['strike'],
                'last_price': row['lastPrice'],
                'bid': row['bid'],
                'ask': row['ask'],
                'volume': row['volume'],
                'open_interest': row['openInterest'],
                'implied_volatility': row.get('impliedVolatility', 0),
                'type': opt_type,
                'delta': row.get('delta', None),
                'gamma': row.get('gamma', None),
                'theta': row.get('theta', None),
            })

        return sorted(results, key=lambda x: x['volume'], reverse=True)[:20]

    def detect_unusual_options_activity(self, ticker: str) -> Dict:
        """Detect unusual options activity (potential insider moves)"""
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period='30d')
            current_price = hist['Close'].iloc[-1] if not hist.empty else None

            expiration = stock.options[0] if stock.options else None
            if not expiration:
                return {'unusual_activity': False}

            chain = stock.option_chain(expiration)
            calls = chain.calls
            puts = chain.puts

            unusual = []

            # Check for volume spikes in calls using volume-to-OI ratio
            for _, row in calls.iterrows():
                oi = row.get('openInterest', 0) or 1  # Avoid division by zero
                vol = row.get('volume', 0) or 0
                volume_to_oi_ratio = vol / oi
                if volume_to_oi_ratio > 0.20 and vol > 500:
                    unusual.append({
                        'type': 'CALL',
                        'strike': row['strike'],
                        'volume': row['volume'],
                        'open_interest': row.get('openInterest', 0),
                        'volume_to_oi_ratio': round(volume_to_oi_ratio, 2),
                        'signal': 'BULLISH' if current_price and row['strike'] > current_price else 'BEARISH'
                    })

            # Check for volume spikes in puts using volume-to-OI ratio
            for _, row in puts.iterrows():
                oi = row.get('openInterest', 0) or 1
                vol = row.get('volume', 0) or 0
                volume_to_oi_ratio = vol / oi
                if volume_to_oi_ratio > 0.20 and vol > 500:
                    unusual.append({
                        'type': 'PUT',
                        'strike': row['strike'],
                        'volume': row['volume'],
                        'open_interest': row.get('openInterest', 0),
                        'volume_to_oi_ratio': round(volume_to_oi_ratio, 2),
                        'signal': 'BEARISH'
                    })

            return {
                'ticker': ticker,
                'unusual_activity': len(unusual) > 0,
                'activity_count': len(unusual),
                'activities': unusual[:10],
                'current_price': current_price,
            }

        except Exception as e:
            return {'error': str(e)}

    def suggest_options_strategy(self, ticker: str, direction: str) -> Dict:
        """
        Suggest options strategy based on market outlook
        direction: 'BULLISH', 'BEARISH', 'NEUTRAL'
        """
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period='3mo')
            current_price = hist['Close'].iloc[-1]

            # Calculate volatility (for strategy selection)
            returns = hist['Close'].pct_change().dropna()
            volatility = returns.std() * np.sqrt(252)  # Annualized

            # Get nearest expiration
            if not stock.options:
                return {'error': 'No options available'}

            expiration = stock.options[1] if len(stock.options) > 1 else stock.options[0]
            chain = stock.option_chain(expiration)

            strategies = []

            if direction == 'BULLISH':
                strategies = [
                    {
                        'name': 'Long Call',
                        'description': 'Buy call option for direct upside',
                        'risk': 'Limited to premium paid',
                        'best_if': 'Strong bullish move expected',
                    },
                    {
                        'name': 'Bull Call Spread',
                        'description': 'Buy lower strike call, sell higher strike',
                        'risk': 'Limited',
                        'best_if': 'Moderate bullish outlook',
                    },
                    {
                        'name': 'Cash-Secured Put',
                        'description': 'Sell put to acquire stock at lower price',
                        'risk': 'Obligated to buy at strike',
                        'best_if': 'Want to own stock at discount',
                    }
                ]
            elif direction == 'BEARISH':
                strategies = [
                    {
                        'name': 'Long Put',
                        'description': 'Buy put option for downside protection',
                        'risk': 'Limited to premium paid',
                        'best_if': 'Strong bearish move expected',
                    },
                    {
                        'name': 'Bear Put Spread',
                        'description': 'Buy higher strike put, sell lower strike',
                        'risk': 'Limited',
                        'best_if': 'Moderate bearish outlook',
                    }
                ]
            else:  # NEUTRAL
                strategies = [
                    {
                        'name': 'Iron Condor',
                        'description': 'Sell OTM call and put spreads',
                        'risk': 'Limited but capped profit',
                        'best_if': 'Low volatility expected',
                    },
                    {
                        'name': 'Straddle',
                        'description': 'Buy call and put at same strike',
                        'risk': 'Double premium if no move',
                        'best_if': 'Big move expected (any direction)',
                    }
                ]

            return {
                'ticker': ticker,
                'direction': direction,
                'current_price': round(current_price, 2),
                'volatility': round(volatility * 100, 2),
                'suggested_strategies': strategies,
                'expiration': expiration,
            }

        except Exception as e:
            return {'error': str(e)}

    def calculate_options_profit_loss(self, option_data: Dict, exit_price: float) -> Dict:
        """Calculate profit/loss for an options position using real math"""
        strike = option_data.get('strike', 0)
        premium = option_data.get('last_price', 0)
        opt_type = option_data.get('type', 'call').lower()  # Normalize to lowercase

        if opt_type == 'call':
            intrinsic = max(exit_price - strike, 0)
        else:
            intrinsic = max(strike - exit_price, 0)

        pnl = intrinsic - premium
        pnl_pct = (pnl / premium * 100) if premium > 0 else 0
        breakeven = (strike + premium) if opt_type == 'call' else (strike - premium)

        return {
            'pnl': round(pnl, 2),
            'pnl_pct': round(pnl_pct, 1),
            'breakeven': round(breakeven, 2),
            'max_loss': round(-premium, 2),
            'is_profitable': pnl > 0
        }
