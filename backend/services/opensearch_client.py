# backend/services/opensearch_client.py
from opensearchpy import AsyncOpenSearch, helpers
from typing import List, Dict, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class OpenSearchClient:
    """Async OpenSearch client for log storage"""
    
    def __init__(self, hosts: List[Dict], http_auth=None, use_ssl=False):
        self.hosts = hosts
        self.http_auth = http_auth
        self.use_ssl = use_ssl
        self.client = None
    
    async def connect(self):
        """Connect to OpenSearch"""
        try:
            self.client = AsyncOpenSearch(
                hosts=self.hosts,
                http_auth=self.http_auth,
                use_ssl=self.use_ssl,
                verify_certs=False,
                ssl_show_warn=False,
                timeout=30,
                max_retries=3,
                retry_on_timeout=True
            )
            
            # Test connection
            info = await self.client.info()
            logger.info(f"✓ Connected to OpenSearch: {info['version']['number']}")
            
            # Create index template
            await self._create_index_template()
            
        except Exception as e:
            logger.error(f"✗ Failed to connect to OpenSearch: {e}")
            raise
    
    async def _create_index_template(self):
        """Create index template for logs"""
        template = {
            "index_patterns": ["logs-*"],
            "template": {
                "settings": {
                    "number_of_shards": 1,
                    "number_of_replicas": 1,
                    "refresh_interval": "5s",
                    "index.mapping.total_fields.limit": 2000
                },
                "mappings": {
                    "properties": {
                        "id": {"type": "keyword"},
                        "timestamp": {"type": "date"},
                        "level": {"type": "keyword"},
                        "message": {"type": "text"},
                        "service": {"type": "keyword"},
                        "source": {"type": "keyword"},
                        "environment": {"type": "keyword"},
                        "host": {"type": "keyword"},
                        "error_type": {"type": "keyword"},
                        "stack_trace": {"type": "text"},
                        "metadata": {"type": "object"},
                        "ai_analysis": {"type": "object"}
                    }
                }
            }
        }
        
        try:
            await self.client.indices.put_index_template(
                name="logs-template",
                body=template
            )
            logger.info("✓ Index template created")
        except Exception as e:
            logger.warning(f"⚠ Index template creation warning: {e}")
    
    async def bulk_index(self, logs: List[Dict[str, Any]]) -> int:
        """Bulk index logs"""
        if not logs:
            return 0
        
        index_name = f"logs-{datetime.now().strftime('%Y.%m.%d')}"
        
        actions = [
            {
                "_index": index_name,
                "_id": log['id'],
                "_source": log
            }
            for log in logs
        ]
        
        try:
            success, failed = await helpers.async_bulk(
                self.client,
                actions,
                stats_only=True,
                raise_on_error=False
            )
            
            if failed:
                logger.warning(f"⚠ {failed} logs failed to index")
            
            return success
            
        except Exception as e:
            logger.error(f"✗ Bulk index error: {e}")
            return 0
    
    async def search_logs(
        self,
        query: str = None,
        level: str = None,
        service: str = None,
        start_time: str = None,
        end_time: str = None,
        size: int = 100
    ) -> Dict[str, Any]:
        """Search logs"""
        must_clauses = []
        
        if query:
            must_clauses.append({"match": {"message": query}})
        
        if level:
            must_clauses.append({"term": {"level": level}})
        
        if service:
            must_clauses.append({"term": {"service": service}})
        
        if start_time or end_time:
            range_query = {"range": {"timestamp": {}}}
            if start_time:
                range_query["range"]["timestamp"]["gte"] = start_time
            if end_time:
                range_query["range"]["timestamp"]["lte"] = end_time
            must_clauses.append(range_query)
        
        search_body = {
            "query": {
                "bool": {
                    "must": must_clauses if must_clauses else [{"match_all": {}}]
                }
            },
            "sort": [{"timestamp": {"order": "desc"}}],
            "size": size
        }
        
        try:
            response = await self.client.search(
                index="logs-*",
                body=search_body
            )
            
            return {
                "total": response['hits']['total']['value'],
                "logs": [hit['_source'] for hit in response['hits']['hits']]
            }
            
        except Exception as e:
            logger.error(f"✗ Search error: {e}")
            return {"total": 0, "logs": []}
    
    async def close(self):
        """Close connection"""
        if self.client:
            await self.client.close()
            logger.info("✓ Closed OpenSearch connection")