#!/bin/sh
set -eu
envsubst < /etc/asterisk/pjsip.conf.template > /etc/asterisk/pjsip.conf
envsubst < /etc/asterisk/manager.conf.template > /etc/asterisk/manager.conf
exec asterisk -f -U asterisk -G asterisk
