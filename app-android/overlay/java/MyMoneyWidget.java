package it.robypet73.mymoney;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.Shader;
import android.os.Bundle;
import android.view.View;
import android.widget.RemoteViews;
import java.text.NumberFormat;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import org.json.JSONArray;
import org.json.JSONObject;

/** Widget: valore, rendimento sull'investito, variazione di oggi, confronto col benchmark e andamento del portafoglio preferito. */
public class MyMoneyWidget extends AppWidgetProvider {
    static final String PREFS = "mymoney_widget";
    static final String KEY = "data";
    static final int UP = Color.parseColor("#1F9D6B");
    static final int DOWN = Color.parseColor("#D6453D");

    @Override
    public void onUpdate(Context c, AppWidgetManager m, int[] ids) {
        for (int id : ids) draw(c, m, id);
    }

    @Override
    public void onAppWidgetOptionsChanged(Context c, AppWidgetManager m, int id, Bundle o) {
        draw(c, m, id);
    }

    static void refreshAll(Context c) {
        AppWidgetManager m = AppWidgetManager.getInstance(c);
        for (int id : m.getAppWidgetIds(new ComponentName(c, MyMoneyWidget.class))) draw(c, m, id);
    }

    static String eur(double v) {
        return NumberFormat.getCurrencyInstance(Locale.ITALY).format(v);
    }

    static String pct(double v) {
        return String.format(Locale.ITALY, "%+.2f%%", v * 100);
    }

    static void draw(Context c, AppWidgetManager m, int id) {
        RemoteViews v = new RemoteViews(c.getPackageName(), R.layout.widget_mymoney);
        Intent open = c.getPackageManager().getLaunchIntentForPackage(c.getPackageName());
        if (open != null) {
            v.setOnClickPendingIntent(R.id.w_root, PendingIntent.getActivity(c, 0, open, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE));
        }
        String raw = c.getSharedPreferences(PREFS, 0).getString(KEY, null);
        try {
            JSONObject d = new JSONObject(raw);
            double val = d.getDouble("val");
            v.setTextViewText(R.id.w_name, d.optString("name", "Portafoglio"));
            v.setTextViewText(R.id.w_value, eur(val));
            boolean hasRoi = !d.isNull("roi");
            if (hasRoi) {
                double roi = d.getDouble("roi"), profit = d.optDouble("profit", 0);
                v.setTextViewText(R.id.w_roi, pct(roi) + "  " + (profit >= 0 ? "+" : "") + eur(profit));
                v.setTextColor(R.id.w_roi, roi >= 0 ? UP : DOWN);
                v.setTextViewText(R.id.w_roi_l, "sull'investito");
            } else {
                v.setTextViewText(R.id.w_roi, "");
                v.setTextViewText(R.id.w_roi_l, "");
            }
            if (!d.isNull("day")) {
                double day = d.getDouble("day");
                v.setTextViewText(R.id.w_day, "Oggi " + pct(day));
                v.setTextColor(R.id.w_day, day >= 0 ? UP : DOWN);
            } else {
                v.setTextViewText(R.id.w_day, "");
            }
            if (!d.isNull("gap")) {
                double gap = d.getDouble("gap");
                v.setTextViewText(R.id.w_bm, String.format(Locale.ITALY, "vs benchmark %+.1f pp", gap));
                v.setTextColor(R.id.w_bm, gap >= 0.5 ? UP : gap >= -1 ? Color.parseColor("#B8860B") : DOWN);
            } else {
                v.setTextViewText(R.id.w_bm, "");
            }
            long at = d.optLong("at", 0);
            v.setTextViewText(R.id.w_upd, at > 0 ? new SimpleDateFormat("HH:mm", Locale.ITALY).format(new Date(at)) : "");
            JSONArray a = d.optJSONArray("series");
            Bitmap chart = null;
            if (a != null && a.length() >= 2) {
                double[] s = new double[a.length()];
                for (int i = 0; i < s.length; i++) s[i] = a.getDouble(i);
                chart = chart(s, s[s.length - 1] >= s[0]);
            }
            if (chart != null) {
                v.setImageViewBitmap(R.id.w_chart, chart);
                v.setViewVisibility(R.id.w_chart, View.VISIBLE);
            } else {
                v.setViewVisibility(R.id.w_chart, View.GONE);
            }
        } catch (Exception e) {
            v.setTextViewText(R.id.w_name, "myMoney");
            v.setTextViewText(R.id.w_value, "Apri l'app");
            v.setTextViewText(R.id.w_roi, "");
            v.setTextViewText(R.id.w_roi_l, "");
            v.setTextViewText(R.id.w_day, "");
            v.setTextViewText(R.id.w_bm, "");
            v.setTextViewText(R.id.w_upd, "");
            v.setViewVisibility(R.id.w_chart, View.GONE);
        }
        m.updateAppWidget(id, v);
    }

    /** Andamento del valore: linea e area sfumata, verde se in salita nel periodo, rossa se in discesa. */
    static Bitmap chart(double[] s, boolean up) {
        final int W = 640, H = 200, pad = 8;
        Bitmap b = Bitmap.createBitmap(W, H, Bitmap.Config.ARGB_8888);
        Canvas cv = new Canvas(b);
        double mn = Double.MAX_VALUE, mx = -Double.MAX_VALUE;
        for (double x : s) {
            mn = Math.min(mn, x);
            mx = Math.max(mx, x);
        }
        if (mx - mn < 1e-9) mx = mn + 1;
        int col = up ? UP : DOWN;
        Path line = new Path(), fill = new Path();
        float lx = 0, ly = 0;
        for (int i = 0; i < s.length; i++) {
            float x = pad + (W - 2f * pad) * i / (s.length - 1);
            float y = (float) (pad + (H - 2f * pad) * (1 - (s[i] - mn) / (mx - mn)));
            if (i == 0) {
                line.moveTo(x, y);
                fill.moveTo(x, H);
                fill.lineTo(x, y);
            } else {
                line.lineTo(x, y);
                fill.lineTo(x, y);
            }
            lx = x;
            ly = y;
        }
        fill.lineTo(lx, H);
        fill.close();
        Paint fp = new Paint(Paint.ANTI_ALIAS_FLAG);
        fp.setStyle(Paint.Style.FILL);
        fp.setShader(new LinearGradient(0, 0, 0, H, (col & 0x00FFFFFF) | 0x55000000, (col & 0x00FFFFFF), Shader.TileMode.CLAMP));
        cv.drawPath(fill, fp);
        Paint lp = new Paint(Paint.ANTI_ALIAS_FLAG);
        lp.setStyle(Paint.Style.STROKE);
        lp.setStrokeWidth(5f);
        lp.setStrokeJoin(Paint.Join.ROUND);
        lp.setStrokeCap(Paint.Cap.ROUND);
        lp.setColor(col);
        cv.drawPath(line, lp);
        Paint dp = new Paint(Paint.ANTI_ALIAS_FLAG);
        dp.setColor(col);
        cv.drawCircle(lx, ly, 8f, dp);
        return b;
    }
}
