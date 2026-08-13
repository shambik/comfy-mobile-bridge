import uvicorn

from backend.config import APP_HOST, APP_PORT

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host=APP_HOST, port=APP_PORT, log_level="info")
