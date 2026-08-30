package com.asus.ds.tangpoetry;

import android.content.Intent;
import android.content.res.AssetManager;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.os.Bundle;
import android.util.Log;
import android.view.View;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.TextView;

import com.asus.ctc.tool.DSAPI_Result;
import com.asus.robotframework.API.DialogSystem;
import com.asus.robotframework.API.RobotAPI;
import com.asus.robotframework.API.RobotCallback;
import com.asus.robotframework.API.RobotCmdState;
import com.asus.robotframework.API.RobotErrorCode;
import com.asus.robotframework.API.SpeakConfig;
import com.robot.asus.robotactivity.RobotActivity;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.Random;

public class emotionChatBotPortal extends RobotActivity {
    public final static String TAG = "Tang Poetry";
    public final static String DOMAIN_UUID = "346241F0B8984AD09CD921ED8E52B9FA";
    public final static String DOMAIN_ID = "16486";
    public static SQLiteDatabase db = null;
    public static String DB_PATH = "/data/data/com.asus.ds.tangpoetry/databases/";
    private static TextView mTextView;
    private ImageView imageView = null;
    private static RobotAPI mRobotAPI = null;

    // RobotCallback 與 RobotCallback.Listen 是從 Sample code 複製過來的，其中 RobotCallback.Listen 可以收到自己 domain 的 callback
    public static RobotCallback robotCallback = new RobotCallback() {
        @Override
        public void onResult(int cmd, int serial, RobotErrorCode err_code, Bundle result) {
            super.onResult(cmd, serial, err_code, result);
            String text;
            text = "[RobotCallback]onResult: " + result.toString();
            Log.d(TAG, text);
        }

        @Override
        public void onStateChange(int cmd, int serial, RobotErrorCode err_code, RobotCmdState state) {
            super.onStateChange(cmd, serial, err_code, state);
        }
    };
    public static String content="";
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
            text = "[RobotCallback.Listen]onEventUserUtterance: " + jsonObject.toString();
            Log.d(TAG, text);
        }

        @Override
        // 語音指令時，均會收到屬於自己domain的callback，就算不同activity也會收到~
        public void onResult(JSONObject jsonObject) {
            String text;
            text = "[RobotCallback.Listen]onResult: " + jsonObject.toString();
            Log.d(TAG, text);

            String Domain = QuerySLUJson(jsonObject, "Domain");
            String plan = QuerySLUJson(jsonObject, "IntentionId");
            ArrayList<String> sentenceList = new ArrayList<String>();
            if(Domain!= null&&Domain.equals(DOMAIN_ID)) {
                Log.d("[RobotCallback.Listen]",plan);
                String title="";
                String poet="";
                String type="";
                String utterance="";
                poetStructure psResult = new poetStructure();
                // 設定語速: set up the speed of speaking
                SpeakConfig poetSpeed = new SpeakConfig();
                poetSpeed.speed(80);
                // 設定語速: set up the speed of speaking
                SpeakConfig normalSpeed = new SpeakConfig();
                normalSpeed.speed(100);

                try {
                    switch (plan) {
                        case "plan_listen_any"://fuzzy match
                            utterance = QuerySLUJson(jsonObject, "any");
                            Log.d(TAG, utterance);
                            if (!utterance.equals("") && !utterance.isEmpty()) {
                                psResult = queryDB(db, null, null, null, "plan_listen_any", utterance);
                                if(!psResult.getContent().isEmpty()&&psResult.getAuthor()!=""&&psResult.getTitle()!="") {
                                    mRobotAPI.robot.stopSpeak();
                                    content = psResult.getContent();
                                    mRobotAPI.robot.speakAndListen("我知道這段是 " + psResult.getAuthor() + " 的 " + psResult.getTitle() +
                                            " , 需要朗誦出來嗎", normalSpeed);
                                }
                            }
                            break;
                        case "plan_listen_any_one"://隨便一首
                            // 初始化變數
                            mRobotAPI.robot.stopSpeak();

                            psResult = queryDB(db, null, null, null, "plan_listen_any_one", null);
                            if(!psResult.getContent().isEmpty()&&psResult.getAuthor()!=""&&psResult.getTitle()!="") {
                                mRobotAPI.robot.speak(psResult.getAuthor(), normalSpeed);
                                mRobotAPI.robot.speak(psResult.getTitle(), normalSpeed);
                                content = psResult.getContent();
                                speakRules(psResult.getType(),content);
                            }
                            break;
                        case "plan_listen_poet"://找李白的詩
                            // 初始化變數
                            mRobotAPI.robot.stopSpeak();

                            poet = QuerySLUJson(jsonObject, "poet");//poet, ex: 李白
                            Log.d(TAG, "plan: plan_listen_poet " + poet);
                            psResult = queryDB(db, poet, null, null, "plan_listen_poet", null);
                            if(!psResult.getContent().isEmpty()&&psResult.getAuthor()!=""&&psResult.getTitle()!="") {
                                mRobotAPI.robot.speak(psResult.getAuthor(), normalSpeed);
                                mRobotAPI.robot.speak(psResult.getTitle(), normalSpeed);
                                content = psResult.getContent();
                                speakRules(psResult.getType(),content);
                            }
                            break;
                        case "plan_listen_title"://來首塞上曲
                            // 初始化變數
                            mRobotAPI.robot.stopSpeak();

                            title = QuerySLUJson(jsonObject, "title");//相思
                            Log.d(TAG, "plan: plan_listen_title " + title);
                            psResult = queryDB(db, null, null, title, "plan_listen_title", null);
                            if(!psResult.getContent().isEmpty()&&psResult.getAuthor()!=""&&psResult.getTitle()!="") {
                                mRobotAPI.robot.speak(psResult.getAuthor(), normalSpeed);
                                mRobotAPI.robot.speak(psResult.getTitle(), normalSpeed);
                                content = psResult.getContent();
                                speakRules(psResult.getType(),content);
                            }
                            break;
                        case "plan_listen_combo"://李白的長干行之一
                            // 初始化變數
                            mRobotAPI.robot.stopSpeak();

                            title = QuerySLUJson(jsonObject, "title");//poet, ex: 李白
                            poet = QuerySLUJson(jsonObject, "poet");//poet, ex: 李白
                            Log.d(TAG, "plan: plan_listen_combo " + title);
                            psResult = queryDB(db, poet, null, title, "plan_listen_combo", null);
                            if(!psResult.getContent().isEmpty()&&psResult.getAuthor()!=""&&psResult.getTitle()!="") {
                                mRobotAPI.robot.speak(psResult.getAuthor(), normalSpeed);
                                mRobotAPI.robot.speak(psResult.getTitle(), normalSpeed);
                                Log.d(TAG,"[plan: plan_listen_combo]psResult.getType()" + psResult.getType());
                                content = psResult.getContent();
                                speakRules(psResult.getType(),content);
                            }
                            break;
                        case "plan_listen_type"://來一個五言古詩
                            // 初始化變數
                            mRobotAPI.robot.stopSpeak();

                            type = QuerySLUJson(jsonObject, "type");//type, ex: 五言古詩
                            Log.d(TAG, "plan: plan_listen_type " + type);
                            psResult = queryDB(db, null, type, null, "plan_listen_type", null);
                            if(!psResult.getContent().isEmpty()&&psResult.getAuthor()!=""&&psResult.getTitle()!="") {
                                mRobotAPI.robot.speak(psResult.getAuthor(), normalSpeed);
                                mRobotAPI.robot.speak(psResult.getTitle(), normalSpeed);
                                content = psResult.getContent();
                                speakRules(psResult.getType(),content);
                            }
                            break;
                        case "plan_listen_next_one":
                            // 初始化變數
                            mRobotAPI.robot.stopSpeak();

                            psResult = queryDB(db, null, null, null, "plan_listen_next_one", null);
                            if(!psResult.getContent().isEmpty()&&psResult.getAuthor()!=""&&psResult.getTitle()!="") {
                                mRobotAPI.robot.speak(psResult.getAuthor(), normalSpeed);
                                mRobotAPI.robot.speak(psResult.getTitle(), normalSpeed);
                                content = psResult.getContent();
                                speakRules(psResult.getType(),content);
                            }
                            break;
                        case "plan_stopRecite":
                            mRobotAPI.robot.stopSpeak();
                            break;
                        case "plan_continue":
                            mRobotAPI.robot.speak(content, poetSpeed);
                            break;
                        default:
                            break;
                    }
                }catch(Exception e){
                    e.printStackTrace();
                }
            }
        }

        @Override
        public void onRetry(JSONObject jsonObject) {

        }
    };

    public static void speakRules(String type,String content){
        SpeakConfig speed = new SpeakConfig();
        speed.speed(80);
        Log.d(TAG,"[speakRules]: " + type);
        switch(type){
            case "五言絕句":
            case "七言絕句":
            case "五言律詩":
            case "七言律詩":
                mRobotAPI.robot.speak(content,speed);
                break;
            case "五言古詩":
            case "七言古詩":
            case "樂府":
                int count = content.split("[,，。?]").length;
                if(count>=8) {
                    mRobotAPI.robot.speakAndListen("這首詩很長喔, 要朗誦出來嗎?", new SpeakConfig());
                }else {
                    mRobotAPI.robot.speak(content, speed);
                }
                break;
            default:
                break;
        }
    }

    public emotionChatBotPortal() {
        super(robotCallback, robotListenCallback);
    }

    public static poetStructure queryDB(SQLiteDatabase db, String queryPoet, String queryType, String queryTitle, String plan, String sentence){
        String author = "";
        String type = "";
        String title = "";
        poetStructure ps = new poetStructure();
        String content="";
        Cursor result = null;
        db = SQLiteDatabase.openOrCreateDatabase(DB_PATH+"poetry.db", null);
        boolean randomSelect = true;

        switch(plan) {
            case "plan_listen_combo":
                result = db.rawQuery("SELECT * FROM poetryTable where title = ? and author=?", new String[]{queryTitle, queryPoet});
                randomSelect = false;
                break;
            case "plan_listen_type":
                result = db.rawQuery("SELECT * FROM poetryTable where type = ?",new String[]{queryType});
                break;
            case "plan_listen_title":
                result = db.rawQuery("SELECT * FROM poetryTable where title = ?",new String[]{queryTitle});
                break;
            case "plan_listen_poet":
                result = db.rawQuery("SELECT * FROM poetryTable where author = ?",new String[]{queryPoet});
                break;
            case "plan_listen_next_one":
            case "plan_listen_any_one":
                result = db.rawQuery("SELECT * FROM poetryTable where type = ? or type = ?",new String[]{"五言絕句","七言絕句"});
                break;
            case "plan_listen_any":
                if(sentence.length()>=5) {
                    result = db.rawQuery("SELECT * FROM poetryTable where content like ?", new String[]{"%" + sentence + "%"});
                    randomSelect = false;
                }
                break;
        }
        if(result!=null) {
            int rowNumber = result.getCount();
            if (rowNumber != 0) {
                if (randomSelect) {
                    Random random = new Random();
                    int position = random.nextInt(rowNumber);
                    result.moveToPosition(position);
                } else {
                    result.moveToFirst();
                }
                if (result != null) {
                    author = result.getString(0);
                    ps.setAuthor(author);
                    type = result.getString(1);
                    ps.setType(type);
                    title = result.getString(2);
                    ps.setTitle(title);
                    content = result.getString(3);
                    ps.setContent(content);
                    result.close();
                    db.close();
                    String TTS = author + "," + title + " ," + content;
                    Log.d(TAG, TTS);
                    return ps;
                } else {
                    content = "剛剛挑錯了，請再下一次命令";
                    Log.d(TAG, content);
                    ps.setContent(content);
                    result.close();
                    db.close();
                    return ps;
                }
            } else {
                content = "查無資料";
                ps.setContent(content);
                Log.d(TAG, content);
                result.close();
                db.close();
                return ps;
            }
        } else {
            content = "";
            ps.setContent(content);
            Log.d(TAG, content);
            db.close();
            return ps;
        }
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_emotion_chat_bot_portal);
        imageView = (ImageView)findViewById(R.id.tangpoetry);

        mRobotAPI = robotAPI;

        Log.d("onCreate","DB_PATH:"+DB_PATH);
        // 搬動先建立好的DB 從asset移到 /data/data/<package name>/databases/ 底下, 這樣 android 才可以操作
        AssetManager access = getAssets();
        copyDB(DB_PATH,access);

        // 動態新增 instance 到 concept 中 (這邊指的 Concept 與 Instance 均屬於 DDE上的元件)
        // 這個 function 的目的就是讓機器人可以聽懂動態新增的詞彙, 在此我們動態新增"客中行", 開啟唐詩三百首後, 指令"客中行"的預期結果為觸發 plan_listen_title
        JSONArray testUpdate = new JSONArray();
        String [] titleList = {"詠鵝","風","春望詞之一","春望詞之二","春望詞之三","春望詞之四","詠蓮","憫農詩","池上","辛夷塢","七步詩",
                                "題烏江亭","春雁","十一月四日風雨大作","聞王昌齡左遷龍標遙有此寄","夜宿山寺","秋浦歌","勞勞亭",
                                "玉階怨","峨眉山月歌","春夜洛城聞笛","客中行"};
        for(int i=0;i<titleList.length;i++)
            testUpdate.put(titleList[i]); // 李白的客中行, 這是唐詩三百首 DDE 上沒有建置的部分
        robotAPI.robot.dynamicEditInstance(DOMAIN_ID,  DialogSystem.DynamicEditAction.updateNewInstance,"Title" ,testUpdate);

        JSONArray poetUpdate = new JSONArray();
        String [] authorList = {"駱賓王","李嶠","薛饕","鄭允瑞","李紳","曹植","杜牧","王恭","陸游"};
        for(int i=0;i<authorList.length;i++)
            poetUpdate.put(authorList[i]); // 李白的客中行, 這是唐詩三百首 DDE 上沒有建置的部分
        robotAPI.robot.dynamicEditInstance(DOMAIN_ID,  DialogSystem.DynamicEditAction.updateNewInstance,"Poet" ,poetUpdate);

        Intent intent = getIntent();
        JSONObject slu_json;
        try {
            if(intent.getStringExtra("json")!=null) {
                slu_json = new JSONObject(intent.getStringExtra("json"));
                Log.d("[onCreate]JSON", slu_json.toString());
                String TTS = QuerySLUJson(slu_json,"output_text");
                robotAPI.robot.speakAndListen(TTS,new SpeakConfig().timeout(20));
            }
        } catch (NullPointerException | JSONException ex) {
            ex.printStackTrace();
        }
    }

    public static void copyDB(String DB_PATH, AssetManager access){
        byte [] buffer = new byte [1024];
        int length;
        InputStream dbInputStream = null;
        OutputStream dbOutputStream = null;
        //move the db to the designated path
        if ((new File(DB_PATH + "poetry.db")).exists() == false) {
            // 如 SQLite 数据库文件不存在，再检查一下 database 目录是否存在
            File f = new File(DB_PATH);
            // 如 database 目录不存在，新建该目录
            if (!f.exists()) {
                f.mkdir();
            }
        }
        try {
            dbInputStream = access.open("poetry.db");
            dbOutputStream = new FileOutputStream(DB_PATH + "poetry.db");
            while ((length = dbInputStream.read(buffer)) > 0) {
                dbOutputStream.write(buffer, 0, length);
            }
            dbOutputStream.flush();
            dbOutputStream.close();
            dbInputStream.close();
            Log.d(TAG, " DB access successfully");
        } catch (Exception e) {
            e.printStackTrace();
            Log.d(TAG, " DB access Fail from asset manager");
        }

    }

    //parse JSON 的code
    public static String QuerySLUJson(JSONObject Result, String QueryString) {
        DSAPI_Result mDSAPI_Result = new DSAPI_Result(Result.toString());

        JSONObject app_semantic = mDSAPI_Result.event_slu_query.app_semantic();

        if (app_semantic == null)
            return null;

        try {
            if (app_semantic != null) {
                if (app_semantic.isNull(QueryString)) {
                    return null;
                } else {
                    return (app_semantic.optString(QueryString, null));
                }
            }
        } catch (Exception e) {
            e.printStackTrace();
        }
        return null;
    }

    //Android Life Cycle
    @Override
    protected void onStart() {
        super.onStart();
    }

    @Override
    protected void onResume() {
        super.onResume();
        robotAPI.robot.setListenContext(DOMAIN_ID,"listen_poet,listen_combo,listen_title,listne_type,listen_any,listnen_any_one,stopRecite,continue,listen_next_one");
        robotAPI.robot.registerListenCallback(robotListenCallback);
    }

    @Override
    protected void onPause() {
        super.onPause();
        //stop listen user utterance
        robotAPI.robot.stopSpeak();
        robotAPI.robot.unregisterListenCallback();
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        robotAPI.robot.stopSpeak();
        robotAPI.robot.unregisterListenCallback();
        robotAPI.robot.clearAppContext(DOMAIN_ID);
    }

    static class poetStructure{
        String author = ""; //ex: 李白
        String type = ""; //ex: 五言絕句
        String title = ""; //塞上曲
        String content = "";
        public String getAuthor() {
            return author;
        }

        public void setAuthor(String author) {
            this.author = author;
        }

        public String getType() {
            return type;
        }

        public void setType(String type) {
            this.type = type;
        }

        public String getTitle() {
            return title;
        }

        public void setTitle(String title) {
            this.title = title;
        }

        public String getContent() {
            return content;
        }

        public void setContent(String content) {
            this.content = content;
        }
    }
}
