FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends asterisk gettext-base ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY pjsip.conf.template /etc/asterisk/pjsip.conf.template
COPY manager.conf.template /etc/asterisk/manager.conf.template
COPY extensions.conf /etc/asterisk/extensions.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
