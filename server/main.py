import uvicorn

from .app import create_app
from .config import load_config

if __name__ == "__main__":
    import sys
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.SetPriorityClass.restype = wintypes.BOOL
        kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), 0x00004000)
    config = load_config()
    uvicorn.run(create_app(config), host="127.0.0.1", port=config["port"],
                ws_max_size=131072, access_log=False, log_level="warning")
