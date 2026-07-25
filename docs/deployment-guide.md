# Deployment Guide

This guide covers deploying Agent Hub to production environments.

## Prerequisites

- Docker and Docker Compose (for containerized deployment)
- PostgreSQL 15+ with pgvector extension
- Redis (optional, for Celery workers and rate limiting)
- Neo4j (optional, for skill knowledge graph)

## Deployment Steps

### 1. Database Migration

Always run migrations before deploying new code:

```bash
# Run migrations
alembic upgrade head

# Verify migration status
alembic current
```

### 2. Build Container Images

Images are automatically built by CI/CD on push to `main` or version tags:

```bash
# Manual build (if needed)
docker build -t agent-hub:latest .
docker build -t agent-hub-frontend:latest ./frontend
```

### 3. Deploy Application

Using Docker Compose:

```bash
# Pull latest images
docker compose pull

# Deploy with zero downtime (rolling update)
docker compose up -d --no-deps --scale api=2

# Or full stack restart
docker compose up -d
```

### 4. Verify Deployment

```bash
# Health check
curl -I https://api.yourdomain.com/health

# Expected response headers include:
# X-Content-Type-Options: nosniff
# X-Frame-Options: DENY
# X-RateLimit-Limit: 100
```

## Zero-Downtime Deployment

For zero-downtime deployments, use rolling updates:

### Docker Compose

```bash
# Scale up new instances
docker compose up -d --no-deps --scale api=2

# Wait for health checks
sleep 30

# Scale down old instances
docker compose up -d --no-deps --scale api=1
```

### Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: agent-hub-api
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
```

## Rollback Procedure

### Quick Rollback

```bash
# Revert to previous image
docker compose down
docker compose pull previous-tag
docker compose up -d
```

### Database Rollback

```bash
# List migration history
alembic history

# Downgrade to specific revision
alembic downgrade <revision>

# Downgrade one step
alembic downgrade -1
```

## Health Check Endpoints

| Endpoint | Purpose | Expected Response |
|----------|---------|-------------------|
| `GET /health` | Application health | `{"status": "ok"}` |
| `GET /healthz` | Kubernetes liveness | 200 OK |
| `GET /ready` | Kubernetes readiness | 200 OK |

### Health Check Configuration

```yaml
# Kubernetes example
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 30

readinessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 10
```

## Monitoring

### Key Metrics

- Request rate and latency
- Error rate (4xx, 5xx)
- Rate limit hits (429 responses)
- Database connection pool usage
- Memory and CPU usage

### Log Format

Logs are output in JSON format for structured logging:

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "level": "INFO",
  "message": "Request processed",
  "path": "/platform/v1/agents",
  "status": 200,
  "duration_ms": 45
}
```

Sensitive data (passwords, tokens, API keys) is automatically redacted.

## Troubleshooting

### Common Issues

**1. Rate limiting too aggressive**

Increase the limit:
```bash
RATE_LIMIT_RPM=200
```

Or disable temporarily:
```bash
RATE_LIMIT_ENABLED=false
```

**2. CORS errors**

Ensure `CORS_ALLOWED_ORIGINS` includes your frontend domain:
```bash
CORS_ALLOWED_ORIGINS=https://console.yourdomain.com,https://api.yourdomain.com
```

**3. Database connection errors**

Check connection pool settings:
```bash
# Increase pool size if needed
DATABASE_POOL_SIZE=20
DATABASE_MAX_OVERFLOW=10
```

**4. Redis unavailable**

Rate limiting and chat streaming degrade gracefully:
- Rate limiting: pass-through (all requests allowed)
- Chat streaming: falls back to non-resumable inline mode

### Debug Commands

```bash
# Check container logs
docker compose logs -f api

# Check database connectivity
docker compose exec api python -c "from agent_hub.database.config import create_repository; print(create_repository())"

# Check Redis connectivity
docker compose exec api python -c "import redis; r = redis.from_url('redis://redis:6379/0'); print(r.ping())"
```

## Security Considerations

1. **Never expose debug endpoints in production**
2. **Use TLS termination at load balancer**
3. **Rotate secrets regularly**
4. **Monitor for security alerts from CI/CD**
5. **Keep dependencies updated**

## Scaling

### Horizontal Scaling

```bash
# Scale API instances
docker compose up -d --scale api=4

# Scale Celery workers
docker compose up -d --scale worker=4
```

### Vertical Scaling

Adjust resource limits in docker-compose.yml:

```yaml
services:
  api:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G
        reservations:
          cpus: '0.5'
          memory: 1G
```
