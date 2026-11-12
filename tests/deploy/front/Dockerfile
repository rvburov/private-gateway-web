# Как у AI Agent Capper: Caddyfile внутри образа и проверка при сборке
FROM caddy:2.11-alpine@sha256:78bd35025c7ba85961dd149ae670315129954e77abe2383ac47c89106b35ade9
COPY Caddyfile /etc/caddy/Caddyfile
RUN CAPPER_DOMAIN=localhost caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile \
 && rm -rf /data/caddy /config/caddy
