package it.robypet73.mymoney;

import android.os.Bundle;
import android.webkit.WebView;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(MyMoneyWidgetPlugin.class);
        registerPlugin(MyMoneyFolderPlugin.class);
        registerPlugin(MyMoneyKeepAlivePlugin.class);
        super.onCreate(savedInstanceState);
    }

    // Con uno scarico in corso (servizio in primo piano) la pagina non si ferma quando l'app esce dal focus
    private void keepRunning() {
        if (!MyMoneyKeepAliveService.running || getBridge() == null) return;
        WebView w = getBridge().getWebView();
        if (w != null) { w.onResume(); w.resumeTimers(); }
    }
    @Override public void onPause() { super.onPause(); keepRunning(); }
    @Override public void onStop() { super.onStop(); keepRunning(); }
}
