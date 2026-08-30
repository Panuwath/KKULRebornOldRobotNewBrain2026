#!/bin/sh
set -eu

template=/mosquitto/config/mosquitto.conf
runtime_dir=/mosquitto/runtime
runtime_conf="$runtime_dir/mosquitto.conf"
password_file="$runtime_dir/passwordfile"

mkdir -p "$runtime_dir"
cp "$template" "$runtime_conf"

case "${MQTT_AUTH_REQUIRED:-true}" in
  1|true|TRUE|yes|YES|on|ON)
    : "${MQTT_USERNAME:?MQTT_USERNAME must be configured when MQTT authentication is enabled}"
    : "${MQTT_TOKEN:?MQTT_TOKEN must be configured when MQTT authentication is enabled}"
    umask 077
    mosquitto_passwd -b -c "$password_file" "$MQTT_USERNAME" "$MQTT_TOKEN"
    cat >> "$runtime_conf" <<EOF

allow_anonymous false
password_file $password_file
EOF
    ;;
  0|false|FALSE|no|NO|off|OFF)
    # Explicit local-development escape hatch only. Never use this on a
    # network reachable by the Zenbo robot or the public LIFF gateway.
    printf '\nallow_anonymous true\n' >> "$runtime_conf"
    ;;
  *)
    echo "MQTT_AUTH_REQUIRED must be true or false" >&2
    exit 64
    ;;
esac

exec /usr/sbin/mosquitto -c "$runtime_conf"
