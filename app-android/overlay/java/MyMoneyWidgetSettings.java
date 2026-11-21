package it.robypet73.mymoneyportafogli;

import android.app.Activity;
import android.appwidget.AppWidgetManager;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.view.Gravity;
import android.widget.LinearLayout;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.ScrollView;
import android.widget.TextView;

/** Rotellina del widget: periodo del grafico (per ogni widget) e frequenza di aggiornamento dei prezzi (per tutti, predefinita 1 ora). */
public class MyMoneyWidgetSettings extends Activity {
    static final int[] FREQ = {15, 30, 60, 120, 360, 720, 1440};
    static final String[] FREQ_TESTO = {"Ogni 15 minuti", "Ogni 30 minuti", "Ogni ora (predefinito)", "Ogni 2 ore", "Ogni 6 ore", "Ogni 12 ore", "Una volta al giorno"};

    private TextView titolo(String s, int sopra) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(16);
        t.setPadding(0, sopra, 0, MyMoneyWidget.dp(this, 6));
        return t;
    }

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        setTitle("Impostazioni del widget");
        final int id = getIntent().getIntExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, AppWidgetManager.INVALID_APPWIDGET_ID);
        final SharedPreferences sp = getSharedPreferences(MyMoneyWidget.PREFS, 0);
        int p = MyMoneyWidget.dp(this, 20);
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setPadding(p, p, p, p);
        col.addView(titolo("Portafoglio mostrato", 0));
        LinearLayout riga = new LinearLayout(this);
        riga.setOrientation(LinearLayout.HORIZONTAL);
        riga.setGravity(Gravity.CENTER_VERTICAL);
        final TextView nome = new TextView(this);
        nome.setTextSize(15);
        nome.setGravity(Gravity.CENTER);
        final Button prec = new Button(this), succ = new Button(this);
        prec.setText("‹");
        succ.setText("›");
        final Runnable aggiorna = new Runnable() {
            @Override
            public void run() {
                String f = MyMoneyWidget.corrente(MyMoneyWidgetSettings.this, id);
                nome.setText(f == null ? "Nessun portafoglio: aprilo nell'app" : MyMoneyWidget.nomeDi(MyMoneyWidgetSettings.this, f));
                boolean piu = MyMoneyWidget.portafogli(MyMoneyWidgetSettings.this).size() > 1;
                prec.setEnabled(piu);
                succ.setEnabled(piu);
            }
        };
        View.OnClickListener vai = new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                MyMoneyWidget.sposta(MyMoneyWidgetSettings.this, id, v == succ ? 1 : -1);
                aggiorna.run();
                MyMoneyWidget.refreshAll(MyMoneyWidgetSettings.this);
            }
        };
        prec.setOnClickListener(vai);
        succ.setOnClickListener(vai);
        riga.addView(prec);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
        riga.addView(nome, lp);
        riga.addView(succ);
        aggiorna.run();
        col.addView(riga);
        col.addView(titolo("Periodo del grafico dei rendimenti", MyMoneyWidget.dp(this, 16)));
        String cur = MyMoneyWidget.periodo(this, id)[0];
        RadioGroup g = new RadioGroup(this);
        for (final String[] o : MyMoneyWidget.PERIODI) {
            RadioButton r = new RadioButton(this);
            r.setId(View.generateViewId());
            r.setText(o[1]);
            r.setChecked(o[0].equals(cur));
            r.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    sp.edit().putString("per_" + id, o[0]).apply();
                    MyMoneyWidget.refreshAll(MyMoneyWidgetSettings.this);
                }
            });
            g.addView(r);
        }
        col.addView(g);
        col.addView(titolo("Frequenza di aggiornamento dei prezzi", MyMoneyWidget.dp(this, 16)));
        int freq = MyMoneyWidget.freqMin(this);
        RadioGroup gf = new RadioGroup(this);
        for (int i = 0; i < FREQ.length; i++) {
            final int minuti = FREQ[i];
            RadioButton r = new RadioButton(this);
            r.setId(View.generateViewId());
            r.setText(FREQ_TESTO[i]);
            r.setChecked(minuti == freq);
            r.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    sp.edit().putInt("freq_min", minuti).apply();
                    MyMoneyWidget.scheduleWork(MyMoneyWidgetSettings.this, true);  // il lavoro in background riparte con la nuova frequenza
                    MyMoneyWidget.schedule(MyMoneyWidgetSettings.this);
                    MyMoneyWidget.refreshAsync(MyMoneyWidgetSettings.this, null);  // e un aggiornamento subito
                }
            });
            gf.addView(r);
        }
        col.addView(gf);
        TextView nota = new TextView(this);
        nota.setText("Android può ritardare gli aggiornamenti con il risparmio energetico; sotto i 15 minuti non si scende.");
        nota.setTextSize(12);
        nota.setPadding(0, MyMoneyWidget.dp(this, 8), 0, MyMoneyWidget.dp(this, 8));
        col.addView(nota);
        Button fatto = new Button(this);
        fatto.setText("Fatto");
        fatto.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                finish();
            }
        });
        col.addView(fatto);
        ScrollView sv = new ScrollView(this);
        sv.addView(col);
        setContentView(sv);
    }
}
