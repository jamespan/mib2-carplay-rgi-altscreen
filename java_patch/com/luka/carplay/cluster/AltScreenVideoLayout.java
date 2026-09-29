/* Sport small-map alignment for AltScreen displayable 3.  The stock controller
 * positions only native-map planes 33/58; the KDK controller owns 98/101/102.
 * This class caches the OEM Layout offset and is applied only by ScreenModule's
 * persistent worker. Logo and reconnect phases always use the origin. */
package com.luka.carplay.cluster;

import com.luka.carplay.framework.Log;
import de.audi.atip.hmi.view.IDisplayManager;
import de.esolutions.hmi.widgets.audi.base.Layout;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;

public final class AltScreenVideoLayout {
    private static final Object LOCK = new Object();
    private static String tmpRoot = "/tmp"; // host-test seam
    private static boolean sportSmall;
    private static int offsetX, offsetY;
    private static IDisplayManager appliedManager;
    private static int appliedX, appliedY;
    private static String appliedPid, resetToken, lastError;
    private static boolean applied;

    private AltScreenVideoLayout() {}

    public static void updateLayout(Layout layout, boolean small) {
        if (layout == null) return;
        try {
            boolean sport = layout.getClass().getName().endsWith("LayoutMIB2HighB9Sport");
            int dx = layout.getIntegerConstant(80), dy = layout.getIntegerConstant(81);
            synchronized (LOCK) {
                // Reject nonsensical geometry; the CN B9 Sport layout supplies (-476, 0).
                sportSmall = sport && small && dx > -1440 && dx < 1440 && dy > -455 && dy < 455;
                offsetX = sportSmall ? dx : 0;
                offsetY = sportSmall ? dy : 0;
            }
        } catch (Throwable t) {
            synchronized (LOCK) { sportSmall = false; offsetX = offsetY = 0; }
        }
    }

    private static String read(String name, int limit) throws Exception {
        File f = new File(tmpRoot, name);
        if (!f.isFile()) return null;
        FileInputStream in = new FileInputStream(f);
        try {
            byte[] bytes = new byte[limit + 1];
            int n = 0;
            while (n < bytes.length) {
                int count = in.read(bytes, n, bytes.length - n);
                if (count < 0) break;
                if (count == 0) return null;
                n += count;
            }
            return n > limit ? null : new String(bytes, 0, n, "ISO-8859-1");
        } finally { in.close(); }
    }

    private static void write(String name, String text) throws Exception {
        FileOutputStream out = new FileOutputStream(new File(tmpRoot, name));
        try { out.write(text.getBytes("ISO-8859-1")); }
        finally { out.close(); }
    }

    private static String token(String value) {
        if (value == null) return null;
        value = value.trim();
        return value.length() == 0 || value.length() > 96 || value.indexOf('\n') >= 0
            || value.indexOf('\r') >= 0 ? null : value;
    }

    private static boolean digits(String value) {
        if (value == null || value.length() == 0) return false;
        for (int i = 0; i < value.length(); i++)
            if (value.charAt(i) < '0' || value.charAt(i) > '9') return false;
        return true;
    }

    /** Only a complete current-process video record permits a map translation.
     * Existence-only is deliberately insufficient: the same ready file starts at startup-logo. */
    private static String videoPid() throws Exception {
        if (!new File(tmpRoot, "mmi-mirror-active").isFile()) return null;
        String pid = token(read("MMI-Cockpit-Carplay.mirror.pid", 96));
        String ready = read("mmi-mirror-basevideo.ready", 512);
        if (!digits(pid) || ready == null || !ready.endsWith("\n")) return null;
        String record = "\n" + ready;
        if (record.indexOf("\nready=1\n") < 0 || record.indexOf("\nmode=direct-display\n") < 0
            || record.indexOf("\ndisplayable=3\n") < 0 || record.indexOf("\npid=" + pid + "\n") < 0)
            return null;
        return pid;
    }

    private static void position(IDisplayManager dm, int x, int y, String pid, boolean force)
            throws Exception {
        if (!force && applied && appliedManager == dm && appliedX == x && appliedY == y
                && (pid == null ? appliedPid == null : pid.equals(appliedPid))) return;
        // Publish before any possible nonzero DSI write. A following launcher must reset before
        // its first logo; if publication fails, do not risk a persistent untracked translation.
        if ((x != 0 || y != 0) && !new File(tmpRoot, "carplay-video-position.used").isFile())
            write("carplay-video-position.used", "displayable=3\n");
        dm.setPosition(3, 1, x, y);
        appliedManager = dm; appliedX = x; appliedY = y; appliedPid = pid; applied = true;
        Log.i("AltVideoLayout", "displayable=3 position=(" + x + "," + y + ") videoPid=" + pid);
    }

    /** Sole caller: ScreenModule worker, including while disconnected after its first session. */
    public static void reconcile(IDisplayManager dm, boolean connected) {
        if (dm == null) return;
        try {
            String request = token(read("carplay-video-reset.request", 96));
            if (request != null && (!request.equals(resetToken)
                    || !request.equals(token(read("carplay-video-reset.ack", 96))))) {
                position(dm, 0, 0, null, true);
                write("carplay-video-reset.ack", request + "\n");
                resetToken = request;
                lastError = null;
                return; // never reapply a previous process's marker in the reset iteration
            }
            String pid = connected ? videoPid() : null;
            int x = 0, y = 0;
            synchronized (LOCK) {
                if (pid != null && sportSmall) { x = offsetX; y = offsetY; }
            }
            position(dm, x, y, pid, false);
            lastError = null;
        } catch (Throwable t) {
            applied = false;
            String error = t.toString();
            if (!error.equals(lastError)) Log.w("AltVideoLayout", "position retry: " + error);
            lastError = error;
        }
    }
}
