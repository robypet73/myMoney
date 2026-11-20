package it.robypet73.mymoneyportafogli;

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
import android.net.Uri;
import android.os.Build;
import androidx.work.Constraints;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;
import java.util.concurrent.TimeUnit;
import androidx.core.content.ContextCompat;
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

/** Widget: valore, rendita, variazione di oggi e grafico (con assi) del portafoglio aperto; la rotellina apre la scelta del periodo del grafico. */
public class MyMoneyWidget extends AppWidgetProvider {
    static final String PREFS = "mymoney_widget";
    static final String KEY = "data";
    static final int UP = Color.parseColor("#1F9D6B");
    static final int DOWN = Color.parseColor("#D6453D");

    static final String TICK = "it.robypet73.mymoneyportafogli.TICK";
    static final long EVERY = 60 * 60 * 1000L;  // aggiornamento automatico ogni ora

    @Override
    public void onUpdate(Context c, AppWidgetManager m, int[] ids) {
        for (int id : ids) draw(c, m, id);
        schedule(c);
        refreshAsync(c, null); // prezzi nuovi anche quando l'app è chiusa
    }

    @Override
    public void onEnabled(Context c) {
        schedule(c);
        scheduleWork(c);
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

    static Constraints rete() {
        return new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build();
    }

    /** Aggiornamento automatico ogni ora in background (WorkManager: parte anche con l'app chiusa, dopo il riavvio e con il telefono in standby). */
    static void scheduleWork(Context c) {
        try {
            WorkManager.getInstance(c).enqueueUniquePeriodicWork("mymoney-widget", ExistingPeriodicWorkPolicy.KEEP,
                    new PeriodicWorkRequest.Builder(MyMoneyWidgetWorker.class, 60, TimeUnit.MINUTES).setConstraints(rete()).build());
        } catch (Exception e) {
            // WorkManager non disponibile: resta l'allarme
        }
    }

    /** Un aggiornamento subito, in background. */
    static void refreshAsync(final Context c, final PendingResult pr) {
        try {
            scheduleWork(c);
            WorkManager.getInstance(c).enqueue(new OneTimeWorkRequest.Builder(MyMoneyWidgetWorker.class).setConstraints(rete()).build());
        } catch (Exception e) {
            // rete assente o WorkManager non disponibile
        } finally {
            if (pr != null) pr.finish();
        }
    }

    static String http(String u) throws Exception {
        HttpURLConnection h = (HttpURLConnection) new URL(u).openConnection();
        h.setConnectTimeout(6000);
        h.setReadTimeout(8000);
        h.setRequestProperty("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36");
        h.setRequestProperty("Accept-Language", "en-GB");
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

    /** Ultimo prezzo in euro di un titolo da justETF (stesso servizio della pagina). */
    static Double eurPrice(String isin) {
        try {
            SimpleDateFormat f = new SimpleDateFormat("yyyy-MM-dd", Locale.US);
            Date now = new Date();
            String url = "https://www.justetf.com/api/etfs/" + isin + "/performance-chart?locale=en&currency=EUR&valuesType=MARKET_VALUE&reduceData=false&includeDividends=false&features=DIVIDENDS&dateFrom="
                    + f.format(new Date(now.getTime() - 8L * 24 * 3600 * 1000)) + "&dateTo=" + f.format(now);
            JSONArray s = new JSONObject(http(url)).optJSONArray("series");
            if (s == null || s.length() == 0) return null;
            return s.getJSONObject(s.length() - 1).getJSONObject("value").getDouble("raw");
        } catch (Exception e) {
            return null;
        }
    }

    /** Ricalcola valore e rendita con i prezzi attuali delle posizioni salvate dalla pagina (anche con l'app chiusa). */
    static void refreshData(Context c) throws Exception {
        android.content.SharedPreferences sp = c.getSharedPreferences(PREFS, 0);
        String raw = sp.getString(KEY, null);
        if (raw == null) return;
        JSONObject d = new JSONObject(raw);
        JSONArray pos = d.optJSONArray("pos");
        if (pos == null || pos.length() == 0) return;
        double val = 0;
        boolean any = false;
        for (int i = 0; i < pos.length(); i++) {
            JSONObject p = pos.getJSONObject(i);
            double price = p.optDouble("p", 0);
            String isin = p.optString("isin", "");
            if (!isin.isEmpty()) {
                Double e = eurPrice(isin);
                if (e != null) {
                    price = e;
                    p.put("p", e);
                    any = true;
                }
            }
            val += p.getDouble("q") * price;
        }
        if (!any) return;
        d.put("val", Math.round(val * 100) / 100.0);
        JSONArray vs = d.optJSONArray("vs"), ds = d.optJSONArray("ds");
        if (vs != null && ds != null && vs.length() > 0 && vs.length() == ds.length()) {
            String today = new SimpleDateFormat("yyyy-MM-dd", Locale.US).format(new Date());
            if (ds.getString(ds.length() - 1).compareTo(today) < 0) {
                ds.put(today);
                vs.put(val);
            } else {
                vs.put(vs.length() - 1, val);
            }
        }
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

    static final String[][] PERIODI = {{"1m", "1 mese", "31"}, {"3m", "3 mesi", "92"}, {"6m", "6 mesi", "183"}, {"1a", "1 anno", "365"}, {"3a", "3 anni", "1096"}, {"5a", "5 anni", "1827"}, {"max", "Tutto lo storico", "0"}};

    static String[] periodo(Context c, int id) {
        String k = c.getSharedPreferences(PREFS, 0).getString("per_" + id, "1a");
        for (String[] p : PERIODI) if (p[0].equals(k)) return p;
        return PERIODI[3];
    }

    static long giorni(String iso) throws Exception {
        SimpleDateFormat f = new SimpleDateFormat("yyyy-MM-dd", Locale.US);
        f.setTimeZone(java.util.TimeZone.getTimeZone("UTC"));
        return f.parse(iso).getTime() / 86400000L;
    }

    static String compatto(double v, boolean fine) {
        if (Math.abs(v) >= 1000) return String.format(Locale.ITALY, fine ? "%.2fk" : "%.1fk", v / 1000);
        return String.format(Locale.ITALY, "%.0f", v);
    }

    /** Rotellina delle impostazioni: ingranaggio disegnato a mano (nessuna risorsa grafica da mantenere). */
    static Bitmap gear(int size, int col) {
        Bitmap b = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888);
        Canvas cv = new Canvas(b);
        float r = size / 2f;
        Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
        p.setColor(col);
        p.setStyle(Paint.Style.FILL);
        for (int i = 0; i < 8; i++) {
            cv.save();
            cv.rotate(i * 45f, r, r);
            cv.drawRect(r - size * 0.09f, size * 0.03f, r + size * 0.09f, size * 0.30f, p);
            cv.restore();
        }
        cv.drawCircle(r, r, size * 0.34f, p);
        Paint h = new Paint(Paint.ANTI_ALIAS_FLAG);
        h.setXfermode(new android.graphics.PorterDuffXfermode(android.graphics.PorterDuff.Mode.CLEAR));
        cv.drawCircle(r, r, size * 0.14f, h);
        return b;
    }

    static void draw(Context c, AppWidgetManager m, int id) {
        RemoteViews v = new RemoteViews(c.getPackageName(), R.layout.widget_mymoney);
        Bundle o = m.getAppWidgetOptions(id);
        boolean vert = c.getResources().getConfiguration().orientation != android.content.res.Configuration.ORIENTATION_LANDSCAPE;  // in verticale la misura giusta è l'altezza massima e la larghezza minima
        int h = o.getInt(vert ? AppWidgetManager.OPTION_APPWIDGET_MAX_HEIGHT : AppWidgetManager.OPTION_APPWIDGET_MIN_HEIGHT, 110), w = o.getInt(vert ? AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH : AppWidgetManager.OPTION_APPWIDGET_MAX_WIDTH, 250);
        if (h <= 0) h = 110;
        if (w <= 0) w = 250;
        // contenuto in base allo spazio: più basso è il widget, meno righe (nessun testo tagliato in basso)
        boolean tiny = h < 64, low = h < 100, mid = h < 140;
        int pad = tiny ? 6 : low ? 8 : 10;
        v.setViewPadding(R.id.w_col, dp(c, 14), dp(c, pad), dp(c, 14), dp(c, pad));
        v.setViewVisibility(R.id.w_row1, low ? View.GONE : View.VISIBLE);
        v.setViewVisibility(R.id.w_row2, tiny ? View.GONE : View.VISIBLE);
        v.setViewVisibility(R.id.w_row3, mid ? View.GONE : View.VISIBLE);
        v.setViewVisibility(R.id.w_roi_l, w < 200 ? View.GONE : View.VISIBLE);
        v.setTextViewTextSize(R.id.w_value, TypedValue.COMPLEX_UNIT_SP, tiny ? 18 : low ? 22 : 24);
        boolean showChart = h >= 115;
        Intent open = c.getPackageManager().getLaunchIntentForPackage(c.getPackageName());
        if (open != null) {
            v.setOnClickPendingIntent(R.id.w_col, PendingIntent.getActivity(c, 0, open, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE));
        }
        v.setImageViewBitmap(R.id.w_gear, gear(dp(c, 18), ContextCompat.getColor(c, R.color.widget_sub)));
        Intent set = new Intent(c, MyMoneyWidgetSettings.class).putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, id).setData(Uri.parse("mymoney://widget/" + id));
        v.setOnClickPendingIntent(R.id.w_gear, PendingIntent.getActivity(c, id, set, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE));
        String raw = c.getSharedPreferences(PREFS, 0).getString(KEY, null);
        try {
            JSONObject d = new JSONObject(raw);
            double val = d.getDouble("val"), cost = d.optDouble("cost", 0);
            String[] per = periodo(c, id);
            JSONArray ds = d.optJSONArray("ds"), vs = d.optJSONArray("vs");
            int n = ds == null || vs == null ? 0 : Math.min(ds.length(), vs.length());
            // la parte di serie nel periodo scelto
            int from = 0;
            if (n > 1 && !per[0].equals("max")) {
                long cut = giorni(ds.getString(n - 1)) - Long.parseLong(per[2]);
                while (from < n - 2 && giorni(ds.getString(from)) < cut) from++;
            }
            String[] dd = new String[Math.max(0, n - from)];
            double[] ss = new double[dd.length];
            for (int i = 0; i < dd.length; i++) {
                dd[i] = ds.getString(from + i);
                ss[i] = vs.getDouble(from + i);
            }
            v.setTextViewText(R.id.w_name, d.optString("name", "Portafoglio") + " · " + per[1]);
            String vt = eur(val);
            boolean hasRoi = cost > 0 || ss.length >= 2;
            double roi = cost > 0 ? val / cost - 1 : ss.length >= 2 && ss[0] > 0 ? val / ss[0] - 1 : 0;
            double profit = cost > 0 ? val - cost : ss.length >= 2 ? val - ss[0] : 0;
            if (tiny && hasRoi) {
                SpannableStringBuilder sb = new SpannableStringBuilder(vt + "  " + pct(roi));
                sb.setSpan(new ForegroundColorSpan(roi >= 0 ? UP : DOWN), vt.length() + 2, sb.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
                v.setTextViewText(R.id.w_value, sb);
            } else {
                v.setTextViewText(R.id.w_value, vt);
            }
            if (hasRoi) {
                v.setTextViewText(R.id.w_roi, pct(roi) + "  " + (profit >= 0 ? "+" : "") + eur(profit));
                v.setTextColor(R.id.w_roi, roi >= 0 ? UP : DOWN);
                v.setTextViewText(R.id.w_roi_l, cost > 0 ? "sull'investito" : "in " + per[1]);
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
            long at = d.optLong("at", 0);
            String agg = "";
            if (at > 0) {
                boolean oggi = new SimpleDateFormat("yyyyMMdd", Locale.ITALY).format(new Date(at)).equals(new SimpleDateFormat("yyyyMMdd", Locale.ITALY).format(new Date()));
                agg = "agg. " + new SimpleDateFormat(oggi ? "HH:mm" : "dd/MM HH:mm", Locale.ITALY).format(new Date(at));
            }
            v.setTextViewText(R.id.w_agg, agg);
            v.setViewVisibility(R.id.w_agg, tiny ? View.GONE : View.VISIBLE);
            if (showChart && ss.length >= 2) {
                float dens = c.getResources().getDisplayMetrics().density;
                int chartH = Math.round((h - 2 * pad - (low ? 0 : 16) - 32 - (tiny ? 0 : 20) - (mid ? 0 : 18) - 12 - 8) * dens);
                int wpx = Math.round((w - 28) * dens);
                chartH = Math.max(Math.round(44 * dens), Math.min(Math.round(300 * dens), chartH));
                wpx = Math.max(Math.round(120 * dens), Math.min(1300, wpx));
                Bitmap chart = chart(c, dd, ss, ss[ss.length - 1] >= ss[0], wpx, chartH);
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
            v.setTextViewText(R.id.w_agg, "");
            v.setViewVisibility(R.id.w_chart, View.GONE);
        }
        m.updateAppWidget(id, v);
    }

    /** Andamento del valore con assi minuscoli: valori a sinistra (massimo, metà, minimo) e mesi (o anni) in basso. */
    static Bitmap chart(Context c, String[] ds, double[] s, boolean up, int W, int H) throws Exception {
        Bitmap b = Bitmap.createBitmap(W, H, Bitmap.Config.ARGB_8888);
        Canvas cv = new Canvas(b);
        int sub = ContextCompat.getColor(c, R.color.widget_sub);
        float ts = dp(c, 6.5f);
        Paint tp = new Paint(Paint.ANTI_ALIAS_FLAG);
        tp.setTextSize(ts);
        tp.setColor(sub);
        double mn = Double.MAX_VALUE, mx = -Double.MAX_VALUE;
        for (double x : s) {
            mn = Math.min(mn, x);
            mx = Math.max(mx, x);
        }
        if (mx - mn < 1e-9) mx = mn + 1;
        boolean fine = mx - mn < 600 && mx >= 1000;
        float left = tp.measureText(compatto(mx, fine) + "0") + dp(c, 3), top = ts * 0.7f, bottom = ts * 1.7f, right = dp(c, 3);
        float x0 = left, x1 = W - right, y0 = top, y1 = H - bottom;
        long t0 = giorni(ds[0]), t1 = giorni(ds[ds.length - 1]);
        if (t1 <= t0) t1 = t0 + 1;
        int col = up ? UP : DOWN;
        // linee guida e valori dell'asse y
        Paint gp = new Paint(Paint.ANTI_ALIAS_FLAG);
        gp.setColor((sub & 0x00FFFFFF) | 0x33000000);
        gp.setStrokeWidth(1f);
        for (int k = 0; k < 3; k++) {
            double val = mn + (mx - mn) * k / 2.0;
            float y = (float) (y1 - (y1 - y0) * (val - mn) / (mx - mn));
            cv.drawLine(x0, y, x1, y, gp);
            String lab = compatto(val, fine);
            cv.drawText(lab, left - dp(c, 2) - tp.measureText(lab), Math.min(y + ts * 0.35f, y1 + ts * 0.35f), tp);
        }
        // asse x: giorni (periodo breve), mesi (fino a circa un anno) o anni
        long span = t1 - t0;
        java.util.ArrayList<float[]> pos = new java.util.ArrayList<float[]>();
        java.util.ArrayList<String> lab = new java.util.ArrayList<String>();
        SimpleDateFormat fm = new SimpleDateFormat(span <= 45 ? "dd/MM" : span <= 420 ? "MMM" : "yyyy", Locale.ITALY);
        fm.setTimeZone(java.util.TimeZone.getTimeZone("UTC"));
        SimpleDateFormat fi = new SimpleDateFormat("yyyy-MM-dd", Locale.US);
        if (span <= 45) {
            for (int k = 0; k < 4; k++) {
                long t = t0 + Math.round(span * k / 3.0);
                pos.add(new float[]{(float) (x0 + (x1 - x0) * (t - t0) / (double) span)});
                lab.add(fm.format(new Date(t * 86400000L)));
            }
        } else {
            String prev = "";
            for (int i = 0; i < ds.length; i++) {
                String key = span <= 420 ? ds[i].substring(0, 7) : ds[i].substring(0, 4);
                if (key.equals(prev)) continue;
                boolean first = prev.isEmpty();
                prev = key;
                if (first && ds[i].substring(8).compareTo("12") > 0) continue; // il primo mese è già a metà: niente etichetta
                long t = giorni(ds[i]);
                pos.add(new float[]{(float) (x0 + (x1 - x0) * (t - t0) / (double) span)});
                lab.add(fm.format(new Date(t * 86400000L)));
            }
            // troppe etichette: se ne tiene una ogni tanto
            int step = Math.max(1, (int) Math.ceil(lab.size() / 7.0));
            if (step > 1) {
                java.util.ArrayList<float[]> p2 = new java.util.ArrayList<float[]>();
                java.util.ArrayList<String> l2 = new java.util.ArrayList<String>();
                for (int i = 0; i < lab.size(); i += step) {
                    p2.add(pos.get(i));
                    l2.add(lab.get(i));
                }
                pos = p2;
                lab = l2;
            }
        }
        for (int i = 0; i < lab.size(); i++) {
            float w = tp.measureText(lab.get(i)), x = Math.max(x0, Math.min(x1 - w, pos.get(i)[0] - w / 2));
            cv.drawText(lab.get(i), x, H - ts * 0.3f, tp);
        }
        // linea e area
        Path line = new Path(), fill = new Path();
        float lx = 0, ly = 0;
        for (int i = 0; i < s.length; i++) {
            float x = (float) (x0 + (x1 - x0) * (giorni(ds[i]) - t0) / (double) (t1 - t0));
            float y = (float) (y0 + (y1 - y0) * (1 - (s[i] - mn) / (mx - mn)));
            if (i == 0) {
                line.moveTo(x, y);
                fill.moveTo(x, y1);
                fill.lineTo(x, y);
            } else {
                line.lineTo(x, y);
                fill.lineTo(x, y);
            }
            lx = x;
            ly = y;
        }
        fill.lineTo(lx, y1);
        fill.close();
        Paint fp = new Paint(Paint.ANTI_ALIAS_FLAG);
        fp.setStyle(Paint.Style.FILL);
        fp.setShader(new LinearGradient(0, y0, 0, y1, (col & 0x00FFFFFF) | 0x55000000, (col & 0x00FFFFFF), Shader.TileMode.CLAMP));
        cv.drawPath(fill, fp);
        Paint lp = new Paint(Paint.ANTI_ALIAS_FLAG);
        lp.setStyle(Paint.Style.STROKE);
        lp.setStrokeWidth(dp(c, 1.6f));
        lp.setStrokeJoin(Paint.Join.ROUND);
        lp.setStrokeCap(Paint.Cap.ROUND);
        lp.setColor(col);
        cv.drawPath(line, lp);
        Paint dpnt = new Paint(Paint.ANTI_ALIAS_FLAG);
        dpnt.setColor(col);
        cv.drawCircle(lx, ly, dp(c, 2.5f), dpnt);
        return b;
    }
}
