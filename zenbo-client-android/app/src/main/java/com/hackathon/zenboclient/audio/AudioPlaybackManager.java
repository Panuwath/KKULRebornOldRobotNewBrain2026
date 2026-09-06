package com.hackathon.zenboclient.audio;

import android.content.Context;
import android.media.AudioAttributes;
import android.media.AudioManager;
import android.media.MediaPlayer;
import android.os.Build;
import android.os.PowerManager;
import android.util.Log;
import com.hackathon.zenboclient.BuildConfig;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.util.ArrayDeque;
import java.util.Queue;

public class AudioPlaybackManager {
    private static final String TAG = "ZenboAudio";
    private MediaPlayer mMediaPlayer;
    private final Context mContext;
    private final Queue<PlaybackRequest> mQueue = new ArrayDeque<>();
    // 50% default keeps Thai speech clear without starting at maximum chassis volume.
    private int mVolumePercent = 50;

    private static final class PlaybackRequest {
        final String source;
        final File tempFile;
        final OnAudioFinishListener listener;

        PlaybackRequest(String source, File tempFile, OnAudioFinishListener listener) {
            this.source = source;
            this.tempFile = tempFile;
            this.listener = listener;
        }
    }

    public interface OnAudioFinishListener {
        void onFinished();
    }

    public AudioPlaybackManager(Context context) {
        this.mContext = context.getApplicationContext();
    }

    public synchronized void playStream(String audioUrl, final OnAudioFinishListener listener) {
        if (audioUrl == null || audioUrl.trim().isEmpty()) return;
        mQueue.offer(new PlaybackRequest(audioUrl, null, listener));
        playNextLocked();
    }

    public synchronized void playBytes(byte[] audioData, final OnAudioFinishListener listener) {
        if (audioData == null || audioData.length == 0) return;
        try {
            File tempFile = File.createTempFile("zenbo_tts_", ".wav", mContext.getCacheDir());
            FileOutputStream fos = new FileOutputStream(tempFile);
            fos.write(audioData);
            fos.close();
            mQueue.offer(new PlaybackRequest(tempFile.getAbsolutePath(), tempFile, listener));
            playNextLocked();
        } catch (Exception e) {
            Log.e(TAG, "Failed to play TTS bytes: " + e.getMessage(), e);
        }
    }

    public synchronized void setVolumePercent(int percent) {
        mVolumePercent = Math.max(0, Math.min(100, percent));
        AudioManager audioManager = (AudioManager) mContext.getSystemService(Context.AUDIO_SERVICE);
        applySpeakerVolume(audioManager);
        if (mMediaPlayer != null) {
            float gain = mVolumePercent / 100f;
            mMediaPlayer.setVolume(gain, gain);
        }
    }

    /** Starts exactly one item. Completion/error from an old player can never stop a newer one. */
    private void playNextLocked() {
        if (mMediaPlayer != null) return;
        final PlaybackRequest request = mQueue.poll();
        if (request == null) return;
        try {
            final MediaPlayer player = new MediaPlayer();
            mMediaPlayer = player;
            configureAttributes(player);
            player.setDataSource(request.source);
            player.setOnPreparedListener(new MediaPlayer.OnPreparedListener() {
                @Override public void onPrepared(MediaPlayer mp) {
                    synchronized (AudioPlaybackManager.this) {
                        if (mMediaPlayer != mp) { releasePlayer(mp, request); return; }
                        mp.start();
                        Log.i(TAG, "TTS playback started: " + request.source);
                    }
                }
            });
            player.setOnCompletionListener(new MediaPlayer.OnCompletionListener() {
                @Override public void onCompletion(MediaPlayer mp) {
                    synchronized (AudioPlaybackManager.this) {
                        if (mMediaPlayer != mp) { releasePlayer(mp, request); return; }
                        mMediaPlayer = null;
                        releasePlayer(mp, request);
                        if (request.listener != null) request.listener.onFinished();
                        playNextLocked();
                    }
                }
            });
            player.setOnErrorListener(new MediaPlayer.OnErrorListener() {
                @Override public boolean onError(MediaPlayer mp, int what, int extra) {
                    synchronized (AudioPlaybackManager.this) {
                        Log.e(TAG, "MediaPlayer error: what=" + what + ", extra=" + extra);
                        if (mMediaPlayer == mp) {
                            mMediaPlayer = null;
                            releasePlayer(mp, request);
                            playNextLocked();
                        } else {
                            releasePlayer(mp, request);
                        }
                    }
                    return true;
                }
            });
            player.prepareAsync();
        } catch (Exception e) {
            Log.e(TAG, "Failed to start audio playback: " + e.getMessage(), e);
            if (request.tempFile != null) request.tempFile.delete();
            mMediaPlayer = null;
            playNextLocked();
        }
    }

    private void configureAttributes(MediaPlayer player) {
        AudioManager audioManager = (AudioManager) mContext.getSystemService(Context.AUDIO_SERVICE);
        applySpeakerVolume(audioManager);
        if (audioManager != null) {
            // Hold focus for the whole utterance; TRANSIENT caused near-silent output
            // on legacy Zenbo builds when joystick commands arrived in parallel.
            audioManager.requestAudioFocus(null, AudioManager.STREAM_MUSIC,
                    AudioManager.AUDIOFOCUS_GAIN);
        }
        if (BuildConfig.LEGACY_MEDIA_STREAM) {
            // Same route used by the proven Zenbo bridge: old firmware may
            // render content with AudioAttributes silently even after a
            // successful MediaPlayer completion callback.
            player.setAudioStreamType(AudioManager.STREAM_MUSIC);
        } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            player.setAudioAttributes(new AudioAttributes.Builder()
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .build());
        } else {
            player.setAudioStreamType(AudioManager.STREAM_MUSIC);
        }
        float gain = mVolumePercent / 100f;
        player.setVolume(gain, gain);
        try {
            player.setWakeMode(mContext, PowerManager.PARTIAL_WAKE_LOCK);
        } catch (Exception ignored) {
        }
    }

    /** Zenbo routes Thai TTS WAV to STREAM_MUSIC; campus units often boot muted. */
    private void applySpeakerVolume(AudioManager audioManager) {
        if (audioManager == null) return;
        try {
            if (!BuildConfig.LEGACY_MEDIA_STREAM) {
                // Modern Android routing guard. Legacy Zenbo follows its own
                // STREAM_MUSIC path above and must not be forced to a call
                // route by speakerphone APIs.
                audioManager.setMode(AudioManager.MODE_NORMAL);
                audioManager.setSpeakerphoneOn(true);
            }
            for (int stream : new int[] {
                    AudioManager.STREAM_MUSIC,
                    AudioManager.STREAM_ALARM,
                    AudioManager.STREAM_NOTIFICATION
            }) {
                int max = audioManager.getStreamMaxVolume(stream);
                if (max <= 0) continue;
                int target = Math.round(max * (mVolumePercent / 100f));
                audioManager.setStreamVolume(stream, Math.max(0, Math.min(max, target)), 0);
            }
        } catch (Exception e) {
            Log.w(TAG, "Unable to boost speaker volume: " + e.getMessage());
        }
    }

    public synchronized void stop() {
        while (!mQueue.isEmpty()) {
            PlaybackRequest pending = mQueue.poll();
            if (pending != null && pending.tempFile != null) pending.tempFile.delete();
        }
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

    private void releasePlayer(MediaPlayer player, PlaybackRequest request) {
        try { player.release(); } catch (Exception ignored) {}
        if (request.tempFile != null) request.tempFile.delete();
    }
}
