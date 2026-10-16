# external_signal_manager.py
import multiprocessing as mp
import importlib
import os
import glob
from typing import Dict, Any, List
from loguru import logger


def run_signal_module_process(module_name: str):
    """Run a signal module in a separate process."""

    try:
        logger.info(f"📡 Signal module {module_name} process started")

        module = importlib.import_module(module_name)

        if hasattr(module, "do_work"):
            module.do_work()
        else:
            logger.warning(f"⚠️ Module {module_name} has no do_work function")

    except Exception as e:
        logger.error(f"💥 Error in signal module {module_name}: {e}")
    finally:
        logger.info(f"📡 Signal module {module_name} process ended")


class ExternalSignalManager:
    """Manages external signal modules using multiprocessing."""

    def __init__(self, config: Dict[str, Any]):
        """Initialize external signal manager."""
        self.config = config
        self.signalling_modules = config.get("SIGNALLING_MODULES", [])
        self.signal_processes = {}
        self.signal_queue = mp.Queue()
        self.stop_event = mp.Event()

        logger.info(
            f"📡 External signal manager initialized with {len(self.signalling_modules)} modules"
        )

    def start_signal_modules(self):
        """Start all signal modules in separate processes."""
        try:
            for module_name in self.signalling_modules:
                try:
                    process = mp.Process(
                        target=run_signal_module_process,
                        args=(module_name,),
                    )
                    process.start()
                    self.signal_processes[module_name] = process
                    logger.info(f"📡 Started signal module: {module_name}")

                except Exception as e:
                    logger.error(f"💥 Failed to start signal module {module_name}: {e}")

        except Exception as e:
            logger.error(f"💥 Error starting signal modules: {e}")

    def get_external_signals(self) -> Dict[str, Any]:
        """Get signals from external signal files."""
        external_signals = {}

        try:
            # Check for signal files
            signal_files = self._get_signal_files()
            if not signal_files:
                logger.debug("📡 No signal files found")
                return {}

            logger.info(f"📡 Processing {len(signal_files)} signal files")

            for signal_file in signal_files:
                try:
                    signals = self._read_signal_file(signal_file)
                    external_signals.update(signals)

                    # Remove processed signal file
                    os.remove(signal_file)
                    logger.debug(f"📡 Processed and removed signal file: {signal_file}")

                except Exception as e:
                    logger.error(f"💥 Error processing signal file {signal_file}: {e}")

        except Exception as e:
            logger.error(f"💥 Error getting external signals: {e}")

        return external_signals

    def _get_signal_files(self) -> List[str]:
        """Get list of signal files."""

        signal_files = []
        all_files = glob.glob("signals/*")

        for file_path in all_files:
            if os.path.isfile(file_path):
                filename = os.path.basename(file_path)
                if not filename.lower().startswith("readme"):
                    signal_files.append(file_path)

        logger.debug(f"📡 Found signal files: {signal_files}")

        return signal_files

    def _read_signal_file(self, signal_file: str) -> Dict[str, Any]:
        """Read signals from a file with proper signal type detection."""
        signals = {}

        try:
            filename = os.path.basename(signal_file)

            if ".sell" in filename.lower() or "sell" in filename.lower():
                signal_type = "sell"
                signal_key = "sell_signal"
            else:
                signal_type = "buy"
                signal_key = "buy_signal"

            logger.debug(f"📡 Processing {signal_type} signal file: {filename}")

            with open(signal_file, "r") as f:
                for line in f:
                    symbol = line.strip()
                    if symbol and symbol.upper().endswith(self.config.get("PAIR_WITH")):
                        signals[symbol] = {
                            signal_key: "external_signal",
                            "signal_type": signal_type,
                            "value": 1,
                            "source": filename,
                        }
                        logger.debug(f"📡 Added {signal_type} signal for {symbol}")

            logger.debug(
                f"📡 Loaded {len(signals)} {signal_type} signals from {filename}"
            )

        except Exception as e:
            logger.error(f"💥 Error reading signal file {signal_file}: {e}")

        return signals

    def stop_all_modules(self):
        """Stop all signal modules."""
        try:
            logger.info("📡 Stopping all signal modules...")

            # Set stop event
            self.stop_event.set()

            # Terminate all processes
            for module_name, process in self.signal_processes.items():
                try:
                    if process.is_alive():
                        process.terminate()
                        process.join(timeout=5)

                        if process.is_alive():
                            process.kill()
                            process.join()

                    logger.info(f"📡 Stopped signal module: {module_name}")

                except Exception as e:
                    logger.error(f"💥 Error stopping signal module {module_name}: {e}")

            self.signal_processes.clear()
            logger.info("📡 All signal modules stopped")

        except Exception as e:
            logger.error(f"💥 Error stopping signal modules: {e}")
