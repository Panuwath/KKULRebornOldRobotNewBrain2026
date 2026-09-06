package com.hackathon.zenboclient.mqtt;

import android.content.Context;
import android.util.Log;
import org.eclipse.paho.client.mqttv3.IMqttActionListener;
import org.eclipse.paho.client.mqttv3.IMqttDeliveryToken;
import org.eclipse.paho.client.mqttv3.IMqttToken;
import org.eclipse.paho.client.mqttv3.MqttAsyncClient;
import org.eclipse.paho.client.mqttv3.MqttCallbackExtended;
import org.eclipse.paho.client.mqttv3.MqttConnectOptions;
import org.eclipse.paho.client.mqttv3.MqttException;
import org.eclipse.paho.client.mqttv3.MqttMessage;
import org.eclipse.paho.client.mqttv3.persist.MemoryPersistence;

public class MqttManager {
    private static final String TAG = "ZenboMqtt";
    private MqttAsyncClient mMqttClient;
    private String mBrokerUrl;
    private final String mClientId;
    private final String mTopicPrefix;
    private final String mUsername;
    private final String mToken;

    public interface MessageListener {
        void onMessageReceived(String topic, String message);
        void onConnectionStatusChanged(boolean isConnected, String statusMsg);
    }

    private MessageListener mListener;

    public MqttManager(Context context, String brokerIp, int port, String transport, String topicPrefix,
                       String username, String token, MessageListener listener) {
        this(context, brokerIp, port, transport, "/mqtt", topicPrefix, username, token, listener);
    }

    public MqttManager(Context context, String brokerIp, int port, String transport, String path,
                       String topicPrefix, String username, String token, MessageListener listener) {
        this.mBrokerUrl = brokerUrl(brokerIp, port, transport, path);
        this.mTopicPrefix = topicPrefix;
        this.mClientId = topicPrefix.replace('/', '_') + "_client_" + System.currentTimeMillis();
        this.mUsername = username == null ? "" : username.trim();
        this.mToken = token == null ? "" : token;
        this.mListener = listener;
    }

    private static String brokerUrl(String brokerIp, int port, String transport) {
        return brokerUrl(brokerIp, port, transport, "/mqtt");
    }

    private static String brokerUrl(String brokerIp, int port, String transport, String path) {
        if ("ssl".equalsIgnoreCase(transport)) return "ssl://" + brokerIp + ":" + port;
        if ("ws".equalsIgnoreCase(transport) || "wss".equalsIgnoreCase(transport)) {
            String p = (path == null || path.trim().isEmpty()) ? "/mqtt" : path.trim();
            if (!p.startsWith("/")) p = "/" + p;
            return transport.toLowerCase() + "://" + brokerIp + ":" + port + p;
        }
        return "tcp://" + brokerIp + ":" + port;
    }

    public void updateBroker(String brokerIp, int port, String transport) {
        this.mBrokerUrl = brokerUrl(brokerIp, port, transport);
    }

    public String getBrokerUrl() {
        return mBrokerUrl;
    }

