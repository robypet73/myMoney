package it.robypet73.mymoney;

import android.app.AlarmManager;
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
import android.os.Build;
import android.os.PowerManager;
import android.text.SpannableStringBuilder;
import android.text.Spanned;
import android.text.style.ForegroundColorSpan;
import android.util.TypedValue;
import android.os.Bundle;
import android.view.View;
import android.widget.RemoteViews;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.text.NumberFormat;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import org.json.JSONArray;
import org.json.JSONObject;

/** Widget: valore, rendimento sull'investito, variazione di oggi, confronto col benchmark e andamento del portafoglio preferito. */
public class MyMoneyWidget extends AppWidgetProvider {
    static final String PREFS = "mymoney_widget";
    static final String KEY = "data";
    static final int UP = Color.parseColor("#1F9D6B");
    static final int DOWN = Color.parseColor("#D6453D");

    static final String TICK = "it.robypet73.mymoney.TICK";
    static final long EVERY = 5 * 60 * 1000L;

    @Override
    public void onUpdate(Context c, AppWidgetManager m, int[] ids) {
        for (int id : ids) draw(c, m, id);
        schedule(c);
        refreshAsync(c, null); // prezzi nuovi anche quando l'app è chiusa
    }

    @Override
    public void onEnabled(Context c) {
        schedule(c);
    }

    @Override
    public void onDisabled(Context c) {
        AlarmManager am = (AlarmManager) c.getSystemService(Context.ALARM_SERVICE);
        if (am != null) am.cancel(tickIntent(c));
    }

    @Override
    public void onReceive(Context c, Intent i) {
        if (TICK.equals(i.getAction())) {
            schedule(c);
            PowerManager pm = (PowerManager) c.getSystemService(Context.POWER_SERVICE);
            if (pm != null && !pm.isInteractive()) return; // schermo spento: nessuno guarda il widget, si risparmia batteria
            refreshAsync(c, goAsync());
            return;
        }
        super.onReceive(c, i);
    }

