class CPUBridgeError(RuntimeError):
    """Base error for bridge communication and protocol failures."""


class CPUBridgeTimeoutError(CPUBridgeError, TimeoutError):
    """A bridge read or write exceeded its configured timeout."""


class CPUBridgeConnectionError(CPUBridgeError, ConnectionError):
    """The bridge connection could not be established or was lost."""


class CPUBridgeProtocolError(CPUBridgeError):
    """The bridge sent or received a message outside the protocol contract."""


class CPUBridgeServerError(CPUBridgeError):
    """The bridge rejected a command or action."""

    def __init__(self, code: str, message: str, sequence: int | None = None) -> None:
        self.code = code
        self.message = message
        self.sequence = sequence
        super().__init__(f"{code}: {message}")
