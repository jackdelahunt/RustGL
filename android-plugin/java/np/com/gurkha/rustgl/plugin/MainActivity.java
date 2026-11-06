package np.com.gurkha.rustgl.plugin;

import android.app.Activity;
import android.os.Bundle;
import android.view.Gravity;
import android.widget.ScrollView;
import android.widget.TextView;

/**
 * The information screen of the RustGL renderer plugin.
 *
 * It exists because FCL and Zalith Launcher 2 find renderer plugins with
 * PackageManager.queryIntentActivities(Intent.ACTION_MAIN): a plugin package
 * without an exported MAIN activity is invisible to them. There is nothing to
 * configure here - the renderer is selected inside the launcher.
 */
public final class MainActivity extends Activity {

    private static final String INFO =
            "RustGL renderer plugin (Gurkha build)\n"
            + "Package: np.com.gurkha.rustgl.plugin\n"
            + "Library: librust_gl.so (arm64-v8a, armeabi-v7a, x86, x86_64)\n"
            + "\n"
            + "This package is a renderer, not a game launcher. To use it:\n"
            + "\n"
            + "1. Open your launcher (Zalith, Zalith 2, Gurkha, FCL, Pojav-based forks).\n"
            + "2. Fully restart it once after installing this package.\n"
            + "3. Open the Minecraft version settings and pick \"RustGL (Gurkha build)\"\n"
            + "   as the renderer. Launchers that read the older v1 plugin metadata show\n"
            + "   it as \"RustGL (Gurkha build) - OpenGL 4.5 surface on OpenGL ES 3\n"
            + "   [v1 plugin API]\".\n"
            + "4. Start the game. If it crashes, switch back to your previous renderer.\n"
            + "\n"
            + "RustGL is a compatibility layer: the game talks desktop OpenGL to it and\n"
            + "it translates to OpenGL ES 3 for the device driver. Coverage is not\n"
            + "complete - it depends on the Minecraft version, the mods, and the GPU\n"
            + "driver. It needs real OpenGL ES 3 support and Android 8.0 (API 26) or\n"
            + "newer.\n"
            + "\n"
            + "This plugin has no settings of its own, no permissions, and no network\n"
            + "access. Build, source and limitations: see the release page of\n"
            + "kushaladhikari982648-lgtm/RustGL-for-Gurkha-launcher.";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        TextView text = new TextView(this);
        text.setText(INFO);
        text.setTextIsSelectable(true);
        text.setGravity(Gravity.START);
        int pad = (int) (24 * getResources().getDisplayMetrics().density);
        text.setPadding(pad, pad, pad, pad);

        ScrollView scroll = new ScrollView(this);
        scroll.addView(text);
        setContentView(scroll);
    }
}
