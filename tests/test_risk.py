"""Tests pour le Risk Manager."""

import pytest
from src.risk.manager import RiskManager


class TestRiskManager:
    def setup_method(self):
        self.rm = RiskManager({
            "max_position_pct": 2.0,
            "stop_loss_pct": 1.0,
            "take_profit_pct": 1.5,
            "max_drawdown_pct": 10.0,
            "max_open_positions": 3,
        })
        self.rm.set_capital(10000.0)

    def test_position_size(self):
        size = self.rm.calculate_position_size(10000.0, 50000.0)
        # 2% de 10000 = 200 USDT / 50000 = 0.004 BTC
        assert abs(size - 0.004) < 0.0001

    def test_stop_loss_long(self):
        sl = self.rm.calculate_stop_loss(50000.0, "long")
        # 1% en dessous = 49500
        assert sl == 49500.0

    def test_stop_loss_short(self):
        sl = self.rm.calculate_stop_loss(50000.0, "short")
        assert sl == 50500.0

    def test_take_profit_long(self):
        tp = self.rm.calculate_take_profit(50000.0, "long")
        # 1.5% au dessus = 50750
        assert abs(tp - 50750.0) < 0.01

    def test_can_open_position(self):
        assert self.rm.can_open_position(0) is True
        assert self.rm.can_open_position(2) is True
        assert self.rm.can_open_position(3) is False

    def test_drawdown_not_exceeded(self):
        assert self.rm.check_drawdown(9500.0) is False

    def test_drawdown_exceeded(self):
        assert self.rm.check_drawdown(8900.0) is True

    def test_validate_trade_success(self):
        result = self.rm.validate_trade(10000.0, 50000.0, 0)
        assert result is not None
        assert "amount" in result
        assert "stop_loss" in result
        assert "take_profit" in result

    def test_validate_trade_max_positions(self):
        result = self.rm.validate_trade(10000.0, 50000.0, 3)
        assert result is None
