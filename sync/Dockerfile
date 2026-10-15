# syntax=docker/dockerfile:1
FROM golang:1.26.9-alpine3.23 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export SSL_CERT_FILE=/run/secrets/proxy_ca; fi; go mod download
COPY . .
ARG TARGETARCH
ARG VERSION=development
RUN CGO_ENABLED=0 GOOS=linux GOARCH=${TARGETARCH} GOPROXY=off go build -trimpath -ldflags="-s -w -X main.version=${VERSION}" -o /haunt-sync ./cmd/haunt-sync
FROM alpine:3.23.6
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=build /haunt-sync /usr/local/bin/haunt-sync
USER 65532:65532
ENV HAUNT_SYNC_LISTEN_ADDR=127.0.0.1:8090
ENTRYPOINT ["/usr/local/bin/haunt-sync"]
