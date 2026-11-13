import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run("studio.server:app", host=os.environ.get("STUDIO_HOST", "127.0.0.1"),
                port=int(os.environ.get("STUDIO_PORT", "8765")), reload=False)
