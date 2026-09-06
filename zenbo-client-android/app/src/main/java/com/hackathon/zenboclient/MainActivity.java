package com.hackathon.zenboclient;

import android.Manifest;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.ServiceConnection;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.net.wifi.WifiInfo;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.Bundle;
import android.os.IBinder;
import android.provider.Settings;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.TextView;
import android.widget.Toast;
import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import com.hackathon.zenboclient.service.ZenboClientService;
import com.hackathon.zenboclient.ui.ScreenTickerOverlay;
import com.hackathon.zenboclient.update.SemiAutomaticUpdateManager;
import java.io.File;
import java.util.Locale;

public class MainActivity extends AppCompatActivity {
    private TextView mTextStatus;
    private TextView mTextBroker;
    private TextView mTextClientIp;
    private TextView mTextSpeech;
    private TextView mTextSafetyTitle;
    private TextView mTextSafetyDetail;
    private TextView mTextUpdate;
    private TextView mTextTicker;
    private TextView mTextFaceEmoji;
    private Button mBtnConnect;
    private Button mBtnSwitchBrokerMode;
    private Button mBtnRobotFaceMode;
    private Button mBtnUpdate;
    private Button mBtnInstallationComplete;
    private SemiAutomaticUpdateManager mUpdateManager;

    private ZenboClientService mService;
    private boolean mIsBound = false;
    private boolean mInstallationAnnouncementRequested = false;

