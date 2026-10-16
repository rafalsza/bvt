"""
state_manager.py

Handles saving and loading the bot's state to/from persistent storage.
"""
import json
import os
from loguru import logger

class StateManager:
    """Manages the bot's state persistence."""

    def __init__(self, config, script_config, state_file_path):
        """Initialize the StateManager.
        
        Args:
            config: Bot configuration dictionary
            script_config: Script configuration dictionary
            state_file_path: Path to the state file
        """
        self.config = config
        self.script_config = script_config
        self.state_file_path = state_file_path
        
        # Initialize default values
        self.TRADE_TOTAL = float(config.get("TRADE_TOTAL", 100))
        self.TRADE_SLOTS = int(config.get("TRADE_SLOTS", 5))
        self.PAIR_WITH = config.get("PAIR_WITH", "USDT")
        self.REINVEST_PROFITS = config.get("REINVEST_PROFITS", False)
        
        # Initialize bot stats
        self.total_capital = self.TRADE_SLOTS * self.TRADE_TOTAL
        self.historic_profit_incfees_perc = 0.0
        self.historic_profit_incfees_total = 0.0
        self.trade_wins = 0
        self.trade_losses = 0
        self.market_startprice = 0.0

    def load_state(self):
        """Load bot state from file.
        
        Returns:
            dict: The loaded state data
        """
        try:
            if not os.path.exists(self.state_file_path):
                logger.info("💼 No saved state file found, using initial configuration")
                return self._get_default_state()

            with open(self.state_file_path, "r") as f:
                state_data = json.load(f)

            # Update instance variables from loaded state
            if "bot_stats" in state_data:
                self._update_from_state(state_data["bot_stats"])
                
            logger.info(f"💰 Loaded TRADE_TOTAL from saved state: {self.TRADE_TOTAL} {self.PAIR_WITH}")
            return state_data
            
        except Exception as e:
            logger.error(f"💥 Failed to load state: {e}")
            return self._get_default_state()
    
    def save_state(self, positions, trade_total=None):
        """Save current bot state to file.
        
        Args:
            positions: Current open positions
            trade_total: Current trade total (optional, will use instance value if not provided)
            
        Returns:
            bool: True if save was successful, False otherwise
        """
        try:
            if trade_total is not None:
                self.TRADE_TOTAL = trade_total
                
            state_data = {
                "positions": positions,
                "last_updated": self._get_current_timestamp(),
                "total_positions": len(positions),
                "bot_stats": self._get_bot_stats(),
                "metadata": {
                    "trade_total": self.TRADE_TOTAL,
                    "trade_slots": self.TRADE_SLOTS,
                    "pair_with": self.PAIR_WITH,
                    "test_mode": self.script_config.get("TEST_MODE", True),
                },
            }
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.state_file_path), exist_ok=True)
            
            with open(self.state_file_path, "w") as f:
                json.dump(state_data, f, indent=2, default=str)
                
            logger.debug(f"💾 State saved to {self.state_file_path}")
            return True
            
        except Exception as e:
            logger.error(f"💥 Failed to save state: {e}")
            return False
    
    def _update_from_state(self, bot_stats):
        """Update instance variables from loaded state."""
        self.total_capital = float(bot_stats.get("total_capital", self.TRADE_SLOTS * self.TRADE_TOTAL))
        self.historic_profit_incfees_perc = float(bot_stats.get("historicProfitIncFees_Percent", 0.0))
        self.historic_profit_incfees_total = float(bot_stats.get("historicProfitIncFees_Total", 0.0))
        self.trade_wins = int(bot_stats.get("tradeWins", 0))
        self.trade_losses = int(bot_stats.get("tradeLosses", 0))
        self.market_startprice = float(bot_stats.get("market_startprice", 0.0))
        
        # Handle REINVEST_PROFITS logic
        if self.REINVEST_PROFITS:
            if self.total_capital <= 0:
                self.TRADE_TOTAL = (self.TRADE_SLOTS * self.TRADE_TOTAL) / self.TRADE_SLOTS
            else:
                self.TRADE_TOTAL = self.total_capital / self.TRADE_SLOTS
    
    def _get_bot_stats(self):
        """Get current bot statistics as a dictionary."""
        return {
            "botstart_datetime": self._get_current_timestamp(),
            "total_capital": self.TRADE_TOTAL * self.TRADE_SLOTS,
            "historicProfitIncFees_Percent": self.historic_profit_incfees_perc,
            "historicProfitIncFees_Total": self.historic_profit_incfees_total,
            "tradeWins": self.trade_wins,
            "tradeLosses": self.trade_losses,
            "market_startprice": self.market_startprice
        }
    
    def _get_default_state(self):
        """Get default state dictionary."""
        return {
            "positions": {},
            "last_updated": self._get_current_timestamp(),
            "total_positions": 0,
            "bot_stats": self._get_bot_stats(),
            "metadata": {
                "trade_total": self.TRADE_TOTAL,
                "trade_slots": self.TRADE_SLOTS,
                "pair_with": self.PAIR_WITH,
                "test_mode": self.script_config.get("TEST_MODE", True),
            },
        }
    
    @staticmethod
    def _get_current_timestamp():
        """Get current timestamp in ISO format."""
        from datetime import datetime
        return datetime.now().isoformat()
