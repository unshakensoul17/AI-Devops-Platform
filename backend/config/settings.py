# backend/config/settings.py
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    # Application
    APP_NAME: str = "AI DevOps Platform FREE"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = "production"
    DEBUG: bool = False
    
    # Database (Render provides this automatically)
    DATABASE_URL: str = ""  # Will be injected by Render
    
    # Groq AI
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.1-70b-versatile"
    GROQ_MAX_TOKENS: int = 1024
    GROQ_TEMPERATURE: float = 0.3
    
    # Queue Settings (In-Memory)
    QUEUE_MAX_SIZE: int = 10000  # Max logs in memory
    BATCH_SIZE: int = 50         # Process in batches
    PROCESSING_INTERVAL: int = 2  # Seconds between batch processing
    
    # Log Retention
    LOG_RETENTION_DAYS: int = 7  # Keep logs for 7 days (FREE tier)
    
    # CORS
    ALLOWED_ORIGINS: list = ["*"]
    
    class Config:
        env_file = ".env"
        case_sensitive = False

@lru_cache()
def get_settings() -> Settings:
    return Settings()