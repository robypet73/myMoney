package it.robypet73.mymoney;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Dopo il riavvio del telefono o l'aggiornamento dell'app riprogramma l'aggiornamento ogni 5 minuti del widget. */
public class MyMoneyBoot extends BroadcastReceiver {
    @Override
    public void onReceive(Context c, Intent i) {
        MyMoneyWidget.schedule(c);
        MyMoneyWidget.refreshAsync(c, null);
    }
}
