package com.asus.robotlinefollow;


import android.app.Activity;
import android.os.Bundle;
import android.support.annotation.Nullable;
import android.util.Log;
import android.view.View;
import android.widget.Button;

import com.asus.robotframework.API.LineFollowerConfig;
import com.asus.robotframework.API.MotionControl;
import com.asus.robotframework.API.RobotAPI;
import com.asus.robotframework.API.RobotCallback;
import com.asus.robotframework.API.RobotCmdState;
import com.asus.robotframework.API.RobotErrorCode;
import com.asus.robotframework.API.RobotFace;
import com.asus.robotframework.API.Utility;

import org.json.JSONException;
import org.json.JSONObject;


public class MainActivity extends Activity {
    RobotAPI mRobotAPI;
    RobotCallback mRobotCallback;
    String TAG = "RobotLineFollow";
    int serial;
    View decorView;
    Button setBehaviorButton;
    Button buttonStartLineFollow;

    RobotErrorCode errorCode;

    @Override
    protected void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        decorView = getWindow().getDecorView();

        setBehaviorButton = (Button) findViewById(R.id.button);
        buttonStartLineFollow = (Button) findViewById(R.id.buttonStart);
    }

    @Override
    protected void onResume() {
        super.onResume();

        decorView.setSystemUiVisibility(View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_IMMERSIVE);


        mRobotCallback = new RobotCallback() {
            @Override
            public void onResult(int cmd, int serial, RobotErrorCode err_code, Bundle result) {
                super.onResult(cmd, serial, err_code, result);
                try {
                    if (result != null) {
                        if (result.getString("Color_Result") != null) {
                            JSONObject json = new JSONObject(result.getString("Color_Result"));
                            String pos = json.getString("Position");
                            String valueString = json.getString("Value");
                            String colorString = json.getString("Color");
                            String behaviorString = json.getString("Behavior");

                            if (colorString.equals("RED")) { /* rule 5 */
                                mRobotAPI.cancelCommandBySerial(serial);
                                mRobotAPI.utility.playEmotionalAction(RobotFace.HAPPY, Utility.PlayAction.Nod_1);
                                mRobotAPI.robot.speak("Good Job");
                            }
                        }
                    }
                } catch (JSONException ex) {

                }
            }

            @Override
            public void onStateChange(int cmd, int serial, RobotErrorCode err_code, RobotCmdState state) {
                super.onStateChange(cmd, serial, err_code, state);
            }

        };
        mRobotAPI = new RobotAPI(this, mRobotCallback);

        mRobotAPI.robot.setExpression(RobotFace.HIDEFACE);

        /* Rule:
            1. Black: Speed L1
            2. Blue: Speed L3
            3. Pattern(Green-Blue-Green): U_TURN (pattern start with Yellow)
            4. Button click: U_TURN
            5. Red: Stop and then set face/TTS/playAction ---> do it in onResult callback
            */
        final LineFollowerConfig lineFollowerConfig = new LineFollowerConfig();

        /* rule 1 */
        errorCode = lineFollowerConfig.addRule(LineFollowerConfig.Color.BLACK,
                LineFollowerConfig.Behavior.SPEED_LEVEL, MotionControl.SpeedLevel.LineFollower.L1);
        if (errorCode != RobotErrorCode.NO_ERROR) {
            Log.d(TAG, "onResume: LineFollowerConfig adds wrong rule 1 with " + errorCode.toString());
            return;
        }

        /* rule 2 */
        errorCode = lineFollowerConfig.addRule(LineFollowerConfig.Color.BLUE,
                LineFollowerConfig.Behavior.SPEED_LEVEL, MotionControl.SpeedLevel.LineFollower.L3);
        if (errorCode != RobotErrorCode.NO_ERROR) {
            Log.d(TAG, "onResume: LineFollowerConfig adds wrong rule 2 with " + errorCode.toString());
            return;
        }


        /* rule 3 */
        LineFollowerConfig.ColorPattern pattern = new LineFollowerConfig.ColorPattern();
        pattern.set(LineFollowerConfig.Color.GREEN, LineFollowerConfig.Color.BLUE, LineFollowerConfig.Color.GREEN);
        errorCode = lineFollowerConfig.addRule(pattern, LineFollowerConfig.Behavior.U_TURN);
        if (errorCode != RobotErrorCode.NO_ERROR) {
            Log.d(TAG, "onResume: LineFollowerConfig adds wrong rule 3 with " + errorCode.toString());
            return;
        }


        /* rule 4 */
        setBehaviorButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                mRobotAPI.lineFollower.setBehavior(serial, LineFollowerConfig.Behavior.U_TURN);
            }
        });


        /* Start line follow*/
        buttonStartLineFollow.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                /* begin */
                serial = mRobotAPI.lineFollower.followLine(lineFollowerConfig.build());
            }
        });

    }

    @Override
    protected void onPause() {
        super.onPause();
        mRobotAPI.cancelCommandBySerial(serial);
        mRobotAPI.robot.setExpression(RobotFace.HIDEFACE);
        mRobotAPI.release();
    }
}
