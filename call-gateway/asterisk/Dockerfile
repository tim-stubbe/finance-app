FROM alpine:3.22
RUN apk add --no-cache asterisk gettext ca-certificates
COPY pjsip.conf.template /etc/asterisk/pjsip.conf.template
COPY manager.conf.template /etc/asterisk/manager.conf.template
COPY extensions.conf /etc/asterisk/extensions.conf
COPY asterisk.conf modules.conf logger.conf rtp.conf /etc/asterisk/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
