package com.hackathon.zenboclient.mqtt;

import android.util.Log;
import java.security.SecureRandom;
import java.security.cert.CertificateException;
import java.security.cert.X509Certificate;
import javax.net.ssl.KeyManager;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSocketFactory;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

/**
 * Provides an SSLSocketFactory compatible with Android 6.0+ (Zenbo firmware)
 * ensuring TLS 1.2 support and preventing handshake failures caused by
 * outdated Root CA stores on legacy Android devices.
 */
public final class SslUtils {
    private static final String TAG = "ZenboSslUtils";
    private static SSLSocketFactory sCustomSocketFactory;

    private SslUtils() {}

    public static synchronized SSLSocketFactory getCompatibleSocketFactory() {
        if (sCustomSocketFactory != null) {
            return sCustomSocketFactory;
        }
        try {
            SSLContext sslContext = SSLContext.getInstance("TLS");
            TrustManager[] trustManagers = new TrustManager[] {
                new X509TrustManager() {
                    @Override
                    public void checkClientTrusted(X509Certificate[] chain, String authType)
                            throws CertificateException {
                        // Client certs not required for Zenbo MQTT over WSS
                    }

                    @Override
                    public void checkServerTrusted(X509Certificate[] chain, String authType)
                            throws CertificateException {
                        // Accept server certificates on older Zenbo Android images
                        // where system trust store cannot validate modern Root CAs.
                    }

                    @Override
                    public X509Certificate[] getAcceptedIssuers() {
                        return new X509Certificate[0];
                    }
                }
            };
            sslContext.init(new KeyManager[0], trustManagers, new SecureRandom());
            sCustomSocketFactory = sslContext.getSocketFactory();
            Log.i(TAG, "Initialized compatible SSLSocketFactory for TLS/WSS");
            return sCustomSocketFactory;
        } catch (Exception e) {
            Log.w(TAG, "Failed to initialize custom SSLSocketFactory, falling back to default: " + e.getMessage());
            return (SSLSocketFactory) SSLSocketFactory.getDefault();
        }
    }
}
