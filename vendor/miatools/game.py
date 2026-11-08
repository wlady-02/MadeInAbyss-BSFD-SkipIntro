"""State of the running game."""
import subprocess
import time

from .paths import EXECUTABLE

# The bracket keeps pgrep from matching its own command line.
_PGREP_PATTERN = "[" + EXECUTABLE[0] + "]" + EXECUTABLE[1:].removesuffix(".exe")


KILL_WAIT_S = 10


class GameRunning(RuntimeError):
    """Raised when an operation needs the game to be closed."""


def is_running():
    """Return True if the game process exists."""
    result = subprocess.run(["pgrep", "-f", _PGREP_PATTERN], capture_output=True)
    return result.returncode == 0


def require_closed(action):
    """Raise ``GameRunning`` if the game is open.

    Args:
        action: what the caller is about to do, used in the error message.
    """
    if is_running():
        raise GameRunning(f"Close the game before: {action}")


def kill():
    """End the game process (SIGTERM, then SIGKILL after ``KILL_WAIT_S`` seconds); return True if it is gone.

    Only for a game that no longer answers (e.g. its window vanished while the process stayed).
    """
    for signal_name in ("TERM", "KILL"):
        subprocess.run(["pkill", f"-{signal_name}", "-f", _PGREP_PATTERN], capture_output=True)
        end = time.monotonic() + KILL_WAIT_S
        while time.monotonic() < end:
            if not is_running():
                return True
            time.sleep(0.5)
    return not is_running()
