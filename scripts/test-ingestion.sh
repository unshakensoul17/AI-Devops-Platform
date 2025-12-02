# scripts/test-ingestion.sh
#!/bin/bash

echo "🧪 Testing log ingestion..."

# Send sample logs
curl -X POST http://localhost:8000/api/logs/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "level": "ERROR",
    "message": "Database connection failed: timeout after 30s",
    "service": "api-gateway",
    "timestamp": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"
  }'

echo ""
echo "✅ Log sent! Check the stream:"
curl -s http://localhost:8000/api/stream/info | jq