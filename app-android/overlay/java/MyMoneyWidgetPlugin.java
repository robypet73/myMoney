package it.robypet73.mymoney;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/** Riceve dalla pagina la sintesi del portafoglio preferito e aggiorna il widget della schermata Home. */
@CapacitorPlugin(name = "MyMoneyWidget")
public class MyMoneyWidgetPlugin extends Plugin {
    @PluginMethod
    public void update(PluginCall call) {
        String data = call.getString("data");
        if (data == null) {
            call.reject("dati mancanti");
            return;
        }
        getContext().getSharedPreferences(MyMoneyWidget.PREFS, 0).edit().putString(MyMoneyWidget.KEY, data).apply();
        MyMoneyWidget.refreshAll(getContext());
        call.resolve(new JSObject());
    }
}
