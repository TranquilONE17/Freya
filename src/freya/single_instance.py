import os


MUTEX_NAME = "Local\\FreyaAssistant"

ERROR_ALREADY_EXISTS = 183

_handle = None


def claim() -> bool:
    """
    Return True if this is the only Freya running for this user.

    Two copies would both listen to the microphone and answer. The
    claim is a named Windows mutex, which Windows releases when this
    process ends for any reason. On other systems, or when
    FREYA_ALLOW_MULTIPLE=1, the claim always succeeds.
    """
    global _handle

    if os.name != "nt" or os.environ.get("FREYA_ALLOW_MULTIPLE") == "1":
        return True

    if _handle is not None:
        return True

    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]

        handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)

        if not handle:
            return True

        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False

        _handle = handle
        return True
    except Exception:
        # Never let the guard itself stop Freya from starting.
        return True


def show_message(text: str, title: str = "Freya") -> None:
    """
    Tell the owner something when there is no console to print to.
    """
    if os.name != "nt":
        print(text)
        return

    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)
    except Exception:
        pass
