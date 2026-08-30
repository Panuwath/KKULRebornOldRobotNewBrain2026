package com.hackathon.zenboclient;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.media.AudioManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.WebChromeClient;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceError;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Zenbo-safe YouTube playback.  This intentionally avoids ACTION_VIEW: many
 * Zenbo images have no external app registered for YouTube links, or Chrome
 * blocks its audio until a screen tap.
 */
public class YouTubePlayerActivity extends Activity {
    public static final String EXTRA_VIDEO_URL = "youtube_url";
    public static final String ACTION_STATUS = "com.hackathon.zenboclient.YOUTUBE_STATUS";
    public static final String EXTRA_STATE = "state";
    public static final String EXTRA_MESSAGE = "message";
    private static final Pattern VIDEO_ID = Pattern.compile("(?:v=|/embed/|/shorts/|youtu\\.be/)([A-Za-z0-9_-]{6,})");
    private static final long PLAYER_STATE_TIMEOUT_MS = 12000L;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private WebView webView;
    private Button tapToPlay;
    private boolean receivedPlaybackState;

    private final Runnable playerStateTimeout = new Runnable() {
        @Override public void run() {
            if (!receivedPlaybackState) {
                report("PLAYER_TIMEOUT", "no_iframe_state; tap the Zenbo screen to start audio");
                if (tapToPlay != null) tapToPlay.setVisibility(View.VISIBLE);
            }
        }
    };

    private final class PlayerBridge {
        @JavascriptInterface public void post(final String state, final String message) {
            runOnUiThread(() -> {
                if ("PLAYING".equals(state) || "PAUSED".equals(state) || "ENDED".equals(state)
                        || "BUFFERING".equals(state) || "ERROR".equals(state)) {
                    receivedPlaybackState = true;
                    handler.removeCallbacks(playerStateTimeout);
                }
                report(state, message);
            });
        }
    }

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        try {
            String id = resolveVideoId(getIntent() == null ? null : getIntent().getStringExtra(EXTRA_VIDEO_URL));
            if (id.isEmpty()) {
                report("REJECTED", "invalid_youtube_url");
                finish();
                return;
            }
            FrameLayout root = new FrameLayout(this);
            root.setBackgroundColor(Color.BLACK);
            webView = new WebView(this);
            root.addView(webView, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
            tapToPlay = new Button(this);
            tapToPlay.setText("แตะเพื่อเปิดเสียง YouTube");
            tapToPlay.setTextSize(20);
            tapToPlay.setTextColor(Color.WHITE);
            tapToPlay.setBackgroundColor(Color.rgb(180, 30, 90));
            FrameLayout.LayoutParams buttonLayout = new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM);
            buttonLayout.setMargins(24, 24, 24, 36);
            root.addView(tapToPlay, buttonLayout);
            tapToPlay.setOnClickListener(v -> { boostAudio(); forcePlay(); tapToPlay.setVisibility(View.GONE); report("USER_PLAY", "tap_to_unmute"); });
            setContentView(root);
            configureWebView();
            boostAudio();
            webView.loadDataWithBaseURL("https://www.youtube.com", playerHtml(id), "text/html", "UTF-8", null);
            report("PLAYER_CREATED", id);
            handler.postDelayed(this::forcePlay, 1500L);
            handler.postDelayed(this::forcePlay, 3500L);
            handler.postDelayed(playerStateTimeout, PLAYER_STATE_TIMEOUT_MS);
        } catch (Throwable error) {
            report("ERROR", safeMessage(error));
            finish();
        }
    }

    private void configureWebView() {
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setLoadWithOverviewMode(true);
        settings.setUseWideViewPort(true);
        webView.addJavascriptInterface(new PlayerBridge(), "ZenboPlayer");
        webView.setWebChromeClient(new WebChromeClient());
        webView.setWebViewClient(new WebViewClient() {
            @Override public void onPageFinished(WebView view, String url) { report("PLAYER_READY", "iframe_loaded"); }
            @Override public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                report("ERROR", error == null ? "webview_error" : String.valueOf(error.getDescription()));
            }
        });
    }

    private void forcePlay() {
        if (webView == null) return;
        webView.evaluateJavascript("(function(){try{if(window.player){player.unMute();player.setVolume(100);player.playVideo();return 'requested';}return 'not_ready';}catch(e){return 'error:'+e.message;}})()", value -> report("PLAY_REQUESTED", value));
    }

    private void boostAudio() {
        try {
            AudioManager audio = (AudioManager) getSystemService(AUDIO_SERVICE);
            if (audio != null) {
                audio.requestAudioFocus(null, AudioManager.STREAM_MUSIC, AudioManager.AUDIOFOCUS_GAIN);
                int max = audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC);
                audio.setStreamVolume(AudioManager.STREAM_MUSIC, max, 0);
            }
        } catch (Exception ignored) { }
    }

    @Override protected void onDestroy() {
        handler.removeCallbacksAndMessages(null);
        if (webView != null) {
            webView.stopLoading();
            webView.destroy();
            webView = null;
        }
        super.onDestroy();
    }

    private void report(String state, String message) {
        Intent intent = new Intent(ACTION_STATUS).setPackage(getPackageName());
        intent.putExtra(EXTRA_STATE, state == null ? "UNKNOWN" : state);
        intent.putExtra(EXTRA_MESSAGE, message == null ? "" : message);
        sendBroadcast(intent);
    }

    private static String resolveVideoId(String url) {
        if (url == null) return "";
        Matcher matcher = VIDEO_ID.matcher(url);
        return matcher.find() ? matcher.group(1) : "";
    }

    private static String playerHtml(String videoId) {
        String id = videoId.replace("\"", "").replace("'", "");
        return String.format(Locale.US, "<!doctype html><html><body style='margin:0;background:#000'><div id='player'></div><script src='https://www.youtube.com/iframe_api'></script><script>var player;function report(s,m){try{ZenboPlayer.post(s,String(m||''));}catch(e){}}function onYouTubeIframeAPIReady(){player=new YT.Player('player',{width:'100%%',height:'100%%',videoId:'%s',playerVars:{autoplay:1,playsinline:1,controls:1,rel:0},events:{onReady:function(e){report('PLAYER_READY','iframe_ready');e.target.unMute();e.target.setVolume(100);e.target.playVideo();},onStateChange:function(e){var states={-1:'UNSTARTED',0:'ENDED',1:'PLAYING',2:'PAUSED',3:'BUFFERING',5:'CUED'};report(states[e.data]||'STATE_'+e.data,'youtube_iframe');},onError:function(e){report('ERROR','youtube_iframe_'+e.data);}}});}</script></body></html>", id);
    }

    private static String safeMessage(Throwable error) {
        return error.getMessage() == null ? error.getClass().getSimpleName() : error.getMessage();
    }
}
