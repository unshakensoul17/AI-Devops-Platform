# backend/services/redis_stream_service.py
import redis.asyncio as redis
import json
import logging
from typing import Dict, Any, List, Optional
import asyncio
from datetime import datetime

logger = logging.getLogger(__name__)

class RedisStreamService:
    """Complete Redis Streams implementation for log processing"""
    
    def __init__(
        self,
        redis_url: str,
        stream_name: str = "logs-stream",
        consumer_group: str = "log-processors",
        consumer_name: str = "consumer-1"
    ):
        self.redis_url = redis_url
        self.stream_name = stream_name
        self.consumer_group = consumer_group
        self.consumer_name = consumer_name
        self.client: Optional[redis.Redis] = None
        
    async def connect(self):
        """Establish Redis connection"""
        try:
            self.client = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5,
                socket_keepalive=True,
                health_check_interval=30
            )
            
            # Test connection
            await self.client.ping()
            logger.info(f"✓ Connected to Redis at {self.redis_url}")
            
            # Initialize consumer group
            await self.initialize_consumer_group()
            
        except Exception as e:
            logger.error(f"✗ Failed to connect to Redis: {e}")
            raise
    
    async def initialize_consumer_group(self):
        """Create consumer group if it doesn't exist"""
        try:
            await self.client.xgroup_create(
                name=self.stream_name,
                groupname=self.consumer_group,
                id='0',
                mkstream=True
            )
            logger.info(f"✓ Created consumer group: {self.consumer_group}")
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                logger.info(f"✓ Consumer group already exists: {self.consumer_group}")
            else:
                logger.error(f"✗ Error creating consumer group: {e}")
                raise
    
    async def produce(self, log_data: Dict[str, Any]) -> str:
        """Add log to stream (Producer)"""
        try:
            # Add timestamp if not present
            if 'timestamp' not in log_data:
                log_data['timestamp'] = datetime.utcnow().isoformat()
            
            # Add to stream
            message_id = await self.client.xadd(
                name=self.stream_name,
                fields={'data': json.dumps(log_data)},
                maxlen=100000,  # Keep last 100k messages
                approximate=True
            )
            
            return message_id
            
        except Exception as e:
            logger.error(f"✗ Error producing message: {e}")
            raise
    
    async def produce_batch(self, logs: List[Dict[str, Any]]) -> int:
        """Add multiple logs to stream"""
        try:
            pipeline = self.client.pipeline()
            
            for log_data in logs:
                if 'timestamp' not in log_data:
                    log_data['timestamp'] = datetime.utcnow().isoformat()
                
                pipeline.xadd(
                    name=self.stream_name,
                    fields={'data': json.dumps(log_data)},
                    maxlen=100000,
                    approximate=True
                )
            
            results = await pipeline.execute()
            logger.info(f"✓ Produced {len(results)} messages to stream")
            return len(results)
            
        except Exception as e:
            logger.error(f"✗ Error producing batch: {e}")
            return 0
    
    async def consume(
        self,
        count: int = 10,
        block: int = 5000
    ) -> List[Dict[str, Any]]:
        """Consume logs from stream (Consumer)"""
        try:
            # Read from consumer group
            messages = await self.client.xreadgroup(
                groupname=self.consumer_group,
                consumername=self.consumer_name,
                streams={self.stream_name: '>'},
                count=count,
                block=block
            )
            
            if not messages:
                return []
            
            processed = []
            for stream_name, stream_messages in messages:
                for message_id, fields in stream_messages:
                    try:
                        log_data = json.loads(fields['data'])
                        processed.append({
                            'message_id': message_id,
                            'data': log_data
                        })
                    except json.JSONDecodeError as e:
                        logger.error(f"✗ Failed to decode message {message_id}: {e}")
                        continue
            
            return processed
            
        except Exception as e:
            logger.error(f"✗ Error consuming messages: {e}")
            return []
    
    async def acknowledge(self, message_ids: List[str]) -> int:
        """Acknowledge processed messages"""
        try:
            if not message_ids:
                return 0
            
            count = await self.client.xack(
                self.stream_name,
                self.consumer_group,
                *message_ids
            )
            
            return count
            
        except Exception as e:
            logger.error(f"✗ Error acknowledging messages: {e}")
            return 0
    
    async def get_pending_messages(self) -> List[Dict]:
        """Get pending (unacknowledged) messages"""
        try:
            pending = await self.client.xpending_range(
                name=self.stream_name,
                groupname=self.consumer_group,
                min='-',
                max='+',
                count=100
            )
            
            return [
                {
                    'message_id': p['message_id'],
                    'consumer': p['consumer'],
                    'idle_time': p['time_since_delivered']
                }
                for p in pending
            ]
            
        except Exception as e:
            logger.error(f"✗ Error getting pending messages: {e}")
            return []
    
    async def claim_pending_messages(self, min_idle_time: int = 60000) -> List[Dict]:
        """Claim pending messages that have been idle too long"""
        try:
            pending = await self.get_pending_messages()
            
            if not pending:
                return []
            
            # Claim messages idle for more than min_idle_time
            idle_message_ids = [
                p['message_id'] for p in pending 
                if p['idle_time'] > min_idle_time
            ]
            
            if not idle_message_ids:
                return []
            
            claimed = await self.client.xclaim(
                name=self.stream_name,
                groupname=self.consumer_group,
                consumername=self.consumer_name,
                min_idle_time=min_idle_time,
                message_ids=idle_message_ids
            )
            
            return [
                {
                    'message_id': msg_id,
                    'data': json.loads(fields['data'])
                }
                for msg_id, fields in claimed
            ]
            
        except Exception as e:
            logger.error(f"✗ Error claiming messages: {e}")
            return []
    
    async def get_stream_info(self) -> Dict[str, Any]:
        """Get stream statistics"""
        try:
            info = await self.client.xinfo_stream(self.stream_name)
            groups = await self.client.xinfo_groups(self.stream_name)
            
            return {
                'stream_length': info['length'],
                'first_entry_id': info.get('first-entry', [None])[0],
                'last_entry_id': info.get('last-entry', [None])[0],
                'consumer_groups': len(groups),
                'groups': [
                    {
                        'name': g['name'],
                        'consumers': g['consumers'],
                        'pending': g['pending']
                    }
                    for g in groups
                ]
            }
            
        except Exception as e:
            logger.error(f"✗ Error getting stream info: {e}")
            return {}
    
    async def trim_stream(self, maxlen: int = 100000):
        """Trim stream to maximum length"""
        try:
            await self.client.xtrim(
                name=self.stream_name,
                maxlen=maxlen,
                approximate=True
            )
            logger.info(f"✓ Trimmed stream to {maxlen} messages")
        except Exception as e:
            logger.error(f"✗ Error trimming stream: {e}")
    
    async def close(self):
        """Close Redis connection"""
        if self.client:
            await self.client.close()
            logger.info("✓ Closed Redis connection")