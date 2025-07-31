# configuration_manager.py
import yaml
import os
from typing import Dict, Any, Tuple
from globals import user_data_path


class ConfigurationError(Exception):
    """Base exception for configuration-related errors."""

    pass


class ConfigurationFileNotFoundError(ConfigurationError):
    """Raised when configuration file is not found."""

    pass


class ConfigurationLoadError(ConfigurationError):
    """Raised when configuration file cannot be loaded or parsed."""

    pass


class CredentialsError(ConfigurationError):
    """Base exception for credentials-related errors."""

    pass


class CredentialsFileNotFoundError(CredentialsError):
    """Raised when credentials file is not found."""

    pass


class CredentialsLoadError(CredentialsError):
    """Raised when credentials file cannot be loaded or parsed."""

    pass


class IncompleteCredentialsError(CredentialsError):
    """Raised when API credentials are missing or incomplete."""

    pass


class ConfigurationManager:
    """
    Manages configuration loading and validation for the trading bot.
    """

    def __init__(self, config_file: str, creds_file: str):
        """
        Initialize configuration manager with file paths.

        Args:
            config_file (str): Path to configuration YAML file
            creds_file (str): Path to credentials YAML file

        Raises:
            ConfigurationFileNotFoundError: When config file doesn't exist
            ConfigurationLoadError: When config file cannot be loaded
            CredentialsFileNotFoundError: When credentials file doesn't exist
            CredentialsLoadError: When credentials file cannot be loaded
        """
        self.config_file = config_file
        self.creds_file = creds_file
        self.config_data = None
        self.credentials = None
        self._trading_config = None

        # Load configuration files
        self._load_configuration()
        self._load_credentials()

    def _load_configuration(self):
        """
        Load trading configuration from YAML file.

        Raises:
            ConfigurationFileNotFoundError: When config file doesn't exist
            ConfigurationLoadError: When config file cannot be parsed
        """
        try:
            if not os.path.exists(self.config_file):
                raise ConfigurationFileNotFoundError(
                    f"Configuration file not found: {self.config_file}. Please create the file or check the path."
                )

            with open(self.config_file, "r", encoding="utf-8") as file:
                self.config_data = yaml.safe_load(file)

            # Validate that config was loaded successfully
            if self.config_data is None:
                raise ConfigurationLoadError(
                    f"Configuration file is empty or invalid: {self.config_file}"
                )

        except ConfigurationFileNotFoundError:
            # Re-raise our custom exceptions
            raise

        except yaml.YAMLError as e:
            raise ConfigurationLoadError(
                f"Invalid YAML syntax in configuration file {self.config_file}: {e}"
            ) from e

        except PermissionError as e:
            raise ConfigurationLoadError(
                f"Permission denied reading configuration file {self.config_file}: {e}"
            ) from e

        except OSError as e:
            raise ConfigurationLoadError(
                f"OS error reading configuration file {self.config_file}: {e}"
            ) from e

        except Exception as e:
            raise ConfigurationLoadError(
                f"Unexpected error loading configuration from {self.config_file}: {e}"
            ) from e

    def _load_credentials(self):
        """
        Load API credentials from YAML file.

        Raises:
            CredentialsFileNotFoundError: When credentials file doesn't exist
            CredentialsLoadError: When credentials file cannot be parsed
        """
        try:
            if not os.path.exists(self.creds_file):
                raise CredentialsFileNotFoundError(
                    f"Credentials file not found: {self.creds_file}. "
                    f"Please create the file with your Binance API credentials."
                )

            with open(self.creds_file, "r", encoding="utf-8") as file:
                self.credentials = yaml.safe_load(file)

            # Validate that credentials were loaded successfully
            if self.credentials is None:
                raise CredentialsLoadError(
                    f"Credentials file is empty or invalid: {self.creds_file}"
                )

        except CredentialsFileNotFoundError:
            # Re-raise our custom exceptions
            raise

        except yaml.YAMLError as e:
            raise CredentialsLoadError(
                f"Invalid YAML syntax in credentials file {self.creds_file}: {e}"
            ) from e

        except PermissionError as e:
            raise CredentialsLoadError(
                f"Permission denied reading credentials file {self.creds_file}: {e}"
            ) from e

        except OSError as e:
            raise CredentialsLoadError(
                f"OS error reading credentials file {self.creds_file}: {e}"
            ) from e

        except Exception as e:
            raise CredentialsLoadError(
                f"Unexpected error loading credentials from {self.creds_file}: {e}"
            ) from e

    def get_trading_config(self) -> Dict[str, Any]:
        """
        Get trading configuration parameters.

        Returns:
            Dict[str, Any]: Trading configuration dictionary

        Raises:
            ConfigurationError: When configuration is not loaded or invalid
        """
        if self._trading_config is None:
            if not self.config_data:
                raise ConfigurationError(
                    "Configuration not loaded. Ensure configuration file was loaded successfully."
                )

            if not isinstance(self.config_data, dict):
                raise ConfigurationError(
                    "Invalid configuration format. Expected dictionary structure."
                )

            trading_options = self.config_data.get("trading_options")
            if trading_options is None:
                raise ConfigurationError(
                    "Missing 'trading_options' section in configuration file. Please check your config.yml structure."
                )

            if not isinstance(trading_options, dict):
                raise ConfigurationError(
                    "Invalid 'trading_options' format. Expected dictionary structure."
                )
            self._trading_config = trading_options

        return self._trading_config

    def get_telegram_credentials(self) -> Tuple[str, str]:
        """
        Get Telegram bot API credentials.

        Returns:
            Tuple[str, str]: API key and chat ID

        Raises:
            IncompleteCredentialsError: When credentials are missing or invalid
        """
        if not self.credentials:
            raise CredentialsError("Credentials data not loaded")

        telegram_creds = self.credentials.get("telegram", {})

        token = telegram_creds.get("TELEGRAM_BOT_TOKEN")
        chat_id = telegram_creds.get("TELEGRAM_CHAT_ID")

        if not token or not isinstance(token, str) or not token.strip():
            raise IncompleteCredentialsError(
                "Missing or invalid 'TELEGRAM_BOT_TOKEN' in credentials file under 'telegram' section."
            )
        if not chat_id or not isinstance(chat_id, str) or not chat_id.strip():
            raise IncompleteCredentialsError(
                "Missing or invalid 'TELEGRAM_CHAT_ID' in credentials file under 'telegram' section."
            )

        return token.strip(), chat_id.strip()

    def get_api_credentials(self) -> Tuple[str, str]:
        """
        Get Binance API credentials.

        Returns:
            Tuple[str, str]: API key and secret

        Raises:
            CredentialsError: When credentials are not loaded
            IncompleteCredentialsError: When credentials are missing or invalid
        """
        if not self.credentials:
            raise CredentialsError(
                "Credentials not loaded. Ensure credentials file was loaded successfully."
            )

        if not isinstance(self.credentials, dict):
            raise CredentialsError(
                "Invalid credentials format. Expected dictionary structure."
            )

        api_key = self.credentials.get("api_key")
        api_secret = self.credentials.get("api_secret")

        # Validate API key
        if not api_key:
            raise IncompleteCredentialsError(
                "Missing 'api_key' in credentials file. Please add your Binance API key to creds.yml"
            )

        if not isinstance(api_key, str) or not api_key.strip():
            raise IncompleteCredentialsError(
                "Invalid API key format. API key must be a non-empty string."
            )

        # Validate API secret
        if not api_secret:
            raise IncompleteCredentialsError(
                "Missing 'api_secret' in credentials file. Please add your Binance API secret to creds.yml"
            )

        if not isinstance(api_secret, str) or not api_secret.strip():
            raise IncompleteCredentialsError(
                "Invalid API secret format. API secret must be a non-empty string."
            )

        return api_key.strip(), api_secret.strip()

    def get_db_filename(self) -> str:
        """Get database filename from configuration."""
        if not self.config_data or "data_options" not in self.config_data:
            raise ConfigurationError("Missing 'data_options' in config.yml")
        db_filename = self.config_data["data_options"].get(
            "DB_TRANSACTIONS_FILE_NAME", "transactions.db"
        )
        return f"{user_data_path}/{db_filename}"

    def validate_configuration(self) -> bool:
        """
        Validate that all required configuration parameters are present.

        Returns:
            bool: True if configuration is valid

        Raises:
            ConfigurationError: When required configuration is missing
        """
        try:
            config = self.get_trading_config()

            # List of required configuration parameters
            required_params = [
                "PAIR_WITH",
                "TRADE_TOTAL",
                "TRADE_SLOTS",
                "STOP_LOSS",
                "TAKE_PROFIT",
            ]

            missing_params = []
            for param in required_params:
                if param not in config:
                    missing_params.append(param)

            if missing_params:
                raise ConfigurationError(
                    f"Missing required configuration parameters: {', '.join(missing_params)}. "
                    f"Please check your config.yml file."
                )

            return True

        except ConfigurationError:
            raise

        except Exception as e:
            raise ConfigurationError(f"Configuration validation failed: {e}") from e

    def get_config_value(self, key: str):
        """
        Get a specific configuration value.

        Args:
            key (str): Configuration key to retrieve

        Returns:
            Any: Configuration value

        Raises:
            ConfigurationError: When configuration is not loaded
        """
        try:
            config = self.get_trading_config()
            return config.get(key)

        except ConfigurationError:
            raise

        except Exception as e:
            raise ConfigurationError(
                f"Error retrieving config value '{key}': {e}"
            ) from e

    def get_script_options(self) -> Dict[str, Any]:
        """
        Get script configuration parameters.

        Returns:
            Dict[str, Any]: Script options dictionary

        Raises:
            ConfigurationError: When configuration is not loaded or invalid
        """
        if not self.config_data:
            raise ConfigurationError(
                "Configuration not loaded. Ensure configuration file was loaded successfully."
            )

        if not isinstance(self.config_data, dict):
            raise ConfigurationError(
                "Invalid configuration format. Expected dictionary structure."
            )

        script_options = self.config_data.get("script_options", {})

        if not isinstance(script_options, dict):
            raise ConfigurationError(
                "Invalid 'script_options' format. Expected dictionary structure."
            )

        return script_options

    def get_script_option(self, key: str, default=None):
        """
        Get a specific script option value.

        Args:
            key (str): Script option key to retrieve
            default: Default value if key not found

        Returns:
            Any: Script option value or default

        Raises:
            ConfigurationError: When configuration is not loaded
        """
        try:
            script_options = self.get_script_options()
            return script_options.get(key, default)

        except ConfigurationError:
            raise

        except Exception as e:
            raise ConfigurationError(
                f"Error retrieving script option '{key}': {e}"
            ) from e

    def set_take_profit(self, new_tp: float):
        """
        Update TAKE_PROFIT in config_data and config_file.
        Args:
            new_tp (float): New take profit value
        Raises:
            ConfigurationError: If update or save fails
        """
        try:
            # Update in-memory config
            if "trading_options" not in self.config_data:
                raise ConfigurationError("Missing 'trading_options' in config.")
            self.config_data["trading_options"]["TAKE_PROFIT"] = float(new_tp)
            # Write to file
            with open(self.config_file, "w", encoding="utf-8") as file:
                yaml.safe_dump(self.config_data, file, default_flow_style=False)
        except Exception as e:
            raise ConfigurationError(f"Failed to update TAKE_PROFIT: {e}")

    def set_stop_loss(self, new_sl: float):
        """
        Update STOP_LOSS in config_data and config_file.
        Args:
            new_sl (float): New stop loss value
        Raises:
            ConfigurationError: If update or save fails
        """
        try:
            # Update in-memory config
            if "trading_options" not in self.config_data:
                raise ConfigurationError("Missing 'trading_options' in config.")
            self.config_data["trading_options"]["STOP_LOSS"] = float(new_sl)
            # Write to file
            with open(self.config_file, "w", encoding="utf-8") as file:
                yaml.safe_dump(self.config_data, file, default_flow_style=False)
        except Exception as e:
            raise ConfigurationError(f"Failed to update STOP_LOSS: {e}")
