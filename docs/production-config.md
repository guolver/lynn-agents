# Production Configuration

This document describes the environment variables and configuration options for deploying Agent Hub in production.

## Environment Variables

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+psycopg://user:pass@host:5432/db` |
| `AUTH_JWT_SECRET` | JWT signing secret (min 32 chars) | `python -c "import secrets; print(secrets.token_urlsafe(32))"` |

### Recommended for Production

| Variable | Description | Default | Production Value |
|----------|-------------|---------|------------------|
| `CORS_ALLOWED_ORIGINS` | Allowed CORS origins (comma-separated) | `*` (all) | `https://yourdomain.com` |
| `ENABLE_HSTS` | Enable HTTP Strict Transport Security | `false` | `true` |
| `RATE_LIMIT_ENABLED` | Enable rate limiting | `true` | `true` |
| `RATE_LIMIT_RPM` | Requests per minute per client | `100` | `100` |

### Optional Services

| Variable | Description | Default |
|----------|-------------|---------|
| `CELERY_BROKER_URL` | Redis URL for Celery | (disabled) |
| `CELERY_RESULT_BACKEND` | Redis URL for Celery results | (disabled) |
| `NEO4J_URI` | Neo4j connection URI | (disabled) |
| `NEO4J_USER` | Neo4j username | `neo4j` |
| `NEO4J_PASSWORD` | Neo4j password | (required if URI set) |
| `CHAT_STREAM_REDIS_URL` | Redis for chat streaming | Falls back to `CELERY_BROKER_URL` |

### Security Headers

| Variable | Description | Default |
|----------|-------------|---------|
| `HSTS_MAX_AGE` | HSTS max-age in seconds | `31536000` (1 year) |
| `CSP_POLICY` | Content-Security-Policy header | See below |

Default CSP policy:
```
default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'
```

## Secret Generation

Generate secure secrets using Python:

```bash
# JWT secret (32+ characters)
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Database password
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

## Security Checklist

Before deploying to production, verify:

- [ ] `AUTH_JWT_SECRET` is set to a strong random value
- [ ] `DATABASE_URL` uses a strong password
- [ ] `CORS_ALLOWED_ORIGINS` is set to specific domains (not `*`)
- [ ] `ENABLE_HSTS=true` if using HTTPS
- [ ] Rate limiting is enabled (`RATE_LIMIT_ENABLED=true`)
- [ ] All secrets are stored securely (e.g., Kubernetes secrets, Vault)
- [ ] Debug mode is disabled in production
- [ ] TLS is enabled at the load balancer/proxy level

## Rate Limiting

Rate limits are enforced per client IP:

| Path | Limit |
|------|-------|
| Default | 100 req/min |
| `/auth/login`, `/identity/login` | 10 req/min |
| `/auth/register`, `/identity/register` | 5 req/min |

When rate limited, clients receive HTTP 429 with `Retry-After` header.

## Security Headers

All responses include these security headers:

| Header | Value |
|--------|-------|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `X-XSS-Protection` | `1; mode=block` |
| `Content-Security-Policy` | Configurable |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Permissions-Policy` | Disables unnecessary browser features |
| `Strict-Transport-Security` | Enabled with `ENABLE_HSTS=true` |

## Example Production Configuration

```bash
# Required
DATABASE_URL=postgresql+psycopg://agent_hub:${DB_PASSWORD}@db.internal:5432/agent_hub
AUTH_JWT_SECRET=${JWT_SECRET}

# Security
CORS_ALLOWED_ORIGINS=https://console.yourdomain.com,https://api.yourdomain.com
ENABLE_HSTS=true
RATE_LIMIT_ENABLED=true
RATE_LIMIT_RPM=100

# Optional services
CELERY_BROKER_URL=redis://redis.internal:6379/0
CELERY_RESULT_BACKEND=redis://redis.internal:6379/1
NEO4J_URI=bolt://neo4j.internal:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=${NEO4J_PASSWORD}
```
