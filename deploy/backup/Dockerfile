# syntax=docker/dockerfile:1
# Образ бэкапов: pg_dump и pg_restore той же версии, что база сайта (postgres:18-alpine с тем
# же digest, что в compose), age для шифрования, rclone для S3, cron из busybox. Секретов в
# образе нет. Адаптация AI Agent Capper deploy/backup/Dockerfile (docs/sources/infra-reuse.md).
# age собирается из исходников известной версии: модуль проверяется по sum.golang.org
FROM golang:1.26-alpine@sha256:30b1e546a9c7fa3b747c2bdba3a0c7bdf3a02ebb4c5b8405d2f948d7e8aac4ec AS age
ARG AGE_VERSION=v1.3.2
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export SSL_CERT_FILE=/run/secrets/proxy_ca; fi; \
    CGO_ENABLED=0 GOBIN=/out go install -trimpath -ldflags="-s -w" \
      "filippo.io/age/cmd/age@${AGE_VERSION}" "filippo.io/age/cmd/age-keygen@${AGE_VERSION}"

# rclone — статический бинарник из официального образа
FROM rclone/rclone:1.75@sha256:2687085f718d3c628f7fdfb77c52a1d344332aed543110bb88088f2c70d43eb5 AS rclone

FROM postgres:18-alpine@sha256:123b17998ccaf47e53b502e8c6a1e79afd8f579c6f3eec83c563da026f957395
COPY --from=age /out/age /out/age-keygen /usr/local/bin/
COPY --from=rclone /usr/local/bin/rclone /usr/local/bin/rclone
COPY common.sh backup.sh restore.sh restore-check.sh healthcheck.sh entrypoint.sh /usr/local/bin/
COPY crontab /etc/crontabs/root
RUN chmod 0755 /usr/local/bin/*.sh \
 && chmod 0600 /etc/crontabs/root \
 && age --version && rclone version > /dev/null
ENV BACKUP_DIR=/backups
WORKDIR /backups
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["crond", "-f", "-d", "8"]
