"""Probe for a free TCP port starting at a preferred default.

Used by scripts/setup.sh to pick host-side ports for docker-compose when the
defaults are in use. Prints the chosen port to stdout; exits non-zero only on
unrecoverable error.
"""

import socket
import sys


def is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def find(preferred: int, max_tries: int = 100) -> int:
    for offset in range(max_tries):
        candidate = preferred + offset
        if candidate > 65535:
            break
        if is_free(candidate):
            return candidate
    raise RuntimeError(f"no free port found near {preferred}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: find_free_port.py <preferred_port>", file=sys.stderr)
        sys.exit(2)
    print(find(int(sys.argv[1])))
