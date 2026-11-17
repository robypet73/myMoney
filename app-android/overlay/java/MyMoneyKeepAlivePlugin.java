package it.robypet73.mymoney;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/** start/stop del servizio in primo piano durante gli scarichi; delay = attesa nativa (i timer JS di una pagina in secondo piano vengono rallentati da Chromium). */
@CapacitorPlugin(name = "MyMoneyKeepAlive")
public class MyMoneyKeepAlivePlugin extends Plugin {
    @PluginMethod public void start(PluginCall call) {
        try {
            if (Build.VERSION.SDK_INT >= 33 && getActivity().checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
                getActivity().requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 7002);
            Intent i = new Intent(getContext(), MyMoneyKeepAliveService.class).putExtra("text", call.getString("text", "Scarico i dati degli ETF"));
            if (Build.VERSION.SDK_INT >= 26) getContext().startForegroundService(i); else getContext().startService(i);
            call.resolve(new JSObject().put("ok", true));
        } catch (Exception e) { call.resolve(new JSObject().put("ok", false).put("error", String.valueOf(e.getMessage()))); }
    }
    @PluginMethod public void stop(PluginCall call) {
        try { getContext().stopService(new Intent(getContext(), MyMoneyKeepAliveService.class)); } catch (Exception e) { }
        call.resolve(new JSObject().put("ok", true));
    }
    @PluginMethod public void delay(PluginCall call) {
        final int ms = Math.max(0, Math.min(60000, call.getInt("ms", 0)));
        new Handler(Looper.getMainLooper()).postDelayed(() -> call.resolve(new JSObject().put("ok", true)), ms);
    }
}
