package com.asus.template.taipeiBus;

import android.content.Context;
import android.os.Bundle;
import android.util.Log;
import android.widget.TextView;

import com.asus.robotframework.API.RobotAPI;
import com.asus.robotframework.API.RobotCallback;
import com.asus.robotframework.API.RobotCmdState;
import com.asus.robotframework.API.RobotErrorCode;
import com.asus.robotframework.API.RobotFace;
import com.asus.robotframework.API.RobotUtil;
import com.asus.robotframework.API.SpeakConfig;
import com.asus.template.taipeiBus.R;
import com.robot.asus.robotactivity.RobotActivity;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Iterator;

public class Bus extends RobotActivity{
    public final static String TAG = "TaipeiBus";
    public final static String DOMAIN = "0101C61DBC204827AD186F99CEB572BB";
    public final static String DOMAIN_ID = "16534";
    public final static String PKG_NAME = "com.asus.template.taipeiBus";
    public final static String VERSION = "20210802_1110";

    private static TextView mTextView;
    public static Context mContext = null;

    private static RobotAPI mRobotAPI = null;
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_zenbo_dialog_bus);

        mTextView = (TextView) findViewById(R.id.textview_info);
    }

    @Override
    protected void onResume() {
        super.onResume();

        // close faical
        robotAPI.robot.setExpression(RobotFace.HIDEFACE);

        // jump dialog domain
        robotAPI.robot.jumpToPlan(DOMAIN, "taipeiBus.plan.user.startApp");

        // listen user utterance
        robotAPI.robot.speak("歡迎使用台北公車王", new SpeakConfig().timeout(20));
//        robotAPI.robot.speak("歡迎使用台北公車王", new SpeakConfig().timeout(20));
        
        // show hint
//        mTextView.setText(getResources().getString(R.string.dialog_example)+"\n"+getResources().getString(R.string.usage1));
        mContext = this;

        mRobotAPI = robotAPI;
    }


    @Override
    protected void onPause() {
        super.onPause();

        //stop listen user utterance
        robotAPI.robot.stopSpeakAndListen();
    }


    @Override
    protected void onDestroy() {
        super.onDestroy();
    }

    public static RobotCallback robotCallback = new RobotCallback() {
        @Override
        public void onResult(int cmd, int serial, RobotErrorCode err_code, Bundle result) {
            super.onResult(cmd, serial, err_code, result);
        }

        @Override
        public void onStateChange(int cmd, int serial, RobotErrorCode err_code, RobotCmdState state) {
            super.onStateChange(cmd, serial, err_code, state);
        }

        @Override
        public void initComplete() {
            super.initComplete();
        }
    };


    public static RobotCallback.Listen robotListenCallback = new RobotCallback.Listen() {
        @Override
        public void onFinishRegister() {

        }

        @Override
        public void onVoiceDetect(JSONObject jsonObject) {

        }

        @Override
        public void onSpeakComplete(String s, String s1) {

        }

        @Override
        public void onEventUserUtterance(JSONObject jsonObject) {
            String text;
            text = "onEventUserUtterance: " + jsonObject.toString();
            Log.d(TAG, text);
        }

        @Override
        public void onResult(JSONObject jsonObject) {
            String text;
            text = "onResult: " + jsonObject.toString();
            Log.i(TAG, text);

            try {
                String domain = RobotUtil.queryListenResultJson(jsonObject, "domain");
                Log.i(TAG, "Package = " + domain);

                String intention = RobotUtil.queryListenResultJson(jsonObject, "IntentionId");
                Log.i(TAG, "Intention = " + intention);

                String utterance = RobotUtil.queryListenResultJson(jsonObject, "correctedSentence");
                Log.i(TAG, "Utterance = " + utterance);

                String response = RobotUtil.queryListenResultJson(jsonObject, "output_text");
                Log.i(TAG, "Response = " + response);

                String beliefs = RobotUtil.queryListenResultJson(jsonObject, "beliefs");
                Log.i(TAG, "Beliefs = " + beliefs);

                if(domain.equalsIgnoreCase(PKG_NAME)) {
//                    if( (response != null && !response.isEmpty()) && (utterance != null && !utterance.isEmpty()) ) {
                    if(response != null && !response.isEmpty()) {
                        // 顯示文字
                        String showText = "CSR: " + utterance + "\n" + "TTS: " + response;
                        if(beliefs != null && !beliefs.isEmpty() && !beliefs.equals("{}")){
                            showText += "\n" + "參數: ";
                            String belief = "";
                            ArrayList<String> keys = getBeliefArray(beliefs);
                            for(String key : keys){
                                belief = getBeliefValue(beliefs, key);
                                showText += belief + " ";
                            }
                        }
                        mTextView.setText(showText);
                        // 發話並收音
//                        robotAPI.robot.speakAndListen(response, new SpeakConfig().timeout(20));
                        // 發話
//                        robotAPI.robot.speak(response, new SpeakConfig().timeout(20));
                    }else{
                        mTextView.setText(utterance);
                    }
                    Log.d("HW", "intention="+intention);
                    if ("taipeiBus.plan.user.startApp".equals(intention)) {
                        mTextView.append("\n\n"+mContext.getResources().getString(R.string.may_say)+
                                mContext.getResources().getString(R.string.usage1)+"\n"+
                                mContext.getResources().getString(R.string.or_str)+
                                mContext.getResources().getString(R.string.usage5));
                        mRobotAPI.robot.speakAndListen(response, new SpeakConfig().timeout(20));
                    } else if ("taipeiBus.plan.user.queryBusWhenArriveStation".equals(intention)) { // yes
                        mTextView.append("\n\n"+mContext.getResources().getString(R.string.may_say)+
                                mContext.getResources().getString(R.string.usage4));
                        mRobotAPI.robot.speak(response, new SpeakConfig().timeout(20));
                    } else if ("taipeiBus.plan.user.querySpecificBus".equals(intention)) {
                        mTextView.append("\n\n"+mContext.getResources().getString(R.string.may_say)+
                                mContext.getResources().getString(R.string.usage2));
                        mRobotAPI.robot.speakAndListen(response, new SpeakConfig().timeout(20));
                    } else if ("taipeiBus.plan.user.querySpecificBus.startStationAndTime".equals(intention)) {
                        mTextView.append("\n\n"+mContext.getResources().getString(R.string.may_say)+
                                mContext.getResources().getString(R.string.usage3)+"\n"+
                                mContext.getResources().getString(R.string.or_str)+
                                mContext.getResources().getString(R.string.usage4));
                        mRobotAPI.robot.speak(response, new SpeakConfig().timeout(20));
                    } else {
                        mRobotAPI.robot.speak(response, new SpeakConfig().timeout(20));
                    }
                }

            }catch(Exception e){
                e.printStackTrace();
            }

        }

        @Override
        public void onRetry(JSONObject jsonObject) {

        }
    };

    // handle StateIntentions LanguageType
    private static JSONObject handleLanguageType(String language) {
        JSONObject LanguageType = new JSONObject();

        try{
            LanguageType.put("LanguageType", language);
        }catch(JSONException jex){
            jex.printStackTrace();
        }

        return LanguageType;
    }

    // get Belief array
    private static ArrayList<String> getBeliefArray(String beliefJson){
        ArrayList<String> beliefArray = new ArrayList();

        try{
            JSONObject belief_obj = new JSONObject(beliefJson);
            Iterator<String> keys = belief_obj.keys();
            for (Iterator<String> iterator = keys; iterator.hasNext(); ) {
                String key = iterator.next();
                beliefArray.add(key);
            }
        }catch(JSONException jex){
            jex.printStackTrace();
        }

        return beliefArray;
    }

    // get Belief value
    private static String getBeliefValue(String beliefJson, String beliefName) {
        String beliefValue = "";

        try{
            JSONObject belief_obj = new JSONObject(beliefJson);
            JSONObject beliefName_obj = (JSONObject) belief_obj.get(beliefName);
            beliefValue = beliefName_obj.getString("value");
        }catch(JSONException jex){
            jex.printStackTrace();
        }

        return beliefValue;
    }


    public Bus() { super(robotCallback, robotListenCallback); }

}

