import os

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
MODEL_DIR = os.getenv("MODEL_DIR", "models")