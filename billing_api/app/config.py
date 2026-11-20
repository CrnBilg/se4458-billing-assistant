"""Runtime configuration, read from environment variables (see .env.example)."""
import os

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://billing:billing@localhost:5432/billing"
)
# Override in any real deployment (>= 32 chars): e.g. `openssl rand -hex 32`.
JWT_SECRET = os.getenv("JWT_SECRET", "dev-only-secret-change-me-in-production-0123456789")
JWT_ALGORITHM = "HS256"
# `iss` claim; the API Gateway (Kong jwt plugin) maps it to its consumer credential.
JWT_ISSUER = os.getenv("JWT_ISSUER", "billing-api")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))
PBKDF2_ITERATIONS = int(os.getenv("PBKDF2_ITERATIONS", "200000"))
# Create tables on startup (convenient for docker-compose / first deploy).
AUTO_CREATE_TABLES = os.getenv("AUTO_CREATE_TABLES", "true").lower() == "true"
