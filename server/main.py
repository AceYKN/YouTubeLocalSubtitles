import uvicorn

from .app import create_app
from .config import load_config

if __name__ == "__main__":
    config = load_config()
    uvicorn.run(create_app(config), host="127.0.0.1", port=config["port"],
                ws_max_size=131072, access_log=False, log_level="warning")
