"""
SEBI Compliance Module for Algorithmic Trading
Implements SEBI's retail algo trading framework requirements:
- Algo-ID tracking and registration
- IP whitelisting
- Audit trails and order logging
- Kill-switch enforcement
- Position limits and risk controls
"""

import hashlib
import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set
from functools import lru_cache
import ipaddress
import os

logger = logging.getLogger(__name__)


class AlgoStatus(Enum):
    """Algorithm status"""
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"
    SUSPENDED = "suspended"


class OrderStatus(Enum):
    """Order status for audit trail"""
    PENDING = "pending"
    PLACED = "placed"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass
class AlgoRegistration:
    """Algorithm registration details"""
    algo_id: str  # Exchange-issued Algo-ID
    name: str
    description: str
    strategy_type: str  # e.g., "momentum", "mean_reversion", "options_writer"
    registered_at: datetime
    status: AlgoStatus
    parameters: Dict  # Strategy parameters
    risk_limits: Dict  # Position limits, stop-loss, etc.
    broker: str  # Broker name (e.g., "zerodha", "upstox")


@dataclass
class AuditLogEntry:
    """Audit log entry for compliance"""
    timestamp: datetime
    algo_id: str
    event_type: str  # "order_placed", "order_filled", "signal_generated", etc.
    order_id: Optional[str]
    symbol: str
    side: Optional[str]  # "BUY" or "SELL"
    quantity: Optional[int]
    price: Optional[float]
    status: OrderStatus
    ip_address: str
    user_id: str
    details: Dict  # Additional context


@dataclass
class ComplianceConfig:
    """Compliance configuration"""
    # SEBI requirements
    require_algo_id: bool = True
    require_ip_whitelist: bool = True
    require_audit_trail: bool = True
    max_orders_per_second: int = 10
    max_orders_per_day: int = 1000

    # Risk limits
    max_position_value: float = 500000.0  # Max 5 lakhs per position
    max_daily_loss_pct: float = 2.0  # Stop trading at 2% daily loss
    max_drawdown_pct: float = 20.0  # Max 20% drawdown

    # Kill-switch
    kill_switch_file: str = "kill_switch.active"
    auto_kill_on_error: bool = True

    # IP whitelist
    allowed_ips: List[str] = None  # List of allowed IP addresses

    # Audit trail
    audit_log_file: str = "logs/compliance_audit.log"
    retain_audit_days: int = 90


