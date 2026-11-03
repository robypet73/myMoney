package it.robypet73.mymoney;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.provider.DocumentsContract;
import androidx.activity.result.ActivityResult;
import androidx.documentfile.provider.DocumentFile;
import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.ActivityCallback;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;

/**
 * Cartella dei portafogli scelta con il selettore di cartelle di Android (Storage Access Framework): può stare sulla memoria del telefono
 * oppure su Google Drive (l'app Drive compare tra le posizioni del selettore). I file sono quelli di index.html: un JSON per portafoglio.
 */
@CapacitorPlugin(name = "MyMoneyFolder")
public class MyMoneyFolderPlugin extends Plugin {
    static final String PREFS = "mymoney_folder";
    static final String KEY = "tree";

    private String tree() {
        return getContext().getSharedPreferences(PREFS, 0).getString(KEY, null);
    }

    private DocumentFile root() {
        String t = tree();
        if (t == null) return null;
        DocumentFile r = DocumentFile.fromTreeUri(getContext(), Uri.parse(t));
        return r != null && r.canRead() && r.canWrite() ? r : null;
    }

    private String read(Uri u) throws IOException {
        InputStream in = getContext().getContentResolver().openInputStream(u);
        if (in == null) throw new IOException("file non leggibile");
        try {
            ByteArrayOutputStream o = new ByteArrayOutputStream();
            byte[] b = new byte[8192];
            int n;
            while ((n = in.read(b)) > 0) o.write(b, 0, n);
            return o.toString("UTF-8");
        } finally {
            in.close();
        }
    }

    private void write(DocumentFile dir, String name, String text) throws IOException {
        if (name.indexOf('/') >= 0 || !name.endsWith(".json")) throw new IOException("nome non valido: " + name);
        DocumentFile f = dir.findFile(name);
        if (f != null) {
            if (text.equals(read(f.getUri()))) return; // invariato: non si tocca (Drive non risincronizza)
        } else {
            f = dir.createFile("application/json", name);
            if (f == null) throw new IOException("creazione non riuscita: " + name);
        }
        OutputStream out = getContext().getContentResolver().openOutputStream(f.getUri(), "wt");
        if (out == null) throw new IOException("file non scrivibile: " + name);
        try {
            out.write(text.getBytes(StandardCharsets.UTF_8));
        } finally {
            out.close();
        }
    }

    @PluginMethod
    public void info(PluginCall call) {
        DocumentFile r = root();
        JSObject o = new JSObject();
        o.put("uri", r == null ? null : tree());
        o.put("label", r == null ? null : (r.getName() == null ? "cartella" : r.getName()));
        call.resolve(o);
    }

    @PluginMethod
    public void pick(PluginCall call) {
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION | Intent.FLAG_GRANT_PREFIX_URI_PERMISSION);
        if (Boolean.TRUE.equals(call.getBoolean("drive", false)) && Build.VERSION.SDK_INT >= 26) {
            try { // suggerimento: il selettore si apre su Google Drive (se non c'è, si apre dove vuole)
                i.putExtra(DocumentsContract.EXTRA_INITIAL_URI, DocumentsContract.buildDocumentUri("com.google.android.apps.docs.storage", "root"));
            } catch (Exception e) {
                // ignorato
            }
        }
        startActivityForResult(call, i, "pickResult");
    }

    @ActivityCallback
    private void pickResult(PluginCall call, ActivityResult result) {
        if (call == null) return;
        if (result.getResultCode() != Activity.RESULT_OK || result.getData() == null || result.getData().getData() == null) {
            call.resolve(new JSObject()); // annullato
            return;
        }
        Uri u = result.getData().getData();
        getContext().getContentResolver().takePersistableUriPermission(u, Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
        getContext().getSharedPreferences(PREFS, 0).edit().putString(KEY, u.toString()).apply();
        info(call);
    }

    @PluginMethod
    public void forget(PluginCall call) {
        getContext().getSharedPreferences(PREFS, 0).edit().remove(KEY).apply();
        call.resolve();
    }

    @PluginMethod
    public void list(PluginCall call) {
        DocumentFile r = root();
        if (r == null) {
            call.reject("cartella non collegata");
            return;
        }
        try {
            JSArray files = new JSArray();
            for (DocumentFile f : r.listFiles()) {
                String n = f.getName();
                if (f.isFile() && n != null && n.endsWith(".json")) {
                    JSObject o = new JSObject();
                    o.put("name", n);
                    o.put("text", read(f.getUri()));
                    o.put("mtime", f.lastModified());
                    files.put(o);
                }
            }
            JSObject res = new JSObject();
            res.put("files", files);
            call.resolve(res);
        } catch (Exception e) {
            call.reject(String.valueOf(e.getMessage()));
        }
    }

    /** write: [{name, text}] solo se cambia; trash: [name] in «_eliminati»; remove: [name] (portafogli rinominati). */
    @PluginMethod
    public void apply(PluginCall call) {
        DocumentFile r = root();
        if (r == null) {
            call.reject("cartella non collegata");
            return;
        }
        try {
            JSArray w = call.getArray("write");
            if (w != null) {
                for (int i = 0; i < w.length(); i++) {
                    JSONObject o = w.getJSONObject(i);
                    write(r, o.getString("name"), o.getString("text"));
                }
            }
            JSArray t = call.getArray("trash");
            if (t != null) {
                for (int i = 0; i < t.length(); i++) {
                    String n = t.getString(i);
                    DocumentFile f = r.findFile(n);
                    if (f == null) continue;
                    DocumentFile dir = r.findFile("_eliminati");
                    if (dir == null) dir = r.createDirectory("_eliminati");
                    if (dir == null) throw new IOException("cartella _eliminati non creata");
                    String nm = n;
                    if (dir.findFile(nm) != null) nm = n.substring(0, n.length() - 5) + " (" + System.currentTimeMillis() + ").json";
                    write(dir, nm, read(f.getUri()));
                    f.delete();
                }
            }
            JSArray d = call.getArray("remove");
            if (d != null) {
                for (int i = 0; i < d.length(); i++) {
                    DocumentFile f = r.findFile(d.getString(i));
                    if (f != null) f.delete();
                }
            }
            call.resolve();
        } catch (Exception e) {
            call.reject(String.valueOf(e.getMessage()));
        }
    }
}
