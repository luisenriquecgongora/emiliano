"""
Single instance mutex guard using loopback socket (derived from robot_host).
Prevents duplicate engine daemon processes from fighting over OS input hooks or ports.
"""

import socket
import sys
from loguru import logger

DEFAULT_MUTEX_PORT = 51838  # Distinct from robot_host's 51837


class SingleInstanceGuard:
    def __init__(self, port: int = DEFAULT_MUTEX_PORT):
        self.port = port
        self.sock = None

    def acquire(self) -> bool:
        """Attempts to bind to 127.0.0.1:<port>. Returns True if acquired, False otherwise."""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # Do NOT use SO_REUSEADDR on Windows loopback as it can allow hijacking
            self.sock.bind(("127.0.0.1", self.port))
            self.sock.listen(1)
            logger.debug(f"[Engine] Acquired single-instance mutex on port {self.port}")
            return True
        except socket.error as e:
            logger.warning(f"[Engine] Could not bind to mutex port {self.port}: {e}")
            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass
            self.sock = None
            return False

    def release(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
