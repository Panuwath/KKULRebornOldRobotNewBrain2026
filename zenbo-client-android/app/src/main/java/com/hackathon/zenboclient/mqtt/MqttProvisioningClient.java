package com.hackathon.zenboclient.mqtt;

import android.util.Log;
import org.json.JSONObject;
import java.io.BufferedReader;
import java.io.OutputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/** Fetches an ephemeral MQTT connection configuration without persisting it. */
public final class MqttProvisioningClient {
    private static final String TAG = "ZenboMqttProvision";

    public interface Callback {
        void onSuccess(Connection connection);
        void onFailure(String safeMessage);
    }

    public static final class Connection {
        public final String host;
        public final int port;
        public final String transport;
        public final String username;
        public final String token;
        public final String topicPrefix;
        public final boolean usedLanFallback;

        Connection(String host, int port, String transport, String username, String token,
                   String topicPrefix, boolean usedLanFallback) {
            this.host = host;
            this.port = port;
            this.transport = transport;
            this.username = username;
            this.token = token;
            this.topicPrefix = topicPrefix;
            this.usedLanFallback = usedLanFallback;
        }

        public static Connection remapped(String host, int port, String transport, String username,
                                          String token, String topicPrefix) {
            return new Connection(host, port, transport, username, token, topicPrefix, true);
        }
    }

    private MqttProvisioningClient() {}

    public static void fetchAsync(final String endpoint, final String bootstrapToken,
                                  final String robotSlug, final Callback callback) {
        fetchAsync(endpoint, bootstrapToken, robotSlug, true, false, callback);
    }

    /** Try HTTPS endpoints in order, then an optional LAN HTTP fallback. */
    public static void fetchWithFallbackChainAsync(final String[] httpsEndpoints,
                                                   final String lanEndpoint,
                                                   final String bootstrapToken,
                                                   final String robotSlug,
                                                   final Callback callback) {
        fetchNext(httpsEndpoints, 0, lanEndpoint, bootstrapToken, robotSlug, callback);
    }

    private static void fetchNext(final String[] httpsEndpoints, final int index,
                                  final String lanEndpoint, final String bootstrapToken,
                                  final String robotSlug, final Callback callback) {
        if (httpsEndpoints != null && index < httpsEndpoints.length) {
            String endpoint = httpsEndpoints[index];
            if (endpoint == null || endpoint.trim().isEmpty()) {
                fetchNext(httpsEndpoints, index + 1, lanEndpoint, bootstrapToken, robotSlug, callback);
                return;
            }
            fetchAsync(endpoint, bootstrapToken, robotSlug, true, false, new Callback() {
                @Override public void onSuccess(Connection connection) {
                    callback.onSuccess(connection);
                }

                @Override public void onFailure(String safeMessage) {
                    Log.i(TAG, "Provisioning failed for " + endpoint + "; trying next endpoint");
                    fetchNext(httpsEndpoints, index + 1, lanEndpoint, bootstrapToken, robotSlug, callback);
                }
            });
            return;
        }
        if (lanEndpoint == null || lanEndpoint.trim().isEmpty()) {
            callback.onFailure("MQTT provisioning request failed");
            return;
        }
        Log.i(TAG, "HTTPS provisioning failed; trying LAN fallback");
        fetchAsync(lanEndpoint, bootstrapToken, robotSlug, false, true, callback);
    }

    private static void fetchAsync(final String endpoint, final String bootstrapToken,
                                   final String robotSlug, final boolean requireHttps,
                                   final boolean usedLanFallback, final Callback callback) {
        new Thread(new Runnable() {
            @Override public void run() {
                if (bootstrapToken == null || bootstrapToken.trim().isEmpty()) {
                    callback.onFailure("MQTT bootstrap token is not provisioned");
                    return;
                }
                HttpURLConnection connection = null;
                try {
                    URL url = new URL(endpoint);
                    String protocol = url.getProtocol();
                    if (requireHttps && !"https".equalsIgnoreCase(protocol)) {
                        callback.onFailure("MQTT provisioning URL must use HTTPS");
                        return;
                    }
                    if (!requireHttps && !"http".equalsIgnoreCase(protocol)
                            && !"https".equalsIgnoreCase(protocol)) {
                        callback.onFailure("MQTT provisioning URL is invalid");
                        return;
                    }
                    connection = (HttpURLConnection) url.openConnection();
                    connection.setRequestMethod("POST");
                    connection.setConnectTimeout(10000);
                    connection.setReadTimeout(10000);
                    connection.setDoOutput(true);
                    connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                    connection.setRequestProperty("Accept", "application/json");
                    connection.setRequestProperty("X-Zenbo-Provisioning-Token", bootstrapToken);
                    byte[] body = new JSONObject().put("robot_slug", robotSlug).toString()
                            .getBytes(StandardCharsets.UTF_8);
                    connection.setFixedLengthStreamingMode(body.length);
                    try (OutputStream output = connection.getOutputStream()) {
                        output.write(body);
                    }
                    int statusCode = connection.getResponseCode();
                    if (statusCode != HttpURLConnection.HTTP_OK) {
                        Log.w(TAG, "MQTT provisioning HTTP " + statusCode + " from " + endpoint);
                        callback.onFailure("MQTT provisioning was not authorized");
                        return;
                    }
                    StringBuilder payload = new StringBuilder();
                    try (BufferedReader reader = new BufferedReader(new InputStreamReader(
                            connection.getInputStream(), StandardCharsets.UTF_8))) {
                        String line;
                        while ((line = reader.readLine()) != null) payload.append(line);
                    }
                    Connection parsed = parseConnection(payload.toString(), usedLanFallback);
                    if (parsed == null) {
                        callback.onFailure("MQTT provisioning response is invalid");
                        return;
                    }
                    callback.onSuccess(parsed);
                } catch (Exception error) {
                    Log.w(TAG, "MQTT provisioning request failed for " + endpoint, error);
                    callback.onFailure("MQTT provisioning request failed");
                } finally {
                    if (connection != null) connection.disconnect();
                }
            }
        }, "zenbo-mqtt-provision").start();
    }

    private static Connection parseConnection(String payload, boolean usedLanFallback) {
        try {
            JSONObject json = new JSONObject(payload);
            String host = json.optString("broker_host").trim();
            int port = json.optInt("broker_port", -1);
            String transport = json.optString("transport").trim().toLowerCase();
            String username = json.optString("username").trim();
            String token = json.optString("token");
            String topicPrefix = json.optString("topic_prefix").trim();
            if (host.isEmpty() || port < 1 || port > 65535 || username.isEmpty()
                    || token.isEmpty() || topicPrefix.isEmpty()
                    || !("tcp".equals(transport) || "ssl".equals(transport)
                    || "ws".equals(transport) || "wss".equals(transport))) {
                return null;
            }
            return new Connection(host, port, transport, username, token, topicPrefix, usedLanFallback);
        } catch (Exception error) {
            Log.w(TAG, "MQTT provisioning response parse failed", error);
            return null;
        }
    }
}
