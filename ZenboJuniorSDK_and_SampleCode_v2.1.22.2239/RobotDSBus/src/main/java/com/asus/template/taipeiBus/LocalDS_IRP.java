package com.asus.template.taipeiBus;
//package com.asus.ctc.cloud;

import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.ServiceConnection;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Message;
import android.os.Messenger;
import android.os.RemoteException;
import android.util.Log;
import android.widget.Toast;

import org.json.JSONObject;

/**
 * Created by asus on 2016/8/26.
 */
public class LocalDS_IRP {
    public static String TAG = "EdgeDS_IRP";
    private Messenger mDSService = null;
    private Messenger mDSReciver = new Messenger(new IncomingHandler());
    private Context mcontext = null;
    Boolean isDSRunning = false;
    long sysTimeSpent = 0, sysT1 = 0;
    LocalDS_IRP_Callback mLocalDS_IRP_Callback = null;
    String appList = "";
    boolean mIsBound = false;

    public LocalDS_IRP(Context in_context, LocalDS_IRP_Callback in_LocalDS_IRP_Callback, String _inStr)  {
        mLocalDS_IRP_Callback = in_LocalDS_IRP_Callback;
        mcontext=in_context;
        appList = _inStr;
        InitialLocalDS();
    }

    public interface LocalDS_IRP_Callback {
        void replyMessage(int what, String str1, String str2);
    }

    class IncomingHandler extends Handler {
        @Override
        public void handleMessage(Message msg) {
            Bundle bundle;
            String str1="", str2="";
            switch (msg.what) {
                case Setting._LOCALDS:
                case Setting._CLOUDDS:
                    //Log.i(TAG, "MainActivity receives msg from Local DS Service. Input: " + inputString);
                    bundle = msg.getData();
                    str1 = bundle.getString("message1"); // output String by DS
                    str2 = bundle.getString("message2"); // timeSpent
                    isDSRunning = false;
                    sysTimeSpent = System.currentTimeMillis() - sysT1;
                    mLocalDS_IRP_Callback.replyMessage( msg.what, str1, str2);
                    break;
                case Setting._LOCALDS_READY:
                case Setting._BUILD_MONGO_ALL:
                case Setting._BUILD_MONGO_OK:
                case Setting._BUILD_SLUDB_ALL:
                case Setting._BUILD_SLUDB_BY_APP:
                case Setting._BUILD_SLUDB_OK:
                case Setting._UPDATE_DS_DATA_OK:
                case Setting._UPDATE_DS_DATA_FAIL:
                case Setting._SHOW_APPLIST_OK:
                case Setting._PREPARE_UPLOAD_OK:
                case Setting._UPLOAD_LOG_FAIL:
                case Setting._UPLOAD_LOG_OK:
                case Setting._SET_SERVERLO:
                case Setting._SET_SERVERLO_DONE:
                case Setting._SET_SERVERLO_FAIL:
                case Setting._MESSAGE:
                case Setting._UPDATE_DS_BY_PKG_OK:
                case Setting._UPDATE_DS_BY_PKG_FAIL:
                case Setting._UPDATE_DS_DATA_COMPLETE:
                    bundle = msg.getData();
                    str1 = bundle.getString("message1");
                    str2 = bundle.getString("message2");
                    mLocalDS_IRP_Callback.replyMessage( msg.what, str1, str2);
                    break;
                case Setting._GET_SERVERLO:
                    bundle = msg.getData();
                    str1 = bundle.getString("message1");
                    mLocalDS_IRP_Callback.replyMessage( msg.what, str1, "");
                    break;
                default:
                    super.handleMessage(msg);
            }
        }
    }

    public void send2LocalDSService(String str, int what) {

        sysT1 = System.currentTimeMillis();
        Message msg = Message.obtain();
        Bundle data = new Bundle();
        data.putString("message", str);
//        data.putString("server", "ext_server");
        msg.setData(data);
        msg.what    = what;
        msg.replyTo = mDSReciver;

        try {
            if ( mDSService != null )
                mDSService.send(msg);
            else
                returnErrorMsg(str, what);
        } catch (RemoteException e) {
            // TODO Auto-generated catch block
            e.printStackTrace();
        }
    }

    void returnErrorMsg(String str, int what) {
        try {
            JSONObject ans = null;
            JSONObject info = new JSONObject();

            ans = new JSONObject();
            info.put( "Status" , "Not_Ready");
            info.put( "Mode" , "Local");
            ans.put( "LocalDS" , info);
            String str1 = ans.toString();

            mLocalDS_IRP_Callback.replyMessage( Setting._LOCALDS_NOT_READY, str, "0");
            Log.e(TAG, "[returnErrorMsg] mDSService not ready!! DS got: " + str + ", what = " + what +  ", DS sent back: " + str1);

        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    private void InitialLocalDS() {
        Log.v(TAG, "InitialLocalDS");
        Intent intent = new Intent();
        intent.setClassName("com.asus.edgeDS", "com.asus.edgeDS.EdgeDS");
        mIsBound = mcontext.bindService(intent, connection, Context.BIND_AUTO_CREATE | Context.BIND_IMPORTANT);
        Log.i(TAG, "[InitialLocalDS] initService() bound value: " + mIsBound);
    }

    public void unbindLocalDS(){
        if(mIsBound) {
            send2LocalDSService( "" , Setting._REMOVE_MSG);
            mcontext.unbindService(connection);
            mIsBound = false;
        }
    }

    /**
     * @brief Service connection
     */

    private ServiceConnection connection = new ServiceConnection() {
        @Override
        public void onServiceConnected(ComponentName name, IBinder boundService) {
            mDSService = new Messenger(boundService);
            Toast.makeText(mcontext, "LocalDS Service connected", Toast.LENGTH_LONG).show();

//            send2LocalDSService( appList , Setting._LOCALDS_START);
//            send2LocalDSService( "" , Setting._GET_SERVERLO);
        }

        @Override
        public void onServiceDisconnected(ComponentName name) {

        }
    };

    public void refreshUI(){
        if(mIsBound) {
            send2LocalDSService( "" , Setting._GET_SERVERLO);
        }
    }

}
