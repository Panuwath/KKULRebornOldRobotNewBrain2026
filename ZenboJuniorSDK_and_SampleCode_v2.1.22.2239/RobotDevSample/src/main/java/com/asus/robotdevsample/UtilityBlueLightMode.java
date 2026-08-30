package com.asus.robotdevsample;

import android.os.Bundle;
import android.util.Log;
import android.view.View;
import android.view.WindowManager;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.Spinner;
import android.widget.TextView;

import com.asus.robotframework.API.RobotAPI;
import com.asus.robotframework.API.RobotCallback;
import com.asus.robotframework.API.RobotCmdState;
import com.asus.robotframework.API.RobotCommand;
import com.asus.robotframework.API.RobotErrorCode;
import com.asus.robotframework.API.RobotFace;
import com.asus.robotframework.API.RobotUtil;
import com.robot.asus.robotactivity.RobotActivity;

import org.json.JSONObject;
import org.w3c.dom.Text;

import java.util.ArrayList;
import java.util.List;

public class UtilityBlueLightMode extends RobotActivity {
    private Spinner mSpinner;
    private ArrayAdapter<String> SpinnerList;
    private String[] blueLightModeArray = {"DEF", "Rd01", "Rd02", "Rd03", "RdStrong", "RdWeak"};

    private Button btn_start;
    private static TextView  textView_currentBlueLightModeState;
    private static TextView  textView_currentBlueLightMode;

    private static RobotAPI mRobotAPI;
    private static int iCurrentCommandSerial;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.layout_utility_bluelightmode);

        mRobotAPI = robotAPI;
        textView_currentBlueLightModeState = (TextView) findViewById(R.id.textView_get_blueLight_mode_state_result);
        textView_currentBlueLightMode = (TextView) findViewById(R.id.textView_get_blueLight_mode_result);

        //title
        TextView mTextViewTitle = (TextView) findViewById(R.id.textview_title);
        mTextViewTitle.setText(getString(R.string.utility_setScreenBlueLightFilterMode_full));

        //hide ime
        getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_STATE_HIDDEN);


        //get current blue light filter mode state
        boolean isBlueLightFilterEnable =  mRobotAPI.utility.getScreenBlueLightFilterEnable();
        textView_currentBlueLightModeState.setText( isBlueLightFilterEnable?"ON": "OFF");

        //check blue light filter if enable, then get current blue light mode.
        if(isBlueLightFilterEnable) {
            //get current blue light filter mode
            textView_currentBlueLightMode.setText(mRobotAPI.utility.getScreenBlueLightFilterMode());
        } else {
            //blue light mode is disabled
            textView_currentBlueLightMode.setText("Not Available");
        }

        //spinner of blue light filter mode selections
        mSpinner = (Spinner) findViewById(R.id.spinner_blue_light_mode_candidate);
        SpinnerList = new ArrayAdapter<String>(this, android.R.layout.simple_spinner_item, blueLightModeArray);
        mSpinner.setAdapter(SpinnerList);

        btn_start = (Button) findViewById(R.id.btn_setScreenBlueLightFilterMode);
        btn_start.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View arg0) {

                // get user's selection of blue light filter mode
                String SpinnerText = mSpinner.getSelectedItem().toString();

                // set blue light mode, and take robot the command serial
                // the mode can be set by string "DEF", "Rd01", "Rd02", "Rd03", "RdStrong", "RdWeak"
                iCurrentCommandSerial = mRobotAPI.utility.setScreenBlueLightFilterMode(SpinnerText);

                Log.d("RobotDevSample", "setScreenBlueLightFilterMode = " + SpinnerText);

            }
        });

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

            Log.d("RobotDevSample", "onStateChange:"
                    + RobotCommand.getRobotCommand(cmd).name()
                    + ", serial:" + serial + ", err_code:" + err_code
                    + ", state:" + state);


            // when set blue light mode api done, check if command succeed, and then update blue light status on UI
            if (serial == iCurrentCommandSerial && state == RobotCmdState.SUCCEED) {

                boolean isBlueLightFilterEnable =  mRobotAPI.utility.getScreenBlueLightFilterEnable();

                //update current blue light filter mode state
                textView_currentBlueLightModeState.setText( isBlueLightFilterEnable?"ON": "OFF");

                //update current blue light filter mode if blue light filter is enabled
                if(isBlueLightFilterEnable) {
                    textView_currentBlueLightMode.setText(mRobotAPI.utility.getScreenBlueLightFilterMode());
                } else {
                    textView_currentBlueLightMode.setText("Not Available");
                }
            }

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


    public UtilityBlueLightMode() {
        super(robotCallback, robotListenCallback);
    }
}
