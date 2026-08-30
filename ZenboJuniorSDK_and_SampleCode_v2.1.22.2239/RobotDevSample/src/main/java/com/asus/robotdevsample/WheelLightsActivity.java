package com.asus.robotdevsample;

import android.content.Intent;
import android.os.Bundle;
import android.util.Log;
import android.view.View;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.ListView;
import android.widget.TextView;

import com.asus.robotframework.API.RobotCallback;
import com.asus.robotframework.API.RobotCmdState;
import com.asus.robotframework.API.RobotCommand;
import com.asus.robotframework.API.RobotErrorCode;
import com.asus.robotframework.API.WheelLights;
import com.robot.asus.robotactivity.RobotActivity;

import org.json.JSONObject;

import java.util.Random;

public class WheelLightsActivity extends RobotActivity {

    private ListView listView;
    private String[] listViewitems;
    private ArrayAdapter listAdapter;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.layout_listview_menu);

        //title
        TextView mTextViewTitle = (TextView) findViewById(R.id.textview_title);
        mTextViewTitle.setText(getString(R.string.toolbar_title_subclass_wheel_title));

        listViewitems = getResources().getStringArray(R.array.subclasses_wheel);
        listView = (ListView) findViewById(R.id.list_view);
        listAdapter = new ArrayAdapter(this, android.R.layout.simple_list_item_1, listViewitems);
        listView.setAdapter(listAdapter);
        listView.setOnItemClickListener(new AdapterView.OnItemClickListener() {
            @Override
            public void onItemClick(AdapterView<?> parent, View view, int position, long id) {

                Intent subExample;
                switch (position) {
                    case 0:
                        //.setColor
                        subExample = new Intent(WheelLightsActivity.this, WheelLightsSetColor.class);
                        startActivity(subExample);
                        break;
                    case 1:
                        //.startBreath
                        robotAPI.wheelLights.turnOff(WheelLights.Lights.SYNC_BOTH, 0xff);
                        robotAPI.wheelLights.setColor(WheelLights.Lights.SYNC_BOTH, 0xff, 0x007F7F);
                        robotAPI.wheelLights.startBreath(WheelLights.Lights.SYNC_BOTH, WheelLights.Speed.DEFAULT);
                        break;

                    case 2:
                        //.startBreathRainbow
                        robotAPI.wheelLights.turnOff(WheelLights.Lights.SYNC_BOTH, 0xff);
                        robotAPI.wheelLights.startBreathRainbow(WheelLights.Lights.SYNC_BOTH, WheelLights.Speed.DEFAULT);
                        break;

                    case 3:
                        //.startColorCycle
                        robotAPI.wheelLights.turnOff(WheelLights.Lights.SYNC_BOTH, 0xff);
                        robotAPI.wheelLights.startColorCycle(WheelLights.Lights.SYNC_BOTH, WheelLights.Speed.DEFAULT);
                        break;

                    case 4:
                        //.startComet
                        robotAPI.wheelLights.turnOff(WheelLights.Lights.SYNC_BOTH, 0xff);
                        robotAPI.wheelLights.startComet(WheelLights.Lights.SYNC_BOTH, WheelLights.Direction.DIRECTION_FORWARD, WheelLights.Speed.DEFAULT);
                        break;

                    case 5:
                        //.startFlashDash
                        robotAPI.wheelLights.turnOff(WheelLights.Lights.SYNC_BOTH, 0xff);
                        robotAPI.wheelLights.startFlashDash(WheelLights.Lights.SYNC_BOTH, WheelLights.Direction.DIRECTION_FORWARD, WheelLights.Speed.DEFAULT);
                        break;

                    case 6:
                        //.startGlowingYoYo
                        robotAPI.wheelLights.turnOff(WheelLights.Lights.SYNC_BOTH, 0xff);
                        robotAPI.wheelLights.startGlowingYoYo(WheelLights.Lights.SYNC_BOTH, WheelLights.Speed.DEFAULT);
                        break;

                    case 7:
                        //.startMovingFlash
                        robotAPI.wheelLights.turnOff(WheelLights.Lights.SYNC_BOTH, 0xff);
                        robotAPI.wheelLights.setColor(WheelLights.Lights.SYNC_BOTH, 0xff, 0xf542e9);
                        robotAPI.wheelLights.startMovingFlash(WheelLights.Lights.SYNC_BOTH, WheelLights.Direction.DIRECTION_FORWARD, WheelLights.Speed.DEFAULT);
                        break;

                    case 8:
                        //.startRainbowComet
                        robotAPI.wheelLights.turnOff(WheelLights.Lights.SYNC_BOTH, 0xff);
                        robotAPI.wheelLights.startRainbowComet(WheelLights.Lights.SYNC_BOTH, WheelLights.Direction.DIRECTION_FORWARD, WheelLights.Speed.DEFAULT);
                        break;

                    case 9:
                        //.startRainbowWave
                        robotAPI.wheelLights.turnOff(WheelLights.Lights.SYNC_BOTH, 0xff);
                        robotAPI.wheelLights.startRainbowWave(WheelLights.Lights.SYNC_BOTH, WheelLights.Direction.DIRECTION_FORWARD, WheelLights.Speed.DEFAULT);
                        break;

                    case 10:
                        //.startStarryNight
                        robotAPI.wheelLights.turnOff(WheelLights.Lights.SYNC_BOTH, 0xff);
                        robotAPI.wheelLights.startStarryNight(WheelLights.Lights.SYNC_BOTH, WheelLights.Speed.DEFAULT);
                        break;

                    case 11:
                        //.startStatic
                        robotAPI.wheelLights.turnOff(WheelLights.Lights.SYNC_BOTH, 0xff);
                        robotAPI.wheelLights.setColor(WheelLights.Lights.SYNC_BOTH, 0xff, 0x63f250);
                        robotAPI.wheelLights.startStatic(WheelLights.Lights.SYNC_BOTH);
                        break;

                    case 12:
                        //.startStrobing
                        robotAPI.wheelLights.turnOff(WheelLights.Lights.SYNC_BOTH, 0xff);
                        robotAPI.wheelLights.setColor(WheelLights.Lights.SYNC_BOTH, 0xff, 0x47b339);
                        robotAPI.wheelLights.startStrobing(WheelLights.Lights.SYNC_BOTH, WheelLights.Speed.DEFAULT);
                        break;

                    case 13:
                        //.startWave
                        robotAPI.wheelLights.turnOff(WheelLights.Lights.SYNC_BOTH, 0xff);
                        robotAPI.wheelLights.setColor(WheelLights.Lights.SYNC_BOTH, 0xff, 0x393db3);
                        robotAPI.wheelLights.startWave(WheelLights.Lights.SYNC_BOTH, WheelLights.Speed.DEFAULT);
                        break;


                    case 14:
                        //.turnOff
                        subExample = new Intent(WheelLightsActivity.this, WheelLightsTurnOff.class);
                        startActivity(subExample);
                        break;
                }


            }
        });

    }


    int color = 0;

    private int getRandomColor() {
        Random random = new Random();

        return random.nextInt() % 0xA0 + random.nextInt() % 0xA0 * 0x100 +
                random.nextInt() % 0xA0 * 0x10000;
    }


    public static RobotCallback robotCallback = new RobotCallback() {
        @Override
        public void onResult(int cmd, int serial, RobotErrorCode err_code, Bundle result) {
            super.onResult(cmd, serial, err_code, result);

            Log.d("RobotDevSample", "onResult:"
                    + RobotCommand.getRobotCommand(cmd).name()
                    + ", serial:" + serial + ", err_code:" + err_code
                    + ", result:" + result.getString("RESULT"));
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

        }

        @Override
        public void onResult(JSONObject jsonObject) {

        }

        @Override
        public void onRetry(JSONObject jsonObject) {

        }
    };


    public WheelLightsActivity() {
        super(robotCallback, robotListenCallback);
    }
}
