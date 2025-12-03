# backend/services/queue_service.py
import asyncio
from typing import Dict, Any, Optional
import logging
from collections import deque

logger = logging.getLogger(__name__)

class InMemoryQueue:
    """In-memory queue using asyncio.Queue - NO external dependencies"""
    
    def __init__(self, maxsize: int = 10000):
        self.queue = asyncio.Queue(maxsize=maxsize)
        self.stats = {
            'total_enqueued': 0,
            'total_processed': 0,
            'queue_full_count': 0,
            'processing_errors': 0
        }
        self._recent_logs = deque(maxlen=100)  # Keep last 100 for WebSocket
    
    async def enqueue(self, log_data: Dict[str, Any]) -> bool:
        """Add log to queue"""
        try:
            # Try to add without blocking
            self.queue.put_nowait(log_data)
            self.stats['total_enqueued'] += 1
            self._recent_logs.append(log_data)
            return True
        except asyncio.QueueFull:
            self.stats['queue_full_count'] += 1
            logger.warning("⚠️ Queue is full, dropping log")
            return False
        except Exception as e:
            logger.error(f"❌ Error enqueueing log: {e}")
            return False
    
    async def dequeue(self, timeout: float = 1.0) -> Optional[Dict[str, Any]]:
        """Get log from queue"""
        try:
            log_data = await asyncio.wait_for(
                self.queue.get(),
                timeout=timeout
            )
            return log_data
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            logger.error(f"❌ Error dequeuing log: {e}")
            return None
    
    async def dequeue_batch(self, batch_size: int, timeout: float = 1.0) -> list:
        """Get multiple logs from queue"""
        batch = []
        
        try:
            # Get first item with timeout
            first_item = await asyncio.wait_for(
                self.queue.get(),
                timeout=timeout
            )
            batch.append(first_item)
            
            # Get remaining items without blocking
            for _ in range(batch_size - 1):
                try:
                    item = self.queue.get_nowait()
                    batch.append(item)
                except asyncio.QueueEmpty:
                    break
        
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            logger.error(f"❌ Error dequeuing batch: {e}")
        
        return batch
    
    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics"""
        return {
            **self.stats,
            'current_size': self.queue.qsize(),
            'max_size': self.queue.maxsize
        }
    
    def get_recent_logs(self, count: int = 10) -> list:
        """Get recent logs for WebSocket streaming"""
        return list(self._recent_logs)[-count:]

# Global queue instance
log_queue = InMemoryQueue()