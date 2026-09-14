#!/bin/sh
set -eu
mkdir -p /run/asterisk /var/log/asterisk /var/spool/asterisk /var/lib/asterisk/sounds/custom
chown -R asterisk:asterisk /run/asterisk /var/log/asterisk /var/spool/asterisk /var/lib/asterisk
envsubst < /etc/asterisk/pjsip.conf.template > /etc/asterisk/pjsip.conf
envsubst < /etc/asterisk/manager.conf.template > /etc/asterisk/manager.conf
chown asterisk:asterisk /etc/asterisk/pjsip.conf /etc/asterisk/manager.conf
exec asterisk -f -U asterisk -G asterisk
