package com.hackathon.zenboclient;

import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.ServiceConnection;
import android.net.wifi.WifiInfo;
import android.net.wifi.WifiManager;
import android.os.Bundle;
import android.os.IBinder;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.TextView;
import android.widget.Toast;
import androidx.appcompat.app.AppCompatActivity;
import com.hackathon.zenboclient.service.ZenboClientService;
import java.util.Locale;

public class MainActivity extends AppCompatActivity {
    private static final String DEFAULT_BROKER = "10.101.118.149";
    private static final int DEFAULT_PORT = 1883;
    private static final String DEFAULT_TOPIC_PREFIX = "zenbo";

    private TextView mTextStatus;
    private TextView mTextBroker;
    private TextView mTextClientIp;
    private TextView mTextSpeech;
    private Button mBtnConnect;

    private ZenboClientService mService;
    private boolean mIsBound = false;

    private final ServiceConnection mConnection = new ServiceConnection() {
        @Override
        public void onServiceConnected(ComponentName className, IBinder service) {
            ZenboClientService.LocalBinder binder = (ZenboClientService.LocalBinder) service;
            mService = binder.getService();
            mIsBound = true;
            mService.setConnectionStatusListener(new ZenboClientService.ConnectionStatusListener() {
                @Override
                public void onConnectionStatusChanged(final boolean isConnected, final String statusMessage) {
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            String prefix = isConnected ? "เชื่อมต่อ MQTT แล้ว: " : "MQTT ไม่เชื่อมต่อ: ";
                            mTextStatus.setText(prefix + statusMessage);
                        }
                    });
                }
            });
            mService.setSpeechStatusListener(new ZenboClientService.SpeechStatusListener() {
                @Override
                public void onSpeechStatusChanged(final String text, final String state) {
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            if (text == null || text.isEmpty()) return;
                            mTextSpeech.setText(text);
                            mTextStatus.setText(state);
                        }
                    });
                }
            });
            connectMqtt();
        }

        @Override
        public void onServiceDisconnected(ComponentName arg0) {
            mIsBound = false;
            mService = null;
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        enableZenboMode();
        setContentView(R.layout.activity_main);

        mTextStatus = findViewById(R.id.text_status);
        mTextBroker = findViewById(R.id.text_broker);
        mTextClientIp = findViewById(R.id.text_client_ip);
        mTextSpeech = findViewById(R.id.text_speech);
        mBtnConnect = findViewById(R.id.btn_connect);
        mTextClientIp.setText("Client IP: " + getClientIpAddress());
        updateBrokerSummary();

        mBtnConnect.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                connectMqtt();
            }
        });

        try {
            Intent intent = new Intent(this, ZenboClientService.class);
            startService(intent);
            bindService(intent, mConnection, Context.BIND_AUTO_CREATE);
        } catch (Exception e) {
            Toast.makeText(this, "Start service failed: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    private void enableZenboMode() {
        getWindow().getDecorView().setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                        | View.SYSTEM_UI_FLAG_FULLSCREEN
                        | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                        | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) enableZenboMode();
    }

    private String getBrokerHost() {
        return DEFAULT_BROKER;
    }

    private int getBrokerPort() {
        return DEFAULT_PORT;
    }

    private String getTopicPrefix() {
        String ip = getClientIpAddress();
        if (ip.matches("[0-9.]+")) return DEFAULT_TOPIC_PREFIX + "/" + ip.replace('.', '-');
        return DEFAULT_TOPIC_PREFIX;
    }

    private void updateBrokerSummary() {
        mTextBroker.setText("Broker: " + getBrokerHost() + ":" + getBrokerPort()
                + "  |  Client: " + getTopicPrefix());
    }

    private void connectMqtt() {
        if (mIsBound && mService != null) {
            String host = getBrokerHost();
            int port = getBrokerPort();
            mTextClientIp.setText("Client IP: " + getClientIpAddress());
            mTextStatus.setText("กำลังเชื่อมต่อ " + host + ":" + port + "...");
            mService.startMqtt(host, port, getTopicPrefix());
        }
    }

    private String getClientIpAddress() {
        WifiManager wifi = (WifiManager) getApplicationContext().getSystemService(Context.WIFI_SERVICE);
        if (wifi == null) return "unavailable";
        WifiInfo info = wifi.getConnectionInfo();
        if (info == null || info.getIpAddress() == 0) return "not connected";
        int ip = info.getIpAddress();
        return String.format(Locale.US, "%d.%d.%d.%d", ip & 0xff, (ip >> 8) & 0xff,
                (ip >> 16) & 0xff, (ip >> 24) & 0xff);
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        if (mIsBound) {
            if (mService != null) mService.setConnectionStatusListener(null);
            if (mService != null) mService.setSpeechStatusListener(null);
            unbindService(mConnection);
            mIsBound = false;
        }
    }
}