    private final ServiceConnection mConnection = new ServiceConnection() {
        @Override
        public void onServiceConnected(ComponentName className, IBinder service) {
            ZenboClientService.LocalBinder binder = (ZenboClientService.LocalBinder) service;
            mService = binder.getService();
            mIsBound = true;
            updateBrokerSummary();
            mService.setConnectionStatusListener(new ZenboClientService.ConnectionStatusListener() {
                @Override
                public void onConnectionStatusChanged(final boolean isConnected, final String statusMessage) {
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            String prefix = isConnected ? "เชื่อมต่อ MQTT แล้ว: " : "MQTT ไม่เชื่อมต่อ: ";
                            mTextStatus.setText(prefix + statusMessage);
                            updateBrokerSummary();
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
                            updateBottomTicker(text);
                            mTextStatus.setText(state);
                        }
                    });
                }
            });
            mService.setSafetyStatusListener(new ZenboClientService.SafetyStatusListener() {
                @Override
                public void onSafetyStatusChanged(final String title, final String detail, final boolean danger) {
                    runOnUiThread(new Runnable() {
                        @Override public void run() {
                            mTextSafetyTitle.setText(title);
                            mTextSafetyDetail.setText(detail);
                            int color = getColor(danger ? android.R.color.holo_red_light : android.R.color.holo_green_light);
                            mTextSafetyTitle.setTextColor(color);
                        }
                    });
                }
            });
            mService.setFaceStatusListener(new ZenboClientService.FaceStatusListener() {
                @Override
                public void onFaceStatusChanged(final String faceName) {
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            if (mTextFaceEmoji != null && faceName != null) {
                                mTextFaceEmoji.setText(getEmojiForFace(faceName));
                            }
                        }
                    });
                }
            });
            connectMqtt();
            announceInstallationIfNeeded();
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
        mTextSafetyTitle = findViewById(R.id.text_safety_title);
        mTextSafetyDetail = findViewById(R.id.text_safety_detail);
        mTextUpdate = findViewById(R.id.text_update);
        mTextTicker = findViewById(R.id.text_bottom_ticker);
        // A selected marquee restarts whenever the service receives a new
        // command, so long Thai sentences remain readable on Zenbo's screen.
        mTextSpeech.setSelected(true);
        mTextTicker.setSelected(true);
        mTextTicker.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && !Settings.canDrawOverlays(MainActivity.this)) {
                    try {
                        Intent intent = new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                                Uri.parse("package:" + getPackageName()));
                        startActivity(intent);
                        Toast.makeText(MainActivity.this, "โปรดเปิด 'อนุญาตให้แสดงทับแอปอื่น'", Toast.LENGTH_SHORT).show();
                    } catch (Exception ignored) {}
                } else {
                    Toast.makeText(MainActivity.this, "ป้ายข้อความวิ่ง (Ticker) พร้อมทำงานแล้วครับ", Toast.LENGTH_SHORT).show();
                }
            }
        });
        mBtnConnect = findViewById(R.id.btn_connect);
        mBtnSwitchBrokerMode = findViewById(R.id.btn_switch_broker_mode);
        mBtnRobotFaceMode = findViewById(R.id.btn_robot_face_mode);
        mBtnUpdate = findViewById(R.id.btn_update);
        mBtnInstallationComplete = findViewById(R.id.btn_installation_complete);
        mTextFaceEmoji = findViewById(R.id.text_face_emoji);
        if (mTextFaceEmoji != null) {
            mTextFaceEmoji.setOnClickListener(new View.OnClickListener() {
                @Override public void onClick(View v) {
                    switchToRobotFaceMode();
                }
            });
        }
        if (mBtnRobotFaceMode != null) {
            mBtnRobotFaceMode.setOnClickListener(new View.OnClickListener() {
                @Override public void onClick(View v) {
                    switchToRobotFaceMode();
                }
            });
        }
        if (BuildConfig.SELF_UPDATE_ENABLED) {
            mUpdateManager = new SemiAutomaticUpdateManager(this);
        } else {
            // The Drive-distribution artifact deliberately never asks Android
            // to install another package from inside this app.
            mBtnUpdate.setVisibility(View.GONE);
            mTextUpdate.setText("รุ่นแจกผ่าน Drive: ให้ผู้ดูแลติดตั้ง APK รุ่นถัดไปโดยตรง");
        }
        mTextClientIp.setText("Client IP: " + getClientIpAddress());
        updateBrokerSummary();

        mBtnConnect.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                connectMqtt();
            }
        });
        mBtnSwitchBrokerMode.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                if (mIsBound && mService != null) {
                    mService.toggleBrokerMode();
                    updateBrokerSummary();
                }
            }
        });
        mBtnUpdate.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) { checkForUpdate(); }
        });
        configureInstallationCompleteButton();
        requestRuntimePermissions();

        try {
            Intent intent = new Intent(this, ZenboClientService.class);
            startService(intent);
            bindService(intent, mConnection, Context.BIND_AUTO_CREATE);
        } catch (Exception e) {
            Toast.makeText(this, "Start service failed: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    private static final int CAMERA_PERMISSION_REQUEST_CODE = 1001;

    private void requestRuntimePermissions() {
        // WebRTC teleop and two-way audio need CAMERA and RECORD_AUDIO on
        // Android 6+. Request once at launch so the operator does not need to
        // open Android settings during an urgent camera session.
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return;
        String[] permissions = { Manifest.permission.CAMERA, Manifest.permission.RECORD_AUDIO };
        java.util.List<String> needed = new java.util.ArrayList<>();
        for (String permission : permissions) {
            if (ContextCompat.checkSelfPermission(this, permission) != PackageManager.PERMISSION_GRANTED) {
                needed.add(permission);
            }
        }
        if (!needed.isEmpty()) {
            ActivityCompat.requestPermissions(this, needed.toArray(new String[0]), CAMERA_PERMISSION_REQUEST_CODE);
        }

        if (!Settings.canDrawOverlays(this)) {
            try {
                Intent intent = new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                        Uri.parse("package:" + getPackageName()));
                startActivity(intent);
                Toast.makeText(this, "โปรดเปิดสิทธิ์ 'แสดงทับแอปอื่น' เพื่อเปิดใช้งานป้ายข้อความวิ่ง (Ticker)", Toast.LENGTH_LONG).show();
            } catch (Exception ignored) {}
        }
    }

    private void configureInstallationCompleteButton() {
        int confirmedVersion = getSharedPreferences("zenbo_update_notice", MODE_PRIVATE)
                .getInt("confirmed_version_code", -1);
        if (confirmedVersion == BuildConfig.VERSION_CODE) {
            mBtnInstallationComplete.setVisibility(View.GONE);
            return;
        }
        mBtnInstallationComplete.setVisibility(View.VISIBLE);
        mBtnInstallationComplete.setText("กำลังเตรียมประกาศการอัปเดต...");
        mBtnInstallationComplete.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) {
                announceInstallationIfNeeded();
            }
        });
    }

    /** First foreground launch after a new version is installed announces it once. */
    private void announceInstallationIfNeeded() {
        int confirmedVersion = getSharedPreferences("zenbo_update_notice", MODE_PRIVATE)
                .getInt("confirmed_version_code", -1);
        if (confirmedVersion == BuildConfig.VERSION_CODE) {
            mBtnInstallationComplete.setVisibility(View.GONE);
            return;
        }
        if (!mIsBound || mService == null) {
            mTextStatus.setText("กำลังรอ Zenbo Client Service พร้อม...");
            return;
        }
        if (mInstallationAnnouncementRequested) return;
        mInstallationAnnouncementRequested = true;
        mBtnInstallationComplete.setVisibility(View.VISIBLE);
        mBtnInstallationComplete.setEnabled(false);
        mTextStatus.setText("กำลังให้ Zenbo แจ้งผลการอัปเดต...");
        updateBottomTicker("ติดตั้งสำเร็จครับ • Zenbo พร้อมให้บริการแล้วครับ");
        mService.announceUpdateCompleted(new ZenboClientService.UpdateAnnouncementListener() {
                    @Override public void onCompleted() {
                        runOnUiThread(new Runnable() {
                            @Override public void run() {
                                getSharedPreferences("zenbo_update_notice", MODE_PRIVATE).edit()
                                        .putInt("confirmed_version_code", BuildConfig.VERSION_CODE).apply();
                                mBtnInstallationComplete.setVisibility(View.GONE);
                                mTextUpdate.setText("Zenbo แจ้งอัปเดตเรียบร้อยแล้ว");
                                updateBottomTicker("ติดตั้งสำเร็จครับ • Booky พร้อมรับคำสั่งแล้วครับ");
                            }
                        });
                    }

                    @Override public void onFailed(final String message) {
                        runOnUiThread(new Runnable() {
                            @Override public void run() {
                                mInstallationAnnouncementRequested = false;
                                mBtnInstallationComplete.setEnabled(true);
                                mBtnInstallationComplete.setText("ลองประกาศการอัปเดตอีกครั้ง");
                                mTextUpdate.setText("Zenbo พูดไม่สำเร็จ: " + message + " — กดอีกครั้งได้");
                            }
                        });
                    }
        });
    }

    private void updateBottomTicker(String text) {
        if (text == null || text.trim().isEmpty() || mTextTicker == null) return;
        mTextTicker.setText("  " + text.trim() + "     •     ");
        mTextTicker.setSelected(false);
        mTextTicker.setSelected(true);
    }

    private void checkForUpdate() {
        if (!BuildConfig.SELF_UPDATE_ENABLED || mUpdateManager == null) {
            mTextUpdate.setText("รุ่นนี้รับอัปเดตจากผู้ดูแลโดยตรง");
            return;
        }
        mBtnUpdate.setEnabled(false);
        mUpdateManager.checkAndDownload(new SemiAutomaticUpdateManager.Listener() {
            @Override public void onStatus(String text, boolean isError) {
                mTextUpdate.setText(text);
                mTextUpdate.setTextColor(getColor(isError ? android.R.color.holo_red_light : android.R.color.holo_blue_light));
                mBtnUpdate.setEnabled(true);
            }

            @Override public void onInstallReady(final File apkFile, final String versionName, final String notes) {
                mBtnUpdate.setEnabled(true);
                mTextUpdate.setText("ดาวน์โหลดและตรวจ SHA-256 ผ่านแล้ว — รอการยืนยันติดตั้ง");
                new AlertDialog.Builder(MainActivity.this)
                        .setTitle("อัปเดต Zenbo Client " + versionName)
                        .setMessage((notes == null || notes.isEmpty() ? "ไฟล์ผ่านการตรวจสอบแล้ว" : notes)
                                + "\n\nAndroid จะเปิดหน้าติดตั้ง ให้ผู้ดูแลกดยืนยันอีกครั้ง")
                        .setNegativeButton("ยังไม่ติดตั้ง", null)
                        .setPositiveButton("เปิดตัวติดตั้ง", (dialog, which) -> {
                            try {
                                SemiAutomaticUpdateManager.requestUserConfirmedInstall(MainActivity.this, apkFile);
                            } catch (Exception error) {
                                mTextUpdate.setText("เปิดตัวติดตั้งไม่สำเร็จ: " + error.getMessage());
                                mTextUpdate.setTextColor(getColor(android.R.color.holo_red_light));
                            }
                        })
                        .show();
            }
        });
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

    private void updateBrokerSummary() {
        String brokerSummary;
        String modeLabel;
        if (mIsBound && mService != null) {
            brokerSummary = mService.getActiveBrokerSummary();
            modeLabel = "โหมด: " + mService.getBrokerModeName();
        } else {
            brokerSummary = "โหมด: AUTO\nเส้นทาง: LAN :1884 (" + BuildConfig.DIRECT_MQTT_HOST + ")";
            modeLabel = "โหมด: AUTO";
        }
        if (mBtnSwitchBrokerMode != null) {
            mBtnSwitchBrokerMode.setText(modeLabel);
        }
        mTextBroker.setText("Version: " + BuildConfig.VERSION_NAME
                + " (" + BuildConfig.VERSION_CODE + ")"
                + "\n" + brokerSummary
                + "  |  Robot: " + BuildConfig.ROBOT_SLUG);
    }

    private void connectMqtt() {
        if (mIsBound && mService != null) {
            mTextClientIp.setText("Client IP: " + getClientIpAddress());
            mTextStatus.setText("กำลังขอการเชื่อมต่อ MQTT จาก Core...");
            mService.reconnectMqtt();
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

    private void switchToRobotFaceMode() {
        Toast.makeText(this, "เข้าสู่โหมดใบหน้าหุ่นยนต์แล้วครับ (แตะหน้าจอเพื่อกลับมา)", Toast.LENGTH_SHORT).show();
        moveTaskToBack(true);
    }

    private String getEmojiForFace(String faceName) {
        if (faceName == null) return "🤖";
        switch (faceName.trim().toUpperCase()) {
            case "HAPPY": return "😄";
            case "PLEASED": return "😊";
            case "PROUD": return "😎";
            case "CONFIDENT": return "🤩";
            case "ACTIVE": return "✨";
            case "SINGING": return "🎤";
            case "INTEREST":
            case "INTERESTED": return "🧐";
            case "EXPECT":
            case "EXPECTING": return "🥺";
            case "DOUBT":
            case "DOUBTING": return "🤔";
            case "QUESTIONING": return "❓";
            case "SHY": return "😳";
            case "INNOCENT": return "😇";
            case "SERIOUS": return "😐";
            case "SHOCK":
            case "SHOCKED": return "😲";
            case "WORRIED": return "😟";
            case "HELPLESS": return "🤷";
            case "TIRED": return "😴";
            case "LAZY": return "🥱";
            case "IMPATIENT": return "⏳";
            case "PRETENDING": return "😜";
            default: return "🤖";
        }
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        if (mIsBound) {
            if (mService != null) mService.setConnectionStatusListener(null);
            if (mService != null) mService.setSpeechStatusListener(null);
            if (mService != null) mService.setSafetyStatusListener(null);
            if (mService != null) mService.setFaceStatusListener(null);
            unbindService(mConnection);
            mIsBound = false;
        }
    }
}
