ARG BASE_IMAGE=novel-writer-frontend:collection-fix-20260924
FROM ${BASE_IMAGE}
COPY writter_front/nginx.conf /etc/nginx/conf.d/default.conf
COPY writter_front/dist/ /usr/share/nginx/html/
ARG SOURCE_SHA256
LABEL novel-writer.source-sha256=${SOURCE_SHA256}
