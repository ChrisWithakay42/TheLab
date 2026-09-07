FROM python:3.11-alpine

# Set architecture for etcdctl download (amd64 or arm64)
ARG ETCD_VERSION=v3.5.13
ARG TARGETARCH=amd64

# Install ca-certificates and curl
RUN apk add --no-cache ca-certificates curl bash

# Download and install etcdctl
RUN curl -L https://github.com/etcd-io/etcd/releases/download/${ETCD_VERSION}/etcd-${ETCD_VERSION}-linux-${TARGETARCH}.tar.gz -o /tmp/etcd.tar.gz && \
    tar -xzf /tmp/etcd.tar.gz -C /tmp && \
    mv /tmp/etcd-${ETCD_VERSION}-linux-${TARGETARCH}/etcdctl /usr/local/bin/ && \
    chmod +x /usr/local/bin/etcdctl && \
    rm -rf /tmp/etcd*

# Install Python minio SDK
RUN pip install --no-cache-dir minio

WORKDIR /app
COPY backup.py /app/backup.py
RUN chmod +x /app/backup.py

ENTRYPOINT ["python3", "/app/backup.py"]
