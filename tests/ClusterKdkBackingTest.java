import com.luka.carplay.core.ScreenModule;
import com.luka.carplay.framework.Log;
import de.audi.atip.hmi.event.ATIPEventListener;
import de.audi.atip.hmi.event.ModelUpdateEvent;
import de.audi.atip.hmi.intercommunication.NaviMoKoKDKConstants;
import de.audi.tghu.fwhmi.IDisplayManagerKombiControl;
import de.esolutions.hmi.widgets.audi.base.AbstractWidget;
import de.esolutions.hmi.widgets.audi.base.Layout;
import de.esolutions.hmi.widgets.audi.evo.high.LayoutMIB2HighB9;
import de.esolutions.hmi.widgets.audi.evo.high.LayoutMIB2HighB9Sport;
import de.esolutions.hmi.widgets.audi.evo.high.widgets.CombiMapController;
import java.lang.reflect.*;
import java.util.*;
import sun.misc.Unsafe;

/** Real CN model event and layouts through the stock KDK writer, before CarPlay reapply.
 * Record every backing write: checking only final opacity could miss a gray flash. */
public final class ClusterKdkBackingTest implements InvocationHandler {
    private final List writes = new ArrayList();

    private static void check(boolean ok, String message) {
        if (!ok) throw new AssertionError(message);
    }

    private static Object defaultValue(Class type) {
        if (type == Boolean.TYPE) return Boolean.FALSE;
        if (type == Byte.TYPE) return Byte.valueOf((byte)0);
        if (type == Short.TYPE) return Short.valueOf((short)0);
        if (type == Integer.TYPE) return Integer.valueOf(0);
        if (type == Long.TYPE) return Long.valueOf(0);
        if (type == Float.TYPE) return Float.valueOf(0);
        if (type == Double.TYPE) return Double.valueOf(0);
        if (type == Character.TYPE) return Character.valueOf((char)0);
        return null;
    }

    public Object invoke(Object proxy, Method method, Object[] args) {
        if (method.getName().equals("setOpacity")) {
            writes.add(new int[] { ((Integer)args[0]).intValue(),
                ((Integer)args[1]).intValue(), ((Integer)args[2]).intValue() });
        }
        return defaultValue(method.getReturnType());
    }

    private void verifyWrites(int visibleBacking, int expectedBacking, int expectedKdk,
                              String scenario) {
        int sportWrites = 0, popupWrites = 0, kdkWrites = 0;
        for (int i = 0; i < writes.size(); i++) {
            int[] write = (int[])writes.get(i);
            check(write[1] == 1, scenario + ": wrong terminal");
            if (write[0] == 101 || write[0] == 102) {
                int expected = write[0] == visibleBacking ? expectedBacking : 0;
                check(write[2] == expected, scenario + ": transient backing "
                    + write[0] + " opacity=" + write[2] + ", expected=" + expected);
                if (write[0] == 101) sportWrites++; else popupWrites++;
            } else {
                check(write[0] == 20 && write[2] == expectedKdk,
                    scenario + ": stock maneuver opacity changed");
                kdkWrites++;
            }
        }
        check(sportWrites == 1 && popupWrites == 1 && kdkWrites == 1,
            scenario + ": missing or duplicate layer writes");
    }

    private static void screenField(String name, boolean value) throws Exception {
        Field field = ScreenModule.class.getDeclaredField(name);
        field.setAccessible(true); field.setBoolean(null, value);
    }

    private static void initializeWidgetLogs() throws Exception {
        Constructor ctor = Class.forName("com.luka.carplay.rgd.BAPBridge$SilentLogChannel")
            .getDeclaredConstructor();
        ctor.setAccessible(true);
        final Object log = ctor.newInstance();
        // IWidgetLogChannel initializes its channels from this stock static field.
        // Populate it before the first access to CombiMapController.logKDK.
        Field framework = AbstractWidget.class.getDeclaredField("framework");
        framework.setAccessible(true);
        framework.set(null, Proxy.newProxyInstance(ClusterKdkBackingTest.class.getClassLoader(),
            new Class[] { framework.getType() }, new InvocationHandler() {
                public Object invoke(Object proxy, Method method, Object[] args) {
                    if (method.getName().equals("getLogChannel")) return log;
                    return defaultValue(method.getReturnType());
                }
            }));
    }

    public static void main(String[] args) throws Exception {
        Log.setLevel(-1);
        initializeWidgetLogs();
        Field unsafeField = Unsafe.class.getDeclaredField("theUnsafe");
        unsafeField.setAccessible(true);
        Unsafe unsafe = (Unsafe)unsafeField.get(null);
        CombiMapController controller = (CombiMapController)unsafe.allocateInstance(CombiMapController.class);
        controller.setKombiTerminal(1);
        Method apply = CombiMapController.class.getDeclaredMethod("applyKdkDualTerminal",
            new Class[] { IDisplayManagerKombiControl.class, Integer.TYPE,
                ModelUpdateEvent.class, Layout.class, Boolean.TYPE });
        apply.setAccessible(true);
        Field opacity = CombiMapController.class.getDeclaredField("kdkOpacity");
        opacity.setAccessible(true);
        ClusterKdkBackingTest capture = new ClusterKdkBackingTest();
        IDisplayManagerKombiControl dm = (IDisplayManagerKombiControl)Proxy.newProxyInstance(
            ClusterKdkBackingTest.class.getClassLoader(),
            new Class[] { IDisplayManagerKombiControl.class }, capture);
        ModelUpdateEvent event = new ModelUpdateEvent((ATIPEventListener)null, 0);
        Layout[] layouts = { new LayoutMIB2HighB9(), new LayoutMIB2HighB9Sport() };
        screenField("platformSupported", true);

        for (int l = 0; l < layouts.length; l++) {
            for (int stage = 0; stage < 2; stage++) {
                boolean inTube = stage == 1;
                int backing = inTube ? 101 : 102;
                String scenario = layouts[l].getClass().getName() + (inTube ? " inTube" : " popup");
                // Include reconnect: an already visible OEM backing must be suppressed
                // immediately, without waiting for ClusterLayerController.reapply().
                for (int pass = 0; pass < 3; pass++) {
                    boolean connected = pass != 1;
                    screenField("connected", connected);
                    // Test both fade states, ending visible so reconnect follows
                    // a real nonzero stock backing write.
                    for (int fade = 0; fade < 2; fade++) {
                        int stockOpacity = fade == 0 ? 0 : 100;
                        event.setHints(stockOpacity == 100 ? NaviMoKoKDKConstants.BITFIELD_KDK_FADED_IN : 0);
                        capture.writes.clear();
                        apply.invoke(controller, new Object[] { dm, Integer.valueOf(20), event,
                            layouts[l], Boolean.valueOf(inTube) });
                        String step = scenario + " connected=" + connected + " stock=" + stockOpacity;
                        capture.verifyWrites(backing, connected ? 0 : stockOpacity, stockOpacity, step);
                        check(opacity.getInt(controller) == stockOpacity,
                            step + ": original kdkOpacity cache was overwritten");
                    }
                }
            }
        }
        screenField("connected", false);
        System.out.println("ClusterKdkBackingTest: real CN Classic/Sport popup/inTube, every backing write transparent, stock cache/fade/disconnect/reconnect PASS");
    }
}
