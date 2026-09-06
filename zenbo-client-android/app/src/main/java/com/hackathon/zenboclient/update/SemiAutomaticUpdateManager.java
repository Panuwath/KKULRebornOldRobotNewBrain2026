package com.hackathon.zenboclient.update;

import android.app.Activity;
import android.content.ClipData;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import androidx.core.content.FileProvider;
import com.hackathon.zenboclient.BuildConfig;
import org.json.JSONObject;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.security.MessageDigest;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Downloads a release only after an operator asks to check, verifies its
 * server-pinned SHA-256, then hands installation to Android's own installer.
 * It deliberately contains no silent-install path.
 */
public final class SemiAutomaticUpdateManager {
    public interface Listener {
        void onStatus(String text, boolean isError);
        void onInstallReady(File apkFile, String versionName, String notes);
    }

    private final Context mContext;
    private final Handler mMainHandler = new Handler(Looper.getMainLooper());
    private final ExecutorService mExecutor = Executors.newSingleThreadExecutor();

    private static final class ManifestResponse {
        final JSONObject body;
        final String sourceUrl;

        ManifestResponse(JSONObject body, String sourceUrl) {
            this.body = body;
            this.sourceUrl = sourceUrl;
        }
    }

    public SemiAutomaticUpdateManager(Context context) {
        mContext = context.getApplicationContext();
    }

    public void checkAndDownload(final Listener listener) {
        mExecutor.execute(new Runnable() {
            @Override public void run() {
                try {
                    postStatus(listener, "กำลังตรวจสอบอัปเดต...", false);
                    ManifestResponse response = readManifestWithLanFallback();
                    JSONObject manifest = response.body;
                    if (!"ready".equals(manifest.optString("status"))) {
                        postStatus(listener, "ยังไม่มีอัปเดตที่เผยแพร่", false);
                        return;
                    }
                    JSONObject update = manifest.optJSONObject("update");
                    if (update == null) throw new IllegalStateException("manifest ไม่มีข้อมูลอัปเดต");
                    int availableVersion = update.getInt("version_code");
                    if (availableVersion <= currentVersionCode()) {
                        postStatus(listener, "ใช้งานเวอร์ชันล่าสุดแล้ว", false);
                        return;
                    }
                    String apkUrl = update.getString("apk_url");
                    if (response.sourceUrl.equals(BuildConfig.UPDATE_LAN_MANIFEST_URL)) {
                        apkUrl = lanDownloadUrl(apkUrl);
                    }
                    String expectedSha256 = update.getString("sha256").toLowerCase(Locale.US);
                    if (!isPermittedApkUrl(response.sourceUrl, apkUrl)
                            || !expectedSha256.matches("[a-f0-9]{64}")) {
                        throw new IllegalStateException("manifest ไม่ผ่าน integrity policy");
                    }
                    postStatus(listener, "กำลังดาวน์โหลดอัปเดตเพื่อตรวจสอบ...", false);
                    File apkFile = new File(mContext.getCacheDir(), "zenbo-update-" + availableVersion + ".apk");
                    download(apkUrl, apkFile);
                    if (!expectedSha256.equals(sha256(apkFile))) {
                        // Do not leave a tampered or incomplete APK for a later install attempt.
                        apkFile.delete();
                        throw new SecurityException("SHA-256 ของ APK ไม่ตรงกับ manifest");
                    }
                    final String versionName = update.optString("version_name", String.valueOf(availableVersion));
                    final String notes = update.optString("notes", "");
                    mMainHandler.post(new Runnable() {
                        @Override public void run() { listener.onInstallReady(apkFile, versionName, notes); }
                    });
                } catch (Exception error) {
                    postStatus(listener, "ตรวจอัปเดตไม่สำเร็จ: " + error.getMessage(), true);
                }
            }
        });
    }

    public static void requestUserConfirmedInstall(Activity activity, File apkFile) {
        requestUserConfirmedInstall((Context) activity, apkFile);
    }

    public static void requestUserConfirmedInstall(Context context, File apkFile) {
        Uri apkUri = FileProvider.getUriForFile(context,
                context.getPackageName() + ".updateprovider", apkFile);
        Intent intent = new Intent(Intent.ACTION_INSTALL_PACKAGE);
        intent.setData(apkUri);
        intent.setClipData(ClipData.newRawUri("verified APK", apkUri));
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
        if (intent.resolveActivity(context.getPackageManager()) == null) {
            intent = new Intent(Intent.ACTION_VIEW);
            intent.setDataAndType(apkUri, "application/vnd.android.package-archive");
            intent.setClipData(ClipData.newRawUri("verified APK", apkUri));
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
        }
        if (intent.resolveActivity(context.getPackageManager()) == null) {
            throw new IllegalStateException("ไม่พบ Android Package Installer");
        }
        context.startActivity(intent);
    }

    private int currentVersionCode() throws Exception {
        PackageInfo info = mContext.getPackageManager().getPackageInfo(mContext.getPackageName(), 0);
        return Build.VERSION.SDK_INT >= Build.VERSION_CODES.P ? (int) info.getLongVersionCode() : info.versionCode;
    }

