FROM python:3.12-slim

# Install networking tools: ping, curl, dig, netcat, traceroute, nslookup
RUN apt-get update && apt-get install -y --no-install-recommends \
        iputils-ping \
        curl \
        dnsutils \
        netcat-openbsd \
        traceroute \
        net-tools \
        iproute2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

# Non-root user for security
RUN useradd -r -u 1001 appuser \
    && chown -R appuser:appuser /app

# Allow ping without root (requires cap_net_raw, granted via K8s securityContext)
RUN setcap cap_net_raw+ep /bin/ping

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
