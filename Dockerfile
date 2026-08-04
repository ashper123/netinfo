FROM python:3.11-slim

WORKDIR /app

# Install basic network utilities for ARP table populating
RUN apt-get update && apt-get install -y --no-install-recommends \
    iproute2 \
    iputils-ping \
    net-tools \
    && rm -rf /var/lib/apt/lists/*

COPY netinfo.py /app/netinfo.py

ENTRYPOINT ["python3", "/app/netinfo.py"]