    public void connect() {
        try {
            if (mUsername.isEmpty() || mToken.isEmpty()) {
                Log.e(TAG, "MQTT credentials are not provisioned");
                if (mListener != null) {
                    mListener.onConnectionStatusChanged(false, "MQTT token is not provisioned");
                }
                return;
            }
            if (mMqttClient != null && mMqttClient.isConnected()) {
                mMqttClient.disconnect();
            }

            mMqttClient = new MqttAsyncClient(mBrokerUrl, mClientId, new MemoryPersistence());
            MqttConnectOptions options = new MqttConnectOptions();
            options.setAutomaticReconnect(true);
            options.setCleanSession(true);
            options.setConnectionTimeout(10);
            options.setKeepAliveInterval(20);
            options.setUserName(mUsername);
            options.setPassword(mToken.toCharArray());

            if (mBrokerUrl.startsWith("ssl://") || mBrokerUrl.startsWith("wss://")) {
                options.setSocketFactory(SslUtils.getCompatibleSocketFactory());
            }

            mMqttClient.setCallback(new MqttCallbackExtended() {
                @Override
                public void connectComplete(boolean reconnect, String serverURI) {
                    Log.d(TAG, "Connected to MQTT Broker: " + serverURI);
                    if (mListener != null) {
                        mListener.onConnectionStatusChanged(true, "Connected to " + serverURI);
                    }
                    subscribeToTopics();
                }

                @Override
                public void connectionLost(Throwable cause) {
                    Log.w(TAG, "Connection lost: " + (cause != null ? cause.getMessage() : "Unknown"));
                    if (mListener != null) {
                        mListener.onConnectionStatusChanged(false, "Disconnected");
                    }
                }

                @Override
                public void messageArrived(String topic, MqttMessage message) {
                    try {
                        String payload = new String(message.getPayload());
                        Log.i(TAG, "MQTT Received: " + topic + " -> " + (payload.length() > 200 ? payload.substring(0, 200) + "..." : payload));
                        if (mListener != null) {
                            mListener.onMessageReceived(topic, payload);
                        }
                    } catch (Throwable t) {
                        Log.e(TAG, "Error handling message on " + topic + ": " + t.getMessage(), t);
                    }
                }

                @Override
                public void deliveryComplete(IMqttDeliveryToken token) {}
            });

            mMqttClient.connect(options, null, new IMqttActionListener() {
                @Override
                public void onSuccess(IMqttToken asyncActionToken) {
                    Log.i(TAG, "MQTT Connection Request Sent Successfully");
                    subscribeToTopics();
                }

                @Override
                public void onFailure(IMqttToken asyncActionToken, Throwable exception) {
                    Log.e(TAG, "MQTT Connection Failed: " + (exception != null ? exception.getMessage() : "unknown"));
                    if (mListener != null) {
                        mListener.onConnectionStatusChanged(false, "Failed: " + (exception != null ? exception.getMessage() : "unknown"));
                    }
                }
            });
        } catch (MqttException e) {
            Log.e(TAG, "MqttException: " + e.getMessage(), e);
        }
    }

    private void subscribeToTopics() {
        if (mMqttClient == null || !mMqttClient.isConnected()) {
            Log.w(TAG, "Cannot subscribe yet - client is not connected");
            return;
        }
        try {
            // Support both the core API contract and the direct n8n gateway topics.
            final String[] topics = {
                mTopicPrefix + "/cmd/#",
                mTopicPrefix + "/audio",
                mTopicPrefix + "/movement",
                mTopicPrefix + "/vision",
                mTopicPrefix + "/stop",
                mTopicPrefix + "/ping"
            };
            int[] qos = {1, 1, 1, 1, 1, 1};
            mMqttClient.subscribe(topics, qos, null, new IMqttActionListener() {
                @Override
                public void onSuccess(IMqttToken asyncActionToken) {
                    Log.i(TAG, "Subscribed successfully to " + topics.length + " topics for " + mTopicPrefix);
                }

                @Override
                public void onFailure(IMqttToken asyncActionToken, Throwable exception) {
                    Log.e(TAG, "Subscribe failed in listener: " + (exception != null ? exception.getMessage() : "unknown"));
                }
            });
        } catch (MqttException e) {
            Log.e(TAG, "Subscribe exception: " + e.getMessage(), e);
        }
    }

    public void publish(String topic, String payload) {
        publish(topic, payload, 1, false);
    }

    public void publish(String topic, String payload, int qos, boolean retained) {
        if (mMqttClient == null || !mMqttClient.isConnected()) return;
        try {
            MqttMessage msg = new MqttMessage(payload.getBytes());
            msg.setQos(qos);
            msg.setRetained(retained);
            mMqttClient.publish(topic, msg);
        } catch (MqttException e) {
            Log.e(TAG, "Publish failed: " + e.getMessage());
        }
    }

    public String getClientId() {
        return mClientId;
    }

    public void disconnect() {
        try {
            if (mMqttClient != null) {
                mMqttClient.disconnect();
                mMqttClient.close();
            }
        } catch (Exception ignored) {}
    }
}
