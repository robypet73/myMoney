package it.robypet73.mymoney;

import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(MyMoneyWidgetPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
