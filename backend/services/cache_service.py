# backend/services/cache_service.py
import redis.asyncio as redis
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

class CacheService:
    """Redis cache service"""
    
    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self.client = None
    
    async def connect(self):
        """Connect to Redis"""
        try:
            self.client = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5
            )
            
            await self.client.ping()
            logger.info("✓ Connected to Redis Cache")
            
        except Exception as e:
            logger.error(f"✗ Failed to connect to Redis: {e}")
            raise
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        try:
            value = await self.client.get(key)
            return json.loads(value) if value else None
        except Exception as e:
            logger.error(f"✗ Cache get error: {e}")
            return None
    
    async def set(self, key: str, value: Any, expire: int = 3600):
        """Set value in cache"""
        try:
            await self.client.setex(key, expire, json.dumps(value))
        except Exception as e:
            logger.error(f"✗ Cache set error: {e}")
    
    async def delete(self, key: str):
        """Delete key"""
        try:
            await self.client.delete(key)
        except Exception as e:
            logger.error(f"✗ Cache delete error: {e}")
    
    async def close(self):
        """Close connection"""
        if self.client:
            await self.client.close()
            logger.info("✓ Closed Redis cache connection")