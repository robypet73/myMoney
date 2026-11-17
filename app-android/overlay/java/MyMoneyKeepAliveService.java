package it.robypet73.mymoney;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;

/** Servizio in primo piano: tiene viva l'app (e la CPU) mentre scarica i dati con la clessidra, anche se l'app esce dal focus. */
public class MyMoneyKeepAliveService extends Service {
    static volatile boolean running = false;
    private PowerManager.WakeLock wl;
    private static final String CH = "mm_download";

    @Override public IBinder onBind(Intent i) { return null; }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        String text = intent != null && intent.getStringExtra("text") != null ? intent.getStringExtra("text") : "Scarico i dati degli ETF";
        NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= 26 && nm != null) nm.createNotificationChannel(new NotificationChannel(CH, "Scarico dati", NotificationManager.IMPORTANCE_LOW));
        Intent open = new Intent(this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent pi = PendingIntent.getActivity(this, 0, open, PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0));
        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(this, CH) : new Notification.Builder(this);
        Notification n = b.setContentTitle("myMoney").setContentText(text).setSmallIcon(android.R.drawable.stat_sys_download).setOngoing(true).setContentIntent(pi).build();
        if (Build.VERSION.SDK_INT >= 29) startForeground(7001, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC); else startForeground(7001, n);
        if (wl == null) {
            PowerManager pm = (PowerManager) getSystemService(Context.POWER_SERVICE);
            if (pm != null) { wl = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "myMoney:download"); wl.setReferenceCounted(false); }
        }
        if (wl != null && !wl.isHeld()) wl.acquire(60 * 60 * 1000L); // al massimo 1 ora
        running = true;
        return START_NOT_STICKY;
    }

    @Override public void onDestroy() {
        running = false;
        if (wl != null && wl.isHeld()) wl.release();
        super.onDestroy();
    }
}
