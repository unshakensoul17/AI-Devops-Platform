# backend/consumers/stream_consumer.py
import asyncio
import signal
import sys
import logging
from typing import List, Dict
from datetime import datetime

from config.settings import get_settings
from services.redis_stream_service import RedisStreamService
from services.groq_service import GroqAIService
from services.log_processor import LogProcessor
from services.opensearch_client import OpenSearchClient
from services.cache_service import CacheService

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

settings = get_settings()

class StreamConsumerWorker:
    """Background worker that consumes logs from Redis Streams"""
    
    def __init__(self):
        self.running = False
        self.stream_service = None
        self.groq_service = None
        self.log_processor = None
        self.opensearch = None
        self.cache = None
        
        # Statistics
        self.stats = {
            'processed': 0,
            'errors': 0,
            'started_at': None
        }
    
    async def initialize(self):
        """Initialize all services"""
        logger.info("🚀 Initializing Stream Consumer Worker...")
        
        try:
            # Initialize Redis Streams
            self.stream_service = RedisStreamService(
                redis_url=settings.REDIS_URL,
                stream_name=settings.STREAM_NAME,
                consumer_group=settings.STREAM_GROUP,
                consumer_name=settings.STREAM_CONSUMER
            )
            await self.stream_service.connect()
            
            # Initialize Groq AI
            self.groq_service = GroqAIService()
            
            # Initialize Log Processor
            self.log_processor = LogProcessor(groq_service=self.groq_service)
            
            # Initialize OpenSearch
            self.opensearch = OpenSearchClient(
                hosts=[{
                    'host': settings.OPENSEARCH_HOST,
                    'port': settings.OPENSEARCH_PORT
                }],
                http_auth=(settings.OPENSEARCH_USERNAME, settings.OPENSEARCH_PASSWORD) if settings.OPENSEARCH_USERNAME else None,
                use_ssl=settings.OPENSEARCH_USE_SSL
            )
            await self.opensearch.connect()
            
            # Initialize Cache
            self.cache = CacheService(redis_url=settings.REDIS_URL)
            await self.cache.connect()
            
            self.stats['started_at'] = datetime.utcnow()
            logger.info("✅ All services initialized successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize services: {e}")
            raise
    
    async def start(self):
        """Start consuming logs"""
        self.running = True
        logger.info("▶️  Starting log consumption...")
        
        batch = []
        batch_size = settings.BATCH_SIZE
        
        while self.running:
            try:
                # Consume messages from stream
                messages = await self.stream_service.consume(
                    count=batch_size,
                    block=1000  # Block for 1 second
                )
                
                if not messages:
                    # No new messages, process pending batch if any
                    if batch:
                        await self._process_batch(batch)
                        batch = []
                    
                    # Check for pending messages that need reprocessing
                    await self._handle_pending_messages()
                    
                    continue
                
                # Process each message
                for message in messages:
                    try:
                        raw_log = message['data']
                        message_id = message['message_id']
                        
                        # Process log
                        processed_log = await self.log_processor.process(raw_log)
                        processed_log['stream_message_id'] = message_id
                        
                        batch.append(processed_log)
                        
                        # Process batch when full
                        if len(batch) >= batch_size:
                            await self._process_batch(batch)
                            
                            # Acknowledge messages
                            message_ids = [log['stream_message_id'] for log in batch]
                            await self.stream_service.acknowledge(message_ids)
                            
                            batch = []
                        
                    except Exception as e:
                        logger.error(f"❌ Error processing message: {e}")
                        self.stats['errors'] += 1
                        continue
                
                # Small delay to prevent tight loop
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"❌ Error in consumer loop: {e}")
                await asyncio.sleep(5)  # Wait before retrying
        
        # Process remaining batch on shutdown
        if batch:
            await self._process_batch(batch)
            message_ids = [log['stream_message_id'] for log in batch]
            await self.stream_service.acknowledge(message_ids)
    
    async def _process_batch(self, logs: List[Dict]):
        """Process a batch of logs"""
        try:
            # Bulk index to OpenSearch
            success = await self.opensearch.bulk_index(logs)
            
            # Update stats
            self.stats['processed'] += len(logs)
            
            # Cache statistics
            await self._update_stats_cache(logs)
            
            logger.info(f"✅ Processed batch: {success}/{len(logs)} logs indexed")
            
        except Exception as e:
            logger.error(f"❌ Error processing batch: {e}")
            self.stats['errors'] += len(logs)
    
    async def _handle_pending_messages(self):
        """Handle messages that have been pending too long"""
        try:
            # Claim messages pending for more than 1 minute
            claimed = await self.stream_service.claim_pending_messages(
                min_idle_time=60000
            )
            
            if claimed:
                logger.info(f"🔄 Reclaiming {len(claimed)} pending messages")
                
                batch = []
                for message in claimed:
                    processed_log = await self.log_processor.process(message['data'])
                    processed_log['stream_message_id'] = message['message_id']
                    batch.append(processed_log)
                
                if batch:
                    await self._process_batch(batch)
                    message_ids = [log['stream_message_id'] for log in batch]
                    await self.stream_service.acknowledge(message_ids)
        
        except Exception as e:
            logger.error(f"❌ Error handling pending messages: {e}")
    
    async def _update_stats_cache(self, logs: List[Dict]):
        """Update statistics in cache"""
        try:
            # Count by level
            level_counts = {}
            service_counts = {}
            error_type_counts = {}
            
            for log in logs:
                level = log['level']
                service = log['service']
                error_type = log.get('error_type')
                
                level_counts[level] = level_counts.get(level, 0) + 1
                service_counts[service] = service_counts.get(service, 0) + 1
                
                if error_type:
                    error_type_counts[error_type] = error_type_counts.get(error_type, 0) + 1
            
            # Increment counters in Redis
            pipeline = self.cache.client.pipeline()
            
            for level, count in level_counts.items():
                pipeline.hincrby('stats:logs:level', level, count)
            
            for service, count in service_counts.items():
                pipeline.hincrby('stats:logs:service', service, count)
            
            for error_type, count in error_type_counts.items():
                pipeline.hincrby('stats:errors:type', error_type, count)
            
            await pipeline.execute()
            
        except Exception as e:
            logger.error(f"❌ Error updating stats: {e}")
    
    def stop(self):
        """Stop the consumer"""
        logger.info("🛑 Stopping consumer...")
        self.running = False
    
    async def shutdown(self):
        """Cleanup and shutdown"""
        logger.info("🔌 Shutting down consumer...")
        
        self.stop()
        
        # Close connections
        if self.stream_service:
            await self.stream_service.close()
        
        if self.opensearch:
            await self.opensearch.close()
        
        if self.cache:
            await self.cache.close()
        
        # Print final stats
        logger.info(f"""
📊 Final Statistics:
   Processed: {self.stats['processed']} logs
   Errors: {self.stats['errors']}
   Runtime: {datetime.utcnow() - self.stats['started_at'] if self.stats['started_at'] else 'N/A'}
        """)

# Main execution
async def main():
    worker = StreamConsumerWorker()
    
    # Setup signal handlers
    def signal_handler(signum, frame):
        logger.info(f"📡 Received signal {signum}")
        asyncio.create_task(worker.shutdown())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await worker.initialize()
        await worker.start()
    except Exception as e:
        logger.error(f"❌ Worker failed: {e}")
        await worker.shutdown()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())