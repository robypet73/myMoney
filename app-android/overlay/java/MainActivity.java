package it.robypet73.mymoneyportafogli;

import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(MyMoneyWidgetPlugin.class);  // la pagina passa al widget valore, rendita e andamento
        registerPlugin(MyMoneyFolderPlugin.class);  // cartella dei portafogli scelta con il selettore di Android (telefono o Google Drive)
        super.onCreate(savedInstanceState);
    }
}