    static PendingIntent tickIntent(Context c) {
        Intent i = new Intent(c, MyMoneyWidget.class).setAction(TICK);
        return PendingIntent.getBroadcast(c, 1, i, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    /** Prossimo aggiornamento tra 5 minuti (Android può ritardarlo a telefono in standby o con il risparmio energetico). */
    static void schedule(Context c) {
        AlarmManager am = (AlarmManager) c.getSystemService(Context.ALARM_SERVICE);
        if (am == null) return;
        if (AppWidgetManager.getInstance(c).getAppWidgetIds(new ComponentName(c, MyMoneyWidget.class)).length == 0) return;
        long at = System.currentTimeMillis() + EVERY;
        try {
            if (Build.VERSION.SDK_INT < 31 || am.canScheduleExactAlarms()) am.setExactAndAllowWhileIdle(AlarmManager.RTC, at, tickIntent(c));
            else am.setAndAllowWhileIdle(AlarmManager.RTC, at, tickIntent(c));
        } catch (Exception e) {
            am.setAndAllowWhileIdle(AlarmManager.RTC, at, tickIntent(c));
        }
    }

    static void refreshAsync(final Context c, final PendingResult pr) {
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    refreshData(c);
                    refreshAll(c);
                } catch (Exception e) {
                    // rete assente: resta l'ultimo dato
                } finally {
                    if (pr != null) pr.finish();
                }
            }
        }).start();
    }

    static String http(String u) throws Exception {
        HttpURLConnection h = (HttpURLConnection) new URL(u).openConnection();
        h.setConnectTimeout(6000);
        h.setReadTimeout(8000);
        h.setRequestProperty("User-Agent", "Mozilla/5.0 (compatible; myMoney/1.0)");
        InputStream in = h.getInputStream();
        try {
            ByteArrayOutputStream o = new ByteArrayOutputStream();
            byte[] b = new byte[8192];
            int n;
            while ((n = in.read(b)) > 0) o.write(b, 0, n);
            return o.toString("UTF-8");
        } finally {
            in.close();
            h.disconnect();
        }
    }

    /** Ultimo prezzo di Yahoo Finance in euro (come la pagina: valute estere convertite al cambio del momento). */
    static Double eurPrice(String sym, Map<String, Double> fx) {
        try {
            JSONObject meta = new JSONObject(http("https://query1.finance.yahoo.com/v8/finance/chart/" + java.net.URLEncoder.encode(sym, "UTF-8") + "?range=1d&interval=1d")).getJSONObject("chart").getJSONArray("result").getJSONObject(0).getJSONObject("meta");
            double p = meta.getDouble("regularMarketPrice");
            String cur = meta.optString("currency", "EUR");
            if (cur.equals("EUR")) return p;
            String base = cur.equals("GBp") ? "GBP" : cur;
            Double rate = fx.get(base);
            if (rate == null) {
                rate = new JSONObject(http("https://query1.finance.yahoo.com/v8/finance/chart/EUR" + base + "%3DX?range=1d&interval=1d")).getJSONObject("chart").getJSONArray("result").getJSONObject(0).getJSONObject("meta").getDouble("regularMarketPrice");
                fx.put(base, rate);
            }
            return p / (rate / (cur.equals("GBp") ? 0.01 : 1.0));
        } catch (Exception e) {
            return null;
        }
    }

    /** Ricalcola valore, rendimento e variazione di oggi con i prezzi attuali delle posizioni salvate dalla pagina. */
    static void refreshData(Context c) throws Exception {
        android.content.SharedPreferences sp = c.getSharedPreferences(PREFS, 0);
        String raw = sp.getString(KEY, null);
        if (raw == null) return;
        JSONObject d = new JSONObject(raw);
        JSONArray pos = d.optJSONArray("pos");
        if (pos == null || pos.length() == 0) return;
        Map<String, Double> px = new HashMap<String, Double>(), fx = new HashMap<String, Double>();
        double val = 0;
        boolean any = false;
        for (int i = 0; i < pos.length(); i++) {
            JSONObject p = pos.getJSONObject(i);
            double price = p.optDouble("p", 0);
            String s = p.optString("s", "");
            if (!s.isEmpty()) {
                Double e = px.get(s);
                if (e == null) {
                    e = eurPrice(s, fx);
                    if (e != null) px.put(s, e);
                }
                if (e != null) {
                    price = e;
                    p.put("p", e);
                    any = true;
                }
            }
            val += p.getDouble("q") * price;
        }
        if (!any) return;
        double cost = d.optDouble("cost", 0), base = d.optDouble("dayBase", 0), flow = d.optDouble("flowToday", 0);
        d.put("val", Math.round(val * 100) / 100.0);
        if (cost > 0) {
            d.put("roi", val / cost - 1);
            d.put("profit", Math.round((val - cost) * 100) / 100.0);
        }
        if (base > 0) d.put("day", (val - flow) / base - 1);
        JSONArray ser = d.optJSONArray("series");
        if (ser != null && ser.length() > 0) ser.put(ser.length() - 1, val);
        d.put("at", System.currentTimeMillis());
        sp.edit().putString(KEY, d.toString()).apply();
    }

    @Override
    public void onAppWidgetOptionsChanged(Context c, AppWidgetManager m, int id, Bundle o) {
        draw(c, m, id);
    }

    static int dp(Context c, float v) {
        return Math.round(TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, c.getResources().getDisplayMetrics()));
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
        Bundle o = m.getAppWidgetOptions(id);
        int h = o.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_HEIGHT, 110), w = o.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH, 250);
        if (h <= 0) h = 110;
        if (w <= 0) w = 250;
        // contenuto in base allo spazio: più basso è il widget, meno righe (nessun testo tagliato in basso)
        boolean tiny = h < 64, low = h < 100, mid = h < 140;
        int pad = tiny ? 6 : low ? 8 : 10;
        v.setViewPadding(R.id.w_root, dp(c, 14), dp(c, pad), dp(c, 14), dp(c, pad));
        v.setViewVisibility(R.id.w_row1, low ? View.GONE : View.VISIBLE);
        v.setViewVisibility(R.id.w_row2, tiny ? View.GONE : View.VISIBLE);
        v.setViewVisibility(R.id.w_row3, mid ? View.GONE : View.VISIBLE);
        v.setViewVisibility(R.id.w_roi_l, w < 200 ? View.GONE : View.VISIBLE);
        v.setViewVisibility(R.id.w_upd, w < 200 ? View.GONE : View.VISIBLE);
        v.setTextViewTextSize(R.id.w_value, TypedValue.COMPLEX_UNIT_SP, tiny ? 18 : low ? 22 : 24);
        boolean showChart = h >= 115;
        Intent open = c.getPackageManager().getLaunchIntentForPackage(c.getPackageName());
        if (open != null) {
            v.setOnClickPendingIntent(R.id.w_root, PendingIntent.getActivity(c, 0, open, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE));
        }
        String raw = c.getSharedPreferences(PREFS, 0).getString(KEY, null);
        try {
            JSONObject d = new JSONObject(raw);
            double val = d.getDouble("val");
            v.setTextViewText(R.id.w_name, d.optString("name", "Portafoglio"));
            String vt = eur(val);
            if (tiny && !d.isNull("roi")) {
                double r0 = d.getDouble("roi");
                SpannableStringBuilder sb = new SpannableStringBuilder(vt + "  " + pct(r0));
                sb.setSpan(new ForegroundColorSpan(r0 >= 0 ? UP : DOWN), vt.length() + 2, sb.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
                v.setTextViewText(R.id.w_value, sb);
            } else {
                v.setTextViewText(R.id.w_value, vt);
            }
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
            if (chart != null && showChart) {
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
