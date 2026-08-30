package com.hackathon.zenboclient.audio;

import android.util.Log;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

public class TtsClient {
    private static final String TAG = "ZenboTts";
    private static final String TTS_URL = "http://10.101.118.149:8025/api/tts/binary";
    private static final String NEURAL_TTS_URL = "http://10.101.118.149:5005/api/v1/tts/neural/binary";

    /** Only use values documented by the on-LAN TTS API: age 10, 15, or 20. */
    private static final class VoiceSettings {
        final String voice;
        final int age;
        final float speed;
        final boolean neural;
        final String rate;
        final String pitch;

        VoiceSettings(String voice, int age, float speed) {
            this(voice, age, speed, false, "-10%", "+0Hz");
        }

        VoiceSettings(String voice, int age, float speed, boolean neural, String rate, String pitch) {
            this.voice = voice;
            this.age = age;
            this.speed = speed;
            this.neural = neural;
            this.rate = rate;
            this.pitch = pitch;
        }
    }

    public interface OnTtsResult {
        void onSuccess(byte[] wavBytes);
        void onError(String message);
    }

    public static void synthesize(String text, String voiceProfile, String requestedVoice,
                                  Integer requestedAge, Float requestedSpeed,
                                  final OnTtsResult callback) {
        final VoiceSettings settings = resolveVoice(voiceProfile, requestedVoice,
                requestedAge, requestedSpeed);
        new Thread(new Runnable() {
            @Override
            public void run() {
                HttpURLConnection conn = null;
                try {
                    URL url = new URL(settings.neural ? NEURAL_TTS_URL : TTS_URL);
                    conn = (HttpURLConnection) url.openConnection();
                    conn.setRequestMethod("POST");
                    conn.setRequestProperty("Content-Type", "application/json");
                    conn.setConnectTimeout(15000);
                    conn.setReadTimeout(30000);
                    conn.setDoOutput(true);

                    JSONObject body = new JSONObject();
                    body.put("text", text);
                    body.put("voice", settings.voice);
                    if (settings.neural) {
                        body.put("rate", settings.rate);
                        body.put("pitch", settings.pitch);
                    } else {
                        body.put("age", settings.age);
                        body.put("speed", settings.speed);
                        body.put("natural_mode", true);
                    }

                    byte[] payload = body.toString().getBytes("UTF-8");
                    conn.setRequestProperty("Content-Length", String.valueOf(payload.length));
                    conn.getOutputStream().write(payload);
                    conn.getOutputStream().close();

                    int code = conn.getResponseCode();
                    if (code != 200) {
                        callback.onError("TTS HTTP " + code);
                        return;
                    }

                    InputStream in = conn.getInputStream();
                    ByteArrayOutputStream out = new ByteArrayOutputStream();
                    byte[] buffer = new byte[8192];
                    int n;
                    while ((n = in.read(buffer)) != -1) {
                        out.write(buffer, 0, n);
                    }
                    in.close();

                    byte[] wavBytes = out.toByteArray();
                    Log.d(TAG, "TTS synthesized " + wavBytes.length + " bytes for: " + text);
                    callback.onSuccess(wavBytes);
                } catch (Exception e) {
                    Log.e(TAG, "TTS error: " + e.getMessage(), e);
                    callback.onError(e.getMessage());
                } finally {
                    if (conn != null) {
                        conn.disconnect();
                    }
                }
            }
        }).start();
    }

    private static VoiceSettings resolveVoice(String voiceProfile, String requestedVoice,
                                              Integer requestedAge, Float requestedSpeed) {
        if ("female_child".equals(voiceProfile)) return neuralFemale("-8%", "+10Hz");
        if ("female_young".equals(voiceProfile)) return neuralFemale("-6%", "+4Hz");
        if ("female_adult".equals(voiceProfile)) return neuralFemale("-3%", "+0Hz");
        if ("male_child".equals(voiceProfile)) return neuralMale("boy_cute", "-8%", "+7Hz");
        if ("male_young".equals(voiceProfile)) return neuralMale("male_natural", "-4%", "+2Hz");
        if ("male_adult".equals(voiceProfile)) return neuralMale("male_natural", "-2%", "+0Hz");

        if ("th_f_1".equals(requestedVoice) || "female".equals(requestedVoice)
                || "female_sweet".equals(requestedVoice)) {
            return neuralFemale("-6%", "+4Hz");
        }
        if ("th_m_1".equals(requestedVoice) || "th_m_2".equals(requestedVoice)
                || "male".equals(requestedVoice) || "male_natural".equals(requestedVoice)
                || "boy_cute".equals(requestedVoice)) {
            return neuralMale("male_natural", "-2%", "+0Hz");
        }
        String voice = requestedVoice == null || requestedVoice.isEmpty() ? "th_m_1" : requestedVoice;
        int age = nearestSupportedAge(requestedAge == null ? 20 : requestedAge);
        float speed = requestedSpeed == null ? 0.96f : Math.max(0.41f, Math.min(1.99f, requestedSpeed));
        return new VoiceSettings(voice, age, speed);
    }

    private static int nearestSupportedAge(int age) {
        if (age <= 12) return 10;
        if (age <= 17) return 15;
        return 20;
    }

    private static VoiceSettings neuralFemale(String rate, String pitch) {
        // The remote neural gateway can time out on the robot network.  The
        // on-LAN binary service is verified to return WAV reliably, so voice
        // profiles deliberately resolve to its supported female voice.
        return new VoiceSettings("th_f_1", 20, 0.96f, false, rate, pitch);
    }

    private static VoiceSettings neuralMale(String voice, String rate, String pitch) {
        // See neuralFemale: keep the profile contract but use the reliable
        // binary endpoint until the neural gateway has a health guarantee.
        return new VoiceSettings("th_m_1", 20, 0.96f, false, rate, pitch);
    }
}
