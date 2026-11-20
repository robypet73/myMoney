package it.robypet73.mymoneyportafogli;

import android.app.Activity;
import android.appwidget.AppWidgetManager;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.TextView;

/** Rotellina del widget: periodo del grafico dei rendimenti (per ogni widget). */
public class MyMoneyWidgetSettings extends Activity {
    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        setTitle("Grafico del widget");
        final int id = getIntent().getIntExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, AppWidgetManager.INVALID_APPWIDGET_ID);
        final SharedPreferences sp = getSharedPreferences(MyMoneyWidget.PREFS, 0);
        String cur = MyMoneyWidget.periodo(this, id)[0];
        int p = MyMoneyWidget.dp(this, 20);
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setPadding(p, p, p, p);
        TextView t = new TextView(this);
        t.setText("Periodo del grafico dei rendimenti");
        t.setTextSize(16);
        t.setPadding(0, 0, 0, MyMoneyWidget.dp(this, 10));
        col.addView(t);
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
                    finish();
                }
            });
            g.addView(r);
        }
        col.addView(g);
        setContentView(col);
    }
}
