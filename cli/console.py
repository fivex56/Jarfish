import asyncio
import sys
import threading
from datetime import datetime


class ConsoleBridge:
    """Bridges CLI stdin/stdout with the bot via asyncio queues."""

    def __init__(self, cli_to_bot: asyncio.Queue, bot_to_cli: asyncio.Queue):
        self.incoming: asyncio.Queue = cli_to_bot
        self.outgoing: asyncio.Queue = bot_to_cli
        self._reading = False

    async def start_stdin_reader(self):
        """Read stdin in a thread (Windows asyncio stdin limitation) and put on queue."""
        self._reading = True
        loop = asyncio.get_event_loop()

        def read_lines():
            while self._reading:
                try:
                    line = sys.stdin.readline()
                    if not line:
                        break
                    text = line.strip()
                    if text:
                        asyncio.run_coroutine_threadsafe(
                            self.incoming.put({
                                "type": "cli_message",
                                "text": text,
                                "timestamp": datetime.now().isoformat()
                            }),
                            loop
                        )
                except (OSError, EOFError):
                    break
                except Exception:
                    break

        thread = threading.Thread(target=read_lines, daemon=True)
        thread.start()

    async def stdout_writer(self):
        """Drain outgoing queue and print to stdout."""
        while True:
            try:
                msg = await self.outgoing.get()
                formatted = self._format(msg)
                print(formatted, flush=True)
            except UnicodeEncodeError:
                # Windows console may not support all Unicode chars
                print(formatted.encode("ascii", errors="replace").decode("ascii"), flush=True)
            except Exception:
                pass  # Don't crash the whole bot on a print error

    def _format(self, msg: dict) -> str:
        ts = datetime.now().strftime("%H:%M:%S")
        source = msg.get("source", "system")
        text = msg.get("text", "")

        # Color codes
        CYAN = "\033[36m"
        YELLOW = "\033[33m"
        GREEN = "\033[32m"
        RESET = "\033[0m"

        if source == "telegram":
            return f"[{ts}] {CYAN}[TG]{RESET} {text}"
        elif source == "jarvis":
            return f"[{ts}] {GREEN}[JARVIS]{RESET} {text}"
        elif source == "system":
            return f"[{ts}] {YELLOW}[SYS]{RESET} {text}"
        else:
            return f"[{ts}] {text}"

    def stop(self):
        self._reading = False
