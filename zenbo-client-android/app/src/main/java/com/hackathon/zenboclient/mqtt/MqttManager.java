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

    public MqttManager(Context context, String brokerIp, int port, String topicPrefix,
                       String username, String token, MessageListener listener) {
        this.mBrokerUrl = "tcp://" + brokerIp + ":" + port;
        this.mTopicPrefix = topicPrefix;
        this.mClientId = topicPrefix.replace('/', '_') + "_client_" + System.currentTimeMillis();
        this.mUsername = username == null ? "" : username.trim();
        this.mToken = token == null ? "" : token;
        this.mListener = listener;
    }

    public void updateBroker(String brokerIp, int port) {
        this.mBrokerUrl = "tcp://" + brokerIp + ":" + port;
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
                    String payload = new String(message.getPayload());
                    Log.d(TAG, "MQTT Received: " + topic + " -> " + payload);
                    if (mListener != null) {
                        mListener.onMessageReceived(topic, payload);
                    }
                }

                @Override
                public void deliveryComplete(IMqttDeliveryToken token) {}
            });

            mMqttClient.connect(options, null, new IMqttActionListener() {
                @Override
                public void onSuccess(IMqttToken asyncActionToken) {
                    Log.d(TAG, "MQTT Connection Request Sent Successfully");
                }

                @Override
                public void onFailure(IMqttToken asyncActionToken, Throwable exception) {
                    Log.e(TAG, "MQTT Connection Failed: " + exception.getMessage());
                    if (mListener != null) {
                        mListener.onConnectionStatusChanged(false, "Failed: " + exception.getMessage());
                    }
                }
            });
        } catch (MqttException e) {
            Log.e(TAG, "MqttException: " + e.getMessage(), e);
        }
    }

    private void subscribeToTopics() {
        try {
            // Support both the core API contract and the direct n8n gateway topics.
            String[] topics = {mTopicPrefix + "/cmd/#", mTopicPrefix + "/audio", mTopicPrefix + "/movement",
                    mTopicPrefix + "/vision", mTopicPrefix + "/stop", mTopicPrefix + "/ping"};
            int[] qos = {1, 1, 1, 1, 2, 1};
            mMqttClient.subscribe(topics, qos);
            Log.d(TAG, "Subscribed to Zenbo command and gateway topics");
        } catch (MqttException e) {
            Log.e(TAG, "Subscribe failed: " + e.getMessage());
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
