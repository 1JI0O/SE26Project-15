import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/tracelab-server-tests.db")
os.environ.setdefault("CLOUD_BLOB_ROOT", "/tmp/tracelab-server-tests/blobs")
os.environ.setdefault("CLOUD_TMP_ROOT", "/tmp/tracelab-server-tests/tmp")
os.environ.setdefault("CLOUD_JWT_SECRET", "test-only-secret-with-at-least-thirty-two-bytes")
