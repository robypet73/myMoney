package it.robypet73.mymoneyportafogli;

import android.content.Context;
import androidx.annotation.NonNull;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

/** Aggiornamento del widget in background (WorkManager): scarica i prezzi da justETF anche con l'app chiusa e ridisegna il widget. */
public class MyMoneyWidgetWorker extends Worker {
    public MyMoneyWidgetWorker(@NonNull Context c, @NonNull WorkerParameters p) {
        super(c, p);
    }

    @NonNull
    @Override
    public Result doWork() {
        try {
            MyMoneyWidget.refreshData(getApplicationContext());
            MyMoneyWidget.refreshAll(getApplicationContext());
            return Result.success();
        } catch (Exception e) {
            return Result.retry();
        }
    }
}