class SEBIComplianceManager:
    """
    Main compliance manager enforcing SEBI regulations
    """

    def __init__(self, config: ComplianceConfig = None):
        self.config = config or ComplianceConfig()
        self._registered_algos: Dict[str, AlgoRegistration] = {}
        self._audit_log: List[AuditLogEntry] = []
        self._whitelisted_ips: Set[str] = set(self.config.allowed_ips or [])
        self._current_ip: Optional[str] = None
        self._daily_order_count = 0
        self._daily_order_reset: Optional[datetime] = None
        self._kill_switch_active = False

        # Load existing audit log
        self._load_audit_log()

        # Check kill-switch
        self._check_kill_switch()

    def register_algo(
        self,
        algo_id: str,
        name: str,
        description: str,
        strategy_type: str,
        parameters: Dict = None,
        risk_limits: Dict = None,
        broker: str = "zerodha"
    ) -> AlgoRegistration:
        """
        Register an algorithm with SEBI compliance
        Returns the registration details
        """
        registration = AlgoRegistration(
            algo_id=algo_id,
            name=name,
            description=description,
            strategy_type=strategy_type,
            registered_at=datetime.now(),
            status=AlgoStatus.ACTIVE,
            parameters=parameters or {},
            risk_limits=risk_limits or {},
            broker=broker
        )

        self._registered_algos[algo_id] = registration
        self._log_audit(
            algo_id=algo_id,
            event_type="algo_registered",
            symbol="",
            status=OrderStatus.PENDING,
            details={"registration": asdict(registration)}
        )

        logger.info(f"Registered algorithm: {algo_id} - {name}")
        return registration

    def get_algo(self, algo_id: str) -> Optional[AlgoRegistration]:
        """Get algorithm registration by ID"""
        return self._registered_algos.get(algo_id)

    def update_algo_status(self, algo_id: str, status: AlgoStatus) -> bool:
        """Update algorithm status"""
        algo = self._registered_algos.get(algo_id)
        if algo:
            algo.status = status
            self._log_audit(
                algo_id=algo_id,
                event_type="algo_status_changed",
                symbol="",
                status=OrderStatus.PENDING,
                details={"new_status": status.value}
            )
            return True
        return False

    def add_whitelisted_ip(self, ip_address: str) -> bool:
        """Add IP address to whitelist"""
        try:
            ipaddress.ip_address(ip_address)
            self._whitelisted_ips.add(ip_address)
            logger.info(f"Added whitelisted IP: {ip_address}")
            return True
        except ValueError:
            logger.error(f"Invalid IP address: {ip_address}")
            return False

    def remove_whitelisted_ip(self, ip_address: str) -> bool:
        """Remove IP address from whitelist"""
        if ip_address in self._whitelisted_ips:
            self._whitelisted_ips.remove(ip_address)
            logger.info(f"Removed whitelisted IP: {ip_address}")
            return True
        return False

    def check_ip_whitelist(self, ip_address: str) -> bool:
        """Check if IP address is whitelisted"""
        if not self.config.require_ip_whitelist:
            return True

        return ip_address in self._whitelisted_ips

    def set_current_ip(self, ip_address: str) -> bool:
        """Set current IP address for validation"""
        if self.check_ip_whitelist(ip_address):
            self._current_ip = ip_address
            return True
        return False

    def validate_order(
        self,
        algo_id: str,
        symbol: str,
        side: str,
        quantity: int,
        price: float
    ) -> Tuple[bool, str]:
        """
        Validate order against SEBI compliance rules
        Returns (is_valid, reason)
        """
        # Check kill-switch
        if self._kill_switch_active:
            return False, "Kill-switch is active"

        # Check IP whitelist
        if self.config.require_ip_whitelist and not self._current_ip:
            return False, "IP address not set"

        if not self.check_ip_whitelist(self._current_ip):
            return False, f"IP address {self._current_ip} not whitelisted"

        # Check algo registration
        algo = self._registered_algos.get(algo_id)
        if not algo:
            return False, f"Algorithm {algo_id} not registered"

        if algo.status != AlgoStatus.ACTIVE:
            return False, f"Algorithm {algo_id} is not active (status: {algo.status.value})"

        # Check order rate limits
        if not self._check_order_rate_limit():
            return False, "Order rate limit exceeded"

        # Check risk limits
        if not self._check_risk_limits(algo, symbol, quantity, price):
            return False, "Risk limit exceeded"

        return True, "Valid"

    def log_order(
        self,
        algo_id: str,
        order_id: str,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        status: OrderStatus,
        details: Dict = None
    ) -> None:
        """Log order to audit trail"""
        self._log_audit(
            algo_id=algo_id,
            event_type="order_placed",
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            status=status,
            details=details or {}
        )

    def log_signal(
        self,
        algo_id: str,
        symbol: str,
        signal: str,
        confidence: float,
        details: Dict = None
    ) -> None:
        """Log trading signal to audit trail"""
        self._log_audit(
            algo_id=algo_id,
            event_type="signal_generated",
            symbol=symbol,
            status=OrderStatus.PENDING,
            details={
                "signal": signal,
                "confidence": confidence,
                **(details or {})
            }
        )

    def _log_audit(
        self,
        algo_id: str,
        event_type: str,
        symbol: str,
        status: OrderStatus,
        order_id: Optional[str] = None,
        side: Optional[str] = None,
        quantity: Optional[int] = None,
        price: Optional[float] = None,
        details: Dict = None
    ) -> None:
        """Add entry to audit log"""
        entry = AuditLogEntry(
            timestamp=datetime.now(),
            algo_id=algo_id,
            event_type=event_type,
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            status=status,
            ip_address=self._current_ip or "unknown",
            user_id=os.getenv("USER", "unknown"),
            details=details or {}
        )

        self._audit_log.append(entry)

        # Write to file
        self._write_audit_log(entry)

    def _write_audit_log(self, entry: AuditLogEntry) -> None:
        """Write audit log entry to file"""
        try:
            log_file = Path(self.config.audit_log_file)
            log_file.parent.mkdir(parents=True, exist_ok=True)

            with open(log_file, 'a') as f:
                f.write(json.dumps(asdict(entry), default=str) + '\n')
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")

    def _load_audit_log(self) -> None:
        """Load existing audit log from file"""
        try:
            log_file = Path(self.config.audit_log_file)
            if log_file.exists():
                with open(log_file, 'r') as f:
                    for line in f:
                        try:
                            data = json.loads(line)
                            entry = AuditLogEntry(**data)
                            self._audit_log.append(entry)
                        except Exception as e:
                            logger.error(f"Failed to parse audit log entry: {e}")
        except Exception as e:
            logger.error(f"Failed to load audit log: {e}")

    def _check_order_rate_limit(self) -> bool:
        """Check if order rate limit is respected"""
        now = datetime.now()

        # Reset daily counter at midnight
        if (self._daily_order_reset is None or
            now.date() > self._daily_order_reset.date()):
            self._daily_order_count = 0
            self._daily_order_reset = now

        return self._daily_order_count < self.config.max_orders_per_day

    def _check_risk_limits(
        self,
        algo: AlgoRegistration,
        symbol: str,
        quantity: int,
        price: float
    ) -> bool:
        """Check if order respects risk limits"""
        position_value = quantity * price

        # Check max position value
        if position_value > self.config.max_position_value:
            logger.warning(
                f"Position value {position_value} exceeds limit "
                f"{self.config.max_position_value}"
            )
            return False

        # Check algo-specific risk limits
        risk_limits = algo.risk_limits
        if 'max_position_value' in risk_limits:
            if position_value > risk_limits['max_position_value']:
                return False

        return True

    def _check_kill_switch(self) -> None:
        """Check if kill-switch is active"""
        kill_file = Path(self.config.kill_switch_file)
        if kill_file.exists():
            self._kill_switch_active = True
            logger.critical("KILL-SWITCH ACTIVE - All trading disabled")
        else:
            self._kill_switch_active = False

    def activate_kill_switch(self, reason: str = "") -> None:
        """Activate kill-switch"""
        kill_file = Path(self.config.kill_switch_file)
        kill_file.touch()
        self._kill_switch_active = True

        self._log_audit(
            algo_id="system",
            event_type="kill_switch_activated",
            symbol="",
            status=OrderStatus.PENDING,
            details={"reason": reason}
        )

        logger.critical(f"KILL-SWITCH ACTIVATED: {reason}")

    def deactivate_kill_switch(self) -> None:
        """Deactivate kill-switch"""
        kill_file = Path(self.config.kill_switch_file)
        if kill_file.exists():
            kill_file.unlink()

        self._kill_switch_active = False

        self._log_audit(
            algo_id="system",
            event_type="kill_switch_deactivated",
            symbol="",
            status=OrderStatus.PENDING,
            details={}
        )

        logger.info("KILL-SWITCH DEACTIVATED")

    def is_kill_switch_active(self) -> bool:
        """Check if kill-switch is active"""
        return self._kill_switch_active

    def get_audit_log(
        self,
        algo_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 1000
    ) -> List[AuditLogEntry]:
        """
        Get audit log entries with optional filters
        """
        filtered = self._audit_log

        if algo_id:
            filtered = [e for e in filtered if e.algo_id == algo_id]

        if start_date:
            filtered = [e for e in filtered if e.timestamp >= start_date]

        if end_date:
            filtered = [e for e in filtered if e.timestamp <= end_date]

        return filtered[-limit:]

    def generate_compliance_report(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict:
        """
        Generate compliance report for audit
        """
        if start_date is None:
            start_date = datetime.now() - timedelta(days=30)
        if end_date is None:
            end_date = datetime.now()

        entries = self.get_audit_log(start_date=start_date, end_date=end_date)

        # Calculate statistics
        total_orders = len([e for e in entries if e.event_type == "order_placed"])
        filled_orders = len([e for e in entries if e.status == OrderStatus.FILLED])
        rejected_orders = len([e for e in entries if e.status == OrderStatus.REJECTED])

        # Orders by algo
        orders_by_algo = {}
        for entry in entries:
            if entry.event_type == "order_placed":
                algo_id = entry.algo_id
                if algo_id not in orders_by_algo:
                    orders_by_algo[algo_id] = 0
                orders_by_algo[algo_id] += 1

        # Orders by symbol
        orders_by_symbol = {}
        for entry in entries:
            if entry.event_type == "order_placed":
                symbol = entry.symbol
                if symbol not in orders_by_symbol:
                    orders_by_symbol[symbol] = 0
                orders_by_symbol[symbol] += 1

        return {
            "report_period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat()
            },
            "summary": {
                "total_orders": total_orders,
                "filled_orders": filled_orders,
                "rejected_orders": rejected_orders,
                "fill_rate": filled_orders / total_orders if total_orders > 0 else 0
            },
            "by_algorithm": orders_by_algo,
            "by_symbol": orders_by_symbol,
            "registered_algos": {
                algo_id: {
                    "name": algo.name,
                    "status": algo.status.value,
                    "strategy_type": algo.strategy_type
                }
                for algo_id, algo in self._registered_algos.items()
            },
            "compliance_status": {
                "kill_switch_active": self._kill_switch_active,
                "whitelisted_ips": list(self._whitelisted_ips),
                "current_ip": self._current_ip
            }
        }

    def cleanup_old_audit_logs(self) -> None:
        """Remove audit log entries older than retention period"""
        cutoff_date = datetime.now() - timedelta(days=self.config.retain_audit_days)
        self._audit_log = [
            e for e in self._audit_log if e.timestamp >= cutoff_date
        ]
        logger.info(f"Cleaned up audit logs older than {cutoff_date}")


# Singleton instance
_compliance_manager: Optional[SEBIComplianceManager] = None


def get_compliance_manager(config: ComplianceConfig = None) -> SEBIComplianceManager:
    """Get the global compliance manager instance"""
    global _compliance_manager
    if _compliance_manager is None:
        _compliance_manager = SEBIComplianceManager(config)
    return _compliance_manager


def initialize_compliance(config: ComplianceConfig = None) -> SEBIComplianceManager:
    """Initialize the global compliance manager"""
    global _compliance_manager
    _compliance_manager = SEBIComplianceManager(config)
    return _compliance_manager
