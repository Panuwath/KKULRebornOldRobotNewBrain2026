package com.hackathon.zenboclient.audio;

import android.content.Context;
import android.media.AudioAttributes;
import android.media.AudioManager;
import android.media.MediaPlayer;
import android.os.Build;
import android.util.Log;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;

public class AudioPlaybackManager {
    private static final String TAG = "ZenboAudio";
    private MediaPlayer mMediaPlayer;
    private final Context mContext;

    public interface OnAudioFinishListener {
        void onFinished();
    }

    public AudioPlaybackManager(Context context) {
        this.mContext = context;
    }

    public synchronized void playStream(String audioUrl, final OnAudioFinishListener listener) {
        stop();
        try {
            mMediaPlayer = new MediaPlayer();
            configureAttributes();

            mMediaPlayer.setDataSource(audioUrl);
            mMediaPlayer.setOnPreparedListener(new MediaPlayer.OnPreparedListener() {
                @Override
                public void onPrepared(MediaPlayer mp) {
                    Log.d(TAG, "MediaPlayer prepared, starting playback: " + audioUrl);
                    mp.start();
                }
            });

            mMediaPlayer.setOnCompletionListener(new MediaPlayer.OnCompletionListener() {
                @Override
                public void onCompletion(MediaPlayer mp) {
                    Log.d(TAG, "MediaPlayer finished playback");
                    if (listener != null) {
                        listener.onFinished();
                    }
                    stop();
                }
            });

            mMediaPlayer.setOnErrorListener(new MediaPlayer.OnErrorListener() {
                @Override
                public boolean onError(MediaPlayer mp, int what, int extra) {
                    Log.e(TAG, "MediaPlayer error: what=" + what + ", extra=" + extra);
                    stop();
                    return true;
                }
            });

            mMediaPlayer.prepareAsync();
        } catch (Exception e) {
            Log.e(TAG, "Failed to play audio stream: " + e.getMessage(), e);
        }
    }

    public synchronized void playBytes(byte[] audioData, final OnAudioFinishListener listener) {
        stop();
        File tempFile = null;
        try {
            tempFile = File.createTempFile("zenbo_tts_", ".wav", mContext.getCacheDir());
            FileOutputStream fos = new FileOutputStream(tempFile);
            fos.write(audioData);
            fos.close();

            mMediaPlayer = new MediaPlayer();
            configureAttributes();

            mMediaPlayer.setDataSource(tempFile.getAbsolutePath());
            mMediaPlayer.setOnPreparedListener(new MediaPlayer.OnPreparedListener() {
                @Override
                public void onPrepared(MediaPlayer mp) {
                    Log.d(TAG, "MediaPlayer prepared, playing local TTS bytes");
                    mp.start();
                }
            });

            mMediaPlayer.setOnCompletionListener(new MediaPlayer.OnCompletionListener() {
                @Override
                public void onCompletion(MediaPlayer mp) {
                    Log.d(TAG, "MediaPlayer finished TTS playback");
                    if (listener != null) {
                        listener.onFinished();
                    }
                    stop();
                }
            });

            mMediaPlayer.setOnErrorListener(new MediaPlayer.OnErrorListener() {
                @Override
                public boolean onError(MediaPlayer mp, int what, int extra) {
                    Log.e(TAG, "MediaPlayer error playing TTS: what=" + what + ", extra=" + extra);
                    stop();
                    return true;
                }
            });

            mMediaPlayer.prepareAsync();
        } catch (Exception e) {
            Log.e(TAG, "Failed to play TTS bytes: " + e.getMessage(), e);
        }
    }

    private void configureAttributes() {
        AudioManager audioManager = (AudioManager) mContext.getSystemService(Context.AUDIO_SERVICE);
        if (audioManager != null) {
            // Zenbo routes the media stream to its physical speaker.  The previous
            // accessibility usage may be independently muted or routed elsewhere.
            audioManager.requestAudioFocus(null, AudioManager.STREAM_MUSIC,
                    AudioManager.AUDIOFOCUS_GAIN_TRANSIENT);
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            mMediaPlayer.setAudioAttributes(new AudioAttributes.Builder()
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .build());
        } else {
            mMediaPlayer.setAudioStreamType(AudioManager.STREAM_MUSIC);
        }
        mMediaPlayer.setVolume(1.0f, 1.0f);
    }

    public synchronized void stop() {
        if (mMediaPlayer != null) {
            try {
                if (mMediaPlayer.isPlaying()) {
                    mMediaPlayer.stop();
                }
                mMediaPlayer.release();
            } catch (Exception ignored) {}
            mMediaPlayer = null;
        }
        AudioManager audioManager = (AudioManager) mContext.getSystemService(Context.AUDIO_SERVICE);
        if (audioManager != null) {
            audioManager.abandonAudioFocus(null);
        }
    }
}
