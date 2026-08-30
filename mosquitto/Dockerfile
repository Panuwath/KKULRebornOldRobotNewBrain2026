FROM eclipse-mosquitto:2.0

USER root
COPY docker-entrypoint-secure.sh /usr/local/bin/docker-entrypoint-secure.sh
RUN chmod 0555 /usr/local/bin/docker-entrypoint-secure.sh \
    && mkdir -p /mosquitto/runtime \
    && chown -R mosquitto:mosquitto /mosquitto/runtime

USER mosquitto
ENTRYPOINT ["/usr/local/bin/docker-entrypoint-secure.sh"]