    private static ManifestResponse readManifestWithLanFallback() throws Exception {
        String[] candidateUrls = new String[] {
                "https://lib.kku.ac.th/liff-api/api/v1/apk-update",
                BuildConfig.UPDATE_MANIFEST_URL,
                BuildConfig.UPDATE_LAN_MANIFEST_URL
        };
        StringBuilder errors = new StringBuilder();
        for (String urlStr : candidateUrls) {
            if (urlStr == null || urlStr.isEmpty()) continue;
            try {
                boolean isHttps = urlStr.startsWith("https");
                return new ManifestResponse(readJson(urlStr, isHttps), urlStr);
            } catch (Exception e) {
                if (errors.length() > 0) errors.append(" | ");
                errors.append(urlStr).append(": ").append(e.getMessage());
            }
        }
        throw new IllegalStateException("ไม่สามารถดึง update manifest: " + errors.toString());
    }

    private static JSONObject readJson(String value, boolean requireHttps) throws Exception {
        URL url = new URL(value);
        if (requireHttps && !"https".equalsIgnoreCase(url.getProtocol())) {
            throw new IllegalStateException("URL update manifest ต้องเป็น HTTPS");
        }
        if (!requireHttps && !sameOrigin(url, new URL(BuildConfig.UPDATE_LAN_MANIFEST_URL))) {
            throw new IllegalStateException("URL LAN update manifest ไม่ตรงกับค่าที่กำหนด");
        }
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        if (connection instanceof javax.net.ssl.HttpsURLConnection) {
            ((javax.net.ssl.HttpsURLConnection) connection).setSSLSocketFactory(
                    com.hackathon.zenboclient.mqtt.SslUtils.getCompatibleSocketFactory());
        }
        connection.setConnectTimeout(10000);
        connection.setReadTimeout(15000);
        connection.setRequestMethod("GET");
        connection.setInstanceFollowRedirects(false);
        if (connection.getResponseCode() != 200) throw new IllegalStateException("manifest HTTP " + connection.getResponseCode());
        InputStream input = connection.getInputStream();
        StringBuilder body = new StringBuilder();
        byte[] buffer = new byte[4096];
        int read;
        while ((read = input.read(buffer)) != -1) body.append(new String(buffer, 0, read, "UTF-8"));
        input.close();
        connection.disconnect();
        return new JSONObject(body.toString());
    }

    private static boolean isPermittedApkUrl(String manifestUrl, String apkUrl) {
        try {
            URL manifest = new URL(manifestUrl);
            URL apk = new URL(apkUrl);
            if (manifestUrl.equals(BuildConfig.UPDATE_LAN_MANIFEST_URL)) {
                return sameOrigin(apk, new URL(BuildConfig.UPDATE_LAN_DOWNLOAD_ORIGIN));
            }
            if (!"https".equalsIgnoreCase(apk.getProtocol())) return false;
            String apkHost = apk.getHost().toLowerCase(Locale.US);
            String manifestHost = manifest.getHost().toLowerCase(Locale.US);
            return apkHost.equals(manifestHost) || (apkHost.endsWith(".kku.ac.th") && manifestHost.endsWith(".kku.ac.th"));
        } catch (Exception ignored) {
            return false;
        }
    }

    private static String lanDownloadUrl(String publicApkUrl) throws Exception {
        URL publicUrl = new URL(publicApkUrl);
        URL lanOrigin = new URL(BuildConfig.UPDATE_LAN_DOWNLOAD_ORIGIN);
        if (!"https".equalsIgnoreCase(publicUrl.getProtocol())) {
            throw new IllegalStateException("APK URL ใน manifest ต้องเป็น HTTPS");
        }
        String origin = lanOrigin.toString();
        if (origin.endsWith("/")) origin = origin.substring(0, origin.length() - 1);
        return origin + publicUrl.getPath();
    }

    private static boolean sameOrigin(URL left, URL right) {
        return left.getProtocol().equalsIgnoreCase(right.getProtocol())
                && left.getHost().equalsIgnoreCase(right.getHost())
                && effectivePort(left) == effectivePort(right);
    }

    private static int effectivePort(URL url) {
        return url.getPort() >= 0 ? url.getPort() : url.getDefaultPort();
    }

    private static void download(String value, File destination) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(value).openConnection();
        if (connection instanceof javax.net.ssl.HttpsURLConnection) {
            ((javax.net.ssl.HttpsURLConnection) connection).setSSLSocketFactory(
                    com.hackathon.zenboclient.mqtt.SslUtils.getCompatibleSocketFactory());
        }
        connection.setConnectTimeout(15000);
        connection.setReadTimeout(60000);
        connection.setRequestMethod("GET");
        connection.setInstanceFollowRedirects(false);
        if (connection.getResponseCode() != 200) throw new IllegalStateException("APK HTTP " + connection.getResponseCode());
        InputStream input = connection.getInputStream();
        FileOutputStream output = new FileOutputStream(destination, false);
        byte[] buffer = new byte[8192];
        int read;
        while ((read = input.read(buffer)) != -1) output.write(buffer, 0, read);
        output.close();
        input.close();
        connection.disconnect();
    }

    private static String sha256(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        FileInputStream input = new FileInputStream(file);
        byte[] buffer = new byte[8192];
        int read;
        while ((read = input.read(buffer)) != -1) digest.update(buffer, 0, read);
        input.close();
        StringBuilder hex = new StringBuilder();
        for (byte value : digest.digest()) hex.append(String.format(Locale.US, "%02x", value));
        return hex.toString();
    }

    private void postStatus(final Listener listener, final String text, final boolean isError) {
        mMainHandler.post(new Runnable() {
            @Override public void run() { listener.onStatus(text, isError); }
        });
    }
}
