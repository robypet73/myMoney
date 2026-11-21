package it.robypet73.mymoneyportafogli;

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
        String file = call.getString("file");
        if (file == null || file.isEmpty()) file = "portafoglio";
        android.content.SharedPreferences.Editor ed = getContext().getSharedPreferences(MyMoneyWidget.PREFS, 0).edit();
        ed.remove("data");  // formato delle versioni precedenti: un solo portafoglio
        ed.putString(MyMoneyWidget.chiave(file), data);
        ed.putString("ultimo", file);
        com.getcapacitor.JSArray files = call.getArray("files");
        if (files != null) {  // i portafogli eliminati o rinominati escono dal widget
            java.util.HashSet<String> ok = new java.util.HashSet<String>();
            try {
                for (int i = 0; i < files.length(); i++) ok.add(files.getString(i));
            } catch (Exception e) {
                ok.clear();
            }
            if (!ok.isEmpty()) for (String f : MyMoneyWidget.portafogli(getContext())) if (!ok.contains(f) && !f.equals(file)) ed.remove(MyMoneyWidget.chiave(f));
        }
        ed.apply();
        MyMoneyWidget.scheduleWork(getContext());  // da ora il widget si aggiorna da solo ogni ora
        MyMoneyWidget.refreshAll(getContext());
        call.resolve(new JSObject());
    }
}
